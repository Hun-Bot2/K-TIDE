"""Evaluation A — professor-compatible LLM Judge.

The judge receives exactly the professor's EVAL_SYSTEM_PROMPT plus the ``judge_input.txt`` text
([질문]/[답변] pairs). No reference answers, lecture material, model names or training details are
given, mirroring the professor's setup. All questions of a run are judged in one call, as in the
notebook example.

Backends:
    codex   — ``codex exec`` (runs headless, isolated empty working dir, read-only sandbox)
    claude  — ``claude -p`` (run from a normal terminal; cannot be nested inside Claude Code)
    manual  — writes the full prompt to judge_prompt.txt; paste the judge's reply into
              judge_raw_response.txt and re-run with ``--parse-only``.

Usage:
    uv run python -m ktide.judge runs/baseline/B0/<run_id> --backend codex --model gpt-6.2-sol
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from statistics import mean

from ktide.artifacts import JudgeResult, JudgeScores, read_json, write_json
from ktide.metrics import aggregate_rule_metrics
from ktide.professor import load_professor_notebook

CRITERIA = ("accuracy", "relevance", "constraints")


def build_prompt(eval_system_prompt: str, judge_input: str) -> str:
    return f"{eval_system_prompt.rstrip()}\n\n{judge_input.strip()}\n"


def call_codex(prompt: str, model: str | None, reasoning: str | None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "last.txt"
        cmd = [
            "codex",
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-rules",
            "-C",
            tmp,
            "-o",
            str(out_file),
        ]
        if model:
            cmd += ["-m", model]
        if reasoning:
            cmd += ["-c", f'model_reasoning_effort="{reasoning}"']
        cmd.append("-")
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, check=False)
        text = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
        return {
            "backend": "codex",
            "command": cmd[:-1],
            "returncode": proc.returncode,
            "text": text,
            "stderr_tail": proc.stderr[-4000:],
        }


def call_claude(prompt: str, system_prompt: str, judge_input: str, model: str | None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--system-prompt",
            system_prompt,
            "--tools",
            "",
        ]
        if model:
            cmd += ["--model", model]
        proc = subprocess.run(
            cmd, input=judge_input, capture_output=True, text=True, cwd=tmp, check=False
        )
        text = proc.stdout
        meta = None
        try:
            meta = json.loads(proc.stdout)
            text = meta.get("result", "")
        except json.JSONDecodeError:
            pass
        return {
            "backend": "claude",
            "command": cmd[:4] + ["<EVAL_SYSTEM_PROMPT>"] + cmd[5:],
            "returncode": proc.returncode,
            "text": text,
            "cli_meta": meta,
            "stderr_tail": proc.stderr[-4000:],
        }


def extract_json_array(text: str) -> list:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        raise ValueError("no JSON array in judge response")
    return json.loads(text[start : end + 1])


def parse_results(items: list, predictions: list[dict]) -> list[JudgeResult]:
    by_num = {}
    for it in items:
        n = int(it["question_number"])
        if n in by_num:
            raise ValueError(f"duplicate question_number {n} in judge response")
        by_num[n] = it
    expected = [p["question_number"] for p in predictions]
    if sorted(by_num) != expected:
        raise ValueError(f"judge returned numbers {sorted(by_num)}, expected {expected}")
    results = []
    for p in predictions:
        it = by_num[p["question_number"]]
        scores = JudgeScores(**{k: it["scores"].get(k) for k in CRITERIA})
        vals = [getattr(scores, k) for k in CRITERIA]
        avg = round(mean(vals), 4) if all(v is not None for v in vals) else None
        results.append(
            JudgeResult(
                question_number=p["question_number"],
                question_id=p["question_id"],
                scores=scores,
                total_average=avg,
                judge_reported_average=it.get("total_average"),
                feedback=it.get("feedback"),
            )
        )
    return results


def summarize(results: list[JudgeResult]) -> dict:
    out = {"n": len(results)}
    for k in CRITERIA:
        vals = [getattr(r.scores, k) for r in results if getattr(r.scores, k) is not None]
        out[f"mean_{k}"] = round(mean(vals), 4) if vals else None
    tot = [r.total_average for r in results if r.total_average is not None]
    out["mean_total_average"] = round(mean(tot), 4) if tot else None
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--backend", choices=["codex", "claude", "manual"], default="codex")
    ap.add_argument("--model", default=None)
    ap.add_argument("--reasoning", default=None, help="codex model_reasoning_effort")
    ap.add_argument(
        "--parse-only", action="store_true", help="parse an existing judge_raw_response.json / .txt"
    )
    args = ap.parse_args(argv)

    run: Path = args.run_dir
    preds = read_json(run / "predictions.json")
    judge_input = (run / "judge_input.txt").read_text(encoding="utf-8")
    nb = load_professor_notebook()
    prompt = build_prompt(nb.eval_system_prompt, judge_input)

    raw_json, raw_txt = run / "judge_raw_response.json", run / "judge_raw_response.txt"
    if args.parse_only:
        raw = (
            read_json(raw_json)
            if raw_json.exists()
            else {"backend": "manual", "text": raw_txt.read_text(encoding="utf-8")}
        )
    elif args.backend == "manual":
        (run / "judge_prompt.txt").write_text(prompt, encoding="utf-8")
        print(f"Wrote {run / 'judge_prompt.txt'}; paste reply into {raw_txt} then --parse-only")
        return
    else:
        if raw_json.exists():
            raise FileExistsError(f"{raw_json} exists; judge results are not overwritten")
        if shutil.which(args.backend) is None:
            raise RuntimeError(f"{args.backend} CLI not found")
        raw = (
            call_codex(prompt, args.model, args.reasoning)
            if args.backend == "codex"
            else call_claude(prompt, nb.eval_system_prompt, judge_input, args.model)
        )
        raw |= {
            "model": args.model,
            "reasoning": args.reasoning,
            "timestamp": dt.datetime.now().astimezone().isoformat(),
        }
        write_json(raw_json, raw)

    results = parse_results(extract_json_array(raw["text"]), preds)
    write_json(run / "judge_results.json", [r.model_dump() for r in results])

    rule_rows = read_json(run / "rule_metrics.json") if (run / "rule_metrics.json").exists() else []
    metrics = {
        "evaluation_A_professor_judge": summarize(results)
        | {
            "judge_backend": raw.get("backend"),
            "judge_model": raw.get("model"),
            "judge_reasoning": raw.get("reasoning"),
        },
        "evaluation_B_rule_based": aggregate_rule_metrics(rule_rows),
    }
    write_json(run / "metrics.json", metrics)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
