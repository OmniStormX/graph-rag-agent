# 从空白 Docker 环境拉取并运行 GraphRAG 镜像

本文档适用于一台 Docker 环境干净的机器：没有本项目镜像、容器、网络和数据卷，需要从已发布镜像直接启动 GraphRAG 全套服务。

## 1. 前置条件

需要已安装：

```bash
docker --version
docker compose version
```

如果 Docker daemon 未启动，Ubuntu 非 systemd 环境可执行：

```bash
sudo service docker start
```

常规 Linux 主机可执行：

```bash
sudo systemctl start docker
```

确认 Docker 服务可用：

```bash
docker info
```

## 2. 准备配置文件

进入项目根目录：

```bash
cd ~/graphRAG
```

如果还没有 `.env`，先复制示例文件：

```bash
cp .env.example .env
```

至少确认以下配置已填写：

```env
CHAT_API_KEY=你的对话模型密钥
CHAT_BASE_URL=你的对话模型 OpenAI 兼容地址
CHAT_MODEL=你的对话模型名称

EMBEDDING_API_KEY=你的向量模型密钥
EMBEDDING_BASE_URL=你的向量模型 OpenAI 兼容地址
EMBEDDING_MODEL=你的向量模型名称

NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=12345678
```

说明：容器内部访问 Neo4j 时，`docker-compose.image.yaml` 会自动覆盖为 `neo4j://neo4j:7687`；宿主机直接运行测试时使用 `.env` 中的 `bolt://localhost:7687`。

## 3. 确认端口空闲

本项目默认占用以下宿主机端口：

```text
8000  FastAPI 后端
8501  Streamlit 前端
8502  管理/辅助界面
7474  Neo4j Browser
7687  Neo4j Bolt
5432  Postgres
```

检查端口占用：

```bash
sudo ss -ltnp '( sport = :8000 or sport = :8501 or sport = :8502 or sport = :7474 or sport = :7687 or sport = :5432 )'
```

如果存在旧容器占用，可以先查看：

```bash
docker ps
```

再按需停止旧容器，例如：

```bash
docker stop graphrag-neo4j graphrag-postgres
```

## 4. 拉取已发布镜像

项目使用 `docker-compose.image.yaml` 从远端镜像启动，不需要本地构建 `Dockerfile`。

执行：

```bash
docker compose -f docker-compose.image.yaml pull
```

默认会拉取：

```text
ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
postgres:16
neo4j:5.22.0
```

确认镜像已存在：

```bash
docker image ls | grep -E 'graph-rag-app|postgres|neo4j'
```

## 5. 启动服务

执行：

```bash
docker compose -f docker-compose.image.yaml up -d
```

查看服务状态：

```bash
docker compose -f docker-compose.image.yaml ps
```

正常情况下应看到：

```text
graph-rag-app                      healthy
graph-rag-fluid-property-service   healthy
graphrag-postgres-1                healthy
graphrag-neo4j-1                   running
```

如果依赖容器因为首次端口冲突等原因创建异常，可在释放端口后重建依赖容器：

```bash
docker compose -f docker-compose.image.yaml up -d --force-recreate postgres neo4j
docker compose -f docker-compose.image.yaml up -d
```

## 6. 访问服务

启动完成后访问：

```text
FastAPI 后端: http://localhost:8000
Streamlit 前端: http://localhost:8501
管理/辅助界面: http://localhost:8502
Neo4j Browser: http://localhost:7474
```

Neo4j 默认账号：

```text
用户名: neo4j
密码: 12345678
```

## 7. 验证连通性

查看端口监听：

```bash
sudo ss -ltnp '( sport = :8000 or sport = :8501 or sport = :8502 or sport = :7474 or sport = :7687 or sport = :5432 )'
```

运行项目 API 连通性测试：

```bash
python3 -m unittest test.test_api_availability -v
```

预期结果：

```text
Chat API       通过
Embedding API  通过
Neo4j TCP      通过
```

## 8. 查看日志

查看主应用日志：

```bash
docker compose -f docker-compose.image.yaml logs -f app
```

查看 Neo4j 日志：

```bash
docker compose -f docker-compose.image.yaml logs -f neo4j
```

查看 Postgres 日志：

```bash
docker compose -f docker-compose.image.yaml logs -f postgres
```

## 9. 停止与重启

停止服务但保留数据卷：

```bash
docker compose -f docker-compose.image.yaml stop
```

重新启动：

```bash
docker compose -f docker-compose.image.yaml up -d
```

停止并删除容器、网络，但保留数据卷：

```bash
docker compose -f docker-compose.image.yaml down
```

## 10. 从零清理后重来

危险操作：以下命令会删除本项目容器和数据卷，Neo4j/Postgres 数据会丢失。

```bash
docker compose -f docker-compose.image.yaml down -v
```

如果需要重新拉取最新镜像：

```bash
docker compose -f docker-compose.image.yaml pull
docker compose -f docker-compose.image.yaml up -d
```

## 11. 常见问题

### 端口已被占用

错误示例：

```text
Bind for 0.0.0.0:7474 failed: port is already allocated
```

处理方式：

```bash
docker ps
sudo ss -ltnp 'sport = :7474'
docker stop 占用该端口的容器名
docker compose -f docker-compose.image.yaml up -d
```

### Docker daemon 未运行

错误示例：

```text
failed to connect to the docker API at unix:///var/run/docker.sock
```

处理方式：

```bash
sudo service docker start
docker info
```

如果是 Docker Desktop 或 WSL 环境，需要先在宿主机启动 Docker Desktop，并确保 WSL integration 已开启。

### 主应用长时间 health starting

先查看日志：

```bash
docker compose -f docker-compose.image.yaml logs --tail=100 app
```

重点检查：

1. `.env` 中模型 API Key、Base URL、Model 是否正确。
2. Neo4j 和 Postgres 是否已启动。
3. 端口是否被旧容器占用。

### Neo4j 插件下载警告

如果日志中出现 `graph-data-science` 插件兼容信息查询失败，一般是容器网络访问外部站点失败。Neo4j 仍可能启动，但 GDS 能力可能不可用。生产环境建议提前准备可用网络或固定插件镜像版本，避免启动期动态下载失败。
