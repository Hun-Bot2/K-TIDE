"""Guard: the public repository must not track professor materials or private outputs."""

import subprocess

from ktide.professor import REPO_ROOT

FORBIDDEN_PREFIXES = (
    "data_private/",
    "runs/",
    "checkpoints/",
    "submission/",
    "NLP/",
    "Speech-Language/",
    "report_course/",
)
FORBIDDEN_SUFFIXES = (".pdf", ".zip", ".safetensors", ".ipynb")


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "--cached"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [f for f in out.splitlines() if f]


def test_no_private_files_tracked():
    def allowed(f):  # public runner notebooks written by us (no professor content)
        return f.startswith("notebooks/") and not f.startswith("notebooks/private/")

    bad = [
        f
        for f in tracked_files()
        if f.startswith(FORBIDDEN_PREFIXES) or (f.endswith(FORBIDDEN_SUFFIXES) and not allowed(f))
    ]
    assert bad == []
