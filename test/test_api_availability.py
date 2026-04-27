import json
import os
import socket
import unittest
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def load_env_file(env_path: Path) -> Dict[str, str]:
    """读取项目根目录 `.env` 配置。

    说明：
        这里使用轻量解析逻辑，避免测试依赖 `python-dotenv`，
        从而将检查重点放在外部服务可用性，而不是本地依赖是否已安装。

    Args:
        env_path: `.env` 文件路径。

    Returns:
        解析后的键值对字典；文件不存在时返回空字典。
    """
    if not env_path.exists():
        return {}

    config: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        if line.startswith("export "):
            line = line[len("export "):].strip()

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        # 去除成对引号，兼容 `.env.example` 当前写法。
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        config[key] = value

    return config


class ApiAvailabilityTest(unittest.TestCase):
    """验证当前项目依赖的外部 API 是否可用。"""

    @classmethod
    def setUpClass(cls):
        """初始化测试会话和配置。"""
        cls.file_config = load_env_file(ENV_PATH)
        cls.session = requests.Session()
        cls.session.headers.update(
            {"User-Agent": "graph-rag-api-health-check/1.0"}
        )

    @classmethod
    def tearDownClass(cls):
        """释放 HTTP 会话资源。"""
        cls.session.close()

    def get_config(self, key: str, default: str = "") -> str:
        """读取环境变量，优先使用进程环境，再回退 `.env`。"""
        return os.getenv(key) or self.file_config.get(key, default)

    def require_config(self, key: str) -> str:
        """读取必须存在的配置项。

        Args:
            key: 配置名。

        Returns:
            配置值。
        """
        value = self.get_config(key)
        self.assertTrue(value, f"缺少必要配置: {key}")
        return value

    def build_url(self, base_url: str, path: str) -> str:
        """拼接 OpenAI 兼容接口地址。"""
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    def format_response_error(self, response: requests.Response) -> str:
        """构造便于排障的失败信息。"""
        body = response.text.strip().replace("\n", " ")
        if len(body) > 300:
            body = f"{body[:300]}..."
        return f"status={response.status_code}, body={body}"

    def test_llm_chat_completion_api_available(self):
        """验证 LLM `chat/completions` 接口可正常响应。"""
        api_key = (
            self.get_config("CHAT_API_KEY")
            or self.get_config("OPENAI_CHAT_API_KEY")
            or self.require_config("OPENAI_API_KEY")
        )
        base_url = (
            self.get_config("CHAT_BASE_URL")
            or self.get_config("OPENAI_CHAT_BASE_URL")
            or self.require_config("OPENAI_BASE_URL")
        )
        model = (
            self.get_config("CHAT_MODEL")
            or self.get_config("OPENAI_LLM_MODEL")
        )
        self.assertTrue(model, "缺少必要配置: CHAT_MODEL 或 OPENAI_LLM_MODEL")
        endpoint = self.build_url(base_url, "/chat/completions")

        try:
            response = self.session.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    # 使用确定性短问答，避免不同供应商的健康检查响应过长。
                    "messages": [{"role": "user", "content": "请只回复 pong"}],
                    "temperature": 0,
                    # 推理模型可能先输出 reasoning_content，预算过小时 content 会为空。
                    "max_tokens": 64,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            self.fail(f"LLM 请求失败: endpoint={endpoint}, model={model}, error={exc}")

        self.assertLess(
            response.status_code,
            400,
            f"LLM 接口不可用: endpoint={endpoint}, model={model}, {self.format_response_error(response)}",
        )

        payload = response.json()
        choices = payload.get("choices", [])
        self.assertTrue(choices, f"LLM 接口返回缺少 choices: {json.dumps(payload)[:300]}")

        message = choices[0].get("message", {})
        content = message.get("content")
        self.assertTrue(content, f"LLM 接口返回内容为空: {json.dumps(payload)[:300]}")

    def test_embedding_api_available(self):
        """验证 Embedding 接口可正常生成向量。"""
        api_key = (
            self.get_config("EMBEDDING_API_KEY")
            or self.get_config("OPENAI_EMBEDDING_API_KEY")
            or self.require_config("OPENAI_API_KEY")
        )
        base_url = (
            self.get_config("EMBEDDING_BASE_URL")
            or self.get_config("OPENAI_EMBEDDING_BASE_URL")
            or self.require_config("OPENAI_BASE_URL")
        )
        model = (
            self.get_config("EMBEDDING_MODEL")
            or self.get_config("OPENAI_EMBEDDING_MODEL")
            or self.get_config("OPENAI_EMBEDDINGS_MODEL")
        )
        self.assertTrue(
            model,
            "缺少必要配置: EMBEDDING_MODEL 或 OPENAI_EMBEDDINGS_MODEL",
        )
        endpoint = self.build_url(base_url, "/embeddings")

        try:
            response = self.session.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": "ping",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            self.fail(
                f"Embedding 请求失败: endpoint={endpoint}, model={model}, error={exc}"
            )

        self.assertLess(
            response.status_code,
            400,
            f"Embedding 接口不可用: endpoint={endpoint}, model={model}, {self.format_response_error(response)}",
        )

        payload = response.json()
        data = payload.get("data", [])
        self.assertTrue(data, f"Embedding 接口返回缺少 data: {json.dumps(payload)[:300]}")

        embedding = data[0].get("embedding")
        self.assertIsInstance(
            embedding,
            list,
            f"Embedding 返回格式异常: {json.dumps(payload)[:300]}",
        )
        self.assertGreater(len(embedding), 0, "Embedding 向量长度不能为 0")

    def test_neo4j_tcp_connectivity_available(self):
        """验证 Neo4j 服务端口可建立连接。"""
        uri = self.require_config("NEO4J_URI")
        username = self.require_config("NEO4J_USERNAME")
        password = self.require_config("NEO4J_PASSWORD")
        self.assertTrue(username and password, "Neo4j 用户名或密码为空")

        parsed = urlparse(uri)
        host: Optional[str] = parsed.hostname
        port = parsed.port or 7687

        self.assertTrue(host, f"NEO4J_URI 缺少主机名: {uri}")

        try:
            with socket.create_connection((host, port), timeout=5):
                pass
        except OSError as exc:
            self.fail(f"Neo4j 端口不可达: host={host}, port={port}, error={exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
