"""CLI for the lab."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import typer
import yaml

from .graph import build_graph
from .metrics import MetricsReport, metric_from_state, summarize_metrics, write_metrics
from .persistence import build_checkpointer
from .report import write_report
from .scenarios import load_scenarios
from .state import Route, initial_state

app = typer.Typer(no_args_is_help=True)


@app.command("run-scenarios")
def run_scenarios(
    config: Annotated[Path, typer.Option("--config")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Run all grading scenarios and write metrics JSON."""
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    scenarios = load_scenarios(cfg["scenarios_path"])
    checkpointer = build_checkpointer(cfg.get("checkpointer", "memory"), cfg.get("database_url"))
    graph = build_graph(checkpointer=checkpointer)
    metrics: list = []

    for scenario in scenarios:
        state = initial_state(scenario)
        run_config: dict = {"configurable": {"thread_id": state["thread_id"]}}
        t0 = time.monotonic()
        final_state = graph.invoke(state, config=run_config)
        latency_ms = int((time.monotonic() - t0) * 1000)
        metrics.append(
            metric_from_state(
                final_state,
                scenario.expected_route.value,
                scenario.requires_approval,
                latency_ms=latency_ms,
            )
        )
        typer.echo(
            f"  {scenario.id}: route={final_state.get('route')} "
            f"latency={latency_ms}ms"
        )

    # Crash-resume demonstration: retrieve persisted state for an error scenario
    resume_success = False
    if cfg.get("demo_resume") and checkpointer is not None:
        error_scenario = next(
            (s for s in scenarios if s.expected_route == Route.ERROR), None
        )
        if error_scenario:
            thread_id = f"thread-{error_scenario.id}"
            try:
                saved = graph.get_state({"configurable": {"thread_id": thread_id}})
                if saved and saved.values:
                    resume_success = True
                    typer.echo(
                        f"[persistence] Resume evidence: thread_id={thread_id} "
                        f"route={saved.values.get('route')} "
                        f"attempt={saved.values.get('attempt', 0)} "
                        f"nodes={len(saved.values.get('events', []))} — state recovered"
                    )
                    # Print state history depth
                    history = list(
                        graph.get_state_history({"configurable": {"thread_id": thread_id}})
                    )
                    typer.echo(
                        f"[persistence] State history depth: {len(history)} checkpoint(s) "
                        f"for thread_id={thread_id}"
                    )
            except Exception as exc:  # noqa: BLE001
                typer.echo(f"[persistence] Resume demo failed: {exc}")

    report = summarize_metrics(metrics, resume_success=resume_success)
    write_metrics(report, output)
    if cfg.get("report_path"):
        write_report(report, cfg["report_path"])
    typer.echo(f"\nWrote metrics to {output}")
    typer.echo(
        f"Summary: {report.total_scenarios} scenarios, "
        f"success_rate={report.success_rate:.0%}, "
        f"retries={report.total_retries}, "
        f"interrupts={report.total_interrupts}"
    )


@app.command("validate-metrics")
def validate_metrics(
    metrics: Annotated[Path, typer.Option("--metrics")],
) -> None:
    """Validate metrics JSON schema for grading."""
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    report = MetricsReport.model_validate(payload)
    if report.total_scenarios < 6:
        raise typer.BadParameter("Expected at least 6 scenarios")
    typer.echo(f"Metrics valid. success_rate={report.success_rate:.2%}")


@app.command("draw-diagram")
def draw_diagram(
    output: Annotated[Path, typer.Option("--output")] = Path("outputs/graph.md"),
) -> None:
    """Export the workflow graph as a Mermaid diagram."""
    graph = build_graph()
    try:
        mermaid = graph.get_graph().draw_mermaid()
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Could not render Mermaid diagram: {exc}")
        raise typer.Exit(1) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"```mermaid\n{mermaid}\n```\n", encoding="utf-8")
    typer.echo(f"Diagram written to {output}")


@app.command("replay-history")
def replay_history(
    thread_id: Annotated[str, typer.Option("--thread-id")],
    config: Annotated[Path, typer.Option("--config")],
) -> None:
    """Print the checkpoint history for a given thread (time-travel demo)."""
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    checkpointer = build_checkpointer(cfg.get("checkpointer", "memory"), cfg.get("database_url"))
    graph = build_graph(checkpointer=checkpointer)
    run_config: dict = {"configurable": {"thread_id": thread_id}}
    history = list(graph.get_state_history(run_config))
    typer.echo(f"Thread '{thread_id}': {len(history)} checkpoint(s)")
    for i, snapshot in enumerate(history):
        vals = snapshot.values
        typer.echo(
            f"  [{i}] route={vals.get('route')} "
            f"attempt={vals.get('attempt')} "
            f"nodes={len(vals.get('events', []))}"
        )


if __name__ == "__main__":
    app()
