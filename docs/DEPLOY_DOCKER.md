# GraphRAG Docker 快速部署指南

> 适用场景：在一台已安装 Docker 的机器上，仅通过一个 `.env` 文件 + 一个 `docker-compose.yaml`（或直接用 `docker run`）即可拉起完整的 GraphRAG 服务栈（FastAPI + Chat UI + Admin UI + Neo4j + Postgres + 流体属性微服务）。

---

## 1. 前置要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux / macOS / Windows (WSL2) |
| Docker Engine | ≥ 24.0 |
| Docker Compose | v2（`docker compose` 子命令） |
| 可用内存 | ≥ 8 GB（Neo4j 堆 + App 推理） |
| 可用磁盘 | ≥ 10 GB（镜像 + 图数据卷） |
| 可访问外网 | 首次需要拉取镜像及调用 LLM API |

开放端口（宿主机 → 容器）：

- `8000` FastAPI 后端 API
- `8501` Chat 前端（Streamlit）
- `8502` Admin 控制台（Streamlit）
- `7474` Neo4j Browser
- `7687` Neo4j Bolt
- `5432` Postgres（admin 元数据）

---

## 2. 部署目录结构

在任意空目录（以下示例为 `~/graphrag-deploy`）下准备如下两个文件即可：

```
graphrag-deploy/
├── .env                  # 配置（必填，参考第 3 节）
└── docker-compose.yaml   # 编排（直接使用第 4 节模板）
```

首次启动后，Docker 会自动在该目录旁创建如下挂载目录（用于持久化）：

```
graphrag-deploy/
├── cache/        # 嵌入/结果缓存
├── files/        # 用户上传文件
├── runtime/      # 构建日志、图快照
├── datasets/     # 原始数据集（只读）
├── documents/    # 文档语料（只读）
```

---

## 3. 准备 `.env` 文件

在部署目录创建 `.env`，最小可运行配置如下（仅需替换 **Chat / Embedding 的 Key 与 Base URL**）：

```dotenv
# === Chat 模型（必填）===
CHAT_API_KEY=sk-your-chat-key
CHAT_BASE_URL=https://api.deepseek.com/v1
CHAT_MODEL=deepseek-chat

# === Embedding 模型（必填）===
EMBEDDING_API_KEY=sk-your-embedding-key
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3

# === OpenAI 兼容兜底（可选，Chat/Embedding 未配时回退）===
OPENAI_API_KEY=sk-your-fallback-key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_LLM_MODEL=qwen3-max

# === 服务并发 ===
SERVER_WORKERS=1
FASTAPI_WORKERS=2
TEMPERATURE=0
MAX_TOKENS=2000

# === Admin / 前端 ===
GRAPH_ADMIN_ENABLED=true
FRONTEND_DEFAULT_AGENT=naive_rag_agent
FRONTEND_USE_STREAM=true

# === Neo4j（保持与 compose 中服务一致即可）===
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=12345678
```

> 💡 其余参数（GDS、缓存、检索、多智能体等）如需调优，可从仓库内 `.env.example` 完整拷贝后按需修改。容器启动时会通过 `env_file: .env` 直接加载。

> ⚠️ `NEO4J_URI` 与 `GRAPH_ADMIN_METADATA_DSN` **无需在 `.env` 里写**，compose 会强制覆盖为容器内部服务名（`neo4j://neo4j:7687` / `postgresql://postgres:postgres@postgres:5432/graphrag_admin`），避免 `localhost` 语义冲突。

---

## 4. `docker-compose.yaml` 模板

将下述内容保存为部署目录下的 `docker-compose.yaml`（直接复用仓库发布镜像，无需本地构建）：

```yaml
services:
  app:
    image: ${GRAPH_RAG_IMAGE:-ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU}
    container_name: graph-rag-app
    env_file:
      - .env
    environment:
      # 容器网络内统一走服务名，避免使用宿主机 localhost
      NEO4J_URI: neo4j://neo4j:7687
      GRAPH_ADMIN_METADATA_DSN: postgresql://postgres:postgres@postgres:5432/graphrag_admin
      FRONTEND_API_URL: http://127.0.0.1:8000
      ADMIN_FRONTEND_API_URL: http://127.0.0.1:8000
      MCP_TOOL_ENDPOINTS: http://fluid-property-service:8010
      FLUID_PROPERTY_SERVICE_URL: http://fluid-property-service:8010
      SERVER_HOST: 0.0.0.0
      SERVER_PORT: 8000
      SERVER_WORKERS: ${SERVER_WORKERS:-1}
      FASTAPI_WORKERS: ${FASTAPI_WORKERS:-2}
    ports:
      - "8000:8000"   # FastAPI
      - "8501:8501"   # Chat UI
      - "8502:8502"   # Admin UI
    volumes:
      - ./cache:/app/cache
      - ./files:/app/files
      - ./runtime:/app/runtime
      - ./datasets:/app/datasets
      - ./documents:/app/documents
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_started
      fluid-property-service:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "/app/docker/app/healthcheck.py"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
    restart: unless-stopped

  fluid-property-service:
    image: ${GRAPH_RAG_IMAGE:-ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU}
    container_name: graph-rag-fluid-property-service
    env_file:
      - .env
    environment:
      PYTHONPATH: /app:/app/server:/app/frontend
    command:
      - python
      - -m
      - uvicorn
      - tool_services.fluid_property_service.app:app
      - --host
      - 0.0.0.0
      - --port
      - "8010"
    expose:
      - "8010"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8010/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 15s
    restart: unless-stopped

  postgres:
    image: postgres:16
    container_name: graph-rag-postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: graphrag_admin
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      TZ: UTC
      PGTZ: UTC
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d graphrag_admin"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  neo4j:
    image: neo4j:5.22.0
    container_name: graph-rag-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: "neo4j/12345678"
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
      NEO4J_dbms_security_procedures_unrestricted: "apoc.*,gds.*"
      NEO4J_dbms_memory_heap_initial__size: "2G"
      NEO4J_dbms_memory_heap_max__size: "2G"
      NEO4J_dbms_memory_pagecache_size: "1G"
      NEO4J_apoc_trigger_enabled: "true"
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
      - neo4j_plugins:/plugins
    restart: unless-stopped

volumes:
  neo4j_data:
  neo4j_logs:
  neo4j_plugins:
  postgres_data:
```

> 如果需要替换为私有镜像仓库，仅需在 `.env` 中加一行：
> `GRAPH_RAG_IMAGE=your-registry.example.com/graph-rag-app:v1.0.0`

---

## 5. 启动与停止

在部署目录（包含 `.env` 和 `docker-compose.yaml`）执行：

```bash
# 启动（首次会自动拉取镜像，需要几分钟）
docker compose up -d

# 查看服务状态
docker compose ps

# 查看应用日志（Ctrl+C 退出，但不停止服务）
docker compose logs -f app

# 停止并保留数据卷
docker compose down

# 停止并清除所有数据（⚠️ 会清空 Neo4j / Postgres 的持久化数据）
docker compose down -v
```

启动就绪判断：

```bash
# 等待 app 容器变为 healthy
docker compose ps app
# STATUS 列出现 (healthy) 即可
```

---

## 6. 访问入口

运行"一键拉起全栈"命令后，**等待一段时间**后 web 服务会被拉取，访问以下网址：
| 服务 | 地址 | 用途 |
|------|------|------|
| Chat 前端 | http://localhost:8501 | 用户问答主界面 |
| Admin 控制台 | http://localhost:8502 | 数据集管理、图构建、快照 |
| FastAPI Swagger | http://localhost:8000/docs | 后端 API 调试 |
| Neo4j Browser | http://localhost:7474 | 图数据库浏览（登录：neo4j / 12345678） |

---

## 7. 单容器快速验证（无 compose）

如果只想快速验证 App 镜像是否可用（依赖需自备或指向外部 Neo4j/Postgres），可在含 `.env` 的目录执行：

```bash
docker run -d --name graph-rag-app \
  --env-file .env \
  -e NEO4J_URI=neo4j://host.docker.internal:7687 \
  -e GRAPH_ADMIN_METADATA_DSN=postgresql://postgres:postgres@host.docker.internal:5432/graphrag_admin \
  -p 8000:8000 -p 8501:8501 -p 8502:8502 \
  -v "$(pwd)/cache:/app/cache" \
  -v "$(pwd)/files:/app/files" \
  -v "$(pwd)/runtime:/app/runtime" \
  ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
```

> 适用于「已有外部 Neo4j + Postgres」的场景，生产仍建议使用 compose 编排整栈。

---

## 8. 常见问题（FAQ）

**Q1. 容器启动后 `app` 一直 `unhealthy`？**
查看日志定位阶段：
```bash
docker compose logs --tail=200 app
```
常见原因：
- LLM API Key / Base URL 配置错误（检查 `.env` 中 `CHAT_*` / `EMBEDDING_*`）
- Neo4j 尚未就绪，等 60s 后 `start_period` 结束会重试
- 端口 8000/8501/8502 被宿主机占用

**Q2. 如何重新构建图索引？**
进入 app 容器执行构建 CLI：
```bash
docker compose exec app \
  python -m graphrag_agent.integrations.build.main --help
```

**Q3. 如何只升级镜像保留数据？**
```bash
docker compose pull app
docker compose up -d app
```
`cache/`、`files/`、`runtime/` 及 `neo4j_data` / `postgres_data` 卷会保留。

**Q4. 修改 `.env` 后是否需要重启？**
需要。`env_file` 只在容器启动时读取：
```bash
docker compose up -d --force-recreate app fluid-property-service
```

**Q5. Neo4j 密码想换怎么办？**
同时修改以下两处并 `docker compose down -v`（会清库）后重启：
- compose 中 `NEO4J_AUTH: "neo4j/<新密码>"`
- `.env` 中 `NEO4J_PASSWORD=<新密码>`

---

## 9. 生产加固建议（可选）

1. **密钥管理**：`.env` 严禁入库；在 CI/CD 或 Secret Manager 中注入。
2. **反向代理**：前置 Nginx / Caddy，统一 HTTPS、限流与鉴权；不要把 8501 / 8502 / 7474 直接暴露到公网。
3. **资源限制**：在每个 service 下加 `deploy.resources.limits`（memory / cpus），防止 Neo4j GDS 计算挤占。
4. **备份策略**：定期 `neo4j-admin database dump` 并同步 `postgres_data` 卷；`runtime/admin/snapshots` 也纳入备份。
5. **监控**：接入 Langfuse（见 `.env` 中 `LANGFUSE_*`）跟踪 LLM 调用与成本；Prometheus 抓 `/metrics`（如后续启用）。
6. **镜像版本固化**：避免使用 `:latest`，在 `.env` 固定 `GRAPH_RAG_IMAGE=...:<commit-sha>`。

---

## 10. 快速核对清单

- [ ] `.env` 中 `CHAT_*` / `EMBEDDING_*` 已填真实 Key
- [ ] 8000 / 8501 / 8502 / 7474 / 7687 / 5432 端口未被占用
- [ ] `docker compose up -d` 后 `docker compose ps` 全部 `running/healthy`
- [ ] 打开 http://localhost:8501 能进行一轮问答
- [ ] 打开 http://localhost:8502 能看到 Admin 控制台
- [ ] http://localhost:8000/docs 可访问 Swagger

全部通过即代表部署成功，可开始导入数据并构建图索引。
