import streamlit as st

from utils.state import (
    init_session_state,
)
from components.styles import custom_css
from components.chat import display_chat_interface
from components.sidebar import display_sidebar
from components.debug import display_debug_panel
from utils.performance import init_performance_monitoring

def main():
    """主应用入口函数"""
    # 页面配置
    st.set_page_config(
        page_title="GraphRAG Chat Interface",
        page_icon="🤖",
        layout="wide"
    )
    
    # 初始化会话状态
    init_session_state()
    
    # 初始化性能监控
    init_performance_monitoring()
    
    # 添加自定义CSS
    custom_css()
    
    # 显示侧边栏
    display_sidebar()
    
    # 主区域布局
    if st.session_state.debug_mode:
        # 调试模式下的布局（左侧聊天，右侧调试信息）
        col1, col2 = st.columns([5, 4])
        
        with col1:
            display_chat_interface()
            
        with col2:
            display_debug_panel()
    else:
        # 非调试模式下的布局（仅聊天界面）
        display_chat_interface()

if __name__ == "__main__":
    import shutup
    shutup.please()
    main()
