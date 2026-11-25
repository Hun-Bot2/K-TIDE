"""Stratified slot plan for the independent evaluation set (docs/research/evaluation_protocol.md).

Reads the private concept map and CKUs, writes data_private/evalset/plan_v1.json.
No lecture or question text is produced here — only slot assignments.

Usage:
    uv run python -m ktide.evalset.plan [--seed 20261125]
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from ktide.professor import REPO_ROOT

KNOW = REPO_ROOT / "data_private" / "knowledge"
OUT = REPO_ROOT / "data_private" / "evalset"

SIZES = {"dev": 150, "test_seen": 200}
UNSEEN_CONCEPTS = 25
UNSEEN_PER_CONCEPT = 2
VARIANT_GROUPS = 20
MAX_PER_CONCEPT = 3  # per split
DEPTH_FACTOR = {"core": 1.5, "supporting": 1.0, "mention_only": 0.5}
QTYPE_DIST = {
    "definition": 0.30,
    "purpose": 0.15,
    "mechanism": 0.15,
    "comparison": 0.15,
    "limitation": 0.10,
    "consequence": 0.10,
    "judgment": 0.05,
}
TERM_DIST = {"ko": 0.35, "en": 0.40, "abbr": 0.15, "mixed": 0.10}


def load():
    concepts = json.loads((KNOW / "concept_map.json").read_text(encoding="utf-8"))["concepts"]
    path = KNOW / "cku_v2_1.jsonl"
    if not path.exists():
        path = KNOW / "cku_v2.jsonl"
    ckus = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            ckus[item["concept_id"]] = item
    return concepts, ckus, path.name


def weight(c) -> float:
    return math.log1p(len(c["lecture_sources"])) * DEPTH_FACTOR.get(c["coverage_depth"], 1.0)


def has_abbr(c, cku) -> bool:
    return bool(c.get("abbreviations")) or bool(cku.get("terminology", {}).get("full_form"))


def has_ko(c) -> bool:
    return bool(c.get("ko_name")) and c["ko_name"] != c["canonical_term"]


def allowed_qtypes(cku) -> list[str]:
    allowed = ["definition", "purpose", "consequence", "judgment"]
    if cku.get("mechanism_ko"):
        allowed.append("mechanism")
    if cku.get("contrast_with"):
        allowed.append("comparison")
    if cku.get("limitations_ko"):
        allowed.append("limitation")
    return allowed


def allocate(weights: dict[str, float], total: int, cap: int) -> dict[str, int]:
    """Largest-remainder allocation with a per-concept cap."""
    alloc = {k: 0 for k in weights}
    remaining = total
    active = dict(weights)
    while remaining > 0 and active:
        s = sum(active.values())
        quotas = {k: remaining * w / s for k, w in active.items()}
        base = {k: min(int(q), cap - alloc[k]) for k, q in quotas.items()}
        for k, n in base.items():
            alloc[k] += n
        remaining -= sum(base.values())
        order = sorted(active, key=lambda k: quotas[k] - int(quotas[k]), reverse=True)
        for k in order:
            if remaining == 0:
                break
            if alloc[k] < cap:
                alloc[k] += 1
                remaining -= 1
        active = {k: w for k, w in active.items() if alloc[k] < cap}
    return alloc


def pick(rng, dist: dict[str, float], allowed: list[str]) -> str:
    keys = [k for k in dist if k in allowed]
    return rng.choices(keys, weights=[dist[k] for k in keys])[0]


def main(argv=None) -> Path:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261125)
    args = ap.parse_args(argv)
    rng = random.Random(args.seed)

    concepts, ckus, cku_file = load()
    by_id = {c["concept_id"]: c for c in concepts}
    parents = {c["parent_id"] for c in concepts if c.get("parent_id")}

    # 1. Unseen concepts: stratified by domain, substantive coverage, not a parent of others.
    pool = defaultdict(list)
    for c in concepts:
        if c["coverage_depth"] != "mention_only" and c["concept_id"] not in parents:
            pool[c["domain"]].append(c["concept_id"])
    dom_w = {d: sum(weight(by_id[i]) for i in ids) for d, ids in pool.items()}
    dom_alloc = allocate(dom_w, UNSEEN_CONCEPTS, cap=10**6)
    unseen = []
    for d, n in sorted(dom_alloc.items()):
        ids = sorted(pool[d])
        rng.shuffle(ids)
        unseen += ids[: min(n, max(len(ids) - 1, 0))]  # keep at least one seen concept per domain
    unseen_set = set(unseen)
    seen = [c for c in concepts if c["concept_id"] not in unseen_set]

    # 2. Variant groups (inside test_seen): concepts with a Korean name and English/abbr forms.
    cand = [c["concept_id"] for c in seen if has_ko(c) and c["coverage_depth"] != "mention_only"]
    cand.sort(key=lambda i: -weight(by_id[i]))
    top = cand[: VARIANT_GROUPS * 2]
    rng.shuffle(top)
    variant_concepts = sorted(top[:VARIANT_GROUPS])

    slots = []

    def add(split, cid, qtype, term_form, group=None):
        c = by_id[cid]
        slots.append(
            {
                "slot_id": f"{split}-{len(slots) + 1:04d}",
                "split": split,
                "concept_id": cid,
                "domain": c["domain"],
                "coverage_depth": c["coverage_depth"],
                "question_type": qtype,
                "term_form": term_form,
                "variant_group": group,
            }
        )

    for g, cid in enumerate(variant_concepts, 1):
        cku = ckus[cid]
        qtype = pick(rng, QTYPE_DIST, allowed_qtypes(cku))
        third = "abbr" if has_abbr(by_id[cid], cku) else "mixed"
        for tf in ("ko", "en", third):
            add("test_seen", cid, qtype, tf, group=f"VG{g:02d}")

    # 3. Remaining test_seen and dev slots by weight.
    w_seen = {c["concept_id"]: weight(c) for c in seen}
    used = Counter(s["concept_id"] for s in slots)
    test_left = SIZES["test_seen"] - len(slots)
    w_test = {k: v for k, v in w_seen.items()}
    test_alloc = allocate(w_test, test_left, cap=MAX_PER_CONCEPT)
    for cid, n in sorted(test_alloc.items()):
        n = min(n, MAX_PER_CONCEPT - used[cid])
        for _ in range(max(n, 0)):
            cku = ckus[cid]
            tf_allowed = ["ko", "en", "mixed"] + (["abbr"] if has_abbr(by_id[cid], cku) else [])
            if not has_ko(by_id[cid]):
                tf_allowed = [t for t in tf_allowed if t != "ko"]
            add(
                "test_seen",
                cid,
                pick(rng, QTYPE_DIST, allowed_qtypes(cku)),
                pick(rng, TERM_DIST, tf_allowed),
            )
    # top up if caps left a shortfall
    while sum(s["split"] == "test_seen" for s in slots) < SIZES["test_seen"]:
        counts = Counter(s["concept_id"] for s in slots if s["split"] == "test_seen")
        room = {k: v for k, v in w_seen.items() if counts[k] < MAX_PER_CONCEPT}
        cid = rng.choices(list(room), weights=list(room.values()))[0]
        add("test_seen", cid, pick(rng, QTYPE_DIST, allowed_qtypes(ckus[cid])), "en")

    test_types = defaultdict(set)
    for s in slots:
        test_types[s["concept_id"]].add(s["question_type"])
    # Every seen concept with substantive coverage appears at least once (dev or test).
    uncovered = [
        c["concept_id"]
        for c in seen
        if c["coverage_depth"] != "mention_only" and not test_types[c["concept_id"]]
    ]
    dev_alloc = Counter({cid: 1 for cid in uncovered})
    rest = allocate(w_seen, SIZES["dev"] - len(uncovered), cap=MAX_PER_CONCEPT)
    for cid, n in rest.items():
        dev_alloc[cid] = min(dev_alloc[cid] + n, MAX_PER_CONCEPT)
    while sum(dev_alloc.values()) < SIZES["dev"]:
        room = {k: v for k, v in w_seen.items() if dev_alloc[k] < MAX_PER_CONCEPT}
        dev_alloc[rng.choices(list(room), weights=list(room.values()))[0]] += 1
    for cid, n in sorted(dev_alloc.items()):
        cku = ckus[cid]
        for _ in range(n):
            allowed = allowed_qtypes(cku)
            fresh = [q for q in allowed if q not in test_types[cid]] or allowed
            tf_allowed = ["ko", "en", "mixed"] + (["abbr"] if has_abbr(by_id[cid], cku) else [])
            if not has_ko(by_id[cid]):
                tf_allowed = [t for t in tf_allowed if t != "ko"]
            add("dev", cid, pick(rng, QTYPE_DIST, fresh), pick(rng, TERM_DIST, tf_allowed))

    for cid in unseen:
        cku = ckus[cid]
        types = allowed_qtypes(cku)
        first = "definition"
        second = pick(rng, QTYPE_DIST, [t for t in types if t != "definition"] or types)
        for q in (first, second):
            tf_allowed = ["en", "mixed"] + (["ko"] if has_ko(by_id[cid]) else [])
            add("test_unseen", cid, q, pick(rng, TERM_DIST, tf_allowed))

    OUT.mkdir(parents=True, exist_ok=True)
    plan = {
        "version": 1,
        "seed": args.seed,
        "cku_source": cku_file,
        "unseen_concepts": unseen,
        "variant_concepts": variant_concepts,
        "slots": slots,
        "summary": {
            "by_split": Counter(s["split"] for s in slots),
            "by_domain": Counter(s["domain"] for s in slots),
            "by_qtype": Counter(s["question_type"] for s in slots),
            "by_term_form": Counter(s["term_form"] for s in slots),
            "concepts_covered": len({s["concept_id"] for s in slots}),
        },
    }
    out = OUT / "plan_v1.json"
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan["summary"], ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    main()
