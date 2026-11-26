"""Load evaluation code and constants directly from the professor's (private) notebook.

The notebook is never copied into the public repository. Instead, we parse it at runtime:

* literal constants (QUESTIONS, SYSTEM_PROMPT, EVAL_SYSTEM_PROMPT, MAX_NEW_TOKENS, ...) are read
  with ``ast.literal_eval`` — no code execution;
* function definitions (``load_model``, ``unpack_model``, ``answer_questions``, ...) and their
  imports are executed *verbatim* so that our inference is the professor's code, not a copy.

Top-level statements with side effects (pip install, downloading MODEL_ZIP_URL, generating
answers) are skipped.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NOTEBOOK = REPO_ROOT / "data_private" / "professor" / "TEST_Qwen25_SFT.ipynb"

CONSTANT_NAMES = (
    "QUESTIONS",
    "SYSTEM_PROMPT",
    "EVAL_SYSTEM_PROMPT",
    "MAX_NEW_TOKENS",
    "BATCH_SIZE",
    "MAX_PACKAGE_BYTES",
    "MODEL_FILES",
)
REQUIRED_FUNCTIONS = ("load_model", "unpack_model", "answer_questions")


def notebook_path() -> Path:
    return Path(os.environ.get("KTIDE_PROFESSOR_NOTEBOOK", DEFAULT_NOTEBOOK))


@dataclass
class ProfessorNotebook:
    path: Path
    sha256: str
    constants: dict[str, Any]
    function_sources: dict[str, str]
    namespace: dict[str, Any] = field(repr=False)

    @property
    def questions(self) -> list[str]:
        return list(self.constants["QUESTIONS"])

    @property
    def system_prompt(self) -> str:
        return self.constants["SYSTEM_PROMPT"]

    @property
    def eval_system_prompt(self) -> str:
        return self.constants["EVAL_SYSTEM_PROMPT"]

    def fn(self, name: str):
        return self.namespace[name]


def _code_cells(nb: dict) -> list[str]:
    cells = []
    for cell in nb["cells"]:
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        cells.append("".join(src) if isinstance(src, list) else src)
    return cells


def _literal(node: ast.expr) -> Any:
    """Evaluate literal constants, including ``9 * 1024**3``, parenthesised str concat and sets."""
    if isinstance(node, ast.Set):
        return {_literal(e) for e in node.elts}
    if isinstance(node, ast.BinOp):
        left, right = _literal(node.left), _literal(node.right)
        ops = {
            ast.Mult: lambda a, b: a * b,
            ast.Pow: lambda a, b: a**b,
            ast.Add: lambda a, b: a + b,
        }
        return ops[type(node.op)](left, right)
    return ast.literal_eval(node)


def load_professor_notebook(path: Path | None = None) -> ProfessorNotebook:
    path = Path(path) if path else notebook_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Professor notebook not found at {path}. Put it under data_private/professor/ "
            "or set KTIDE_PROFESSOR_NOTEBOOK."
        )
    raw = path.read_bytes()
    nb = json.loads(raw.decode("utf-8"))

    constants: dict[str, Any] = {}
    function_sources: dict[str, str] = {}
    exec_nodes: list[ast.stmt] = []

    for src in _code_cells(nb):
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue  # e.g. magics; none expected in this notebook
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if any(a.name in {"subprocess"} for a in node.names):
                    continue
                exec_nodes.append(node)
            elif isinstance(node, ast.FunctionDef):
                exec_nodes.append(node)
                function_sources[node.name] = ast.unparse(node)
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    try:
                        value = _literal(node.value)
                    except (ValueError, TypeError, KeyError, SyntaxError):
                        # Non-literal assignment (e.g. SHARD_NAME = re.compile(...)) — needed by
                        # the functions, safe to execute; skip ones that call the model/downloads.
                        if target.id in {"SHARD_NAME"}:
                            exec_nodes.append(node)
                        continue
                    constants[target.id] = value
                    exec_nodes.append(node)
            # All other top-level statements (calls, loops, prints) are intentionally skipped.

    missing = [n for n in ("QUESTIONS", "SYSTEM_PROMPT") if n not in constants]
    missing += [f for f in REQUIRED_FUNCTIONS if f not in function_sources]
    if missing:
        raise ValueError(f"Professor notebook is missing expected definitions: {missing}")

    namespace: dict[str, Any] = {"__name__": "professor_notebook"}
    module = ast.Module(body=exec_nodes, type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102 — trusted, user-provided

    return ProfessorNotebook(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        constants={k: constants[k] for k in CONSTANT_NAMES if k in constants},
        function_sources=function_sources,
        namespace=namespace,
    )


def as_namespace(nb: ProfessorNotebook) -> SimpleNamespace:
    return SimpleNamespace(**nb.constants)
