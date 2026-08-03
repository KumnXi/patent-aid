"""
RAG（检索增强生成）引擎

将专利文本分块向量化，支持语义检索，为专利撰写过程提供相关参考内容。

技术方案: TF-IDF + BM25排序（轻量级，无需下载模型，适合52篇专利的规模）
后续可升级为sentence-transformers嵌入模型以提升检索质量。

检索维度:
- 技术问题 → 相关背景技术和现有方案
- 技术方案描述 → 相似的权利要求写法
- 技术效果关键词 → 效果表述模板
- 技术方法 → 具体实施方式参考
"""

import json
import re
import time
import numpy as np
import scipy.sparse as sp
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.parsers.patent_parser import StructuredPatent
from src.utils.text_utils import ChineseTextProcessor, ipc_to_str
from src.core.embedding_client import EmbeddingClient


@dataclass
class DocumentChunk:
    """文档块——RAG检索的基本单元"""
    chunk_id: str
    patent_id: str
    section_type: str  # background | claims | solution | effects | implementation
    text: str
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "chunk_id": self.chunk_id,
            "patent_id": self.patent_id,
            "section_type": self.section_type,
            "text": self.text,  # 保留全文（加载后仍可完整检索/展示）
            "metadata": self.metadata,
        }


@dataclass
class RetrievalResult:
    """检索结果"""
    chunk: DocumentChunk
    score: float
    relevance_reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "chunk_id": self.chunk.chunk_id,
            "patent_id": self.chunk.patent_id,
            "section_type": self.chunk.section_type,
            "text_preview": self.chunk.text[:200],
            "score": round(self.score, 4),
            "reason": self.relevance_reason,
        }


class RAGEngine:
    """RAG引擎

    构建专利文本索引，提供多维度检索能力。

    使用方式:
        rag = RAGEngine()
        rag.build_index(patents)
        results = rag.retrieve("虚拟电厂调频策略", top_k=5)
        context = rag.generate_writing_context("光伏功率预测方法")
    """

    # 索引结构版本号：分块逻辑/元数据变更时递增，旧索引自动作废重建
    INDEX_SCHEMA_VERSION = 5

    def __init__(self, storage_path: str = "data/rag_index"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.text_processor = ChineseTextProcessor()

        # 文档块存储
        self.chunks: List[DocumentChunk] = []
        self.chunks_by_type: Dict[str, List[int]] = defaultdict(list)
        self.chunks_by_patent: Dict[str, List[int]] = defaultdict(list)

        # 稠密向量（可选，需 embedding API；可用时与 TF-IDF 做 RRF 混合检索）
        self.embedder = EmbeddingClient()
        self.dense_vectors: Optional[np.ndarray] = None

        # TF-IDF向量化器（使用jieba中文分词）
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            tokenizer=self._chinese_tokenizer,
            token_pattern=None,  # 禁用默认token_pattern，使用自定义tokenizer
            sublinear_tf=True,   # 对数缩放词频
        )
        self.chunk_vectors = None
        self.is_built = False

    def _chinese_tokenizer(self, text: str) -> list:
        """中文分词器（供 TfidfVectorizer 使用）

        使用 jieba 分词，过滤停用词和单字符。
        """
        return self.text_processor.segment_words(text)

    def build_index(self, patents: List[StructuredPatent]):
        """构建文档索引

        Args:
            patents: 结构化专利列表
        """
        self.chunks = []
        # 记录全部参与索引的专利 ID（含无文本不产生chunk的，供增量判断）
        self._input_patent_ids = [p.patent_id for p in patents]

        for p in patents:
            patent_chunks = self._chunk_patent(p)
            self.chunks.extend(patent_chunks)

            for i, chunk in enumerate(patent_chunks):
                idx = len(self.chunks) - len(patent_chunks) + i
                self.chunks_by_type[chunk.section_type].append(idx)
                self.chunks_by_patent[p.patent_id].append(idx)

        # TF-IDF 向量化
        self.dense_vectors = None
        if self.chunks:
            texts = [c.text for c in self.chunks]
            try:
                self.chunk_vectors = self.vectorizer.fit_transform(texts)
                self.is_built = True
            except ValueError:
                self.is_built = False

        # 稠密向量（可选，需 embedding API；失败则回退纯 TF-IDF）
        if self.is_built and self.embedder.is_available():
            try:
                print(f"  计算稠密向量 ({len(self.chunks)} chunks)...")
                t0 = time.time()
                vecs = self.embedder.embed(texts)
                if vecs and len(vecs) == len(texts):
                    self.dense_vectors = np.asarray(vecs, dtype=np.float32)
                    print(f"  稠密向量完成: {self.dense_vectors.shape} "
                          f"({time.time()-t0:.0f}s)，启用混合检索")
            except Exception as e:
                print(f"  稠密向量计算失败，回退 TF-IDF 检索: {e}")
                self.dense_vectors = None

    def _chunk_patent(self, patent: StructuredPatent) -> List[DocumentChunk]:
        """将一篇专利拆分为多个可检索的文档块

        分块策略（结构化分块，避免固定窗口硬切）：
        - 摘要: 整体一块
        - 技术问题: 背景技术 + 发明目的 → background
        - 技术方案: 发明内容概述 → solution
        - 权利要求: 独立+从属**逐条**成块（带依赖链元数据），另加整篇父块
        - 技术效果: 逐条 → effects
        - 具体实施方式: 优先按结构化实施例切块，否则滑动窗口回退
        每块携带 patent_id/title/ipc/日期/法律状态 等元数据，供检索过滤。

        Args:
            patent: 结构化专利

        Returns:
            文档块列表
        """
        chunks = []
        ds = patent.description_sections
        base_meta = {
            "title": patent.title,
            "applicant": patent.applicant,
            "ipc": ipc_to_str(patent.ipc),
            "application_date": patent.application_date,
            "legal_status": patent.legal_status,
        }

        # 块1: 摘要（整体一块，不进分块流程）
        if ds and ds.abstract_text and len(ds.abstract_text.strip()) > 10:
            chunks.append(DocumentChunk(
                chunk_id=f"{patent.patent_id}_abstract",
                patent_id=patent.patent_id,
                section_type="abstract",
                text=ds.abstract_text.strip(),
                metadata=dict(base_meta),
            ))

        # 块2: 技术问题（背景技术 + 发明目的），无提取结果时回退到说明书背景章节
        problem_text = patent.technical_problem or (ds.background if ds else "")
        if problem_text:
            chunks.append(DocumentChunk(
                chunk_id=f"{patent.patent_id}_problem",
                patent_id=patent.patent_id,
                section_type="background",
                text=problem_text,
                metadata=dict(base_meta),
            ))

        # 块3: 技术方案概述，无提取结果时回退到发明内容章节
        solution_text = patent.technical_solution or (ds.invention_content if ds else "")
        if solution_text:
            chunks.append(DocumentChunk(
                chunk_id=f"{patent.patent_id}_solution",
                patent_id=patent.patent_id,
                section_type="solution",
                text=solution_text,
                metadata=dict(base_meta),
            ))

        # 块4: 权利要求——独立+从属逐条成块，带依赖链元数据；另加整篇父块
        if patent.claims_tree:
            tree = patent.claims_tree
            # 整篇权利要求书父块（提供上下文完整性）
            if patent.claims_raw:
                chunks.append(DocumentChunk(
                    chunk_id=f"{patent.patent_id}_claims_full",
                    patent_id=patent.patent_id,
                    section_type="claims",
                    text=patent.claims_raw[:3000],
                    metadata={**base_meta, "claim_scope": "full"},
                ))
            seen_claims = set()
            for claim in tree.get_all_claims():
                if claim.claim_number in seen_claims:
                    continue  # 防解析重复
                seen_claims.add(claim.claim_number)
                chunks.append(DocumentChunk(
                    chunk_id=f"{patent.patent_id}_claim{claim.claim_number}",
                    patent_id=patent.patent_id,
                    section_type="claims",
                    text=claim.claim_text,
                    metadata={
                        **base_meta,
                        "claim_number": claim.claim_number,
                        "claim_type": claim.claim_type,
                        "parent_number": claim.parent_number,
                        "dependency_chain": tree.get_dependency_chain(claim.claim_number),
                        "claim_category": claim.claim_category,
                    },
                ))

        # 块5: 技术效果（逐条成块）
        effects = patent.technical_effects or (ds.beneficial_effects if ds else [])
        for i, effect in enumerate(effects[:5]):
            if len(effect) > 10:
                chunks.append(DocumentChunk(
                    chunk_id=f"{patent.patent_id}_effect{i}",
                    patent_id=patent.patent_id,
                    section_type="effects",
                    text=effect,
                    metadata={**base_meta, "effect_index": i},
                ))

        # 块6: 具体实施方式——优先按结构化实施例切块，否则滑动窗口回退
        if ds:
            if ds.embodiments:
                # 同一实施例编号可能出现多次（正文各处引用），用出现序号保证 chunk_id 唯一
                emb_occurrence = defaultdict(int)
                for emb in ds.embodiments:
                    content = (emb.get("content") or "").strip()
                    if len(content) > 50:
                        emb_idx = emb.get("index")
                        emb_occurrence[emb_idx] += 1
                        occurrence = emb_occurrence[emb_idx]
                        cid = f"{patent.patent_id}_emb{emb_idx}"
                        if occurrence > 1:
                            cid = f"{patent.patent_id}_emb{emb_idx}_{occurrence}"
                        chunks.append(DocumentChunk(
                            chunk_id=cid,
                            patent_id=patent.patent_id,
                            section_type="implementation",
                            text=content,
                            metadata={**base_meta, "embodiment_index": emb_idx},
                        ))
            elif ds.detailed_implementation and len(ds.detailed_implementation) > 200:
                # 回退：按句子聚合为 ~700字语义块（无重叠），每篇封顶30块，避免碎片爆炸
                impl_text = ds.detailed_implementation
                sentences = self.text_processor.split_sentences(impl_text)
                blocks = []
                current, cur_len = [], 0
                for sent in sentences:
                    if cur_len + len(sent) > 700 and current:
                        blocks.append("".join(current))
                        current, cur_len = [], 0
                    current.append(sent)
                    cur_len += len(sent)
                if current:
                    blocks.append("".join(current))
                for idx, block in enumerate(blocks[:30]):
                    block = block.strip()
                    if len(block) > 50:
                        chunks.append(DocumentChunk(
                            chunk_id=f"{patent.patent_id}_impl{idx}",
                            patent_id=patent.patent_id,
                            section_type="implementation",
                            text=block,
                            metadata={**base_meta, "position": idx},
                        ))

        return chunks

    # ═══════════════════════════════════════════════════════════════
    # 检索方法
    # ═══════════════════════════════════════════════════════════════

    def retrieve(self, query: str, top_k: int = 5,
                section_filter: List[str] = None) -> List[RetrievalResult]:
        """语义检索相关专利文本

        TF-IDF 与稠密向量（可用时）经 RRF 融合；稠密不可用时回退纯 TF-IDF。

        Args:
            query: 查询文本
            top_k: 返回数量
            section_filter: 可选的章节类型过滤

        Returns:
            检索结果列表
        """
        if not self.is_built or self.chunk_vectors is None:
            return []

        # TF-IDF 查询向量
        try:
            query_vec = self.vectorizer.transform([query])
        except (ValueError, AttributeError):
            return []
        tfidf_scores = cosine_similarity(query_vec, self.chunk_vectors)[0]

        # 混合融合
        scores, hybrid_active = self._fused_scores(query, tfidf_scores)

        # 排序
        sorted_indices = scores.argsort()[::-1]

        # 阈值：混合模式（RRF）分数量纲小，不做绝对分数过滤，直接取 top_k；
        # 纯 TF-IDF 模式保留原有动态阈值
        if hybrid_active:
            min_threshold = None
        else:
            top_score = scores[sorted_indices[0]] if len(sorted_indices) > 0 else 0
            min_threshold = max(0.05, top_score * 0.3) if top_score > 0.1 else 0.05

        results = []
        for idx in sorted_indices:
            chunk = self.chunks[idx]
            score = scores[idx]

            # 章节类型过滤
            if section_filter and chunk.section_type not in section_filter:
                continue

            if min_threshold is not None and score < min_threshold:
                continue

            results.append(RetrievalResult(
                chunk=chunk,
                score=float(score),
                relevance_reason=self._explain_relevance(query, chunk),
            ))

            if len(results) >= top_k:
                break

        return results

    def _fused_scores(self, query: str,
                      tfidf_scores: np.ndarray) -> Tuple[np.ndarray, bool]:
        """计算检索最终分数

        embedding 可用时做 TF-IDF + 稠密向量 RRF 融合；否则返回纯 TF-IDF。

        Returns:
            (分数数组, 是否启用混合模式)
        """
        if self.dense_vectors is not None and self.embedder.is_available():
            try:
                qemb = self.embedder.embed([query])
                if qemb and len(qemb[0]) == self.dense_vectors.shape[1]:
                    dense_scores = cosine_similarity(
                        np.asarray(qemb), self.dense_vectors
                    )[0]
                    return self._rrf_fuse(tfidf_scores, dense_scores), True
            except Exception as e:
                print(f"[RAG] 稠密检索失败，回退 TF-IDF: {e}")
        return tfidf_scores, False

    @staticmethod
    def _rrf_fuse(tfidf_scores: np.ndarray,
                  dense_scores: np.ndarray, k: int = 60) -> np.ndarray:
        """RRF（Reciprocal Rank Fusion）分数融合

        score(d) = Σ_list 1/(k + rank_list(d))，k 取默认 60，
        规避 TF-IDF 与余弦分数量纲不可比的问题。
        """
        n = len(tfidf_scores)
        fused = np.zeros(n, dtype=np.float64)
        for scores in (tfidf_scores, dense_scores):
            order = scores.argsort()[::-1]
            for rank, idx in enumerate(order):
                fused[idx] += 1.0 / (k + rank + 1)
        return fused

    def retrieve_by_problem(self, problem_desc: str, top_k: int = 5) -> List[RetrievalResult]:
        """根据技术问题检索相关背景技术和方案

        Args:
            problem_desc: 技术问题描述
            top_k: 返回数量

        Returns:
            检索结果
        """
        return self.retrieve(
            problem_desc, top_k=top_k,
            section_filter=["background", "solution"]
        )

    def retrieve_similar_claims(self, claim_text: str, top_k: int = 5) -> List[RetrievalResult]:
        """检索相似的权利要求写法

        Args:
            claim_text: 权利要求草稿
            top_k: 返回数量

        Returns:
            相似权利要求
        """
        return self.retrieve(
            claim_text, top_k=top_k,
            section_filter=["claims"]
        )

    def retrieve_effect_templates(self, effect_keywords: str, top_k: int = 5) -> List[RetrievalResult]:
        """检索技术效果的表述模板

        Args:
            effect_keywords: 效果关键词（如"提高效率"、"降低损耗"）
            top_k: 返回数量

        Returns:
            效果表述示例
        """
        return self.retrieve(
            effect_keywords, top_k=top_k,
            section_filter=["effects"]
        )

    def retrieve_implementation_examples(self, tech_method: str, top_k: int = 5) -> List[RetrievalResult]:
        """检索具体实施方式示例

        Args:
            tech_method: 技术方法关键词
            top_k: 返回数量

        Returns:
            实施方式示例
        """
        return self.retrieve(
            tech_method, top_k=top_k,
            section_filter=["implementation"]
        )

    def hybrid_search(self, query: str, keywords: List[str] = None,
                     top_k: int = 5) -> List[RetrievalResult]:
        """混合检索——结合语义和关键词匹配

        Args:
            query: 语义查询
            keywords: 强制匹配的关键词列表
            top_k: 返回数量

        Returns:
            混合检索结果
        """
        # 先做语义检索，取双倍结果
        semantic_results = self.retrieve(query, top_k=top_k * 2)

        if not keywords:
            return semantic_results[:top_k]

        # 对关键词匹配的结果加权
        for result in semantic_results:
            keyword_bonus = sum(
                0.1 for kw in keywords if kw in result.chunk.text
            )
            result.score += keyword_bonus

        # 重新排序
        semantic_results.sort(key=lambda r: r.score, reverse=True)
        return semantic_results[:top_k]

    def _explain_relevance(self, query: str, chunk: DocumentChunk) -> str:
        """解释检索结果的相关性

        Args:
            query: 查询文本
            chunk: 文档块

        Returns:
            相关性说明
        """
        # 简单的关键词重叠解释
        query_words = set(self.text_processor.segment_words(query))
        chunk_words = set(self.text_processor.segment_words(chunk.text))
        overlap = query_words & chunk_words
        if overlap:
            return f"共享关键词: {', '.join(list(overlap)[:5])}"
        return "语义相似"

    # ═══════════════════════════════════════════════════════════════
    # 撰写上下文生成
    # ═══════════════════════════════════════════════════════════════

    def generate_writing_context(self, user_idea: str) -> Dict:
        """为专利撰写生成完整的参考上下文

        从多个维度检索相关内容，为专利撰写提供参考。

        Args:
            user_idea: 用户的技术想法描述

        Returns:
            多维度的参考上下文
        """
        context = {
            "idea": user_idea,
            "related_background": [],     # 相关背景技术
            "similar_claims": [],          # 相似权利要求结构
            "effect_templates": [],        # 效果表述模板
            "implementation_references": [],  # 实施方式参考
        }

        # 根据想法推测效果关键词
        effect_keywords = self._infer_effect_keywords(user_idea)

        # 多维度检索
        context["related_background"] = [
            r.to_dict() for r in self.retrieve_by_problem(user_idea, top_k=5)
        ]
        context["similar_claims"] = [
            r.to_dict() for r in self.retrieve_similar_claims(user_idea, top_k=5)
        ]
        context["effect_templates"] = [
            r.to_dict() for r in self.retrieve_effect_templates(effect_keywords, top_k=5)
        ]
        context["implementation_references"] = [
            r.to_dict() for r in self.retrieve_implementation_examples(user_idea, top_k=5)
        ]

        # 去重：按 chunk_id 跨维度去重（同一文档块只保留一次），
        # 保留各维度最佳结果——同一专利的不同章节（背景/权利要求/实施例）
        # 可各自成为不同维度的参考，不应互相挤掉。
        seen_chunks = set()
        for dim in ["related_background", "similar_claims", "effect_templates", "implementation_references"]:
            deduped = []
            for item in context[dim]:
                cid = item.get("chunk_id", "")
                if cid not in seen_chunks:
                    deduped.append(item)
                    seen_chunks.add(cid)
            # 按相关度降序排序
            deduped.sort(key=lambda x: x.get("score", 0), reverse=True)
            context[dim] = deduped

        return context

    def _infer_effect_keywords(self, idea: str) -> str:
        """从想法描述中推测可能的技术效果关键词

        Args:
            idea: 想法描述

        Returns:
            效果关键词字符串
        """
        effect_kw_map = {
            "效率": "提高效率 降低损耗",
            "精度": "提高精度 降低误差",
            "成本": "降低成本 经济效益",
            "稳定": "提高稳定性 抑制振荡",
            "安全": "提高安全性 故障保护",
            "速度": "提高响应速度 实时性",
            "节能": "降低能耗 提高效率",
            "质量": "提高质量 改善波形",
        }

        keywords = []
        for kw, effects in effect_kw_map.items():
            if kw in idea:
                keywords.append(effects)

        return " ".join(keywords) if keywords else idea

    # ═══════════════════════════════════════════════════════════════
    # 统计与持久化
    # ═══════════════════════════════════════════════════════════════

    def get_statistics(self) -> Dict:
        """获取索引统计信息

        Returns:
            统计字典
        """
        return {
            "total_chunks": len(self.chunks),
            "is_built": self.is_built,
            "chunks_by_type": {k: len(v) for k, v in self.chunks_by_type.items()},
            "patents_indexed": len(self.chunks_by_patent),
            "vector_dimension": self.chunk_vectors.shape[1] if self.chunk_vectors is not None else 0,
        }

    def save_index(self, filename: str = "rag_index.json"):
        """保存索引到磁盘

        Args:
            filename: 索引文件名
        """
        filepath = self.storage_path / filename

        chunks_data = [c.to_dict() for c in self.chunks]

        # 保存完整的chunk数据（用于重新加载）
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({
                "chunks": chunks_data,
                "chunks_by_type": {k: v for k, v in self.chunks_by_type.items()},
                "chunks_by_patent": {k: v for k, v in self.chunks_by_patent.items()},
            }, f, ensure_ascii=False, indent=2)

        # 保存向量化器
        import pickle
        vec_path = self.storage_path / "vectorizer.pkl"
        with open(vec_path, "wb") as f:
            pickle.dump(self.vectorizer, f)

        vec_data_path = self.storage_path / "vectors.npz"
        if self.chunk_vectors is not None:
            sp.save_npz(vec_data_path, self.chunk_vectors.tocsr())

        # 稠密向量
        dense_path = self.storage_path / "vectors_dense.npy"
        has_dense = self.dense_vectors is not None
        if has_dense:
            np.save(dense_path, self.dense_vectors)
        elif dense_path.exists():
            dense_path.unlink()

        # 保存已索引专利 ID 清单（供增量模式判断新旧）
        meta_path = self.storage_path / "index_meta.json"
        indexed_ids = sorted(set(getattr(self, "_input_patent_ids", None)
                                 or self.chunks_by_patent.keys()))
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "indexed_patents": indexed_ids,
                "total_chunks": len(self.chunks),
                "schema_version": self.INDEX_SCHEMA_VERSION,
                "has_dense": has_dense,
            }, f, ensure_ascii=False)

        print(f"RAG索引已保存: {filepath} ({len(self.chunks)}个文档块)")

    def load_index(self, filename: str = "rag_index.json"):
        """从磁盘加载索引（含文档块和向量，支持直接检索）

        Args:
            filename: 索引文件名
        """
        filepath = self.storage_path / filename
        if not filepath.exists():
            print(f"索引文件不存在: {filepath}")
            return

        import pickle

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 重建文档块和映射
        self.chunks = [
            DocumentChunk(
                chunk_id=c["chunk_id"],
                patent_id=c["patent_id"],
                section_type=c["section_type"],
                text=c["text"],
                metadata=c.get("metadata", {}),
            )
            for c in data.get("chunks", [])
        ]
        self.chunks_by_type = defaultdict(list, {
            k: v for k, v in data.get("chunks_by_type", {}).items()
        })
        self.chunks_by_patent = defaultdict(list, {
            k: v for k, v in data.get("chunks_by_patent", {}).items()
        })

        # 加载向量化器和向量
        vec_path = self.storage_path / "vectorizer.pkl"
        if vec_path.exists():
            with open(vec_path, "rb") as f:
                self.vectorizer = pickle.load(f)

        vec_data_path = self.storage_path / "vectors.npz"
        if vec_data_path.exists() and self.chunks:
            self.chunk_vectors = sp.load_npz(vec_data_path).tocsr()
            self.is_built = True
        else:
            self.is_built = False

        # 稠密向量
        dense_path = self.storage_path / "vectors_dense.npy"
        self.dense_vectors = None
        if dense_path.exists() and self.chunks:
            try:
                self.dense_vectors = np.load(dense_path)
            except Exception:
                self.dense_vectors = None

        print(f"RAG索引已加载: {filepath} ({len(self.chunks)}个文档块)")

    def get_indexed_patent_ids(self) -> set:
        """获取已保存索引覆盖的专利 ID 集合"""
        meta_path = self.storage_path / "index_meta.json"
        if not meta_path.exists():
            return set()
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return set(meta.get("indexed_patents", []))
        except (json.JSONDecodeError, OSError):
            return set()

    def is_index_stale(self, patent_ids) -> bool:
        """判断已保存索引是否过期（是否有未索引的专利或缺少索引文件）

        版本号不符（分块逻辑/元数据变更）也视为过期，强制重建。

        Args:
            patent_ids: 当前数据库中的专利 ID 集合

        Returns:
            True 表示需要重建
        """
        index_file = self.storage_path / "rag_index.json"
        vec_file = self.storage_path / "vectors.npz"
        if not index_file.exists() or not vec_file.exists():
            return True

        meta_path = self.storage_path / "index_meta.json"
        version_ok = False
        has_dense = False
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            version_ok = meta.get("schema_version") == self.INDEX_SCHEMA_VERSION
            has_dense = bool(meta.get("has_dense", False))
        except (json.JSONDecodeError, OSError):
            pass
        if not version_ok:
            return True

        # embedding 已配置但索引缺稠密向量 → 重建以启用混合检索
        if self.embedder.is_available() and not has_dense:
            return True

        indexed = self.get_indexed_patent_ids()
        if not indexed:
            return True
        return not set(patent_ids).issubset(indexed)
