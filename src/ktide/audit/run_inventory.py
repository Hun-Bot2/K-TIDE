"""Build the private first-pass PDF audit with Poppler."""

import collections
import concurrent.futures
import difflib
import hashlib
import itertools
import json
import math
import re
import subprocess
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data_private/audit"
TERMS = {
    "NLP": r"natural language processing|(?<!\w)NLP\b|자연어\s*처리",
    "Tokenization": r"tokeniz(?:ation|er|e)|토큰화|토크나이저",
    "Preprocessing": r"preprocess(?:ing)?|전처리",
    "Regular Expression": r"regular expressions?|정규\s*표현식",
    "BPE": r"\bBPE\b|byte.pair encoding",
    "N-gram": r"\bn[ -]?grams?\b|엔그램",
    "Language Model": r"language model|언어\s*모델",
    "Smoothing": r"\bsmoothing\b|스무딩|평활화",
    "Perplexity": r"\bperplexity\b|\bPPL\b|퍼플렉시티",
    "Naive Bayes": r"na[iï]ve bayes|나이브\s*베이즈",
    "Logistic Regression": r"logistic regression|로지스틱\s*회귀",
    "Cross-entropy": r"cross[ -]entropy|교차\s*엔트로피",
    "Neural Network": r"neural networks?|신경망",
    "Backpropagation": r"back[ -]?propagation|역전파",
    "RNN": r"\bRNN\b|recurrent neural network|순환\s*신경망",
    "LSTM": r"\bLSTM\b|long short.term memory",
    "Embedding": r"embedding|임베딩",
    "Word2Vec": r"word2vec",
    "CBOW": r"\bCBOW\b|continuous bag.of.words",
    "Skip-gram": r"skip[ -]?gram|스킵그램",
    "Negative Sampling": r"negative sampling|네거티브\s*샘플링",
    "TF-IDF": r"\btf\s*[-–·]?\s*idf\b|term frequency.inverse document frequency",
    "Cosine Similarity": r"cosine similarity|코사인\s*유사도",
    "Text Classification": r"(?:text|document|sentence) classification|(?:텍스트|문서|문장)\s*분류",
    "Attention": r"\battention\b|어텐션",
    "Self-Attention": r"self[ -]attention|셀프\s*어텐션",
    "Multi-Head Attention": r"multi[ -]?head attention|멀티\s*헤드\s*어텐션",
    "Positional Encoding": r"position(?:al)? encodings?|위치\s*인코딩",
    "Transformer": r"\btransformers?\b|트랜스포머",
    "BERT": r"\bBERT\b",
    "GPT": r"\bGPT(?:-\d+)?\b",
    "LLM": r"\bLLMs?\b|large language model|거대\s*언어\s*모델",
    "Pretraining": r"pre[ -]?train(?:ing|ed)?|사전\s*학습",
    "Masked Language Modeling": r"masked language model|\bMLM\b",
    "Fine-tuning": r"fine[ -]?tun(?:e|ed|ing)|미세\s*조정",
    "SFT": r"\bSFT\b|supervised fine[ -]?tuning|지도\s*미세\s*조정",
    "LoRA": r"\bLoRA\b|low[ -]rank adaptation",
    "Quantization": r"quantiz(?:ation|ed)|양자화",
    "Distillation": r"distillation|지식\s*증류",
    "Pruning": r"\bpruning\b|가지치기",
    "NER": r"\bNER\b|named entity recognition|개체명\s*인식",
    "POS Tagging": r"\bPOS\b|part.of.speech tagging|품사\s*태깅",
    "BIO Tagging": r"\b(?:BIO|IOB2)\b",
}
TERMS = {name: re.compile(pattern, re.I) for name, pattern in TERMS.items()}
RELATED = {
    "BPE": ["Tokenization"],
    "Smoothing": ["N-gram"],
    "Perplexity": ["Language Model"],
    "Negative Sampling": ["Word2Vec", "Skip-gram"],
    "Multi-Head Attention": ["Attention", "Transformer"],
    "Positional Encoding": ["Transformer"],
    "Masked Language Modeling": ["BERT", "Pretraining"],
    "LoRA": ["Fine-tuning", "SFT"],
    "BIO Tagging": ["NER"],
}


def poppler(*args):
    return subprocess.check_output(args, cwd=ROOT).decode("utf-8")


def count_scripts(text):
    return len(re.findall(r"[가-힣ᄀ-ᇿㄱ-ㆎ]", text)), len(re.findall(r"[A-Za-z]", text))


def language(ko, en):
    if ko + en == 0:
        return "미확인"
    if ko >= 0.05 * (ko + en) and en >= 0.05 * (ko + en):
        return "혼합"
    return "한국어" if ko > en else "영어"


def extract(path):
    file = path.relative_to(ROOT).as_posix()
    n = int(re.search(r"^Pages:\s+(\d+)", poppler("pdfinfo", file), re.M)[1])
    raw_pages = poppler("pdftotext", "-layout", "-enc", "UTF-8", file, "-").split("\f")
    if raw_pages[-1] == "":
        raw_pages.pop()
    if len(raw_pages) != n:
        raise ValueError(f"PDF page counts disagree: {file}")
    images = collections.Counter()
    for line in poppler("pdfimages", "-list", file).splitlines()[2:]:
        fields = line.split()
        if fields and fields[2] == "image" and int(fields[3]) * int(fields[4]) >= 30_000:
            images[int(fields[0])] += 1
    pages, sequences = [], []
    for number, raw in enumerate(raw_pages, 1):
        raw = unicodedata.normalize("NFKC", raw)
        compact = re.sub(r"\s+", " ", raw).strip()
        ko, en = count_scripts(compact)
        letters = ko + en
        sources = {"file": file, "page": number}
        concepts = [key for key, regex in TERMS.items() if regex.search(compact)]
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        formula = bool(re.search(r"[∑∏∫√∂∇≠≈≤≥∀∈]|\b[\w()]+\s*=\s*[\w(]", raw))
        table_rows = sum(len(re.split(r" {3,}", line)) >= 3 for line in lines)
        heading = lines[0] if lines else ""
        if (number == 1 and letters < 350) or re.fullmatch(
            r"(?:목차|강의\s*목차|contents|table of contents|outline|agenda)", heading, re.I
        ):
            kind = "표지·목차"
        elif letters < 120 and images[number]:
            kind = "정보성 이미지·다이어그램 후보"
        elif formula or table_rows >= 3:
            kind = "수식·표 후보"
        elif letters >= 40:
            kind = "텍스트 중심 후보"
        elif re.search(r"^(?:thank you|감사합니다|questions\??)[.! ]*$", compact, re.I):
            kind = "장식용 후보"
        else:
            kind = "미확인"
        pages.append(
            {
                "source": sources,
                "type": kind,
                "has_text": bool(re.search(r"[^\W_]", compact)),
                "korean_chars": ko,
                "english_chars": en,
                "raster_images": images[number],
                "visual_signal_detected": (
                    letters < 120 or bool(images[number]) or formula or table_rows >= 3
                ),
                "concept_mentions": concepts,
            }
        )
        word_chars = re.sub(r"[^\w]+", "", compact.casefold())
        if len(word_chars) >= 40:
            sequences.append(hashlib.sha256(word_chars.encode()).hexdigest())
    counts = collections.Counter(concept for page in pages for concept in page["concept_mentions"])
    text_pages = sum(page["has_text"] for page in pages)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "source": {"file": file, "page": 1},
        "page_count": n,
        "sha256": digest,
        "language": language(
            sum(p["korean_chars"] for p in pages), sum(p["english_chars"] for p in pages)
        ),
        "text_pages": text_pages,
        "extractable_text_page_ratio": text_pages / n,
        "topic_candidates": [
            {
                "concept": concept,
                "sources": [p["source"] for p in pages if concept in p["concept_mentions"]],
            }
            for concept, _ in counts.most_common(5)
        ],
        "pages": pages,
    }, sequences


def write(name, payload):
    dest = OUT / name
    temp = dest.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(dest)


def stem(source):
    return re.sub(r"\s*\(\d+\)$", "", unicodedata.normalize("NFC", Path(source["file"]).stem))


def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(extract, sorted((ROOT / "NLP").glob("*.pdf"))))
    files = [file for file, _ in results]
    all_pages = [p for f in files for p in f["pages"]]
    by_hash = collections.defaultdict(list)
    for f in files:
        by_hash[f["sha256"]].append(f["source"])
    exact = [sources for sources in by_hash.values() if len(sources) > 1]
    variants = []
    for (left, a), (right, b) in itertools.combinations(results, 2):
        if left["sha256"] == right["sha256"]:
            continue
        same_stem = stem(left["source"]) == stem(right["source"])
        if not same_stem and (
            left["source"] != by_hash[left["sha256"]][0]
            or right["source"] != by_hash[right["sha256"]][0]
        ):
            continue
        matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
        shared = sum(block.size for block in matcher.get_matching_blocks())
        if same_stem or (shared >= 5 and shared >= math.ceil(0.5 * min(len(a), len(b)))):
            variants.append(
                {
                    "sources": [left["source"], right["source"]],
                    "same_stem": same_stem,
                    "shared_ordered_text_pages": shared,
                    "text_signature_page_counts": [len(a), len(b)],
                }
            )
    concepts = {
        term: [p["source"] for p in all_pages if term in p["concept_mentions"]] for term in TERMS
    }
    concepts = {term: sources for term, sources in concepts.items() if sources}
    reviewed = {
        (item["source"]["file"], item["source"]["page"]): item
        for item in json.loads((OUT / "visual_sample" / "sample.json").read_text(encoding="utf-8"))
    }
    gaps = []
    for page in all_pages:
        source = page["source"]
        observation = reviewed.get((source["file"], source["page"]))
        letters = page["korean_chars"] + page["english_chars"]
        if observation:
            status = "표본 판독 완료"
        elif letters < 40 or (letters < 120 and page["raster_images"]):
            status = "우선 시각 검토"
        elif page["visual_signal_detected"]:
            status = "후순위 시각 검토"
        else:
            status = "자동 선별 신호 없음"
        page["visual_screening_status"] = status
        if status != "자동 선별 신호 없음":
            gaps.append({"type": status, "source": source})
    for term, related in RELATED.items():
        for f in files:
            matches = [p["source"] for p in f["pages"] if term in p["concept_mentions"]]
            if matches:
                continue
            sources = [
                p["source"] for p in f["pages"] if any(x in p["concept_mentions"] for x in related)
            ]
            if sources:
                gaps.append(
                    {
                        "type": "정의·원리 누락 확인 후보",
                        "concept": term,
                        "related_concepts": related,
                        "sources": sources,
                    }
                )
    write(
        "inventory.json",
        {"files": files, "exact_duplicates": exact, "version_candidates": variants},
    )
    write(
        "concepts.json",
        [{"concept": term, "sources": sources} for term, sources in concepts.items()],
    )
    write("review_candidates.json", gaps)
    print(
        json.dumps(
            {
                "files": len(files),
                "unique": len(by_hash),
                "pages": len(all_pages),
                "text_pages": sum(p["has_text"] for p in all_pages),
                "languages": collections.Counter(f["language"] for f in files),
                "types": collections.Counter(p["type"] for p in all_pages),
                "exact_groups": len(exact),
                "version_pairs": len(variants),
                "concepts": len(concepts),
                "review_types": collections.Counter(g["type"] for g in gaps),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
