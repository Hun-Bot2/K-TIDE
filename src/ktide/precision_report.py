"""M1 training-precision comparison (BF16 pilot vs FP16 controlled), built only from run artifacts.

Writes
  report_course/generated/precision_comparison.md   (course report, private folder)
  paper/generated/precision_tables.tex              (paper appendix, aggregate numbers only)
Cells whose artifacts do not exist yet (e.g. LLM-judge files still being produced) are printed as
"pending"; re-run after scoring to fill them. Nothing here is a significance test, and the two runs
differ in GPU as well as precision, so differences cannot be attributed to precision alone.

Usage:
    uv run python -m ktide.precision_report
"""

from __future__ import annotations

import json
from pathlib import Path

from ktide.professor import REPO_ROOT

SPLIT = "during_development"
VERDICT = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}
ROWS = [
    ("Strict accuracy (correct only)", "reference", "accuracy", 3),
    ("Reference score (partial = 0.5)", "reference", "score", 3),
    ("Judge total (1-5)", "rubric", "total", 2),
    ("Judge accuracy (1-5)", "rubric", "accuracy", 2),
    ("Judge relevance (1-5)", "rubric", "relevance", 2),
    ("Judge constraints (1-5)", "rubric", "constraints", 2),
    ("30-word limit", "rules", "word_limit", 3),
    ("1-2 sentences", "rules", "sentence_limit", 3),
    ("Both length limits", "rules", "both_limits", 3),
    ("English term preservation", "rules", "term_preservation", 3),
    ("Polite register", "rules", "polite_rate", 3),
    ("Source mention", "rules", "source_mention_rate", 3),
    ("Chinese characters", "rules", "han_rate", 3),
]


def load(run_dir: Path) -> dict:
    out = {"dir": run_dir, "metrics": json.loads((run_dir / "eval_metrics.json").read_text())}
    out["answers"] = {
        p["question_id"]: p["answer"]
        for p in json.loads((run_dir / "predictions.json").read_text())
    }
    out["env"] = json.loads((run_dir / "environment.json").read_text())
    train = run_dir / "training"
    if (train / "train_config.json").is_file():
        out["train"] = json.loads((train / "train_config.json").read_text())
        out["log"] = json.loads((train / "train_log.json").read_text())
        export = train / "export_report.json"
        out["export"] = json.loads(export.read_text()) if export.is_file() else {}
    for name in (f"eval_ref_{SPLIT}_r1.json", "eval_ref_r1.json"):
        if (run_dir / name).is_file():
            out["ref"] = json.loads((run_dir / name).read_text())
            break
    return out


def runs(root: Path) -> dict[str, dict]:
    m1 = sorted((root / "runs/main/M1").glob("*/eval_metrics.json"))
    pick = {}
    for path in m1:
        cfg_path = path.parent / "training" / "train_config.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {}
        if cfg.get("precision") == "bf16":
            pick["M1 pilot (BF16)"] = path.parent
        elif cfg.get("precision") == "fp16" and cfg.get("study_phase") == "controlled":
            pick["M1 (FP16)"] = path.parent  # the latest controlled FP16 run
    base = sorted((root / "runs/main/M0").glob("*/eval_metrics.json"))[-1].parent
    return {"M0": load(base), **{k: load(v) for k, v in sorted(pick.items(), reverse=True)}}


def cell(metrics: dict, section: str, key: str):
    try:
        return metrics[section][key]["split"][SPLIT]
    except KeyError:
        return None


def paired(a: dict, b: dict) -> dict | None:
    if "ref" not in a or "ref" not in b:
        return None
    shared = [k for k in b["ref"] if k in a["ref"]]
    better = sum(VERDICT[b["ref"][k]["verdict"]] > VERDICT[a["ref"][k]["verdict"]] for k in shared)
    worse = sum(VERDICT[b["ref"][k]["verdict"]] < VERDICT[a["ref"][k]["verdict"]] for k in shared)
    return {
        "items": len(shared),
        "better": better,
        "same": len(shared) - better - worse,
        "worse": worse,
    }


def build(root: Path = REPO_ROOT) -> dict:
    data = runs(root)
    names = list(data)
    pilot, fp16 = data.get("M1 pilot (BF16)"), data.get("M1 (FP16)")
    shared = sorted(set(pilot["answers"]) & set(fp16["answers"])) if pilot and fp16 else []
    return {
        "names": names,
        "data": data,
        "identical": sum(pilot["answers"][k] == fp16["answers"][k] for k in shared),
        "shared": len(shared),
        "paired_fp16_vs_pilot": paired(pilot, fp16) if pilot and fp16 else None,
        "paired_vs_m0": {n: paired(data["M0"], data[n]) for n in names if n != "M0"},
    }


def fmt(c, digits):
    return "pending" if c is None else f"{c['mean']:.{digits}f}"


def markdown(r: dict) -> str:
    d, names = r["data"], r["names"]
    lines = [
        "# M1 학습 정밀도 비교: BF16 pilot vs FP16 통제 실험",
        "",
        "`uv run python -m ktide.precision_report`가 결과 파일에서 생성한다. "
        "`pending`은 아직 결과 파일이 없는 칸이다(채점 후 다시 생성).",
        "",
        "## 실행 조건",
        "",
        "| 항목 | " + " | ".join(n for n in names if n != "M0") + " |",
        "|---|" + "---:|" * (len(names) - 1),
    ]
    trained = [d[n] for n in names if n != "M0"]

    def row(label, fn):
        lines.append(f"| {label} | " + " | ".join(str(fn(x)) for x in trained) + " |")

    row("학습 GPU", lambda x: x["train"]["gpu"])
    row("학습 정밀도", lambda x: x["train"]["precision"].upper())
    row("데이터 버전", lambda x: x["train"]["dataset_version"][:22] + "…")
    row("학습/검증 예시", lambda x: f"{x['train']['n_train']} / {x['train']['n_val']}")
    row("LoRA r / α / dropout", lambda x: "{r} / {alpha} / {dropout}".format(**x["train"]["lora"]))
    row(
        "lr / epochs / 유효 배치",
        lambda x: "{lr} / {epochs:g} / {effective_batch}".format(**x["train"]["optim"]),
    )
    row("seed", lambda x: x["train"]["seed"])
    row("optimizer step", lambda x: max(e.get("step", 0) for e in x["log"]))
    row(
        "logging 간격(step)",
        lambda x: (lambda s: s[1] - s[0] if len(s) > 1 else "-")(
            [e["step"] for e in x["log"] if "loss" in e]
        ),
    )
    row("학습 시간(초)", lambda x: x["train"]["train_seconds"])
    row(
        "최종 train_loss(전체 평균)",
        lambda x: round(next(e["train_loss"] for e in x["log"] if "train_loss" in e), 4),
    )
    row(
        "검증 손실(epoch별)",
        lambda x: ", ".join(f"{e['eval_loss']:.4f}" for e in x["log"] if "eval_loss" in e),
    )
    row(
        "FP16 점검(NaN/Inf, scale 감소)",
        lambda x: (
            lambda n: (
                f"{n['train/nonfinite_steps']}, {n['train/grad_scale_decreases']}"
                if n
                else "기록 없음(도입 전)"
            )
        )(x["train"].get("numerics")),
    )
    row(
        "내보내기 unpack / greedy",
        lambda x: (
            f"{x['export'].get('professor_unpack_model')} / {x['export'].get('effective_generation', {}).get('do_sample') is False}"
        ),
    )
    row("답변 생성 GPU", lambda x: x["env"].get("gpu"))
    row("생성 문항 수", lambda x: len(x["answers"]))
    lines += [
        "",
        f"- 두 run에 공통인 {r['shared']}문항 중 답변 문자열이 완전히 같은 문항: **{r['identical']}**",
        "",
    ]

    lines += [
        f"## 지표 ({SPLIT}, 채점 1회)",
        "",
        "| 지표 | " + " | ".join(names) + " |",
        "|---|" + "---:|" * len(names),
    ]
    for label, section, key, digits in ROWS:
        lines.append(
            f"| {label} | "
            + " | ".join(fmt(cell(d[n]["metrics"], section, key), digits) for n in names)
            + " |"
        )
    n_note = {n: (cell(d[n]["metrics"], "rules", "word_limit") or {}).get("n") for n in names}
    lines += ["", f"- 문항 수(n): {n_note}", "", "## 문항별 정답 기반 판정 변화", ""]
    for n, p in r["paired_vs_m0"].items():
        lines.append(
            f"- {n} vs M0: "
            + (
                "pending"
                if p is None
                else f"개선 {p['better']}, 유지 {p['same']}, 하락 {p['worse']} (n={p['items']})"
            )
        )
    p = r["paired_fp16_vs_pilot"]
    lines.append(
        "- FP16 vs BF16 pilot: "
        + (
            "pending"
            if p is None
            else f"개선 {p['better']}, 유지 {p['same']}, 하락 {p['worse']} (n={p['items']})"
        )
    )
    lines += [
        "",
        "## 해석 범위",
        "",
        "- 두 M1 run은 정밀도뿐 아니라 **학습 GPU와 답변 생성 GPU도 다르다**"
        "(T4 vs RTX 5000 Ada). 차이를 정밀도 효과로 단정할 수 없다.",
        "- 채점은 1회이며 유의성 검정을 하지 않았다. 판정 흔들림(B0에서 확인)을 고려해야 한다.",
        "- pilot은 420문항 전체에 답했고 FP16 run은 during_development 156문항에만 답했다. 비교는 공통 156문항으로 한다.",
        "- pilot의 logging 간격은 5 step, FP16 run은 1 step이다(기록 빈도만 다르고 학습에는 영향이 없다).",
        "- 이후 M1~M4 통제 실험은 FP16, 같은 GPU 종류로 통일한다. pilot은 결과 비교에서 제외하고 기록으로만 보존한다.",
    ]
    return "\n".join(lines) + "\n"


def latex(r: dict) -> str:
    d, names = r["data"], r["names"]
    esc = lambda s: s.replace("_", r"\_").replace("%", r"\%")  # noqa: E731
    trained = [n for n in names if n != "M0"]
    lines = [
        "% generated by ktide.precision_report; do not edit by hand",
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\begin{tabular}{l" + "r" * len(trained) + "}",
        r"\toprule",
        " & " + " & ".join(esc(n) for n in trained) + r" \\",
        r"\midrule",
    ]

    def row(label, fn):
        lines.append(esc(label) + " & " + " & ".join(esc(str(fn(d[n]))) for n in trained) + r" \\")

    row("Training GPU", lambda x: x["train"]["gpu"].replace("NVIDIA ", ""))
    row("Training precision", lambda x: x["train"]["precision"].upper())
    row("Training time (s)", lambda x: x["train"]["train_seconds"])
    row(
        "Validation loss (epoch 3)",
        lambda x: f"{[e['eval_loss'] for e in x['log'] if 'eval_loss' in e][-1]:.4f}",
    )
    row(
        "Non-finite steps / scale drops",
        lambda x: (
            lambda n: (
                f"{n['train/nonfinite_steps']} / {n['train/grad_scale_decreases']}"
                if n
                else "not logged"
            )
        )(x["train"].get("numerics")),
    )
    row("Generation GPU", lambda x: x["env"].get("gpu", "").replace("NVIDIA ", ""))
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\caption{Two M1 training runs with the same data, hyperparameters and seed. "
        r"They differ in training precision and GPU. Identical answers on the "
        + f"{r['shared']} shared items: {r['identical']}."
        + "}",
        r"\label{tab:precision-setup}",
        r"\end{table}",
        "",
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\begin{tabular}{l" + "r" * len(names) + "}",
        r"\toprule",
        "Metric & " + " & ".join(esc(n) for n in names) + r" \\",
        r"\midrule",
    ]
    for label, section, key, digits in ROWS:
        lines.append(
            esc(label)
            + " & "
            + " & ".join(fmt(cell(d[n]["metrics"], section, key), digits) for n in names)
            + r" \\"
        )
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\caption{Development split, one judge pass, no significance test. "
        r"``pending'' marks scores not yet computed.}",
        r"\label{tab:precision-metrics}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    r = build()
    md = REPO_ROOT / "report_course" / "generated" / "precision_comparison.md"
    tex = REPO_ROOT / "paper" / "generated" / "precision_tables.tex"
    for path, text in ((md, markdown(r)), (tex, latex(r))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print("wrote", path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
