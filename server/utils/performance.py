import time
import functools

from graphrag_agent.runtime_logging import emit_runtime_log


def measure_performance(endpoint_name):
    """
    性能测量装饰器
    
    Args:
        endpoint_name: API端点名称
        
    Returns:
        装饰后的函数
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                
                # 记录性能
                duration = time.time() - start_time
                emit_runtime_log(
                    "api.performance",
                    endpoint=endpoint_name,
                    duration=duration,
                    duration_ms=round(duration * 1000, 2),
                )
                
                return result
            except Exception as e:
                # 记录异常和性能
                duration = time.time() - start_time
                emit_runtime_log(
                    "api.error",
                    endpoint=endpoint_name,
                    error=str(e),
                    duration=duration,
                    duration_ms=round(duration * 1000, 2),
                )
                raise
                
        return wrapper
    return decorator
