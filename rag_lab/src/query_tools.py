"""
Level 2 (part 1): improve the student's QUESTION before searching.

Steps 2.1-2.3 of the plan, as five modes of one retriever wrapper:

    spell      2.1  correct misspelled words using the books' own vocabulary (no AI)
    rewrite    2.2  AI rewrites the question as one clear question in textbook terms
    multi      2.2  AI writes 3 alternative search queries
    hyde       2.2  AI writes a short imaginary TEXTBOOK PARAGRAPH that would answer it;
                    we search with that paragraph (it "sounds like" the book)
    decompose  2.3  AI splits a multi-part question into simple questions; results from
                    EVERY part are kept, so two-part answers get both halves

SAFETY RULE: the ORIGINAL question is always searched too, and the results are merged.
A bad rewrite can add noise but cannot remove what the original search found.

Merging: for spell/rewrite/multi/hyde, Reciprocal Rank Fusion (the same method as hybrid).
For decompose, results are taken in turn from each part ("round robin"), so every part is
represented near the top instead of one part crowding out the other.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from common import Chunk
from llm import DEFAULT_MODEL, generate, generate_json

MODES = ("none", "spell", "rewrite", "multi", "hyde", "decompose")
POOL = 30          # results taken from each query variant before merging
RRF_K = 60

# -
# The prompts. Short and explicit, because small models follow simple instructions best.
# -
CONTEXT = ("You help university students search their Business Mathematics and Statistics "
           "textbooks (topics: percentages, interest, annuities, loans, bonds, break-even, "
           "markup, taxes, descriptive statistics, probability, sampling, confidence "
           "intervals, hypothesis tests, regression).")

REWRITE_PROMPT = CONTEXT + """
Rewrite the student's question as ONE clear, correctly spelled question that uses standard textbook terms.
Keep exactly the same meaning. Do not answer it. Do not add new topics, contexts or examples that the student did not mention.
Only mention a formula if the student asked for one.
Reply with the rewritten question only.

Student question: {q}
Rewritten question:"""

MULTI_PROMPT = CONTEXT + """
Write 3 different short search queries that would find the textbook section answering the student's question.
Use textbook terminology. Do not answer the question.
Reply in JSON exactly like: {{"queries": ["...", "...", "..."]}}

Student question: {q}"""

HYDE_PROMPT = CONTEXT + """
Write a short paragraph (2 to 3 sentences) as it might appear in a textbook, explaining the concept the student is asking about.
Use the textbook's technical terms. Do not mention the student. Do not use bullet points.

Student question: {q}
Textbook paragraph:"""

DECOMPOSE_PROMPT = CONTEXT + """
If the student's question asks about more than one concept or step, split it into separate simple questions (at most 3).
If it asks about only one thing, return it unchanged as a single question. Do not answer.
Reply in JSON exactly like: {{"questions": ["...", "..."]}}

Student question: {q}"""


# =
# 2.1 Spell correction against the books' vocabulary (no AI)
# =
class SpellCorrector:
    """
    Plain language: collect every word that appears in the books. For each word of the
    question that is NOT in that list, look for the most similar book word (same first
    letter, similar length, at least 80% similar) and swap it in. "intrest" -> "interest".

    Why the books' vocabulary and not a general dictionary: the books define what can be
    found, and it already contains the course's technical words (amortization, annuity).
    """

    def __init__(self, chunks: list[Chunk], min_count: int = 2):
        counts = Counter(w for c in chunks for w in re.findall(r"[a-z]+", c.text.lower()))
        self.vocabulary = {w: n for w, n in counts.items() if n >= min_count and len(w) > 1}
        self.by_first_letter: dict[str, list[str]] = defaultdict(list)
        for word in self.vocabulary:
            self.by_first_letter[word[0]].append(word)

    def correct_word(self, word: str) -> str:
        lower = word.lower()
        if len(lower) < 4 or not lower.isalpha() or lower in self.vocabulary:
            return word                      # short, numeric or already known: leave it
        best, best_key = None, (0.8, 0)      # must be at least 80% similar
        for candidate in self.by_first_letter.get(lower[0], []):
            if abs(len(candidate) - len(lower)) > 2:
                continue
            # compare (similarity, how common the word is in the books): most similar wins,
            # and between equally similar words the more frequent one wins
            key = (SequenceMatcher(None, lower, candidate).ratio(), self.vocabulary[candidate])
            if key[0] >= 0.8 and key > best_key:
                best, best_key = candidate, key
        return best or word

    def correct(self, question: str) -> str:
        return re.sub(r"[A-Za-z]+", lambda m: self.correct_word(m.group(0)), question)


# =
# The wrapper: turns one question into several queries, searches each, merges
# =
class QueryExpandingRetriever:
    def __init__(self, base, chunks: list[Chunk], mode: str, model: str = DEFAULT_MODEL):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.base, self.mode, self.model = base, mode, model
        self.speller = SpellCorrector(chunks) if mode == "spell" else None
        self.last_variants: list[str] = []   # kept so evaluate.py can record what was searched

    def variants(self, question: str) -> list[str]:
        """The extra queries for this mode (the original question is added separately)."""
        if self.mode == "spell":
            corrected = self.speller.correct(question)
            return [corrected] if corrected != question else []
        if self.mode == "rewrite":
            return _clean_lines(generate(REWRITE_PROMPT.format(q=question), self.model))[:1]
        if self.mode == "multi":
            return _strings(generate_json(MULTI_PROMPT.format(q=question), self.model).get("queries"))[:3]
        if self.mode == "hyde":
            paragraph = generate(HYDE_PROMPT.format(q=question), self.model).strip()
            return [paragraph] if paragraph else []
        if self.mode == "decompose":
            return _strings(generate_json(DECOMPOSE_PROMPT.format(q=question), self.model).get("questions"))[:3]
        return []

    def search(self, question: str, k: int = 10) -> list[tuple[Chunk, float]]:
        extra = [v for v in self.variants(question)
                 if v.strip() and v.strip() != question.strip() and not _is_refusal(v)]
        self.last_variants = extra
        queries = [question] + extra
        result_lists = [self.base.search(q, POOL) for q in queries]
        if self.mode == "decompose" and len(extra) > 1:
            return _round_robin(result_lists[1:] + result_lists[:1], k)   # each part first, original last
        return _rrf(result_lists, k)


def _rrf(result_lists, k):
    fused: dict[str, float] = defaultdict(float)
    by_id: dict[str, Chunk] = {}
    for results in result_lists:
        for rank, (chunk, _) in enumerate(results, start=1):
            fused[chunk.chunk_id] += 1 / (RRF_K + rank)
            by_id[chunk.chunk_id] = chunk
    best = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:k]
    return [(by_id[i], score) for i, score in best]


def _round_robin(result_lists, k):
    """Take the 1st result of each list, then the 2nd of each, ... skipping duplicates."""
    merged, seen = [], set()
    for position in range(POOL):
        for results in result_lists:
            if position < len(results):
                chunk, score = results[position]
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    merged.append((chunk, 1 / (RRF_K + position + 1)))
        if len(merged) >= k:
            break
    return merged[:k]


def _clean_lines(text: str) -> list[str]:
    """First non-empty line, without quotes or a leading label like 'Rewritten question:'."""
    lines = [re.sub(r"^(rewritten question|question)\s*:\s*", "", l.strip(), flags=re.I).strip(' "\'')
             for l in text.splitlines() if l.strip()]
    return lines


_REFUSAL = re.compile(r"^\W*(i can'?t|i cannot|i am unable|i'm unable|i'm sorry|sorry|as an ai)\b", re.I)


def _is_refusal(text: str) -> bool:
    """
    Small models sometimes refuse instead of rewriting ("I can't help with that.").
    Seen 13 Oct for "What is Machine Learning?". Such text must not be searched as a query.
    """
    return bool(_REFUSAL.match(text.strip()))


def _strings(value) -> list[str]:
    return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []
