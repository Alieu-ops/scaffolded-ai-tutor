r"""
Score one retrieval setup against the test set. This is how we detect improvement.

Run from the app folder, e.g.:
    .\.venv\Scripts\python.exe rag_lab\src\evaluate.py --chunker fixed --size 1000

What it does, in order:
    1. load the extracted pages of the books named in the test set
    2. cut them into chunks with the chosen chunker
    3. build a BM25 index over the chunks
    4. ask every test question, keep the top 10 chunks
    5. a chunk is a HIT if its book matches and its pages overlap the expected pages
    6. compute the scores, print them, and save two CSV files (Excel-friendly):
         output/results/<label>_questions.csv   one row per question (what came back, rank)
         output/results/summary.csv             one row per run (append), to compare levels

The metrics (all between 0 and 1, higher is better):
    Hit@k  share of answerable questions with a correct chunk in the top k (k = 1, 3, 5)
    MRR    mean of 1/rank of the first correct chunk (1st -> 1, 2nd -> 0.5, 3rd -> 0.33,
           not in the top 10 -> 0). Rewards putting the right chunk near the top.
    "Absent" questions have no right chunk; for them we report how often the system
    correctly returned nothing, and their average top score (compare with answerable ones:
    if absent questions score as high, a score threshold cannot separate them).
"""

from __future__ import annotations

import argparse
import csv
import statistics
import time

from chunkers import fixed_size, recursive, semantic, structure
from common import CHUNKS_DIR, RESULTS_DIR, Chunk, load_pages, load_testset, use_utf8_output
from llm import DEFAULT_MODEL, check_ollama
from query_tools import MODES, QueryExpandingRetriever
from retrievers import RETRIEVERS, DiversifyRetriever, Reranked, make_retriever

# Each chunking method registered by name (for the command line) with its level (for labels).
CHUNKERS = {
    "fixed": ("L5", fixed_size),        # becomes "L4a" when --overlap is above 0
    "recursive": ("L4b", recursive),
    "structure": ("L4c", structure),
    "semantic": ("L4d", semantic),
}
TOP_K = 10


def build_chunks(pages, chunker: str, size: int, overlap: int = 0, headers: bool = False,
                 exclude: set[str] = frozenset()) -> list[Chunk]:
    """Run the chosen chunker, then drop chunks whose kind is excluded (only 4c sets kinds)."""
    chunks = CHUNKERS[chunker][1](pages, size=size, overlap=overlap, headers=headers)
    return [c for c in chunks if c.kind not in exclude]


def run_label(chunker: str, size: int, overlap: int, headers: bool, exclude: set[str],
              retriever: str = "bm25", rerank: bool = False) -> str:
    """
    A readable name for the run, e.g. "L3b-hybrid+rerank-structure-1000-ov0-excl-...".
    The level is the highest one used: a re-ranker makes it 3c, hybrid 3b, dense 3a;
    with plain BM25 the chunker decides (5, 4a, 4b, 4c, 4d).
    """
    if rerank:
        level = "L3c"
    elif retriever == "hybrid":
        level = "L3b"
    elif retriever == "dense":
        level = "L3a"
    else:
        level = "L4a" if chunker == "fixed" and overlap > 0 else CHUNKERS[chunker][0]
    search = "" if retriever == "bm25" and not rerank else f"{retriever}{'+rerank' if rerank else ''}-"
    label = f"{level}-{search}{chunker}-{size}-ov{overlap}"
    if headers:
        label += "-headers"
    if exclude:
        label += "-excl-" + "+".join(sorted(exclude))
    return label


def is_hit(chunk: Chunk, expected: list[dict]) -> bool:
    """True if the chunk is from an expected book and its page span overlaps an expected range."""
    for target in expected:
        low, high = target["pages"]
        # Two ranges [a, b] and [c, d] overlap when a <= d and b >= c.
        if chunk.book == target["book"] and chunk.first_page <= high and chunk.last_page >= low:
            return True
    return False


def main() -> None:
    use_utf8_output()
    parser = argparse.ArgumentParser(description="Score a retrieval setup on the RAG lab test set.")
    parser.add_argument("--chunker", default="fixed", choices=sorted(CHUNKERS))
    parser.add_argument("--size", type=int, default=1000, help="characters per chunk")
    parser.add_argument("--overlap", type=int, default=0, help="characters repeated between chunks")
    parser.add_argument("--headers", action="store_true",
                        help="4c only: put the section path at the top of each chunk")
    parser.add_argument("--exclude", default="",
                        help="4c only: comma-separated kinds to leave out, e.g. summary,front_back")
    parser.add_argument("--retriever", default="bm25", choices=RETRIEVERS,
                        help="bm25 = words (Levels 5/4); dense = meaning (3a); hybrid = both (3b)")
    parser.add_argument("--rerank", action="store_true", help="Level 3c: re-rank the top 20 with a cross-encoder")
    parser.add_argument("--testset", default="dev",
                        help="dev = questions.yaml; heldout = questions_heldout.yaml; "
                             "or any testset/<name>.yaml, e.g. v2_dev, v2_heldout")
    parser.add_argument("--pages", default="raw", choices=["raw", "clean"],
                        help="raw = text as extracted; clean = after clean.py")
    parser.add_argument("--query", default="none", choices=MODES,
                        help="Level 2: improve the question before searching (spell, rewrite, multi, hyde, decompose)")
    parser.add_argument("--llm", default=DEFAULT_MODEL, help="local Ollama model for the AI query modes")
    parser.add_argument("--final-rerank", action="store_true",
                        help="Level 2: after the query step, re-rank the top 20 against the ORIGINAL question")
    parser.add_argument("--max-per-section", type=int, default=0,
                        help="Level 2: keep at most N chunks per section near the top (0 = off)")
    parser.add_argument("--neighbours", type=int, default=0,
                        help="Level 2: add the next section's first chunk after each of the top N results (0 = off)")
    parser.add_argument("--dump", action="store_true",
                        help="also save every chunk to output/chunks/<run>.csv so you can read them")
    args = parser.parse_args()
    exclude = {k.strip() for k in args.exclude.split(",") if k.strip()}
    label = run_label(args.chunker, args.size, args.overlap, args.headers, exclude, args.retriever, args.rerank)
    if args.pages == "clean":
        label += "-clean"
    if args.query != "none":
        # e.g. "L2-rewrite-llama3.2_3b-L3b-hybrid-..." : Level 2 query step on top of the rest
        model_tag = "" if args.query == "spell" else "-" + args.llm.replace(":", "_")
        label = f"L2-{args.query}{model_tag}-{label}"
        if args.query != "spell":
            check_ollama(args.llm)              # stop early if Ollama or the model is missing
    if args.final_rerank:
        label += "-frr"
    if args.max_per_section:
        label += f"-div{args.max_per_section}"
    if args.neighbours:
        label += f"-nb{args.neighbours}"
    if args.testset == "heldout":
        label += "-HELDOUT"
    elif args.testset != "dev":
        label += f"-{args.testset.upper()}"          # e.g. "-V2_DEV", "-V2_HELDOUT"

    # Steps 1-3: load, chunk, index (timed, because cost matters on a CPU server).
    # For dense/hybrid this includes embedding all chunks; a second run reuses the saved
    # embeddings, so index_seconds is much lower then.
    testset = load_testset(args.testset)
    pages = load_pages(testset["books_indexed"], args.pages)
    started = time.perf_counter()
    chunks = build_chunks(pages, args.chunker, args.size, args.overlap, args.headers, exclude)
    index = make_retriever(chunks, args.retriever, args.rerank)
    if args.query != "none":
        index = QueryExpandingRetriever(index, chunks, args.query, args.llm)
    if args.final_rerank:
        index = Reranked(index)                  # sees the original question, not the HyDE paragraph
    if args.max_per_section or args.neighbours:
        index = DiversifyRetriever(index, chunks, args.max_per_section, args.neighbours)
    index_seconds = time.perf_counter() - started
    if args.dump:
        dump_chunks(chunks, CHUNKS_DIR / f"{label}.csv")

    # Step 4-5: ask every question
    rows = []
    for q in testset["questions"]:
        started = time.perf_counter()
        results = index.search(q["question"], k=TOP_K)
        query_ms = (time.perf_counter() - started) * 1000
        hit_ranks = [rank for rank, (chunk, _) in enumerate(results, start=1) if is_hit(chunk, q["expected"])]
        first = hit_ranks[0] if hit_ranks else None
        top_chunk, top_score = results[0] if results else (None, 0.0)
        # Stricter measure for questions with 2+ expected sections: is EVERY one found in the top 5?
        top5 = [chunk for chunk, _ in results[:5]]
        all_found = all(any(is_hit(c, [target]) for c in top5) for target in q["expected"]) if q["expected"] else False
        rows.append({
            "id": q["id"], "type": q["type"], "subtype": q.get("subtype", ""), "style": q.get("style", ""),
            "question": q["question"],
            "first_hit_rank": first or "",
            "hit@1": int(first is not None and first <= 1),
            "hit@3": int(first is not None and first <= 3),
            "hit@5": int(first is not None and first <= 5),
            "reciprocal_rank": round(1 / first, 3) if first else 0,
            "all_expected@5": int(all_found),
            "results_returned": len(results),
            "top_score": round(top_score, 3),   # 3 decimals: dense scores lie between 0 and 1
            "top_chunk": f"{top_chunk.book} p{top_chunk.first_page}-{top_chunk.last_page}" if top_chunk else "",
            "top_kind": top_chunk.kind if top_chunk else "",
            "top_section": top_chunk.section[:70] if top_chunk else "",
            "expected": "; ".join(f"{e['book']} p{e['pages'][0]}-{e['pages'][1]}" for e in q["expected"]),
            "query_ms": round(query_ms, 1),
            # what the Level 2 step actually searched with, besides the original question
            "query_variants": " || ".join(getattr(index, "last_variants", []))[:600],
        })

    # Step 6: summarise. Absent questions are excluded from Hit@k and MRR (they have no right answer).
    answerable = [r for r in rows if r["type"] != "absent"]
    absent = [r for r in rows if r["type"] == "absent"]

    def mean(values):
        return round(statistics.mean(values), 3) if values else 0

    summary = {
        "label": label, "pages": args.pages, "chunks": len(chunks), "index_seconds": round(index_seconds, 2),
        "hit@1": mean([r["hit@1"] for r in answerable]),
        "hit@3": mean([r["hit@3"] for r in answerable]),
        "hit@5": mean([r["hit@5"] for r in answerable]),
        "mrr": mean([r["reciprocal_rank"] for r in answerable]),
    }
    # Hit@3 for every answerable question type present (v2 adds grammar_error, spelling_error)
    kinds = ["direct", "paraphrase", "spanning"] + sorted({r["type"] for r in answerable} - {"direct", "paraphrase", "spanning"})
    for kind in kinds:
        of_kind = [r for r in rows if r["type"] == kind]
        summary[f"{kind}_hit@3"] = mean([r["hit@3"] for r in of_kind])
    spanning = [r for r in rows if r["type"] == "spanning"]
    summary["spanning_both@5"] = mean([r["all_expected@5"] for r in spanning])
    summary["questions"] = len(rows)
    # Lesson 2 of Level 5: how often is the TOP result a summary/contents/etc. page?
    # (Only the structure chunker knows kinds; for the others this is always 0.)
    summary["top1_not_content"] = mean([int(r["top_kind"] not in ("", "content")) for r in answerable])
    summary["no_answer_accuracy"] = mean([int(r["results_returned"] == 0) for r in absent])
    summary["avg_top_score_answerable"] = mean([r["top_score"] for r in answerable])
    summary["avg_top_score_absent"] = mean([r["top_score"] for r in absent])
    summary["avg_query_ms"] = mean([r["query_ms"] for r in rows])
    summary["testset_status"] = testset.get("status", "")

    # Save the CSV files
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    per_question = RESULTS_DIR / f"{label}_questions.csv"
    with per_question.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    append_summary(RESULTS_DIR / "summary.csv", summary)
    summary_file = RESULTS_DIR / "summary.csv"

    # Print a short report
    print(f"\n{label}: {len(chunks)} chunks, indexed in {summary['index_seconds']} s "
          f"(test set {summary['testset_status']})\n")
    print(f"{'id':<5}{'type':<12}{'rank':>5}  {'top chunk':<22}{'kind':<11}{'score':>7}  expected")
    for r in rows:
        print(f"{r['id']:<5}{r['type']:<12}{str(r['first_hit_rank'] or '-'):>5}  {r['top_chunk']:<22}"
              f"{r['top_kind']:<11}{r['top_score']:>7}  {r['expected']}")
    print("\nAnswerable questions:  Hit@1 {hit@1}  Hit@3 {hit@3}  Hit@5 {hit@5}  MRR {mrr}".format(**summary))
    print("Hit@3 by type:  direct {direct_hit@3}  paraphrase {paraphrase_hit@3}  spanning {spanning_hit@3}".format(**summary))
    print("Absent questions:  correctly returned nothing {no_answer_accuracy};  average top score "
          "{avg_top_score_absent} (answerable: {avg_top_score_answerable})".format(**summary))
    print(f"Average query time {summary['avg_query_ms']} ms")
    print(f"\nSaved: {per_question}\n       {summary_file}")


def dump_chunks(chunks: list[Chunk], path) -> None:
    """
    Chunks normally live only in memory for the duration of a run. This saves them as a CSV
    (one row per chunk) so they can be read in Excel or VS Code. Git-ignored: contains book text.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:      # utf-8-sig: Excel shows symbols correctly
        writer = csv.writer(f)
        writer.writerow(["chunk_id", "book", "first_page", "last_page", "kind", "section", "characters", "text"])
        for c in chunks:
            writer.writerow([c.chunk_id, c.book, c.first_page, c.last_page, c.kind, c.section, len(c.text), c.text])
    print(f"Chunks saved to {path}")


def append_summary(path, summary: dict) -> None:
    """
    Add one row to summary.csv. If this run has columns that older rows lack (we add metrics
    as the lab grows), rewrite the file with the combined columns so nothing shifts out of place.
    """
    old_rows, columns = [], list(summary)
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            old_rows = list(reader)
            columns = list(reader.fieldnames or []) + [c for c in summary if c not in (reader.fieldnames or [])]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(old_rows + [summary])


if __name__ == "__main__":
    main()
