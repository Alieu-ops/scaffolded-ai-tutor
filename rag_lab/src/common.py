"""
Shared building blocks for every level of the RAG lab.

READ THIS FILE FIRST. It defines:
    - where things live on disk (the paths)
    - the two "shapes" of data we pass around: a Page and a Chunk
    - how text is split into words for searching (tokenize)
    - how to load the extracted pages and the test set

Nothing here searches or scores anything; the other files do that.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# -
# 1. Paths. Path(__file__) is this file; .parents[1] goes up two levels: src -> rag_lab.
# -
LAB = Path(__file__).resolve().parents[1]          # .../app/rag_lab
PAGES_DIR = LAB / "output" / "pages"              # written by extract.py (git-ignored)
PAGES_CLEAN_DIR = LAB / "output" / "pages_clean"  # written by clean.py: same pages, noise removed
CHUNKS_DIR = LAB / "output" / "chunks"            # written by evaluate.py --dump, to inspect chunks
RESULTS_DIR = LAB / "output" / "results"          # written by evaluate.py (git-ignored)
TOC_DIR = LAB / "output" / "toc"                  # written by toc.py: each book's table of contents
TESTSET = LAB / "testset" / "questions.yaml"      # the questions and their expected pages


# -
# 2. Data shapes. A @dataclass is a small class that just holds named values.
#    frozen=True means the values cannot be changed after creation (safer).
# -
@dataclass(frozen=True)
class Page:
    """One page of extracted text, exactly as extract.py saved it."""
    book: str        # book id, e.g. "olivier"
    page: int        # PDF page number (1 = first page of the file)
    text: str


@dataclass(frozen=True)
class Chunk:
    """
    One searchable piece of a book. Every chunking method produces these.
    first_page/last_page record where the piece came from, so (a) the tutor can cite it
    and (b) the evaluation can check it against the test set's expected pages.
    """
    chunk_id: str     # e.g. "olivier-00042" (book + running number)
    book: str
    first_page: int
    last_page: int    # same as first_page unless the chunk crosses a page boundary
    text: str
    # Filled in only by the structure-aware chunker (Level 4c); others leave the defaults.
    section: str = ""          # e.g. "Chapter 5: ... > 5.2: Break-Even Analysis"
    kind: str = "content"      # content | summary | case_study | solutions | front_back | formulas


# -
# 3. Tokenizing: turning text into a list of words ("tokens") for word search.
# -
# Very common words carry almost no meaning for search ("the", "how"), so we drop them.
# This list is deliberately short and plain; a longer list is one of the things we can test.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how",
    "i", "if", "in", "into", "is", "it", "its", "me", "my", "of", "on", "or", "so", "that", "the",
    "their", "then", "there", "this", "to", "was", "we", "what", "when", "where", "which", "why",
    "will", "with", "you", "your",
}
_WORD = re.compile(r"[a-z0-9]+")   # a "word" = a run of letters or digits


def tokenize(text: str) -> list[str]:
    """
    'How do you calculate the break-even point?' -> ['calculate', 'break', 'even', 'point']

    Steps: lower-case everything, pull out runs of letters/digits, drop stopwords.
    Note what is NOT done at Level 5: "loans" and "loan" stay different words (no stemming),
    and "profit"/"gain" are unrelated words (no synonyms). Those gaps are what later levels fix.
    """
    return [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS]


# -
# 4. Loading data from disk.
# -
def load_pages(books: list[str], variant: str = "raw") -> list[Page]:
    """
    Read <book>.jsonl for each book (one JSON object per line).
    variant="raw"   -> output/pages        (as extracted)
    variant="clean" -> output/pages_clean  (after clean.py)
    """
    folder, maker = (PAGES_DIR, "extract.py") if variant == "raw" else (PAGES_CLEAN_DIR, "clean.py")
    pages: list[Page] = []
    for book in books:
        path = folder / f"{book}.jsonl"
        if not path.exists():
            raise SystemExit(f"Missing {path}. Run rag_lab/src/{maker} first.")
        with path.open(encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                pages.append(Page(record["book"], record["page"], record["text"]))
    return pages


def load_testset(name: str = "dev") -> dict:
    """
    The YAML test set as a Python dictionary: {'books_indexed': [...], 'questions': [...]}.
    name="dev"     -> testset/questions.yaml          (first 30 questions, used for tuning)
    name="heldout" -> testset/questions_heldout.yaml  (first 20 held-out questions)
    any other name -> testset/<name>.yaml             (e.g. "v2_dev", "v2_heldout")
    """
    files = {"dev": "questions.yaml", "heldout": "questions_heldout.yaml"}
    path = TESTSET.with_name(files.get(name, f"{name}.yaml"))
    if not path.exists():
        raise SystemExit(f"No test set {path}.")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def use_utf8_output() -> None:
    """
    The Windows terminal uses an old character set by default and crashes on symbols such
    as '−' or 'σ' that appear in the books. This switches printing to UTF-8 and replaces
    anything it still cannot show with '?' instead of crashing.
    """
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
