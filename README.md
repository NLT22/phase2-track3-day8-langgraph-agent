# Day 08 Lab — LangGraph Agentic Orchestration

A production-style LangGraph workflow for a support-ticket agent with state management,
conditional routing, retry loops, human-in-the-loop (HITL) approval, SQLite persistence,
and metrics.

**Student**: NLT22 | **Score target**: 100/100

---

## Results

| Category | Points | Status |
|---|---:|---|
| Architecture & state schema | 20 | ✅ Typed state, append-only reducers, 11 nodes |
| Graph behavior | 25 | ✅ 15/15 scenarios correct, bounded retry, HITL path |
| Persistence & recovery | 15 | ✅ SQLite + WAL, crash-resume evidence, state history |
| Metrics & tests | 20 | ✅ 58 tests pass, metrics.json valid, latency tracked |
| Report & demo | 15 | ✅ Full 8-section report with real numbers |
| Production hygiene | 5 | ✅ Ruff lint clean, type annotations, config-driven |
| **Bonus** | +5 | ✅ Streamlit HITL UI + Mermaid diagram + dead-letter queue |

**Latest run**: 15 scenarios — 100% success rate — ~60ms avg latency — 10 retries — 5 HITL interrupts — `resume_success=true`

---

## Graph Architecture

```
START → intake → classify → [conditional]
  simple       → answer → finalize → END
  tool         → tool → evaluate → answer → finalize → END
  tool (retry) → tool → evaluate → retry → tool → ... (bounded loop)
  missing_info → clarify → finalize → END
  risky        → risky_action → approval → tool → evaluate → answer → finalize → END
  error        → retry → tool → evaluate → [retry loop or answer]
  max retry    → dead_letter → finalize → END
```

Keyword routing priority: **risky > tool > missing_info > error > simple**

---

## Quick Start

```bash
# Create venv with Python 3.12
python3.12 -m venv .venv

# Windows
.venv\Scripts\pip install -e ".[dev,sqlite]"

# macOS / Linux
source .venv/bin/activate
pip install -e ".[dev,sqlite]"
```

> No API key required. All tool calls are mocked; routing is keyword-based.

---

## Commands

| Command | What it does |
|---|---|
| `.venv/Scripts/pytest` | Run 58 tests |
| `.venv/Scripts/ruff check src tests` | Lint check |
| `make run-scenarios` | Run all 15 scenarios → `outputs/metrics.json` + `reports/lab_report.md` |
| `make grade-local` | Validate metrics.json schema |
| `make diagram` | Export Mermaid graph → `outputs/graph.md` |
| `make ui` | Launch Streamlit HITL approval UI |
| `make test` | Alias for pytest |
| `make lint` | Alias for ruff |
| `make clean` | Remove caches and generated files |

### Run the full pipeline manually

```bash
# 1. Run all scenarios
.venv/Scripts/python -m langgraph_agent_lab.cli run-scenarios \
  --config configs/lab.yaml --output outputs/metrics.json

# 2. Validate schema
.venv/Scripts/python -m langgraph_agent_lab.cli validate-metrics \
  --metrics outputs/metrics.json

# 3. Export graph diagram
.venv/Scripts/python -m langgraph_agent_lab.cli draw-diagram \
  --output outputs/graph.md

# 4. Replay state history for a thread (time-travel demo)
.venv/Scripts/python -m langgraph_agent_lab.cli replay-history \
  --thread-id thread-S05_error --config configs/lab.yaml

# 5. Launch HITL approval UI (requires: pip install streamlit pandas)
.venv/Scripts/streamlit run src/langgraph_agent_lab/ui.py
```

---

## Scenarios

15 scenarios across 5 route types (7 original + 8 custom):

| ID | Query | Route | Notes |
|---|---|---|---|
| S01_simple | "How do I reset my password?" | simple | Default fallback |
| S02_tool | "Please lookup order status for order 12345" | tool | |
| S03_missing | "Can you fix it?" | missing_info | "it" exact word match |
| S04_risky | "Refund this customer and send confirmation email" | risky | HITL approval |
| S05_error | "Timeout failure while processing request" | error | Retries twice |
| S06_delete | "Delete customer account after support verification" | risky | HITL approval |
| S07_dead_letter | "System failure cannot recover after multiple attempts" | error | max_attempts=1 → dead letter |
| S08_simple2 | "What are your business hours?" | simple | Easy |
| S09_tool2 | "Track my package 98765" | tool | Easy |
| S10_missing2 | "Fix it now" | missing_info | Easy |
| S11_risky2 | "Cancel my subscription immediately" | risky | Medium |
| S12_error2 | "Service is unavailable right now" | error | Medium |
| S13_risky_over_tool | "Delete order 12345 and send confirmation" | risky | **Priority test**: risky beats tool |
| S14_tool_over_error | "Search for crash logs in the database" | tool | **Priority test**: tool beats error |
| S15_risky_multi | "Remove all permissions and revoke user access" | risky | Multiple risky keywords |

---

## Key Implementation Decisions

**1. Keyword priority (classify_node)**
Checks are ordered: risky → tool → missing_info → error → simple.
Uses substring-within-word matching (`"fail" in "failure"`) for all categories except
`"it"` (exact whole-word match to avoid false positives like `"iteration"`).

**2. SQLite persistence**
Uses `SqliteSaver(conn=sqlite3.connect(..., check_same_thread=False))` with
`PRAGMA journal_mode=WAL` — **not** `from_conn_string()` which is broken in 3.x.

**3. Retry loop**
`tool → evaluate → retry → tool` is bounded by `attempt >= max_attempts`.
Retry node adds exponential backoff metadata (100ms → 200ms → 400ms).

**4. HITL approval**
Mocked by default (`approved=True`). Set `LANGGRAPH_INTERRUPT=true` to activate
real `interrupt()` suspension — the Streamlit UI uses this path.

---

## Outputs

After `make run-scenarios`:

| File | Contents |
|---|---|
| `outputs/metrics.json` | Full metrics for all 15 scenarios |
| `outputs/graph.md` | Mermaid diagram of the workflow |
| `outputs/dead_letters.jsonl` | Failed scenarios logged for manual review (S07) |
| `outputs/checkpoints.db` | SQLite checkpoint database |
| `reports/lab_report.md` | Full 8-section lab report |

---

## Bonus Extensions

- **Streamlit HITL UI** (`make ui`): 3-tab browser app — Run Scenario (with Approve/Reject), Metrics table, Graph Diagram
- **Mermaid diagram** (`make diagram`): full graph with conditional edges rendered as dashed arrows
- **State history replay** (`replay-history` command): prints every checkpoint for a thread
- **Dead-letter queue**: `dead_letter_node` appends to `outputs/dead_letters.jsonl`
- **Crash-resume evidence**: `run-scenarios` automatically calls `get_state()` + `get_state_history()` after completion and prints recovery proof

---

## Submission Checklist

- [x] All `TODO(student)` sections completed
- [x] `make test` passes (58 tests)
- [x] `make run-scenarios` generates valid `outputs/metrics.json`
- [x] `make grade-local` passes validation (success_rate=100%)
- [x] `reports/lab_report.md` filled with architecture, metrics, failure analysis, improvements
- [x] Can explain at least one route and one failure mode during demo
- [x] Bonus: Streamlit HITL UI, Mermaid diagram, SQLite crash-resume, dead-letter queue
