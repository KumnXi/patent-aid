"""专利撰写助手 Web 应用

功能：
1. 输入技术想法 → 自动生成专利技术交底书
2. 专利数据库搜索（关键词/IPC/申请人）
3. 专利详情查看（权利要求+说明书）
4. 按IPC分类/申请人浏览

启动: python app.py
访问: http://localhost:5000
"""

import sys
import json
import traceback
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, render_template, request, jsonify, send_file, Response

app = Flask(__name__)

# PDF文件目录
PDF_DIR = PROJECT_ROOT / "data" / "patent_pdfs"

from src.core.database_loader import ipc_to_list


def _ipc_str(raw) -> str:
    """IPC 字段转分号分隔字符串（兼容 list/str）"""
    return ";".join(ipc_to_list(raw))

# ═══════════════════════════════════════════════════════════
# 全局状态
# ═══════════════════════════════════════════════════════════

_engine = None
_engine_status = "未初始化"
_patent_db = None  # 专利数据库缓存


def get_engine():
    """获取或初始化分析引擎"""
    global _engine, _engine_status
    if _engine is not None and _engine.is_initialized:
        return _engine
    try:
        _engine_status = "正在初始化..."
        from src.core import PatentInnovationEngine
        _engine = PatentInnovationEngine(
            db_path=str(PROJECT_ROOT / "data" / "patent_database"),
            config_dir=str(PROJECT_ROOT / "config")
        )
        _engine.initialize()
        _engine_status = "就绪"
        return _engine
    except Exception as e:
        _engine_status = f"初始化失败: {e}"
        traceback.print_exc()
        return None


def get_patent_db():
    """加载专利数据库（带缓存）"""
    global _patent_db
    if _patent_db is not None:
        return _patent_db
    
    db_path = PROJECT_ROOT / "data" / "patent_database" / "index.json"
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    _patent_db = {
        "patents": data.get("patents", {}),
        "metadata": data.get("metadata", {}),
    }
    return _patent_db


# ═══════════════════════════════════════════════════════════
# 页面路由
# ═══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ═══════════════════════════════════════════════════════════
# 交底书生成 API
# ═══════════════════════════════════════════════════════════

@app.route("/api/status")
def api_status():
    """引擎状态"""
    db = get_patent_db()
    total = len(db["patents"])
    
    engine = get_engine()
    if engine and engine.is_initialized:
        stats = engine.get_statistics()
        return jsonify({
            "status": "ready",
            "summary": engine.get_summary(),
            "stats": {
                "patents": total,
                "kg_nodes": stats.get("knowledge_graph", {}).get("total_nodes", 0),
                "kg_edges": stats.get("knowledge_graph", {}).get("total_edges", 0),
                "rag_chunks": stats.get("rag_index", {}).get("total_chunks", 0),
            }
        })
    return jsonify({"status": "loading", "message": _engine_status, "stats": {"patents": total}})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """生成技术交底书"""
    data = request.get_json()
    idea = data.get("idea", "").strip()
    title = data.get("title", "").strip() or None
    fields = {
        "tech_field": data.get("tech_field", "").strip(),
        "purpose": data.get("purpose", "").strip(),
        "core_method": data.get("core_method", "").strip(),
        "problems": data.get("problems", "").strip(),
    }

    if not idea or len(idea) < 10:
        return jsonify({"error": "技术想法描述太短，请至少输入10个字"}), 400

    engine = get_engine()
    if not engine:
        return jsonify({"error": f"引擎初始化失败: {_engine_status}"}), 500

    try:
        start_time = datetime.now()
        result = engine.generate_disclosure(idea, title=title, fields=fields)
        elapsed = (datetime.now() - start_time).total_seconds()

        disclosure = result["disclosure"]
        mode = result["mode"]
        quality_report = result.get("quality_report")
        word_count = len(disclosure.replace(" ", "").replace("\n", ""))

        # 保存生成历史
        from src.utils.history import save_disclosure
        try:
            history_id = save_disclosure(
                idea, disclosure, mode, title=title,
                quality_report=quality_report
            )
        except Exception as e:
            print(f"[历史保存] 失败: {e}")
            history_id = None

        resp = {
            "success": True,
            "disclosure": disclosure,
            "mode": mode,
            "history_id": history_id,
            "stats": {
                "word_count": word_count,
                "section_count": disclosure.count("## "),
                "elapsed_seconds": round(elapsed, 1),
            }
        }
        if quality_report:
            resp["quality_report"] = {
                "total_score": quality_report.get("total_score"),
                "grade": quality_report.get("grade"),
                "dimensions": quality_report.get("dimensions"),
            }
        return jsonify(resp)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


@app.route("/api/download", methods=["POST"])
def api_download():
    """下载交底书"""
    data = request.get_json()
    disclosure = data.get("disclosure", "")
    title = data.get("title", "技术交底书")
    
    if not disclosure:
        return jsonify({"error": "无内容可下载"}), 400
    
    safe_title = "".join(c for c in title if c.isalnum() or c in "._- ")[:50]
    filename = f"{safe_title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    
    out_path = PROJECT_ROOT / "output" / filename
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(disclosure, encoding="utf-8")
    
    return send_file(str(out_path), as_attachment=True, download_name=filename)


# ═══════════════════════════════════════════════════════════
# 生成历史 API
# ═══════════════════════════════════════════════════════════

@app.route("/api/history")
def api_history():
    """生成历史列表"""
    from src.utils.history import list_history
    try:
        limit = min(100, max(1, int(request.args.get("limit", 50))))
    except ValueError:
        limit = 50
    return jsonify({"success": True, "records": list_history(limit)})


@app.route("/api/history/<record_id>")
def api_history_detail(record_id):
    """生成历史详情（含全文）"""
    from src.utils.history import get_history
    record = get_history(record_id)
    if not record:
        return jsonify({"error": "记录不存在"}), 404
    return jsonify({"success": True, "record": record})


@app.route("/api/history/<record_id>", methods=["DELETE"])
def api_history_delete(record_id):
    """删除一条生成历史"""
    from src.utils.history import delete_history
    if delete_history(record_id):
        return jsonify({"success": True})
    return jsonify({"error": "记录不存在"}), 404


@app.route("/api/quality-review", methods=["POST"])
def api_quality_review():
    """质量审查"""
    data = request.get_json()
    disclosure = data.get("disclosure", "").strip()
    idea = data.get("idea", "").strip()

    if not disclosure:
        return jsonify({"error": "缺少交底书内容"}), 400
    if not idea:
        idea = disclosure[:100]

    engine = get_engine()
    if not engine:
        return jsonify({"error": f"引擎初始化失败: {_engine_status}"}), 500

    try:
        report = engine.review_quality(disclosure, idea)
        return jsonify({"success": True, "report": report})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"质量审查失败: {str(e)}"}), 500


@app.route("/api/batch-test", methods=["POST"])
def api_batch_test():
    """批量测试（10题多领域）"""
    from scripts.batch_quality_test import TEST_TOPICS, run_single_topic

    engine = get_engine()
    if not engine:
        return jsonify({"error": f"引擎初始化失败: {_engine_status}"}), 500

    data = request.get_json() or {}
    topics = data.get("topics", TEST_TOPICS)

    try:
        results = []
        for i, topic in enumerate(topics):
            result = run_single_topic(engine, topic)
            result["index"] = i + 1
            results.append(result)

        scores = [r["quality"]["total_score"] for r in results if r.get("quality")]
        summary = {
            "total_topics": len(results),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
        }
        return jsonify({"success": True, "results": results, "summary": summary})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"批量测试失败: {str(e)}"}), 500


# ═══════════════════════════════════════════════════════════
# 专利搜索 API
# ═══════════════════════════════════════════════════════════

@app.route("/api/search")
def api_search():
    """搜索专利
    
    参数:
        q: 关键词（匹配标题、申请人、IPC）
        ipc: IPC分类号前缀过滤
        applicant: 申请人关键词
        page: 页码（从1开始）
        size: 每页数量（默认20）
    """
    q = request.args.get("q", "").strip().lower()
    ipc_filter = request.args.get("ipc", "").strip()
    applicant_filter = request.args.get("applicant", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = min(50, max(1, int(request.args.get("size", 20))))
    except ValueError:
        return jsonify({"error": "page/size 必须为整数"}), 400
    
    db = get_patent_db()
    patents = db["patents"]
    
    results = []
    for pid, p in patents.items():
        # IPC过滤
        if ipc_filter:
            codes = ipc_to_list(p.get("ipc", ""))
            if not any(c.upper().startswith(ipc_filter.upper()) for c in codes):
                continue
        
        # 申请人过滤
        if applicant_filter:
            p_app = (p.get("applicant", "") or "").lower()
            if applicant_filter.lower() not in p_app:
                continue
        
        # 关键词搜索
        if q:
            title = (p.get("title", "") or "").lower()
            applicant = (p.get("applicant", "") or "").lower()
            ipc = _ipc_str(p.get("ipc", "")).lower()
            claims_preview = (p.get("claims", "") or "")[:500].lower()
            
            # 计算相关度分数
            score = 0
            if q in title:
                score += 10
            if q in ipc:
                score += 5
            if q in applicant:
                score += 3
            if q in claims_preview:
                score += 2
            
            if score == 0:
                continue
            
            results.append((score, pid, p))
        else:
            results.append((0, pid, p))
    
    # 按相关度降序，同分按申请日期降序
    def sort_key(item):
        score = item[0]
        date_str = item[2].get("application_date", "") or ""
        try:
            date_val = -int(date_str.replace("-", "")) if date_str else 0
        except ValueError:
            date_val = 0
        return (-score, date_val)
    results.sort(key=sort_key)
    
    total = len(results)
    start = (page - 1) * size
    end = start + size
    page_results = results[start:end]
    
    # 构建返回数据（列表页只返回摘要）
    items = []
    for score, pid, p in page_results:
        items.append({
            "id": pid,
            "title": p.get("title", ""),
            "applicant": p.get("applicant", ""),
            "application_date": p.get("application_date", ""),
            "ipc": _ipc_str(p.get("ipc", "")),
            "legal_status": p.get("legal_status", ""),
            "has_claims": p.get("has_claims", False),
            "has_description": p.get("has_description", False),
            "has_pdf": _has_pdf(pid),
        })
    
    return jsonify({
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
        "results": items,
    })


def _clean_text(text):
    """清理专利文本中的乱码字符"""
    if not text:
        return ""
    # 移除Unicode替换字符和空字符
    text = text.replace('\ufffd', '').replace('\x00', '')
    # 移除其他不可见控制字符（保留换行和制表符）
    text = ''.join(c for c in text if c >= ' ' or c in '\n\r\t')
    return text


def _has_pdf(patent_id):
    """检查专利是否有PDF文件"""
    return (PDF_DIR / f"{patent_id}.pdf").exists()


@app.route("/api/patent/<patent_id>")
def api_patent_detail(patent_id):
    """获取专利详情"""
    db = get_patent_db()
    p = db["patents"].get(patent_id)
    
    if not p:
        return jsonify({"error": f"未找到专利 {patent_id}"}), 404
    
    return jsonify({
        "id": p.get("id", patent_id),
        "title": p.get("title", ""),
        "applicant": p.get("applicant", ""),
        "application_date": p.get("application_date", ""),
        "ipc": _ipc_str(p.get("ipc", "")),
        "legal_status": p.get("legal_status", ""),
        "claims": _clean_text(p.get("claims", "")),
        "description": _clean_text(p.get("description", "")),
        "has_claims": p.get("has_claims", False),
        "has_description": p.get("has_description", False),
        "has_pdf": _has_pdf(patent_id),
        "crawled_at": p.get("crawled_at", ""),
    })


@app.route("/api/patent/<patent_id>/pdf")
def api_patent_pdf(patent_id):
    """提供专利PDF文件（供PDF.js渲染）"""
    pdf_path = PDF_DIR / f"{patent_id}.pdf"
    if not pdf_path.exists():
        return jsonify({"error": "该专利暂无PDF文件"}), 404
    return send_file(str(pdf_path), mimetype="application/pdf")


@app.route("/api/stats")
def api_db_stats():
    """数据库统计信息"""
    db = get_patent_db()
    patents = db["patents"]
    
    # IPC分布
    ipc_counter = {}
    applicant_counter = {}
    date_range = {"min": "9999", "max": "0000"}
    with_claims = 0
    with_desc = 0
    
    for p in patents.values():
        # IPC统计（取大类）
        codes = ipc_to_list(p.get("ipc", ""))
        if codes:
            ipc_class = codes[0][:4] if len(codes[0]) >= 4 else codes[0]
            ipc_counter[ipc_class] = ipc_counter.get(ipc_class, 0) + 1
        
        # 申请人统计
        app = p.get("applicant", "") or ""
        if app:
            # 取第一个申请人
            first_app = app.split(";")[0].strip()
            if first_app:
                applicant_counter[first_app] = applicant_counter.get(first_app, 0) + 1
        
        # 日期范围
        date = p.get("application_date", "") or ""
        if date:
            if date < date_range["min"]:
                date_range["min"] = date
            if date > date_range["max"]:
                date_range["max"] = date
        
        if p.get("has_claims"):
            with_claims += 1
        if p.get("has_description"):
            with_desc += 1
    
    # 排序取Top
    top_ipc = sorted(ipc_counter.items(), key=lambda x: -x[1])[:20]
    top_applicants = sorted(applicant_counter.items(), key=lambda x: -x[1])[:20]
    
    return jsonify({
        "total": len(patents),
        "with_claims": with_claims,
        "with_description": with_desc,
        "date_range": date_range,
        "ipc_distribution": [{"code": k, "count": v} for k, v in top_ipc],
        "top_applicants": [{"name": k, "count": v} for k, v in top_applicants],
    })


@app.route("/api/ipc_list")
def api_ipc_list():
    """获取所有IPC分类列表"""
    db = get_patent_db()
    ipc_counter = {}
    
    for p in db["patents"].values():
        ipc = p.get("ipc", "") or ""
        if ipc:
            ipc_class = ipc[:4] if len(ipc) >= 4 else ipc
            ipc_counter[ipc_class] = ipc_counter.get(ipc_class, 0) + 1
    
    result = sorted(ipc_counter.items(), key=lambda x: -x[1])
    return jsonify([{"code": k, "count": v} for k, v in result])


# ═══════════════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    print("  专利撰写助手 Web 应用")
    print("  访问: http://localhost:5000")
    print("=" * 50)
    
    # 预加载数据库（快速）
    db = get_patent_db()
    print(f"\n  数据库已加载: {len(db['patents'])} 篇专利")
    
    # 预加载引擎（较慢）
    print("  正在初始化分析引擎...\n")
    get_engine()
    
    print("\n  启动Web服务器...\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
