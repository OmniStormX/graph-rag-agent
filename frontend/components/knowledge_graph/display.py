import streamlit as st
from utils.api import get_knowledge_graph, get_kg_reasoning
from .visualization import visualize_knowledge_graph
import re


def _resolve_focus_node_id(kg_data, evidence_id: str | None):
    """根据选中的证据 ID 解析知识图谱中的目标节点。"""
    if not kg_data or not evidence_id:
        return None

    nodes = kg_data.get("nodes", [])
    node_ids = {node.get("id") for node in nodes if isinstance(node, dict)}
    if evidence_id in node_ids:
        return evidence_id

    focus_map = kg_data.get("focus_map", {})
    candidate_node_ids = focus_map.get(evidence_id, [])
    for node_id in candidate_node_ids:
        if node_id in node_ids:
            return node_id

    return None

def display_knowledge_graph_tab(tabs):
    """显示知识图谱标签页内容 - 懒加载"""
    with tabs[1]:
        st.markdown('<div class="kg-controls">', unsafe_allow_html=True)

        # 检查当前agent类型
        if st.session_state.agent_type == "naive_rag_agent":
            st.info("Naive RAG 是传统的向量搜索方式，没有知识图谱的可视化。")
            return
        elif st.session_state.agent_type == "deep_research_agent":
            st.info("Deep Research Agent 专注于深度推理过程，没有知识图谱的可视化。请查看执行轨迹标签页了解详细推理过程。")
            return
        elif st.session_state.agent_type == "fusion_agent":
            st.info("Fusion Agent 使用多种知识图谱技术进行融合分析。查看图谱可以了解实体间的关联和社区结构。")
        
        # 添加标签页，分离图谱显示和推理问答
        kg_tabs = st.tabs(["图谱显示", "推理问答"])
        
        with kg_tabs[0]:
            # 如果是从证据点击跳转而来，优先展示“回答相关图谱”。
            if st.session_state.get("selected_evidence_id"):
                st.session_state.kg_display_mode = "回答相关图谱"

            # 原有的图谱显示代码
            kg_display_mode = st.radio(
                "显示模式:",
                ["回答相关图谱", "全局知识图谱"],
                key="kg_display_mode",
                horizontal=True
            )
            st.markdown('</div>', unsafe_allow_html=True)
            
            # 使用会话状态跟踪是否需要加载图谱
            # 如果是第一次访问标签页或者切换了显示模式，才需要加载
            should_load_kg = False
            
            # 检查是否是第一次切换到这个标签或显示模式改变
            if "current_tab" in st.session_state and st.session_state.current_tab == "知识图谱":
                if "last_kg_mode" not in st.session_state or st.session_state.last_kg_mode != kg_display_mode:
                    should_load_kg = True
                    st.session_state.last_kg_mode = kg_display_mode
            
            # 显示相应的图谱
            if kg_display_mode == "回答相关图谱":
                # 原有的回答相关图谱代码
                if "current_kg_message" in st.session_state and st.session_state.current_kg_message is not None:
                    msg_idx = st.session_state.current_kg_message
                    
                    # 安全地检查索引是否有效以及kg_data是否存在
                    if (0 <= msg_idx < len(st.session_state.messages) and 
                        "kg_data" in st.session_state.messages[msg_idx] and 
                        st.session_state.messages[msg_idx]["kg_data"] is not None and
                        len(st.session_state.messages[msg_idx]["kg_data"].get("nodes", [])) > 0):
                        
                        # 获取相关回答的消息内容前20个字符用于显示
                        msg_preview = st.session_state.messages[msg_idx]["content"][:20] + "..."
                        st.success(f"显示与回答「{msg_preview}」相关的知识图谱")
                        kg_data = st.session_state.messages[msg_idx]["kg_data"]
                        focus_node_id = _resolve_focus_node_id(
                            kg_data,
                            st.session_state.get("selected_evidence_id"),
                        )
                        if focus_node_id:
                            st.info(f"已根据证据定位图谱节点：{focus_node_id}")
                            st.session_state.selected_focus_node_id = focus_node_id

                        # 显示图谱
                        visualize_knowledge_graph(kg_data, focus_node_id=focus_node_id)
                    else:
                        st.info("未找到与当前回答相关的知识图谱数据")
                        # 如果没有相关图谱数据，显示提示
                        st.warning("尝试加载全局知识图谱...")
                        with st.spinner("加载全局知识图谱..."):
                            kg_data = get_knowledge_graph(limit=100)
                            if kg_data and len(kg_data.get("nodes", [])) > 0:
                                focus_node_id = _resolve_focus_node_id(
                                    kg_data,
                                    st.session_state.get("selected_evidence_id"),
                                )
                                visualize_knowledge_graph(kg_data, focus_node_id=focus_node_id)
                else:
                    st.info("在调试模式下发送查询获取相关的知识图谱")
            else:
                # 全局知识图谱
                with st.spinner("加载全局知识图谱..."):
                    kg_data = get_knowledge_graph(limit=100)
                    if kg_data and len(kg_data.get("nodes", [])) > 0:
                        focus_node_id = _resolve_focus_node_id(
                            kg_data,
                            st.session_state.get("selected_evidence_id"),
                        )
                        visualize_knowledge_graph(kg_data, focus_node_id=focus_node_id)
                    else:
                        st.warning("未能加载全局知识图谱数据")
            
        with kg_tabs[1]:
            # 添加知识图谱推理问答界面
            st.markdown("## 知识图谱推理问答")
            st.markdown("探索实体之间的关系和路径，从知识图谱中发现深层次的关联。")
            
            # 选择推理类型
            reasoning_type = st.selectbox(
                "选择推理类型",
                options=[
                    "shortest_path", 
                    "one_two_hop", 
                    "common_neighbors",
                    "all_paths",
                    "entity_cycles",
                    "entity_influence",
                    "entity_community"
                ],
                format_func=lambda x: {
                    "shortest_path": "最短路径查询",
                    "one_two_hop": "一到两跳关系路径",
                    "common_neighbors": "共同邻居查询",
                    "all_paths": "关系路径查询",
                    "entity_cycles": "实体环路检测",
                    "entity_influence": "影响力分析",
                    "entity_community": "社区检测"
                }.get(x, x),
                key="kg_reasoning_type"
            )
            
            # 显示说明
            if reasoning_type == "shortest_path":
                st.info("查询两个实体之间的最短连接路径，了解它们如何关联。")
            elif reasoning_type == "one_two_hop":
                st.info("找出两个实体之间的直接关系或通过一个中间节点的间接关系。")
            elif reasoning_type == "common_neighbors":
                st.info("发现同时与两个实体相关联的其他实体（共同邻居）。")
            elif reasoning_type == "all_paths":
                st.info("探索两个实体之间的所有可能路径，了解它们之间的多种关联方式。")
            elif reasoning_type == "entity_cycles":
                st.info("检测实体的环路，发现循环依赖或递归关系。")
            elif reasoning_type == "entity_influence":
                st.info("分析实体的影响范围，找出它直接和间接关联的所有实体。")
            elif reasoning_type == "entity_community":
                st.info("发现实体所属的社区或集群，分析实体在更大知识网络中的位置。")
                # 添加社区检测算法选择
                algorithm = st.selectbox(
                    "社区检测算法",
                    options=["leiden", "sllpa"],
                    format_func=lambda x: {
                        "leiden": "Leiden算法",
                        "sllpa": "SLLPA算法"
                    }.get(x, x),
                    key="community_algorithm"
                )
                
                # 算法说明
                if algorithm == "leiden":
                    st.markdown("""
                    **Leiden算法**是一种优化的社区检测方法，与Louvain算法相似，但能更好地避免出现孤立社区。
                    适合较大规模的图谱，质量更高但计算量也更大。
                    """)
                else:
                    st.markdown("""
                    **SLLPA**（Speaker-Listener Label Propagation Algorithm）是一种标签传播算法，
                    能够快速检测重叠社区，适合中小规模的图谱，速度较快。
                    """)
            
            # 根据不同的推理类型显示不同的输入表单
            if reasoning_type in ["shortest_path", "one_two_hop", "common_neighbors", "all_paths"]:
                # 需要两个实体的推理类型
                col1, col2 = st.columns(2)
                
                with col1:
                    entity_a = st.text_input("实体A", key="kg_entity_a", 
                                            help="输入第一个实体的名称")
                
                with col2:
                    entity_b = st.text_input("实体B", key="kg_entity_b", 
                                            help="输入第二个实体的名称")
                
                # 对于路径类查询，增加最大深度选项
                if reasoning_type in ["shortest_path", "all_paths"]:
                    max_depth = st.slider("最大深度/跳数", 1, 5, 3, key="kg_max_depth",
                                        help="限制搜索的最大深度")
                else:
                    max_depth = 1  # 默认值
                
                # 推理按钮
                if st.button("执行推理", key="kg_reasoning_button", 
                            help="点击执行知识图谱推理"):
                    if not entity_a or not entity_b:
                        st.error("请输入两个实体名称")
                    else:
                        with st.spinner("正在执行知识图谱推理..."):
                            # 显示处理中的信息
                            process_info = st.empty()
                            process_info.info(f"正在处理: {reasoning_type} 查询 (可能需要几秒钟...)")
                            
                            try:
                                # 调用API获取推理结果
                                result = get_kg_reasoning(
                                    reasoning_type=reasoning_type,
                                    entity_a=entity_a,
                                    entity_b=entity_b,
                                    max_depth=max_depth
                                )
                                
                                # 清除处理信息
                                process_info.empty()
                                
                                # 检查错误
                                if "error" in result and result["error"]:
                                    st.error(f"推理失败: {result['error']}")
                                    return
                                
                                if len(result.get("nodes", [])) == 0:
                                    st.warning("未找到相关的推理结果")
                                    return
                                    
                                # 显示结果信息
                                display_reasoning_result(reasoning_type, result, entity_a, entity_b)
                                
                                # 显示可视化图谱
                                visualize_knowledge_graph(result)
                            except Exception as e:
                                process_info.empty()
                                st.error(f"处理请求时出错: {str(e)}")
                                import traceback
                                st.error(traceback.format_exc())
            else:
                # 只需要一个实体的推理类型 (entity_cycles, entity_influence, entity_community)
                entity_id = st.text_input("实体名称", key="kg_entity_single", 
                                        help="输入实体的名称")
                
                # 设置最大深度
                max_depth = st.slider("最大深度", 1, 4, 2, key="kg_max_depth_single",
                                    help="限制搜索的最大深度")
                
                # 获取社区检测算法
                algorithm = st.session_state.get("community_algorithm", "leiden") if reasoning_type == "entity_community" else None
                
                # 推理按钮
                if st.button("执行推理", key="kg_reasoning_button_single", 
                           help="点击执行知识图谱推理"):
                    if not entity_id:
                        st.error("请输入实体名称")
                    else:
                        with st.spinner("正在执行知识图谱推理..."):
                            # 显示处理中的信息
                            process_info = st.empty()
                            process_info.info(f"正在处理: {reasoning_type} 查询 (可能需要几秒钟...)")
                            
                            try:
                                # 调用API获取推理结果
                                result = get_kg_reasoning(
                                    reasoning_type=reasoning_type,
                                    entity_a=entity_id,
                                    max_depth=max_depth,
                                    algorithm=algorithm
                                )
                                
                                # 清除处理信息
                                process_info.empty()
                                
                                # 检查错误
                                if "error" in result and result["error"]:
                                    st.error(f"推理失败: {result['error']}")
                                    return
                                
                                if len(result.get("nodes", [])) == 0:
                                    st.warning("未找到相关的推理结果")
                                    return
                                
                                # 显示结果
                                display_reasoning_result(reasoning_type, result, entity_id)
                                
                                # 显示可视化图谱
                                visualize_knowledge_graph(result)
                            except Exception as e:
                                process_info.empty()
                                st.error(f"处理请求时出错: {str(e)}")
                                import traceback
                                st.error(traceback.format_exc())
            
            # 添加使用说明
            with st.expander("📖 推理问答使用指南", expanded=False):
                st.markdown("""
                ### 知识图谱推理功能使用指南
                
                本功能允许您探索知识图谱中实体之间的关系和结构。以下是各种推理类型的说明：
                
                #### 1. 最短路径查询
                查找两个实体之间的最短连接路径，帮助您理解它们是如何关联的。
                - **输入**: 实体A和实体B的名称
                - **参数**: 最大跳数（限制搜索深度）
                - **输出**: 最短路径可视化和路径长度
                
                #### 2. 一到两跳关系路径
                查找两个实体之间的直接关系或通过一个中间节点的间接关系。
                - **输入**: 实体A和实体B的名称
                - **输出**: 所有一跳或两跳路径的列表和可视化
                
                #### 3. 共同邻居查询
                发现同时与两个实体相关联的其他实体（共同邻居）。
                - **输入**: 实体A和实体B的名称
                - **输出**: 共同邻居列表和可视化网络
                
                #### 4. 关系路径查询
                探索两个实体之间的所有可能路径，不限于最短路径。
                - **输入**: 实体A和实体B的名称
                - **参数**: 最大深度（限制搜索深度）
                - **输出**: 发现的所有路径和可视化
                
                #### 5. 实体环路检测
                检测一个实体的环路，即从该实体出发，经过一系列关系后再次回到该实体的路径。
                - **输入**: 实体名称
                - **参数**: 最大环路长度
                - **输出**: 环路列表和可视化
                
                #### 6. 影响力分析
                分析一个实体的影响范围，找出它直接和间接关联的所有实体。
                - **输入**: 实体名称
                - **参数**: 最大深度
                - **输出**: 影响统计和可视化网络
                
                #### 7. 社区检测
                发现实体所属的社区或集群，分析实体在更大知识网络中的位置。
                - **输入**: 实体名称
                - **参数**: 最大深度（定义社区范围）和算法选择
                - **输出**: 社区统计和可视化
                - **算法**: 
                  - Leiden算法 - 精准度更高，适合复杂图谱
                  - SLLPA算法 - 速度更快，适合中小型图谱
                
                ### 使用技巧
                
                - 对于大型知识图谱，建议先限制较小的搜索深度，然后根据需要增加
                - 在可视化图谱中，可以双击节点聚焦，右键点击节点查看更多选项
                - 单击空白处可重置图谱视图
                - 使用右上角的控制面板进行图谱导航
                """)
            
            # 添加图例
            with st.expander("🎨 图谱可视化图例", expanded=False):
                st.markdown("""
                ### 图谱节点颜色说明
                
                - **蓝色**: 源实体/查询实体
                - **红色**: 目标实体
                - **绿色**: 中间节点/共同邻居
                - **紫色**: 社区1成员
                - **青色**: 社区2成员
                - **黄色**: 其他社区成员
                
                ### 图谱交互指南
                
                - **双击节点**: 聚焦显示该节点及其直接相连的节点
                - **右键点击节点**: 打开上下文菜单，提供更多操作
                - **单击空白处**: 重置视图，显示所有节点
                - **拖拽节点**: 手动调整布局
                - **滚轮缩放**: 放大或缩小视图
                - **右上角控制面板**: 提供额外功能，如重置和返回上一步
                """)

def display_reasoning_result(reasoning_type, result, entity_a=None, entity_b=None):
    """根据推理类型显示不同的结果信息，使用实体名称而不是ID"""
    if reasoning_type == "shortest_path":
        if "path_info" in result:
            # 使用实体名称替换原始路径信息中的ID
            path_info = result["path_info"]
            if entity_a and entity_b:
                path_info = path_info.replace(entity_a, f"'{entity_a}'")
                path_info = path_info.replace(entity_b, f"'{entity_b}'")
            st.success(f"{path_info} (长度: {result['path_length']})")
    
    elif reasoning_type == "one_two_hop":
        if "paths_info" in result:
            st.success(f"找到 {result['path_count']} 条路径")
            if result["path_count"] > 0:
                with st.expander("查看详细路径", expanded=True):
                    for i, path in enumerate(result["paths_info"]):
                        # 替换路径中的ID为更友好的显示
                        formatted_path = format_path_with_names(path)
                        st.markdown(f"**路径 {i+1}**: {formatted_path}")
    
    elif reasoning_type == "common_neighbors":
        if "common_neighbors" in result:
            st.success(f"找到 {result['neighbor_count']} 个共同邻居")
            if result["neighbor_count"] > 0:
                # 格式化显示共同邻居，使用更友好的名称格式
                neighbors = [format_entity_name(neighbor) for neighbor in result["common_neighbors"]]
                neighbors_str = ", ".join(neighbors)
                if len(neighbors_str) > 200:  # 如果太长就截断
                    neighbors_str = neighbors_str[:200] + "..."
                st.write(f"共同邻居: {neighbors_str}")
                
                # 显示在可折叠区域中的完整列表
                if len(result["common_neighbors"]) > 5:
                    with st.expander("查看所有共同邻居", expanded=False):
                        for i, neighbor in enumerate(result["common_neighbors"]):
                            st.markdown(f"- {format_entity_name(neighbor)}")
    
    elif reasoning_type == "all_paths":
        if "paths_info" in result:
            st.success(f"找到 {result['path_count']} 条路径")
            if result["path_count"] > 0:
                with st.expander("查看详细路径", expanded=True):
                    for i, path in enumerate(result["paths_info"]):
                        # 格式化路径
                        formatted_path = format_path_with_names(path)
                        st.markdown(f"**路径 {i+1}**: {formatted_path}")
    
    elif reasoning_type == "entity_cycles":
        if "cycles_info" in result:
            st.success(f"找到 {result['cycle_count']} 个环路")
            if result["cycle_count"] > 0:
                with st.expander("查看环路详情", expanded=True):
                    for i, cycle in enumerate(result["cycles_info"]):
                        # 格式化环路描述
                        formatted_desc = format_path_with_names(cycle["description"])
                        st.markdown(f"**环路 {i+1}** (长度: {cycle['length']}): {formatted_desc}")
    
    elif reasoning_type == "entity_influence":
        if "influence_stats" in result:
            stats = result["influence_stats"]
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("直接关联实体", stats["direct_connections"])
            with col2:
                st.metric("总关联实体", stats["total_connections"])
            with col3:
                st.metric("关系类型数", len(stats["connection_types"]))
            
            # 显示关系类型分布
            if stats["connection_types"]:
                st.subheader("关系类型分布")
                for rel_type in stats["connection_types"]:
                    st.markdown(f"- **{rel_type['type']}**: {rel_type['count']}次")
    
    elif reasoning_type == "entity_community":
        if "communities" in result:
            st.success(f"检测到 {result['community_count']} 个社区")
            
            # 显示实体所属社区，使用实体名称
            if "entity_community" in result:
                entity_name = entity_a if entity_a else "当前实体"
                st.info(f"实体'{entity_name}'所属社区: {result['entity_community']}")
            
            # 显示社区详情
            if result["communities"]:
                with st.expander("查看社区详情", expanded=True):
                    for comm in result["communities"]:
                        contains = "✓" if comm["contains_center"] else "✗" 
                        st.markdown(f"**社区 {comm['id']}** (包含中心实体: {contains})")
                        st.markdown(f"- 成员数量: {comm['size']}")
                        st.markdown(f"- 连接密度: {comm['density']:.2f}")
                        
                        # 格式化样本成员
                        if "sample_members" in comm and comm["sample_members"]:
                            sample_members = [format_entity_name(member) for member in comm["sample_members"]]
                            sample_str = ", ".join(sample_members)
                            if len(sample_str) > 100:  # 如果太长就截断
                                sample_str = sample_str[:100] + "..."
                            st.markdown(f"- 样本成员: {sample_str}")
                        
                        st.markdown("---")
                        
        # 如果有社区摘要信息，显示它
        if "community_info" in result and isinstance(result["community_info"], dict):
            info = result["community_info"]
            if "summary" in info and info["summary"]:
                with st.expander("社区摘要", expanded=True):
                    st.markdown(f"""
                    **社区ID**: {info.get('id', 'N/A')}
                    
                    **实体数量**: {info.get('entity_count', 0)}
                    
                    **关系数量**: {info.get('relation_count', 0)}
                    
                    **摘要**:
                    {info.get('summary', '无摘要')}
                    """)

def format_entity_name(entity_id):
    """将实体ID格式化为友好的显示名称"""
    if not entity_id:
        return "未知实体"
    
    # 如果实体ID看起来是一个数字，保持原样
    if isinstance(entity_id, (int, float)) or (isinstance(entity_id, str) and entity_id.isdigit()):
        return str(entity_id)
    
    # 否则，使用引号包围实体名称
    return f"'{entity_id}'"

def format_path_with_names(path):
    """将路径中的实体ID格式化为友好的显示名称"""
    if not path:
        return ""
    
    # 替换路径中的实体ID
    formatted = path
    
    # 识别并替换路径中的实体ID
    entity_pattern = r'\b([a-zA-Z0-9_\u4e00-\u9fa5]+)\b'
    
    def replace_entity(match):
        entity = match.group(1)
        
        # 跳过关系名称（通常在方括号内）
        if "-[" in match.string[max(0, match.start()-2):match.start()]:
            return entity
        
        # 跳过关系类型
        if match.start() > 0 and match.string[match.start()-1:match.start()+len(entity)+1] == f"[{entity}]":
            return entity
        
        return format_entity_name(entity)
    
    # 应用替换
    formatted = re.sub(entity_pattern, replace_entity, formatted)
    
    return formatted

def get_node_color(node_type, is_center=False):
    """根据节点类型和是否为中心节点返回颜色"""
    from frontend_config.settings import NODE_TYPE_COLORS, KG_COLOR_PALETTE
    
    # 如果是中心节点，直接返回中心节点颜色
    if is_center:
        return NODE_TYPE_COLORS["Center"]
    
    # 检查是否有预定义的颜色映射
    if node_type in NODE_TYPE_COLORS:
        return NODE_TYPE_COLORS[node_type]
    
    # 处理社区节点
    if isinstance(node_type, str) and "Community" in node_type:
        try:
            # 提取社区ID数字部分
            comm_id_str = node_type.replace("Community", "")
            # 确保处理空字符串情况
            if not comm_id_str:
                comm_id = 0
            else:
                comm_id = int(comm_id_str)
                
            # 使用社区ID取模获取颜色索引
            color_index = (comm_id - 1) % len(KG_COLOR_PALETTE) if comm_id > 0 else 0
            return KG_COLOR_PALETTE[color_index]
        except (ValueError, TypeError):
            # 转换失败，使用默认颜色
            return "#757575"  # 灰色
    
    # 其他类型节点使用默认颜色
    return "#757575"  # 灰色
