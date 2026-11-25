"""Index exact repeated raster images and their rendered page coordinates."""

import hashlib
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def raster_occurrences(root, directory, files):
    grouped = defaultdict(list)
    for index, (file, allowed) in enumerate(files.items()):
        pdf = (root / file).resolve()
        prefix = directory / f"raster-{index}"
        subprocess.run(
            ["pdftohtml", "-q", "-xml", "-zoom", "1", str(pdf), str(prefix)],
            check=True,
            capture_output=True,
        )
        for page in ET.parse(prefix.with_suffix(".xml")).getroot().findall("page"):
            number = int(page.attrib["number"])
            if number not in allowed:
                continue
            width, height = int(page.attrib["width"]), int(page.attrib["height"])
            for image in page.findall("image"):
                x, y, w, h = (int(image.attrib[k]) for k in ("left", "top", "width", "height"))
                if w < 65 or h < 65 or w * h < width * height * 0.04:
                    continue
                source_image = Path(image.attrib["src"]).resolve()
                if not source_image.is_relative_to(directory) or not source_image.is_file():
                    continue
                digest = hashlib.sha256(source_image.read_bytes()).hexdigest()
                grouped[digest].append(
                    {
                        "file": file,
                        "page": number,
                        "bbox": [x, y, x + w, y + h],
                    }
                )
    return grouped


def index_figures(grouped, rank):
    output = []
    for digest, occurrences in sorted(grouped.items()):
        by_page = {(x["file"], x["page"]) for x in occurrences}
        if len(by_page) < 2:
            continue
        representative = max(by_page, key=rank)
        output.append(
            {
                "figure_id": digest,
                "hash": digest,
                "occurrences": occurrences,
                "representative": {"file": representative[0], "page": representative[1]},
                "coordinate_space": "pdf_display_points_top_left",
                "extract": True,
            }
        )
    return output
