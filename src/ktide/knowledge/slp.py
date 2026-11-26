"""Extract the retained SLP chapters and build page-grounded CKU revisions."""

import argparse
import re
import subprocess
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from ktide.audit.filter_corpus import identity, write_jsonl
from ktide.knowledge.cku import FIELDS, read_jsonl, validate
from ktide.knowledge.extract import write_json
from ktide.knowledge.polish_cku import fix_particles, particle_lookup
from ktide.knowledge.visual import load

CHAPTERS = tuple(map(str, range(1, 10))) + ("11", "14", "B", "C", "I")
ROLES = dict(
    zip("dmfel", ("definition", "mechanism", "formula", "example", "limitation"), strict=True)
)
FIELD_CODES = dict(zip("cdmploxfta", FIELDS, strict=True))


def chapter_files(root):
    folder = root / "Speech-Language"
    for chapter in CHAPTERS:
        path = folder / f"{chapter}.pdf"
        if path.is_symlink() or path.resolve() != folder.resolve() / path.name:
            raise ValueError("A retained textbook chapter must be a regular local PDF")
        if not path.is_file():
            raise FileNotFoundError(path)
        yield chapter, path


def poppler(*args):
    return subprocess.run(args, capture_output=True, check=True, text=True, encoding="utf-8").stdout


def page_count(path):
    metadata = poppler("pdfinfo", str(path))
    return int(
        next(line.split(":", 1)[1] for line in metadata.splitlines() if line.startswith("Pages:"))
    )


def extract_pages(root):
    rows = []
    for chapter, path in chapter_files(root):
        raw = poppler("pdftotext", "-layout", "-enc", "UTF-8", str(path), "-")
        pages = raw.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        if len(pages) != page_count(path):
            raise ValueError(f"Extracted page count does not match the PDF for chapter {chapter}")
        file = path.relative_to(root).as_posix()
        title_start = re.compile(
            rf"^\s*({chapter}\.\d+(?:\.\d+)*)[ \t]{{2,}}([^\W\d].+)$",
            flags=re.MULTILINE,
        )
        running = re.compile(rf"\b({chapter}\.\d+)[ \t]+[•·][ \t]+([^\n]+)")
        images = {
            int(columns[0])
            for line in poppler("pdfimages", "-list", str(path)).splitlines()
            if (columns := line.split())
            and columns[0].isdigit()
            and len(columns) >= 6
            and columns[2] == "image"
            and int(columns[3]) >= 150
            and int(columns[4]) >= 50
        }
        for page, content in enumerate(pages, 1):
            visible_math = "<latexit" in content
            content = re.sub(r"<latexit\b[^>]*>.*?</latexit>", "", content, flags=re.DOTALL)
            headings = {}
            for match in title_start.finditer(content):
                section, title = match.groups()
                if "•" not in title and "·" not in title:
                    headings.setdefault(section, title.strip())
            first_lines = "\n".join(content.splitlines()[:5])
            for match in running.finditer(first_lines):
                section, title = match.groups()
                headings.setdefault(section, re.sub(r"\s{2,}\d+\s*$", "", title).strip())
            rows.append(
                {
                    "file": file,
                    "chapter": chapter,
                    "page": page,
                    "section": next((f"{key} {title}" for key, title in headings.items()), None),
                    "sections": headings,
                    "text": content.rstrip(),
                    "needs_visual_review": (
                        page in images or visible_math or "\ufffd" in content or not content.strip()
                    ),
                }
            )
    return rows


def reference(spec):
    chapter, section, page, role = spec.split("/")
    return {
        "file": f"Speech-Language/{chapter}.pdf",
        "chapter": chapter,
        "section": None if section == "-" else section,
        "page": int(page),
        "role": ROLES[role],
    }


def unique_sources(refs):
    return list({tuple(source.values()): source for source in refs}.values())


def load_editorial(path):
    decisions = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        key, review = line.split(maxsplit=1)
        if key in decisions:
            raise ValueError(f"Duplicate review for {key}")
        fields = defaultdict(list)
        sources = []
        absent = review.startswith("!")
        if not absent:
            for annotation in review.split():
                locator, codes = annotation.split(":")
                source = reference(locator)
                sources.append(source)
                if codes != "-":
                    for code in codes:
                        fields[FIELD_CODES[code]].append(source)
        decisions[key] = {
            "concept_id": key,
            "slp_sources": unique_sources(sources),
            "field_sources": dict(fields),
            "not_in_slp": absent,
            **({"reason": review[1:]} if absent else {}),
        }
    return decisions


def verify_source(source, pages, sections):
    chapter, page = source["chapter"], source["page"]
    assert chapter in CHAPTERS and source["file"] == f"Speech-Language/{chapter}.pdf"
    assert type(page) is int and (chapter, page) in pages
    section = source["section"]
    assert section is None or section in sections[chapter]
    assert source["role"] in ROLES.values()


def validate_grounding(units, concepts, allowed, pages, evidence, lookup):
    validate(units, concepts, allowed)
    index = {(r["chapter"], r["page"]): r for r in pages}
    assert len(index) == len(pages)
    sections = defaultdict(set)
    for row in pages:
        assert row["chapter"] in CHAPTERS
        assert row["file"] == f"Speech-Language/{row['chapter']}.pdf"
        sections[row["chapter"]].update(row["sections"])
    decisions = {row["concept_id"]: row for row in evidence}
    assert len(decisions) == len(evidence) and decisions.keys() == concepts.keys()
    for unit in units:
        assert unit["version"] == 3 and unit["revision"]["based_on"] == "cku_v2_1"
        assert not fix_particles(unit, lookup)
        decision = decisions[unit["concept_id"]]
        sources = unit["sources"]["slp"]
        assert sources == decision["slp_sources"]
        assert bool(sources) != decision["not_in_slp"]
        for source in sources:
            verify_source(source, index, sections)
        assert {field for field, basis in unit["basis"].items() if "slp_textbook" in basis} == (
            decision["field_sources"].keys()
        )
        for field, refs in decision["field_sources"].items():
            assert unit[field] and refs and all(ref in sources for ref in refs)
        alignment = unit["lecture_alignment"]
        if alignment.get("textbook_note"):
            assert alignment["textbook_sources"]
            assert all(ref in sources for ref in alignment["textbook_sources"])


def revise(root, folder):
    private = root / "data_private"
    knowledge = private / "knowledge"
    review = knowledge / "review"
    rules = particle_lookup(load(review / "particle_rules.json"))
    previous = read_jsonl(knowledge / "cku_v2_1.jsonl")
    concepts = {r["concept_id"]: r for r in load(knowledge / "concept_map.json")["concepts"]}
    allowed = {identity(r) for r in load(private / "audit/corpus_v2.json")["pages"]}
    pages = read_jsonl(folder / "pages.jsonl")
    decisions = load_editorial(folder / "editorial.tsv")
    edits = load(folder / "edits.json")
    assert edits.keys() <= decisions.keys()
    units = []
    receipts = []
    corrected = Counter()
    filled = Counter()
    for old in previous:
        key = old["concept_id"]
        decision = decisions[key]
        row = deepcopy(old)
        editorial = edits.get(key, {})
        amended = editorial.get("fields", {})
        reasons = {}
        for field, edit in amended.items():
            assert field in FIELDS
            assert old[field] != edit["after"] and edit["reason"]
            row[field] = edit["after"]
            reasons[field] = edit["reason"]
            if old[field]:
                corrected[field] += 1
            else:
                filled[field] += 1
            decision["field_sources"][field] = [reference(s) for s in edit["sources"]]
            if edit.get("also_ground"):
                for extra in edit["also_ground"]:
                    assert extra in FIELDS and row[extra]
                    decision["field_sources"][extra] = decision["field_sources"][field]
        note = editorial.get("textbook_note")
        note_refs = [reference(s) for s in editorial.get("note_sources", [])]
        if note:
            assert note_refs
            row["lecture_alignment"].update(textbook_note=note, textbook_sources=note_refs)
            if editorial.get("lecture_note_sources"):
                lecture_refs = editorial["lecture_note_sources"]
                assert all(identity({"source": ref}) in allowed for ref in lecture_refs)
                row["lecture_alignment"]["textbook_lecture_sources"] = lecture_refs
            reasons["lecture_alignment"] = (
                "강의와 교재에서 확인한 표기 또는 설명 범위의 차이를 기록했다."
            )

        for field in decision["field_sources"]:
            prior_basis = old["basis"][field]
            if field in amended:
                kept = (
                    ["lecture"]
                    if amended[field].get("keep_lecture") and "lecture" in prior_basis
                    else []
                )
                row["basis"][field] = [*kept, "slp_textbook"]
            elif prior_basis in ([], ["model_knowledge"]):
                row["basis"][field] = ["slp_textbook"]
            elif "slp_textbook" not in prior_basis:
                row["basis"][field] = [*prior_basis, "slp_textbook"]
        decision["slp_sources"] = unique_sources(
            [
                *decision["slp_sources"],
                *(ref for refs in decision["field_sources"].values() for ref in refs),
                *note_refs,
            ]
        )
        row["sources"]["slp"] = decision["slp_sources"]
        fix_particles(row, rules)
        changed = [
            field
            for field in old
            if field not in {"revision", "version"} and old[field] != row[field]
        ]
        changes = []
        if decision["slp_sources"]:
            changes.append("slp_grounding")
        if any(old[field] for field in amended):
            changes.append("content_correction")
        if any(not old[field] for field in amended):
            changes.append("textbook_enrichment")
        if note:
            changes.append("textbook_difference")
        row.update(
            version=3,
            revision={"based_on": "cku_v2_1", "changes": changes, "changed_fields": changed},
        )
        units.append(row)
        details = []
        for field in changed:
            refs = decision["field_sources"].get(field, decision["slp_sources"])
            if field == "lecture_alignment":
                refs = note_refs
            reason = reasons.get(field, "페이지별로 확인한 교재 근거와 출처를 반영했다.")
            if field == "sources" and not refs:
                reason = "유지한 교재 범위에서는 해당 개념의 실질 설명을 찾지 못했다."
            details.append(
                {
                    "field": field,
                    "before": old[field],
                    "after": row[field],
                    "sources": refs,
                    "reason": reason,
                }
            )
        receipts.append(
            {
                "concept_id": key,
                "changes": details,
                "content_corrections": [field for field in amended if old[field]],
                "filled_fields": [field for field in amended if not old[field]],
                "not_in_slp": decision["not_in_slp"],
            }
        )

    evidence = list(decisions.values())
    validate_grounding(units, concepts, allowed, pages, evidence, rules)
    write_jsonl(folder / "concept_evidence.jsonl", evidence)
    write_jsonl(review / "cku_v3_changes.jsonl", receipts)
    write_jsonl(knowledge / "cku_v3.jsonl", units)
    summary = {
        "concepts": len(units),
        "slp_grounded": sum(not r["not_in_slp"] for r in evidence),
        "not_in_slp": sum(r["not_in_slp"] for r in evidence),
        "basis": {
            label: dict(
                Counter(kind for row in rows for basis in row["basis"].values() for kind in basis)
            )
            for label, rows in (("v2.1", previous), ("v3", units))
        },
        "corrected": dict(corrected),
        "filled": dict(filled),
        "textbook_differences": sum(
            bool(row["lecture_alignment"].get("textbook_note")) for row in units
        ),
        "out_of_scope": len(load(folder / "out_of_scope_candidates.json")["candidates"]),
    }
    write_json(folder / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("extract", "revise"), nargs="?", default="extract")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    folder = root / "data_private/external/slp"
    folder.mkdir(parents=True, exist_ok=True)
    if args.action == "extract":
        pages = extract_pages(root)
        write_jsonl(folder / "pages.jsonl", pages)
        print(len(pages))
    else:
        print(revise(root, folder))
        from ktide.tracking import record

        record(lambda r: r.stage == "data", reason="CKU build")


if __name__ == "__main__":
    main()
