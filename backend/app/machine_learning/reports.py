"""Evaluation reports: Markdown files rendered from ``training_runs.report``.

Every training run (collaborative or satisfaction, deployed, kept, skipped or
failed) gets ``<models_dir>/reports/<kind>-<run id>.md`` plus the JSON in the
database, so the evidence behind each deployment decision is kept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.ml import TrainingRun


def _table(rows: dict[str, dict[str, Any]], metrics: list[str]) -> list[str]:
    out = ["| Model | " + " | ".join(metrics) + " |", "|---|" + "---:|" * len(metrics)]
    for name, m in rows.items():
        out.append(f"| {name} | " + " | ".join(_fmt(m.get(k)) for k in metrics) + " |")
    return out


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def render(run: TrainingRun) -> str:
    r = run.report or {}
    lines = [
        f"# {run.kind.capitalize()} training run {run.id}",
        "",
        f"- Started: {run.started_at:%Y-%m-%d %H:%M} UTC · trigger: {run.trigger}"
        f" · status: **{run.status}**",
        f"- Decision: {run.decision or r.get('decision') or run.error or '-'}",
        "",
        "## Dataset",
        "",
        "```json",
        json.dumps(r.get("dataset", run.dataset_stats or {}), indent=1, default=str),
        "```",
    ]
    if run.kind == "satisfaction" and "models" in r:
        lines += ["", "## Time-based splits", ""]
        for name, w in r.get("splits", {}).items():
            lines.append(
                f"- {name}: {w.get('rows')} rows, {w.get('positives', '-')} satisfied, "
                f"{w.get('from', '-')} → {w.get('to', '-')}"
            )
        lines += ["", "## Test metrics (binary satisfaction)", ""]
        lines += _table(
            r["models"], ["auc", "logloss", "brier", "ece", "mean_predicted", "observed_rate"]
        )
        cal = r.get("calibration", {})
        lines += [
            "",
            f"## Calibration ({cal.get('method')}, fitted on {cal.get('fitted_on_rows')} rows)",
            "",
            "| Bin | Rows | Predicted | Observed |",
            "|---|---:|---:|---:|",
        ]
        for b in cal.get("test_table", []):
            lines.append(
                f"| {b['lo']:.1f}-{b['hi']:.1f} | {b['n']} "
                f"| {b['predicted']:.3f} | {b['observed']:.3f} |"
            )
        lines += ["", "## Ranking within each player's test labels", ""]
        lines += _table(r.get("ranking", {}), ["ndcg@5", "players"])
        lines += [
            "",
            "## Ordinal satisfaction (investigated, not deployed)",
            "",
            "```json",
            json.dumps(r.get("ordinal", {}), indent=1),
            "```",
        ]
        if r.get("by_category"):
            lines += ["", "## By category", ""]
            for cat, v in r["by_category"].items():
                lines.append(
                    f"- {cat} ({v['rows']} rows): "
                    f"LightGBM AUC {_fmt(v['lgbm_calibrated']['auc'])}, "
                    f"content AUC {_fmt(v['content_logistic']['auc'])}"
                )
        lines += ["", "## Top features (gain)", ""]
        lines += [f"- {f['feature']}: {f['gain']}" for f in r.get("feature_importance", [])]
        lines += ["", "## Deployment gates", ""]
        lines += [
            f"- {'✅' if g['passed'] else '❌'} {g['name']}: {g['detail']}"
            for g in r.get("gates", [])
        ]
    if run.kind == "collaborative" and "results" in r:
        for split, res in r["results"].items():
            lines += ["", f"## {split} split", ""]
            lines += _table(
                res,
                ["users", "ndcg@5", "precision@5", "recall@20", "negative_rate@5", "coverage@5"],
            )
    return "\n".join(lines) + "\n"


def write(models_dir: str, run: TrainingRun) -> str:
    d = Path(models_dir) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{run.kind}-{run.id}.md"
    path.write_text(render(run), encoding="utf-8")
    return str(path)
