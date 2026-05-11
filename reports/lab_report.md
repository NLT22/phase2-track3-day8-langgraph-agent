# Day 08 Lab Report

## 1. Team / Student

- Name: Nguyễn Lê Trung
- StudentID: 2A202600174
- Date: 2026-05-11

## 2. Architecture

The workflow implements a support-ticket routing agent built with LangGraph. It has
**11 nodes** connected by **4 conditional routing functions**. All paths terminate at
`finalize → END`.

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

**Key design decisions:**

- **Keyword priority in `classify_node`**: risky > tool > missing_info > error > simple.
  Risky keywords are checked first to prevent "delete order" from routing to `tool`.
  Uses substring-within-word matching so "failure" triggers `error` correctly.
  The word "it" uses exact whole-word matching to avoid false positives like "iteration".

- **Retry loop**: `tool → evaluate → retry → tool` creates a bounded cycle.
  `route_after_retry` exits to `dead_letter` when `attempt >= max_attempts`.
  S07 (max_attempts=1) immediately exhausts retries and lands in dead_letter.

- **HITL approval gate**: Risky actions pass through `risky_action → approval` before
  any tool execution. With `LANGGRAPH_INTERRUPT=true`, `approval_node` calls `interrupt()`
  to suspend the graph for a real human decision.

- **Append-only audit fields**: `messages`, `tool_results`, `errors`, and `events` use
  the `add` reducer, preserving full history for debugging and grading.

## 3. State Schema

| Field | Reducer | Why |
|---|---|---|
| `messages` | append (`add`) | Full conversation audit trail |
| `tool_results` | append (`add`) | Preserve all tool call results for evaluate_node |
| `errors` | append (`add`) | Accumulate retry error records across attempts |
| `events` | append (`add`) | Ordered audit log of every node visit |
| `route` | overwrite | Current routing decision — only latest matters |
| `attempt` | overwrite | Current retry counter |
| `final_answer` | overwrite | Latest response replaces previous placeholder |
| `approval` | overwrite | Latest approval decision |
| `evaluation_result` | overwrite | Latest evaluate_node verdict |
| `proposed_action` | overwrite | Action pending approval |
| `risk_level` | overwrite | Severity set at classification time |

## 4. Scenario Results

| Scenario | Expected | Actual | Success | Retries | Interrupts | Latency |
|---|---|---|---|---|---|---|
| S01_simple | simple | simple | YES | 0 | 0 | 47ms |
| S02_tool | tool | tool | YES | 0 | 0 | 47ms |
| S03_missing | missing_info | missing_info | YES | 0 | 0 | 30ms |
| S04_risky | risky | risky | YES | 0 | 3 | 63ms |
| S05_error | error | error | YES | 6 | 0 | 77ms |
| S06_delete | risky | risky | YES | 0 | 3 | 62ms |
| S07_dead_letter | error | error | YES | 3 | 0 | 46ms |
| S08_simple2 | simple | simple | YES | 0 | 0 | 47ms |
| S09_tool2 | tool | tool | YES | 0 | 0 | 63ms |
| S10_missing2 | missing_info | missing_info | YES | 0 | 0 | 46ms |
| S11_risky2 | risky | risky | YES | 0 | 3 | 62ms |
| S12_error2 | error | error | YES | 6 | 0 | 62ms |
| S13_risky_over_tool | risky | risky | YES | 0 | 3 | 78ms |
| S14_tool_over_error | tool | tool | YES | 0 | 0 | 77ms |
| S15_risky_multi | risky | risky | YES | 0 | 3 | 61ms |

**Summary**: 15 scenarios — 100% success rate —
avg 19.8 nodes visited — 15 total retries —
15 HITL interrupts — resume_success=True

## 5. Failure Analysis

**Failure mode 1 — Transient tool failure (S05_error, S12_error2)**:
The error route enters the retry loop. `tool_node` returns an `ERROR:` prefixed result
when `route == error` and `attempt < 2`. `evaluate_node` detects the `ERROR` prefix and
sets `evaluation_result = "needs_retry"`. `route_after_evaluate` returns `"retry"`,
which increments `attempt` and computes exponential backoff metadata. After two retries
`attempt >= 2`, so `tool_node` returns a success result and the flow proceeds to
`answer → finalize`. This demonstrates a bounded, self-healing retry loop.

**Failure mode 2 — Max retries exhausted / dead-letter (S07_dead_letter)**:
S07 sets `max_attempts=1`. After the first retry `attempt` becomes 1 and
`route_after_retry` checks `1 >= 1` → routes to `dead_letter`. `dead_letter_node`
writes the failure record to `outputs/dead_letters.jsonl` and sets `final_answer` to
a manual-review message. This path still reaches `finalize → END`, so the graph always
terminates.

**Failure mode 3 — Keyword false positive**:
The query "In order to get help..." contains the word "order", which is a TOOL keyword.
This routes it to `tool` instead of `simple`. This is a known trade-off of
keyword-based routing: precision vs. coverage. In production, a small LLM call would
replace the keyword heuristic.

## 6. Persistence / Recovery Evidence

SQLite checkpointer used with WAL journal mode. One thread_id per run. After all scenarios completed, `graph.get_state()` was called for the first error-route scenario and the full persisted state was recovered, confirming crash-resume capability. State history depth also verified via `graph.get_state_history()`.

## 7. Extension Work

- **SQLite persistence**: `build_checkpointer("sqlite")` uses
  `sqlite3.connect(path, check_same_thread=False)` with `PRAGMA journal_mode=WAL` for
  safe concurrent access. The `from_conn_string()` API (broken in 3.x) was replaced.

- **Graph diagram**: `agent-lab draw-diagram --output outputs/graph.md` exports the
  Mermaid diagram via `graph.get_graph().draw_mermaid()`.

- **State history replay**: `agent-lab replay-history --thread-id <id>` iterates
  `graph.get_state_history()` and prints each checkpoint's route/attempt/node count.

- **Streamlit HITL UI**: `streamlit run src/langgraph_agent_lab/ui.py` provides a
  browser-based Approve/Reject interface that uses `interrupt()` + `Command(resume=...)`.

- **Dead-letter queue**: `dead_letter_node` appends failure records to
  `outputs/dead_letters.jsonl` for manual review.

## 8. Improvement Plan

If given one more day:

1. **Semantic routing**: Replace keyword heuristics with a single Claude Haiku call.
   Cost: ~$0.0003/request. Benefit: eliminates all keyword false positives and handles
   multilingual queries.

2. **Real HITL with Streamlit**: The Streamlit UI already exists; wire it to a persistent
   SQLite checkpoint so the approver can log in hours after the request was submitted and
   the graph resumes exactly where it paused.

3. **Parallel fan-out**: Use `Send()` to query two tool backends (e.g., CRM + billing)
   concurrently and merge results via the `add` reducer in a single `evaluate` step.

4. **Prometheus metrics**: Export `retry_count`, `latency_ms`, and `dead_letter_count`
   as Prometheus gauges so on-call can set alerts on retry spikes.
