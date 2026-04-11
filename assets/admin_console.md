# 图谱后台管理系统使用说明

本文档说明如何启动和使用独立的图谱后台管理系统。该系统与现有问答前端、后端并行存在，互不替代。

## 1. 设计目标

后台管理系统主要面向知识图谱运维与内容治理，当前版本支持以下能力：

- 增量上传 PDF，并登记为新的文档 revision
- 触发增量构建或全量重建
- 为每次构建生成图谱版本快照
- 查看历史图谱版本，并支持激活与回滚
- 以图形化和表格方式查看某个版本的图数据库内容
- 维护人工修正规则，并在构图时追加到图谱构建 prompt
- 查看后台接口状态、前后端日志和最近构建任务状态

## 2. 架构说明

当前采用的是适合 MVP 落地的“双存储”架构：

- `Neo4j`：只存放当前激活中的知识图谱
- `PostgreSQL`：存放文档、revision、图谱版本、构建任务、修正规则等元数据
- `runtime/admin/snapshots/*.json`：存放每个版本的图谱快照

这样做的好处是：

- 不需要大改现有 GraphRAG 构图主链路
- 回滚语义简单，运维风险较低
- 便于后续平滑升级为更严格的版本仓库模型

## 3. 环境变量

请在 `.env` 中至少补充以下后台管理配置：

```env
GRAPH_ADMIN_ENABLED = true
GRAPH_ADMIN_METADATA_DSN = 'postgresql://postgres:postgres@localhost:5432/graphrag_admin'
GRAPH_ADMIN_RUNTIME_DIR = './runtime/admin'
GRAPH_ADMIN_BUILD_LOG_DIR = './runtime/admin/build_logs'
GRAPH_ADMIN_SNAPSHOT_DIR = './runtime/admin/snapshots'
GRAPH_ADMIN_UPLOAD_DIR = './runtime/admin/uploads'
ADMIN_FRONTEND_API_URL = 'http://localhost:8001'
GRAPH_ADMIN_BACKEND_LOG_PATH = ''
GRAPH_ADMIN_FRONTEND_LOG_PATH = ''
GRAPH_ADMIN_MAX_LOG_LINES = 500
```

建议在生产环境中将 PostgreSQL、Neo4j、应用日志目录都挂载到持久化卷。

## 4. 本地启动

### 4.1 启动基础依赖

```bash
docker compose up -d
```

此命令会启动：

- `neo4j`
- `postgres`

### 4.2 安装依赖

```bash
pip install -r requirements.txt
```

### 4.3 启动后端

```bash
uvicorn server.main:app --reload
```

如果你使用 `make start-admin-backend`，默认会监听 `8001` 端口。

### 4.4 启动原有问答前端

```bash
streamlit run frontend/app.py
```

### 4.5 启动后台管理前端

```bash
streamlit run frontend/admin_app.py
```

如果你使用 `make start-admin-frontend`，脚本会自动把 `ADMIN_FRONTEND_API_URL` 指向 `http://127.0.0.1:8001`。

## 5. 推荐操作流程

### 场景一：新增 PDF 后进行增量补图

1. 在后台管理页“文档上传”中上传 PDF
2. 在“构建任务”中选择对应 revision
3. 触发“增量构建”
4. 构建成功后会自动生成新的图谱版本快照
5. 如勾选“自动激活”，则该版本会成为当前生效图谱

### 场景二：发现抽取错误并修正

1. 在“版本查看”中检查图谱节点与关系
2. 在“修正规则”中新增人工规则
3. 重新触发增量构建或全量重建
4. 如结果不符合预期，可回滚到上一个稳定版本

### 场景三：回滚历史版本

1. 在“图谱版本”中选择目标版本
2. 点击“回滚到该版本”
3. 系统会读取该版本快照并恢复到 Neo4j
4. 元数据库中会同步将该版本标记为 active

## 6. 当前实现边界

当前版本是工程上可运行的 MVP，而不是最终的生产级治理平台，主要边界如下：

- 构图主流程仍复用现有构建逻辑，尚未完全隔离到独立工作目录
- 人工修正规则目前通过构建期 prompt 追加方式生效
- 快照是基于“当前 Neo4j 全图导出”的版本表示
- 暂未提供规则编辑、规则审批、任务重试和权限控制

如果后续要上生产，建议继续演进：

- 将构建流程改造成真正的“版本工作区”
- 将修正规则细分为抽取规则、归一化规则、合并规则、黑白名单规则
- 增加任务队列、锁机制和并发控制
- 增加审计日志、RBAC 和操作审批
- 为大图谱接入抽样预览、分页查询和异步 diff 计算

## 7. Kubernetes 部署建议

如果后续要部署到 Kubernetes，建议采用如下拆分：

- `backend-api` Deployment：FastAPI 主后端
- `chat-frontend` Deployment：现有用户前端
- `admin-frontend` Deployment：后台管理前端
- `worker` Deployment / Job：图谱构建任务执行器
- `postgres` StatefulSet：元数据库
- `neo4j` StatefulSet：图数据库

同时建议：

- 使用 `PersistentVolume` 持久化 `files/`、Neo4j 数据和 PostgreSQL 数据
- 将构建任务从 Web 线程中剥离，改为队列消费模型
- 给构建任务设置资源配额，避免与在线问答抢占 CPU / 内存
- 对上传、构建、回滚接口单独做鉴权和审计
