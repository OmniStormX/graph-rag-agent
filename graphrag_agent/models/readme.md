# Model 模块

## 目录结构

```
graphrag_agent/models/
├── __init__.py          # 模块初始化文件
├── get_models.py        # 模型获取和初始化功能
└── test_stream_model.py # 流式模型测试
```

## 模块说明

Model 模块负责初始化和管理各种语言模型，主要基于 LangChain 框架实现了对 OpenAI API 的集成，支持普通调用和流式输出两种模式。

### 核心功能

1. **模型初始化**：支持从环境变量加载配置参数，灵活配置模型行为

2. **支持的模型类型**：
   - 嵌入模型 (Embeddings)：用于文本向量化
   - 对话模型 (LLM)：支持普通和流式两种输出方式

3. **流式输出支持**：通过 AsyncIteratorCallbackHandler 实现逐字输出能力

### 核心函数

- `get_embeddings_model()`：初始化并返回文本嵌入模型，用于向量化查询和文档
- `get_llm_model()`：初始化并返回标准对话模型，用于一次性生成完整回答
- `get_stream_llm_model()`：初始化并返回流式对话模型，支持逐字输出，提升用户体验

### 使用方法

```python
# 标准模型使用示例
from graphrag_agent.models.get_models import get_llm_model

llm = get_llm_model()
response = llm.invoke("你好")
print(response)

# 流式模型使用示例(注：由于langchain bug，这里需要改源码才能使用，本项目采用模拟流式输出)
import asyncio
from graphrag_agent.models.get_models import get_stream_llm_model
from langchain_core.messages import HumanMessage

async def main():
    chat = get_stream_llm_model()
    messages = [HumanMessage(content="Tell me a short joke.")]
    async for chunk in chat.astream(messages):
        print(chunk.content, end="", flush=True)

asyncio.run(main())
```

### 配置说明

模块依赖以下环境变量：
- `CHAT_API_KEY`: Chat 模型 API 密钥
- `CHAT_BASE_URL`: Chat 模型 OpenAI 兼容 API 地址
- `CHAT_MODEL`: Chat 模型名称
- `EMBEDDING_API_KEY`: Embedding 模型 API 密钥
- `EMBEDDING_BASE_URL`: Embedding 模型 OpenAI 兼容 API 地址
- `EMBEDDING_MODEL`: Embedding 模型名称
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_LLM_MODEL`: 旧版兜底配置
- `OPENAI_EMBEDDING_MODEL` / `OPENAI_EMBEDDINGS_MODEL`: 旧版 Embedding 模型名兜底配置
- `TEMPERATURE`: 模型温度参数
- `MAX_TOKENS`: 最大生成token数
