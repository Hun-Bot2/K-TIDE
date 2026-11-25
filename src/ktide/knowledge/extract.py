"""Extract text for the retained lecture pages using Poppler."""

import argparse
import hashlib
import json
import subprocess
import unicodedata
from collections import defaultdict
from pathlib import Path


def write_json(path, document):
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract(root):
    audit = root / "data_private/audit"
    draft = json.loads((audit / "p2_corpus_draft.json").read_text(encoding="utf-8"))
    inventory = json.loads((audit / "inventory.json").read_text(encoding="utf-8"))
    requested = defaultdict(set)
    for record in draft["pages"]:
        source = record["source"]
        requested[source["file"], record["sha256"]].add(source["page"])
    lecture_dir = (root / "NLP").resolve()
    by_hash = {}
    pages = []
    files = []
    for item in inventory["files"]:
        file = item["source"]["file"]
        digest = item["sha256"]
        path = (root / file).resolve()
        if not path.is_relative_to(lecture_dir) or path.suffix.lower() != ".pdf":
            raise ValueError(f"Invalid PDF path: {file}")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError(f"PDF checksum differs: {file}")
        allowed = requested.pop((file, digest), set())
        if not allowed:
            files.append({"file": file, "status": "skipped", "reason": "no_retained_pages"})
            continue
        if digest in by_hash:
            canonical, text = by_hash[digest]
            files.append(
                {
                    "file": file,
                    "status": "skipped",
                    "reason": "duplicate_sha256",
                    "canonical_file": canonical,
                    "retained_pages": len(allowed),
                }
            )
        else:
            result = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            text = result.stdout.removesuffix("\f").split("\f")
            if len(text) != item["page_count"]:
                raise ValueError(f"PDF page count differs: {file}")
            by_hash[digest] = file, text
            files.append(
                {
                    "file": file,
                    "status": "processed",
                    "retained_pages": len(allowed),
                    "poppler_warning_count": len(result.stderr.splitlines()),
                }
            )
        for number in sorted(allowed):
            if not 1 <= number <= len(text):
                raise ValueError(f"Out-of-range page: {file} {number}")
            pages.append(
                {
                    "source": {"file": file, "page": number},
                    "sha256": digest,
                    "text": unicodedata.normalize("NFKC", text[number - 1]).strip(),
                }
            )
    if requested:
        raise ValueError("Draft references PDFs missing from inventory")
    return pages, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    root = parser.parse_args().root.resolve()
    output = root / "data_private/knowledge"
    output.mkdir(parents=True, exist_ok=True)
    pages, files = extract(root)
    write_json(output / "lecture_pages.json", pages)
    write_json(output / "extraction_files.json", files)


if __name__ == "__main__":
    main()
