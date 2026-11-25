# ADR-0001: Ship the original Qwen `generation_config.json` byte-for-byte

- Status: Accepted (2026-11-24)
- Context phase: P1 Baseline

## Context

The professor's `answer_questions` passes
`GenerationConfig(do_sample=False, num_beams=1, max_new_tokens=128, ...)` to `model.generate`.
In transformers 4.57.1 (`GenerationMixin._prepare_generation_config`), when a caller passes a
config, every field still equal to the *global* default is overwritten by the model's
`generation_config.json` value — **only if** that file's `transformers_version >= 4.50.0`.
`do_sample=False` equals the global default, so it is overridable.

Verified with `python -m ktide.check_generation_config` (meta-device, no weights):

| `generation_config.json` | effective decoding in the professor notebook |
|---|---|
| original Qwen2.5-1.5B-Instruct (`transformers_version: 4.37.0`) | greedy (`do_sample=False`, rep. penalty 1.0) |
| same values re-stamped `4.57.1` (what `save_pretrained` writes) | **sampling**: `do_sample=True`, T=0.7, top_p=0.8, top_k=20, rep. penalty 1.1 |

## Decision

Per the user's rule (keep the original tokenizer, chat template, special tokens and the
*effective* generation configuration), the submission ZIP must contain the original
`generation_config.json` from the pinned base-model revision, copied byte-for-byte after
`save_pretrained`. The export step will assert that the effective config of the final package is
greedy and identical to the base model's.

## Consequences

- Official evaluation stays deterministic greedy decoding, as the assignment specifies.
- Every fine-tuned checkpoint evaluated by our pipeline must also go through this copy step before
  evaluation; otherwise comparisons against B0 would mix greedy and sampled decoding.
