"""Local web labeler for evaluation-set review (binds to 127.0.0.1 only).

Every action is saved immediately to data_private/evalset/review/:
    decisions_v1.json    {item_id: {decision, edited_question, edited_answer, note, updated_at}}
    human_items_v1.json  [{id, concept_id, question_ko, reference_answer_ko, key_points_ko, note}]

Usage:
    uv run python -m ktide.evalset.review_server            # http://127.0.0.1:8770
    uv run python -m ktide.evalset.review_server --port 8800
Then apply the decisions with:
    uv run python -m ktide.evalset.review import
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ktide.metrics import sentence_count, word_count
from ktide.professor import REPO_ROOT

EVAL = REPO_ROOT / "data_private" / "evalset"
REVIEW = EVAL / "review"
DECISIONS = REVIEW / "decisions_v1.json"
HUMAN = REVIEW / "human_items_v1.json"
RECHECK = REVIEW / "recheck_v1.json"
ADJUDICATION = EVAL / "answerability_adjudication_v1.jsonl"
ANSWERABILITY = EVAL / "answerability_v1.jsonl"
HTML = Path(__file__).with_name("review_ui.html")
SPLITS = ("test_seen", "test_unseen")
LOCK = threading.Lock()


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def atomic_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def answer_check(text: str) -> dict:
    wc, sc = word_count(text), sentence_count(text)
    return {"words": wc, "sentences": sc, "ok": 0 < wc <= 30 and 1 <= sc <= 2}


def load_items():
    concepts = {
        c["concept_id"]: c
        for c in json.loads(
            (REPO_ROOT / "data_private/knowledge/concept_map.json").read_text(encoding="utf-8")
        )["concepts"]
    }
    items = []
    for line in (EVAL / "filtered_v1.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        it = json.loads(line)
        if it["split"] not in SPLITS:
            continue
        c = concepts.get(it["concept_id"], {})
        items.append(
            {
                "item_id": it["item_id"],
                "split": it["split"],
                "domain": it["domain"],
                "concept_id": it["concept_id"],
                "concept": c.get("canonical_term", ""),
                "concept_ko": c.get("ko_name", ""),
                "question_type": it["question_type"],
                "term_form": it["term_form"],
                "variant_group": it.get("variant_group"),
                "question_ko": it["question_ko"],
                "reference_answer_ko": it["reference_answer_ko"],
                "key_points_ko": it.get("key_points_ko", []),
                "required_terms": it.get("required_terms", []),
                "auto_flags": it.get("failed_checks", []),
                "writer_notes": it.get("writer_notes", ""),
                "answer_check": answer_check(it["reference_answer_ko"]),
            }
        )
    items.sort(key=lambda i: (i["split"], i["domain"], i["concept_id"], i["item_id"]))
    seen_concepts = sorted(
        {
            (i["concept_id"], i["concept"], i["concept_ko"], i["domain"])
            for i in items
            if i["split"] == "test_seen"
        }
    )
    return items, [
        {"concept_id": a, "concept": b, "concept_ko": c, "domain": d}
        for a, b, c, d in seen_concepts
    ]


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def load_recheck():
    """Items the adjudicator marked as needing a change (category != nitpick)."""
    adj = [a for a in read_jsonl(ADJUDICATION) if a.get("category") != "nitpick"]
    if not adj:
        return []
    current = {r["item_id"]: r for r in read_jsonl(EVAL / "filtered_v1.jsonl")}
    current.update({r["item_id"]: r for r in read_jsonl(EVAL / "reviewed_v1.jsonl")})
    codex = {r["item_id"]: r for r in read_jsonl(ANSWERABILITY)}
    out = []
    for a in adj:
        it = current.get(a["item_id"])
        if not it:
            continue
        out.append(
            {
                "item_id": a["item_id"],
                "split": it["split"],
                "category": a["category"],
                "question_type": it["question_type"],
                "concept_id": it["concept_id"],
                "question_ko": it["question_ko"],
                "reference_answer_ko": it["reference_answer_ko"],
                "suggested_question_ko": a.get("suggested_question_ko"),
                "suggested_answer_ko": a.get("suggested_answer_ko"),
                "reason": a.get("reason", ""),
                "codex_issue": codex.get(a["item_id"], {}).get("issues", ""),
            }
        )
    order = {"error": 0, "ambiguous_fix": 1, "precision_fix": 2}
    out.sort(key=lambda r: (order.get(r["category"], 9), r["split"], r["item_id"]))
    return out


class Handler(BaseHTTPRequestHandler):
    items: list = []
    concepts: list = []
    recheck: list = []

    def log_message(self, *args):  # keep the terminal quiet
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/items":
            return self.send(200, {"items": self.items, "decisions": read_json(DECISIONS, {})})
        if self.path == "/api/human":
            return self.send(200, {"concepts": self.concepts, "human": read_json(HUMAN, [])})
        if self.path == "/api/recheck":
            Handler.recheck = load_recheck()
            return self.send(200, {"items": self.recheck, "decisions": read_json(RECHECK, {})})
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        try:
            payload = self.body()
        except (ValueError, json.JSONDecodeError):
            return self.send(400, {"error": "bad json"})
        now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        if self.path == "/api/recheck":
            iid, action = payload.get("item_id"), payload.get("action")
            if iid not in {r["item_id"] for r in self.recheck} or action not in (
                "apply",
                "keep",
                "edit",
                "reject",
                None,
            ):
                return self.send(400, {"error": "invalid item or action"})
            rec = {
                "action": action,
                "edited_question": (payload.get("edited_question") or "").strip(),
                "edited_answer": (payload.get("edited_answer") or "").strip(),
                "note": (payload.get("note") or "").strip(),
                "updated_at": now,
            }
            if action == "edit" and not (rec["edited_question"] or rec["edited_answer"]):
                return self.send(400, {"error": "edit needs an edited question or answer"})
            with LOCK:
                data = read_json(RECHECK, {})
                if action is None:
                    data.pop(iid, None)
                else:
                    data[iid] = rec
                atomic_write(RECHECK, data)
            check = answer_check(rec["edited_answer"]) if rec["edited_answer"] else None
            return self.send(200, {"saved": True, "n_decided": len(data), "answer_check": check})
        if self.path == "/api/decision":
            ids = {i["item_id"] for i in self.items}
            iid, decision = payload.get("item_id"), payload.get("decision")
            if iid not in ids or decision not in ("accept", "edit", "reject", None):
                return self.send(400, {"error": "invalid item or decision"})
            rec = {
                "decision": decision,
                "edited_question": (payload.get("edited_question") or "").strip(),
                "edited_answer": (payload.get("edited_answer") or "").strip(),
                "note": (payload.get("note") or "").strip(),
                "updated_at": now,
            }
            if decision == "edit" and not (rec["edited_question"] or rec["edited_answer"]):
                return self.send(400, {"error": "edit needs an edited question or answer"})
            check = answer_check(rec["edited_answer"]) if rec["edited_answer"] else None
            with LOCK:
                data = read_json(DECISIONS, {})
                if decision is None:
                    data.pop(iid, None)
                else:
                    data[iid] = rec
                atomic_write(DECISIONS, data)
            return self.send(200, {"saved": True, "answer_check": check, "n_decided": len(data)})
        if self.path == "/api/human":
            action = payload.get("action")
            with LOCK:
                human = read_json(HUMAN, [])
                if action == "add":
                    q = (payload.get("question_ko") or "").strip()
                    a = (payload.get("reference_answer_ko") or "").strip()
                    cid = payload.get("concept_id")
                    if (
                        not q
                        or not a
                        or (cid and cid not in {c["concept_id"] for c in self.concepts})
                    ):
                        return self.send(400, {"error": "question and answer are required"})
                    next_id = max([h["id"] for h in human] + [0]) + 1
                    human.append(
                        {
                            "id": next_id,
                            "concept_id": cid or None,
                            "question_ko": q,
                            "reference_answer_ko": a,
                            "key_points_ko": [
                                k.strip()
                                for k in (payload.get("key_points") or "").split("|")
                                if k.strip()
                            ],
                            "note": (payload.get("note") or "").strip(),
                            "created_at": now,
                        }
                    )
                elif action == "delete":
                    human = [h for h in human if h["id"] != payload.get("id")]
                else:
                    return self.send(400, {"error": "unknown action"})
                atomic_write(HUMAN, human)
            return self.send(
                200,
                {
                    "saved": True,
                    "human": human,
                    "answer_check": answer_check(payload.get("reference_answer_ko") or "")
                    if action == "add"
                    else None,
                },
            )
        return self.send(404, {"error": "not found"})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    args = ap.parse_args(argv)
    Handler.items, Handler.concepts = load_items()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Review UI: http://127.0.0.1:{args.port}  ({len(Handler.items)} items)  Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
