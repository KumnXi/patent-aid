"""
多源专利数据管理器
统一管理 Patenthub（搜索发现）+ Google Patents（全文获取）

数据流：
    Patenthub搜索 → 获取专利ID列表
    Google Patents → 获取完整权利要求+说明书
    降级策略: Google失败 → Patenthub PDF → 标记待处理
"""

import json
import time
from typing import Optional, Dict, List, Any
from pathlib import Path
from datetime import datetime

from src.api.patenthub import PatenthubClient, load_config
from src.api.google_patents import GooglePatentsClient, create_client_from_config


class PatentSourceManager:
    """多源专利数据管理器"""

    def __init__(self, db_path: str = "data/patent_database"):
        """
        初始化多源管理器

        Args:
            db_path: 数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.index_file = self.db_path / "index.json"

        # 初始化 Patenthub 客户端（用于搜索）
        patenthub_token = load_config()
        self.patenthub = PatenthubClient(patenthub_token) if patenthub_token else None

        # 初始化 Google Patents 客户端（用于全文获取）
        self.google = create_client_from_config()
        self._google_available = None  # 延迟检测

        # 统计
        self.stats = {
            "google_success": 0,
            "google_failed": 0,
            "patenthub_fallback": 0,
            "errors": []
        }

    def is_google_available(self) -> bool:
        """检测 Google Patents 是否可用（代理是否启动）"""
        if self._google_available is None:
            print("检测 Google Patents 连接...")
            self._google_available = self.google.check_proxy()
            if self._google_available:
                print("  Google Patents 可用")
            else:
                print("  Google Patents 不可用，将使用 Patenthub 降级方案")
        return self._google_available

    def discover_patents(self, keywords: List[str], max_results: int = 20) -> List[Dict[str, Any]]:
        """
        搜索发现新专利（使用Patenthub免费搜索接口）

        Args:
            keywords: 关键词列表
            max_results: 最大结果数

        Returns:
            专利基本信息列表
        """
        if not self.patenthub:
            print("错误: Patenthub未配置")
            return []

        # 构建检索式
        keyword_query = " OR ".join(keywords)
        query = f"({keyword_query}) AND ipc:H02 AND type:发明授权 AND legalStatus:有效专利"

        try:
            result = self.patenthub.search(query, page=1, page_size=min(max_results, 50))
            patents = result.get("patents", [])

            # 过滤已存在的
            db = self._load_db()
            new_patents = []
            for p in patents:
                pid = p.get("id", "")
                if pid and pid not in db["patents"]:
                    new_patents.append({
                        "id": pid,
                        "title": p.get("title", ""),
                        "applicant": p.get("applicant", ""),
                        "application_date": p.get("applicationDate", ""),
                        "ipc": p.get("mainIpc", ""),
                        "summary": p.get("summary", ""),
                    })

            print(f"  搜索到 {len(patents)} 篇，其中新专利 {len(new_patents)} 篇")
            return new_patents

        except Exception as e:
            print(f"  搜索失败: {e}")
            return []

    def fetch_full_text(self, patent_id: str) -> Optional[Dict[str, str]]:
        """
        获取专利全文（智能选择数据源）

        优先级: Google Patents → Patenthub PDF提取

        Args:
            patent_id: 专利号

        Returns:
            {"claims": ..., "description": ...} 或 None
        """
        # 优先使用 Google Patents
        if self.is_google_available():
            result = self._fetch_from_google(patent_id)
            if result:
                self.stats["google_success"] += 1
                return result
            self.stats["google_failed"] += 1

        # 降级: 标记为待处理（后续通过PDF提取）
        print(f"  [{patent_id}] 全文获取失败，标记待处理")
        return None

    def _fetch_from_google(self, patent_id: str) -> Optional[Dict[str, str]]:
        """从 Google Patents 获取全文"""
        try:
            patent = self.google.get_patent_detail(patent_id)
            if not patent:
                return None

            result = {}
            if patent.claims:
                result["claims"] = patent.claims
            if patent.description:
                result["description"] = patent.description

            # 至少要有权利要求才算成功
            if "claims" not in result:
                print(f"  [{patent_id}] Google Patents 未解析到权利要求")
                return None

            return result

        except Exception as e:
            print(f"  [{patent_id}] Google Patents 异常: {e}")
            return None

    def add_patent_to_db(self, patent_info: Dict[str, Any],
                         full_text: Optional[Dict[str, str]] = None):
        """
        将专利添加到数据库

        Args:
            patent_info: 基本信息 {id, title, applicant, ...}
            full_text: 全文 {claims, description}（可选）
        """
        db = self._load_db()
        patent_id = patent_info["id"]

        # 构建数据库条目
        entry = {
            "id": patent_id,
            "title": patent_info.get("title", ""),
            "applicant": patent_info.get("applicant", ""),
            "application_date": patent_info.get("application_date", ""),
            "ipc": patent_info.get("ipc", ""),
            "summary": patent_info.get("summary", ""),
            "crawled_at": datetime.now().isoformat(),
            "source": "multi_source",
            "has_claims": False,
            "has_description": False,
        }

        # 合并全文
        if full_text:
            if "claims" in full_text:
                entry["claims"] = full_text["claims"]
                entry["has_claims"] = True
            if "description" in full_text:
                entry["description"] = full_text["description"]
                entry["has_description"] = True
            entry["text_source"] = "google_patents"
            entry["text_fetched_at"] = datetime.now().isoformat()

        db["patents"][patent_id] = entry

        # 更新元数据
        db["metadata"]["updated"] = datetime.now().isoformat()
        db["metadata"]["total_patents"] = len(db["patents"])

        self._save_db(db)

    def batch_fetch(self, patent_list: List[Dict[str, Any]],
                    fetch_text: bool = True) -> Dict[str, Any]:
        """
        批量处理专利列表

        Args:
            patent_list: 专利基本信息列表
            fetch_text: 是否获取全文

        Returns:
            处理统计
        """
        stats = {
            "total": len(patent_list),
            "added": 0,
            "with_text": 0,
            "failed": 0,
            "skipped": 0,
        }

        db = self._load_db()

        for i, patent_info in enumerate(patent_list):
            patent_id = patent_info["id"]

            # 跳过已存在
            if patent_id in db["patents"]:
                existing = db["patents"][patent_id]
                if existing.get("has_claims"):
                    stats["skipped"] += 1
                    continue

            print(f"\n[{i+1}/{len(patent_list)}] 处理: {patent_id} - {patent_info.get('title', '')[:30]}")

            # 获取全文
            full_text = None
            if fetch_text:
                full_text = self.fetch_full_text(patent_id)

            # 添加到数据库
            self.add_patent_to_db(patent_info, full_text)
            stats["added"] += 1

            if full_text and full_text.get("claims"):
                stats["with_text"] += 1
                print(f"  [OK] 权利要求{len(full_text.get('claims', ''))}字 + 说明书{len(full_text.get('description', ''))}字")
            else:
                stats["failed"] += 1

        return stats

    def get_pending_patents(self) -> List[str]:
        """获取缺少全文的专利ID列表"""
        db = self._load_db()
        pending = []
        for pid, p in db["patents"].items():
            if not p.get("has_claims") or not p.get("has_description"):
                pending.append(pid)
        return pending

    def backfill_missing_text(self, max_count: int = 50) -> Dict[str, Any]:
        """
        补全数据库中缺少全文的专利

        Args:
            max_count: 最大处理数量

        Returns:
            补全统计
        """
        pending = self.get_pending_patents()
        print(f"待补全专利: {len(pending)} 篇")

        if not pending:
            return {"total": 0, "filled": 0, "failed": 0}

        stats = {"total": len(pending), "filled": 0, "failed": 0}

        for i, patent_id in enumerate(pending[:max_count]):
            print(f"\n[{i+1}/{min(len(pending), max_count)}] 补全: {patent_id}")

            full_text = self.fetch_full_text(patent_id)
            if full_text:
                # 更新数据库
                db = self._load_db()
                if patent_id in db["patents"]:
                    if "claims" in full_text:
                        db["patents"][patent_id]["claims"] = full_text["claims"]
                        db["patents"][patent_id]["has_claims"] = True
                    if "description" in full_text:
                        db["patents"][patent_id]["description"] = full_text["description"]
                        db["patents"][patent_id]["has_description"] = True
                    db["patents"][patent_id]["text_source"] = "google_patents"
                    db["patents"][patent_id]["text_fetched_at"] = datetime.now().isoformat()
                    self._save_db(db)
                    stats["filled"] += 1
                    print(f"  [OK] 已补全")
            else:
                stats["failed"] += 1

        return stats

    def _load_db(self) -> Dict:
        """加载数据库"""
        if self.index_file.exists():
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "metadata": {
                "created": datetime.now().isoformat(),
                "updated": datetime.now().isoformat(),
                "total_patents": 0,
            },
            "patents": {},
            "keywords": {},
            "applicants": {}
        }

    def _save_db(self, db: Dict):
        """保存数据库"""
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)

    def print_stats(self):
        """打印统计信息"""
        db = self._load_db()
        total = len(db["patents"])
        with_claims = sum(1 for p in db["patents"].values() if p.get("has_claims"))
        with_desc = sum(1 for p in db["patents"].values() if p.get("has_description"))
        with_both = sum(1 for p in db["patents"].values()
                       if p.get("has_claims") and p.get("has_description"))

        print(f"\n{'='*40}")
        print(f"数据库统计:")
        print(f"  总专利数: {total}")
        print(f"  有权利要求: {with_claims}")
        print(f"  有说明书: {with_desc}")
        print(f"  完整文本: {with_both}/{total}")
        print(f"{'='*40}")
