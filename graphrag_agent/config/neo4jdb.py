from typing import Dict, Any
import pandas as pd
from neo4j import GraphDatabase, Result
from langchain_neo4j import Neo4jGraph
from graphrag_agent.config.settings import NEO4J_CONFIG


class DBConnectionManager:
    """数据库连接管理器，实现单例模式"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DBConnectionManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        # 避免重复初始化
        if self._initialized:
            return
            
        # 从统一设置中获取连接信息
        self.neo4j_uri = NEO4J_CONFIG["uri"]
        self.neo4j_username = NEO4J_CONFIG["username"]
        self.neo4j_password = NEO4J_CONFIG["password"]
        self.max_pool_size = NEO4J_CONFIG["max_pool_size"]
        self.refresh_schema = NEO4J_CONFIG["refresh_schema"]

        # 使用惰性初始化，避免在模块导入阶段因 Neo4j 暂时不可用而导致服务启动失败。
        self._driver = None
        self._graph = None
        
        # 连接池配置
        self.session_pool = []
        
        # 标记为已初始化
        self._initialized = True
    
    @property
    def driver(self):
        """兼容旧代码，按需返回 Neo4j 驱动实例。"""
        return self.get_driver()

    @property
    def graph(self):
        """兼容旧代码，按需返回 LangChain Neo4j 图实例。"""
        return self.get_graph()

    def _build_driver(self):
        """创建 Neo4j 原生驱动。"""
        if not self.neo4j_uri:
            raise ValueError("未配置 NEO4J_URI")
        return GraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_username, self.neo4j_password),
            max_connection_pool_size=self.max_pool_size
        )

    def _build_graph(self):
        """创建 LangChain Neo4j 图实例。"""
        if not self.neo4j_uri:
            raise ValueError("未配置 NEO4J_URI")
        return Neo4jGraph(
            url=self.neo4j_uri,
            username=self.neo4j_username,
            password=self.neo4j_password,
            refresh_schema=self.refresh_schema,
        )

    def get_driver(self):
        """获取Neo4j驱动实例"""
        if self._driver is None:
            self._driver = self._build_driver()
        return self._driver
    
    def get_graph(self):
        """获取LangChain Neo4j图实例"""
        if self._graph is None:
            self._graph = self._build_graph()
        return self._graph
    
    def execute_query(self, cypher: str, params: Dict[str, Any] = {}) -> pd.DataFrame:
        """
        执行Cypher查询并返回结果
        
        参数:
            cypher: Cypher查询语句
            params: 查询参数
            
        返回:
            pd.DataFrame: 查询结果DataFrame
        """
        return self.get_driver().execute_query(
            cypher,
            parameters_=params,
            result_transformer_=Result.to_df
        )
    
    def get_session(self):
        """
        从连接池获取会话
        
        返回:
            neo4j.Session: Neo4j会话
        """
        if self.session_pool:
            # 从池中获取会话
            return self.session_pool.pop()
        else:
            # 创建新会话
            return self.get_driver().session()
    
    def release_session(self, session):
        """
        释放会话回连接池
        
        参数:
            session: Neo4j会话
        """
        if len(self.session_pool) < self.max_pool_size:
            self.session_pool.append(session)
        else:
            # 池已满，关闭会话
            session.close()
    
    def close(self):
        """关闭所有资源"""
        # 关闭所有池中的会话
        for session in self.session_pool:
            try:
                session.close()
            except:
                pass
        
        # 清空池
        self.session_pool = []
        
        # 关闭驱动
        if self._driver:
            self._driver.close()
            self._driver = None
        self._graph = None
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()


# 提供便捷的全局访问点
db_manager = DBConnectionManager()


def get_db_manager() -> DBConnectionManager:
    """获取数据库连接管理器实例"""
    return db_manager
