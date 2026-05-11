"""Streamlit HITL approval UI for the LangGraph agent lab.

Run with:
    streamlit run src/langgraph_agent_lab/ui.py

Features:
- Select a risky/HITL scenario or enter a custom query
- Runs the graph with LANGGRAPH_INTERRUPT=true — suspends at approval_node
- Approve or Reject the proposed action via browser buttons
- Shows full audit events and final answer after resume
- Metrics tab displays outputs/metrics.json if available
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["LANGGRAPH_INTERRUPT"] = "true"

# Add src to path for direct streamlit run
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from langgraph_agent_lab.graph import build_graph
from langgraph_agent_lab.persistence import build_checkpointer
from langgraph_agent_lab.scenarios import load_scenarios
from langgraph_agent_lab.state import Route, Scenario, initial_state

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Support Ticket Agent — HITL Approval",
    page_icon="🤖",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state bootstrap
# ---------------------------------------------------------------------------
if "graph" not in st.session_state:
    st.session_state.graph = build_graph(checkpointer=build_checkpointer("memory"))
if "pending_interrupt" not in st.session_state:
    st.session_state.pending_interrupt = None
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "final_result" not in st.session_state:
    st.session_state.final_result = None
if "run_log" not in st.session_state:
    st.session_state.run_log: list[str] = []

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_run, tab_metrics, tab_diagram = st.tabs(["Run Scenario", "Metrics", "Graph Diagram"])

# ---------------------------------------------------------------------------
# Tab 1: Run Scenario
# ---------------------------------------------------------------------------
with tab_run:
    st.title("Support Ticket Agent — HITL Approval UI")
    st.markdown(
        "Select a scenario or type a custom query. "
        "Risky queries will pause for human approval."
    )

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("Input")
        try:
            scenarios = load_scenarios("data/sample/scenarios.jsonl")
        except FileNotFoundError:
            scenarios = []

        scenario_ids = ["(custom query)"] + [s.id for s in scenarios]
        selected_id = st.selectbox("Select scenario", scenario_ids)

        if selected_id == "(custom query)":
            custom_query = st.text_input("Enter your query", value="Refund customer and send email")
            expected_route_str = st.selectbox(
                "Expected route (for metrics)",
                ["simple", "tool", "missing_info", "risky", "error"],
                index=3,
            )
        else:
            selected_scenario = next(s for s in scenarios if s.id == selected_id)
            custom_query = selected_scenario.query
            expected_route_str = selected_scenario.expected_route.value
            st.info(f"Query: {custom_query}")
            st.info(f"Expected route: {expected_route_str}")

        run_disabled = st.session_state.pending_interrupt is not None
        if st.button("Run", type="primary", disabled=run_disabled):
            st.session_state.final_result = None
            st.session_state.run_log = []
            try:
                route_enum = Route(expected_route_str)
            except ValueError:
                route_enum = Route.SIMPLE

            scenario_obj = Scenario(
                id="ui-run",
                query=custom_query,
                expected_route=route_enum,
            )
            init = initial_state(scenario_obj)
            st.session_state.thread_id = init["thread_id"]
            cfg: dict = {"configurable": {"thread_id": init["thread_id"]}}

            try:
                result = st.session_state.graph.invoke(init, config=cfg)
                st.session_state.final_result = result
                st.session_state.pending_interrupt = None
                st.session_state.run_log.append("Graph completed without interruption.")
            except Exception:  # noqa: BLE001
                # LangGraph interrupt raises — check for pending tasks
                saved = st.session_state.graph.get_state(cfg)
                if saved and saved.tasks:
                    for task in saved.tasks:
                        if task.interrupts:
                            st.session_state.pending_interrupt = task.interrupts[0].value
                            st.session_state.run_log.append(
                                f"Graph suspended at approval_node. "
                                f"Proposed: {task.interrupts[0].value}"
                            )
                            break
                else:
                    st.session_state.run_log.append("Graph suspended (no interrupt value found).")
            st.rerun()

        reset_disabled = (
            st.session_state.pending_interrupt is None
            and st.session_state.final_result is None
        )
        if st.button("Reset", disabled=reset_disabled):
            st.session_state.pending_interrupt = None
            st.session_state.final_result = None
            st.session_state.thread_id = None
            st.session_state.run_log = []
            st.rerun()

    with col_right:
        st.subheader("Workflow Status")

        if st.session_state.run_log:
            for msg in st.session_state.run_log:
                st.caption(msg)

        # --------------- HITL approval panel -------------------
        if st.session_state.pending_interrupt:
            st.warning("**HITL Approval Required**")
            st.json(st.session_state.pending_interrupt)
            st.markdown("---")
            a_col, r_col = st.columns(2)

            with a_col:
                if st.button("✅ Approve", type="primary"):
                    cfg = {"configurable": {"thread_id": st.session_state.thread_id}}
                    try:
                        from langgraph.types import Command  # type: ignore[import-untyped]

                        result = st.session_state.graph.invoke(
                            Command(resume={
                                "approved": True,
                                "reviewer": "streamlit-user",
                                "comment": "approved via UI",
                            }),
                            config=cfg,
                        )
                        st.session_state.final_result = result
                        st.session_state.pending_interrupt = None
                        st.session_state.run_log.append("Action approved — graph resumed.")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Resume failed: {exc}")
                    st.rerun()

            with r_col:
                if st.button("❌ Reject"):
                    cfg = {"configurable": {"thread_id": st.session_state.thread_id}}
                    try:
                        from langgraph.types import Command  # type: ignore[import-untyped]

                        result = st.session_state.graph.invoke(
                            Command(resume={
                                "approved": False,
                                "reviewer": "streamlit-user",
                                "comment": "rejected via UI",
                            }),
                            config=cfg,
                        )
                        st.session_state.final_result = result
                        st.session_state.pending_interrupt = None
                        st.session_state.run_log.append("Action rejected — graph resumed.")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Resume failed: {exc}")
                    st.rerun()

        # --------------- Final result -------------------------
        if st.session_state.final_result:
            result = st.session_state.final_result
            st.success("**Workflow Complete**")

            st.markdown(f"**Route**: `{result.get('route', 'N/A')}`")
            st.markdown(f"**Risk level**: `{result.get('risk_level', 'N/A')}`")

            final_ans = result.get("final_answer") or result.get("pending_question")
            if final_ans:
                st.info(f"**Answer / Question**: {final_ans}")

            if result.get("approval"):
                approval = result["approval"]
                icon = "✅" if approval.get("approved") else "❌"
                st.markdown(
                    f"**Approval**: {icon} reviewer=`{approval.get('reviewer')}` "
                    f"comment=`{approval.get('comment', '')}`"
                )

            with st.expander("Audit events"):
                st.json(result.get("events", []))

            with st.expander("Tool results"):
                st.json(result.get("tool_results", []))

            if result.get("errors"):
                with st.expander("Errors / retries"):
                    st.json(result.get("errors", []))

# ---------------------------------------------------------------------------
# Tab 2: Metrics
# ---------------------------------------------------------------------------
with tab_metrics:
    st.title("Scenario Metrics")
    metrics_path = Path("outputs/metrics.json")
    if metrics_path.exists():
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        st.metric("Total scenarios", data.get("total_scenarios", 0))
        st.metric("Success rate", f"{data.get('success_rate', 0):.0%}")
        st.metric("Avg nodes visited", f"{data.get('avg_nodes_visited', 0):.1f}")
        st.metric("Total retries", data.get("total_retries", 0))
        st.metric("Total interrupts", data.get("total_interrupts", 0))
        st.metric("Resume success", str(data.get("resume_success", False)))

        st.subheader("Per-scenario results")
        rows = data.get("scenario_metrics", [])
        if rows:
            import pandas as pd

            df = pd.DataFrame(rows)[
                [
                    "scenario_id",
                    "expected_route",
                    "actual_route",
                    "success",
                    "retry_count",
                    "interrupt_count",
                    "latency_ms",
                ]
            ]
            st.dataframe(df, use_container_width=True)
        st.json(data, expanded=False)
    else:
        st.info("No metrics.json found. Run `make run-scenarios` first.")

# ---------------------------------------------------------------------------
# Tab 3: Graph Diagram
# ---------------------------------------------------------------------------
with tab_diagram:
    st.title("Graph Diagram (Mermaid)")
    diagram_path = Path("outputs/graph.md")
    if diagram_path.exists():
        content = diagram_path.read_text(encoding="utf-8")
        mermaid_code = content.strip().removeprefix("```mermaid").removesuffix("```").strip()
        st.markdown(f"```mermaid\n{mermaid_code}\n```")
    else:
        st.info("No diagram found. Run `make diagram` first.")
        try:
            graph = build_graph()
            mermaid = graph.get_graph().draw_mermaid()
            st.markdown(f"**Live diagram:**\n\n```mermaid\n{mermaid}\n```")
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not render live diagram: {exc}")
