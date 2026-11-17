r"""
Ask ONE question and read what comes back. For building intuition, not for scoring.

Run from the app folder, e.g.:
    .\.venv\Scripts\python.exe rag_lab\src\ask.py "What is a residual?"
    .\.venv\Scripts\python.exe rag_lab\src\ask.py "How many items must a shop sell before it stops losing money?" --chunker structure --exclude summary,front_back,case_study,solutions,formulas --retriever hybrid --rerank

Prints the top chunks with their book, pages, section/kind (Level 4c) and score, plus the start
of their text. "matched" lists the question's words found in the chunk: with dense or hybrid
retrieval a chunk can rank high with NO matched words, which is the point of meaning search.
"""

from __future__ import annotations

import argparse

from bm25 import BM25Index
from common import load_pages, load_testset, tokenize, use_utf8_output
from evaluate import CHUNKERS, build_chunks
from retrievers import RETRIEVERS, make_retriever


def main() -> None:
    use_utf8_output()
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--chunker", default="fixed", choices=sorted(CHUNKERS))
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--overlap", type=int, default=0)
    parser.add_argument("--headers", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--retriever", default="bm25", choices=RETRIEVERS)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--pages", default="raw", choices=["raw", "clean"])
    parser.add_argument("--show", type=int, default=3, help="how many chunks to print")
    parser.add_argument("--chars", type=int, default=500, help="how much of each chunk to print")
    args = parser.parse_args()

    exclude = {k.strip() for k in args.exclude.split(",") if k.strip()}
    pages = load_pages(load_testset()["books_indexed"], args.pages)
    chunks = build_chunks(pages, args.chunker, args.size, args.overlap, args.headers, exclude)
    retriever = make_retriever(chunks, args.retriever, args.rerank)
    vocabulary = BM25Index(chunks).postings                  # only to report which words exist
    words = tokenize(args.question)
    print(f"\nQuestion: {args.question}")
    print(f"Search words after tokenizing: {words}")
    print(f"Words that never appear in the books: {[w for w in words if w not in vocabulary] or 'none'}\n")

    for rank, (chunk, score) in enumerate(retriever.search(args.question, k=args.show), start=1):
        matched = sorted({w for w in words if w in set(tokenize(chunk.text))})
        print(f"#{rank}  score {score:.3f}  {chunk.book} pages {chunk.first_page}-{chunk.last_page}  "
              f"kind: {chunk.kind}  matched: {matched}")
        if chunk.section:
            print(f"    section: {chunk.section}")
        print("    " + chunk.text[:args.chars].replace("\n", " ") + " ...\n")


if __name__ == "__main__":
    main()
