from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from graphrag_agent.config.settings import community_algorithm


class ChatRequest(BaseModel):
    """聊天请求模型"""
    message: str
    session_id: str
    debug: bool = False
    agent_type: str = "naive_rag_agent"
    use_deeper_tool: Optional[bool] = True
    show_thinking: Optional[bool] = False


class ChatResponse(BaseModel):
    """聊天响应模型"""
    answer: str
    execution_log: Optional[List[Dict]] = None
    kg_data: Optional[Dict] = None
    kg_cache_key: Optional[str] = None
    reference: Optional[Dict] = None
    iterations: Optional[List[Dict]] = None


class SourceRequest(BaseModel):
    """源内容请求模型"""
    source_id: str


class SourceResponse(BaseModel):
    """源内容响应模型"""
    content: str
    source_id: Optional[str] = None
    source_type: Optional[str] = None
    title: Optional[str] = None
    file_name: Optional[str] = None
    chunk_id: Optional[str] = None
    community_id: Optional[str] = None
    summary: Optional[str] = None
    full_content: Optional[str] = None
    text: Optional[str] = None
    position: Optional[int] = None
    length: Optional[int] = None
    content_offset: Optional[int] = None
    error: Optional[str] = None


class SourceInfoResponse(BaseModel):
    """源文件信息响应模型"""
    file_name: str


class ClearRequest(BaseModel):
    """清除聊天历史请求模型"""
    session_id: str


class ClearResponse(BaseModel):
    """清除聊天历史响应模型"""
    status: str
    remaining_messages: Optional[str] = None


class ClearCacheRequest(BaseModel):
    """清除缓存请求模型"""
    session_id: str
    agent_type: Optional[str] = None


class ClearCacheResponse(BaseModel):
    """清除缓存响应模型"""
    status: str
    message: Optional[str] = None


class FeedbackRequest(BaseModel):
    """反馈请求模型"""
    message_id: str
    query: str
    is_positive: bool
    thread_id: str
    agent_type: Optional[str] = "naive_rag_agent"


class FeedbackResponse(BaseModel):
    """反馈响应模型"""
    status: str
    action: str

class SourceInfoBatchRequest(BaseModel):
    source_ids: List[str]

class ContentBatchRequest(BaseModel):
    chunk_ids: List[str]

class ReasoningRequest(BaseModel):
    reasoning_type: str
    entity_a: str
    entity_b: Optional[str] = None
    max_depth: Optional[int] = 3
    algorithm: Optional[str] = community_algorithm


class KnowledgeGraphFromMessageRequest(BaseModel):
    """基于回答文本或缓存键获取知识图谱的请求模型。"""
    session_id: Optional[str] = None
    message: Optional[str] = None
    query: Optional[str] = None
    kg_cache_key: Optional[str] = None

class EntityData(BaseModel):
    id: str
    name: str
    type: str
    description: Optional[str] = ""
    properties: Optional[Dict[str, Any]] = {}

class EntityUpdateData(BaseModel):
    id: str
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None

class EntitySearchFilter(BaseModel):
    term: Optional[str] = None
    type: Optional[str] = None
    limit: Optional[int] = 100

class RelationData(BaseModel):
    source: str
    type: str
    target: str
    description: Optional[str] = ""
    weight: Optional[float] = 0.5
    properties: Optional[Dict[str, Any]] = {}

class RelationUpdateData(BaseModel):
    source: str
    original_type: str
    target: str
    new_type: Optional[str] = None
    description: Optional[str] = None
    weight: Optional[float] = None
    properties: Optional[Dict[str, Any]] = None

class RelationSearchFilter(BaseModel):
    source: Optional[str] = None
    target: Optional[str] = None
    type: Optional[str] = None
    limit: Optional[int] = 100

class EntityDeleteData(BaseModel):
    id: str

class RelationDeleteData(BaseModel):
    source: str
    type: str
    target: str


class BuildRequest(BaseModel):
    """后台构建请求。"""
    version_name: Optional[str] = None
    document_revision_ids: Optional[List[str]] = None


class ActivateVersionRequest(BaseModel):
    """激活或回滚版本请求。"""
    activate: bool = True


class CorrectionRuleCreateRequest(BaseModel):
    """修正规则创建请求。"""
    rule_type: str
    title: str
    content: str
    scope_type: str = "global"
    scope_id: Optional[str] = None
    enabled: bool = True


class BuildJobItem(BaseModel):
    """后台构建任务条目。"""
    job_id: str
    version_id: str
    job_type: str
    status: str
    message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    log_path: Optional[str] = None


class BuildJobPageResponse(BaseModel):
    """后台构建任务分页响应。"""
    items: List[BuildJobItem]
    total: int
    page: int
    page_size: int
    total_pages: int
    keyword: Optional[str] = None
    status: Optional[str] = None


class AdminStatusResponse(BaseModel):
    """后台系统状态响应。"""
    metadata_db_connected: bool
    neo4j_connected: bool
    active_version_id: Optional[str] = None
    active_version_name: Optional[str] = None
    latest_job: Optional[BuildJobItem] = None
    document_count: int = 0
    version_count: int = 0


class LogResponse(BaseModel):
    """日志查看响应。"""
    path: Optional[str] = None
    lines: List[str]


class AdminActionRequest(BaseModel):
    """后台进程控制请求。"""
    target: str
    action: str


class AdminResetRequest(BaseModel):
    """后台重置请求。"""
    confirm: bool = False
