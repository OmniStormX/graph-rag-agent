# Graph RAG

面向工程热力学场景的 GraphRAG 问答与知识图谱系统。项目包含图谱构建链路、FastAPI 后端、Streamlit 前端、后台管理能力，以及围绕热工问题补充的流体物性计算工具。

当前仓库的目标不是通用演示工程，而是一个可本地运行、可增量构建、可做问答联调与图谱治理的完整开发项目。

## 项目定位

- 面向工程热力学语料构建知识图谱
- 支持 GraphRAG、Hybrid RAG、Deep Research 与 Fusion 多种问答模式
- 支持图谱版本管理、增量构建、文档上传与后台治理
- 支持热力学状态点定量计算，如 `T/P/H/S/D/Q` 组合反演

## 当前能力

### 1. 图谱构建

- 文档解析、切分、实体关系抽取
- Neo4j 图写入、实体索引、文本块索引
- 社区检测与社区摘要
- 全量构建与增量更新

### 2. 问答能力

- `graph_agent`：图谱局部/全局检索
- `hybrid_agent`：图谱 + 向量混合检索
- `naive_rag_agent`：基础向量检索
- `deep_research_agent`：多轮研究与推理
- `fusion_agent`：Plan-Execute-Report 多智能体协作

### 3. 后台治理

- 文档上传与 revision 管理
- 构建任务查看
- 图谱版本激活与回滚
- 图谱快照查看
- 修正规则维护

### 4. 热工工具

- `fluid_property_calc` 支持流体物性计算
- 当前支持工质别名包括 `Water`、`steam`、`H2O`、`水`、`水蒸气`、`蒸汽`、`Air`、`R134a`、`Ammonia`、`CO2`
- 支持状态量 `T`、`P`、`H`、`S`、`D`、`Q`
- 已支持通过 MCP 风格 HTTP 目录把外部计算工具自动接入 Agent 工具集

## 目录结构

```text
graph-RAG/
├── graphrag_agent/         # 核心包
│   ├── agents/             # 各类 Agent 与多智能体编排
│   ├── graph/              # 图谱抽取、处理、索引
│   ├── integrations/build/ # 全量/增量构建入口
│   ├── search/             # 检索与工具层
│   ├── cache_manager/      # 缓存管理
│   ├── community/          # 社区检测与摘要
│   ├── config/             # 配置与提示词
│   └── evaluation/         # 评估与实验脚本
├── server/                 # FastAPI 后端
├── frontend/               # Streamlit 前端与后台前端
├── test/                   # unittest 与联调脚本
├── assets/                 # 启动与后台说明
├── datasets/               # 原始数据集
├── pdf/                    # PDF 示例与处理中间文件
├── files/                  # 运行期文件
├── cache/                  # 缓存产物
└── runtime/                # 后台运行时目录
```

## 环境要求

- Python `3.10+`
- Neo4j `5.x`
- PostgreSQL `16`（后台管理需要）
- 可用的 OpenAI 兼容 LLM / Embedding 接口

如需处理 `.doc`、`.pdf` 等文件，请按 [requirements.txt](/home/omnistorm/桌面/code/project/graph-RAG/requirements.txt:1) 中注释安装系统依赖。

## 快速开始

### 1. 创建环境并安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果你需要本地 NLP/向量模型能力（如 HanLP、本地 SentenceTransformer，通常会间接安装 `torch`），再额外执行：

```bash
pip install -r requirements.local_nlp.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，至少确认以下配置：

```env
OPENAI_API_KEY='sk-xxx'
OPENAI_BASE_URL='http://localhost:13000/v1'
OPENAI_LLM_MODEL='gpt-4o'

EMBEDDING_MODEL='text-embedding-v4'

NEO4J_URI='neo4j://localhost:7687'
NEO4J_USERNAME='neo4j'
NEO4J_PASSWORD='12345678'
```

如需后台管理，还需要：

```env
GRAPH_ADMIN_ENABLED=true
GRAPH_ADMIN_METADATA_DSN='postgresql://postgres:postgres@localhost:5432/graphrag_admin'
```

完整可选项请参考 [.env.example](/home/omnistorm/桌面/code/project/graph-RAG/.env.example:1)。

### 3. 启动依赖服务

```bash
docker compose up -d postgres neo4j
```

如果你需要本地可观测性，也可以直接启动全部服务：

```bash
docker compose up -d
```

### 4. 本地构建 Docker 镜像并启动

如果你希望把当前项目应用层完整封装到一个镜像里，可以直接构建并启动 `app` 服务。该镜像会在单容器内同时拉起：

- FastAPI 后端：`8000`
- Streamlit 聊天前端：`8501`
- Streamlit 管理后台：`8502`

启动前请先准备 `.env`，并确认其中的 LLM、Embedding 等外部依赖可用。

```bash
docker compose up -d --build app
```

推荐直接拉起整套栈：

```bash
docker compose up -d --build
```

启动后访问：

- 聊天前端：`http://localhost:8501`
- 管理后台：`http://localhost:8502`
- 后端 OpenAPI：`http://localhost:8000/docs`
- Neo4j Browser：`http://localhost:7474`

如果需要可观测性栈（Langfuse），再显式启用对应 profile：

```bash
docker compose --profile observability up -d
```

### 5. 直接拉取 Docker 镜像运行

项目应用层会发布为一个 Docker 镜像，镜像内包含：

- FastAPI 后端
- Streamlit 聊天前端
- Streamlit 管理后台
- 内置的流体物性工具服务代码

当前 `graphRAG-CSU` 分支的默认发布地址：

```text
ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
```

使用者只需要拉取这一份项目镜像：

```bash
docker pull ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
```

说明：`latest` 只会在默认分支发布成功后生成；当前分支请使用 `graphRAG-CSU` 或某次提交对应的 `sha-xxxxxxx`。

如果镜像仓库是私有的，先登录 GHCR：

```bash
echo <YOUR_GITHUB_TOKEN> | docker login ghcr.io -u <YOUR_GITHUB_USERNAME> --password-stdin
```

#### 5.1 推荐方式：镜像 + Docker 编排依赖

GraphRAG 运行时仍依赖 Neo4j 和 PostgreSQL。行业内不建议把数据库塞进同一个业务镜像；更稳定的做法是“一个项目镜像 + 数据库容器 + 持久化卷”。仓库提供了 `docker-compose.image.yaml`，它不会构建本地代码，只会使用已发布镜像。

准备 `.env` 后执行：

```bash
docker compose -f docker-compose.image.yaml up -d
```

如需固定版本或使用私有镜像地址，可以覆盖 `GRAPH_RAG_IMAGE`：

```bash
GRAPH_RAG_IMAGE=ghcr.io/omnistormx/graph-rag-app:sha-xxxxxxx \
  docker compose -f docker-compose.image.yaml up -d
```

启动后访问：

- 聊天前端：`http://localhost:8501`
- 管理后台：`http://localhost:8502`
- 后端 OpenAPI：`http://localhost:8000/docs`
- Neo4j Browser：`http://localhost:7474`

#### 5.2 仅运行项目应用容器

如果 Neo4j、PostgreSQL、MCP 工具服务已经在其他位置运行，可以只启动项目应用容器。此时 `.env` 中必须配置可达的 `NEO4J_URI`、`GRAPH_ADMIN_METADATA_DSN`、`MCP_TOOL_ENDPOINTS` 等地址。

```bash
docker run -d \
  --name graph-rag-app \
  --env-file .env \
  -p 8000:8000 \
  -p 8501:8501 \
  -p 8502:8502 \
  -v $(pwd)/cache:/app/cache \
  -v $(pwd)/files:/app/files \
  -v $(pwd)/runtime:/app/runtime \
  -v $(pwd)/datasets:/app/datasets \
  -v $(pwd)/documents:/app/documents \
  ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
```

注意：单独 `docker run` 不会自动启动 Neo4j、PostgreSQL 和流体工具服务，适合已有外部依赖的部署环境。

### 6. Docker 开发模式

如果你是在本地频繁改代码，建议使用开发态 compose，直接挂载源码，避免每次都重建镜像：

```bash
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml up -d app
```

这种模式下：

- Python 代码修改后只需要重启容器内进程或重新启动服务
- 默认不会拉起 Langfuse，减少额外容器开销
- 依赖层缓存稳定后，后续联调明显更快

### 7. 启动后端与前端

```bash
uvicorn server.main:app --reload
streamlit run frontend/app.py
```

或使用 Makefile：

```bash
make start-backend
make start-frontend
```

### 8. 启动后台管理界面

```bash
make start-admin-backend
make start-admin-frontend
```

## 自制 MCP 工具接入流程

当前项目已经支持一种轻量的 MCP 风格工具接入机制。核心思想是：

- 外部工具服务只需要暴露工具描述和调用接口
- 主项目启动后会自动读取工具目录
- Agent 会把这些工具自动加入 `Tools`，无需再手工改每个 Agent 的 `_setup_tools`

这套机制适合把热力计算、物性查询、经验公式计算、设备选型校核这类“独立、定量、可服务化”的能力拆出去。

### 1. 接口协议

你的工具服务至少需要提供两个 HTTP 接口：

```text
GET  /tools
POST /tools/{tool_name}/invoke
```

其中 `GET /tools` 返回工具目录，最小返回格式如下：

```json
{
  "tools": [
    {
      "name": "my_custom_calc",
      "description": "这是一个自定义计算工具，用于根据输入参数执行定量计算。",
      "input_schema": {
        "type": "object",
        "properties": {
          "x": {
            "type": "number",
            "description": "输入参数 x"
          },
          "y": {
            "type": "number",
            "description": "输入参数 y"
          }
        },
        "required": ["x", "y"]
      },
      "invoke_path": "/tools/my_custom_calc/invoke",
      "tags": ["calculation", "custom"]
    }
  ]
}
```

`POST /tools/my_custom_calc/invoke` 的返回建议兼容项目当前工具层协议：

```json
{
  "success": true,
  "answer": "计算成功: z=42.0",
  "results": {
    "z": 42.0
  },
  "metadata": {
    "notes": []
  },
  "error": null,
  "retrieval_results": []
}
```

### 2. 项目如何自动发现工具

主项目通过以下环境变量发现外部工具服务：

```env
MCP_TOOL_ENDPOINTS='http://127.0.0.1:8010,http://127.0.0.1:8020'
```

或：

```env
MCP_TOOL_ENDPOINTS='["http://127.0.0.1:8010","http://127.0.0.1:8020"]'
```

如果你接的是流体物性独立服务，也可以单独配置：

```env
FLUID_PROPERTY_SERVICE_URL='http://127.0.0.1:8010'
``` 

当前实现位置：

- MCP 发现入口：[graphrag_agent/mcp/discovery.py](/home/omnistorm/桌面/code/project/graph-RAG/graphrag_agent/mcp/discovery.py:1)
- MCP 适配层：[graphrag_agent/mcp/adapter.py](/home/omnistorm/桌面/code/project/graph-RAG/graphrag_agent/mcp/adapter.py:1)
- 工具统一注册入口：[graphrag_agent/search/tool_registry.py](/home/omnistorm/桌面/code/project/graph-RAG/graphrag_agent/search/tool_registry.py:1)

### 3. 最小实现示例

你可以参考当前已经拆出去的流体物性服务：

- 服务入口：[tool_services/fluid_property_service/app.py](/home/omnistorm/桌面/code/project/graph-RAG/tool_services/fluid_property_service/app.py:1)
- 计算核心：[tool_services/fluid_property_service/core.py](/home/omnistorm/桌面/code/project/graph-RAG/tool_services/fluid_property_service/core.py:1)

启动方式：

```bash
uvicorn tool_services.fluid_property_service.app:app --host 0.0.0.0 --port 8010
```

然后在主项目 `.env` 中加入：

```env
MCP_TOOL_ENDPOINTS='http://127.0.0.1:8010'
FLUID_PROPERTY_SERVICE_URL='http://127.0.0.1:8010'
```

此时主项目内的 Agent 会自动发现 `fluid_property_calc`，并加入工具集。

### 4. 自己新增一个工具的推荐步骤

1. 在独立目录下实现一个 FastAPI 服务，建议放在 `tool_services/<your_service>/`
2. 定义 `GET /tools`，准确描述工具名称、用途和 `input_schema`
3. 定义 `POST /tools/<tool_name>/invoke`，返回统一结构
4. 先用 `curl` 或 Postman 验证该服务可独立调用
5. 把服务地址写入 `.env` 的 `MCP_TOOL_ENDPOINTS`
6. 重启主项目后端，让 Agent 重新发现工具
7. 增加 `unittest`，至少覆盖目录接口和调用接口

### 5. Agent 自动装配的边界

当前自动装配依赖两个关键字段：

- `name`：工具唯一名称，供模型函数调用时引用
- `description`：工具用途说明，供模型判断是否应调用该工具

`input_schema` 会被适配成 LangChain 工具参数模型，因此建议：

- 字段名简洁稳定，避免频繁变更
- `description` 写清单位、取值范围、必填条件
- 对定量工具明确说明输入输出的工程语义

如果工具返回结构化结果，建议至少包含：

- `success`
- `answer`
- `results`
- `metadata`
- `error`

这样可以同时兼容普通 Agent 调用和多智能体执行器调用。

### 6. 工程建议

- 高耗时计算工具优先独立服务化，不要直接塞进主进程
- 工具服务要做到无状态，便于后续 Docker 化和 Kubernetes 横向扩容
- 输入输出协议保持稳定，版本升级时尽量新增字段，不要直接改旧字段语义
- 如果后续工具数量继续增加，建议把 `MCP_TOOL_ENDPOINTS` 进一步收敛为统一工具网关
- 如果部署到 Windows，优先采用“主应用容器 + 若干工具服务容器”模式，比把所有定量工具都耦合进主镜像更易维护

## 常用命令

```bash
# 全量重建图谱
python -m graphrag_agent.integrations.build.main

# 或使用 make
make rebuild-graph

# 运行默认测试集
python -m unittest discover test -v

# 仅测试模型与服务可用性
python -m unittest test.test_api_availability -v

# 仅测试流体物性工具
python -m unittest test.test_fluid_property_tool -v
```

## 测试说明

项目当前主要使用 `unittest`：

- 单元测试：覆盖工具、构图约束、流式接口、可观测性等
- 接口可用性测试：校验 LLM、Embedding、Neo4j
- 联调脚本：位于 `test/search_with_stream.py` 与 `test/search_without_stream.py`

建议至少执行：

```bash
python -m unittest discover test -v
```

## 适合维护的文档边界

当前应优先维护以下文档：

- 根 `readme.md`：项目总览与启动方式
- [assets/start.md](/home/omnistorm/桌面/code/project/graph-RAG/assets/start.md:1)：快速启动与环境配置
- [assets/admin_console.md](/home/omnistorm/桌面/code/project/graph-RAG/assets/admin_console.md:1)：后台管理说明
- 模块内 `readme.md`：仅说明该模块职责，不再重复整仓库介绍

不再把历史宣传链接、无关演示文案、训练支线描述混入项目主文档。

## 开发建议

- 将问答链路与构图链路解耦，避免在线请求阻塞构图任务
- 后台构建任务建议逐步迁移为队列消费模型
- 对生产环境使用独立的 Neo4j、PostgreSQL 与对象存储卷
- 若部署到 Kubernetes，建议拆分为 `backend-api`、`chat-frontend`、`admin-frontend`、`builder-worker` 四类工作负载
- 流体物性工具属于定量链路，新增工质或单位时应优先补测试，再补解析能力

## 相关文档

- [assets/start.md](/home/omnistorm/桌面/code/project/graph-RAG/assets/start.md:1)
- [assets/admin_console.md](/home/omnistorm/桌面/code/project/graph-RAG/assets/admin_console.md:1)
- [frontend/readme.md](/home/omnistorm/桌面/code/project/graph-RAG/frontend/readme.md:1)
- [server/readme.md](/home/omnistorm/桌面/code/project/graph-RAG/server/readme.md:1)
- [graphrag_agent/readme.md](/home/omnistorm/桌面/code/project/graph-RAG/graphrag_agent/readme.md:1)
