# P1 — B0 Baseline (professor public set, 11 questions)

Aggregate results only; question/answer text stays in `runs/` (private, gitignored).

## Setup

- Model: `Qwen/Qwen2.5-1.5B-Instruct` rev `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`, unmodified.
- Submission ZIP `qwen25_baseline_v2.zip`: passes the professor's `unpack_model`; all 7 files
  byte-identical to the hub revision; effective decoding = greedy (ADR-0001).
- Official run: professor notebook, unmodified, Colab NVIDIA T4 (user-reported), FP16/SDPA.
  Answers ingested from the printed output (`ktide.ingest`).
- Preliminary run: same professor code on local Mac CPU, FP32.
- Judge: professor's `EVAL_SYSTEM_PROMPT`, all 11 Q/A in one call, Codex CLI `gpt-6.2-sol`,
  reasoning `medium`. No references or lecture material given to the judge.

## Results

| Run | Accuracy | Relevance | Constraints | Total avg |
|---|---|---|---|---|
| Official (Colab T4, CUDA FP16), judge call #2 | 2.27 | 3.00 | 3.82 | **3.03** |
| Preliminary (CPU FP32), judge call #1 | 2.45 | 3.00 | 4.09 | 3.18 |

Rule-based (identical for both, since the answers are identical): 30-word compliance 10/11,
1–2 sentence compliance 9/11, mean 18.8 words, max 47 words, no Chinese-character mixing, no
answer reached the 128-token limit.

## Findings

1. **CUDA FP16 and CPU FP32 produced byte-identical answers for all 11 questions.** For this model
   and question set, local CPU runs reproduce the official outputs. This is checked for B0 only;
   it must be re-checked for fine-tuned models before local results are treated as official.
2. **The saved output inside the professor notebook is not B0.** It differs from both runs and
   comes from a different question list (12 questions).
3. **Judge noise is large compared with n=11.** Identical answers, two judge calls: 7/11
   questions changed at least one sub-score by ±1, and the total average moved by 0.15.
   → Model comparisons need repeated judge calls (mean ± sd) plus our own evaluation set.
4. Error types (from judge feedback; to be confirmed by human review):
   - Terminology misreading outside the NLP domain: tokenization explained as turning digital
     assets into tokens, SFT expanded as a server token-transfer protocol (both scored 1/1).
   - Conceptual errors: IDF, the Recall denominator, LoRA ("reducing weights").
   - Length violations: 2 answers had 3 sentences; one had 47 words.
