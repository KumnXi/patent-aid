"""
专利知识图谱引擎

从结构化专利数据中构建问题→方案→效果→技术→设备→参数的多维知识图谱。
使用NetworkX作为图存储引擎，JSON持久化，支持语义查询和创新灵感发现。

图谱节点类型:
- problem: 技术问题（如"电解槽响应延时导致频率振荡"）
- solution: 技术方案（如"低通滤波器频域解耦"）
- effect: 技术效果（如"消除高频扰动"）
- technology: 具体技术/方法（如"帕累托优化"）
- equipment: 设备/组件（如"ALK电解槽"）
- parameter: 参数/指标（如"响应时间常数"）

图谱边类型:
- solves: solution→problem（方案解决问题）
- achieves: solution→effect（方案达成效果）
- uses: solution→technology（方案使用技术）
- composes: solution→equipment（方案由设备组成）
- measures: effect→parameter（效果由参数度量）
- similar_to: 同类型节点间的相似关系
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import Counter

import numpy as np
import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.parsers.patent_parser import StructuredPatent, PatentParser
from src.core.database_loader import DatabaseLoader
from src.utils.text_utils import ChineseTextProcessor


@dataclass
class KnowledgeNode:
    """知识图谱节点"""
    node_id: str
    node_type: str  # problem | solution | effect | technology | equipment | parameter
    name: str       # 节点显示名称
    description: str = ""
    source_patents: List[str] = field(default_factory=list)  # 来源专利ID（数据溯源）
    frequency: int = 1  # 出现频次
    metadata: Dict = field(default_factory=dict)


@dataclass
class KnowledgeEdge:
    """知识图谱边"""
    source_id: str
    target_id: str
    relation_type: str  # solves | achieves | uses | composes | measures | similar_to
    weight: float = 1.0
    evidence: List[str] = field(default_factory=list)  # 支持该关系的专利ID列表


class KnowledgeGraph:
    """专利知识图谱

    构建和查询技术知识图谱，发现创新模式。

    使用方式:
        kg = KnowledgeGraph()
        kg.build_from_patents(patents)   # 从解析后的专利构建
        results = kg.query_by_problem("频率振荡")  # 查询解决方案
        kg.save("data/knowledge_graph.json")
    """

    def __init__(self, storage_path: str = "data/knowledge_graph"):
        """初始化知识图谱

        Args:
            storage_path: 图谱数据存储路径
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.graph = nx.MultiDiGraph()  # 多重有向图
        self.text_processor = ChineseTextProcessor()

        # TF-IDF向量化器（用于相似度计算）
        self.vectorizer = TfidfVectorizer(max_features=1000)
        self.node_embeddings: Dict[str, List[float]] = {}
        self._embedding_matrix = None

    # ═══════════════════════════════════════════════════════════════
    # 图谱构建
    # ═══════════════════════════════════════════════════════════════

    def build_from_patents(self, patents: List[StructuredPatent]):
        """从解析后的专利列表构建知识图谱

        Args:
            patents: 结构化专利列表
        """
        # 1. 提取各类型节点
        problem_nodes = self._extract_problem_nodes(patents)
        solution_nodes = self._extract_solution_nodes(patents)
        effect_nodes = self._extract_effect_nodes(patents)
        technology_nodes = self._extract_technology_nodes(patents)
        equipment_nodes = self._extract_equipment_nodes(patents)
        parameter_nodes = self._extract_parameter_nodes(patents)

        # 2. 添加所有节点到图中
        all_nodes = (problem_nodes + solution_nodes + effect_nodes +
                    technology_nodes + equipment_nodes + parameter_nodes)
        self._add_nodes_to_graph(all_nodes)

        # 3. 创建关系边
        edges = []
        edges.extend(self._create_problem_solution_edges(patents, problem_nodes, solution_nodes))
        edges.extend(self._create_solution_effect_edges(patents, solution_nodes, effect_nodes))
        edges.extend(self._create_solution_technology_edges(patents, solution_nodes, technology_nodes))
        edges.extend(self._create_solution_equipment_edges(patents, solution_nodes, equipment_nodes))
        edges.extend(self._create_effect_parameter_edges(patents, effect_nodes, parameter_nodes))
        edges.extend(self._create_similarity_edges(all_nodes))

        # 4. 添加所有边到图中
        for edge in edges:
            self.graph.add_edge(
                edge.source_id, edge.target_id,
                relation_type=edge.relation_type,
                weight=edge.weight,
                evidence=edge.evidence
            )

        # 5. 计算节点嵌入向量
        self._compute_embeddings(all_nodes)

    def _add_nodes_to_graph(self, nodes: List[KnowledgeNode]):
        """将节点列表添加到图中（自动去重合并）

        Args:
            nodes: 知识节点列表
        """
        for node in nodes:
            if node.node_id in self.graph:
                # 已存在：更新频率和来源专利
                self.graph.nodes[node.node_id]["frequency"] += node.frequency
                existing_patents = set(self.graph.nodes[node.node_id].get("source_patents", []))
                existing_patents.update(node.source_patents)
                self.graph.nodes[node.node_id]["source_patents"] = list(existing_patents)
            else:
                self.graph.add_node(
                    node.node_id,
                    node_type=node.node_type,
                    name=node.name,
                    description=node.description,
                    source_patents=node.source_patents,
                    frequency=node.frequency,
                    metadata=node.metadata,
                )

    # ═══════════════════════════════════════════════════════════════
    # 节点提取
    # ═══════════════════════════════════════════════════════════════

    def _extract_problem_nodes(self, patents: List[StructuredPatent]) -> List[KnowledgeNode]:
        """提取技术问题节点

        从专利的背景技术章节和发明目的中提取技术问题。
        使用TF-IDF对问题描述进行聚类，合并相似问题。

        Args:
            patents: 结构化专利列表

        Returns:
            问题节点列表
        """
        nodes = []

        # 收集所有问题描述
        all_problems = []
        for p in patents:
            if not p.is_parsed or not p.description_sections:
                continue

            ds = p.description_sections
            # 优先使用"现有问题"列表
            if ds.existing_problems:
                for prob in ds.existing_problems[:2]:
                    all_problems.append((prob, p.patent_id, p.title))
            # 其次使用发明目的
            elif ds.invention_purpose:
                all_problems.append((ds.invention_purpose, p.patent_id, p.title))
            # fallback到合并后的问题
            elif p.technical_problem:
                all_problems.append((p.technical_problem, p.patent_id, p.title))

        # 对问题进行去重合并（基于文本相似度）
        merged = self._merge_similar_items(all_problems, threshold=0.3)

        for i, (merged_text, sources) in enumerate(merged.items()):
            node_id = f"problem_{i:03d}"
            node = KnowledgeNode(
                node_id=node_id,
                node_type="problem",
                name=self._truncate(merged_text, 80),
                description=merged_text,
                source_patents=[s[1] for s in sources],
                frequency=len(sources),
            )
            nodes.append(node)

        return nodes

    def _extract_solution_nodes(self, patents: List[StructuredPatent]) -> List[KnowledgeNode]:
        """提取技术方案节点

        从专利的发明内容和独立权利要求中提取技术方案。

        Args:
            patents: 结构化专利列表

        Returns:
            方案节点列表
        """
        nodes = []
        for p in patents:
            if not p.is_parsed:
                continue

            solution_text = p.technical_solution or ""

            # 如果没有综合方案，使用权利要求1的特征部分
            if not solution_text and p.claims_tree:
                indep_claims = p.claims_tree.independent_claims
                if indep_claims:
                    solution_text = indep_claims[0].characterizing

            if solution_text:
                node_id = f"solution_{p.patent_id}"
                node = KnowledgeNode(
                    node_id=node_id,
                    node_type="solution",
                    name=p.title or f"方案_{p.patent_id}",
                    description=solution_text,
                    source_patents=[p.patent_id],
                    frequency=1,
                )
                nodes.append(node)

        return nodes

    def _extract_effect_nodes(self, patents: List[StructuredPatent]) -> List[KnowledgeNode]:
        """提取技术效果节点

        Args:
            patents: 结构化专利列表

        Returns:
            效果节点列表
        """
        nodes = []
        all_effects = []

        for p in patents:
            if not p.is_parsed:
                continue
            for effect in p.technical_effects:
                all_effects.append((effect, p.patent_id, p.title))

        # 去重合并相似效果
        merged = self._merge_similar_items(all_effects, threshold=0.5)

        for i, (merged_text, sources) in enumerate(merged.items()):
            node_id = f"effect_{i:03d}"
            node = KnowledgeNode(
                node_id=node_id,
                node_type="effect",
                name=self._truncate(merged_text, 80),
                description=merged_text,
                source_patents=[s[1] for s in sources],
                frequency=len(sources),
            )
            nodes.append(node)

        return nodes

    def _extract_technology_nodes(self, patents: List[StructuredPatent]) -> List[KnowledgeNode]:
        """提取具体技术/方法节点

        从专利关键词和方案描述中识别具体的技术方法。
        如：帕累托优化、低通滤波、ARIMA、Transformer等。

        Args:
            patents: 结构化专利列表

        Returns:
            技术节点列表
        """
        # 基于关键词匹配的具体技术方法
        tech_patterns = {
            "帕累托优化": ["帕累托", "Pareto"],
            "低通滤波": ["低通滤波"],
            "MPC模型预测控制": ["MPC", "模型预测控制"],
            "ARIMA模型": ["ARIMA"],
            "Transformer模型": ["Transformer"],
            "BP神经网络": ["BP神经网络", "BP网络"],
            "深度强化学习": ["深度强化学习", "DRL"],
            "卡尔曼滤波": ["卡尔曼滤波", "Kalman"],
            "粒子群优化": ["粒子群", "PSO"],
            "模糊控制": ["模糊控制", "Fuzzy"],
            "滑模控制": ["滑模控制", "SMC"],
            "遗传算法": ["遗传算法", "GA"],
            "支持向量机": ["支持向量机", "SVM"],
            "长短期记忆网络": ["LSTM", "长短期记忆"],
            "SE-Block": ["SE-Block", "SE Block"],
        }

        tech_counter = Counter()
        tech_patents = {}
        all_texts = []

        for p in patents:
            if not p.is_parsed:
                continue
            # 合并标题、方案、关键词用于匹配
            text = f"{p.title} {p.technical_solution} {' '.join(p.keywords)}"
            all_texts.append(text)

            for tech_name, patterns in tech_patterns.items():
                for pattern in patterns:
                    if pattern.lower() in text.lower():
                        tech_counter[tech_name] += 1
                        if tech_name not in tech_patents:
                            tech_patents[tech_name] = []
                        tech_patents[tech_name].append(p.patent_id)

        nodes = []
        for i, (tech_name, count) in enumerate(tech_counter.most_common(30)):
            node_id = f"technology_{i:03d}"
            node = KnowledgeNode(
                node_id=node_id,
                node_type="technology",
                name=tech_name,
                description=f"{tech_name}技术，在{count}篇专利中使用",
                source_patents=tech_patents.get(tech_name, []),
                frequency=count,
            )
            nodes.append(node)

        # 也添加从专利中提取的TF-IDF高频关键词作为技术节点
        all_keywords = []
        for p in patents:
            all_keywords.extend(p.keywords)

        kw_counter = Counter(all_keywords)
        tech_offset = len(nodes)
        for i, (kw, count) in enumerate(kw_counter.most_common(20)):
            # 跳过已覆盖的技术名词
            if any(kw.lower() in t.lower() or t.lower() in kw.lower()
                  for t in tech_counter):
                continue
            node_id = f"technology_{tech_offset + i:03d}"
            node = KnowledgeNode(
                node_id=node_id,
                node_type="technology",
                name=kw,
                description=f"关键词：{kw}，出现{count}次",
                source_patents=[],
                frequency=count,
            )
            nodes.append(node)

        return nodes

    def _extract_equipment_nodes(self, patents: List[StructuredPatent]) -> List[KnowledgeNode]:
        """提取设备/组件节点

        Args:
            patents: 结构化专利列表

        Returns:
            设备节点列表
        """
        equipment_patterns = [
            "电解槽", "光伏", "逆变器", "变压器", "断路器",
            "储能系统", "电池", "传感器", "控制器", "继电器",
            "开关柜", "配电柜", "并网柜", "智能电表", "互感器",
            "风力发电", "微电网", "电网", "变电站",
        ]

        equip_counter = Counter()
        equip_patents = {}

        for p in patents:
            if not p.is_parsed:
                continue
            text = f"{p.title} {p.technical_solution}"
            for equip in equipment_patterns:
                if equip in text:
                    equip_counter[equip] += 1
                    if equip not in equip_patents:
                        equip_patents[equip] = []
                    equip_patents[equip].append(p.patent_id)

        nodes = []
        for i, (equip, count) in enumerate(equip_counter.most_common(30)):
            node_id = f"equipment_{i:03d}"
            node = KnowledgeNode(
                node_id=node_id,
                node_type="equipment",
                name=equip,
                description=f"{equip}设备，在{count}篇专利中涉及",
                source_patents=equip_patents.get(equip, []),
                frequency=count,
            )
            nodes.append(node)

        return nodes

    def _extract_parameter_nodes(self, patents: List[StructuredPatent]) -> List[KnowledgeNode]:
        """提取参数/指标节点

        Args:
            patents: 结构化专利列表

        Returns:
            参数节点列表
        """
        param_patterns = [
            "响应时间", "响应延时", "功率", "频率", "电压", "电流",
            "温度", "效率", "损耗", "谐波", "功率因数",
            "时间常数", "调节容量", "惩罚系数", "权重因子",
            "频率偏差", "电压偏差", "阻抗", "绝缘",
        ]

        param_counter = Counter()
        param_patents = {}

        for p in patents:
            if not p.is_parsed:
                continue
            text = f"{p.title} {p.technical_solution}"
            for param in param_patterns:
                if param in text:
                    param_counter[param] += 1
                    if param not in param_patents:
                        param_patents[param] = []
                    param_patents[param].append(p.patent_id)

        nodes = []
        for i, (param, count) in enumerate(param_counter.most_common(30)):
            node_id = f"parameter_{i:03d}"
            node = KnowledgeNode(
                node_id=node_id,
                node_type="parameter",
                name=param,
                description=f"{param}参数，在{count}篇专利中涉及",
                source_patents=param_patents.get(param, []),
                frequency=count,
            )
            nodes.append(node)

        return nodes

    # ═══════════════════════════════════════════════════════════════
    # 边创建
    # ═══════════════════════════════════════════════════════════════

    def _create_problem_solution_edges(self, patents: List[StructuredPatent],
                                       problem_nodes: List[KnowledgeNode],
                                       solution_nodes: List[KnowledgeNode]) -> List[KnowledgeEdge]:
        """创建问题→方案的解决关系边

        通过TF-IDF相似度匹配问题和方案（批量向量化，避免逐对重建向量化器）。
        """
        edges = []
        solution_ids = {n.node_id for n in solution_nodes}

        # 收集有技术问题的专利
        patent_problems = [(p.patent_id, p.technical_problem)
                           for p in patents if p.is_parsed and p.technical_problem]
        if not patent_problems or not problem_nodes:
            return edges

        # 共享专利快速匹配：专利问题直接绑定到含该专利的问题节点
        direct = {}  # patent_id -> problem_node_id
        for pid, _ in patent_problems:
            for prob_node in problem_nodes:
                if pid in prob_node.source_patents:
                    direct[pid] = prob_node.node_id
                    break

        # 批量向量化：一次分词+拟合，计算专利问题×问题节点 的相似度矩阵
        prob_texts = [t for _, t in patent_problems]
        node_descs = [n.description for n in problem_nodes]
        try:
            vec = TfidfVectorizer(max_features=1000).fit_transform(
                [" ".join(self.text_processor.segment_words(t)) for t in prob_texts]
                + [" ".join(self.text_processor.segment_words(d)) for d in node_descs]
            )
            prob_vecs = vec[:len(prob_texts)]
            node_vecs = vec[len(prob_texts):]
            sim_matrix = cosine_similarity(prob_vecs, node_vecs)
        except ValueError:
            return edges

        for i, (pid, _) in enumerate(patent_problems):
            solution_id = f"solution_{pid}"
            if solution_id not in solution_ids:
                continue

            # 已有直接绑定则优先
            if pid in direct:
                edges.append(KnowledgeEdge(
                    source_id=solution_id,
                    target_id=direct[pid],
                    relation_type="solves",
                    weight=1.0,
                    evidence=[pid],
                ))
                continue

            # 矩阵查找最相似问题节点
            scores = sim_matrix[i]
            best_j = int(scores.argmax())
            best_score = float(scores[best_j])
            if best_score > 0.2:
                edges.append(KnowledgeEdge(
                    source_id=solution_id,
                    target_id=problem_nodes[best_j].node_id,
                    relation_type="solves",
                    weight=best_score,
                    evidence=[pid],
                ))

        return edges

    def _create_solution_effect_edges(self, patents: List[StructuredPatent],
                                      solution_nodes: List[KnowledgeNode],
                                      effect_nodes: List[KnowledgeNode]) -> List[KnowledgeEdge]:
        """创建方案→效果的关系边"""
        edges = []
        solution_ids = {n.node_id for n in solution_nodes}

        for p in patents:
            solution_id = f"solution_{p.patent_id}"
            if solution_id not in solution_ids:
                continue

            for effect_node in effect_nodes:
                if p.patent_id in effect_node.source_patents:
                    edges.append(KnowledgeEdge(
                        source_id=solution_id,
                        target_id=effect_node.node_id,
                        relation_type="achieves",
                        weight=1.0,
                        evidence=[p.patent_id],
                    ))

        return edges

    def _create_solution_technology_edges(self, patents: List[StructuredPatent],
                                         solution_nodes: List[KnowledgeNode],
                                         technology_nodes: List[KnowledgeNode]) -> List[KnowledgeEdge]:
        """创建方案→技术的使用关系边"""
        edges = []
        solution_ids = {n.node_id for n in solution_nodes}

        for p in patents:
            solution_id = f"solution_{p.patent_id}"
            if solution_id not in solution_ids:
                continue

            text = f"{p.title} {p.technical_solution}"

            for tech_node in technology_nodes:
                if tech_node.name.lower() in text.lower():
                    edges.append(KnowledgeEdge(
                        source_id=solution_id,
                        target_id=tech_node.node_id,
                        relation_type="uses",
                        weight=1.0,
                        evidence=[p.patent_id],
                    ))

        return edges

    def _create_solution_equipment_edges(self, patents: List[StructuredPatent],
                                        solution_nodes: List[KnowledgeNode],
                                        equipment_nodes: List[KnowledgeNode]) -> List[KnowledgeEdge]:
        """创建方案→设备的组成关系边"""
        edges = []
        solution_ids = {n.node_id for n in solution_nodes}

        for p in patents:
            solution_id = f"solution_{p.patent_id}"
            if solution_id not in solution_ids:
                continue

            text = f"{p.title} {p.technical_solution}"

            for equip_node in equipment_nodes:
                if equip_node.name in text:
                    edges.append(KnowledgeEdge(
                        source_id=solution_id,
                        target_id=equip_node.node_id,
                        relation_type="composes",
                        weight=1.0,
                        evidence=[p.patent_id],
                    ))

        return edges

    def _create_effect_parameter_edges(self, patents: List[StructuredPatent],
                                      effect_nodes: List[KnowledgeNode],
                                      parameter_nodes: List[KnowledgeNode]) -> List[KnowledgeEdge]:
        """创建效果→参数的度量关系边"""
        edges = []

        for p in patents:
            all_effects_text = " ".join(p.technical_effects)
            for param_node in parameter_nodes:
                if param_node.name in all_effects_text:
                    # 找到关联的效果节点
                    for effect_node in effect_nodes:
                        if p.patent_id in effect_node.source_patents:
                            edges.append(KnowledgeEdge(
                                source_id=effect_node.node_id,
                                target_id=param_node.node_id,
                                relation_type="measures",
                                weight=0.8,
                                evidence=[p.patent_id],
                            ))

        return edges

    def _create_similarity_edges(self, all_nodes: List[KnowledgeNode]) -> List[KnowledgeEdge]:
        """创建同类型节点间的相似关系边（批量向量化优化）

        Args:
            all_nodes: 所有节点列表

        Returns:
            相似边列表
        """
        edges = []
        # 按类型分组
        by_type = {}
        for node in all_nodes:
            by_type.setdefault(node.node_type, []).append(node)

        # 为每种类型内部的节点计算相似度（批量方式）
        for node_type, nodes in by_type.items():
            if len(nodes) < 2:
                continue

            # 批量分词 + 向量化（一次性处理所有节点）
            descriptions = [n.description for n in nodes]
            tokenized = [" ".join(self.text_processor.segment_words(d)) for d in descriptions]

            try:
                vec = TfidfVectorizer(max_features=1000).fit_transform(tokenized)
                sim_matrix = cosine_similarity(vec)
            except ValueError:
                continue

            # 从相似度矩阵提取超过阈值的边（numpy 向量化，避免 O(n²) Python 循环）
            mat = np.asarray(sim_matrix)
            i_idx, j_idx = np.triu_indices(mat.shape[0], k=1)
            mask = mat[i_idx, j_idx] > 0.4
            for ii, jj, sc in zip(i_idx[mask], j_idx[mask], mat[i_idx[mask], j_idx[mask]]):
                edges.append(KnowledgeEdge(
                    source_id=nodes[ii].node_id,
                    target_id=nodes[jj].node_id,
                    relation_type="similar_to",
                    weight=float(sc),
                    evidence=[],
                ))

        return edges

    # ═══════════════════════════════════════════════════════════════
    # 查询接口
    # ═══════════════════════════════════════════════════════════════

    def query_by_problem(self, problem_desc: str, top_k: int = 5) -> List[Dict]:
        """根据技术问题描述查询相关解决方案

        Args:
            problem_desc: 技术问题描述
            top_k: 返回前k个结果

        Returns:
            相关方案列表，每项含方案信息、相关度和证据专利
        """
        results = []

        # 找到最相似的问题节点（取 top-3 而非单个）
        problem_nodes = self._get_nodes_by_type("problem")
        scored_problems = []

        for node_id in problem_nodes:
            node_data = self.graph.nodes[node_id]
            score = self._text_similarity(problem_desc, node_data.get("description", ""))
            if score > 0.1:  # 最低相似度阈值
                scored_problems.append((node_id, score))

        # 按相似度排序，取 top-3
        scored_problems.sort(key=lambda x: x[1], reverse=True)
        matched_problems = scored_problems[:3]

        if not matched_problems:
            # 回退：直接从所有 solution 节点中匹配
            solution_nodes = self._get_nodes_by_type("solution")
            for node_id in solution_nodes:
                node_data = self.graph.nodes[node_id]
                desc = node_data.get("description", "")
                score = self._text_similarity(problem_desc, desc)
                if score > 0.15:
                    results.append({
                        "solution_id": node_id,
                        "solution_name": node_data.get("name", ""),
                        "description": desc[:200],
                        "source_patents": node_data.get("source_patents", []),
                        "score": score,
                    })
            results.sort(key=lambda r: r["score"], reverse=True)
            return results[:top_k]

        # 查找匹配问题的解决方案
        for prob_id, prob_score in matched_problems:
            for source, _, data in self.graph.in_edges(prob_id, data=True):
                if data.get("relation_type") == "solves":
                    node_data = self.graph.nodes[source]
                    results.append({
                        "solution_id": source,
                        "solution_name": node_data.get("name", ""),
                        "description": node_data.get("description", "")[:200],
                        "source_patents": node_data.get("source_patents", []),
                        "score": prob_score * data.get("weight", 1.0),
                    })

        # 按相关度排序
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def query_solution_path(self, problem: str) -> List[List[str]]:
        """查询从问题到方案再到效果的完整路径

        Args:
            problem: 技术问题描述

        Returns:
            路径列表，每条路径为 [problem_id, solution_id, effect_id1, ...]
        """
        paths = []

        # 找到最匹配的问题节点
        problem_nodes = self._get_nodes_by_type("problem")
        best_problem = None
        best_score = 0
        for node_id in problem_nodes:
            node_data = self.graph.nodes[node_id]
            score = self._text_similarity(problem, node_data.get("description", ""))
            if score > best_score:
                best_score = score
                best_problem = node_id

        if not best_problem:
            return paths

        # 从问题节点出发，查找方案和效果
        for source, _, data in self.graph.in_edges(best_problem, data=True):
            if data.get("relation_type") == "solves":
                solution_id = source
                # 查找该方案达成的效果
                for _, effect_id, e_data in self.graph.out_edges(solution_id, data=True):
                    if e_data.get("relation_type") == "achieves":
                        paths.append([best_problem, solution_id, effect_id])

        return paths

    def find_alternative_solutions(self, problem: str, top_k: int = 5) -> List[Dict]:
        """为同一个问题发现不同的解决方案（创新灵感）

        通过问题节点的相似节点，找到不同方案。

        Args:
            problem: 技术问题描述
            top_k: 返回数量

        Returns:
            替代方案列表
        """
        alternatives = []

        # 先找到匹配的问题节点
        problem_nodes = self._get_nodes_by_type("problem")
        matched_problems = []
        for node_id in problem_nodes:
            node_data = self.graph.nodes[node_id]
            score = self._text_similarity(problem, node_data.get("description", ""))
            if score > 0.2:
                matched_problems.append((node_id, score))

        matched_problems.sort(key=lambda x: x[1], reverse=True)

        # 收集解决这些问题的所有方案
        seen_solutions = set()
        for prob_id, prob_score in matched_problems[:3]:
            for source, _, data in self.graph.in_edges(prob_id, data=True):
                if data.get("relation_type") == "solves":
                    if source not in seen_solutions:
                        seen_solutions.add(source)
                        node_data = self.graph.nodes[source]
                        alternatives.append({
                            "solution_id": source,
                            "solution_name": node_data.get("name", ""),
                            "description": node_data.get("description", "")[:200],
                            "source_patents": node_data.get("source_patents", []),
                            "problem_match_score": prob_score,
                        })

        alternatives.sort(key=lambda r: r["problem_match_score"], reverse=True)
        return alternatives[:top_k]

    def get_innovation_inspiration(self, tech_domain: str) -> Dict:
        """获取创新灵感报告

        基于知识图谱分析，为特定技术领域提供创新建议。

        Args:
            tech_domain: 技术领域关键词（如"电解槽"、"光伏"）

        Returns:
            创新灵感报告字典
        """
        report = {
            "domain": tech_domain,
            "related_problems": [],
            "common_solutions": [],
            "emerging_technologies": [],
            "cross_domain_ideas": [],
        }

        # 查找相关设备节点
        equip_nodes = self._get_nodes_by_type("equipment")
        related_equip = []
        for node_id in equip_nodes:
            node_data = self.graph.nodes[node_id]
            if tech_domain in node_data.get("name", ""):
                related_equip.append(node_id)

        # 查找使用该设备的方案
        solution_ids = set()
        for equip_id in related_equip:
            for source, _, data in self.graph.in_edges(equip_id, data=True):
                if data.get("relation_type") == "composes":
                    solution_ids.add(source)

        # 收集方案信息
        for sol_id in list(solution_ids)[:10]:
            node_data = self.graph.nodes[sol_id]
            report["common_solutions"].append({
                "name": node_data.get("name", ""),
                "patents": node_data.get("source_patents", []),
            })

        # 查找这些方案使用的技术
        tech_counter = Counter()
        for sol_id in solution_ids:
            for _, tech_id, data in self.graph.out_edges(sol_id, data=True):
                if data.get("relation_type") == "uses":
                    tech_name = self.graph.nodes[tech_id].get("name", "")
                    tech_counter[tech_name] += 1

        report["emerging_technologies"] = [
            {"name": name, "frequency": count}
            for name, count in tech_counter.most_common(10)
        ]

        # 发现跨领域技术（在别的设备中使用但本领域尚未使用的技术）
        all_tech_used = {t["name"] for t in report["emerging_technologies"]}
        all_tech_nodes = self._get_nodes_by_type("technology")
        for tech_id in all_tech_nodes:
            tech_data = self.graph.nodes[tech_id]
            tech_name = tech_data.get("name", "")
            if tech_name not in all_tech_used and tech_data.get("frequency", 0) >= 2:
                report["cross_domain_ideas"].append({
                    "technology": tech_name,
                    "frequency": tech_data.get("frequency", 0),
                    "suggestion": f"可考虑将{tech_name}技术应用于{tech_domain}领域",
                })

        return report

    # ═══════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════

    def _merge_similar_items(self, items: List[Tuple[str, str, str]],
                            threshold: float = 0.3) -> Dict[str, List[Tuple[str, str, str]]]:
        """合并相似的文本项

        基于TF-IDF余弦相似度将相似的项目合并。

        Args:
            items: [(文本, 专利ID, 专利标题), ...] 列表
            threshold: 相似度阈值

        Returns:
            {合并后文本: [(原始文本, 专利ID, 专利标题), ...]}
        """
        if len(items) <= 1:
            return {item[0]: [item] for item in items}

        texts = [item[0] for item in items]

        # TF-IDF向量化（使用jieba分词）
        try:
            tokenized = [" ".join(self.text_processor.segment_words(t)) for t in texts]
            vec = TfidfVectorizer(max_features=500).fit_transform(tokenized)
            sim_matrix = cosine_similarity(vec)
        except ValueError:
            # 文本太短时fallback
            return {item[0]: [item] for item in items}

        # 贪心聚类
        merged = {}
        used = set()

        for i in range(len(texts)):
            if i in used:
                continue

            group = [items[i]]
            used.add(i)

            for j in range(i + 1, len(texts)):
                if j not in used and sim_matrix[i][j] > threshold:
                    group.append(items[j])
                    used.add(j)

            # 取最长的文本作为合并后的描述
            best_text = max(group, key=lambda x: len(x[0]))[0]
            merged[best_text] = group

        return merged

    def _text_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的TF-IDF余弦相似度（使用jieba中文分词）

        Args:
            text1, text2: 待比较文本

        Returns:
            相似度分数 [0, 1]
        """
        try:
            # 使用jieba分词后再向量化
            words1 = " ".join(self.text_processor.segment_words(text1))
            words2 = " ".join(self.text_processor.segment_words(text2))
            if not words1.strip() or not words2.strip():
                return 0.0
            vec = TfidfVectorizer(max_features=500).fit_transform([words1, words2])
            return cosine_similarity(vec[0:1], vec[1:2])[0][0]
        except ValueError:
            # 文本太短时，使用简单的字符重叠度
            if not text1 or not text2:
                return 0.0
            chars1, chars2 = set(text1), set(text2)
            if not chars1 or not chars2:
                return 0.0
            return len(chars1 & chars2) / len(chars1 | chars2)

    def _get_nodes_by_type(self, node_type: str) -> List[str]:
        """获取指定类型的所有节点ID

        Args:
            node_type: 节点类型

        Returns:
            节点ID列表
        """
        return [n for n, d in self.graph.nodes(data=True)
                if d.get("node_type") == node_type]

    def _compute_embeddings(self, nodes: List[KnowledgeNode]):
        """计算所有节点的TF-IDF嵌入向量（用于快速相似度查询）

        Args:
            nodes: 节点列表
        """
        texts = [node.description or node.name for node in nodes]
        if not texts:
            return

        try:
            self._embedding_matrix = self.vectorizer.fit_transform(texts)
            for i, node in enumerate(nodes):
                self.node_embeddings[node.node_id] = self._embedding_matrix[i].toarray().flatten().tolist()
        except ValueError:
            pass

    def _truncate(self, text: str, max_len: int) -> str:
        """截断文本，保留前max_len个字符

        Args:
            text: 输入文本
            max_len: 最大长度

        Returns:
            截断后的文本
        """
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + "..."

    # ═══════════════════════════════════════════════════════════════
    # 统计与持久化
    # ═══════════════════════════════════════════════════════════════

    def get_statistics(self) -> Dict:
        """获取知识图谱统计信息

        Returns:
            统计字典
        """
        node_types = Counter()
        for _, data in self.graph.nodes(data=True):
            node_types[data.get("node_type", "unknown")] += 1

        edge_types = Counter()
        for _, _, data in self.graph.edges(data=True):
            edge_types[data.get("relation_type", "unknown")] += 1

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "node_types": dict(node_types),
            "edge_types": dict(edge_types),
        }

    def save(self, filename: str = "knowledge_graph.json"):
        """保存知识图谱到JSON文件

        保存节点和边为JSON格式，支持重新加载。

        Args:
            filename: 文件名
        """
        filepath = self.storage_path / filename

        # 提取节点数据
        nodes_data = []
        for node_id, data in self.graph.nodes(data=True):
            node_entry = {
                "node_id": node_id,
                "node_type": data.get("node_type", ""),
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "source_patents": data.get("source_patents", []),
                "frequency": data.get("frequency", 0),
                "metadata": data.get("metadata", {}),
            }
            nodes_data.append(node_entry)

        # 提取边数据
        edges_data = []
        for source, target, data in self.graph.edges(data=True):
            edge_entry = {
                "source_id": source,
                "target_id": target,
                "relation_type": data.get("relation_type", ""),
                "weight": data.get("weight", 1.0),
                "evidence": data.get("evidence", []),
            }
            edges_data.append(edge_entry)

        output = {
            "metadata": {
                "created": "",
                "statistics": self.get_statistics(),
            },
            "nodes": nodes_data,
            "edges": edges_data,
        }

        import datetime
        output["metadata"]["created"] = datetime.datetime.now().isoformat()

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"知识图谱已保存: {filepath} ({len(nodes_data)}节点, {len(edges_data)}边)")

    def load(self, filename: str = "knowledge_graph.json"):
        """从JSON文件加载知识图谱

        Args:
            filename: 文件名
        """
        filepath = self.storage_path / filename
        if not filepath.exists():
            print(f"知识图谱文件不存在: {filepath}")
            return

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.graph.clear()

        for node in data.get("nodes", []):
            self.graph.add_node(
                node["node_id"],
                node_type=node.get("node_type", ""),
                name=node.get("name", ""),
                description=node.get("description", ""),
                source_patents=node.get("source_patents", []),
                frequency=node.get("frequency", 0),
                metadata=node.get("metadata", {}),
            )

        for edge in data.get("edges", []):
            self.graph.add_edge(
                edge["source_id"],
                edge["target_id"],
                relation_type=edge.get("relation_type", ""),
                weight=edge.get("weight", 1.0),
                evidence=edge.get("evidence", []),
            )

        print(f"知识图谱已加载: {filepath} ({self.graph.number_of_nodes()}节点, {self.graph.number_of_edges()}边)")
