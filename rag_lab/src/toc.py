r"""
Save each book's table of contents (the PDF "outline" or bookmarks) for Level 4c.

Run once from the app folder:
    .\.venv\Scripts\python.exe rag_lab\src\toc.py

Output: rag_lab/output/toc/<book>.json, a list of {"level": 2, "title": "5.2: Break-Even Analysis", "page": 173}
    level = depth in the outline (1 = chapter, 2 = section, 3 = sub-section)
    page  = PDF page number where the entry points (same numbering as extract.py)

Many PDFs carry this outline (it is what a PDF viewer shows in its bookmarks panel), but not
all do. A book without one cannot use Level 4c; that is a real-world limitation we record.
"""

from __future__ import annotations

import json
import sys

from pypdf import PdfReader

from common import TOC_DIR
from extract import books_dir, load_books   # reuse the book list and location (also quiets pypdf warnings)


def outline_entries(reader: PdfReader) -> list[dict]:
    """
    pypdf gives the outline as a nested list: an entry, then (optionally) a list of its
    children, then the next entry, and so on. Walking it recursively gives each entry's level.
    """
    entries: list[dict] = []

    def walk(items, level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)              # children of the previous entry
                continue
            try:
                page = reader.get_destination_page_number(item) + 1   # pypdf counts from 0
            except Exception:
                page = -1                          # entry points nowhere usable
            entries.append({"level": level, "title": str(item.title).strip(), "page": page})

    walk(reader.outline, 1)
    return entries


def main() -> None:
    TOC_DIR.mkdir(parents=True, exist_ok=True)
    for book in load_books():
        source = books_dir() / book["file"]
        if not source.exists():
            print(f"  {book['id']:<9} MISSING: {source}")
            continue
        entries = outline_entries(PdfReader(source))
        (TOC_DIR / f"{book['id']}.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False),
                                                     encoding="utf-8")
        levels = sorted({e["level"] for e in entries})
        print(f"  {book['id']:<9} {len(entries):4} outline entries, levels {levels or '-'}")
    print(f"Saved to {TOC_DIR}")


if __name__ == "__main__":
    main()
