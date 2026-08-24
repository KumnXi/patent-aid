# Repository Metadata Checklist

> This is a **manual checklist** for the repo owner. The items below are set in the GitHub
> web UI (Settings → About) — they cannot be committed via code. Copy-paste-ready text is
> provided for each.

---

## 1. GitHub Topics

**Where:** GitHub repo page → right sidebar → **Settings → About → Topics** → paste & save.

Paste the following (space- or comma-separated, all lowercase):

```
ai, patent, patent-writing, legaltech, python, document-generation, anti-hallucination, rag, claude-code, word-document
```

| Topic | Why it fits |
|---|---|
| `ai` | LLM-driven generation |
| `patent` | Core domain |
| `patent-writing` | Primary use case |
| `legaltech` | Legal-domain tool |
| `python` | Implementation language |
| `document-generation` | Word disclosure output |
| `anti-hallucination` | Key differentiator |
| `rag` | Patent-aware retrieval |
| `claude-code` | Agent integration (Claude Code skills) |
| `word-document` | `.docx` output format |

---

## 2. Repository Description

**Where:** GitHub repo page → right sidebar → **Settings → About → Description** → paste & save.

```
AI patent disclosure writer: turn a technical idea into a submission-ready Word disclosure with anti-hallucination checks. Any domain.
```

---

## 3. README Badges

Already added (committed) to `README.md`, directly below the title inside the centered
header block:

```markdown
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square)]()
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)]()
[![Patents](https://img.shields.io/badge/Patents-9%2C800%2B-blue?style=flat-square)]()
[![Tests](https://img.shields.io/badge/Tests-31-blue?style=flat-square)]()
```

| Badge | Value | Source |
|---|---|---|
| Python | 3.10+ | `requirements.txt` |
| License | MIT | `LICENSE` |
| Patents | 9,800+ | 9,812 indexed patents (`data/patent_database/index.json.gz`) |
| Tests | 31 | `python scripts/run_tests.py` (31 tests) |

All badges are static shields.io badges (`style=flat-square`) — no external service
dependency, they render immediately.

---

## 4. Optional (nice-to-have)

- **Website:** point to the demo/landing page if one is hosted later.
- **Releases:** tag the first release once the quick-start flow is validated end-to-end.
