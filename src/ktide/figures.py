"""Benchmark figures from local results (no W&B, no LLM calls).

Reads runs/main/M*/<run>/eval_metrics.json (and training/train_log.json) and draws:
  1_rates.png      rate metrics (0-1) on the during_development split, one dot per run
  2_rubric.png     professor-rubric scores (1-5), same split (separate chart: different scale)
  3_slices.png     term preservation by term form, 30-word limit by domain (all generated answers)
  4_paired.png     per-item change of the reference verdict vs M0 (better / same / worse)
  5_training.png   training and validation loss per trained run
Every run with an eval_metrics.json is included, so new conditions appear on re-run.
Colors follow the condition (fixed order), never the rank.

Usage:
    uv run python -m ktide.figures --out report_course/figures/dev
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ktide.professor import REPO_ROOT

SPLIT = "during_development"
# fixed categorical order (validated: scripts/validate_palette.js, light surface)
COLORS = {"M0": "#2a78d6", "M1": "#eb6834", "M2": "#1baf7a", "M3": "#eda100", "M4": "#e87ba4"}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
RATES = [
    ("Reference accuracy", "reference", "accuracy"),
    ("Reference score (partial = 0.5)", "reference", "score"),
    ("30-word limit", "rules", "word_limit"),
    ("1-2 sentences", "rules", "sentence_limit"),
    ("English term preservation", "rules", "term_preservation"),
    ("Polite register", "rules", "polite_rate"),
    ("Source mention", "rules", "source_mention_rate"),
]
RUBRIC = [
    ("Total", "total"),
    ("Accuracy", "accuracy"),
    ("Relevance", "relevance"),
    ("Constraints", "constraints"),
]
TERM_FORMS = [
    ("Korean term", "ko"),
    ("English term", "en"),
    ("Abbreviation", "abbr"),
    ("Mixed", "mixed"),
]


def runs(root: Path) -> list[dict]:
    out = []
    for path in sorted((root / "runs/main").glob("M[0-4]/*/eval_metrics.json")):
        condition = path.parent.parent.name
        cfg_path = path.parent / "training" / "train_config.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {}
        if cfg.get("track") in ("smoke", "course"):
            continue
        from ktide.tracking import study_phase

        phase = study_phase(condition, cfg or None)
        label = (
            condition if not cfg else f"{condition} {phase} ({cfg.get('precision', '?').upper()})"
        )
        out.append(
            {
                "condition": condition,
                "label": label,
                "dir": path.parent,
                "metrics": json.loads(path.read_text()),
                "train": cfg,
            }
        )
    return out


def value(m: dict, section: str, key: str, split: str = SPLIT):
    try:
        cell = m[section][key]["split"][split]
    except KeyError:
        return None
    return cell["mean"], cell["n"]


def style(ax, title: str):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=10)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def dot_rows(ax, rows: list[str], series: list[tuple[str, str, list]], xlim, fmt):
    """One row per metric, one dot per run, a thin connector between the runs of a row."""
    import numpy as np

    y = np.arange(len(rows))[::-1]
    for i in range(len(rows)):
        vals = [s[2][i] for s in series if s[2][i] is not None]
        if len(vals) > 1:
            ax.plot([min(vals), max(vals)], [y[i]] * 2, color=GRID, linewidth=2, zorder=1)
    for k, (label, color, vals) in enumerate(series):
        xs = [v for v in vals if v is not None]
        ys = [y[i] for i, v in enumerate(vals) if v is not None]
        ax.scatter(xs, ys, s=64, color=color, edgecolor=SURFACE, linewidth=2, zorder=3, label=label)
        offset = 7 if k % 2 else -7
        for xv, yv in zip(xs, ys, strict=True):
            ax.annotate(
                fmt(xv),
                (xv, yv),
                xytext=(0, offset),
                textcoords="offset points",
                ha="center",
                va="center",
                fontsize=8,
                color=INK2,
            )
    ax.set_yticks(y, rows)
    ax.set_xlim(*xlim)
    ax.set_ylim(-0.7, len(rows) - 0.3)


def save(fig, path: Path):
    fig.patch.set_facecolor(SURFACE)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=SURFACE)


def draw(root: Path, out: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    data = runs(root)
    if not data:
        raise SystemExit("no runs with eval_metrics.json")
    color = {d["label"]: COLORS.get(d["condition"], INK2) for d in data}
    written = []
    n_dev = max((value(d["metrics"], "rules", "word_limit") or (0, 0))[1] for d in data)

    # 1. rates
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    series = [
        (
            d["label"],
            color[d["label"]],
            [(value(d["metrics"], s, k) or (None,))[0] for _, s, k in RATES],
        )
        for d in data
    ]
    dot_rows(ax, [t for t, _, _ in RATES], series, (-0.03, 1.08), lambda v: f"{v:.2f}")
    style(ax, f"Quality and format ({SPLIT}, n={n_dev}, 1 judge pass)")
    ax.legend(frameon=False, fontsize=9, loc="lower right", labelcolor=INK2)
    save(fig, out / "1_rates.png")
    written.append(out / "1_rates.png")
    plt.close(fig)

    # 2. rubric
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    series = [
        (
            d["label"],
            color[d["label"]],
            [(value(d["metrics"], "rubric", k) or (None,))[0] for _, k in RUBRIC],
        )
        for d in data
    ]
    dot_rows(ax, [t for t, _ in RUBRIC], series, (1, 5.2), lambda v: f"{v:.2f}")
    style(ax, f"Professor rubric 1-5 ({SPLIT}, n={n_dev}, 1 judge pass)")
    ax.legend(frameon=False, fontsize=9, loc="lower left", labelcolor=INK2)
    save(fig, out / "2_rubric.png")
    written.append(out / "2_rubric.png")
    plt.close(fig)

    # 3. slices (all generated answers)
    domains = sorted(
        {
            k
            for d in data
            for k in d["metrics"]["rules"]["word_limit"]["domain"]
            if k not in ("None", "null")
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={"width_ratios": [1, 1.4]})
    series = [
        (
            d["label"],
            color[d["label"]],
            [
                d["metrics"]["rules"]["term_preservation"]["term_form"].get(k, {}).get("mean")
                for _, k in TERM_FORMS
            ],
        )
        for d in data
    ]
    dot_rows(axes[0], [t for t, _ in TERM_FORMS], series, (-0.03, 1.08), lambda v: f"{v:.2f}")
    style(axes[0], "English term preservation by question term form")
    series = [
        (
            d["label"],
            color[d["label"]],
            [d["metrics"]["rules"]["word_limit"]["domain"].get(k, {}).get("mean") for k in domains],
        )
        for d in data
    ]
    dot_rows(
        axes[1],
        [k.split("_", 1)[1].replace("_", " ") for k in domains],
        series,
        (-0.03, 1.08),
        lambda v: f"{v:.2f}",
    )
    style(axes[1], "30-word limit by domain")
    axes[1].legend(frameon=False, fontsize=9, loc="lower left", labelcolor=INK2)
    fig.suptitle(
        "All generated answers per run (all splits)", x=0.01, ha="left", fontsize=9, color=INK2
    )
    save(fig, out / "3_slices.png")
    written.append(out / "3_slices.png")
    plt.close(fig)

    # 4. paired change vs M0 (reference verdict)
    base = next((d for d in data if d["condition"] == "M0"), None)
    trained = [d for d in data if d["condition"] != "M0"]
    if base and trained:
        score = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}
        m0 = json.loads((base["dir"] / "eval_ref_r1.json").read_text())
        rows = []
        for d in trained:
            path = d["dir"] / f"eval_ref_{SPLIT}_r1.json"
            if not path.is_file():
                continue
            mx = json.loads(path.read_text())
            better = sum(score[mx[k]["verdict"]] > score[m0[k]["verdict"]] for k in mx if k in m0)
            worse = sum(score[mx[k]["verdict"]] < score[m0[k]["verdict"]] for k in mx if k in m0)
            same = sum(1 for k in mx if k in m0) - better - worse
            rows.append((d["label"], better, same, worse))
        if rows:
            fig, ax = plt.subplots(figsize=(7.2, 0.9 + 0.55 * len(rows)))
            parts = [
                ("Better than M0", "#2a78d6"),
                ("Same", "#c3c2b7"),
                ("Worse than M0", "#eb6834"),
            ]
            for i, row in enumerate(rows):
                left = 0
                for (name, col), n in zip(parts, row[1:], strict=True):
                    ax.barh(
                        i,
                        n,
                        left=left,
                        color=col,
                        edgecolor=SURFACE,
                        linewidth=2,
                        height=0.5,
                        label=name if i == 0 else None,
                    )
                    ax.text(
                        left + n / 2, i, str(n), ha="center", va="center", fontsize=8, color=INK
                    )
                    left += n
            ax.set_yticks(range(len(rows)), [r[0] for r in rows])
            style(ax, f"Reference verdict per item vs M0, {SPLIT} split")
            ax.legend(
                frameon=False,
                fontsize=8,
                ncol=3,
                loc="upper center",
                bbox_to_anchor=(0.5, -0.25),
                labelcolor=INK2,
            )
            save(fig, out / "4_paired.png")
            written.append(out / "4_paired.png")
            plt.close(fig)

    # 5. training curves
    curves = [d for d in trained if (d["dir"] / "training" / "train_log.json").is_file()]
    if curves:
        fig, ax = plt.subplots(figsize=(7.2, 3.4))
        for d in curves:
            log = json.loads((d["dir"] / "training" / "train_log.json").read_text())
            c = color[d["label"]]
            tr = [(e["step"], e["loss"]) for e in log if "loss" in e]
            ev = [(e["step"], e["eval_loss"]) for e in log if "eval_loss" in e]
            ax.plot(
                *zip(*tr, strict=True),
                color=c,
                linewidth=2,
                marker="o",
                markersize=5,
                label=f"{d['label']} training loss",
            )
            ax.plot(
                *zip(*ev, strict=True),
                color=c,
                linewidth=2,
                linestyle="--",
                marker="s",
                markersize=5,
                label=f"{d['label']} validation loss",
            )
        style(ax, "Training curves (logged points only)")
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.spines["left"].set_visible(False)
        ax.set_xlabel("optimizer step", fontsize=9, color=INK2)
        ax.legend(frameon=False, fontsize=8, labelcolor=INK2)
        save(fig, out / "5_training.png")
        written.append(out / "5_training.png")
        plt.close(fig)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "report_course" / "figures" / "dev")
    args = ap.parse_args(argv)
    for path in draw(REPO_ROOT, args.out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
