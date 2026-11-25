"""Serve the private lecture page labeler on the local machine."""
import argparse
import hashlib
import json
import shutil
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from urllib.parse import urlsplit

HTML = Path(__file__).with_name("label_pages.html")
LABELS = {"keep", "exclude", None}


class Audit:
    def __init__(self, root):
        lecture_dir = (root / "NLP").resolve()
        directory = root / "data_private" / "audit"
        self.output = directory / "page_labels.json"
        self.review_queue = directory / "human_review_queue.json"
        self.final_queue = directory / "p2d0_review_queue.json"
        inventory = json.loads((directory / "inventory.json").read_text(encoding="utf-8"))
        self.pages = {}
        self.paths = {}
        self.lock = Lock()
        for entry in inventory["files"]:
            file = entry["source"]["file"]
            pdf = (root / file).resolve()
            if not pdf.is_relative_to(lecture_dir) or pdf.suffix.lower() != ".pdf":
                raise ValueError("Invalid lecture PDF path")
            with pdf.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != entry["sha256"]:
                raise ValueError(f"PDF changed since inventory: {pdf.name}")
            for page in entry["pages"]:
                key = str(len(self.pages))
                self.paths[key] = pdf
                self.pages[key] = {
                    "id": key,
                    "source": page["source"],
                    "sha256": digest,
                    "status": page.get("visual_screening_status", "미확인"),
                }

    def state(self):
        if self.output.exists():
            return json.loads(self.output.read_text(encoding="utf-8"))["labels"]
        return []

    @staticmethod
    def identity(page):
        return page["source"]["file"], page["source"]["page"], page["sha256"]

    def catalog(self):
        with self.lock:
            labels = {self.identity(item): item["label"] for item in self.state()}
        review = {}
        if self.review_queue.exists():
            records = json.loads(self.review_queue.read_text(encoding="utf-8"))["pages"]
            review = {self.identity(item): item["question"] for item in records}
        final = {}
        if self.final_queue.exists():
            records = json.loads(self.final_queue.read_text(encoding="utf-8"))["pages"]
            final = {self.identity(item): item["question"] for item in records}
        return [
            {
                **page,
                "final_review": final.get(self.identity(page)),
                "label": labels.get(self.identity(page)),
                "review_question": review.get(self.identity(page)),
            }
            for page in self.pages.values()
        ]

    def save(self, key, label):
        page = self.pages[key]
        with self.lock:
            records = {self.identity(item): item for item in self.state()}
            identity = self.identity(page)
            if label is None:
                records.pop(identity, None)
            else:
                records[identity] = {
                    "source": page["source"], "sha256": page["sha256"], "label": label,
                }
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.output.parent, delete=False
            ) as stream:
                temp = Path(stream.name)
                try:
                    json.dump(
                        {"schema_version": 1, "labels": [records[k] for k in sorted(records)]},
                        stream, ensure_ascii=False, indent=2,
                    )
                    stream.write("\n")
                    stream.flush()
                    temp.replace(self.output)
                finally:
                    temp.unlink(missing_ok=True)

    def image(self, key):
        page = str(self.pages[key]["source"]["page"])
        return subprocess.run(
            ["pdftoppm", "-f", page, "-l", page, "-scale-to", "1600",
             "-png", "-singlefile", str(self.paths[key])],
            check=True, capture_output=True, timeout=20,
        ).stdout


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, content_type, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def local_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in {f"localhost:{port}", f"127.0.0.1:{port}"}

    def do_GET(self):
        if not self.local_host():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        path = urlsplit(self.path).path
        if path == "/":
            self.reply(HTML.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/pages":
            body = json.dumps(self.server.audit.catalog(), ensure_ascii=False).encode()
            self.reply(body, "application/json; charset=utf-8")
        elif path.startswith("/page/"):
            key = path.removeprefix("/page/")
            try:
                body = self.server.audit.image(key)
            except KeyError:
                self.send_error(HTTPStatus.NOT_FOUND)
            except (subprocess.SubprocessError, OSError):
                self.send_error(HTTPStatus.BAD_GATEWAY, "Page render failed")
            else:
                self.reply(body, "image/png")
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        origins = {
            f"http://localhost:{self.server.server_port}",
            f"http://127.0.0.1:{self.server.server_port}",
        }
        if not self.local_host() or self.headers.get("Origin") not in origins:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if self.path != "/api/label":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size < 1024 or self.headers.get_content_type() != "application/json":
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            key, label = payload["id"], payload["label"]
            if key not in self.server.audit.pages or label not in LABELS:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid label")
            return
        try:
            self.server.audit.save(key, label)
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Could not save label")
        else:
            self.reply(b"{}", "application/json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not shutil.which("pdftoppm"):
        parser.error("pdftoppm is required (Poppler)")
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.audit = Audit(Path.cwd())
        print(f"http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
