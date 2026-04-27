# 快速开始指南

## One-API 部署

使用 Docker 启动 One-API：

```bash
docker run --name one-api -d --restart always \
  -p 13000:3000 \
  -e TZ=Asia/Shanghai \
  -v /home/ubuntu/data/one-api:/data \
  justsong/one-api
```

在 One-API 控制台中配置第三方 API Key。本项目的所有 API 请求将通过 One-API 转发。

该项目的官方地址：https://github.com/songquanpeng/one-api

具体的填写方式可以看[这里](https://github.com/1517005260/graph-rag-agent/issues/7#issuecomment-2906770240)

**注意**：默认用管理员账号登录，用户名root，密码123456，进去之后可以改密码

### 或者

1. 直接使用第三方代理平台，如[云雾api](https://yunwu.ai/)等，使用方法同one-api，`.env`中api-key写中转站给你的key，url写中转站的url

2. 使用更先进的[new-api](https://github.com/QuantumNous/new-api)，使用方法基本同one-api

```bash
# 使用SQLite部署new-api
docker run --name new-api -d --restart always -p 3000:3000 -e TZ=Asia/Shanghai -v /home/ubuntu/data/new-api:/data calciumion/new-api:latest
```


## Neo4j 启动

```bash
cd graph-rag-agent/
docker compose up -d
```

默认会同时启动：

- Neo4j 图数据库
- PostgreSQL 图谱后台元数据库
- Langfuse 可观测性服务
- Langfuse Worker / ClickHouse / Redis / MinIO 依赖栈

Neo4j 默认账号密码：

```
用户名：neo4j
密码：12345678
```

PostgreSQL 默认连接信息：

```
数据库：graphrag_admin
用户名：postgres
密码：postgres
地址：localhost:5432
```

Langfuse 默认访问地址：

```
Web UI：http://localhost:3000
MinIO API：http://localhost:9090
MinIO Console：http://localhost:9091
```

Langfuse 本地默认初始化账号：

```
邮箱：admin@example.com
密码：admin123456
项目：graph-rag
```

说明：

- 这些默认值仅适合本地开发，生产环境务必改掉 `.env` 中的 Langfuse 密钥与口令
- 若你只想启动图谱服务、不想启动 Langfuse，可使用 `docker compose up -d postgres neo4j`

## 使用已发布镜像启动

如果不需要在本地构建镜像，可以直接拉取发布到 GHCR 的项目镜像：

```bash
docker pull ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
docker compose -f docker-compose.image.yaml up -d
```

`docker-compose.image.yaml` 使用同一个项目镜像分别启动主应用和流体物性工具服务，同时编排 Neo4j 与 PostgreSQL。`latest` 只会在默认分支发布成功后生成；生产环境建议固定具体 tag 或提交 SHA，避免不可预期升级。

## 环境搭建

```bash
conda create -n graphrag python==3.10
conda activate graphrag
cd graph-rag-agent/
pip install -r requirements.txt
```

注意：如需处理 `.doc` 格式（旧版 Word 文件），请根据操作系统安装相应依赖，详见 `requirements.txt` 中注释：

```txt
# Linux
sudo apt-get install python-dev-is-python3 libxml2-dev libxslt1-dev antiword unrtf poppler-utils

# Windows
pywin32>=302

textract==1.6.3  # Windows 无需安装
```

如果遇到报错：`OSError: [WinError 1114] 动态链接库(DLL)初始化例程失败。 Error loading "D:\anaconda\envs\graphrag\lib\site-packages\torch\lib\c10.dll" or one of its dependencies.` 是因为下载了torch2.9.0版本，遇到此问题请手动降级torch，比如`pip install torch==2.8.0`即可。

## 环境变量配置 (.env)

### 配置说明

项目配置已统一至 `.env` 文件，除知识图谱实体/关系模式外，所有运行参数均可通过环境变量覆盖。请在项目根目录创建 `.env` 文件进行配置。

### 必选配置项

以下配置为必填项，项目无法运行时需首先检查这些配置：

```env
# ===== Chat 模型配置 =====
CHAT_API_KEY = 'sk-chat-xxx'
CHAT_BASE_URL = 'http://localhost:13000/v1'
CHAT_MODEL = 'gpt-4o'

# ===== Embedding 模型配置 =====
EMBEDDING_API_KEY = 'sk-embedding-xxx'
EMBEDDING_BASE_URL = 'http://localhost:13000/v1'
EMBEDDING_MODEL = 'text-embedding-v4'

# 旧版兜底配置（可选）
OPENAI_API_KEY = 'sk-xxx'
OPENAI_BASE_URL = 'http://localhost:13000/v1'
OPENAI_LLM_MODEL = 'gpt-4o'

# ===== Hugging Face 镜像与缓存配置 =====
# 当 transformers 需要下载 tokenizer 或模型时，优先走镜像站。
HF_ENDPOINT = 'https://hf-mirror.com'
HF_HOME = './cache/huggingface'
HF_HUB_CACHE = './cache/huggingface/hub'
HF_HUB_ETAG_TIMEOUT = 30
HF_HUB_DOWNLOAD_TIMEOUT = 60
# 若模型与 tokenizer 已预下载到本地，可改为 1 开启离线模式。
HF_HUB_OFFLINE = 0

# ===== Neo4j 数据库配置 =====
NEO4J_URI = 'neo4j://localhost:7687'
NEO4J_USERNAME = 'neo4j'
NEO4J_PASSWORD = '12345678'
```

### 推荐修改配置项

以下配置根据实际使用场景建议调整：

```env
# ===== 独立 Embedding 服务示例（以 Qwen 兼容接口为例） =====
# OPENAI_API_KEY = '你的对话模型 Key'
# OPENAI_BASE_URL = '你的对话模型兼容地址'
# OPENAI_LLM_MODEL = 'gpt-4o'
#
# EMBEDDING_API_KEY = '你的 Qwen Embedding Key'
# EMBEDDING_BASE_URL = '你的 Qwen Embedding 兼容地址'
# EMBEDDING_MODEL = 'text-embedding-v4'
#
# ===== 缓存向量模型配置 =====
# 推荐使用第三方embedding模型api，省事。以下是需要下载的配置
CACHE_EMBEDDING_PROVIDER = 'sentence_transformer'
CACHE_SENTENCE_TRANSFORMER_MODEL = 'all-MiniLM-L6-v2'

# ===== 并发与性能配置 =====
# 根据机器性能调整，4核CPU推荐值如下
FASTAPI_WORKERS = 2
MAX_WORKERS = 4
MA_WORKER_EXECUTION_MODE = 'parallel'
MA_WORKER_MAX_CONCURRENCY = 4
BATCH_SIZE = 100

# ===== GDS 内存配置 =====
# 根据服务器内存调整，单位 GB
GDS_MEMORY_LIMIT = 6

# ===== 文本处理参数 =====
# 根据文档特性调整分块大小
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

# ===== 图谱后台管理系统 =====
GRAPH_ADMIN_ENABLED = true
GRAPH_ADMIN_METADATA_DSN = 'postgresql://postgres:postgres@localhost:5432/graphrag_admin'
GRAPH_ADMIN_RUNTIME_DIR = './runtime/admin'
GRAPH_ADMIN_BUILD_LOG_DIR = './runtime/admin/build_logs'
GRAPH_ADMIN_SNAPSHOT_DIR = './runtime/admin/snapshots'
GRAPH_ADMIN_UPLOAD_DIR = './runtime/admin/uploads'
ADMIN_FRONTEND_API_URL = 'http://localhost:8001'
```

### 默认即可配置项

以下配置一般无需修改，保持默认值即可：

```env
# ===== LLM 生成参数 =====
TEMPERATURE = 0
MAX_TOKENS = 2000
VERBOSE = True

# ===== 文本处理 =====
MAX_TEXT_LENGTH = 500000
SIMILARITY_THRESHOLD = 0.9
RESPONSE_TYPE = '多个段落'

# ===== 批处理大小 =====
ENTITY_BATCH_SIZE = 50
CHUNK_BATCH_SIZE = 100
EMBEDDING_BATCH_SIZE = 64
LLM_BATCH_SIZE = 5
COMMUNITY_BATCH_SIZE = 50

# ===== GDS 运行参数 =====
GDS_CONCURRENCY = 4
GDS_NODE_COUNT_LIMIT = 50000
GDS_TIMEOUT_SECONDS = 300

# ===== 实体消歧配置 =====
DISAMBIG_STRING_THRESHOLD = 0.7
DISAMBIG_VECTOR_THRESHOLD = 0.85
DISAMBIG_NIL_THRESHOLD = 0.6
DISAMBIG_TOP_K = 5
ALIGNMENT_CONFLICT_THRESHOLD = 0.5
ALIGNMENT_MIN_GROUP_SIZE = 2

# ===== Neo4j 连接池 =====
NEO4J_MAX_POOL_SIZE = 10
NEO4J_REFRESH_SCHEMA = false

# ===== 缓存系统配置 =====
MODEL_CACHE_ROOT = './cache'
CACHE_ROOT = './cache'
CACHE_DIR = './cache'
CACHE_MEMORY_ONLY = false
CACHE_MAX_MEMORY_SIZE = 100
CACHE_MAX_DISK_SIZE = 1000
CACHE_THREAD_SAFE = true
CACHE_ENABLE_VECTOR_SIMILARITY = true
CACHE_SIMILARITY_THRESHOLD = 0.9
CACHE_MAX_VECTORS = 10000

# ===== 相似实体检测 =====
SIMILAR_ENTITY_WORD_EDIT_DISTANCE = 3
SIMILAR_ENTITY_BATCH_SIZE = 500
SIMILAR_ENTITY_MEMORY_LIMIT = 6
SIMILAR_ENTITY_TOP_K = 10

# ===== 搜索工具参数 =====
SEARCH_CACHE_MEMORY_SIZE = 200
SEARCH_VECTOR_LIMIT = 5
SEARCH_TEXT_LIMIT = 5
SEARCH_SEMANTIC_TOP_K = 5
SEARCH_RELEVANCE_TOP_K = 5
NAIVE_SEARCH_TOP_K = 3

LOCAL_SEARCH_TOP_CHUNKS = 3
LOCAL_SEARCH_TOP_COMMUNITIES = 3
LOCAL_SEARCH_TOP_OUTSIDE_RELS = 10
LOCAL_SEARCH_TOP_INSIDE_RELS = 10
LOCAL_SEARCH_TOP_ENTITIES = 10
LOCAL_SEARCH_INDEX_NAME = 'vector'

GLOBAL_SEARCH_LEVEL = 0
GLOBAL_SEARCH_BATCH_SIZE = 5

HYBRID_SEARCH_ENTITY_LIMIT = 15
HYBRID_SEARCH_MAX_HOP = 2
HYBRID_SEARCH_TOP_COMMUNITIES = 3
HYBRID_SEARCH_BATCH_SIZE = 10
HYBRID_SEARCH_COMMUNITY_LEVEL = 0

# ===== Server 运行参数 =====
SERVER_HOST = '0.0.0.0'
SERVER_PORT = 8000
SERVER_RELOAD = false
SERVER_LOG_LEVEL = 'info'
SERVER_WORKERS = 2

# ===== 前端运行参数 =====
FRONTEND_API_URL = 'http://localhost:8000'
FRONTEND_DEFAULT_AGENT = 'naive_rag_agent'
FRONTEND_DEFAULT_DEBUG = false
FRONTEND_SHOW_THINKING = true
FRONTEND_USE_DEEPER_TOOL = true
FRONTEND_USE_STREAM = true
FRONTEND_USE_CHAIN_EXPLORATION = true

# ===== 知识图谱可视化参数 =====
KG_PHYSICS_ENABLED = true
KG_NODE_SIZE = 25
KG_EDGE_WIDTH = 2
KG_SPRING_LENGTH = 150
KG_GRAVITY = -5000

# ===== Agent 参数 =====
AGENT_RECURSION_LIMIT = 5
AGENT_CHUNK_SIZE = 4
AGENT_STREAM_FLUSH_THRESHOLD = 40
DEEP_AGENT_STREAM_FLUSH_THRESHOLD = 80
FUSION_AGENT_STREAM_FLUSH_THRESHOLD = 60
```

### 可选配置项

以下配置为可选功能，不需要可以不配置或注释掉：

```env
# ===== Langfuse 监控（可选，本地部署友好）=====
# 不需要可以完全注释掉此部分
LANGFUSE_ENABLED = false
LANGFUSE_BASE_URL = "http://localhost:3000"
LANGFUSE_HOST = "http://localhost:3000"
LANGFUSE_PUBLIC_KEY = "pk-lf-xxx"
LANGFUSE_SECRET_KEY = "sk-lf-xxx"

# ===== Langfuse Docker 本地部署（可选）=====
LANGFUSE_PUBLIC_URL = "http://localhost:3000"
LANGFUSE_NEXTAUTH_SECRET = "change-this-nextauth-secret"
LANGFUSE_SALT = "change-this-salt"
LANGFUSE_ENCRYPTION_KEY = "0000000000000000000000000000000000000000000000000000000000000000"
LANGFUSE_POSTGRES_PASSWORD = "langfuse"
LANGFUSE_CLICKHOUSE_PASSWORD = "clickhouse"
LANGFUSE_REDIS_PASSWORD = "langfuse-redis"
LANGFUSE_MINIO_ROOT_USER = "minio"
LANGFUSE_MINIO_ROOT_PASSWORD = "minio123456"
LANGFUSE_S3_BUCKET = "langfuse"
LANGFUSE_S3_REGION = "auto"
LANGFUSE_INIT_ORG_ID = "graph-rag"
LANGFUSE_INIT_ORG_NAME = "GraphRAG Local"
LANGFUSE_INIT_PROJECT_ID = "graph-rag"
LANGFUSE_INIT_PROJECT_NAME = "graph-rag"
LANGFUSE_INIT_PROJECT_PUBLIC_KEY = "pk-lf-graph-rag-local"
LANGFUSE_INIT_PROJECT_SECRET_KEY = "sk-lf-graph-rag-local"
LANGFUSE_INIT_USER_EMAIL = "admin@example.com"
LANGFUSE_INIT_USER_NAME = "GraphRAG Admin"
LANGFUSE_INIT_USER_PASSWORD = "admin123456"
```

### 配置模板获取

完整配置模板请参考项目根目录的 `.env.example` 文件，可直接复制重命名为 `.env` 后修改。

### 模型兼容性说明

全流程测试通过的模型：
- DeepSeek (20241226版本)
- GPT-4o

已知问题模型：
- DeepSeek (20250324版本)：幻觉问题严重，可能导致实体抽取失败
- Qwen 系列：可以抽取实体，但与 LangChain/LangGraph 兼容性存在问题，建议使用其官方 [Qwen-Agent](https://qwen.readthedocs.io/zh-cn/latest/framework/qwen_agent.html) 框架

## 项目初始化

```bash
pip install -e .
```

## 知识图谱原始文件放置

请将原始文件放入 `files/` 文件夹，支持有目录的存放。当前支持以下格式（采用简单分块，后续会优化处理方式）：

```
- TXT（纯文本）
- PDF（PDF 文档）
- MD（Markdown）
- DOCX（新版 Word 文档）
- DOC（旧版 Word 文档）
- CSV（表格）
- JSON（结构化文本）
- YAML/YML（配置文件）
```

## 知识图谱实体与关系配置

除环境变量配置外，知识图谱的实体类型和关系类型需要在代码中配置。

编辑 `graphrag_agent/config/settings.py`：

```python
# 知识图谱主题
theme = "教材与技术文档知识体系"

# 实体类型定义
entity_types = [
    "章节",
    "小节",
    "图表",
    "案例",
    "概念",
    "原理定律",
    "物理量",
    "公式",
    "变量",
    "条件",
    "过程",
    "状态",
    "系统对象",
    "组成部件",
    "材料介质",
    "其它",
]

# 关系类型定义
relationship_types = [
    "包含",
    "属于",
    "定义",
    "遵循",
    "表示",
    "使用变量",
    "单位为",
    "适用条件",
    "导致",
    "影响",
    "依赖",
    "具有状态",
    "图示说明",
    "实例说明",
    "对比",
    "其它",
]

# 冲突解决策略（也可通过环境变量 GRAPH_CONFLICT_STRATEGY 覆盖）
# manual_first: 优先保留手动编辑
# auto_first: 优先自动更新
# merge: 尝试合并
conflict_strategy = "manual_first"

# 社区检测算法（也可通过环境变量 GRAPH_COMMUNITY_ALGORITHM 覆盖）
# leiden / sllpa （sllpa如果发现不了社区，建议换成leiden）
community_algorithm = "leiden"
```

## 构建知识图谱

```bash
cd graph-rag-agent/

# 初始全量构建
python graphrag_agent/integrations/build/main.py

# 单次变量（增量、减量）构建：
python graphrag_agent/integrations/build/incremental_update.py --once

# 后台守护进程，定期变量更新：
python graphrag_agent/integrations/build/incremental_update.py --daemon
```

**注意：** `main.py`是构建的全流程，如果需要单独跑某个流程，请先完成实体索引的构建，再进行 chunk 索引构建，否则会报错（chunk 索引依赖实体索引）。

## 知识图谱搜索测试

```bash
cd graph-rag-agent/test

# 查询前可以注释掉不想测试的Agent，防止运行过慢

# 非流式查询
python search_without_stream.py

# 流式查询
python search_with_stream.py
```

## 知识图谱评估

```bash
cd graphrag_agent/evaluation/test
# 查看对应 README 获取更多信息
```

## 前端示例问题配置

编辑 `graphrag_agent/config/settings.py` 中的 `examples` 字段：

```python
examples = [
    "旷课多少学时会被退学？",
    "国家奖学金和国家励志奖学金互斥吗？",
    "优秀学生要怎么申请？",
    "那上海市奖学金呢？"
]
```

## 配置体系说明

项目配置分为三层：

1. `.env` 文件：所有运行时参数、密钥、性能调优参数
2. `graphrag_agent/config/settings.py`：知识图谱结构配置（实体/关系类型、示例问题等）
3. `server/server_config/settings.py` 和 `frontend/frontend_config/settings.py`：自动继承上层配置

大部分配置可通过 `.env` 直接控制，无需修改代码。

## 深度搜索优化（建议禁用前端超时）

如需开启深度搜索功能，建议禁用前端超时限制，修改 `frontend/utils/api.py`：

```python
response = requests.post(
    f"{API_URL}/chat",
    json={
        "message": message,
        "session_id": st.session_state.session_id,
        "debug": st.session_state.debug_mode,
        "agent_type": st.session_state.agent_type
    },
    # timeout=120  # 建议注释掉此行
)
```

## 中文字体支持（Linux）

如需中文图表显示，可参考[字体安装教程](https://zhuanlan.zhihu.com/p/571610437)。默认使用英文绘图（`matplotlib`）。


## 启动前后端服务

```bash
# 启动后端
cd graph-rag-agent/
python server/main.py

# 启动问答前端
cd graph-rag-agent/
streamlit run frontend/app.py

# 启动后台管理前端
cd graph-rag-agent/
streamlit run frontend/admin_app.py
```

**注意**：由于langchain版本问题，目前的流式是伪流式实现，即先完整生成答案，再分段返回。

如果启用了后台管理系统，请确认 `.env` 中的 `GRAPH_ADMIN_METADATA_DSN` 已正确指向 PostgreSQL，否则后台相关接口不会落库。
如果后台通过 `make start-admin-backend` 启动，则默认监听 `8001` 端口，`ADMIN_FRONTEND_API_URL` 也应指向同一地址。
