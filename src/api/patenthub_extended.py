"""
Patenthub API 扩展客户端
包含更多用于构建专利数据库的接口
"""

import requests
import json
import time
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime


class PatenthubExtendedClient:
    """Patenthub API扩展客户端 - 用于构建完整专利数据库"""

    BASE_URL = "https://www.patenthub.cn"

    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PatentWriterAssistant/1.0",
            "Accept": "application/json"
        })

    def _request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        params["t"] = self.token
        params["v"] = 1
        url = f"{self.BASE_URL}{endpoint}"

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data.get("success", False):
                error_code = data.get("code", "unknown")
                error_msg = data.get("message", "未知错误")
                raise Exception(f"API错误 [{error_code}]: {error_msg}")

            return data

        except requests.exceptions.RequestException as e:
            raise Exception(f"请求失败: {str(e)}")

    def search(self, query: str, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """搜索专利"""
        params = {
            "q": query,
            "ds": "cn",
            "p": page,
            "ps": min(page_size, 50),
            "s": "!applicationDate",  # 按申请日降序
            "hl": 0
        }
        return self._request("/api/s", params)

    def get_claims(self, patent_id: str) -> Dict[str, Any]:
        """获取权利要求"""
        params = {"id": patent_id}
        return self._request("/api/patent/claims", params)

    def get_description(self, patent_id: str) -> Dict[str, Any]:
        """获取说明书"""
        params = {"id": patent_id}
        return self._request("/api/patent/desc", params)

    def get_patent_detail(self, patent_id: str) -> Dict[str, Any]:
        """
        获取专利完整详情（一次请求获取更多信息）

        Args:
            patent_id: 专利ID

        Returns:
            专利详情数据
        """
        params = {"id": patent_id}
        return self._request("/api/patent/detail", params)

    def get_similar_patents(self, patent_id: str) -> Dict[str, Any]:
        """
        获取相似专利（用于自动发现相关专利）

        Args:
            patent_id: 专利ID

        Returns:
            相似专利列表
        """
        params = {"id": patent_id}
        return self._request("/api/patent/like", params)

    def get_citations(self, patent_id: str) -> Dict[str, Any]:
        """
        获取专利引用数据（建立引用关系图）

        Args:
            patent_id: 专利ID

        Returns:
            引用数据（被引和施引）
        """
        params = {"id": patent_id}
        return self._request("/api/patent/citing", params)

    def get_patent_family(self, patent_id: str) -> Dict[str, Any]:
        """
        获取同族专利（同一发明在不同国家的专利）

        Args:
            patent_id: 专利ID

        Returns:
            同族专利列表
        """
        params = {"id": patent_id}
        return self._request("/api/patent/family", params)

    def get_transactions(self, patent_id: str) -> Dict[str, Any]:
        """
        获取专利交易信息（转让、许可、质押）

        Args:
            patent_id: 专利ID

        Returns:
            交易信息
        """
        params = {"id": patent_id}
        return self._request("/api/patent/tx", params)

    def get_company_portrait(self, company_name: str) -> Dict[str, Any]:
        """
        获取企业画像（专利布局分析）

        Args:
            company_name: 企业名称

        Returns:
            企业专利画像数据
        """
        params = {"q": company_name}
        return self._request("/api/a/portrait", params)

    def get_statistics(self, query: str) -> Dict[str, Any]:
        """
        获取专利统计分析

        Args:
            query: 检索式

        Returns:
            统计数据
        """
        params = {"q": query}
        return self._request("/api/ration", params)

    def batch_legal_status(self, patent_ids: List[str]) -> Dict[str, Any]:
        """
        批量查询法律状态

        Args:
            patent_ids: 专利ID列表

        Returns:
            法律状态数据
        """
        params = {"ids": ",".join(patent_ids)}
        return self._request("/api/ls", params)


class PatentDatabaseBuilder:
    """专利数据库构建器 - 定时爬取和更新"""

    def __init__(self, token: str, db_path: str = "data/patent_database"):
        self.client = PatenthubExtendedClient(token)
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)

        # 初始化数据库文件
        self.index_file = self.db_path / "index.json"
        self.citations_file = self.db_path / "citations.json"
        self.similar_file = self.db_path / "similar_patents.json"
        self._init_database()

    def _init_database(self):
        """初始化数据库结构"""
        if not self.index_file.exists():
            self._save_json(self.index_file, {
                "metadata": {
                    "created": datetime.now().isoformat(),
                    "updated": datetime.now().isoformat(),
                    "total_patents": 0,
                    "last_crawl": None
                },
                "patents": {},
                "keywords": {},
                "applicants": {}
            })

        if not self.citations_file.exists():
            self._save_json(self.citations_file, {
                "metadata": {"updated": datetime.now().isoformat()},
                "citations": {}
            })

        if not self.similar_file.exists():
            self._save_json(self.similar_file, {
                "metadata": {"updated": datetime.now().isoformat()},
                "similar_groups": {}
            })

    def _load_json(self, filepath: Path) -> Dict:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_json(self, filepath: Path, data: Dict):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def crawl_by_keywords(self, keywords: List[str], max_patents: int = 50) -> Dict[str, Any]:
        """
        按关键词爬取专利

        Args:
            keywords: 关键词列表
            max_patents: 最大爬取数量

        Returns:
            爬取结果统计
        """
        stats = {
            "total_found": 0,
            "new_patents": 0,
            "updated_patents": 0,
            "errors": []
        }

        # 构建检索式
        query = " OR ".join(keywords)
        full_query = f"({query}) AND type:发明授权 AND legalStatus:有效专利"

        # 搜索
        result = self.client.search(full_query, page=1, page_size=50)
        patents = result.get("patents", [])
        stats["total_found"] = result.get("total", 0)

        # 加载现有数据库
        db = self._load_json(self.index_file)

        for patent_data in patents[:max_patents]:
            patent_id = patent_data.get("id")

            try:
                # 获取权利要求和说明书
                claims_data = self.client.get_claims(patent_id)
                desc_data = self.client.get_description(patent_id)

                # 更新数据库
                db["patents"][patent_id] = {
                    "id": patent_id,
                    "title": patent_data.get("title"),
                    "applicant": patent_data.get("applicant"),
                    "application_date": patent_data.get("applicationDate"),
                    "ipc": patent_data.get("mainIpc"),
                    "legal_status": patent_data.get("legalStatus"),
                    "crawled_at": datetime.now().isoformat(),
                    "has_claims": bool(claims_data.get("patent", {}).get("claims")),
                    "has_description": bool(desc_data.get("patent", {}).get("description"))
                }

                # 更新申请人索引
                applicant = patent_data.get("applicant", "")
                if applicant:
                    if applicant not in db["applicants"]:
                        db["applicants"][applicant] = []
                    if patent_id not in db["applicants"][applicant]:
                        db["applicants"][applicant].append(patent_id)

                # 更新关键词索引
                for kw in keywords:
                    if kw not in db["keywords"]:
                        db["keywords"][kw] = []
                    if patent_id not in db["keywords"][kw]:
                        db["keywords"][kw].append(patent_id)

                stats["new_patents"] += 1
                print(f"[{stats['new_patents']}] 已爬取: {patent_data.get('title')}")

                # 避免请求过快
                time.sleep(0.5)

            except Exception as e:
                stats["errors"].append({"id": patent_id, "error": str(e)})
                print(f"爬取失败 {patent_id}: {e}")

        # 保存数据库
        db["metadata"]["updated"] = datetime.now().isoformat()
        db["metadata"]["total_patents"] = len(db["patents"])
        db["metadata"]["last_crawl"] = datetime.now().isoformat()
        self._save_json(self.index_file, db)

        return stats

    def expand_by_similarity(self, patent_id: str, max_expansions: int = 10) -> List[str]:
        """
        通过相似专利扩展数据库

        Args:
            patent_id: 种子专利ID
            max_expansions: 最大扩展数量

        Returns:
            新发现的专利ID列表
        """
        try:
            result = self.client.get_similar_patents(patent_id)
            similar_patents = result.get("patents", [])

            new_patents = []
            db = self._load_json(self.index_file)

            for patent in similar_patents[:max_expansions]:
                pid = patent.get("id")
                if pid and pid not in db["patents"]:
                    new_patents.append(pid)

                    # 添加到数据库
                    db["patents"][pid] = {
                        "id": pid,
                        "title": patent.get("title"),
                        "applicant": patent.get("applicant"),
                        "application_date": patent.get("applicationDate"),
                        "ipc": patent.get("mainIpc"),
                        "discovered_via": f"similar:{patent_id}",
                        "crawled_at": datetime.now().isoformat()
                    }

            # 保存相似专利关系
            similar_db = self._load_json(self.similar_file)
            similar_db["similar_groups"][patent_id] = new_patents
            similar_db["metadata"]["updated"] = datetime.now().isoformat()
            self._save_json(self.similar_file, similar_db)

            # 更新主数据库
            db["metadata"]["updated"] = datetime.now().isoformat()
            db["metadata"]["total_patents"] = len(db["patents"])
            self._save_json(self.index_file, db)

            return new_patents

        except Exception as e:
            print(f"相似专利扩展失败: {e}")
            return []

    def build_citation_graph(self, patent_id: str) -> Dict[str, Any]:
        """
        构建专利引用关系图

        Args:
            patent_id: 种子专利ID

        Returns:
            引用关系数据
        """
        try:
            result = self.client.get_citations(patent_id)

            citation_data = {
                "patent_id": patent_id,
                "cited_by": result.get("citedBy", []),  # 被哪些专利引用
                "citing": result.get("citing", []),      # 引用了哪些专利
                "crawled_at": datetime.now().isoformat()
            }

            # 保存引用关系
            citations_db = self._load_json(self.citations_file)
            citations_db["citations"][patent_id] = citation_data
            citations_db["metadata"]["updated"] = datetime.now().isoformat()
            self._save_json(self.citations_file, citations_db)

            return citation_data

        except Exception as e:
            print(f"获取引用数据失败: {e}")
            return {}

    def daily_crawl_task(self):
        """
        每日定时爬取任务

        爬取内容：
        1. 按关键词搜索新专利
        2. 从现有专利扩展相似专利
        3. 更新法律状态
        """
        print(f"=== 开始每日爬取任务 {datetime.now().isoformat()} ===")

        # 1. 按关键词搜索
        keywords_list = [
            ["虚拟电厂", "负荷响应"],
            ["分布式光伏", "光伏并网"],
            ["配电网故障", "故障定位"],
            ["继电保护", "差动保护"],
            ["储能系统", "电池管理"]
        ]

        total_stats = {
            "new_patents": 0,
            "expanded_patents": 0,
            "errors": []
        }

        for keywords in keywords_list:
            print(f"\n--- 搜索关键词: {keywords} ---")
            stats = self.crawl_by_keywords(keywords, max_patents=10)
            total_stats["new_patents"] += stats["new_patents"]
            total_stats["errors"].extend(stats["errors"])

        # 2. 从现有专利扩展相似专利
        db = self._load_json(self.index_file)
        patent_ids = list(db["patents"].keys())[:5]  # 取前5个专利扩展

        print(f"\n--- 扩展相似专利 ---")
        for pid in patent_ids:
            new_ids = self.expand_by_similarity(pid, max_expansions=5)
            total_stats["expanded_patents"] += len(new_ids)
            time.sleep(1)

        print(f"\n=== 爬取完成 ===")
        print(f"新增专利: {total_stats['new_patents']}")
        print(f"扩展专利: {total_stats['expanded_patents']}")
        print(f"错误数量: {len(total_stats['errors'])}")

        return total_stats


# 使用示例
if __name__ == "__main__":
    from patenthub import load_config

    token = load_config()
    builder = PatentDatabaseBuilder(token)

    # 执行每日爬取
    stats = builder.daily_crawl_task()
