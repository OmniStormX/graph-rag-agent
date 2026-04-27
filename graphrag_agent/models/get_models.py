from langchain_openai import ChatOpenAI
from langchain.callbacks.streaming_aiter import AsyncIteratorCallbackHandler
from langchain.callbacks.manager import AsyncCallbackManager
from openai import OpenAI


import os
from typing import List

from graphrag_agent.config.settings import (
    HF_ENDPOINT,
    HF_HUB_CACHE,
    HF_HUB_DOWNLOAD_TIMEOUT,
    HF_HUB_ETAG_TIMEOUT,
    HF_HUB_OFFLINE,
    HF_HOME,
    MODEL_CACHE_DIR,
    TIKTOKEN_CACHE_DIR,
    OPENAI_EMBEDDING_CONFIG,
    OPENAI_LLM_CONFIG,
)


# 设置 tiktoken 缓存目录，避免每次联网拉取
def setup_cache():
    HF_HOME.mkdir(parents=True, exist_ok=True)
    HF_HUB_CACHE.mkdir(parents=True, exist_ok=True)
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TIKTOKEN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ["HF_ENDPOINT"] = HF_ENDPOINT
    os.environ["HF_HUB_ETAG_TIMEOUT"] = HF_HUB_ETAG_TIMEOUT
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = HF_HUB_DOWNLOAD_TIMEOUT
    os.environ["HF_HUB_OFFLINE"] = HF_HUB_OFFLINE
    os.environ["TIKTOKEN_CACHE_DIR"] = str(TIKTOKEN_CACHE_DIR)


setup_cache()


class CompatibleEmbeddings:
    """OpenAI 兼容协议的 Embedding 客户端。"""

    def __init__(self, model: str, api_key: str, base_url: str):
        """初始化 Embedding 客户端。

        Args:
            model: Embedding 模型名称。
            api_key: API 访问密钥。
            base_url: OpenAI 兼容接口地址。
        """
        if not model:
            raise ValueError("未配置 EMBEDDING_MODEL 或 OPENAI_EMBEDDINGS_MODEL")
        if not api_key:
            raise ValueError("未配置 EMBEDDING_API_KEY、OPENAI_EMBEDDING_API_KEY 或 OPENAI_API_KEY")
        if not base_url:
            raise ValueError("未配置 EMBEDDING_BASE_URL、OPENAI_EMBEDDING_BASE_URL 或 OPENAI_BASE_URL")

        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.max_batch_size = self._resolve_max_batch_size()

    def _resolve_max_batch_size(self) -> int:
        """解析当前 embedding 服务允许的最大批量数。

        Returns:
            单次 `/embeddings` 请求允许的最大输入条数。
        """
        normalized_base_url = self.client.base_url.host if self.client.base_url else ""
        normalized_model = self.model.lower()

        # DashScope 兼容模式下，text-embedding-v4 当前单批最多支持 10 条。
        if "dashscope.aliyuncs.com" in normalized_base_url or normalized_model == "text-embedding-v4":
            return 10

        # 其余 OpenAI 兼容服务先保守给一个较大的默认值。
        return 128

    def _chunk_texts(self, texts: List[str]) -> List[List[str]]:
        """按供应商限制切分批次，避免单次请求超限。"""
        batch_size = max(1, self.max_batch_size)
        return [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量生成文档向量。

        Args:
            texts: 待编码的文本列表。

        Returns:
            与输入顺序一致的向量列表。
        """
        normalized_texts = [text if isinstance(text, str) else str(text) for text in texts]
        embeddings: List[List[float]] = []

        # 针对 DashScope 等有单批上限的服务，自动拆分为多个子批次。
        for sub_batch in self._chunk_texts(normalized_texts):
            response = self.client.embeddings.create(
                model=self.model,
                input=sub_batch,
            )
            embeddings.extend(item.embedding for item in response.data)

        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """生成单条查询向量。

        Args:
            text: 查询文本。

        Returns:
            单条向量结果。
        """
        response = self.client.embeddings.create(
            model=self.model,
            input=text if isinstance(text, str) else str(text),
        )
        return response.data[0].embedding


def get_embeddings_model():
    config = {k: v for k, v in OPENAI_EMBEDDING_CONFIG.items() if v}
    # 显式使用兼容协议客户端，避免部分网关不接受 langchain_openai
    # 的内部 len-safe 分片格式，导致 embeddings 请求报 400。
    return CompatibleEmbeddings(
        model=config.get("model", ""),
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", ""),
    )


def get_llm_model():
    config = {k: v for k, v in OPENAI_LLM_CONFIG.items() if v is not None and v != ""}
    return ChatOpenAI(**config)

def get_stream_llm_model():
    callback_handler = AsyncIteratorCallbackHandler()
    # 将回调handler放进AsyncCallbackManager中
    manager = AsyncCallbackManager(handlers=[callback_handler])

    config = {k: v for k, v in OPENAI_LLM_CONFIG.items() if v is not None and v != ""}
    config.update({"streaming": True, "callbacks": manager})
    return ChatOpenAI(**config)

def count_tokens(text):
    """简单通用的token计数"""
    if not text:
        return 0
    
    model_name = (OPENAI_LLM_CONFIG.get("model") or "").lower()
    
    # 如果是deepseek，使用transformers
    if 'deepseek' in model_name:
        try:
            from transformers import AutoTokenizer
            # 显式指定缓存目录与镜像环境，避免在网络受限环境下反复走默认站点。
            tokenizer = AutoTokenizer.from_pretrained(
                "deepseek-ai/DeepSeek-V3",
                cache_dir=str(HF_HUB_CACHE),
                local_files_only=HF_HUB_OFFLINE == "1",
            )
            return len(tokenizer.encode(text))
        except:
            pass
    
    # 如果是gpt，使用tiktoken
    if 'gpt' in model_name:
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except:
            pass
    
    # 备用方案：简单计算
    chinese = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
    english = len(text) - chinese
    return chinese + english // 4

if __name__ == '__main__':
    # 测试llm
    llm = get_llm_model()
    print(llm.invoke("你好"))

    # 由于langchain版本问题，这个目前测试会报错
    # llm_stream = get_stream_llm_model()
    # print(llm_stream.invoke("你好"))

    # 测试embedding
    test_text = "你好，这是一个测试。"
    embeddings = get_embeddings_model()
    print(embeddings.embed_query(test_text))

    # 测试计数
    test_text = "Hello 你好世界"
    tokens = count_tokens(test_text)
    print(f"Token计数: '{test_text}' = {tokens} tokens")
