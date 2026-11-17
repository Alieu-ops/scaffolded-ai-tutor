r"""
RAG lab, step 1 (shared by every level): turn each PDF into plain text, one record per page.

Why a separate step: extraction is slow and the same for every chunking method, so it runs
once and later levels read its output. Keeping the page number with the text means any
chunk can later say which pages it came from, which is how the test set marks a hit.

Run from the app folder:
    .\.venv\Scripts\python.exe rag_lab\src\extract.py            (all books, skips ones already done)
    .\.venv\Scripts\python.exe rag_lab\src\extract.py --force    (redo all)

Output: rag_lab/output/pages/<book id>.jsonl  (git-ignored: it contains book text)
Each line: {"book": "olivier", "page": 12, "label": "4", "extractor": "pypdf", "text": "..."}
    extractor = which PDF reader produced the text (pypdf, or the pymupdf fallback)
    page  = position in the PDF file (1 = first page of the file)
    label = the page number printed in the book, when the PDF records it (may be missing)
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml
from pypdf import PdfReader

LAB = Path(__file__).resolve().parents[1]                       # .../app/rag_lab
OUTPUT = LAB / "output" / "pages"
REPORT = LAB / "output" / "extract_report.csv"                  # one readable row per book
DEFAULT_BOOKS_DIR = LAB.parents[1] / "materials" / "textbooks"  # .../AI_TUTOR_GUIDED_BUILD/materials/textbooks


class _WarningCounter(logging.Handler):
    """pypdf reports font problems as log warnings (very long ones). Count them instead of printing them."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record):
        self.count += 1


WARNINGS = _WarningCounter()
_pypdf_log = logging.getLogger("pypdf")
_pypdf_log.addHandler(WARNINGS)
_pypdf_log.propagate = False            # keep them out of the terminal


def load_books() -> list[dict]:
    return yaml.safe_load((LAB / "books.yaml").read_text(encoding="utf-8"))["books"]


def books_dir() -> Path:
    """Where the PDFs are. An environment variable allows another location without editing code."""
    return Path(os.environ.get("RAG_LAB_BOOKS", DEFAULT_BOOKS_DIR))


def page_labels(reader: PdfReader) -> list[str | None]:
    """Printed page numbers, if the PDF defines them; otherwise None for every page."""
    try:
        return list(reader.page_labels)
    except Exception:          # some PDFs have broken label tables; extraction must still work
        return [None] * len(reader.pages)


def extract_book(book: dict, force: bool = False) -> dict | None:
    """Extract one book and return its summary row (None if skipped or missing)."""
    source = books_dir() / book["file"]
    target = OUTPUT / f"{book['id']}.jsonl"
    if target.exists() and not force:
        print(f"  {book['id']:<9} already extracted (use --force to redo)")
        return None
    if not source.exists():
        print(f"  {book['id']:<9} MISSING: {source}")
        return None

    start, warnings_before = time.perf_counter(), WARNINGS.count
    reader = PdfReader(source)
    labels = page_labels(reader)
    fallback = None                         # second PDF reader, opened only if pypdf fails on a page
    empty_pages, failed_pages, fallback_pages, chars = [], [], [], 0
    with target.open("w", encoding="utf-8") as out:
        for number, page in enumerate(reader.pages, start=1):
            extractor = "pypdf"
            try:
                text = page.extract_text() or ""
            except Exception:               # one bad page should not stop the whole book
                # Seen 13 Oct: 139 Anderson pages crash pypdf ("More than one /FontFile") although
                # they are normal text pages. PyMuPDF tolerates that font defect, so try it next.
                fallback = fallback or _open_fallback(source)
                text = _fallback_text(fallback, number)
                if text is None:
                    failed_pages.append(number)
                    text = ""
                else:
                    extractor = "pymupdf"
                    fallback_pages.append(number)
            if not text.strip():
                empty_pages.append(number)
            chars += len(text)
            out.write(json.dumps({"book": book["id"], "page": number, "label": labels[number - 1],
                                  "extractor": extractor, "text": text}, ensure_ascii=False) + "\n")
    row = {"book": book["id"], "pages": len(reader.pages), "empty_pages": len(empty_pages),
           "failed_pages": len(failed_pages), "fallback_pages": len(fallback_pages), "characters": chars,
           "seconds": round(time.perf_counter() - start, 1), "pdf_warnings": WARNINGS.count - warnings_before,
           "empty_page_list": " ".join(map(str, empty_pages[:60])) + (" ..." if len(empty_pages) > 60 else "")}
    print(f"  {row['book']:<9} {row['pages']:4} pages, {row['empty_pages']:3} empty, {row['failed_pages']} failed, "
          f"{row['fallback_pages']} by fallback, {chars:9,} characters, {row['seconds']:5.1f} s")
    return row


def _open_fallback(source: Path):
    """PyMuPDF, if installed (lab only: its AGPL licence is not wanted in the deployed tutor)."""
    try:
        import pymupdf
    except ImportError:
        return False                         # remembered, so we do not retry the import every page
    return pymupdf.open(source)


def _fallback_text(document, number: int) -> str | None:
    if not document:
        return None
    try:
        return document[number - 1].get_text()
    except Exception:
        return None


def main(argv: list[str]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    print(f"Reading PDFs from {books_dir()}")
    rows = [row for book in load_books() if (row := extract_book(book, force="--force" in argv))]
    if rows:
        with REPORT.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Summary saved to {REPORT}")
    print(f"Done. Page text is in {OUTPUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
