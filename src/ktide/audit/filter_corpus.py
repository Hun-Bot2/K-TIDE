"""Prepare a conservative, source-linked corpus for local exclusion review."""

import argparse
import hashlib
import json
import random
import re
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory

from ktide.audit.index_figures import index_figures, raster_occurrences
from ktide.knowledge.extract import write_json
from ktide.knowledge.visual import load

SEED = 20261125
TEXT_THRESHOLD = 0.92
IMAGE_DISTANCE = 4


def identity(record):
    source = record["source"]
    return source["file"], source["page"]


def signature(raw):
    match = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", raw)
    width, height = map(int, match.groups())
    pixels = raw[match.end() :]
    pixels = memoryview(pixels)
    rows = []
    for y in range(8):
        start = y * (height - 1) // 7 * width
        offsets = [(start + x * (width - 1) // 8) * 3 for x in range(9)]
        rows.append([sum(pixels[offset : offset + 3]) for offset in offsets])
    bits = [left > right for row in rows for left, right in zip(row, row[1:], strict=False)]
    difference_hash = sum(bit << i for i, bit in enumerate(bits))
    return hashlib.sha256(raw).hexdigest(), difference_hash


def render_file(root, directory, file, serial):
    prefix = directory / str(serial)
    pdf = (root / file).resolve()
    if not pdf.is_relative_to((root / "NLP").resolve()) or pdf.suffix.lower() != ".pdf":
        raise ValueError("Invalid lecture PDF")
    result = subprocess.run(
        ["pdftoppm", "-scale-to", "1200", str(pdf), str(prefix)],
        capture_output=True,
        check=True,
    )
    info = subprocess.run(["pdfinfo", "-isodates", str(pdf)], check=True, capture_output=True)
    match = re.search(rb"^ModDate:\s*(.+)$", info.stdout, re.MULTILINE)
    try:
        modified = datetime.fromisoformat(match[1].decode()).timestamp() if match else 0
    except ValueError:
        modified = 0
    images = {
        int(p.stem.rsplit("-", 1)[1]): signature(p.read_bytes())
        for p in directory.glob(f"{serial}-*.ppm")
    }
    return file, modified, images, bool(result.stderr)


def grams(text):
    return {text[i : i + 4] for i in range(len(text) - 3)}


def write_jsonl(path, rows):
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False), file=stream)
    temp.replace(path)


def prepare(root):
    private = root / "data_private"
    audit, extracted = private / "audit", private / "extracted"
    inventory = load(audit / "inventory.json")
    base = load(audit / "p2_corpus_draft.json")
    lecture = load(private / "knowledge/lecture_pages.json")
    labels = {
        (*identity(r), r["sha256"]): r["label"] for r in load(audit / "page_labels.json")["labels"]
    }
    manual_path = audit / "structural_p2d0.json"
    structural = (
        {identity(r): r["reason"] for r in load(manual_path)["pages"]}
        if (manual_path.exists())
        else {}
    )
    current_pages = {identity(r): r for r in base["pages"]}
    pdfs = {r["source"]["file"]: r for r in inventory["files"]}
    # Include original user exclusions in the audit, even if the P2 draft omitted them.
    for file, item in pdfs.items():
        pdf = root / file
        with pdf.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise ValueError(f"PDF checksum differs: {file}")
        for page in item["pages"]:
            key = identity(page)
            if (*key, item["sha256"]) in labels:
                current_pages.setdefault(key, {"source": page["source"], "sha256": item["sha256"]})
    text = {identity(r): re.sub(r"\s+", "", r["text"].casefold()) for r in lecture}
    files = sorted({file for file, _ in current_pages})
    with TemporaryDirectory(dir=extracted, prefix="dedupe-") as temporary:
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [
                pool.submit(render_file, root, Path(temporary), f, n) for n, f in enumerate(files)
            ]
            rendering = {
                f: (modified, images, warning)
                for f, modified, images, warning in (job.result() for job in jobs)
            }
    decisions = {}
    images = {}
    groups = defaultdict(list)
    for key, page in sorted(current_pages.items()):
        human = labels.get((*key, page["sha256"]))
        row = {
            **page,
            "decision": human or "keep",
            "reason": "user_label" if human else None,
            "duplicate_of": None,
            "similarity": None,
            "method": "manual" if human else "image",
            "skip_regions": [],
            "needs_human_review": False,
        }
        decisions[key] = row
        if human == "exclude":
            continue
        if not human and key in structural:
            row.update(decision="exclude", reason=structural[key], method="manual")
            continue
        file, number = key
        images[key] = rendering[file][1][number]
        groups[(images[key][0], text.get(key, ""))].append(key)

    def rank(key):
        file, _ = key
        return (
            labels.get((*key, current_pages[key]["sha256"])) == "keep",
            len(text.get(key, "")),
            rendering[file][0],
            pdfs[file]["page_count"],
            key,
        )

    alignment = defaultdict(list)
    for group in groups.values():
        representative = max(group, key=rank)
        for key in group:
            if key == representative:
                continue
            row = decisions[key]
            if key[0] != representative[0]:
                pair = tuple(sorted((key[0], representative[0])))
                first, second = (
                    (key, representative) if key[0] == pair[0] else (representative, key)
                )
                alignment[pair].append([first[1], second[1]])
            if row["reason"] == "user_label":
                continue
            row.update(
                decision="exclude",
                reason="duplicate" if key[0] != representative[0] else "repeated_slide",
                duplicate_of=decisions[representative]["source"],
                similarity=1.0,
            )

    pending = {}
    retained = [key for key in images if decisions[key]["decision"] == "keep"]
    tokens = {key: grams(text.get(key, "")) for key in retained if len(text.get(key, "")) >= 120}
    for left, right in combinations(retained, 2):
        if left in tokens and right in tokens:
            a, b = tokens[left], tokens[right]
            if min(len(a), len(b)) < TEXT_THRESHOLD * max(len(a), len(b)):
                continue
            score = len(a & b) / len(a | b)
            if score < TEXT_THRESHOLD:
                continue
            method = "text"
        else:
            distance = (images[left][1] ^ images[right][1]).bit_count()
            if distance > IMAGE_DISTANCE or images[left][1] in {0, 2**64 - 1}:
                continue
            score, method = 1 - distance / 64, "image"
        key, other = sorted((left, right), key=rank)
        if decisions[key]["reason"] == "user_label":
            continue
        if key not in pending or score > pending[key][0]:
            pending[key] = score, method, other

    # Inspect only representatives of similar groups in the UI. Retain every uncertain page.
    review = []
    used_pairs = set()
    for key, (score, method, other) in sorted(pending.items(), key=lambda item: -item[1][0]):
        pair = tuple(sorted((key[0], other[0])))
        if pair in used_pairs:
            continue
        used_pairs.add(pair)
        row = decisions[key]
        row.update(needs_human_review=True, similarity=score, method=method)
        review.append(
            {
                **current_pages[key],
                "comparison": current_pages[other]["source"],
                "question": "비슷한 페이지와 비교해 별도의 설명이나 도식이 있는지 확인해 주세요.",
            }
        )

    files_kept = defaultdict(set)
    for (file, number), row in decisions.items():
        if row["decision"] == "keep":
            files_kept[file].add(number)
    with TemporaryDirectory(dir=extracted, prefix="figures-") as temporary:
        grouped = raster_occurrences(root, Path(temporary), files_kept)
    figures = index_figures(grouped, rank)
    for figure in figures:
        for occurrence in figure["occurrences"]:
            key = occurrence["file"], occurrence["page"]
            if key != identity({"source": figure["representative"]}):
                decisions[key]["skip_regions"].append(
                    {
                        "bbox": occurrence["bbox"],
                        "reason": "repeated_figure",
                        "figure_id": figure["figure_id"],
                    }
                )
    expected = {
        tuple(sorted(s["file"] for s in pair["sources"]))
        for pair in inventory["version_candidates"]
    }
    relations = []
    for left, right in sorted(expected | alignment.keys()):
        matched = sorted(alignment.get((left, right), []))
        one, two = ({a for a, _ in matched}, {b for _, b in matched})
        total_left, total_right = pdfs[left]["page_count"], pdfs[right]["page_count"]
        if pdfs[left]["sha256"] == pdfs[right]["sha256"]:
            relation = "identical"
        elif matched and (
            (len(one) == total_left and total_right > total_left)
            or (len(two) == total_right and total_left > total_right)
        ):
            relation = "superset"
        elif matched:
            relation = "partial_overlap"
        else:
            relation = "revised" if (left, right) in expected else "unrelated"
        relations.append({"files": [left, right], "relation": relation, "alignment": matched})
    exclusions = defaultdict(list)
    for row in decisions.values():
        if row["decision"] == "exclude" and row["reason"] != "user_label":
            exclusions[row["reason"]].append(row)
    rng = random.Random(SEED)
    sample = [
        record
        for records in exclusions.values()
        for record in rng.sample(records, min(5, len(records)))
    ]
    kept = [current_pages[key] for key in sorted(decisions) if decisions[key]["decision"] == "keep"]
    keep_keys = {identity(row) for row in kept}
    queue = load(extracted / "visual_queue.json")
    visual = [
        {**row, "skip_regions": decisions[identity(row)]["skip_regions"]}
        for row in queue["pages"]
        if identity(row) in keep_keys
    ]
    write_jsonl(audit / "page_filter.jsonl", decisions.values())
    write_json(audit / "corpus_v2.json", {"schema_version": 2, "pages": kept})
    write_json(audit / "version_relations.json", relations)
    write_json(extracted / "figure_index.json", figures)
    write_json(audit / "exclusion_audit_sample.json", {"seed": SEED, "pages": sample})
    write_json(audit / "p2d0_review_queue.json", {"pages": review})
    write_json(extracted / "visual_queue_v2.json", {**queue, "pages": visual})
    print(
        json.dumps(
            {
                "pages": len(decisions),
                "kept": len(kept),
                "visual": len(visual),
                "review": len(review),
                "exclusions": Counter(
                    r["reason"] for r in decisions.values() if r["decision"] == "exclude"
                ),
                "relations": Counter(r["relation"] for r in relations),
                "sample": len(sample),
                "figures": len(figures),
                "skip_regions": sum(len(r["skip_regions"]) for r in decisions.values()),
            },
            ensure_ascii=False,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    prepare(parser.parse_args().root.resolve())


if __name__ == "__main__":
    main()
