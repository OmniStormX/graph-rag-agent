FROM python:3.10-slim-bookworm AS base

# 统一基础环境，减少不同阶段的重复配置。
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ENV PYTHONPATH=/app:/app/server:/app/frontend
ENV STREAMLIT_SERVER_FILE_WATCHER_TYPE=none
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app


FROM base AS builder

# 仅在构建阶段安装编译工具，避免污染最终运行镜像。
RUN apt-get -o Acquire::Retries=5 -o Acquire::ForceIPv4=true update \
    && apt-get -o Acquire::Retries=5 -o Acquire::ForceIPv4=true install -y --no-install-recommends \
        antiword \
        build-essential \
        gcc \
        g++ \
        libmagic1 \
        libxml2-dev \
        libxslt1-dev \
        poppler-utils \
        python3-venv \
        unrtf \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"

COPY requirements.txt requirements.local_nlp.txt ./

# 将可选本地 NLP 栈做成显式开关，默认镜像不再安装 torch 相关依赖。
ARG INSTALL_LOCAL_NLP=false
RUN pip install --retries 10 --timeout 120 -r requirements.txt \
    && if [ "$INSTALL_LOCAL_NLP" = "true" ]; then \
         pip install --retries 10 --timeout 120 -r requirements.local_nlp.txt; \
       fi


FROM base AS runtime

# 运行镜像仅保留必要系统包，减小体积并降低安全面。
RUN apt-get -o Acquire::Retries=5 -o Acquire::ForceIPv4=true update \
    && apt-get -o Acquire::Retries=5 -o Acquire::ForceIPv4=true install -y --no-install-recommends \
        antiword \
        curl \
        libmagic1 \
        libxml2 \
        libxslt1.1 \
        poppler-utils \
        tini \
        unrtf \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

COPY setup.py ./
COPY graphrag_agent ./graphrag_agent
COPY server ./server
COPY frontend ./frontend
COPY assets ./assets
COPY datasets ./datasets
COPY files ./files
COPY docker ./docker
COPY readme.md ./readme.md

# 创建运行目录，避免首次启动时因目录不存在而报错。
RUN mkdir -p /app/cache /app/documents /app/runtime/admin/build_logs /app/runtime/admin/snapshots \
    && useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000 8501 8502

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "/app/docker/app/start.sh"]
