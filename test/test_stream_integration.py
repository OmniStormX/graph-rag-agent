import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# 将项目根目录和 server 目录加入路径，确保测试脚本可直接运行。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_ROOT = PROJECT_ROOT / "server"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

try:
    from fastapi.testclient import TestClient
    from server.main import app  # noqa: E402
    TEST_IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]
    app = None  # type: ignore[assignment]
    TEST_IMPORT_ERROR = exc


class FakeStreamAgent:
    """用于流式集成测试的最小 Agent 桩。"""

    def set_request_context(self, **_context):
        """兼容服务层注入请求上下文。"""

    def clear_request_context(self):
        """兼容服务层清理请求上下文。"""

    def check_fast_cache(self, query: str, thread_id: str = "default"):
        """测试场景固定走正常流式路径，不命中缓存。"""
        return None

    async def ask_stream(self, query: str, thread_id: str = "default"):
        """按标准协议输出阶段事件和正文 token。"""
        yield {
            "status": "stage",
            "stage": "agent",
            "content": "正在分析问题",
        }
        await asyncio.sleep(0)

        yield {
            "status": "stage",
            "stage": "retrieve",
            "content": "正在检索相关信息",
        }
        await asyncio.sleep(0)

        yield {
            "status": "stage",
            "stage": "generate",
            "content": "正在生成回答",
        }
        await asyncio.sleep(0)

        yield "第一段回答。"
        await asyncio.sleep(0)
        yield "第二段回答。"


class StreamIntegrationTest(unittest.TestCase):
    """最小可运行的 `/chat/stream` 集成测试。"""

    def setUp(self):
        """创建测试客户端。"""
        if TEST_IMPORT_ERROR is not None:
            self.skipTest(f"缺少测试依赖: {TEST_IMPORT_ERROR}")
        self.client = TestClient(app)

    def test_chat_stream_returns_stage_and_token_events(self):
        """验证 SSE 事件顺序和正文聚合结果。"""
        fake_agent = FakeStreamAgent()

        with patch(
            "server.services.chat_service.agent_manager.get_agent",
            return_value=fake_agent,
        ), patch(
            "server.services.chat_service._prepare_cached_kg_payload",
            return_value={"kg_data": None, "kg_cache_key": None},
        ):
            with self.client.stream(
                "POST",
                "/chat/stream",
                json={
                    "message": "测试流式接口",
                    "session_id": "stream-test-session",
                    "debug": False,
                    "agent_type": "graph_agent",
                },
            ) as response:
                self.assertEqual(response.status_code, 200)

                events = []
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    if not raw_line.startswith("data: "):
                        continue
                    payload = json.loads(raw_line[6:])
                    events.append(payload)

        self.assertGreaterEqual(len(events), 5)
        self.assertEqual(events[0]["status"], "start")

        stage_events = [event for event in events if event.get("status") == "stage"]
        token_events = [event for event in events if event.get("status") == "token"]

        self.assertEqual(
            [event.get("stage") for event in stage_events],
            ["agent", "retrieve", "generate"],
        )
        self.assertEqual(
            "".join(event.get("content", "") for event in token_events),
            "第一段回答。第二段回答。",
        )
        self.assertEqual(events[-1]["status"], "done")


if __name__ == "__main__":
    unittest.main(verbosity=2)
