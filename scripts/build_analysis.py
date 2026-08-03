"""
一键构建专利分析系统

运行此脚本完成:
1. 解析所有完整专利文本
2. 构建知识图谱
3. 挖掘创新模式
4. 构建RAG索引
5. 生成分析报告

使用方式:
    D:/Anaconda3/envs/mathmodel/python.exe scripts/build_analysis.py
"""

import sys
import io
import json
from pathlib import Path
from datetime import datetime

# 强制行缓冲，解决终端卡住问题
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core import PatentInnovationEngine


def main():
    print("=" * 60)
    print("  专利创新学习系统 - 一键构建")
    print(f"  执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 初始化引擎（首次运行会构建所有分析结果）
    engine = PatentInnovationEngine()

    try:
        engine.initialize(force_rebuild=True)
    except Exception as e:
        print(f"\n初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 生成报告
    print("\n" + "=" * 60)
    print("  生成分析报告")
    print("=" * 60)

    output_dir = Path("output/analysis")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存创新报告
    innovation_report = engine.get_innovation_report()
    with open(output_dir / "innovation_report.md", "w", encoding="utf-8") as f:
        f.write(innovation_report)
    print(f"  创新报告: {output_dir / 'innovation_report.md'}")

    # 保存权利要求分析报告
    claim_report = engine.get_claim_analysis_report()
    with open(output_dir / "claim_analysis_report.md", "w", encoding="utf-8") as f:
        f.write(claim_report)
    print(f"  权利要求报告: {output_dir / 'claim_analysis_report.md'}")

    # 保存术语分析报告
    term_report = engine.get_terminology_report()
    with open(output_dir / "terminology_report.md", "w", encoding="utf-8") as f:
        f.write(term_report)
    print(f"  术语报告: {output_dir / 'terminology_report.md'}")

    # 保存引擎统计
    stats = engine.get_statistics()
    with open(output_dir / "engine_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"  引擎统计: {output_dir / 'engine_stats.json'}")

    # 测试查询
    print("\n" + "=" * 60)
    print("  功能测试")
    print("=" * 60)

    test_queries = [
        "电解槽调频的振荡抑制方法",
        "分布式光伏并网功率预测",
        "继电保护故障定位方法",
    ]

    for query in test_queries:
        print(f"\n查询: {query}")
        try:
            results = engine.query(query, top_k=2)
            if results.get("related_solutions"):
                print(f"  知识图谱匹配: {len(results['related_solutions'])}个方案")
            if results.get("related_patents"):
                print(f"  RAG检索: {len(results['related_patents'])}个相关专利")
        except Exception as e:
            print(f"  查询失败: {e}")

    print(f"\n构建完成! 引擎状态: {engine.get_summary()}")


if __name__ == "__main__":
    main()
