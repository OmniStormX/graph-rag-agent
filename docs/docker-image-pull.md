# Docker 已发布镜像拉取与启动指南

本文档用于从已发布镜像启动 GraphRAG 服务，适合不希望在本机通过 `Dockerfile` 重新构建镜像的部署场景。

## 前置条件

1. 已安装 Docker Engine 与 Docker Compose。
2. Docker daemon 已启动，并且当前用户可以访问 Docker socket。
3. 项目根目录存在 `.env` 文件，且已配置 Chat、Embedding、Neo4j 等必要参数。

可先执行以下命令确认环境：

```bash
docker --version
docker compose version
docker info
```

如果 `docker info` 无法看到 `Server` 信息，说明 Docker daemon 未正常运行，需要先启动 Docker 服务。

## 拉取已发布镜像

项目提供了 `docker-compose.image.yaml`，其中主应用镜像默认为：

```text
ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
```

在项目根目录执行：

```bash
docker compose -f docker-compose.image.yaml pull
```

该命令会拉取以下运行所需镜像：

```text
ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
postgres:16
neo4j:5.22.0
```

如需指定其他已发布镜像标签，可通过环境变量覆盖：

```bash
GRAPH_RAG_IMAGE=ghcr.io/omnistormx/graph-rag-app:your-tag \
  docker compose -f docker-compose.image.yaml pull
```

## 启动服务

镜像拉取完成后，执行：

```bash
docker compose -f docker-compose.image.yaml up -d
```

查看容器状态：

```bash
docker compose -f docker-compose.image.yaml ps
```

查看主应用日志：

```bash
docker compose -f docker-compose.image.yaml logs -f app
```

## 访问地址

服务启动后，默认端口如下：

```text
FastAPI 后端: http://localhost:8000
Streamlit 前端: http://localhost:8501
管理/辅助界面: http://localhost:8502
Neo4j Browser: http://localhost:7474
Neo4j Bolt: bolt://localhost:7687
```

Neo4j 默认账号密码来自 `docker-compose.image.yaml`：

```text
用户名: neo4j
密码: 12345678
```

本机直接运行测试时，`.env` 中建议保持：

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=12345678
```

容器内部访问 Neo4j 时，Compose 会自动覆盖为：

```env
NEO4J_URI=neo4j://neo4j:7687
```

## 验证 API 与依赖连通性

容器启动完成后，可在宿主机运行：

```bash
python3 -m unittest test.test_api_availability -v
```

预期结果：

1. Chat API 测试通过。
2. Embedding API 测试通过。
3. Neo4j 端口连通性测试通过。

## 常见问题

### Docker daemon 未启动

如果拉取时报错：

```text
failed to connect to the docker API at unix:///var/run/docker.sock
```

说明 Docker client 已安装，但 Docker daemon 未运行或当前环境无法访问 Docker socket。

在常规 Linux 主机上可尝试：

```bash
sudo systemctl start docker
sudo systemctl enable docker
```

如果当前环境不是 systemd 启动，例如部分容器、WSL 或受限开发环境，需要在宿主机 Docker Desktop、Docker Engine 或对应运行时中启动 Docker daemon 后再执行拉取命令。

### 端口被占用

如果 `8000`、`8501`、`8502`、`5432`、`7474` 或 `7687` 已被占用，需要先停止占用端口的服务，或修改 `docker-compose.image.yaml` 中的端口映射。

### 更新镜像

重新拉取并滚动重启：

```bash
docker compose -f docker-compose.image.yaml pull
docker compose -f docker-compose.image.yaml up -d
```

持久化数据保存在 Compose volume 和项目挂载目录中，常规镜像更新不会清空 `cache/`、`files/`、`runtime/`、`datasets/`、`documents/`。

## 本次执行记录

在当前开发环境中已执行：

```bash
sudo service docker start
docker compose -f docker-compose.image.yaml pull
```

执行结果：Docker daemon 已启动，镜像拉取成功。

```text
ghcr.io/omnistormx/graph-rag-app:graphRAG-CSU
postgres:16
neo4j:5.22.0
```

结论：当前环境 Docker 已可用。由于该 Ubuntu 环境不是 systemd init，启动 Docker daemon 时使用 `sudo service docker start`，而不是 `systemctl start docker`。
