"""Export aggregate experiment receipts to W&B without opening a training run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

from ktide.artifacts import read_json, sha256_json
from ktide.compare import baseline_dir, deltas, heatmaps, paired
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
    "rules": (
        "word_limit",
        "sentence_limit",
        "both_limits",
        "term_preservation",
        "han_rate",
        "polite_rate",
        "source_mention_rate",
    ),
}


PROJECT = "K-TIDE"
SLICE_SPLIT = "during_development"
EVAL_SPLITS = ("during_development", "test_seen", "test_unseen")
BREAKDOWN_METRICS = {
    ("reference", "accuracy"),
    ("rubric", "total"),
    ("rules", "word_limit"),
    ("rules", "term_preservation"),
}
TRACKS = ("course", "research")
# group = experiment family. "controlled" (research 2x2, M1-M4) and "optimization"
# (assignment model) must never share a group.
GROUPS = ("baseline", "knowledge", "controlled", "optimization")
STAGES = ("data", "training", "evaluation")
# config keys that define what a run is; other config keys may be added to an existing run
IDENTITY_KEYS = ("condition", "stage", "evaluation_phase", "input_datasets", "output_datasets")
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
    # training hyperparameters (config) and the logged loss curve (W&B history); not identity
    params: dict = field(default_factory=dict, compare=False)
    history: tuple = field(default=(), compare=False)
    # links the training run and the evaluation runs of one experiment (condition/run dir)
    experiment_id: str | None = None
    # a run logged live (e.g. by the Trainer on Colab) keeps its W&B id; receipts then update it
    live_run_id: str | None = field(default=None, compare=False)
    # baseline (M0) | pilot (BF16 M1, kept as a pilot experiment) | controlled (FP16 M1-M4) | ...
    study_phase: str | None = None
    # aggregate figures logged once per content hash (W&B media), e.g. domain heatmaps
    images: dict = field(default_factory=dict, compare=False)

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
        if self.live_run_id:
            return self.live_run_id
        # Track membership is a tag, not part of the identity: a shared run exists once.
        base = sha256_json([self.stage, self.condition, self.source_id])[:24]
        revision = RETIRED_RUN_IDS.get(base)
        return base if revision is None else sha256_json([base, revision])[:24]

    @property
    def display_name(self) -> str:
        label = ""
        for marker in ("colab-t4-", "gpu-"):
            if marker in self.source_id:
                label = self.source_id.rsplit(marker, 1)[-1]
                break
        suffix = f" ({label})" if label else ""
        if self.stage == "training":
            return f"{self.condition} · LoRA training{suffix}"
        if self.stage == "evaluation" and self.condition not in ("B0", "M0"):
            return f"{self.condition} · Eval v1 pre-freeze{suffix}"
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
        return (
            {
                "schema_version": 2,
                "condition": self.condition,
                "stage": self.stage,
                "evaluation_phase": self.evaluation_phase,
                "input_datasets": list(self.input_datasets),
                "output_datasets": list(self.output_datasets),
            }
            | ({"params": self.params} if self.params else {})
            | ({"experiment_id": self.experiment_id} if self.experiment_id else {})
            | ({"study_phase": self.study_phase} if self.study_phase else {})
        )


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


def placement(train_config: dict) -> tuple[tuple[str, ...], str]:
    """Course optimization runs stay out of the research reports (see ADR 0002)."""
    if train_config.get("track") == "course":
        return ("course",), "optimization"
    return ("course", "research"), "controlled"


def study_phase(condition: str, train_config: dict | None) -> str:
    """M0 = baseline; runs logged before phases existed are the BF16 pilot (M1 data-v1)."""
    if condition == "M0" or not train_config:
        return "baseline"
    if train_config.get("study_phase"):
        return train_config["study_phase"]
    return "pilot" if train_config.get("precision") == "bf16" else "controlled"


def experiment_id(condition: str, run_name: str, train_config: dict | None) -> str:
    """One id for a training run and its evaluations: the live W&B run id when there is one."""
    live = (train_config or {}).get("wandb_run_id")
    return f"{condition}/{live or run_name}"


def collect_runs(root: Path) -> list[Receipt]:
    """Evaluation and training runs found under runs/ (absent folders are skipped)."""
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

    for run in sorted((root / "runs/main").glob("M[0-4]/*/eval_metrics.json")):
        condition = run.parent.parent.name
        training = run.parent / "training" / "train_config.json"
        train_config = read_json(training) if training.is_file() else None
        trained_on = (train_config["dataset_version"],) if train_config else ()
        if condition != "M0" and not trained_on:
            raise ValueError(f"{run.parent}: evaluation without training/train_config.json")
        source = read_json(run)
        metrics = metric_fields(source["meta"], ("n_items", "repeats"), "meta")
        if source["meta"].get("n_judged") is not None:
            metrics.update(metric_fields(source["meta"], ("n_judged",), "meta"))
        for section, keys in M0.items():
            for key in keys:
                if section not in source or key not in source[section]:
                    continue
                summary = source[section][key]
                groups = [("all", summary["all"]["all"])]
                groups.extend(
                    (split, summary["split"][split])
                    for split in EVAL_SPLITS
                    if split in summary.get("split", {})
                )
                for split, values in groups:
                    metrics.update(metric_fields(values, ("n", "mean"), f"{section}/{key}/{split}"))
                # error-analysis slices (aggregates only) for the headline metrics
                if (section, key) in BREAKDOWN_METRICS:
                    for facet in ("domain", "question_type", "term_form"):
                        for category, values in summary.get(facet, {}).items():
                            if category in ("None", "null"):
                                continue
                            metrics[f"by_{facet}/{section}/{key}/{category}"] = values["mean"]
        version = dataset_version("eval-v1-prefreeze", run.with_name("questions.json"))
        environment = run.with_name("environment.json")
        params = {}
        if environment.is_file():
            env = read_json(environment)
            params["generation_env"] = {
                k: env.get(k)
                for k in (
                    "python",
                    "torch",
                    "transformers",
                    "accelerate",
                    "safetensors",
                    "huggingface_hub",
                    "tokenizers",
                    "gpu",
                    "cuda",
                    "device",
                )
            }
        if train_config and train_config.get("track") == "smoke":
            continue
        if source.get("slices"):
            for facet in ("term_form", "domain"):
                for metric_key in ("rules/term_preservation", "reference/accuracy"):
                    for category, values in (
                        source["slices"].get(metric_key, {}).get(facet, {}).items()
                    ):
                        if category not in ("None", "null"):
                            metrics[f"{SLICE_SPLIT}/by_{facet}/{metric_key}/{category}"] = values[
                                "mean"
                            ]
        images = {}
        base_dir = baseline_dir(root)
        base = read_json(base_dir / "eval_metrics.json") if base_dir else None
        if condition != "M0" and base:
            metrics.update(deltas(source, base))
            metrics.update(paired(run.parent, base_dir))
        try:
            images = {
                f"heatmap/{name}": path
                for name, path in heatmaps(
                    source,
                    base,
                    f"{condition} · {study_phase(condition, train_config)}",
                    run.parent / "wandb_media",
                ).items()
            }
        except ImportError:  # matplotlib is a dev dependency; figures are optional
            images = {}
        tracks, group = (
            placement(train_config) if train_config else (("course", "research"), "baseline")
        )
        records.append(
            Receipt(
                tracks,
                group,
                condition,
                "evaluation",
                "preliminary",
                run.parent.name,
                (version, *trained_on),
                (),
                metrics,
                params,
                experiment_id=experiment_id(condition, run.parent.name, train_config)
                if train_config
                else None,
                study_phase=study_phase(condition, train_config),
                images=images,
            )
        )

    for config_path in sorted((root / "runs/main").glob("M[1-4]/*/training/train_config.json")):
        config = read_json(config_path)
        if config.get("track") == "smoke" or config.get("status", "finished") != "finished":
            continue
        log = read_json(config_path.with_name("train_log.json"))
        losses = [e for e in log if "loss" in e]
        evals = [e for e in log if "eval_loss" in e]
        metrics = metric_fields(
            config, ("n_train", "n_val", "train_seconds", "trainable_params"), "train"
        )
        for key, number in (config.get("numerics") or {}).items():
            if number is not None:
                metrics[key] = number
        if losses:
            metrics["train/final_loss"] = losses[-1]["loss"]
        if evals:
            metrics["train/final_eval_loss"] = evals[-1]["eval_loss"]
        # Trainer log -> the key names the Trainer's W&B callback uses for live runs
        names = {
            "loss": "train/loss",
            "learning_rate": "train/learning_rate",
            "grad_norm": "train/grad_norm",
            "epoch": "train/epoch",
            "eval_loss": "eval/loss",
        }
        history = tuple(
            {"train/global_step": e["step"], **{names[k]: e[k] for k in names if k in e}}
            for e in log
            if "step" in e and ("loss" in e or "eval_loss" in e)
        )
        params = {
            "lora": config["lora"],
            "optim": config["optim"],
            "max_len": config["max_len"],
            "seed": config["seed"],
            "precision": config["precision"],
            "gpu": config["gpu"],
            "variant": config["variant"],
            "base_revision": config["revision"],
        }
        for key in ("bundle", "versions", "hf_dataset_revision", "tokenizer_revision"):
            if key in config:
                params[key] = config[key]
        export_path = config_path.with_name("export_report.json")
        if export_path.is_file():
            export = read_json(export_path)
            generation = export.get("effective_generation", {})
            metrics["export/professor_unpack_model_ok"] = int(
                export.get("professor_unpack_model") == "ok"
            )
            metrics["export/greedy"] = int(generation.get("do_sample") is False)
            metrics["export/max_new_tokens"] = generation.get("max_new_tokens", 0)
            if "bytes" in export:
                metrics["export/zip_bytes"] = export["bytes"]
            metrics["export/base_files_identical"] = len(export.get("base_files_identical", []))
            if "sha256" in export:
                params["export_sha256"] = export["sha256"]
        run_name = config_path.parent.parent.name
        tracks, group = placement(config)
        records.append(
            Receipt(
                tracks,
                group,
                config["condition"],
                "training",
                "not_applicable",
                run_name,
                (config["dataset_version"],),
                (),
                metrics,
                params,
                history,
                experiment_id=experiment_id(config["condition"], run_name, config),
                live_run_id=config.get("wandb_run_id"),
                study_phase=study_phase(config["condition"], config),
            )
        )
    return records


def collect_data(root: Path) -> list[Receipt]:
    """Dataset build receipts from data_private/ (CKU versions, lecture-only QA)."""
    records = []
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


def collect(root: Path) -> list[Receipt]:
    return collect_runs(root) + collect_data(root)


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
    history = []
    if receipt.history and not receipt.live_run_id and hasattr(remote, "scan_history"):
        logged = sum(1 for _ in remote.scan_history(keys=["train/global_step"]))
        if logged < len(receipt.history):
            history = [f"history:{logged}/{len(receipt.history)}"]
    return (
        placement
        + history
        + [
            f"{section}:{key}"
            for section, expected, actual in (
                ("config", receipt.config, remote.config),
                ("summary", receipt.metrics, remote.summary),
            )
            for key, value in expected.items()
            if not same(actual.get(key), value)
        ]
    )


def same(actual, expected) -> bool:
    """Nested dicts match when every expected key matches (a live run may carry extra keys)."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(same(actual.get(k), v) for k, v in expected.items())
    return actual == expected


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
                identity = {k: receipt.config[k] for k in IDENTITY_KEYS}
                if any(run.config.get(k, v) != v for k, v in identity.items()):
                    raise ValueError(f"Existing W&B run has different identity: {path}")
                run.config.update(receipt.config, allow_val_change=True)
                run.tags = tuple(receipt.tags)  # resume keeps old tags unless reset
                if run.name != receipt.display_name:
                    run.name = receipt.display_name
                if receipt.history and run.starting_step == 0:
                    # same x-axis as the Trainer's W&B callback
                    run.define_metric("train/global_step")
                    run.define_metric("*", step_metric="train/global_step", step_sync=True)
                    for entry in receipt.history:
                        run.log(dict(entry))
                for key, path in receipt.images.items():
                    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    if run.summary.get(f"{key}_sha256") != digest:
                        run.log({key: wandb.Image(str(path))})
                        run.summary[f"{key}_sha256"] = digest
                run.summary.update(receipt.metrics)
    # The SDK service can retain the empty read view from before a newly created run existed.
    wandb.teardown()
    api = wandb.Api(overrides={"base_url": "https://api.wandb.ai"}, timeout=20)
    for receipt in receipts:
        path = f"{entity}/{receipt.project}/{receipt.run_id}"
        verify(api, path, receipt)
        print(f"verified {path}", flush=True)


DEFAULT_ENTITY = "hun-bot"


def record(match=None, root: Path | None = None, reason: str = "") -> bool:
    """Best-effort W&B record after a pipeline step (local results are already written).

    Syncs the receipts selected by `match` (a predicate on Receipt). Never raises: on any failure
    (no network, no login, private data absent) it prints how to retry and returns False.
    Disable with KTIDE_WANDB=0.
    """
    if os.environ.get("KTIDE_WANDB", "1") == "0":
        return False
    entity = os.environ.get("WANDB_ENTITY", DEFAULT_ENTITY)
    try:
        from ktide.professor import REPO_ROOT

        receipts = [r for r in collect((root or REPO_ROOT).resolve()) if match is None or match(r)]
        if not receipts:
            return False
        sync(receipts, entity)
        return True
    except Exception as error:  # noqa: BLE001 - recording must never break the pipeline
        print(
            f"[ktide] W&B record skipped{f' ({reason})' if reason else ''}: "
            f"{type(error).__name__}: {str(error)[:200]}\n"
            f"[ktide] local results are kept; retry: uv run python -m ktide.tracking --sync "
            f"--entity {entity}"
        )
        return False


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
