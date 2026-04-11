import re
from typing import List, Tuple

from graphrag_agent.config.settings import CHUNK_SIZE, OVERLAP, MAX_TEXT_LENGTH

try:
    import pysbd
except ImportError:  # pragma: no cover - 依赖缺失时回退到正则断句
    pysbd = None

class ChineseTextChunker:
    """中英混合文本分块器，将长文本分割成带有重叠的文本块。"""
    
    def __init__(self, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP, max_text_length: int = MAX_TEXT_LENGTH):
        """
        初始化分块器
        
        Args:
            chunk_size: 每个文本块的目标大小（tokens数量）
            overlap: 相邻文本块的重叠大小（tokens数量）
            max_text_length: HanLP处理的最大文本长度，超过此长度将进行预分割
        """
        if chunk_size <= overlap:
            raise ValueError("chunk_size必须大于overlap")
            
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.max_text_length = max_text_length
        self.tokenizer = None
        self._hanlp_module = None
        self.english_sentence_segmenter = (
            pysbd.Segmenter(language="en", clean=False)
            if pysbd is not None else None
        )
        
    def process_files(self, file_contents: List[Tuple[str, str]]) -> List[Tuple[str, str, List[List[str]]]]:
        """
        处理多个文件的内容
        
        Args:
            file_contents: List of (filename, content) tuples
            
        Returns:
            List of (filename, content, chunks) tuples
        """
        results = []
        for filename, content in file_contents:
            chunks = self.chunk_text(content)
            results.append((filename, content, chunks))
        return results
    
    def _preprocess_large_text(self, text: str) -> List[str]:
        """
        预处理过大的文本，将其分割成较小的段落
        
        Args:
            text: 原始文本
            
        Returns:
            分割后的文本段落列表
        """
        if len(text) <= self.max_text_length:
            return [text]
        
        # 计算合适的段落大小（确保不超过最大长度，但也不要太小）
        target_segment_size = min(self.max_text_length, max(10000, self.max_text_length // 2))
        
        # 首先按段落分割
        paragraphs = text.split('\n\n')
        
        # 如果段落数量很少，尝试按单个换行符分割
        if len(paragraphs) < 5:
            paragraphs = text.split('\n')
        
        # 重新组合段落，确保每个段落不超过目标大小
        processed_segments = []
        current_segment = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
                
            # 如果当前段落本身就超长，需要进一步分割
            if len(para) > target_segment_size:
                # 先保存当前积累的内容
                if current_segment:
                    processed_segments.append(current_segment)
                    current_segment = ""
                
                # 分割超长段落
                split_paras = self._split_long_paragraph(para, target_segment_size)
                processed_segments.extend(split_paras)
                
            else:
                # 检查添加当前段落是否会超长
                if len(current_segment) + len(para) + 2 > target_segment_size:  # +2 for \n\n
                    if current_segment:
                        processed_segments.append(current_segment)
                    current_segment = para
                else:
                    if current_segment:
                        current_segment += "\n\n" + para
                    else:
                        current_segment = para
        
        # 添加最后的segment
        if current_segment:
            processed_segments.append(current_segment)
        
        return processed_segments
    
    def _split_long_paragraph(self, text: str, max_size: int) -> List[str]:
        """
        分割超长段落
        
        Args:
            text: 超长段落文本
            max_size: 最大分割大小
            
        Returns:
            分割后的段落列表
        """
        if len(text) <= max_size:
            return [text]
        
        # 按句子分割
        sentences = re.split(r'([。！？.!?])', text)
        
        # 重新组合句子和标点
        combined_sentences = []
        for i in range(0, len(sentences) - 1, 2):
            sentence = sentences[i]
            punctuation = sentences[i + 1] if i + 1 < len(sentences) else ""
            if sentence.strip():
                combined_sentences.append(sentence + punctuation)
        
        # 如果没有找到句子边界，按固定长度分割
        if not combined_sentences:
            result = []
            for i in range(0, len(text), max_size):
                result.append(text[i:i + max_size])
            return result
        
        # 重新组合句子，确保不超过最大长度
        segments = []
        current_segment = ""
        
        for sentence in combined_sentences:
            # 如果单个句子就超长，强制分割
            if len(sentence) > max_size:
                if current_segment:
                    segments.append(current_segment)
                    current_segment = ""
                
                # 按固定长度分割超长句子
                for i in range(0, len(sentence), max_size):
                    segments.append(sentence[i:i + max_size])
            else:
                # 检查添加当前句子是否会超长
                if len(current_segment) + len(sentence) > max_size:
                    if current_segment:
                        segments.append(current_segment)
                    current_segment = sentence
                else:
                    current_segment += sentence
        
        # 添加最后的segment
        if current_segment:
            segments.append(current_segment)
        
        return segments
    
    def _safe_tokenize(self, text: str) -> List[str]:
        """
        安全的分词方法，处理可能的异常
        
        Args:
            text: 要分词的文本
            
        Returns:
            分词结果列表
        """
        try:
            tokenizer = self._get_or_create_tokenizer()
            if tokenizer is None:
                return list(text)

            # 检查文本长度
            if len(text) > self.max_text_length:
                return list(text)
            
            tokens = tokenizer(text)
            return tokens if tokens else []
        except Exception:
            return list(text)

    def _get_or_create_tokenizer(self):
        """按需初始化中文分词器，避免英文构建也触发 HanLP/Torch 启动。"""
        if self.tokenizer is not None:
            return self.tokenizer

        try:
            if self._hanlp_module is None:
                import hanlp

                self._hanlp_module = hanlp
            self.tokenizer = self._hanlp_module.load(
                self._hanlp_module.pretrained.tok.COARSE_ELECTRA_SMALL_ZH
            )
        except Exception:
            self.tokenizer = None
        return self.tokenizer
        
    def chunk_text(self, text: str) -> List[List[str]]:
        """
        将单个文本分割成块
        
        Args:
            text: 要分割的文本
            
        Returns:
            分割后的文本块列表，每个块是token列表
        """
        # 处理空文本或太短的文本
        if not text or len(text) < self.chunk_size / 10:
            tokens = self._safe_tokenize(text)
            return [tokens] if tokens else []

        # 英文教材优先使用句子级切块，避免中文分词器导致切片零碎、信息密度偏低。
        if self._is_english_dominant(text):
            return self._chunk_english_text(text)
        
        # 预处理过大文本
        text_segments = self._preprocess_large_text(text)
        
        # 处理每个文本段落
        all_chunks = []
        for segment in text_segments:
            segment_chunks = self._chunk_single_segment(segment)
            all_chunks.extend(segment_chunks)
        
        return all_chunks
    
    def _chunk_single_segment(self, text: str) -> List[List[str]]:
        """
        处理单个文本段落的分块
        
        Args:
            text: 单个文本段落
            
        Returns:
            分块结果
        """
        if not text:
            return []
            
        # 先将整个文本分词
        all_tokens = self._safe_tokenize(text)
        if not all_tokens:
            return []
        
        chunks = []
        start_pos = 0
        dynamic_overlap = self._compute_dynamic_overlap(len(all_tokens))
        
        while start_pos < len(all_tokens):
            # 确定当前块的结束位置
            end_pos = min(start_pos + self.chunk_size, len(all_tokens))
            
            # 如果不是最后一块，尝试在句子边界结束
            if end_pos < len(all_tokens):
                # 寻找句子结束位置
                sentence_end = self._find_next_sentence_end(all_tokens, end_pos)
                if sentence_end <= start_pos + self.chunk_size + 100:  # 允许略微超出
                    end_pos = sentence_end
            
            # 提取当前块
            chunk = all_tokens[start_pos:end_pos]
            chunk_text = ''.join(chunk).strip()
            if chunk and not self._is_low_value_chinese_chunk(chunk_text):
                chunks.append(chunk)
            
            # 计算下一块的起始位置（考虑重叠）
            if end_pos >= len(all_tokens):
                break
                
            # 寻找重叠的起始位置
            overlap_start = max(start_pos, end_pos - dynamic_overlap)
            next_sentence_start = self._find_previous_sentence_end(all_tokens, overlap_start)
            
            # 如果找到合适的句子开始位置，使用它；否则使用计算的重叠位置
            if next_sentence_start > start_pos and next_sentence_start < end_pos:
                start_pos = next_sentence_start
            else:
                start_pos = overlap_start
                
            # 防止无限循环
            if start_pos >= end_pos:
                start_pos = end_pos
        
        return chunks

    def _compute_dynamic_overlap(self, token_count: int) -> int:
        """根据分块规模动态调整重叠，避免固定 overlap 造成重复上下文过大。"""
        if token_count <= self.chunk_size:
            return 0
        base_overlap = min(self.overlap, max(20, int(self.chunk_size * 0.15)))
        if token_count > self.chunk_size * 4:
            return max(20, int(base_overlap * 0.7))
        return base_overlap
    
    def _is_sentence_end(self, token: str) -> bool:
        """判断token是否为句子结束符"""
        return token in ['。', '！', '？', '.', '!', '?']
    
    def _find_next_sentence_end(self, tokens: List[str], start_pos: int) -> int:
        """从指定位置向后查找句子结束位置"""
        for i in range(start_pos, len(tokens)):
            if self._is_sentence_end(tokens[i]):
                return i + 1
        return len(tokens)
    
    def _find_previous_sentence_end(self, tokens: List[str], start_pos: int) -> int:
        """从指定位置向前查找句子结束位置"""
        for i in range(start_pos - 1, -1, -1):
            if self._is_sentence_end(tokens[i]):
                return i + 1
        return 0

    def _is_english_dominant(self, text: str) -> bool:
        """判断文本是否以英文为主。"""
        letters = re.findall(r"[A-Za-z]", text)
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        if not letters:
            return False
        return len(letters) > max(120, len(chinese_chars) * 2)

    def _chunk_english_text(self, text: str) -> List[List[str]]:
        """对英文主导文本执行句子级切块。

        处理策略：
            1. 基于段落组织输入，优先保留原始语义边界。
            2. 使用 pySBD 进行英文断句；若依赖不存在，则回退到正则方案。
            3. 按 token 预算累积句子，并保留轻量 overlap。
            4. 过滤图注、题号、目录碎片等低价值块。
        """
        normalized_text = re.sub(r"\n{3,}", "\n\n", text)
        paragraphs = [
            self._normalize_english_paragraph(segment)
            for segment in normalized_text.split("\n\n")
            if segment.strip()
        ]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        if not paragraphs:
            return [list(normalized_text)] if normalized_text.strip() else []

        target_tokens = max(self.chunk_size, 220)
        overlap_tokens = max(int(target_tokens * 0.12), 40)
        chunks: List[List[str]] = []
        current_sentences: List[str] = []
        current_tokens = 0

        for paragraph in paragraphs:
            if self._is_noise_paragraph(paragraph):
                continue

            paragraph_sentences = self._split_english_sentences(paragraph)
            if not paragraph_sentences:
                continue

            for sentence in paragraph_sentences:
                normalized_sentence = self._normalize_english_sentence(sentence)
                if not normalized_sentence or self._is_noise_sentence(normalized_sentence):
                    continue

                fragments = self._split_long_english_sentence(
                    normalized_sentence,
                    max_tokens=max(target_tokens // 2, 120),
                )
                for fragment in fragments:
                    fragment_tokens = self._estimate_english_tokens(fragment)
                    if current_sentences and current_tokens + fragment_tokens > target_tokens:
                        finalized_chunk = self._finalize_english_chunk(current_sentences)
                        if finalized_chunk:
                            chunks.append(list(finalized_chunk))

                        current_sentences = self._build_overlap_sentences(
                            current_sentences,
                            overlap_tokens,
                        )
                        current_tokens = self._sum_sentence_tokens(current_sentences)

                    current_sentences.append(fragment)
                    current_tokens += fragment_tokens

            # 段落边界轻微收束，避免将过多段落挤进同一块。
            if current_sentences and current_tokens >= int(target_tokens * 0.88):
                finalized_chunk = self._finalize_english_chunk(current_sentences)
                if finalized_chunk:
                    chunks.append(list(finalized_chunk))
                current_sentences = self._build_overlap_sentences(
                    current_sentences,
                    overlap_tokens,
                )
                current_tokens = self._sum_sentence_tokens(current_sentences)

        if current_sentences:
            finalized_chunk = self._finalize_english_chunk(current_sentences)
            if finalized_chunk:
                chunks.append(list(finalized_chunk))

        return chunks

    def _split_english_sentences(self, text: str) -> List[str]:
        """按英文句子边界切分文本。"""
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []

        if self.english_sentence_segmenter is not None:
            parts = self.english_sentence_segmenter.segment(normalized)
            return [part.strip() for part in parts if part.strip()]

        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])", normalized)
        return [part.strip() for part in parts if part.strip()]

    def _split_long_english_sentence(self, sentence: str, max_tokens: int) -> List[str]:
        """拆分超长英文句子，优先在从句边界切开。"""
        if self._estimate_english_tokens(sentence) <= max_tokens:
            return [sentence]

        clauses = re.split(r"(?<=[,;:])\s+", sentence)
        if len(clauses) <= 1:
            return self._split_english_fragment_by_words(sentence, max_tokens)

        fragments: List[str] = []
        current_fragment = ""
        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue
            candidate = f"{current_fragment} {clause}".strip()
            if current_fragment and self._estimate_english_tokens(candidate) > max_tokens:
                fragments.append(current_fragment)
                current_fragment = clause
            else:
                current_fragment = candidate
        if current_fragment:
            fragments.append(current_fragment)
        return fragments or self._split_english_fragment_by_words(sentence, max_tokens)

    def _normalize_english_paragraph(self, paragraph: str) -> str:
        """清洗英文段落，减少 PDF 版式残留。"""
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        normalized = normalized.replace("ﬁ", "fi").replace("ﬂ", "fl")
        normalized = normalized.replace("–", "-").replace("—", "-")
        normalized = re.sub(r"\b([A-Za-z])\s+([A-Za-z]{1,2})\b", r"\1 \2", normalized)
        return normalized

    def _normalize_english_sentence(self, sentence: str) -> str:
        """进一步清洗句子级文本。"""
        normalized = re.sub(r"\s+", " ", sentence).strip(" -\t\r\n")
        normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
        return normalized

    def _estimate_english_tokens(self, text: str) -> int:
        """近似估算英文 token 数，用于控制 chunk 预算。

        说明：
            这里不强依赖 tiktoken，避免为构建流程引入新的重量级依赖。
            对英文教材文本，按单词和标点近似估算即可满足分块预算控制。
        """
        units = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?|[^\w\s]", text)
        return len(units)

    def _sum_sentence_tokens(self, sentences: List[str]) -> int:
        """计算句子列表的近似 token 总量。"""
        return sum(self._estimate_english_tokens(sentence) for sentence in sentences)

    def _build_overlap_sentences(
        self,
        sentences: List[str],
        overlap_tokens: int,
    ) -> List[str]:
        """基于句子级重叠构造下一块的起始上下文。"""
        if not sentences:
            return []

        overlap_sentences: List[str] = []
        running_tokens = 0
        for sentence in reversed(sentences):
            overlap_sentences.insert(0, sentence)
            running_tokens += self._estimate_english_tokens(sentence)
            if running_tokens >= overlap_tokens:
                break
        return overlap_sentences

    def _finalize_english_chunk(self, sentences: List[str]) -> str:
        """整理英文块文本并过滤低价值内容。"""
        chunk_text = " ".join(sentence.strip() for sentence in sentences if sentence.strip())
        chunk_text = re.sub(r"\s+", " ", chunk_text).strip()
        if not chunk_text:
            return ""
        if self._is_low_quality_chunk(chunk_text):
            return ""
        return chunk_text

    def _is_noise_paragraph(self, paragraph: str) -> bool:
        """过滤明显属于目录、图注或题号页的段落。"""
        stripped = paragraph.strip()
        if not stripped:
            return True
        if "final pdf to printer" in stripped.lower():
            return True
        if re.match(r"^figure\s+", stripped, flags=re.IGNORECASE) and len(stripped) < 220:
            return True
        if re.match(r"^cyu\s+\d", stripped, flags=re.IGNORECASE):
            return True
        if re.match(r"^\d+[–-]\d+\b", stripped):
            return True
        if stripped.count(".") >= 8 and len(stripped.split()) < 30:
            return True
        return False

    def _is_noise_sentence(self, sentence: str) -> bool:
        """过滤低价值句子，减少图号与习题噪声进入 chunk。"""
        stripped = sentence.strip()
        if not stripped:
            return True
        if "final pdf to printer" in stripped.lower():
            return True
        if re.match(r"^figure\s+", stripped, flags=re.IGNORECASE) and len(stripped) < 220:
            return True
        if re.match(r"^cyu\s+\d", stripped, flags=re.IGNORECASE):
            return True
        if re.match(r"^\d+[–-]\d+\b", stripped):
            return True
        if "answer:" in stripped.lower() and len(stripped) < 240:
            return True
        if len(re.findall(r"[A-Za-z]", stripped)) < 8 and len(re.findall(r"\d", stripped)) > 4:
            return True
        return False

    def _is_low_quality_chunk(self, chunk_text: str) -> bool:
        """过滤整体质量偏低的英文块。"""
        token_count = self._estimate_english_tokens(chunk_text)
        if token_count < max(30, int(self.chunk_size * 0.08)):
            return True

        lower_text = chunk_text.lower()
        if lower_text.count("figure") >= 2 and token_count < 120:
            return True
        if lower_text.count("cyu") >= 2:
            return True
        if re.fullmatch(r"[\W\d\s]+", chunk_text):
            return True
        return False

    def _is_low_value_chinese_chunk(self, chunk_text: str) -> bool:
        """过滤中文或混合文本中的低价值块，减少无效抽取。"""
        normalized = re.sub(r"\s+", "", chunk_text)
        if not normalized:
            return True

        chinese_count = len(re.findall(r"[\u4e00-\u9fff]", normalized))
        english_count = len(re.findall(r"[A-Za-z]", normalized))
        if chinese_count + english_count < max(20, int(self.chunk_size * 0.06)):
            return True

        if re.fullmatch(r"[\W\d_]+", normalized):
            return True

        if normalized.count("图") >= 2 and len(normalized) < 80:
            return True
        if normalized.count("表") >= 2 and len(normalized) < 80:
            return True
        if len(set(normalized)) / max(len(normalized), 1) < 0.12 and len(normalized) > 100:
            return True
        return False

    def _split_english_fragment_by_words(self, text: str, max_tokens: int) -> List[str]:
        """在无明显从句边界时按词级预算切分英文长句。"""
        words = text.split()
        if not words:
            return []

        fragments: List[str] = []
        current_words: List[str] = []
        current_tokens = 0
        for word in words:
            word_tokens = self._estimate_english_tokens(word)
            if current_words and current_tokens + word_tokens > max_tokens:
                fragments.append(" ".join(current_words))
                current_words = [word]
                current_tokens = word_tokens
            else:
                current_words.append(word)
                current_tokens += word_tokens

        if current_words:
            fragments.append(" ".join(current_words))
        return fragments
    
    def get_text_stats(self, text: str) -> dict:
        """
        获取文本统计信息
        
        Args:
            text: 输入文本
            
        Returns:
            包含文本统计信息的字典
        """
        stats = {
            'text_length': len(text),
            'needs_preprocessing': len(text) > self.max_text_length,
            'estimated_chunks': max(1, len(text) // self.chunk_size),
            'paragraphs': len(text.split('\n\n')),
            'lines': len(text.split('\n'))
        }
        
        if stats['needs_preprocessing']:
            segments = self._preprocess_large_text(text)
            stats['preprocessed_segments'] = len(segments)
            stats['max_segment_length'] = max(len(seg) for seg in segments) if segments else 0
            
        return stats
