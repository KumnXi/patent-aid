"""CNIPA 官方标准化著录数据导入（免费、官方、免代理、免Firecrawl额度）

数据源: data/cnipa_raw/ 下的官方数据包（用户通过 CNIPA 数据服务获取）
  - 外层 zip（如 20260728.zip）含 5 个内层 zip + 主索引 XML
  - 每个内层 zip 含 3908 条详情 XML（著录+摘要+IPC）

流程:
  1. 解压外层 zip（.NET 处理，Python zipfile 兼容性差）
  2. 逐内层 zip 用 Python 流式解析详情 XML
  3. 增量入库: 只添加库中没有的专利（著录+摘要，不存全文 → 轻量）

用法:
    python scripts/cnipa_official_import.py                       # 处理 data/cnipa_raw 全部数据包
    python scripts/cnipa_official_import.py --limit 100           # 只处理前100条（试跑）
    python scripts/cnipa_official_import.py --dry-run             # 只统计不写库
    python scripts/cnipa_official_import.py --extract-dir output/cnipa_extract/outer

注意:
    - 外层 zip 需先解压（脚本自动调用 .NET PowerShell 完成）
    - 只入库著录信息（title/summary/applicant/ipc/dates），全文不存 → 轻量
"""

import sys
import io
import json
import time
import re
import subprocess
import zipfile
import argparse
from pathlib import Path
from datetime import datetime
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "patent_database" / "index.json"
RAW_DIR = PROJECT_ROOT / "data" / "cnipa_raw"

NS = {
    "base": "http://www.sipo.gov.cn/XMLSchema/base",
    "business": "http://www.sipo.gov.cn/XMLSchema/business",
}


def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    db["metadata"]["updated"] = datetime.now().isoformat()
    db["metadata"]["total_patents"] = len(db["patents"])
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def extract_outer_zip(extract_dir: Path) -> bool:
    """用 .NET 解压外层 zip（Python zipfile 读不了外层）"""
    zips = list(RAW_DIR.rglob("*.zip"))
    if not zips:
        print("[跳过] data/cnipa_raw 下没有 zip 数据包")
        return False
    for zpath in zips:
        # 已解压过则跳过
        marker = extract_dir / f"{zpath.stem}.done"
        if marker.exists():
            print(f"[已解压] {zpath.name}")
            continue
        print(f"[解压] {zpath.name} ({zpath.stat().st_size/1024/1024:.0f} MB) ...")
        ps = (
            "Add-Type -AssemblyName System.IO.Compression.FileSystem; "
            f'$zpath = "{zpath}"; '
            f'$outdir = "{extract_dir}"; '
            "New-Item -ItemType Directory -Force -Path $outdir | Out-Null; "
            "$zip = [System.IO.Compression.ZipFile]::OpenRead($zpath); "
            "foreach ($e in $zip.Entries) { "
            '  $safe = $e.FullName.TrimStart("/") -replace "/", "\"; '
            "  $target = Join-Path $outdir $safe; "
            "  $dir = Split-Path $target -Parent; "
            '  if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }; '
            '  if ($e.Length -eq 0) { continue }; '
            "  [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $target, $true); "
            "}; "
            "$zip.Dispose()"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            print(f"  [失败] {r.stderr[-300:]}")
            return False
        marker.write_text("ok")
        print(f"  [完成] {zpath.name}")
    return True


def _extract_first(xml_text: str, tag: str) -> str:
    """用正则提取第一个指定标签的文本（支持命名空间）"""
    m = re.search(r"<[a-zA-Z0-9_]+:" + tag + r"[^>]*>(.*?)</[a-zA-Z0-9_]+:" + tag + r">", xml_text, re.S)
    return m.group(1).strip() if m else ""


def _extract_all(xml_text: str, tag: str) -> list:
    """用正则提取所有指定标签的文本"""
    out = []
    for m in re.finditer(r"<[a-zA-Z0-9_]+:" + tag + r"[^>]*>(.*?)</[a-zA-Z0-9_]+:" + tag + r">", xml_text, re.S):
        t = m.group(1).strip()
        if t:
            out.append(t)
    return out


def parse_detail_xml(xml_text: str) -> dict:
    """解析单条详情 XML → 著录信息 dict（正则提取，结构已知）"""
    # 公开号（去前导零 → CN 标准格式）
    pub_num = _extract_first(xml_text, "DocNumber")
    if not pub_num or not pub_num.isdigit():
        return None
    pub_num = str(int(pub_num))
    kind = _extract_first(xml_text, "Kind") or "B"
    pid = f"CN{pub_num}{kind}"

    # 标题
    titles = _extract_all(xml_text, "InventionTitle")
    title = titles[0] if titles else ""

    # 摘要
    abs_parts = _extract_all(xml_text, "Paragraphs")
    summary = "".join(abs_parts).strip()

    # IPC（base:Text 如 "G06F   16/176   (2019.01)"，规范化成 G06F16/176）
    ipc_codes = []
    for m in re.finditer(r"<[a-zA-Z0-9_]+:Text>([^<]+)</[a-zA-Z0-9_]+:Text>", xml_text):
        t = m.group(1).strip()
        if re.match(r"^[A-H]\d{2}[A-Z]", t):
            parts = t.split()
            if parts:
                code = parts[0].strip()
                # 补全子组: "G06F 16/176" → "G06F16/176"
                if len(parts) > 1 and re.match(r"^\d+/\d+$", parts[1]):
                    code = parts[0] + parts[1]
                code = code.replace(" ", "")
                if code not in ipc_codes:
                    ipc_codes.append(code)
    ipc = "; ".join(ipc_codes)

    # 申请人（Applicant 下 AddressBook/Name）
    applicants = []
    for m in re.finditer(r"<[a-zA-Z0-9_]+:Applicant[^>]*>.*?<[a-zA-Z0-9_]+:Name>(.*?)</[a-zA-Z0-9_]+:Name>", xml_text, re.S):
        t = m.group(1).strip()
        if t and t not in applicants:
            applicants.append(t)
    applicant = "; ".join(applicants)

    # 发明人
    inventors = []
    for m in re.finditer(r"<[a-zA-Z0-9_]+:Inventor[^>]*>.*?<[a-zA-Z0-9_]+:Name>(.*?)</[a-zA-Z0-9_]+:Name>", xml_text, re.S):
        t = m.group(1).strip()
        if t and t not in inventors:
            inventors.append(t)
    inventor = "; ".join(inventors)

    # 申请号/日期（Date 顺序: 公开日 → 申请日 → 其他）
    app_nums = _extract_all(xml_text, "DocNumber")
    app_num = app_nums[2] if len(app_nums) > 2 else (app_nums[1] if len(app_nums) > 1 else "")
    dates = _extract_all(xml_text, "Date")
    pub_date = dates[0] if dates else ""
    app_date = dates[1] if len(dates) > 1 else ""
    # 修正: 第一个 Date 是公开日, 第二个通常是申请日；但 PublicationsReference 可能有多个 Date
    # 用 ApplicationReference 区块内的 Date 作为申请日
    m_app = re.search(r"<[a-zA-Z0-9_]+:ApplicationReference[^>]*>.*?<[a-zA-Z0-9_]+:Date>(\d{8})</[a-zA-Z0-9_]+:Date>", xml_text, re.S)
    if m_app:
        app_date = m_app.group(1)
    m_pub = re.search(r"<[a-zA-Z0-9_]+:PublicationReference[^>]*>.*?<[a-zA-Z0-9_]+:Date>(\d{8})</[a-zA-Z0-9_]+:Date>", xml_text, re.S)
    if m_pub:
        pub_date = m_pub.group(1)

    return {
        "id": pid,
        "title": title,
        "applicant": applicant,
        "application_number": app_num,
        "application_date": app_date,
        "public_date": pub_date,
        "ipc": ipc,
        "summary": summary,
        "inventor": inventor,
        "source": "cnipa_official",
        "crawled_at": datetime.now().isoformat(),
        "has_claims": False,
        "has_description": False,
    }


def main():
    parser = argparse.ArgumentParser(description="CNIPA 官方数据导入")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N条(0=全部)")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument("--extract-dir", default="output/cnipa_extract/outer",
                        help="外层zip解压目录")
    parser.add_argument("--skip-extract", action="store_true", help="跳过解压(已解压过)")
    args = parser.parse_args()

    extract_dir = Path(args.extract_dir)
    if not args.skip_extract:
        if not extract_outer_zip(extract_dir):
            return

    db = load_db()
    patents = db["patents"]
    existing_ids = set(patents.keys())
    print(f"数据库当前: {len(patents)} 篇")

    # 找所有内层 zip
    inner_zips = sorted(extract_dir.rglob("*.ZIP"))
    if not inner_zips:
        inner_zips = sorted(extract_dir.rglob("*.zip"))
    print(f"内层数据包: {len(inner_zips)} 个")

    total_new = 0
    total_parsed = 0
    total_errors = 0
    ipc_filled = 0

    for iz in inner_zips:
        print(f"\n处理: {iz.name}")
        try:
            z = zipfile.ZipFile(str(iz))
        except zipfile.BadZipFile as e:
            print(f"  [跳过] 无法读取: {e}")
            continue
        xml_names = [n for n in z.namelist() if n.endswith(".XML")]
        print(f"  条目: {len(xml_names)} XML")
        for i, name in enumerate(xml_names, 1):
            try:
                xml_text = z.read(name).decode("utf-8", errors="replace")
                entry = parse_detail_xml(xml_text)
                total_parsed += 1
                if entry is None:
                    total_errors += 1
                    continue
                pid = entry["id"]
                if pid in existing_ids:
                    # 已存在：补 IPC 字段（如果缺）
                    if not patents[pid].get("ipc") and entry.get("ipc"):
                        patents[pid]["ipc"] = entry["ipc"]
                        ipc_filled += 1
                    continue
                if not args.dry_run:
                    patents[pid] = entry
                total_new += 1
                if total_new <= 5 or total_new % 500 == 0:
                    print(f"  [{total_new}] {pid} | {entry['title'][:30]} | IPC: {entry['ipc'][:30]}")
            except Exception as e:
                total_errors += 1
                if total_errors <= 3:
                    print(f"  [错误] {name}: {e}")
            if args.limit and total_new >= args.limit:
                break
        z.close()
        if args.limit and total_new >= args.limit:
            break
        if not args.dry_run and total_new:
            save_db(db)
            print(f"  (已保存, 新增累计 {total_new})")

    if not args.dry_run:
        save_db(db)

    print("\n" + "=" * 50)
    print(f"完成:")
    print(f"  解析: {total_parsed} 条")
    print(f"  新增: {total_new} 篇")
    print(f"  IPC补填: {ipc_filled} 篇")
    print(f"  解析失败: {total_errors} 条")
    print(f"  数据库总量: {len(patents)} 篇")
    if args.dry_run:
        print("(dry-run 未写库)")


if __name__ == "__main__":
    main()
