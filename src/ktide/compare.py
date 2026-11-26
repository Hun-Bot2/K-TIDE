"""Comparisons of an evaluated run against the M0 baseline (aggregates only).

- deltas: run minus M0 for the headline metrics on the during_development split, only when both
  runs were scored on the same number of items there
- paired: per-item reference verdict change vs M0 (better / same / worse), same items only
- domain heatmaps (PNG): the run's per-domain scores and the change vs M0, during_development only

These describe differences; they are not significance tests and do not establish causes.
"""

from __future__ import annotations

import json
from pathlib import Path

SPLIT = "during_development"
HEADLINE = [
    ("reference", "accuracy"),
    ("reference", "score"),
    ("rubric", "total"),
    ("rubric", "accuracy"),
    ("rubric", "relevance"),
    ("rubric", "constraints"),
    ("rules", "word_limit"),
    ("rules", "sentence_limit"),
    ("rules", "both_limits"),
    ("rules", "term_preservation"),
    ("rules", "polite_rate"),
    ("rules", "source_mention_rate"),
]
HEATMAP_ROWS = [
    ("Strict accuracy", "reference/accuracy"),
    ("Reference score", "reference/score"),
    ("Both length limits", "rules/both_limits"),
    ("Term preservation", "rules/term_preservation"),
]
VERDICT = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}


def baseline_dir(root: Path) -> Path | None:
    runs = sorted((root / "runs/main/M0").glob("*/eval_metrics.json"))
    return runs[-1].parent if runs else None


def cell(metrics: dict, section: str, key: str):
    try:
        return metrics[section][key]["split"][SPLIT]
    except KeyError:
        return None


def deltas(metrics: dict, base: dict) -> dict:
    out = {}
    for section, key in HEADLINE:
        a, b = cell(metrics, section, key), cell(base, section, key)
        if a and b and a["n"] == b["n"]:
            out[f"delta_vs_M0/{section}/{key}"] = round(a["mean"] - b["mean"], 4)
    return out


def judged(run_dir: Path) -> dict | None:
    for name in (f"eval_ref_{SPLIT}_r1.json", "eval_ref_r1.json"):
        if (run_dir / name).is_file():
            return json.loads((run_dir / name).read_text())
    return None


def paired(run_dir: Path, base_dir: Path) -> dict:
    run, base = judged(run_dir), judged(base_dir)
    if not run or not base:
        return {}
    shared = [k for k in run if k in base]
    better = sum(VERDICT[run[k]["verdict"]] > VERDICT[base[k]["verdict"]] for k in shared)
    worse = sum(VERDICT[run[k]["verdict"]] < VERDICT[base[k]["verdict"]] for k in shared)
    return {
        "paired_vs_M0/better": better,
        "paired_vs_M0/same": len(shared) - better - worse,
        "paired_vs_M0/worse": worse,
        "paired_vs_M0/items": len(shared),
    }


def domain_table(metrics: dict) -> tuple[list[str], list[list[float | None]]]:
    slices = metrics.get("slices", {})
    domains = sorted(
        {d for _, k in HEATMAP_ROWS for d in slices.get(k, {}).get("domain", {}) if d != "None"}
    )
    table = [
        [slices.get(k, {}).get("domain", {}).get(d, {}).get("mean") for d in domains]
        for _, k in HEATMAP_ROWS
    ]
    return domains, table


def heatmaps(metrics: dict, base: dict | None, title: str, out: Path) -> dict[str, Path]:
    """Two PNGs: per-domain values (sequential) and change vs M0 (diverging, gray at zero)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    domains, table = domain_table(metrics)
    if not domains:
        return {}
    out.mkdir(parents=True, exist_ok=True)
    labels = [d.split("_", 1)[1].replace("_", " ") for d in domains]
    rows = [name for name, _ in HEATMAP_ROWS]
    sequential = LinearSegmentedColormap.from_list("seq", ["#eef4fc", "#2a78d6", "#0d3a73"])
    diverging = LinearSegmentedColormap.from_list("div", ["#e34948", "#e8e7e3", "#2a78d6"])
    paths = {}

    def draw(values, cmap, vmin, vmax, name, subtitle, fmt):
        arr = np.array([[np.nan if v is None else v for v in r] for r in values], dtype=float)
        fig, ax = plt.subplots(figsize=(10, 2.9))
        image = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
        ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right", fontsize=8)
        ax.set_yticks(range(len(rows)), rows, fontsize=8)
        for i in range(arr.shape[0]):
            for j in range(arr.shape[1]):
                if not np.isnan(arr[i, j]):
                    dark = abs(arr[i, j] - (vmin + vmax) / 2) > (vmax - vmin) * 0.3
                    ax.text(
                        j,
                        i,
                        fmt(arr[i, j]),
                        ha="center",
                        va="center",
                        fontsize=7,
                        color="white" if dark and cmap is sequential else "#0b0b0b",
                    )
        ax.set_title(f"{title}: {subtitle}", loc="left", fontsize=9)
        fig.colorbar(image, ax=ax, fraction=0.02, pad=0.01)
        fig.tight_layout()
        path = out / f"{name}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths[name] = path

    draw(table, sequential, 0, 1, "by_domain", f"by domain ({SPLIT})", lambda v: f"{v:.2f}")
    if base is not None and title.split(" ")[0] != "M0":
        _, base_table = domain_table(base)
        base_domains, _ = domain_table(base)
        if base_domains == domains:
            delta = [
                [None if a is None or b is None else a - b for a, b in zip(r, br, strict=True)]
                for r, br in zip(table, base_table, strict=True)
            ]
            span = max((abs(v) for r in delta for v in r if v is not None), default=0.1) or 0.1
            draw(
                delta,
                diverging,
                -span,
                span,
                "by_domain_delta_vs_M0",
                f"change vs M0 by domain ({SPLIT})",
                lambda v: f"{v:+.2f}",
            )
    return paths
