"""Export aggregate experiment receipts to W&B without opening a training run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

from ktide.artifacts import read_json, sha256_json
from ktide.train.data import load_qa

B0 = {
    "evaluation_A_professor_judge": (
        "n",
        "mean_accuracy",
        "mean_relevance",
        "mean_constraints",
        "mean_total_average",
    ),
    "evaluation_B_rule_based": (
        "n",
        "word_limit_compliance",
        "sentence_limit_compliance",
        "both_limits_compliance",
        "empty_rate",
        "max_tokens_reached_rate",
        "han_rate",
        "mean_word_count",
        "max_word_count",
    ),
}
M0 = {
    "rubric": ("total", "accuracy", "relevance", "constraints"),
    "reference": ("accuracy", "score"),
    "rules": ("word_limit", "sentence_limit", "term_preservation", "han_rate"),
}


PROJECT = "ktide"
TRACKS = ("course", "research")
# group = experiment family. "controlled" (research 2x2, M1-M4) and "optimization"
# (assignment model) must never share a group.
GROUPS = ("baseline", "knowledge", "controlled", "optimization")
STAGES = ("data", "training", "evaluation")
# Remote runs that were deleted to be rebuilt. W&B does not reuse a deleted run ID, so the
# replacement gets a new ID derived from the old one. Only these runs may be deleted (--retire).
RETIRED_RUN_IDS = {
    # lecture-only QA build: held M1/M2 answer metrics from before the views were split;
    # W&B did not remove those summary keys, so the run is rebuilt from the local receipt.
    "6ba599ce30ecbe6e714bde52": 1,
}


@dataclass(frozen=True)
class Receipt:
    tracks: tuple[str, ...]
    group: str
    condition: str
    stage: str
    evaluation_phase: str
    source_id: str
    input_datasets: tuple[str, ...]
    output_datasets: tuple[str, ...]
    metrics: dict[str, int | float]

    def __post_init__(self):
        if not self.tracks or set(self.tracks) - set(TRACKS):
            raise ValueError(f"tracks must be a non-empty subset of {TRACKS}: {self.tracks}")
        if self.group not in GROUPS or self.stage not in STAGES:
            raise ValueError(f"unknown group or stage: {self.group}, {self.stage}")
        if self.group == "optimization" and "research" in self.tracks:
            raise ValueError("assignment optimization runs must not be tagged research")

    @property
    def project(self) -> str:
        return PROJECT

    @property
    def tags(self) -> list[str]:
        return sorted(self.tracks)

    @property
    def run_id(self) -> str:
        # Track membership is a tag, not part of the identity: a shared run exists once.
        base = sha256_json([self.stage, self.condition, self.source_id])[:24]
        revision = RETIRED_RUN_IDS.get(base)
        return base if revision is None else sha256_json([base, revision])[:24]

    @property
    def display_name(self) -> str:
        if self.condition == "B0":
            if self.source_id.endswith("_local-cpu-prelim"):
                return "B0 · Local CPU FP32 baseline"
            if self.source_id.endswith("_colab-official"):
                return "B0 · Colab CUDA FP16 baseline"
        names = {
            "M0": "M0 · Eval v1 pre-freeze baseline",
            "M1": "M1 · Training data (translated terms)",
            "M2": "M2 · Training data (English terms preserved)",
            "lecture-only": "Lecture-only QA build (shared by M1/M2)",
        }
        if self.condition.startswith("CKU-"):
            return self.condition + " · Knowledge dataset"
        return names.get(self.condition, self.condition)

    @property
    def config(self) -> dict:
        return {
            "schema_version": 2,
            "condition": self.condition,
            "stage": self.stage,
            "evaluation_phase": self.evaluation_phase,
            "input_datasets": list(self.input_datasets),
            "output_datasets": list(self.output_datasets),
        }


def dataset_version(label: str, *paths: Path) -> str:
    digests = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    return f"{label}@{sha256_json(digests)}"


def metric_fields(data: dict, keys, prefix: str) -> dict:
    result = {}
    for key in keys:
        value = data[key]
        if value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"Invalid numeric metric: {prefix}/{key}")
        result[f"{prefix}/{key}"] = value
    return result


def collect(root: Path) -> list[Receipt]:
    records = []
    for run in sorted((root / "runs/baseline/B0").glob("*/metrics.json")):
        source = read_json(run)
        metrics = {}
        for section, keys in B0.items():
            metrics.update(metric_fields(source[section], keys, section))
        version = dataset_version("course-baseline", run.with_name("questions.json"))
        records.append(
            Receipt(
                ("course",),
                "baseline",
                "B0",
                "evaluation",
                "preliminary",
                run.parent.name,
                (version,),
                (),
                metrics,
            )
        )

    for run in sorted((root / "runs/main/M0").glob("*/eval_metrics.json")):
        source = read_json(run)
        metrics = metric_fields(source["meta"], ("n_items", "repeats"), "meta")
        for section, keys in M0.items():
            for key in keys:
                summary = source[section][key]
                groups = [("all", summary["all"]["all"])]
                groups.extend(
                    (split, summary["split"][split])
                    for split in (
                        "dev",
                        "test_seen",
                        "test_unseen",
                    )
                    if split in summary["split"]
                )
                for split, values in groups:
                    metrics.update(metric_fields(values, ("n", "mean"), f"{section}/{key}/{split}"))
        version = dataset_version("eval-v1-prefreeze", run.with_name("questions.json"))
        records.append(
            Receipt(
                ("course", "research"),
                "baseline",
                "M0",
                "evaluation",
                "preliminary",
                run.parent.name,
                (version,),
                (),
                metrics,
            )
        )

    private = root / "data_private"
    parent = ()
    for variant in ("v1", "v2", "v2_1", "v3"):
        path = private / "knowledge" / f"cku_{variant}.jsonl"
        label = f"CKU-{variant.replace('_', '.')}"
        version = dataset_version(label, path)
        allowed = ("model_knowledge", "lecture", "external_reference", "slp_textbook")
        counts = Counter()
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                counts["records"] += 1
                for tags in json.loads(line)["basis"].values():
                    counts.update(f"basis/{tag}" for tag in tags if tag in allowed)
        records.append(
            Receipt(
                ("course", "research"),
                "knowledge",
                label,
                "data",
                "not_applicable",
                version,
                parent,
                (version,),
                dict(counts),
            )
        )

        parent = (version,)

    directory = private / "train/m1_lecture_only"
    coverage = read_json(directory / "coverage.json")
    qc = read_json(directory / "qc.json")
    version = dataset_version(
        "lecture-only",
        directory / "qa.jsonl",
        directory / "term_translations.json",
    )
    # The QA build is common to M1 and M2 and is recorded once. Each condition trains on a
    # different answer field, so each training view gets its own dataset version and run.
    metrics = metric_fields(
        coverage,
        (
            "qa_count",
            "eligible_concept_count",
            "concepts_with_qa",
            "concepts_without_qa_due_to_insufficient_evidence",
            "excluded_unseen_concept_count",
        ),
        "coverage",
    )
    metrics.update(metric_fields(qc, ("failure_count",), "qc"))
    records.append(
        Receipt(
            ("course", "research"),
            "controlled",
            "lecture-only",
            "data",
            "not_applicable",
            version,
            (),
            (version,),
            metrics,
        )
    )
    for condition, variant in (("M1", "translated"), ("M2", "preserved")):
        rows = load_qa([directory / "qa.jsonl"], variant)
        view = f"{condition}-train@" + sha256_json(
            [[row["question"], row["answer"]] for row in rows]
        )
        words = qc["mean_words"][f"answer_{variant}_ko"]
        view_metrics = {"train/examples": len(rows)}
        view_metrics.update(metric_fields({"mean_words": words}, ("mean_words",), "answer"))
        records.append(
            Receipt(
                ("course", "research"),
                "controlled",
                condition,
                "data",
                "not_applicable",
                view,
                (version,),
                (view,),
                view_metrics,
            )
        )
    return records


def mismatches(remote, receipt: Receipt) -> list[str]:
    placement = [
        name
        for name, expected, actual in (
            ("tags", receipt.tags, sorted(remote.tags)),
            ("group", receipt.group, remote.group),
            ("job_type", receipt.stage, remote.job_type),
        )
        if expected != actual
    ]
    return placement + [
        f"{section}:{key}"
        for section, expected, actual in (
            ("config", receipt.config, remote.config),
            ("summary", receipt.metrics, remote.summary),
        )
        for key, value in expected.items()
        if actual.get(key) != value
    ]


def verify(api, path: str, receipt: Receipt) -> None:
    # new runs can read back empty for a minute or more
    for delay in (0, 2, 4, 8, 16, 32, 64):
        sleep(delay)
        api.flush()
        remote = api.run(path)
        differences = mismatches(remote, receipt)
        if remote.name != receipt.display_name:
            differences.append("display_name")
        if not differences:
            return
    raise ValueError(f"W&B readback mismatch: {path} ({', '.join(differences)})")


def sync(receipts: list[Receipt], entity: str) -> None:
    import wandb

    api = wandb.Api(overrides={"base_url": "https://api.wandb.ai"}, timeout=20)
    if not api.api_key:
        raise ValueError("W&B credentials are unavailable")
    for receipt in receipts:
        path = f"{entity}/{receipt.project}/{receipt.run_id}"
        with TemporaryDirectory(prefix="ktide-wandb-") as scratch:
            settings = wandb.Settings(
                base_url="https://api.wandb.ai",
                mode="online",
                init_timeout=30,
                console="off",
                disable_code=True,
                disable_git=True,
                disable_job_creation=True,
                x_disable_meta=True,
                x_save_requirements=False,
                x_disable_stats=True,
                x_disable_machine_info=True,
            )
            with wandb.init(
                entity=entity,
                project=receipt.project,
                id=receipt.run_id,
                resume="allow",
                dir=scratch,
                name=receipt.display_name,
                job_type=receipt.stage,
                group=receipt.group,
                tags=receipt.tags,
                config=receipt.config,
                settings=settings,
            ) as run:
                if any(run.config.get(key) != value for key, value in receipt.config.items()):
                    raise ValueError(f"Existing W&B run has different metadata: {path}")
                run.tags = tuple(receipt.tags)  # resume keeps old tags unless reset
                if run.name != receipt.display_name:
                    run.name = receipt.display_name
                run.summary.update(receipt.metrics)
    # The SDK service can retain the empty read view from before a newly created run existed.
    wandb.teardown()
    api = wandb.Api(overrides={"base_url": "https://api.wandb.ai"}, timeout=20)
    for receipt in receipts:
        path = f"{entity}/{receipt.project}/{receipt.run_id}"
        verify(api, path, receipt)
        print(f"verified {path}", flush=True)


def retire(entity: str, run_ids: list[str], confirm=input) -> None:
    """Delete retired remote runs (listed in RETIRED_RUN_IDS) after an explicit 'yes'."""
    import wandb

    unknown = [run_id for run_id in run_ids if run_id not in RETIRED_RUN_IDS]
    if unknown:
        raise ValueError(f"not in RETIRED_RUN_IDS, refusing to delete: {unknown}")
    api = wandb.Api(overrides={"base_url": "https://api.wandb.ai"}, timeout=20)
    for run_id in run_ids:
        path = f"{entity}/{PROJECT}/{run_id}"
        try:
            run = api.run(path)
        except Exception:  # already deleted or never created
            print(f"absent {path}")
            continue
        answer = confirm(f"Permanently delete W&B run {path} ({run.name})? Type yes: ")
        if answer.strip() != "yes":
            print(f"kept {path}")
            continue
        run.delete()
        print(f"deleted {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--sync", action="store_true")
    parser.add_argument(
        "--retire",
        action="store_true",
        help="delete the remote runs listed in RETIRED_RUN_IDS (asks for each)",
    )
    parser.add_argument("--entity", default=os.environ.get("WANDB_ENTITY"))
    args = parser.parse_args()
    if (args.sync or args.retire) and not args.entity:
        parser.error("--sync/--retire need the destination --entity or WANDB_ENTITY")
    if args.retire:
        retire(args.entity, list(RETIRED_RUN_IDS))
    receipts = collect(args.root.resolve())
    if args.sync:
        sync(receipts, args.entity)
    else:
        for row in receipts:
            print(
                json.dumps(
                    {
                        "project": row.project,
                        "run_id": row.run_id,
                        "display_name": row.display_name,
                        "tags": row.tags,
                        "group": row.group,
                        "job_type": row.stage,
                        **row.config,
                        "metrics": row.metrics,
                    },
                    sort_keys=True,
                    allow_nan=False,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
