"""Select and render private lecture pages for direct visual transcription."""

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ktide.knowledge.extract import write_json


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def select(root):
    private = root / "data_private"
    baseline = load(private / "knowledge/concept_map.p2b.json")
    inventory = load(private / "audit/inventory.json")
    draft = load(private / "audit/p2_corpus_draft.json")
    allowed = {(x["source"]["file"], x["source"]["page"], x["sha256"]) for x in draft["pages"]}
    backed = {
        s["file"]
        for item in baseline["concepts"]
        for facet in item["facets"].values()
        for s in facet["sources"]
    }
    selected = []
    seen = set()
    for entry in inventory["files"]:
        digest, file = entry["sha256"], entry["source"]["file"]
        if digest in seen:
            continue
        seen.add(digest)
        zero = file not in backed
        priority = 0 if zero else 1 if entry["language"] in {"한국어", "혼합"} else 2
        for page in entry["pages"]:
            source = page["source"]
            if (file, source["page"], digest) not in allowed:
                continue
            reasons = []
            if page["korean_chars"] + page["english_chars"] < 80:
                reasons.append("under_80_letters")
            if page["visual_screening_status"] == "우선 시각 검토":
                reasons.append("priority_visual_review")
            if zero and page["type"].startswith("정보성 이미지·다이어그램"):
                reasons.append("zero_facet_illustrated")
            if reasons:
                selected.append(
                    {
                        "source": source,
                        "sha256": digest,
                        "priority": priority,
                        "reasons": reasons,
                        "image": f"{digest[:16]}-{source['page']:04}.png",
                    }
                )
    return sorted(selected, key=lambda x: (x["priority"], x["source"]["file"], x["source"]["page"]))


def render(root, output, record, dpi):
    source = record["source"]
    pdf = (root / source["file"]).resolve()
    if not pdf.is_relative_to((root / "NLP").resolve()) or pdf.suffix.lower() != ".pdf":
        raise ValueError("Invalid lecture source path")
    page = str(source["page"])
    target = output / record["image"]
    if target.exists():
        return
    temporary = target.with_suffix(".render")
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            str(dpi),
            "-f",
            page,
            "-l",
            page,
            "-png",
            "-singlefile",
            str(pdf),
            str(temporary),
        ],
        check=True,
        capture_output=True,
    )
    temporary.with_suffix(".render.png").replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / "data_private/extracted/page_images"
    output.mkdir(parents=True, exist_ok=True)
    selected = select(root)
    write_json(output.parent / "visual_queue.json", {"dpi": 150, "pages": selected})
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda page: render(root, output, page, 150), selected))
    print(f"Rendered {len(selected)} selected pages")


if __name__ == "__main__":
    main()
