"""批量质量测试脚本

自动测试10个不同领域的交底书生成质量，输出评分报告。
用法: D:/Anaconda3/envs/mathmodel/python.exe scripts/batch_quality_test.py
"""

import sys
import json
import re
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════
# 10 个测试题目（覆盖多领域）
# ═══════════════════════════════════════════════════════════

TEST_TOPICS = [
    {
        "name": "管道检测机器人",
        "idea": "一种基于多传感器融合与深度学习的城市排水管道智能检测机器人系统，采用履带式自适应行走机构，搭载高清摄像头、激光雷达和超声波传感器，通过改进的YOLOv8算法实时识别管道内壁缺陷。",
        "tech_field": "管道检测与智能机器人",
        "purpose": "解决人工检测效率低、漏检率高的问题",
        "core_method": "多传感器融合+改进YOLOv8+SLAM定位+边缘计算",
        "problems": "现有检测方式效率低，智能化程度不足，对复杂环境适应性有限",
    },
    {
        "name": "虚拟电厂调度",
        "idea": "一种基于深度强化学习的虚拟电厂多时间尺度协调调度方法，通过构建日前-日内-实时三层调度架构，结合多智能体强化学习算法，实现分布式资源的优化配置和实时响应。",
        "tech_field": "电力系统调度与优化",
        "purpose": "解决分布式能源接入后电网调度复杂度高、响应慢的问题",
        "core_method": "深度强化学习+多时间尺度协调+多智能体协同",
        "problems": "传统调度方法难以应对高比例新能源接入带来的不确定性",
    },
    {
        "name": "光伏功率预测",
        "idea": "一种基于时空图神经网络的光伏电站功率预测方法，通过构建光伏电站间的空间拓扑图和时间依赖关系，融合气象数据实现多时间尺度精准预测。",
        "tech_field": "新能源发电与并网",
        "purpose": "提高光伏电站功率预测精度，降低弃光率",
        "core_method": "时空图神经网络+气象数据融合+多时间尺度预测",
        "problems": "现有预测方法对空间相关性利用不足，云层遮挡导致预测偏差大",
    },
    {
        "name": "配电网故障定位",
        "idea": "一种基于边缘计算和深度学习的配电网故障精准定位方法，利用卷积神经网络分析故障暂态信号特征，实现毫秒级故障区段定位。",
        "tech_field": "电力系统运行与控制",
        "purpose": "实现配电网故障的快速精准定位，缩短停电时间",
        "core_method": "边缘计算+CNN暂态信号分析+故障区段定位",
        "problems": "传统故障定位依赖人工巡线，耗时长、精度低",
    },
    {
        "name": "自动驾驶路径规划",
        "idea": "一种基于强化学习与语义地图融合的城市自动驾驶动态路径规划方法，结合实时交通流预测和行人意图识别，实现安全高效的自主导航。",
        "tech_field": "人工智能与自动驾驶",
        "purpose": "解决城市复杂交通环境下自动驾驶路径规划的安全性和效率问题",
        "core_method": "深度强化学习+语义SLAM+交通流预测+行人意图识别",
        "problems": "现有路径规划对动态障碍物响应慢，复杂路口决策能力不足",
    },
    {
        "name": "工业焊接质量检测",
        "idea": "一种基于红外热成像与卷积神经网络的工业焊接质量在线检测方法，通过采集焊接过程中的红外热图像序列，利用改进的ResNet模型实时识别气孔、裂纹、未熔合等焊接缺陷。",
        "tech_field": "无损检测与缺陷识别",
        "purpose": "实现焊接质量的在线实时检测，替代传统离线X射线检测",
        "core_method": "红外热成像+改进ResNet+时序特征融合+在线检测",
        "problems": "传统焊接质量检测依赖离线检测，效率低且无法实时反馈",
    },
    {
        "name": "智慧农业灌溉",
        "idea": "一种基于物联网传感器网络与深度强化学习的精准灌溉控制系统，通过土壤湿度、气象数据和作物生长模型的多源融合，实现按需精准灌溉和水量优化分配。",
        "tech_field": "智慧农业与物联网",
        "purpose": "解决传统灌溉水资源浪费大、作物产量不稳定的问题",
        "core_method": "IoT传感器网络+深度强化学习+作物生长模型+多源数据融合",
        "problems": "传统灌溉依赖经验，水资源利用率低，无法精准匹配作物需水规律",
    },
    {
        "name": "医学影像辅助诊断",
        "idea": "一种基于Transformer与多尺度特征融合的肺部CT影像辅助诊断方法，通过自注意力机制捕获全局上下文信息，结合多尺度特征金字塔实现肺结节的精准检测和良恶性分类。",
        "tech_field": "医学人工智能",
        "purpose": "提高肺部CT影像中微小结节的检出率和诊断准确率",
        "core_method": "Vision Transformer+多尺度特征金字塔+自注意力机制",
        "problems": "现有CAD系统对微小结节漏检率高，良恶性鉴别能力不足",
    },
    {
        "name": "区块链供应链溯源",
        "idea": "一种基于联盟链与零知识证明的供应链全流程溯源系统，通过智能合约自动记录物流节点数据，结合零知识证明实现隐私保护下的真伪验证和来源追溯。",
        "tech_field": "信息安全与区块链",
        "purpose": "解决供应链数据易篡改、隐私泄露和溯源可信度低的问题",
        "core_method": "联盟链+零知识证明+智能合约+分布式存储",
        "problems": "传统供应链溯源中心化存储易篡改，数据隐私保护不足",
    },
    {
        "name": "风机叶片损伤检测",
        "idea": "一种基于无人机巡检与深度学习的海上风力发电机叶片损伤智能检测方法，采用改进的U-Net语义分割网络对叶片表面裂纹、腐蚀、雷击损伤进行像素级识别和损伤等级评估。",
        "tech_field": "新能源装备与智能检测",
        "purpose": "解决海上风机叶片人工巡检风险高、效率低、损伤量化评估困难的问题",
        "core_method": "无人机巡检+改进U-Net语义分割+损伤等级评估+数字孪生",
        "problems": "海上风机巡检依赖人工高空作业，风险大且难以量化损伤程度",
    },
]


# ═══════════════════════════════════════════════════════════
# 测试执行
# ═══════════════════════════════════════════════════════════

def _extract_title(disclosure: str) -> str:
    """从交底书全文提取发明名称（兼容分阶段/模板/单次格式）"""
    for pattern in [r"## 一、发明名称\s*\n+\s*(.+?)\s*\n",
                    r"【发明名称】\s*\n+\s*(.+?)\s*\n"]:
        m = re.search(pattern, disclosure)
        if m:
            return m.group(1).strip()
    return ""


def run_single_topic(engine, topic: dict) -> dict:
    """执行单个题目的生成+质量审查

    Args:
        engine: PatentInnovationEngine 实例
        topic: 题目字典 {name, idea, tech_field, purpose, core_method, problems}

    Returns:
        {"name", "mode", "word_count", "elapsed", "quality", "history_id"}
    """
    fields = {
        "tech_field": topic.get("tech_field", ""),
        "purpose": topic.get("purpose", ""),
        "core_method": topic.get("core_method", ""),
        "problems": topic.get("problems", ""),
    }

    t0 = time.time()
    result = engine.generate_disclosure(topic["idea"], fields=fields)
    elapsed = round(time.time() - t0, 1)

    disclosure = result["disclosure"]
    mode = result["mode"]
    word_count = len(disclosure.replace(" ", "").replace("\n", ""))

    # 质量审查
    quality = engine.review_quality(disclosure, topic["idea"])

    # 保存全文到生成历史（与 web 端一致，避免生成成果丢失）
    title = _extract_title(disclosure) or topic["name"]
    try:
        from src.utils.history import save_disclosure
        history_id = save_disclosure(
            topic["idea"], disclosure, mode, title=title,
            quality_report=quality,
        )
    except Exception as e:
        print(f"[历史保存] 失败: {e}")
        history_id = None

    return {
        "name": topic["name"],
        "mode": mode,
        "word_count": word_count,
        "elapsed": elapsed,
        "quality": quality,
        "history_id": history_id,
    }


def run_batch_test():
    """运行完整批量测试"""
    print("=" * 60)
    print("  交底书生成质量批量测试")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  题目数: {len(TEST_TOPICS)}")
    print("=" * 60)

    # 初始化引擎
    print("\n初始化引擎...")
    t0 = time.time()
    from src.core import PatentInnovationEngine
    engine = PatentInnovationEngine()
    engine.initialize()
    print(f"引擎就绪 ({time.time() - t0:.1f}s)\n")

    # 逐题测试
    results = []
    for i, topic in enumerate(TEST_TOPICS, 1):
        print(f"[{i}/{len(TEST_TOPICS)}] {topic['name']}...", end=" ", flush=True)
        result = run_single_topic(engine, topic)
        results.append(result)
        score = result["quality"]["total_score"]
        grade = result["quality"]["grade"]
        hid = result.get("history_id") or "-"
        print(f"{result['mode']} | {result['word_count']}字 | "
              f"{result['elapsed']}s | 评分:{score} ({grade}) | 历史:{hid}")

    # 汇总
    scores = [r["quality"]["total_score"] for r in results]
    print(f"\n{'=' * 60}")
    print(f"  平均分: {sum(scores)/len(scores):.1f}")
    print(f"  最高分: {max(scores):.1f} ({results[scores.index(max(scores))]['name']})")
    print(f"  最低分: {min(scores):.1f} ({results[scores.index(min(scores))]['name']})")
    print(f"{'=' * 60}")

    # 各维度平均
    dim_keys = ["structure", "length", "numbering", "technical_depth",
                "claims", "implementation", "relevance", "novelty"]
    print("\n各维度平均分:")
    for key in dim_keys:
        dim_scores = [r["quality"]["dimensions"][key]["score"] for r in results]
        avg = sum(dim_scores) / len(dim_scores)
        print(f"  {key:20s}: {avg:.1f}")

    # 保存报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_topics": len(results),
            "avg_score": round(sum(scores) / len(scores), 1),
            "min_score": min(scores),
            "max_score": max(scores),
        },
        "results": results,
    }
    out_dir = PROJECT_ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"quality_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {out_file}")

    return report


if __name__ == "__main__":
    run_batch_test()
