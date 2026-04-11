import time
import os
import pickle
import concurrent.futures
import re
from typing import Dict, List, Tuple, Optional
from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
)

from graphrag_agent.graph.core import retry, generate_hash, is_non_retryable_llm_error
from graphrag_agent.config.settings import MAX_WORKERS as DEFAULT_MAX_WORKERS, BATCH_SIZE as DEFAULT_BATCH_SIZE
from graphrag_agent.config.prompts.graph_prompts import (
    system_template_build_graph_batch,
    human_template_build_graph_batch,
)

class EntityRelationExtractor:
    """
    实体关系提取器，负责从文本中提取实体和关系。
    使用LLM分析文本块，生成结构化的实体和关系数据。
    """
    
    def __init__(self, llm, system_template, human_template,
             entity_types: List[str], relationship_types: List[str],
             cache_dir="./cache/graph", max_workers=4, batch_size=5,
             batch_system_template: Optional[str] = None,
             batch_human_template: Optional[str] = None):
        """
        初始化实体关系提取器
        
        Args:
            llm: 语言模型
            system_template: 系统提示模板
            human_template: 用户提示模板
            entity_types: 实体类型列表
            relationship_types: 关系类型列表
            cache_dir: 缓存目录
            max_workers: 并行工作线程数
            batch_size: 批处理大小
        """
        self.llm = llm
        self.entity_types = entity_types
        self.relationship_types = relationship_types
        self.chat_history = []
        
        # 设置分隔符
        self.tuple_delimiter = " : "
        self.record_delimiter = "\n"
        self.completion_delimiter = "\n\n"
        
        # 创建提示模板
        system_message_prompt = SystemMessagePromptTemplate.from_template(system_template)
        human_message_prompt = HumanMessagePromptTemplate.from_template(human_template)
        
        self.chat_prompt = ChatPromptTemplate.from_messages([
            system_message_prompt,
            MessagesPlaceholder("chat_history"),
            human_message_prompt
        ])

        batch_system_message_prompt = SystemMessagePromptTemplate.from_template(
            batch_system_template or system_template_build_graph_batch
        )
        batch_human_message_prompt = HumanMessagePromptTemplate.from_template(
            batch_human_template or human_template_build_graph_batch
        )
        self.batch_chat_prompt = ChatPromptTemplate.from_messages([
            batch_system_message_prompt,
            MessagesPlaceholder("chat_history"),
            batch_human_message_prompt,
        ])
        
        # 创建处理链
        self.chain = self.chat_prompt | self.llm
        self.batch_chain = self.batch_chat_prompt | self.llm
        
        # 缓存设置
        self.cache_dir = cache_dir
        self.enable_cache = True
        
        # 确保缓存目录存在
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        
        # 并行处理配置
        self.max_workers = max_workers or DEFAULT_MAX_WORKERS
        self.batch_size = batch_size or DEFAULT_BATCH_SIZE
        
        # 缓存统计
        self.cache_hits = 0
        self.cache_misses = 0

    @staticmethod
    def _build_empty_result() -> str:
        """返回空抽取结果，保持上游写图流程兼容。"""
        return ""

    def _should_skip_chunk(self, text: str) -> bool:
        """跳过明显低价值 chunk，减少无效 LLM 调用。"""
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) < 40:
            return True

        chinese_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
        english_words = re.findall(r"[A-Za-z]{2,}", normalized)
        informative_units = len(chinese_chars) + len(english_words)
        if informative_units < 20:
            return True

        if re.fullmatch(r"[\W\d_]+", normalized):
            return True

        lower_text = normalized.lower()
        if lower_text.count("figure") >= 2 and len(normalized) < 300:
            return True
        if lower_text.count("table") >= 2 and len(normalized) < 300:
            return True
        if normalized.count(".") >= 8 and len(normalized.split()) < 25:
            return True

        # 对较长的自然语言正文不要轻易跳过。
        # 之前基于“字符去重率”的判定会把英文教材正文误判为重复文本，
        # 进而导致整批 chunk 被跳过，表现为 0 个实体 / 0 个关系。
        word_count = len(normalized.split())
        if word_count >= 80:
            return False

        # 改为更稳妥的“词级别多样性”判定，仅用于中短文本的噪声过滤。
        informative_tokens = re.findall(r"[\u4e00-\u9fff]|[A-Za-z]{2,}", lower_text)
        unique_token_ratio = len(set(informative_tokens)) / max(len(informative_tokens), 1)
        if 30 <= len(informative_tokens) <= 120 and unique_token_ratio < 0.2:
            return True
        return False
        
    def _generate_cache_key(self, text: str) -> str:
        """
        生成文本的缓存键
        
        Args:
            text: 输入文本
            
        Returns:
            str: 缓存键
        """
        return generate_hash(text)
    
    def _cache_path(self, cache_key: str) -> str:
        """
        获取缓存文件路径
        
        Args:
            cache_key: 缓存键
            
        Returns:
            str: 缓存文件路径
        """
        return os.path.join(self.cache_dir, f"{cache_key}.pkl")
    
    def _save_to_cache(self, cache_key: str, result: str) -> None:
        """
        保存结果到缓存
        
        Args:
            cache_key: 缓存键
            result: 结果
        """
        if not self.enable_cache:
            return
            
        cache_path = self._cache_path(cache_key)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(result, f)
        except Exception as e:
            print(f"缓存保存错误: {e}")
    
    def _load_from_cache(self, cache_key: str) -> Optional[str]:
        """
        从缓存加载结果
        
        Args:
            cache_key: 缓存键
            
        Returns:
            Optional[str]: 缓存的结果，如果不存在则返回None
        """
        if not self.enable_cache:
            return None
            
        cache_path = self._cache_path(cache_key)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    result = pickle.load(f)
                    self.cache_hits += 1
                    return result
            except Exception as e:
                print(f"缓存加载错误: {e}")
        
        self.cache_misses += 1
        return None
        
    def process_chunks(self, file_contents: List[Tuple], progress_callback=None) -> List[Tuple]:
        """
        并行处理所有文件的所有chunks
        
        Args:
            file_contents: 文件内容列表
            progress_callback: 进度回调函数
            
        Returns:
            List[Tuple]: 处理结果
        """
        t0 = time.time()
        chunk_index = 0
        total_chunks = sum(len(file_content[2]) for file_content in file_contents)
        
        # 使用多线程分配策略
        for i, file_content in enumerate(file_contents):
            chunks = file_content[2]
            
            # 预检查缓存命中率
            cache_keys = [self._generate_cache_key(''.join(chunk)) for chunk in chunks]
            cached_results = {key: self._load_from_cache(key) for key in cache_keys}
            non_cached_indices = [idx for idx, key in enumerate(cache_keys) if cached_results[key] is None]

            # 对缓存命中的 chunk 也同步推进进度，避免进度条与实际处理量不一致。
            cached_count = len(chunks) - len(non_cached_indices)
            if progress_callback and cached_count > 0:
                for _ in range(cached_count):
                    progress_callback(chunk_index)
                    chunk_index += 1
            
            if len(non_cached_indices) > 0:
                # 只为未缓存的chunks创建任务
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    # 创建任务字典
                    future_to_chunk = {}
                    for idx in non_cached_indices:
                        chunk_text = ''.join(chunks[idx])
                        if self._should_skip_chunk(chunk_text):
                            empty_result = self._build_empty_result()
                            cached_results[cache_keys[idx]] = empty_result
                            self._save_to_cache(cache_keys[idx], empty_result)
                            continue
                        future = executor.submit(self._process_single_chunk, chunk_text)
                        future_to_chunk[future] = idx
                    
                    # 处理完成的任务
                    for future in concurrent.futures.as_completed(future_to_chunk):
                        chunk_idx = future_to_chunk[future]
                        try:
                            result = future.result()
                            cached_results[cache_keys[chunk_idx]] = result
                            
                            # 更新进度
                            if progress_callback:
                                progress_callback(chunk_index)
                            chunk_index += 1
                            
                        except Exception as exc:
                            print(f'Chunk {chunk_idx} 处理异常: {exc}')
                            if is_non_retryable_llm_error(exc):
                                print("检测到不可重试的模型调用错误，跳过该 Chunk 的重复重试。")
                                empty_result = self._build_empty_result()
                                cached_results[cache_keys[chunk_idx]] = empty_result
                                self._save_to_cache(cache_keys[chunk_idx], empty_result)
                                continue
                            # 重试逻辑
                            retry_count = 0
                            while retry_count < 3:
                                try:
                                    print(f'尝试重试 Chunk {chunk_idx}, 第 {retry_count+1} 次')
                                    result = self._process_single_chunk(''.join(chunks[chunk_idx]))
                                    cached_results[cache_keys[chunk_idx]] = result
                                    break
                                except Exception as retry_exc:
                                    if is_non_retryable_llm_error(retry_exc):
                                        print("重试阶段检测到不可重试错误，终止当前 Chunk。")
                                        empty_result = self._build_empty_result()
                                        cached_results[cache_keys[chunk_idx]] = empty_result
                                        self._save_to_cache(cache_keys[chunk_idx], empty_result)
                                        break
                                    print(f'重试失败: {retry_exc}')
                                    retry_count += 1
                                    time.sleep(1)  # 短暂延迟
                            
                            if cached_results[cache_keys[chunk_idx]] is None:
                                empty_result = self._build_empty_result()
                                cached_results[cache_keys[chunk_idx]] = empty_result
                                self._save_to_cache(cache_keys[chunk_idx], empty_result)
            
            # 整理结果，保持原始顺序
            ordered_results = [cached_results[key] for key in cache_keys]
            file_content.append(ordered_results)
            
            # 输出缓存统计
            cache_ratio = self.cache_hits / (self.cache_hits + self.cache_misses) * 100 if (self.cache_hits + self.cache_misses) > 0 else 0
            print(f"文件 {i+1}/{len(file_contents)} 处理完成, 缓存命中率: {cache_ratio:.1f}%")
        
        process_time = time.time() - t0
        print(f"所有chunks处理完成, 总耗时: {process_time:.2f}秒, 平均每chunk: {process_time/total_chunks:.2f}秒")
        return file_contents
    
    def process_chunks_batch(self, file_contents: List[Tuple], progress_callback=None) -> List[Tuple]:
        """
        批量处理chunks，减少LLM调用次数
        
        Args:
            file_contents: 文件内容列表
            progress_callback: 进度回调函数
            
        Returns:
            List[Tuple]: 处理结果
        """
        for file_content in file_contents:
            chunks = file_content[2]
            results = []
            
            # 智能动态批处理大小
            chunk_lengths = [len(''.join(chunk)) for chunk in chunks]
            avg_chunk_size = sum(chunk_lengths) / len(chunk_lengths) if chunk_lengths else 0
            
            # 根据平均chunk大小动态调整批处理大小
            dynamic_batch_size = max(1, min(self.batch_size, int(10000 / (avg_chunk_size + 1))))
            total_batches = max(1, (len(chunks) + dynamic_batch_size - 1) // dynamic_batch_size)
            
            # 按批次处理
            for i in range(0, len(chunks), dynamic_batch_size):
                batch_chunks = chunks[i:i+dynamic_batch_size]
                batch_number = i // dynamic_batch_size + 1
                
                # 缓存检查
                batch_keys = [self._generate_cache_key(''.join(chunk)) for chunk in batch_chunks]
                cached_batch_results = [self._load_from_cache(key) for key in batch_keys]
                cached_count = sum(1 for item in cached_batch_results if item is not None)

                # 批次开始时先发出一次进度提示，避免长时间停留在 0%。
                if progress_callback:
                    progress_callback(
                        {
                            "event": "batch_started",
                            "batch_index": batch_number,
                            "batch_total": total_batches,
                            "chunk_start": i,
                            "chunk_end": i + len(batch_chunks),
                            "chunk_total": len(chunks),
                            "cached_count": cached_count,
                        }
                    )
                
                # 如果所有结果都已缓存，则跳过LLM调用
                if None not in cached_batch_results:
                    results.extend(cached_batch_results)
                    if progress_callback:
                        for j in range(len(batch_chunks)):
                            progress_callback(i + j)
                    continue
                
                # 准备批处理输入
                indexed_batch_inputs: List[Tuple[int, str]] = []
                batch_results: List[str] = [self._build_empty_result()] * len(batch_chunks)
                for idx, chunk in enumerate(batch_chunks):
                    if cached_batch_results[idx] is not None:
                        batch_results[idx] = cached_batch_results[idx]
                        continue
                    chunk_text = ''.join(chunk)
                    if self._should_skip_chunk(chunk_text):
                        batch_results[idx] = self._build_empty_result()
                        self._save_to_cache(batch_keys[idx], batch_results[idx])
                        continue
                    indexed_batch_inputs.append((idx, chunk_text))

                if not indexed_batch_inputs:
                    results.extend(batch_results)
                    if progress_callback:
                        for j in range(len(batch_chunks)):
                            progress_callback(i + j)
                        progress_callback(
                            {
                                "event": "batch_completed",
                                "batch_index": batch_number,
                                "batch_total": total_batches,
                                "chunk_start": i,
                                "chunk_end": i + len(batch_chunks),
                                "chunk_total": len(chunks),
                            }
                        )
                    continue

                batch_text = self._format_batch_input(indexed_batch_inputs)
                
                try:
                    batch_response = self.batch_chain.invoke({
                        "chat_history": self.chat_history,
                        "entity_types": self.entity_types,
                        "relationship_types": self.relationship_types,
                        "tuple_delimiter": self.tuple_delimiter,
                        "record_delimiter": self.record_delimiter,
                        "input_text": batch_text
                    })

                    parsed_batch_results = self._parse_batch_response(batch_response.content)
                    missing_indices = []
                    for idx, _ in indexed_batch_inputs:
                        parsed_result = parsed_batch_results.get(idx)
                        if parsed_result is None:
                            missing_indices.append(idx)
                            continue
                        batch_results[idx] = parsed_result
                        self._save_to_cache(batch_keys[idx], parsed_result)

                    for idx in missing_indices:
                        individual_result = self._process_single_chunk(''.join(batch_chunks[idx]))
                        batch_results[idx] = individual_result

                    results.extend(batch_results)
                except Exception as e:
                    print(f"批处理错误，切换到单个处理: {e}")
                    for idx, chunk in enumerate(batch_chunks):
                        try:
                            cached_result = cached_batch_results[idx]
                            if cached_result is not None:
                                results.append(cached_result)
                                continue
                            chunk_text = ''.join(chunk)
                            if self._should_skip_chunk(chunk_text):
                                empty_result = self._build_empty_result()
                                self._save_to_cache(batch_keys[idx], empty_result)
                                results.append(empty_result)
                                continue
                            individual_result = self._process_single_chunk(chunk_text)
                            results.append(individual_result)
                        except Exception as e2:
                            print(f"单个chunk处理失败: {e2}")
                            results.append("")
                
                # 更新进度
                if progress_callback:
                    for j in range(len(batch_chunks)):
                        progress_callback(i + j)
                    progress_callback(
                        {
                            "event": "batch_completed",
                            "batch_index": batch_number,
                            "batch_total": total_batches,
                            "chunk_start": i,
                            "chunk_end": i + len(batch_chunks),
                            "chunk_total": len(chunks),
                        }
                    )
            
            file_content.append(results)
        
        return file_contents

    def _format_batch_input(self, batch_inputs: List[Tuple[int, str]]) -> str:
        """构造稳定的批量输入协议，避免模型输出无法拆分。"""
        blocks = []
        for idx, text in batch_inputs:
            blocks.append(f"[CHUNK_START:{idx}]\n{text}\n[CHUNK_END:{idx}]")
        return "\n\n".join(blocks)

    def _parse_batch_response(self, batch_content: str) -> Dict[int, str]:
        """
        解析批量响应，将其拆分为按 chunk 编号索引的结果。
        
        Args:
            batch_content: 批处理响应内容
            
        Returns:
            Dict[int, str]: chunk 编号到结果文本的映射
        """
        pattern = re.compile(
            r"\[RESULT_START:(\d+)\](.*?)\[RESULT_END:\1\]",
            flags=re.DOTALL,
        )
        parsed_results: Dict[int, str] = {}
        for match in pattern.finditer(batch_content):
            chunk_idx = int(match.group(1))
            parsed_results[chunk_idx] = match.group(2).strip()
        return parsed_results
    
    @retry(times=3, exceptions=(Exception,), delay=1.0)
    def _process_single_chunk(self, input_text: str) -> str:
        """
        处理单个文本块（带缓存）
        
        Args:
            input_text: 输入文本
            
        Returns:
            str: 处理结果
        """
        # 生成缓存键
        cache_key = self._generate_cache_key(input_text)
        
        # 尝试从缓存加载
        cached_result = self._load_from_cache(cache_key)
        if cached_result:
            return cached_result

        if self._should_skip_chunk(input_text):
            empty_result = self._build_empty_result()
            self._save_to_cache(cache_key, empty_result)
            return empty_result
        
        # 未缓存，调用LLM处理
        response = self.chain.invoke({
            "chat_history": self.chat_history,
            "entity_types": self.entity_types,
            "relationship_types": self.relationship_types,
            "tuple_delimiter": self.tuple_delimiter,
            "record_delimiter": self.record_delimiter,
            "completion_delimiter": self.completion_delimiter,
            "input_text": input_text
        })
        
        result = response.content
        
        # 保存结果到缓存
        self._save_to_cache(cache_key, result)
        
        return result
    
    def stream_process_large_files(self, file_path: str, chunk_size: int = 5000, 
                                   structure_builder=None, graph_writer=None) -> None:
        """
        以流式方式处理大文件，避免一次性加载全部内容
        
        Args:
            file_path: 文件路径
            chunk_size: 块大小
            structure_builder: 结构构建器
            graph_writer: 图写入器
        """
        if not structure_builder or not graph_writer:
            print("需要提供structure_builder和graph_writer才能进行流式处理")
            return
            
        def text_chunks_iterator(file_path, chunk_size):
            with open(file_path, 'r', encoding='utf-8') as f:
                chunk = []
                chars_count = 0
                for line in f:
                    chunk.append(line)
                    chars_count += len(line)
                    if chars_count >= chunk_size:
                        yield chunk
                        chunk = []
                        chars_count = 0
                if chunk:  # 不要忘记最后一个可能不满的chunk
                    yield chunk
        
        # 处理文件的元数据
        file_name = os.path.basename(file_path)
        file_type = os.path.splitext(file_name)[1]
        
        # 创建文档节点
        structure_builder.create_document(
            type=file_type,
            uri=file_path,
            file_name=file_name,
            domain="document"
        )
        
        # 流式处理文件
        chunks = []
        for chunk in text_chunks_iterator(file_path, chunk_size):
            chunks.append(chunk)
        
        # 创建chunk之间的关系
        chunks_with_hash = structure_builder.create_relation_between_chunks(
            file_name, chunks
        )
        
        # 并行处理所有chunks
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 创建任务
            future_to_chunk = {}
            for chunk_data in chunks_with_hash:
                chunk_text = chunk_data['chunk_doc'].page_content
                cache_key = self._generate_cache_key(chunk_text)
                cached_result = self._load_from_cache(cache_key)
                
                if cached_result:
                    # 如果缓存命中，直接处理结果
                    try:
                        graph_document = graph_writer.convert_to_graph_document(
                            chunk_data['chunk_id'],
                            chunk_data['chunk_doc'].page_content,
                            cached_result
                        )
                        
                        if len(graph_document.nodes) > 0 or len(graph_document.relationships) > 0:
                            graph_writer.graph.add_graph_documents(
                                [graph_document],
                                baseEntityLabel=True,
                                include_source=True
                            )
                    except Exception as e:
                        print(f"处理缓存结果时出错: {e}")
                else:
                    # 如果缓存未命中，提交任务
                    future = executor.submit(self._process_single_chunk, chunk_text)
                    future_to_chunk[future] = chunk_data
            
            # 处理结果并写入图数据库
            for future in concurrent.futures.as_completed(future_to_chunk):
                chunk_data = future_to_chunk[future]
                try:
                    result = future.result()
                    
                    # 实时写入一个chunk的结果到图数据库
                    graph_document = graph_writer.convert_to_graph_document(
                        chunk_data['chunk_id'],
                        chunk_data['chunk_doc'].page_content,
                        result
                    )
                    
                    if len(graph_document.nodes) > 0 or len(graph_document.relationships) > 0:
                        graph_writer.graph.add_graph_documents(
                            [graph_document],
                            baseEntityLabel=True,
                            include_source=True
                        )
                        
                except Exception as exc:
                    print(f"处理chunk {chunk_data['chunk_id']} 时发生错误: {exc}")
