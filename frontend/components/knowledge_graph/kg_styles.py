# 知识图谱CSS样式
KG_STYLES = """
<style>
    .vis-network {
        border: 1px solid rgba(29, 29, 31, 0.08);
        border-radius: 18px;
        box-shadow: 0 12px 32px rgba(0,0,0,0.08);
        position: relative;
        background: #fbfbfd;
    }
    .vis-tooltip {
        background-color: rgba(255, 255, 255, 0.98) !important;
        color: #1d1d1f !important;
        border: 1px solid rgba(29, 29, 31, 0.08) !important;
        border-radius: 12px !important;
        padding: 10px 12px !important;
        font-family: 'Helvetica Neue', Arial, sans-serif !important;
        box-shadow: 0 12px 28px rgba(0,0,0,0.12) !important;
    }
    /* 增加节点悬停动画效果 */
    .vis-node:hover {
        transform: scale(1.1);
        transition: all 0.3s ease;
    }
    
    /* Neo4j风格右键菜单样式 */
    .node-context-menu {
        position: absolute;
        background: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(29, 29, 31, 0.08);
        border-radius: 14px;
        padding: 8px 0;
        box-shadow: 0 16px 36px rgba(0,0,0,0.14);
        z-index: 1000;
        min-width: 180px;
    }
    
    .node-context-menu-item {
        padding: 8px 12px;
        cursor: pointer;
        color: #1d1d1f;
    }

    .node-context-menu-item:hover {
        background-color: #f5f5f7;
    }

    .node-context-menu-header {
        padding: 6px 12px;
        font-weight: 600;
        border-bottom: 1px solid rgba(29, 29, 31, 0.06);
    }
    
    /* 控制面板样式 */
    .graph-control-panel {
        position: absolute;
        top: 16px;
        right: 16px;
        z-index: 999;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(29, 29, 31, 0.08);
        border-radius: 16px;
        padding: 12px;
        box-shadow: 0 16px 36px rgba(0,0,0,0.12);
        min-width: 210px;
        backdrop-filter: blur(12px);
    }
    
    .graph-control-button {
        display: block;
        width: 100%;
        margin: 6px 0;
        padding: 8px 12px;
        background-color: #ffffff;
        border: 1px solid rgba(29, 29, 31, 0.08);
        border-radius: 999px;
        cursor: pointer;
        text-align: left;
        color: #1d1d1f;
    }

    .graph-control-button:hover {
        background-color: #eef5ff;
        border-color: rgba(0, 113, 227, 0.18);
    }

    .graph-info {
        font-size: 12px;
        margin-top: 10px;
        color: rgba(29, 29, 31, 0.64);
        border-top: 1px solid rgba(29, 29, 31, 0.06);
        padding-top: 10px;
    }
</style>
"""
