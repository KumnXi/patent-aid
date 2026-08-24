<div align="center">

# PatentAid — AI Patent Disclosure Writer

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square)]()
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)]()
[![Patents](https://img.shields.io/badge/Patents-9%2C800%2B-blue?style=flat-square)]()
[![Tests](https://img.shields.io/badge/Tests-31-blue?style=flat-square)]()

**Turn your technical idea into a submission-ready patent disclosure (Word), in 3 minutes.**

Built-in anti-hallucination checks and claim-format validation — the AI won't invent data
your examiner will reject.

> No patent expertise required. Describe your idea in plain language (or drop in a sketch),
> and PatentAid drafts a complete, standard-format disclosure you can edit and submit.

</div>

---

## Why PatentAid

Writing a patent disclosure is a high-barrier task: it demands knowledge of legal formats,
claim drafting rules, and "sufficient disclosure" requirements that most engineers and
researchers never had to learn. Generic LLMs make it worse — left to their own devices they
**invent experimental results, citation numbers, and quantitative claims** that an examiner
will reject on sight.

PatentAid solves both problems:

1. **It knows the format.** The full standard disclosure template — title, abstract,
   claims, background, solution, effects, embodiments — is built in.
2. **It refuses to fabricate.** Anti-hallucination passes strip out made-up experiments and
   patent numbers, downgrade unverifiable quantities to qualitative statements, and a
   no-new-matter check keeps the claims faithful to your original idea.

## Demo

> Screenshots pending — these images will be added soon.

| | |
|---|---|
| [docs/images/demo/quickstart.png](docs/images/demo/quickstart.png) | **Generation pipeline** — idea → outline → sections → quality iteration, with live progress in the web UI. |
| [docs/images/demo/anti-hallucination.png](docs/images/demo/anti-hallucination.png) | **Anti-hallucination before/after** — the fix report showing fabricated data removed and quantitative claims made qualitative. |
| [docs/images/demo/word-output.png](docs/images/demo/word-output.png) | **Word output** — a generated `.docx` with native editable formulas and patent-style figures. |

## Quick Start

Three steps, no patent knowledge needed:

```bash
# 1. Install
git clone <your-repo-url> && cd patent-aid
pip install -r requirements.txt

# 2. Configure your AI key (one time)
cp config/api_config.example.json config/api_config.json
# edit config/api_config.json and set "api_key": "sk-..." (get one at https://platform.deepseek.com)

# 3. Generate your first disclosure
python scripts/generate_patent.py "A deep-learning-based method for defect detection in underground pipelines" --out output/disclosure.docx
```

Wait 1–3 minutes and you'll have `output/disclosure.docx` — a complete disclosure in
standard patent format. The first run initializes the patent database (~1 min).

> **Zero-command option:** Windows users can double-click `启动专利撰写助手.bat` to install
> dependencies, start the server, and open the web UI automatically.

## How It Works

| Stage | What happens | Why |
|---|---|---|
| ① **Three-stage generation** | Outline planning → section-by-section writing → quality iteration (LLM-staged) | Full-length, coherent 10-section disclosure, not a stub |
| ② **Anti-hallucination** | Removes experiment claims, rewrites quantities as qualitative, deletes fabricated patent numbers | The AI won't invent data your examiner will reject |
| ③ **Validation** | 9-dimension quality review (rewrites sections scoring <70), 6 claim-format checks, compliance review | Format-compliant and faithful to your idea |

The quality review scores structure, length, numbering, technical depth, claims,
implementation detail, relevance, novelty, and support for the original idea. Weak sections
are automatically rewritten once. Everything is rule-based — no extra LLM calls.

## Features

| Feature | Description |
|---|---|
| 🚀 **One-command pipeline** | Idea → standard patent-format Word, fully automatic |
| 📝 **Standard patent format** | Title → abstract → claims → background → solution → effects → embodiments |
| 🧮 **Native editable formulas** | LaTeX → Word OMML (no MathType / plugins required) |
| 🖼️ **Auto figures** | Mermaid → Graphviz layout (300 dpi) → patent-style block diagrams |
| 👁️ **Sketch input** | Paste a hand-drawn sketch / system diagram / screenshot — the vision model extracts technical fields |
| 🛡️ **Anti-hallucination** | Auto-fixes invented data, patent numbers, and experimental conclusions |
| ⚖️ **Claim-format validation** | Numbering, completeness, referencing, feature clauses, existence, order |
| 🔎 **Patent-aware RAG** | Hybrid retrieval (TF-IDF + bge-m3 dense) over a 9,800+ patent database, plus a knowledge graph |

## Examples

> These are illustrative use cases, not the product's only fit. PatentAid is domain-agnostic —
> if you can describe the problem and the method, it can draft the disclosure.

**Example 1 — Underground pipeline inspection robot**

*Idea:* "A multi-sensor fusion robot system for detecting defects in underground pipelines."

Generates a full disclosure including: a claims set covering the sensor-fusion architecture,
a novel localizer for GPS-denied pipe segments, and an embodiment with concrete parameters —
with the anti-hallucination pass ensuring the parameters stay qualitative.

**Example 2 — Self-healing control for distribution networks**

*Idea:* "A self-healing control method for distribution-network faults."

Generates a disclosure with background on existing fault-isolation approaches, a stepped
fault-location → islanding → reconfiguration solution, and claims that stay grounded in the
method you described (no invented field measurements).

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Input: idea text / sketch / system diagram                  │
├──────────────────────────────────────────────────────────────┤
│  Capability layer: three-stage generation · quality review   │
│  anti-hallucination · claim validation · compliance review   │
│  vision input (qwen-vl) · innovation suggestions             │
├──────────────────────────────────────────────────────────────┤
│  Engine:  PatentInnovationEngine  (single entry point)       │
│  hybrid retrieval · knowledge graph · innovation mining      │
├──────────────────────────────────────────────────────────────┤
│  Data layer: 9,800+ patents (944 full-text) · CORE papers    │
│  RAG index · knowledge graph · terminology / law templates   │
├──────────────────────────────────────────────────────────────┤
│  Output: standard Word (.docx) · encrypted history · Web app │
└──────────────────────────────────────────────────────────────┘
```

**Data layer:** a self-built patent database of **9,812 indexed patents** (944 with full
claim & description text — verified from `data/patent_database/index.json.gz`), augmented by
CORE academic papers and a RAG index / knowledge graph.

Everything is behind a single entry point:

```python
from src.core import PatentInnovationEngine
engine = PatentInnovationEngine()
engine.initialize()
result = engine.generate_disclosure("Your technical idea")
```

See [docs/architecture.md](docs/architecture.md) for design decisions and
[docs/modules.md](docs/modules.md) for module reference.

## Entry Points

**CLI**

```bash
# Generate a disclosure (core entry point)
python scripts/generate_patent.py "Your technical idea" \
    --title "A ... method/system" --tech-field "field" \
    --out output/disclosure.docx

# Optional delivery self-check: render the .docx to images and let the AI review layout
python scripts/selfcheck_disclosure.py output/disclosure.docx

# Run the automated test suite (31 tests, real LLM calls, ~10-15 min)
python scripts/run_tests.py
```

**Python API**

```python
from src.core import PatentInnovationEngine

engine = PatentInnovationEngine()
engine.initialize()

# Three-stage generation + quality iteration + anti-hallucination + validation
result = engine.generate_disclosure(
    "A self-healing control method for distribution-network faults",
    fields={"tech_field": "power systems", "purpose": "...", "core_method": "..."}
)
print(result["disclosure"])          # full disclosure text
print(result["quality_report"])      # 9-dimension quality report
print(result["compliance_report"])   # compliance review report

engine.query("pipeline defect detection")     # hybrid search (patents + papers)
engine.suggest_innovation("your idea")         # innovation direction suggestions
```

**Web app**

```bash
python app.py    # then open http://localhost:5000
```

A Flask single-page UI with generation, search, review, history, and export. No proxy
required for local functionality.

**Agent integration**

Six built-in Claude Code Skills — `/idea-to-disclosure`, `/patent-writer`,
`/compliance-checker`, `/patent-supervisor`, `/patent-orchestrator`, `/patent-fetcher` —
cover the full idea → disclosure workflow. Works with **Claude Code / Cursor / any coding
agent**.

## FAQ

**Do I need to know patent formats?**
No. The standard template is built in — just describe your technical idea.

**How long does one disclosure take?**
~1 minute first-time initialization, then 1–3 minutes per disclosure.

**Will the AI make up data?**
The built-in anti-hallucination pass removes fabricated experiments, patent numbers, and
quantitative claims. That said, always review key facts before submitting — no tool replaces
a human check.

**How do I get a DeepSeek API key?**
Register at [platform.deepseek.com](https://platform.deepseek.com) → API Keys → create a
`sk-` key.

**What is LibreOffice for?**
Only for the optional delivery self-check (`--selfcheck`), which renders the Word file to
images for an AI layout review. Skip it if LibreOffice isn't installed — generation is
unaffected.

## License

Released under the [MIT License](LICENSE).

**Built with:** DeepSeek (LLM engine) · DashScope qwen-vl (vision) · CORE (paper search) ·
scikit-learn + bge-m3 (RAG) · NetworkX (knowledge graph) · Graphviz (figures) · Flask (web).
