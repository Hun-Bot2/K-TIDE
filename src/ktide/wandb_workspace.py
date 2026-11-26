"""The K-TIDE W&B workspace views, defined in code.

Two saved views share one panel layout and differ only in the run filter:
  - "K-TIDE controlled (FP16)": M0 baseline + FP16 controlled runs (M1-M4 and later)
  - "K-TIDE pilot (BF16)":      M0 baseline + the BF16 pilot runs (M1 data-v1)
Knowledge accuracy and instruction following are shown separately.

Panels refer to metric keys and the filter uses run attributes (tag, config.stage,
config.study_phase), never run ids or condition names, so new runs appear without saving again.
Run --save only when panels, layout or the filter policy change; use --check after new runs.
Auto-generated panels are off in these views; runs and data are never deleted.

Usage:
    uv run python -m ktide.wandb_workspace            # print the plan
    uv run python -m ktide.wandb_workspace --save     # create or update the saved views
    uv run python -m ktide.wandb_workspace --check    # read-only: runs each view shows now
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ENTITY, PROJECT = "hun-bot", "K-TIDE"
VIEWS_FILE = Path(__file__).with_name("wandb_views.json")
SPLIT = "during_development"
# view name -> study phases shown (with the research tag and training/evaluation stages)
VIEWS = {
    "K-TIDE controlled (FP16)": ("baseline", "controlled"),
    "K-TIDE pilot (BF16)": ("baseline", "pilot"),
}
LEGACY_VIEW = "K-TIDE experiments (managed)"  # the first saved view, reused as the controlled view
FILTER_TAG = "research"
FILTER_STAGES = ("training", "evaluation")
TERM_FORMS = ["ko", "en", "abbr", "mixed"]


def m(section: str, key: str) -> str:
    return f"{section}/{key}/{SPLIT}/mean"


def d(section: str, key: str) -> str:
    return f"delta_vs_M0/{section}/{key}"


def plan() -> list[tuple[str, list[dict]]]:
    """Sections as plain data (testable without the W&B client)."""
    line = lambda title, y: {"kind": "line", "title": title, "x": "train/global_step", "y": [y]}  # noqa: E731
    bar = lambda title, keys: {"kind": "bar", "title": title, "metrics": keys}  # noqa: E731
    media = lambda title, keys: {"kind": "media", "title": title, "keys": keys}  # noqa: E731
    return [
        (
            "1. Training / validation loss",
            [
                line("Training loss", "train/loss"),
                line("Validation loss", "eval/loss"),
                line("Learning rate", "train/learning_rate"),
                line("Gradient norm", "train/grad_norm"),
                bar("FP16 checks: non-finite loss/grad steps", ["train/nonfinite_steps"]),
                bar("FP16 checks: final gradient scale", ["train/grad_scale_final"]),
            ],
        ),
        (
            f"2. Knowledge accuracy ({SPLIT})",
            [
                bar("Strict accuracy (correct only)", [m("reference", "accuracy")]),
                bar("Reference score (correct 1, partial 0.5)", [m("reference", "score")]),
                bar("Judge: accuracy (1-5)", [m("rubric", "accuracy")]),
            ],
        ),
        (
            f"3. Instruction following ({SPLIT})",
            [
                bar("30-word limit", [m("rules", "word_limit")]),
                bar("1-2 sentences", [m("rules", "sentence_limit")]),
                bar("Both length limits", [m("rules", "both_limits")]),
                bar("Judge: constraints (1-5)", [m("rubric", "constraints")]),
            ],
        ),
        (
            f"4. LLM judge detail (professor rubric, 1-5, {SPLIT})",
            [
                bar(
                    "Total / accuracy / relevance / constraints",
                    [m("rubric", k) for k in ("total", "accuracy", "relevance", "constraints")],
                ),
            ],
        ),
        (
            f"5. Terminology ({SPLIT})",
            [
                bar("English term preservation", [m("rules", "term_preservation")]),
                bar(
                    "Term preservation by question term form",
                    [f"{SPLIT}/by_term_form/rules/term_preservation/{c}" for c in TERM_FORMS],
                ),
            ],
        ),
        (
            "6. Change vs M0 baseline (same items)",
            [
                bar(
                    "Knowledge",
                    [d("reference", "accuracy"), d("reference", "score"), d("rubric", "accuracy")],
                ),
                bar(
                    "Instruction following",
                    [
                        d("rules", "word_limit"),
                        d("rules", "sentence_limit"),
                        d("rules", "both_limits"),
                    ],
                ),
                bar(
                    "Judge rubric (points)",
                    [d("rubric", k) for k in ("total", "relevance", "constraints")],
                ),
                bar(
                    "Terminology and style",
                    [
                        d("rules", "term_preservation"),
                        d("rules", "polite_rate"),
                        d("rules", "source_mention_rate"),
                    ],
                ),
            ],
        ),
        (
            "7. Per-item change vs M0 (reference verdict)",
            [
                bar(
                    "Improved / unchanged / declined items",
                    ["paired_vs_M0/better", "paired_vs_M0/same", "paired_vs_M0/worse"],
                ),
            ],
        ),
        (
            f"8. Domain heatmaps ({SPLIT})",
            [
                media(
                    "Per-domain scores and change vs M0",
                    ["heatmap/by_domain", "heatmap/by_domain_delta_vs_M0"],
                )
            ],
        ),
        (
            "9. Style and training summary",
            [
                bar("Polite register", [m("rules", "polite_rate")]),
                bar("Source mention", [m("rules", "source_mention_rate")]),
                bar("Final validation loss", ["train/final_eval_loss"]),
                bar(
                    "Export checks (1 = pass)",
                    ["export/professor_unpack_model_ok", "export/greedy"],
                ),
            ],
        ),
    ]


def runset(phases):
    from wandb_workspaces import expr

    return [
        expr.Tags().isin([FILTER_TAG]),
        expr.Config("stage").isin(list(FILTER_STAGES)),
        expr.Config("study_phase").isin(list(phases)),
    ]


def server_filter(phases) -> dict:
    """The same policy as a W&B API query, to list the runs a view shows."""
    return {
        "tags": {"$in": [FILTER_TAG]},
        "config.stage": {"$in": list(FILTER_STAGES)},
        "config.study_phase": {"$in": list(phases)},
    }


def build(phases):
    import wandb_workspaces.reports.v2 as wr
    import wandb_workspaces.workspaces as ws

    def panel(spec):
        if spec["kind"] == "line":
            return wr.LinePlot(title=spec["title"], x=spec["x"], y=spec["y"])
        if spec["kind"] == "bar":
            return wr.BarPlot(title=spec["title"], metrics=spec["metrics"], orientation="v")
        return wr.MediaBrowser(
            title=spec["title"], media_keys=spec["keys"], mode="grid", grid_x_axis="run"
        )

    sections = [
        ws.Section(name=name, panels=[panel(p) for p in panels], is_open=True)
        for name, panels in plan()
    ]
    settings = ws.WorkspaceSettings(max_runs=50, x_axis="train/global_step")
    return sections, settings, ws.RunsetSettings(filters=runset(phases))


def _url(url: str) -> str:
    return url.replace("forge.coreweave.com", "wandb.ai")


def save() -> dict[str, str]:
    import wandb_workspaces.workspaces as ws

    views = json.loads(VIEWS_FILE.read_text()) if VIEWS_FILE.is_file() else {}
    if LEGACY_VIEW in views and next(iter(VIEWS)) not in views:
        views[next(iter(VIEWS))] = views.pop(LEGACY_VIEW)
    for name, phases in VIEWS.items():
        sections, settings, runset_settings = build(phases)
        if name in views:
            workspace = ws.Workspace.from_url(_url(views[name]))
            workspace.name = name
            workspace.sections = sections  # replaces every existing section
            workspace.settings = settings
            workspace.runset_settings = runset_settings
            workspace.save()
        else:
            workspace = ws.Workspace(
                entity=ENTITY,
                project=PROJECT,
                name=name,
                sections=sections,
                settings=settings,
                runset_settings=runset_settings,
                auto_generate_panels=False,
            )
            workspace.save()
            views[name] = workspace.url
    VIEWS_FILE.write_text(json.dumps(views, indent=1) + "\n")
    return views


def verify(views: dict[str, str]) -> dict:
    import wandb_workspaces.workspaces as ws

    expected = {name: len(panels) for name, panels in plan()}
    out = {}
    for name, phases in VIEWS.items():
        workspace = ws.Workspace.from_url(_url(views[name]))
        actual = {s.name: len(s.panels) for s in workspace.sections}
        saved = str(workspace.runset_settings.filters)
        if actual != expected:
            raise ValueError(f"{name}: sections differ: {actual} != {expected}")
        if any(p not in saved for p in phases) or "condition" in saved or FILTER_TAG not in saved:
            raise ValueError(f"{name}: unexpected run filter: {saved}")
        out[name] = {"panels": sum(actual.values()), "filter": saved}
    return out


def check() -> dict[str, list[dict]]:
    """Read-only: each saved view keeps the dynamic filter; which runs it shows now and how many
    planned panel keys each run has. Use after new runs instead of re-saving."""
    import wandb

    views = json.loads(VIEWS_FILE.read_text())
    verify(views)
    keys = {
        k for _, ps in plan() for p in ps for k in p.get("metrics", p.get("y", p.get("keys", [])))
    }
    api = wandb.Api(overrides={"base_url": "https://api.wandb.ai"}, timeout=20)
    out = {}
    for name, phases in VIEWS.items():
        rows = []
        for run in api.runs(f"{ENTITY}/{PROJECT}", filters=server_filter(phases)):
            present = set(run.summary.keys())
            if run.job_type == "training":
                present |= {k for row in run.scan_history(page_size=50) for k in row}
            rows.append(
                {
                    "run": run.name,
                    "id": run.id,
                    "job_type": run.job_type,
                    "study_phase": run.config.get("study_phase"),
                    "panel_keys_with_data": len(keys & present),
                }
            )
        out[name] = rows
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", action="store_true", help="only after panel/layout/filter changes")
    ap.add_argument("--check", action="store_true", help="read-only: which runs each view shows")
    args = ap.parse_args(argv)
    if args.check:
        for name, rows in check().items():
            print(name)
            for row in rows:
                print("  ", row)
        return 0
    if not args.save:
        for name, panels in plan():
            print(name, [p["title"] for p in panels])
        return 0
    views = save()
    for name, info in verify(views).items():
        print("saved", name, _url(views[name]), info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
