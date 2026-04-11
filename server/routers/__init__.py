from fastapi import APIRouter
from graphrag_agent.config.settings import GRAPH_ADMIN_ENABLED
from . import chat, feedback, knowledge_graph, source

# 创建总路由器
api_router = APIRouter()

# 包含各个子路由器
api_router.include_router(chat.router, tags=["聊天"])
api_router.include_router(feedback.router, tags=["反馈"])
api_router.include_router(knowledge_graph.router, tags=["知识图谱"])
api_router.include_router(source.router, tags=["源内容"])

if GRAPH_ADMIN_ENABLED:
    # 按需加载后台管理路由，避免未安装上传依赖时影响主系统启动。
    from . import admin

    api_router.include_router(admin.router, tags=["后台管理"])

__all__ = ['api_router']
