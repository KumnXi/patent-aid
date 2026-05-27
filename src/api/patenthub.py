"""
Patenthub API 客户端
用于检索和获取中国专利数据

API文档：https://www.patenthub.cn/api/start.html
"""

import requests
import json
import time
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Patent:
    """专利数据结构"""
    id: str
    title: str
    summary: str
    applicant: str
    application_date: str
    application_number: str
    document_number: str
    document_date: str
    inventor: str
    main_ipc: str
    legal_status: str
    patent_type: str
    claims: Optional[str] = None
    description: Optional[str] = None


class PatenthubClient:
    """Patenthub API客户端"""

    BASE_URL = "https://www.patenthub.cn"

    def __init__(self, token: str):
        """
        初始化客户端

        Args:
            token: API Token
        """
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PatentWriterAssistant/1.0",
            "Accept": "application/json"
        })

    def _request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        发送API请求

        Args:
            endpoint: API端点
            params: 请求参数

        Returns:
            API响应数据

        Raises:
            Exception: API请求失败
        """
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

    def search(self, query: str, scope: str = "cn", page: int = 1,
               page_size: int = 10, sort: str = "relation",
               highlight: bool = False) -> Dict[str, Any]:
        """
        搜索专利

        Args:
            query: 检索式
            scope: 数据范围，cn=中国，all=全球
            page: 页码（最大100）
            page_size: 每页条数（最大50）
            sort: 排序方式（relation/applicationDate/documentDate/rank）
            highlight: 是否高亮

        Returns:
            搜索结果，包含patents列表和分页信息
        """
        params = {
            "q": query,
            "ds": scope,
            "p": page,
            "ps": min(page_size, 50),
            "s": sort,
            "hl": 1 if highlight else 0
        }

        return self._request("/api/s", params)

    def get_claims(self, patent_id: str) -> Dict[str, Any]:
        """
        获取专利权利要求

        Args:
            patent_id: 专利ID（如CN108251808A）

        Returns:
            权利要求数据
        """
        params = {"id": patent_id}
        return self._request("/api/patent/claims", params)

    def get_description(self, patent_id: str) -> Dict[str, Any]:
        """
        获取专利说明书全文

        Args:
            patent_id: 专利ID

        Returns:
            说明书数据
        """
        params = {"id": patent_id}
        return self._request("/api/patent/desc", params)

    def get_basic_info(self, patent_id: str) -> Dict[str, Any]:
        """
        获取专利基本信息

        Args:
            patent_id: 专利ID

        Returns:
            基本信息数据
        """
        params = {"id": patent_id}
        return self._request("/api/patent/base", params)

    def get_similar(self, patent_id: str) -> Dict[str, Any]:
        """
        获取相似专利

        Args:
            patent_id: 专利ID

        Returns:
            相似专利列表
        """
        params = {"id": patent_id}
        return self._request("/api/patent/similar", params)

    def get_full_patent(self, patent_id: str, search_info: Dict = None) -> Patent:
        """
        获取专利完整信息（基本信息+权利要求+说明书）

        Args:
            patent_id: 专利ID
            search_info: 搜索结果中的基本信息（可选）

        Returns:
            完整的专利数据对象
        """
        # 获取基本信息（如果搜索结果中有则优先使用）
        if search_info:
            base_data = search_info
        else:
            base_data = self.get_basic_info(patent_id)

        # 获取权利要求
        claims_data = self.get_claims(patent_id)
        claims_text = claims_data.get("patent", {}).get("claims", "")
        # 清理HTML标签
        claims_text = claims_text.replace("<br/>", "\n").replace("<br>", "\n")

        # 获取说明书
        desc_data = self.get_description(patent_id)
        desc_text = desc_data.get("patent", {}).get("description", "")
        # 清理转义字符
        desc_text = desc_text.replace("\\n", "\n").replace("\\t", "\t")

        # 组装专利对象
        patent = Patent(
            id=patent_id,
            title=base_data.get("title", ""),
            summary=base_data.get("summary", ""),
            applicant=base_data.get("applicant", ""),
            application_date=base_data.get("applicationDate", ""),
            application_number=base_data.get("applicationNumber", base_data.get("patent", {}).get("applicationNumber", "")),
            document_number=base_data.get("documentNumber", base_data.get("patent", {}).get("documentNumber", "")),
            document_date=base_data.get("documentDate", ""),
            inventor=base_data.get("inventor", ""),
            main_ipc=base_data.get("mainIpc", ""),
            legal_status=base_data.get("legalStatus", ""),
            patent_type=base_data.get("type", ""),
            claims=claims_text,
            description=desc_text
        )

        return patent

    def search_power_patents(self, keywords: List[str] = None,
                              page: int = 1, page_size: int = 20,
                              authorized_only: bool = True) -> List[Patent]:
        """
        搜索电力领域专利

        Args:
            keywords: 关键词列表
            page: 页码
            page_size: 每页条数
            authorized_only: 是否只获取授权且有效的专利

        Returns:
            专利列表
        """
        if keywords is None:
            keywords = ["电力系统", "配电网", "智能电网", "变电站"]

        # 构建检索式
        keyword_query = " OR ".join(keywords)

        # 如果只获取授权专利，添加过滤条件
        if authorized_only:
            query = f"({keyword_query}) AND type:发明授权 AND legalStatus:有效专利"
        else:
            query = keyword_query

        # 搜索
        result = self.search(query, page=page, page_size=page_size)

        # 提取专利列表
        patents = []
        for item in result.get("patents", []):
            patent = Patent(
                id=item.get("id", ""),
                title=item.get("title", ""),
                summary=item.get("summary", ""),
                applicant=item.get("applicant", ""),
                application_date=item.get("applicationDate", ""),
                application_number=item.get("applicationNumber", ""),
                document_number=item.get("documentNumber", ""),
                document_date=item.get("documentDate", ""),
                inventor=item.get("inventor", ""),
                main_ipc=item.get("mainIpc", ""),
                legal_status=item.get("legalStatus", ""),
                patent_type=item.get("type", "")
            )
            patents.append(patent)

        return patents

    def download_pdf(self, patent_id: str, output_dir: str = "data/reference_patents") -> Optional[str]:
        """
        下载专利PDF全文

        Args:
            patent_id: 专利ID
            output_dir: 输出目录

        Returns:
            PDF文件路径，失败返回None
        """
        url = f"{self.BASE_URL}/api/pdf"
        params = {
            "t": self.token,
            "id": patent_id,
            "v": 1
        }

        try:
            response = self.session.get(url, params=params, timeout=60, stream=True)

            # 检查是否是PDF文件
            content_type = response.headers.get("Content-Type", "")
            if "application/pdf" in content_type or "application/octet-stream" in content_type:
                # 确定保存路径
                output_path = Path(output_dir)
                output_path.mkdir(parents=True, exist_ok=True)

                # 从Content-Disposition获取文件名
                disposition = response.headers.get("Content-Disposition", "")
                if "filename" in disposition:
                    filename = disposition.split("filename=")[-1].strip('"')
                else:
                    filename = f"{patent_id}.pdf"

                filepath = output_path / filename

                # 保存文件
                with open(filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                print(f"PDF已下载: {filepath}")
                return str(filepath)
            else:
                # 可能是错误页面或限额用完
                print(f"PDF下载失败: 非PDF响应 (Content-Type: {content_type})")
                return None

        except Exception as e:
            print(f"PDF下载异常: {str(e)}")
            return None

    def save_patent_to_file(self, patent: Patent, output_dir: str = "data/reference_patents"):
        """
        保存专利到文件

        Args:
            patent: 专利对象
            output_dir: 输出目录
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 确定分类目录
        category = self._classify_patent(patent)
        category_dir = output_path / category
        category_dir.mkdir(exist_ok=True)

        # 生成文件名（清理非法字符）
        safe_title = patent.title[:30].replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
        filename = f"{patent.id}_{safe_title}.md"
        filepath = category_dir / filename

        # 生成Markdown内容
        content = self._generate_markdown(patent)

        # 写入文件
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"专利已保存: {filepath}")

        # 更新索引
        self._update_index(patent, category, str(filepath))

    def _classify_patent(self, patent: Patent) -> str:
        """根据IPC分类号和关键词对专利进行分类"""
        ipc = patent.main_ipc.upper()
        title = patent.title
        summary = patent.summary

        # 根据IPC分类
        if "H02" in ipc:
            if "H02J" in ipc:
                return "power_system"
            elif "H02B" in ipc or "H02G" in ipc:
                return "equipment"
            elif "H02H" in ipc:
                return "protection"
            elif "H02M" in ipc:
                return "automation"

        # 根据关键词分类
        keywords_map = {
            "renewable": ["光伏", "风电", "储能", "新能源", "太阳能", "风力"],
            "smart_grid": ["智能电网", "配电自动化", "微电网", "需求响应", "虚拟电厂"],
            "protection": ["继电保护", "差动保护", "距离保护", "故障隔离"],
            "automation": ["调度", "自动化", "监控", "SCADA"]
        }

        text = f"{title} {summary}"
        for category, keywords in keywords_map.items():
            if any(kw in text for kw in keywords):
                return category

        return "power_system"  # 默认分类

    def _generate_markdown(self, patent: Patent) -> str:
        """生成专利的Markdown格式内容"""
        content = f"""# {patent.title}

## 基本信息
- **专利号**：{patent.document_number}
- **申请号**：{patent.application_number}
- **申请日**：{patent.application_date}
- **公开日**：{patent.document_date}
- **申请人**：{patent.applicant}
- **发明人**：{patent.inventor}
- **技术领域**：{patent.main_ipc}
- **专利类型**：{patent.patent_type}
- **法律状态**：{patent.legal_status}

## 摘要
{patent.summary}

"""
        if patent.claims:
            content += f"""## 权利要求书
{patent.claims}

"""
        if patent.description:
            content += f"""## 说明书
{patent.description}

"""
        content += """## 学习要点
- **创新点**：（待分析）
- **权利要求结构**：（待分析）
- **技术效果描述**：（待分析）
- **术语使用**：（待分析）
- **可借鉴之处**：（待分析）
"""
        return content

    def _update_index(self, patent: Patent, category: str, filepath: str):
        """更新专利索引文件"""
        index_path = Path("data/reference_patents/index.json")

        # 读取现有索引
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        else:
            index = {
                "metadata": {"version": "1.0", "total_patents": 0},
                "patents": [],
                "categories": {}
            }

        # 添加专利到索引
        patent_entry = {
            "id": patent.id,
            "title": patent.title,
            "category": category,
            "filepath": filepath,
            "applicant": patent.applicant,
            "application_date": patent.application_date
        }

        # 避免重复
        if not any(p["id"] == patent.id for p in index["patents"]):
            index["patents"].append(patent_entry)
            index["metadata"]["total_patents"] += 1

            # 更新分类计数
            if category not in index["categories"]:
                index["categories"][category] = {"name": category, "count": 0, "patents": []}
            index["categories"][category]["count"] += 1
            index["categories"][category]["patents"].append(patent.id)

        # 保存索引
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)


def load_config() -> str:
    """从配置文件加载Token"""
    config_path = Path("config/api_config.json")
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config.get("patenthub", {}).get("token", "")
    return ""


# 使用示例
if __name__ == "__main__":
    TOKEN = load_config()
    if not TOKEN:
        print("错误：未找到API Token，请检查 config/api_config.json")
        exit(1)

    client = PatenthubClient(TOKEN)

    # 搜索电力领域专利
    patents = client.search_power_patents(["虚拟电厂", "分布式光伏"])

    for p in patents[:5]:
        print(f"{p.id}: {p.title}")
