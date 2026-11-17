"""
Retrieval benchmark: is semantic (embedding) search needed, or is the simple
lexical FTS5 baseline good enough for this corpus?

Each question is written the way a student might ask it, often WITHOUT the
note's exact words (paraphrases are where lexical search should struggle).
For each retriever we report hit@1 and hit@3: how often the expected note is
the top result, or among the top three.

Run:  python scripts/retrieval_benchmark.py
The questions and expected notes are a small synthetic set (12 queries), so
the result is indicative only. Re-run when the real course notes are added.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qmtutor.llm.providers import FakeProvider              # noqa: E402
from qmtutor.retrieval.search import EmbeddingRetriever, LexicalRetriever   # noqa: E402
from qmtutor.seed import seed                                # noqa: E402
from qmtutor.services.context import build_context, load_settings   # noqa: E402

BENCHMARK = [
    ("How do I get the unknown by itself in an equation?", "equations_functions#solving-linear-equations"),
    ("What does it mean to make a letter the subject?", "equations_functions#rearranging-formulae"),
    ("How do I work out profit from price and costs?", "equations_functions#cost-revenue-and-profit"),
    ("How many items must a business sell so it does not lose money?", "equations_functions#break-even-analysis"),
    ("When does the shop stop making a loss?", "equations_functions#break-even-analysis"),
    ("Interest only on the money I first put in", "interest#simple-interest"),
    ("Why does my savings balance grow faster each year?", "interest#compound-interest"),
    ("What if the bank adds interest every month instead of every year?", "interest#compound-interest"),
    ("How much is money I will get in 3 years worth today?", "interest#present-value-and-discounting"),
    ("What is a discount factor?", "interest#present-value-and-discounting"),
    ("I forgot to change 8% into a decimal", "interest#simple-interest"),
    ("Do the same thing to both sides", "equations_functions#solving-linear-equations"),
]


def evaluate(name, retriever):
    hit1 = hit3 = 0
    misses = []
    started = time.perf_counter()
    for query, expected in BENCHMARK:
        ids = [p.note_id for p in retriever.search(query, 3)]
        hit1 += bool(ids) and ids[0] == expected
        hit3 += expected in ids
        if expected not in ids:
            misses.append(query)
    ms = (time.perf_counter() - started) * 1000 / len(BENCHMARK)
    n = len(BENCHMARK)
    print(f"{name:<10} hit@1 {hit1}/{n} ({hit1 / n:.0%})   hit@3 {hit3}/{n} ({hit3 / n:.0%})   {ms:.1f} ms/query")
    for query in misses:
        print(f"           missed: {query}")
    return hit1, hit3


if __name__ == "__main__":
    ctx = build_context(load_settings(), db_path=":memory:", provider=FakeProvider())
    seed(ctx)
    print(f"Corpus: {ctx.db.query_one('SELECT COUNT(*) n FROM knowledge_note')['n']} approved passages\n")
    evaluate("lexical", LexicalRetriever(ctx.db))
    load_started = time.perf_counter()
    embedding = EmbeddingRetriever(ctx.db)
    print(f"(embedding model loaded in {time.perf_counter() - load_started:.1f} s)")
    evaluate("embedding", embedding)
