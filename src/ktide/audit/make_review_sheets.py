"""Render contact sheets for the first visual triage pass."""

import concurrent.futures
import json
import subprocess
from pathlib import Path
from tempfile import mkdtemp


def render(root, out, index, record):
    number = str(record["source"]["page"])
    pdf = record["source"]["file"]
    result = subprocess.run(
        [
            "pdftoppm",
            "-f",
            number,
            "-l",
            number,
            "-scale-to",
            "250",
            "-png",
            "-singlefile",
            pdf,
            str(out / f"tile_{index:04}"),
        ],
        capture_output=True,
        cwd=root,
    )
    result.check_returncode()
    subprocess.run(
        [
            "sips",
            "--padToHeightWidth",
            "250",
            "250",
            "--padColor",
            "FFFFFF",
            str(out / f"tile_{index:04}.png"),
        ],
        check=True,
        capture_output=True,
    )


def main():
    root = Path(__file__).resolve().parents[3]
    audit = root / "data_private/audit"
    sheets = audit / "triage_sheets"
    sheets.mkdir(exist_ok=True)
    out = Path(mkdtemp(prefix="review-", dir=sheets))
    inventory = json.loads((audit / "inventory.json").read_text())
    labels_path = audit / "page_labels.json"
    labels = json.loads(labels_path.read_text())["labels"] if labels_path.exists() else []
    labeled = {(row["source"]["file"], row["source"]["page"], row["sha256"]) for row in labels}
    selected = []
    seen = set()
    for file in inventory["files"]:
        for page in file["pages"]:
            source = page["source"]
            if page["visual_screening_status"] != "우선 시각 검토":
                continue
            if (source["file"], source["page"], file["sha256"]) in labeled:
                continue
            identity = file["sha256"], source["page"]
            if identity not in seen:
                seen.add(identity)
                selected.append({"source": source, "sha256": file["sha256"]})

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [pool.submit(render, root, out, i, item) for i, item in enumerate(selected)]
        for job in jobs:
            job.result()

    for index in range(0, len(selected), 30):
        tile_count = min(30, len(selected) - index)
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-start_number",
                str(index),
                "-i",
                str(out / "tile_%04d.png"),
                "-vf",
                f"trim=end_frame={tile_count},scale=200:200,tile=5x6:padding=2:color=gray",
                "-frames:v",
                "1",
                str(out / f"fixed_{index // 30:02}.png"),
            ],
            check=True,
        )
    (out / "index.json").write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(selected)} pages: {out.relative_to(root)}")


if __name__ == "__main__":
    main()
