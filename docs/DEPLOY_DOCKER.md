# GraphRAG 一键 Docker 部署指南

> 适用场景：在一台只装了 Docker 的机器上，**仅通过一个 `.env` 文件** 就拉起整个 GraphRAG 项目（App + Neo4j + Postgres + 流体属性微服务）。底层与仓库 `make docker-run` 完全一致，使用官方发布镜像 `docker-compose.image.yaml`，无需本地构建。

---

## 1. 核心思路

`make docker-run` 实际执行的是：

```bash
docker compose -f docker-compose.image.yaml pull
docker compose -f docker-compose.image.yaml up -d
```

所以只要部署机上：

1. 有 `.env` 文件（填好 LLM Key）
2. 有仓库里的 `docker-compose.image.yaml`
3. 装了 `docker` + `docker compose`

就可以一条命令拉起全栈。本文档就是把这个过程包装成「最小可复现步骤」，不依赖 Python / make / 源码仓库本体。

---

## 2. 前置要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux / macOS / Windows (WSL2) |
| Docker Engine | ≥ 24.0 |
| Docker Compose | v2（自带 `docker compose` 子命令） |
| 内存 | ≥ 8 GB（Neo4j 堆 4G + App 推理 ~2G） |
| 磁盘 | ≥ 10 GB |
| 网络 | 首次需拉取镜像 & 调用 LLM API |

放行端口（宿主机）：`8000`（API）、`8501`（Chat UI）、`8502`（Admin UI）、`7474/7687`（Neo4j）、`5432`（Postgres）。

---

## 3. 部署目录结构

选一个空目录（以下记作 `~/graphrag-deploy`），最终只需两个文件：

```
graphrag-deploy/
├── .env                       # 配置（见第 4 节）
└── docker-compose.image.yaml  # 编排（见第 5 节，直接复制）
```

启动后 Docker 会自动在该目录旁生成持久化挂载目录：

```
├── cache/        # 嵌入/结果缓存
├── files/        # 用户上传文件
├── runtime/      # 构建日志、图快照
├── datasets/     # 数据集（可选）
└── documents/    # 文档语料（可选）
```

> ⚠️ **强烈建议启动前先手动创建这些目录**（否则容器会报 `PermissionError: cache/huggingface`，见 FAQ Q5）：
> ```bash
> cd ~/graphrag-deploy
> mkdir -p cache files runtime datasets documents
> ```
> 原因：容器内应用以 `appuser` (UID=1000) 运行，若目录不存在，Docker 守护进程会以 root 身份自动创建，导致 `appuser` 无写权限，后端 FastAPI 启动时直接崩溃。手动创建则属主为当前宿主机用户（通常也是 UID=1000），权限一致。

---

## 4. 准备 `.env`

最小可运行配置（复制保存为 `.env`，替换 Key 即可）：

```dotenv
# === Chat 模型（必填）===
CHAT_API_KEY=sk-your-chat-key
CHAT_BASE_URL=https://api.deepseek.com/v1
CHAT_MODEL=deepseek-chat

# === Embedding 模型（必填）===
EMBEDDING_API_KEY=sk-your-embedding-key
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3

# === OpenAI 兼容兜底（可选）===
OPENAI_API_KEY=sk-your-fallback-key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_LLM_MODEL=qwen3-max

...
```

> 💡 更多可调参数（GDS、检索、多智能体、缓存等）可直接从仓库 `.env.example` 拷贝后按需修改。
> ⚠️ **不要在 `.env` 里写 `NEO4J_URI` 或 `GRAPH_ADMIN_METADATA_DSN`**——compose 会用容器内服务名强制覆盖，写了反而冲突。

---

## 5. 获取 `docker-compose.image.yaml`

将下述内容保存为部署目录下的 `docker-compose.image.yaml`（内容与仓库根目录同名文件一致）：

```yaml
services:
  app:
    image: ${GRAPH_RAG_IMAGE:-ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU}
    container_name: graph-rag-app
    env_file:
      - .env
    ...
```

> 如果要从私有镜像仓库拉取，在 `.env` 增加一行：
> `GRAPH_RAG_IMAGE=your-registry.example.com/graph-rag-app:v1.0.0`

---

## 6. 一键启动（等价于 `make docker-run`）

在部署目录执行：

```bash
# 拉镜像
docker compose -f docker-compose.image.yaml pull

# 一键拉起全栈（后台运行）
docker compose -f docker-compose.image.yaml up -d

# 查看状态
docker compose -f docker-compose.image.yaml ps
```

> 💡 如果嫌 `-f docker-compose.image.yaml` 太长，把文件重命名为默认的 `docker-compose.yaml` 即可省略 `-f` 参数：
> ```bash
> mv docker-compose.image.yaml docker-compose.yaml
> docker compose up -d
> ```

启动就绪判断（app 容器变为 `healthy` 即可）：

```bash
docker compose -f docker-compose.image.yaml ps app
# STATUS 列出现 (healthy) 表示全部就绪
```

---

## 7. 访问入口

| 服务 | 地址 | 用途 |
|------|------|------|
| Chat 前端 | http://localhost:8501 | 用户问答主界面 |
| Admin 控制台 | http://localhost:8502 | 数据集管理 / 图构建 / 快照 |
| FastAPI Swagger | http://localhost:8000/docs | 后端 API 调试 |
| Neo4j Browser | http://localhost:7474 | 图数据库浏览（登录：`neo4j` / `12345678`） |

---

## 8. 常用运维命令

```bash
COMPOSE="docker compose -f docker-compose.image.yaml"

# 查看应用日志
$COMPOSE logs -f app

# 停止服务（保留数据卷）
$COMPOSE down

# 停止并清除所有数据（⚠️ 会清空 Neo4j / Postgres 持久化）
$COMPOSE down -v

# 只重启 app（改完 .env 后）
$COMPOSE up -d --force-recreate app fluid-property-service

# 升级 app 镜像，保留数据
$COMPOSE pull app && $COMPOSE up -d app

# 进入 app 容器
$COMPOSE exec app bash

# 在容器里重建图索引
$COMPOSE exec app python -m graphrag_agent.integrations.build.main --help
```

---

## 9. FAQ

**Q1. app 一直 `unhealthy`？**
```bash
docker compose -f docker-compose.image.yaml logs --tail=200 app
```
常见原因：LLM Key 错误、端口被占、Neo4j 初始化慢（等 60s 内的 `start_period`）。

**Q2. 改了 `.env` 没生效？**
`env_file` 只在容器启动时读取，需 `--force-recreate`：
```bash
docker compose -f docker-compose.image.yaml up -d --force-recreate app fluid-property-service
```

**Q3. 想换 Neo4j 密码？**
同时改 compose 中 `NEO4J_AUTH: "neo4j/<新>"` 和 `.env` 中 `NEO4J_PASSWORD=<新>`，然后 `down -v` 重启（会清库）。

**Q4. 能不能真的只跑一个容器？**
App 镜像里不包含 Neo4j/Postgres。若要「真·单容器」，需要用外部已有的 Neo4j + Postgres：
```bash
docker run -d --name graph-rag-app \
  --env-file .env \
  -e NEO4J_URI=neo4j://<your-neo4j-host>:7687 \
  -e GRAPH_ADMIN_METADATA_DSN=postgresql://postgres:postgres@<your-pg-host>:5432/graphrag_admin \
  -p 8000:8000 -p 8501:8501 -p 8502:8502 \
  -v "$(pwd)/cache:/app/cache" \
  -v "$(pwd)/files:/app/files" \
  -v "$(pwd)/runtime:/app/runtime" \
  ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
```
生产场景仍强烈建议用 compose 整栈，保证依赖隔离与版本一致。

---

**Q5. Streamlit 前端能打开，但 Admin 后台报 `Connection refused: 127.0.0.1:8000/admin/health`？**

**前台页面起来 ≠ 后端存活**。Streamlit UI (8501/8502) 和 FastAPI 后端 (8000) 是独立进程，后端崩了前台还能开，但所有需要调后端的功能都会报 `Connection refused`。

**最常见根因：宿主机挂载目录权限问题**（Docker bind mount 经典陷阱）。

**排查三步**：
```bash
# 1. 看后端是否真的崩了
docker compose -f docker-compose.image.yaml logs --tail=100 app | grep -E "Error|Permission"

# 2. 对比容器里的用户 UID 和宿主机目录属主
docker exec graph-rag-app id                    # 通常是 uid=1000(appuser)
ls -ld ./cache ./files ./runtime                 # 如果显示 root root 就是问题所在

# 3. 健康检查细节
docker inspect graph-rag-app --format '{{json .State.Health}}' | python3 -m json.tool
```

如果日志里出现 `PermissionError: [Errno 13] Permission denied: 'cache/...'`，用下面两选一修复：

**方案 A（推荐，一次性修）**：修正目录属主为 UID=1000（容器里的 `appuser`）
```bash
sudo chown -R 1000:1000 ./cache ./files ./runtime ./datasets ./documents
docker compose -f docker-compose.image.yaml restart app
```

**方案 B（一劳永逸）**：部署前先手动建目录（见第 3 节的前置提示），让目录从一开始就归当前用户所有，不需要 sudo。

> 为什么会发生？如果这些目录在 `docker compose up` 时不存在，Docker daemon 会以 **root 身份** 自动创建它们；而容器内的 `appuser` (UID=1000) 对 root 所有的目录只有只读权限，于是 `HF_HOME.mkdir()` 之类的写操作直接抛 `PermissionError`，Python 进程退出，FastAPI 端口再也不会 listen。

---

## 10. 快速核对清单

- [ ] 目录下有 `.env` 和 `docker-compose.image.yaml`
- [ ] 已手动 `mkdir -p cache files runtime datasets documents`（避免权限踩坑）
- [ ] `.env` 中 `CHAT_*` / `EMBEDDING_*` 已填真实 Key
- [ ] `8000 / 8501 / 8502 / 7474 / 7687 / 5432` 端口未被占用
- [ ] `docker compose -f docker-compose.image.yaml up -d` 后 `ps` 全部 running/healthy
- [ ] http://localhost:8501 能正常问答
- [ ] http://localhost:8502 能打开 Admin
- [ ] http://localhost:8000/docs 能看到 Swagger

通过即部署成功。
