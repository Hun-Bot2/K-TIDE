"""Checks against the private professor notebook (skipped when it is absent, e.g. in public CI).

No professor content is asserted verbatim here, to keep this file safe for the public repo.
"""
import ast
import inspect
import json

import pytest

from ktide.professor import load_professor_notebook, notebook_path

pytestmark = pytest.mark.skipif(not notebook_path().is_file(), reason="private notebook absent")


def test_constants_match_assignment_requirements():
    nb = load_professor_notebook()
    c = nb.constants
    assert len(nb.questions) == 11
    assert c["MAX_NEW_TOKENS"] == 128 and c["BATCH_SIZE"] == 4
    assert c["MAX_PACKAGE_BYTES"] == 9 * 1024**3
    assert "30어절" in nb.system_prompt
    assert "Accuracy" in nb.eval_system_prompt


def test_answer_questions_is_the_notebook_function_verbatim():
    nb = load_professor_notebook()
    raw = json.loads(nb.path.read_text(encoding="utf-8"))
    sources = ["".join(c["source"]) if isinstance(c["source"], list) else c["source"]
               for c in raw["cells"] if c["cell_type"] == "code"]
    defs = {n.name: ast.dump(n) for s in sources for n in ast.parse(s).body
            if isinstance(n, ast.FunctionDef)}
    fn = inspect.unwrap(nb.fn("answer_questions"))  # strip @torch.inference_mode()
    for name in ("answer_questions", "load_model", "unpack_model"):
        executed = ast.dump(ast.parse(nb.function_sources[name]).body[0])
        assert executed == defs[name], name
    # The function resolves SYSTEM_PROMPT / BATCH_SIZE from the notebook's own namespace.
    assert fn.__globals__["SYSTEM_PROMPT"] == nb.system_prompt
    assert fn.__globals__["BATCH_SIZE"] == 4


def test_side_effect_statements_not_executed():
    nb = load_professor_notebook()
    assert "model_path" not in nb.namespace and "results" not in nb.namespace
