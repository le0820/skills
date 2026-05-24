# Data Output Naming Convention

> All files produced by the openclaw agent MUST follow these naming rules. Downstream consumers (state recovery, heartbeat, forward signal log) depend on consistent file names.

## Directory Structure

```
repo_skills/
├── data/                          # Raw input data (fetched by data layer)
│   ├── macro/                     # Macroeconomic data
│   │   └── raw_macro_{YYYYMMDD}.json
│   └── market/                    # Market/ETF data
│       └── raw_market_{YYYYMMDD}.json
│
├── output/                        # Agent output (this is new)
│   ├── scores/
│   │   ├── scores_L1_{YYYYMMDD}.json
│   │   ├── scores_L2_{YYYYMMDD}.json
│   │   ├── scores_L3_{YYYYMMDD}.json
│   │   └── scores_composite_{YYYYMMDD}.json
│   ├── alerts/
│   │   └── alert_{trigger_id}_{YYYYMMDDTHHmmss}.json
│   ├── state/
│   │   └── system_state.json      # Single file, overwritten on each update
│   └── summaries/
│       ├── summary_{type}_{YYYYMMDD}.json
│       └── README.md              # Summary index
│
├── analysis/                      # Full markdown reports (human reading)
│   └── {topic}_{YYYYMMDD}.md     # Existing convention, keep as-is
│
├── schemas/                       # JSON Schema definitions (Phase 1)
│   └── *.schema.json
│
└── sop/                           # SOP documents
    ├── compiled/                  # Machine-readable scoring rules (Phase 2)
    └── *.md                       # Full prose SOPs (deep reference)
```

## File Naming Rules

### Raw Data
- `raw_macro_{YYYYMMDD}.json` — daily macro snapshot
- `raw_market_{YYYYMMDD}.json` — daily market snapshot
- Timestamp represents the data's reference date (not fetch time)

### Scores
- `scores_L1_{YYYYMMDD}.json` — L1 macro scoring
- `scores_L2_{YYYYMMDD}.json` — L2 style factor scoring
- `scores_L3_{YYYYMMDD}.json` — L3 sentiment+risk scoring
- `scores_composite_{YYYYMMDD}.json` — composite + position
- All scores for the same date should use the same `YYYYMMDD`

### Alerts
- `alert_{trigger_id}_{YYYYMMDDTHHmmss}.json`
- `trigger_id` uses 2-digit zero-padded (01-20)
- Example: `alert_01_20260524T093000.json` (trigger 1 = 30Y UST, generated at 09:30)

### System State
- `system_state.json` — single file, always at `output/state/`
- Overwritten on each update. No versioning in filename.
- Previous state should be logged to `forward_signal_log` before overwrite.

### Analysis Summaries
- `summary_{type}_{YYYYMMDD}.json`
- `type` is a short identifier: `cnff`, `gold`, `crude`, `semi`, `macro`
- Example: `summary_macro_20260524.json`

### Full Reports (legacy, keep)
- `{Topic}_{YYYYMMDD}.md` — human-readable analysis reports
- Chinese topics use Chinese characters
- Example: `CoreWeave_Q1_2026_交叉验证.md`

## Conformance Requirement

Any JSON file in `output/` MUST validate against its corresponding `schemas/*.schema.json` before being consumed by downstream agents. Schema validation is the responsibility of the writing agent.

## Context Efficiency Note

When loading for context, prefer:
1. `system_state.json` (current state) — ~500 tokens
2. `sop/compiled/rules_*.json` (scoring rules) — ~1,500 tokens total
3. `output/summaries/summary_*.json` (past analysis) — ~300 tokens each
4. Full SOP markdown — only when rules are ambiguous
5. Full analysis reports — only when investigating a specific past decision

Total context for a typical scoring cycle: ~3,000 tokens (vs. ~30,000 currently).
