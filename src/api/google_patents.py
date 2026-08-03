"""
Google Patents 客户端
通过代理访问 Google Patents，获取专利全文（权利要求 + 说明书）

优势：
- 免费、无每日下载限额
- 直接获取结构化全文，无需PDF提取
- 覆盖几乎所有中国专利

使用方式：
    from src.api.google_patents import GooglePatentsClient
    client = GooglePatentsClient(proxy="http://127.0.0.1:7890")
    patent = client.get_patent_detail("CN117977607B")
"""

import requests
import json
import time
import re
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path
from bs4 import BeautifulSoup


@dataclass
class GooglePatent:
    """Google Patents 专利数据结构"""
    id: str
    title: str = ""
    abstract: str = ""
    claims: str = ""
    description: str = ""
    applicant: str = ""
    inventor: str = ""
    application_date: str = ""
    publication_date: str = ""
    application_number: str = ""
    ipc_codes: list = field(default_factory=list)
    pdf_url: str = ""
    legal_status: str = ""
    url: str = ""


class GooglePatentsClient:
    """Google Patents 客户端 - 通过代理获取专利全文"""

    def __init__(self, proxy: str = "http://127.0.0.1:7890",
                 base_url: str = "https://patents.google.com",
                 language: str = "zh",
                 request_interval: float = 5.0,
                 max_retries: int = 3,
                 timeout: int = 30):
        """
        初始化客户端

        Args:
            proxy: 代理地址（Clash默认端口7890）
            base_url: Google Patents 基础URL
            language: 返回语言（zh=中文）
            request_interval: 请求间隔秒数（避免429）
            max_retries: 最大重试次数
            timeout: 请求超时秒数
        """
        self.base_url = base_url.rstrip("/")
        self.language = language
        self.request_interval = request_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._proxy = proxy  # 保存代理地址用于重建session

        # 配置会话
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        # 设置代理
        if proxy:
            self.session.proxies = {
                "http": proxy,
                "https": proxy,
            }

        self._last_request_time = 0

    def _wait_interval(self):
        """等待请求间隔，避免频率过高"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self._last_request_time = time.time()

    def _rebuild_session(self):
        """重建HTTP会话（代理SSL错误后清除连接池污染）"""
        self.session.close()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        if self._proxy:
            self.session.proxies = {
                "http": self._proxy,
                "https": self._proxy,
            }

    def _fetch_page(self, url: str) -> Optional[str]:
        """
        获取页面HTML，带重试和指数退避

        Args:
            url: 目标URL

        Returns:
            HTML文本，失败返回None
        """
        for attempt in range(self.max_retries):
            try:
                self._wait_interval()
                response = self.session.get(url, timeout=self.timeout)

                if response.status_code == 200:
                    # 强制UTF-8解码（Google Patents不总是在header中指定charset）
                    response.encoding = 'utf-8'
                    return response.text
                elif response.status_code == 429:
                    # 频率限制，指数退避
                    wait_time = (2 ** attempt) * 5
                    print(f"  [429] 频率限制，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                elif response.status_code == 503:
                    # 服务不可用（限流），指数退避
                    wait_time = (2 ** attempt) * 15
                    print(f"  [503] 服务限流，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    if attempt >= 1:
                        self._rebuild_session()
                elif response.status_code == 404:
                    print(f"  [404] 页面不存在: {url}")
                    return None
                else:
                    print(f"  [HTTP {response.status_code}] 请求失败: {url}")
                    time.sleep(2)

            except requests.exceptions.ProxyError as e:
                # 代理SSL错误：指数退避重试，而非直接放弃
                wait_time = (2 ** attempt) * 3
                print(f"  [代理SSL错误] 第{attempt+1}次，等待{wait_time}秒后重试...")
                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)
                    # 重建session以清除可能的连接池污染
                    self._rebuild_session()
                else:
                    print(f"  [代理SSL错误] 已达最大重试次数，跳过")
                    return None
            except requests.exceptions.SSLError as e:
                wait_time = (2 ** attempt) * 3
                print(f"  [SSL错误] 第{attempt+1}次，等待{wait_time}秒后重试...")
                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)
                else:
                    return None
            except requests.exceptions.Timeout:
                print(f"  [超时] 第{attempt+1}次重试...")
                time.sleep(2)
            except requests.exceptions.ConnectionError as e:
                print(f"  [连接错误] {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(3)
                else:
                    return None

        return None

    def get_patent_detail(self, patent_id: str) -> Optional[GooglePatent]:
        """
        获取专利完整信息（权利要求 + 说明书 + 元数据）

        Args:
            patent_id: 专利号（如 CN117977607B）

        Returns:
            GooglePatent对象，失败返回None
        """
        # 构建URL: https://patents.google.com/patent/CN117977607B/zh
        url = f"{self.base_url}/patent/{patent_id}/{self.language}"

        html = self._fetch_page(url)
        if not html:
            return None

        return self._parse_patent_page(html, patent_id, url)

    def _parse_patent_page(self, html: str, patent_id: str, url: str) -> Optional[GooglePatent]:
        """
        解析专利详情页面

        Google Patents 页面结构：
        - <section itemprop="claims"> 权利要求
        - <section itemprop="description"> 说明书
        - <div class="abstract"> 摘要
        - <h1 class="title"> 标题
        - PDF链接在 <a> 标签中
        """
        soup = BeautifulSoup(html, "lxml")

        patent = GooglePatent(id=patent_id, url=url)

        # === 标题 ===
        # Google Patents 标题可能在多种标签中
        title_tag = soup.find("h1", class_="title")
        if not title_tag:
            title_tag = soup.find("h1", itemprop="name")
        if not title_tag:
            title_tag = soup.find("h1")
        if title_tag:
            patent.title = title_tag.get_text(strip=True)
            # 移除标题中的专利号前缀
            patent.title = re.sub(r'^' + re.escape(patent_id) + r'\s*[-\u2013]\s*', '', patent.title)
            # 移除尾部的 " - Google Patents"
            patent.title = re.sub(r'\s*-\s*Google Patents$', '', patent.title)

        # === 摘要 ===
        abstract_tag = soup.find("div", class_="abstract")
        if not abstract_tag:
            abstract_tag = soup.find("section", itemprop="abstract")
        if abstract_tag:
            patent.abstract = abstract_tag.get_text(strip=True)

        # === 权利要求 ===
        claims_section = soup.find("section", itemprop="claims")
        if claims_section:
            patent.claims = self._extract_section_text(claims_section)

        # === 说明书 ===
        desc_section = soup.find("section", itemprop="description")
        if desc_section:
            patent.description = self._extract_section_text(desc_section)

        # === 元数据（从页面表格提取） ===
        self._parse_metadata(soup, patent)

        # === PDF链接 ===
        pdf_link = soup.find("a", href=re.compile(r"patentimages\.storage\.googleapis\.com"))
        if pdf_link:
            patent.pdf_url = pdf_link["href"]
            # 确保是完整URL
            if patent.pdf_url.startswith("//"):
                patent.pdf_url = "https:" + patent.pdf_url

        return patent

    def _extract_section_text(self, section) -> str:
        """
        从section标签提取结构化文本

        保留段落结构和编号，移除HTML标签
        """
        parts = []

        # 遍历所有段落和标题
        for elem in section.find_all(["p", "h2", "h3", "div"], recursive=True):
            # 跳过嵌套的div（避免重复）
            if elem.name == "div" and elem.find(["p", "h2", "h3"]):
                continue

            text = elem.get_text(strip=True)
            if text:
                # 检测是否是章节标题
                if elem.name in ["h2", "h3"]:
                    parts.append(f"\n{text}\n")
                else:
                    parts.append(text)

        # 如果上面没提取到内容，fallback到全文
        if not parts:
            text = section.get_text(separator="\n", strip=True)
            return text

        return "\n".join(parts)

    def _parse_metadata(self, soup: BeautifulSoup, patent: GooglePatent):
        """从页面元数据表格提取著录信息"""
        # Google Patents 使用 <table> 或 <dl> 展示元数据
        # 查找包含"申请人"、"发明人"等信息的区域

        # 方法1: 查找 state-modifier 标签中的结构化数据
        meta_items = soup.find_all("state-modifier")
        for item in meta_items:
            data_result = item.get("data-result", "")
            if data_result:
                patent.application_number = data_result

        # 方法2: 从 <dl> 或表格中提取
        # 申请人/专利权人
        applicant_label = soup.find(string=re.compile(r"申请人|专利权人|Assignee"))
        if applicant_label:
            parent = applicant_label.find_parent()
            if parent:
                next_elem = parent.find_next_sibling()
                if next_elem:
                    patent.applicant = next_elem.get_text(strip=True)

        # 发明人
        inventor_label = soup.find(string=re.compile(r"发明人|Inventor"))
        if inventor_label:
            parent = inventor_label.find_parent()
            if parent:
                next_elem = parent.find_next_sibling()
                if next_elem:
                    patent.inventor = next_elem.get_text(strip=True)

        # 申请日
        date_label = soup.find(string=re.compile(r"申请日|Filing"))
        if date_label:
            parent = date_label.find_parent()
            if parent:
                next_elem = parent.find_next_sibling()
                if next_elem:
                    patent.application_date = next_elem.get_text(strip=True)

        # 公开日
        pub_label = soup.find(string=re.compile(r"公开日|Publication"))
        if pub_label:
            parent = pub_label.find_parent()
            if parent:
                next_elem = parent.find_next_sibling()
                if next_elem:
                    patent.publication_date = next_elem.get_text(strip=True)

        # 方法3: 从 JSON-LD 提取（如果存在）
        json_ld = soup.find("script", type="application/ld+json")
        if json_ld:
            try:
                ld_data = json.loads(json_ld.string)
                if isinstance(ld_data, dict):
                    patent.title = patent.title or ld_data.get("name", "")
                    patent.application_number = patent.application_number or ld_data.get("applicationNumber", "")
                    patent.publication_date = patent.publication_date or ld_data.get("datePublished", "")
                    patent.application_date = patent.application_date or ld_data.get("dateFiled", "")
                    # 发明人
                    inventors = ld_data.get("inventor", [])
                    if inventors and not patent.inventor:
                        if isinstance(inventors, list):
                            names = [inv.get("name", "") for inv in inventors if isinstance(inv, dict)]
                            patent.inventor = "; ".join(names)
                    # 申请人
                    assignee = ld_data.get("assignee", {})
                    if assignee and not patent.applicant:
                        if isinstance(assignee, dict):
                            patent.applicant = assignee.get("name", "")
            except (json.JSONDecodeError, TypeError):
                pass

        # IPC分类号
        ipc_links = soup.find_all("a", href=re.compile(r"classification"))
        for link in ipc_links:
            code = link.get_text(strip=True)
            if code and re.match(r'^[A-H]\d{2}', code):
                if code not in patent.ipc_codes:
                    patent.ipc_codes.append(code)

    def search_patents(self, query: str, num_results: int = 20,
                       country: str = "CN") -> list:
        """
        搜索专利（使用 XHR API）

        Args:
            query: 搜索关键词
            num_results: 期望返回数量
            country: 国家代码

        Returns:
            专利ID列表
        """
        # 使用 Google Patents XHR API（返回 JSON）
        xhr_url = f"{self.base_url}/xhr/query"
        params = {
            "url": f"q={query}&country={country}&type=PATENT&num={num_results}"
        }

        try:
            self._wait_interval()
            response = self.session.get(xhr_url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                # 解析结果
                patent_ids = []
                results = data.get("results", {}).get("cluster", [])
                for cluster in results:
                    for result in cluster.get("result", []):
                        patent = result.get("patent", {})
                        pn = patent.get("publication_number", "")
                        if pn and country in pn:
                            patent_ids.append(pn)
                return patent_ids[:num_results]
        except Exception as e:
            # XHR 失败，回退到 HTML 解析
            pass

        # 回退：HTML 解析
        search_url = f"{self.base_url}/?q={query}&country={country}&type=PATENT"
        html = self._fetch_page(search_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        patent_ids = []

        # 从链接提取专利号
        for link in soup.find_all("a", href=re.compile(r"/patent/CN")):
            match = re.search(r'/patent/(CN\d+[A-Z]\d*)', link.get("href", ""))
            if match:
                pid = match.group(1)
                if pid not in patent_ids:
                    patent_ids.append(pid)

        return patent_ids[:num_results]

    def download_pdf(self, patent_id: str, pdf_url: str = None,
                     output_dir: str = "data/patent_pdfs") -> Optional[str]:
        """
        下载专利PDF

        Args:
            patent_id: 专利号
            pdf_url: PDF直链（如果已知）
            output_dir: 输出目录

        Returns:
            保存的文件路径，失败返回None
        """
        # 如果没有提供URL，先获取
        if not pdf_url:
            patent = self.get_patent_detail(patent_id)
            if not patent or not patent.pdf_url:
                print(f"  未找到PDF链接: {patent_id}")
                return None
            pdf_url = patent.pdf_url

        # 下载PDF
        try:
            self._wait_interval()
            response = self.session.get(pdf_url, timeout=60, stream=True)

            if response.status_code != 200:
                print(f"  PDF下载失败 [HTTP {response.status_code}]: {patent_id}")
                return None

            # 保存文件
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            filepath = output_path / f"{patent_id}.pdf"

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"  PDF已下载: {filepath}")
            return str(filepath)

        except Exception as e:
            print(f"  PDF下载异常: {e}")
            return None

    def check_proxy(self) -> bool:
        """
        检查代理是否可用（5秒超时，失败不阻塞）

        Returns:
            True=代理正常
        """
        try:
            response = self.session.get(
                f"{self.base_url}/patent/CN117977607B/{self.language}",
                timeout=5
            )
            return response.status_code == 200
        except Exception:
            return False


def load_google_config() -> Dict[str, Any]:
    """从配置文件加载 Google Patents 配置"""
    config_path = Path("config/api_config.json")
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config.get("google_patents", {})
    return {}


def create_client_from_config() -> GooglePatentsClient:
    """根据配置文件创建客户端实例"""
    config = load_google_config()
    return GooglePatentsClient(
        proxy=config.get("proxy", "http://127.0.0.1:7890"),
        base_url=config.get("base_url", "https://patents.google.com"),
        language=config.get("language", "zh"),
        request_interval=config.get("request_interval", 3),
        max_retries=config.get("max_retries", 3),
        timeout=config.get("timeout", 30),
    )


# 使用示例
if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    client = create_client_from_config()

    # 检查代理
    print("检查代理连接...")
    if client.check_proxy():
        print("代理连接正常")
    else:
        print("代理连接失败，请确认Clash已启动")
        exit(1)

    # 测试获取一篇专利
    print("\n获取专利 CN117977607B ...")
    patent = client.get_patent_detail("CN117977607B")
    if patent:
        print(f"标题: {patent.title}")
        print(f"申请人: {patent.applicant}")
        print(f"权利要求: {len(patent.claims)}字")
        print(f"说明书: {len(patent.description)}字")
        print(f"PDF链接: {patent.pdf_url[:80]}...")
    else:
        print("获取失败")
