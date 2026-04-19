import uvicorn
from fastapi import FastAPI
from graphrag_agent.config.settings import GRAPH_ADMIN_ENABLED
from server.routers import api_router
from server.server_config.database import get_db_manager
from server.server_config.settings import UVICORN_CONFIG
from server.services.admin_metadata_service import metadata_service
from server.services.agent_service import agent_manager

# 初始化 FastAPI 应用
app = FastAPI(title="知识图谱问答系统", description="基于知识图谱的智能问答系统后端API")

# 添加路由
app.include_router(api_router)

# 获取数据库连接
db_manager = get_db_manager()
driver = db_manager.driver


@app.on_event("startup")
def startup_event():
    """应用启动时初始化后台元数据表。"""
    if GRAPH_ADMIN_ENABLED and metadata_service.available:
        metadata_service.initialize_schema()


@app.on_event("shutdown")
def shutdown_event():
    """应用关闭时清理资源"""
    # 关闭所有Agent资源
    agent_manager.close_all()
    
    # 关闭Neo4j连接
    if driver:
        driver.close()
        print("已关闭Neo4j连接")


# 启动服务器
if __name__ == "__main__":
    # 使用包路径启动，避免容器和本地脚本入口的导入行为不一致。
    uvicorn.run("server.main:app", **UVICORN_CONFIG)
