"""Prepare locally masked page images for lecture-concept review."""

import argparse
import math
import re
import struct
import subprocess
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ktide.knowledge.extract import write_json
from ktide.knowledge.visual import load


def ppm(raw):
    match = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", raw)
    if not match:
        raise ValueError("Expected 8-bit RGB output from Poppler")
    width, height = map(int, match.groups())
    pixels = bytearray(raw[match.end() :])
    if len(pixels) != width * height * 3:
        raise ValueError("Invalid RGB image length")
    return width, height, pixels


def png(width, height, pixels):
    def chunk(name, data):
        return (
            struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))
        )

    stride = width * 3
    scanlines = b"".join(b"\x00" + pixels[i : i + stride] for i in range(0, len(pixels), stride))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(scanlines)),
            chunk(b"IEND", b""),
        )
    )


def render(root, output, item, dpi):
    source = item["source"]
    path = (root / source["file"]).resolve()
    if not path.is_relative_to((root / "NLP").resolve()) or path.suffix.lower() != ".pdf":
        raise ValueError("Invalid lecture PDF")
    page = str(source["page"])
    raw = subprocess.run(
        ["pdftoppm", "-r", str(dpi), "-f", page, "-l", page, "-singlefile", str(path)],
        check=True,
        capture_output=True,
    ).stdout
    width, height, pixels = ppm(raw)
    scale = dpi / 72
    for region in item.get("skip_regions", []):
        x0, y0, x1, y1 = region["bbox"]
        left, top = max(0, math.floor((x0 - 1) * scale)), max(0, math.floor((y0 - 1) * scale))
        right = min(width, math.ceil((x1 + 1) * scale))
        bottom = min(height, math.ceil((y1 + 1) * scale))
        if right <= left or bottom <= top:
            continue
        fill = b"\xff" * ((right - left) * 3)
        for y in range(top, bottom):
            offset = (y * width + left) * 3
            pixels[offset : offset + len(fill)] = fill
    target = output / item["image"]
    target.write_bytes(png(width, height, pixels))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dpi", type=int, choices=(72, 150, 200), default=72)
    args = parser.parse_args()
    root = args.root.resolve()
    extracted = root / "data_private/extracted"
    output = extracted / f"cku_visual_{args.dpi}dpi"
    output.mkdir(parents=True, exist_ok=True)
    queue = load(extracted / "visual_queue_v2.json")["pages"]
    with ThreadPoolExecutor(max_workers=4) as worker:
        list(worker.map(lambda page: render(root, output, page, args.dpi), queue))
    write_json(output / "index.json", {"dpi": args.dpi, "pages": queue})
    print(len(queue))


if __name__ == "__main__":
    main()
