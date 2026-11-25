"""Check which decoding settings the professor's ``answer_questions`` will *effectively* use.

The notebook passes ``GenerationConfig(do_sample=False, num_beams=1, ...)``. In transformers
4.57.1, ``generate`` fills every field the caller left at its *global default* with the model's
``generation_config.json`` value — but only if that file's ``transformers_version`` >= 4.50.
``do_sample=False`` *is* the global default, so a model whose generation_config.json says
``do_sample: true`` and was saved by transformers>=4.50 would be sampled, not greedy.

This script loads the model skeleton on the ``meta`` device (no weights) and reports the effective
config for (a) the model folder as-is and (b) the same file re-stamped with the installed
transformers version, which is what ``save_pretrained`` would write after fine-tuning.

Usage:
    uv run python -m ktide.check_generation_config [MODEL_DIR_OR_HUB_ID]
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

KEYS = ("do_sample", "num_beams", "max_new_tokens", "temperature", "top_p", "top_k",
        "repetition_penalty", "eos_token_id", "pad_token_id")


def effective(model, tokenizer, max_new_tokens: int = 128) -> dict:
    from transformers import GenerationConfig

    cfg = GenerationConfig(
        do_sample=False, num_beams=1, max_new_tokens=max_new_tokens, use_cache=True,
        eos_token_id=tokenizer.eos_token_id, pad_token_id=tokenizer.pad_token_id,
    )
    eff, _ = model._prepare_generation_config(cfg)
    return {k: getattr(eff, k, None) for k in KEYS}


def main(target: str = "Qwen/Qwen2.5-1.5B-Instruct") -> dict:
    import torch
    import transformers
    from transformers import AutoTokenizer, GenerationConfig, Qwen2Config, Qwen2ForCausalLM

    folder = Path(target)
    if not folder.is_dir():
        from huggingface_hub import snapshot_download

        folder = Path(snapshot_download(target, allow_patterns=["*.json", "*.txt"]))

    tok = AutoTokenizer.from_pretrained(folder)
    config = Qwen2Config.from_pretrained(folder)
    with torch.device("meta"):
        model = Qwen2ForCausalLM(config)
    original = GenerationConfig.from_pretrained(folder)
    model.generation_config = original

    report = {"model": str(target), "saved_generation_config": original.to_diff_dict(),
              "as_is": effective(model, tok)}

    restamped = copy.deepcopy(original)
    restamped.transformers_version = transformers.__version__
    model.generation_config = restamped
    report[f"restamped_{transformers.__version__}"] = effective(model, tok)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return report


if __name__ == "__main__":
    main(*sys.argv[1:])
