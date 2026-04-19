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

### 4. 使用 Docker 一键启动完整应用

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

### 5. Docker 开发模式

如果你是在本地频繁改代码，建议使用开发态 compose，直接挂载源码，避免每次都重建镜像：

```bash
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml up -d app
```

这种模式下：

- Python 代码修改后只需要重启容器内进程或重新启动服务
- 默认不会拉起 Langfuse，减少额外容器开销
- 依赖层缓存稳定后，后续联调明显更快

### 6. 启动后端与前端

```bash
uvicorn server.main:app --reload
streamlit run frontend/app.py
```

或使用 Makefile：

```bash
make start-backend
make start-frontend
```

### 7. 启动后台管理界面

```bash
make start-admin-backend
make start-admin-frontend
```

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
