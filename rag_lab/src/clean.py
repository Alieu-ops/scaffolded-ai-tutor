r"""
Clean the extracted page text: remove noise that is not part of the teaching content.

Run from the app folder (after extract.py):
    .\.venv\Scripts\python.exe rag_lab\src\clean.py

Reads  output/pages/<book>.jsonl        (raw, as extracted)
Writes output/pages_clean/<book>.jsonl  (same pages, same page numbers, cleaned text)
       output/clean_report.csv          how many times each cleaning step fired, per book
       output/clean_samples.txt         BEFORE / AFTER of a few pages, to inspect by eye

Why per page: chunks must still know which pages they came from (citations and scoring).

THE STEPS (each written to work on any book, not just these two):
 1. Normalise characters (Unicode NFKC): the PDFs use special "maths italic/bold" letters
    (𝑖, 𝑥, 𝐓) that look like i, x, T but are different characters, so the tokenizer could
    not read them. NFKC turns them into ordinary letters. Odd bullets become "-".
 2. Remove running headers/footers: lines near the top or bottom of the page that repeat on
    many pages (digits ignored), e.g. "Business Math: A Step-by-Step Handbook 2021 Revision A".
 3. Remove "section title + page number" running heads: a first/last line ending in that
    page's own number, e.g. "5.8 Sample standard deviation 56" on page 56.
 4. Remove formula-drawing debris: bracket pieces (⎡ ⎢ ⎣ ...) and the unknown-glyph mark (�).
 5. Drop debris lines: lines of at most 3 characters with no word in them (stray exponents,
    subscripts, lone numbers from broken formulas), and lines of doubled letters such as
    "TTTTTT" / "CC" (a formula drawn in a font the extractor could not decode).
 6. Re-join words split by a hyphen at the end of a line: "sugges-\ntions" -> "suggestions".
 7. Re-join lines broken in the middle of a sentence: "you \nmust sell" -> "you must sell".

Known imperfections (worth knowing, not worth hiding): a genuine hyphenated word broken at its
hyphen ("right-\nhand") loses its hyphen; formulas stay partly garbled (the PDF does not hold
them as text); some short but meaningful lines (e.g. "n = 5") are kept, others may be dropped.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter

from common import LAB, PAGES_CLEAN_DIR, PAGES_DIR, use_utf8_output

REPORT = LAB / "output" / "clean_report.csv"
SAMPLES = LAB / "output" / "clean_samples.txt"
RUNNING_SHARE = 0.30            # a top/bottom line on >= 30% of pages counts as a running header/footer
BULLETS = {"\x88": "-", "•": "-", "◦": "-", "": "-", "": "-"}
DRAWING = re.compile("[⎛-⎭�]")      # ⎛ ... ⎭ bracket pieces, and � (unknown glyph)
DOUBLED_LETTERS = re.compile(r"(?:([A-Za-z])\1)+")  # "TTTTTT", "CC": letters each printed twice


def normalise(text: str) -> str:
    """Step 1: NFKC turns compatibility characters (𝑖 -> i, 𝐓 -> T, ﬁ -> fi) into ordinary ones."""
    text = unicodedata.normalize("NFKC", text)
    for odd, plain in BULLETS.items():
        text = text.replace(odd, plain)
    return text


def mask_digits(line: str) -> str:
    """'J. OLIVIER 5-158' and 'J. OLIVIER 11-458' both become 'J. OLIVIER #-#', so they count as the same line."""
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line.strip()))


def edge_indexes(lines: list[str], n: int) -> list[int]:
    """Positions of the first n and last n non-blank lines of a page."""
    filled = [i for i, line in enumerate(lines) if line.strip()]
    return filled[:n] + filled[-n:]


def find_running_lines(records: list[dict]) -> Counter:
    """Step 2, part 1: count how many pages each (digit-masked) top/bottom line appears on."""
    counts: Counter = Counter()
    for record in records:
        lines = normalise(record["text"]).split("\n")
        counts.update({mask_digits(lines[i]) for i in edge_indexes(lines, 2)})
    threshold = RUNNING_SHARE * len(records)
    return Counter({line: n for line, n in counts.items() if n >= threshold and line})


def ends_with_own_page_number(line: str, page: int, label) -> bool:
    """Step 3: does a top/bottom line end with this page's number (PDF number or printed label)?"""
    match = re.search(r"(\d+)\s*$", line)
    own_numbers = {str(page)} | ({str(label)} if label else set())
    return bool(match) and match.group(1) in own_numbers and len(line) < 90


def clean_page(record: dict, running: Counter, stats: Counter) -> str:
    lines = normalise(record["text"]).split("\n")
    near_edge = set(edge_indexes(lines, 2))        # running headers/footers sit here
    very_edge = set(edge_indexes(lines, 1))        # "title + page number" heads sit here
    kept: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i in near_edge and mask_digits(stripped) in running:
            stats["2 running header/footer lines removed"] += 1
            continue
        if i in very_edge and ends_with_own_page_number(stripped, record["page"], record.get("label")):
            stats["3 title+page-number lines removed"] += 1
            continue
        without_drawing = DRAWING.sub("", line)
        if without_drawing != line:
            stats["4 lines with formula-drawing characters removed"] += 1
        stripped = without_drawing.strip()
        if stripped and len(stripped) <= 3 and not re.search(r"[A-Za-z]{2}", stripped):
            stats["5a debris lines (<=3 chars) dropped"] += 1
            continue
        compact = stripped.replace(" ", "")
        if len(compact) >= 2 and DOUBLED_LETTERS.fullmatch(compact):
            stats["5b doubled-letter lines dropped"] += 1
            continue
        kept.append(without_drawing.rstrip())

    text = "\n".join(kept)
    # Step 6: "sugges-\ntions" -> "suggestions" (only when the next line starts lower-case)
    text, n = re.subn(r"(\w)-\n(?=[a-z])", r"\1", text)
    stats["6 hyphenated line breaks re-joined"] += n
    # Step 7: join a line to the next when the sentence clearly continues
    # (current line does not end a sentence and the next one starts lower-case or with "(")
    text, n = re.subn(r"(?<=[^\s.!?:;])[ \t]*\n(?=[a-z(])", " ", text)
    stats["7 broken lines re-joined"] += n
    text = re.sub(r"[ \t]{2,}", " ", text)          # squeeze runs of spaces
    text = re.sub(r"\n{3,}", "\n\n", text)          # at most one blank line in a row
    return text


def main() -> None:
    use_utf8_output()
    PAGES_CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    report_rows, samples = [], []
    for raw_file in sorted(PAGES_DIR.glob("*.jsonl")):
        book = raw_file.stem
        records = [json.loads(line) for line in raw_file.open(encoding="utf-8")]
        running = find_running_lines(records)
        stats: Counter = Counter()
        with (PAGES_CLEAN_DIR / raw_file.name).open("w", encoding="utf-8") as out:
            for record in records:
                cleaned = dict(record, text=clean_page(record, running, stats))
                out.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
                if record["page"] in sample_pages(len(records)):
                    samples.append((book, record["page"], record["text"], cleaned["text"]))
        before = sum(len(r["text"]) for r in records)
        after = sum(len(json.loads(line)["text"]) for line in (PAGES_CLEAN_DIR / raw_file.name).open(encoding="utf-8"))
        print(f"\n{book}: {before:,} -> {after:,} characters ({100 * (before - after) / max(before, 1):.1f}% removed)")
        for line, pages in running.most_common(5):
            print(f"   running line on {pages} pages: {line[:80]!r}")
        for step in sorted(stats):
            print(f"   {step}: {stats[step]:,}")
            report_rows.append({"book": book, "step": step, "count": stats[step]})
        report_rows.append({"book": book, "step": "characters before -> after", "count": f"{before} -> {after}"})

    with REPORT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["book", "step", "count"])
        writer.writeheader()
        writer.writerows(report_rows)
    with SAMPLES.open("w", encoding="utf-8") as f:
        for book, page, before_text, after_text in samples:
            f.write(f"{'=' * 30} {book} page {page} {'=' * 30}\n--- BEFORE ---\n{before_text}\n"
                    f"--- AFTER ---\n{after_text}\n\n")
    print(f"\nSaved {PAGES_CLEAN_DIR}\n      {REPORT}\n      {SAMPLES}  <- open this to compare before/after")


def sample_pages(n_pages: int) -> set[int]:
    """Three pages spread through each book for the before/after sample file."""
    return {max(1, n_pages // 4), n_pages // 2, (3 * n_pages) // 4}


if __name__ == "__main__":
    main()
