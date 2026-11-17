"""
Chunkers: ways of cutting a book into searchable pieces (Chunks).

Every chunker has the same input and output, so evaluate.py can swap them and compare fairly:
    input : a list of Pages (from common.load_pages), plus settings such as size
    output: a list of Chunks (from common.Chunk)

    Level 5   fixed_size   equal slices of characters, blind to meaning
    Level 4a  fixed_size   with overlap > 0 (each slice repeats the end of the previous one)
    Level 4b  recursive    cut only at natural boundaries: paragraph, sentence, line, word
    Level 4c  structure    cut at the book's own sections (from its table of contents),
                           label each section's kind (content, summary, solutions, ...),
                           optionally put the section title at the top of each chunk
    Level 4d  semantic     cut where the TOPIC changes, judged by an embedding model

READING ORDER: _join_pages and _make_chunk (shared helpers, at the bottom) -> fixed_size ->
recursive -> structure -> semantic. Each one reuses ideas from the one before.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_right

from common import TOC_DIR, Chunk, Page


# =
# LEVEL 5 / 4a: fixed size (with optional overlap)
# =
def fixed_size(pages: list[Page], size: int = 1000, overlap: int = 0, **_) -> list[Chunk]:
    """
    Cut each book into slices of `size` characters, "with scissors, without looking".
    overlap: characters each slice repeats from the previous one (0 = Level 5, >0 = Level 4a).
    (**_ accepts and ignores settings meant for other chunkers, so all can be called the same way.)
    """
    step = size - overlap                     # how far the scissors move each time
    if size <= 0 or step <= 0:
        raise ValueError("size must be positive and larger than overlap")

    chunks: list[Chunk] = []
    for book, book_pages in _group_by_book(pages).items():
        book_text = _join_pages(book_pages)
        full = book_text.text
        for start in range(0, len(full), step):
            end = min(start + size, len(full))
            if full[start:end].strip():
                chunks.append(_make_chunk(book, len(chunks), start, end, book_text))
            if end == len(full):
                break
    return chunks


# =
# LEVEL 4b: recursive splitting at natural boundaries
# =
# Preferred cutting points, best first. A chunk is only cut at a weaker boundary when no
# stronger one is available inside it. Note: in PDF text a "\n" is usually just the end of a
# printed LINE, not of a paragraph, so a sentence end (". ") is ranked above a line break.
SEPARATORS = ["\n\n", ".\n", ". ", "\n", " "]


def recursive(pages: list[Page], size: int = 1000, **_) -> list[Chunk]:
    """
    Cut at paragraph ends if possible; if a piece is still too long, at sentence ends; then at
    line breaks; then between words. Small neighbouring pieces are merged back together up to
    `size`, so chunks are as big as allowed but never cut through a sentence unless forced.

    Works on ANY text: it needs no page numbers, headings or table of contents.
    """
    chunks: list[Chunk] = []
    for book, book_pages in _group_by_book(pages).items():
        book_text = _join_pages(book_pages)
        for start, end in _recursive_spans(book_text.text, 0, len(book_text.text), size, SEPARATORS):
            if book_text.text[start:end].strip():
                chunks.append(_make_chunk(book, len(chunks), start, end, book_text))
    return chunks


def _recursive_spans(text: str, start: int, end: int, size: int, separators: list[str]) -> list[tuple[int, int]]:
    """
    Return (start, end) positions of pieces of text[start:end], each at most `size` long.
    "Recursive" because a piece that is still too long is split again by the same function,
    using only the weaker separators that remain.
    """
    if end - start <= size:
        return [(start, end)]
    for i, separator in enumerate(separators):
        # positions just AFTER each separator, i.e. where a new piece would begin
        cuts = [start + m.end() for m in re.finditer(re.escape(separator), text[start:end])]
        cuts = [c for c in cuts if start < c < end]
        if not cuts:
            continue                                   # this separator does not occur: try the next
        bounds = [start] + cuts + [end]
        pieces: list[tuple[int, int]] = []
        for a, b in zip(bounds, bounds[1:]):
            if b - a > size:
                pieces.extend(_recursive_spans(text, a, b, size, separators[i + 1:]))
            else:
                pieces.append((a, b))
        return _merge_spans(pieces, size)
    # No separator at all (e.g. one enormous "word"): fall back to plain fixed-size cuts.
    return [(s, min(s + size, end)) for s in range(start, end, size)]


def _merge_spans(pieces: list[tuple[int, int]], size: int) -> list[tuple[int, int]]:
    """Glue neighbouring small pieces together while the result stays within `size`."""
    merged: list[tuple[int, int]] = []
    current_start, current_end = pieces[0]
    for start, end in pieces[1:]:
        if end - current_start <= size:
            current_end = end                          # fits: extend the current chunk
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    merged.append((current_start, current_end))
    return merged


# =
# LEVEL 4c: structure-aware (sections from the table of contents)
# =
def structure(pages: list[Page], size: int = 1000, headers: bool = False, max_level: int = 3,
              **_) -> list[Chunk]:
    """
    1. Read the book's table of contents (saved by toc.py) and find where each section starts.
    2. Each section becomes its own unit; a chunk never mixes two sections.
    3. A section longer than `size` is split further with the 4b recursive method.
    4. Each chunk is labelled with its section path and its KIND (content, summary, ...),
       so evaluate.py can test what happens if summaries, contents pages etc. are excluded.
    5. headers=True puts "[section path]" at the top of every chunk ("contextual header"),
       so a chunk deep inside "5.2 Break-Even Analysis" carries the words "Break-Even".

    Needs a table of contents. Books without one cannot use this method (that is what
    4b and 4d are for).
    """
    chunks: list[Chunk] = []
    for book, book_pages in _group_by_book(pages).items():
        book_text = _join_pages(book_pages)
        sections = _sections(book, book_text, max_level)
        boundaries = [s[0] for s in sections[1:]] + [len(book_text.text)]
        for (start, path, kind), end in zip(sections, boundaries):
            if end <= start:
                continue                               # two headings at the same spot: nothing between
            header = f"[{path}]\n" if headers else ""
            for a, b in _recursive_spans(book_text.text, start, end, size, SEPARATORS):
                if book_text.text[a:b].strip():
                    chunks.append(_make_chunk(book, len(chunks), a, b, book_text,
                                              section=path, kind=kind, header=header))
    return chunks


# Words in a section title that show it is not ordinary teaching content.
_KIND_RULES = [
    ("solutions", ("solution", "answer")),
    ("summary", ("summary",)),
    ("case_study", ("case study",)),
    ("formulas", ("key formulas", "formula sheet")),
    ("front_back", ("table of contents", "contents", "license", "attribution", "preface",
                    "about the author", "textbook features", "lyryx", "bibliography", "articles",
                    "endmatter", "rounding rules", "acknowledgement")),
]


def _kind_of(title: str) -> str:
    lowered = title.lower()
    for kind, words in _KIND_RULES:
        if any(word in lowered for word in words):
            return kind
    return "content"


def _sections(book: str, book_text: "_BookText", max_level: int) -> list[tuple[int, str, str]]:
    """
    Return (start position, section path, kind) for each section, in reading order.
    The section path joins the titles above it: "Chapter 5: ... > 5.2: Break-Even Analysis".
    """
    toc_file = TOC_DIR / f"{book}.json"
    if not toc_file.exists():
        raise SystemExit(f"Missing {toc_file}. Run rag_lab/src/toc.py first.")
    toc = json.loads(toc_file.read_text(encoding="utf-8"))
    page_offset = dict(zip(book_text.page_numbers, book_text.page_starts))

    sections = [(0, "Front matter", "front_back")]     # anything before the first heading
    trail: dict[int, str] = {}                          # level -> title, to build the path
    for entry in toc:
        level, title, page = entry["level"], entry["title"], entry["page"]
        if level > max_level or page not in page_offset:
            continue
        trail[level] = title
        for deeper in [lv for lv in trail if lv > level]:
            del trail[deeper]                           # a new heading closes deeper ones
        path = " > ".join(trail[lv] for lv in sorted(trail))
        start = _heading_position(book_text.text, page_offset[page], title)
        sections.append((start, path, _kind_of(title)))
    sections.sort(key=lambda s: s[0])
    return sections


def _heading_position(full: str, page_start: int, title: str) -> int:
    """
    A section may start halfway down a page. Look for the title's first words on that page
    (allowing any spacing/punctuation between them); if not found, use the top of the page.
    """
    words = re.findall(r"[A-Za-z]+", title)[:3]
    if not words:
        return page_start
    pattern = re.compile(r"\W+".join(map(re.escape, words)), re.IGNORECASE)
    match = pattern.search(full, page_start, page_start + 6000)
    return match.start() if match else page_start


# =
# LEVEL 4d: semantic chunking (cut where the topic changes)
# =
def semantic(pages: list[Page], size: int = 1000, percentile: float = 20, min_size: int = 200,
             model_name: str = "all-MiniLM-L6-v2", **_) -> list[Chunk]:
    """
    1. Split the text into sentences.
    2. Turn each sentence into an embedding: a list of 384 numbers representing its meaning.
    3. Compare each sentence with the next (cosine similarity: near 1 = same topic).
    4. Where similarity is unusually LOW (in the bottom `percentile` % for that book), the topic
       has probably changed: start a new chunk there. Also start one if the chunk would
       exceed `size`; never end one before `min_size` characters.

    Needs no headings or page numbers, but needs the sentence-transformers package and a
    small model (~90 MB, downloaded once). Slower than the others: every sentence is embedded.
    """
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise SystemExit("Level 4d needs sentence-transformers. Install it with:\n"
                         "  .\\.venv\\Scripts\\python.exe -m pip install sentence-transformers")
    model = SentenceTransformer(model_name)

    chunks: list[Chunk] = []
    for book, book_pages in _group_by_book(pages).items():
        book_text = _join_pages(book_pages)
        full = book_text.text
        spans = _sentence_spans(full)
        print(f"  embedding {len(spans):,} sentences of {book} ...")
        vectors = model.encode([full[s:e] for s, e in spans], normalize_embeddings=True,
                               batch_size=64, show_progress_bar=True)
        # similarity[i] compares sentence i with sentence i+1 (dot product of normalised vectors)
        similarity = (vectors[:-1] * vectors[1:]).sum(axis=1)
        cutoff = float(np.percentile(similarity, percentile)) if len(similarity) else 0.0

        chunk_start = spans[0][0]
        for i, (_, sentence_end) in enumerate(spans):
            last = i == len(spans) - 1
            topic_changes = not last and similarity[i] < cutoff and sentence_end - chunk_start >= min_size
            too_long_next = not last and spans[i + 1][1] - chunk_start > size
            if last or topic_changes or too_long_next:
                # a single sentence longer than `size` (e.g. a table) is split the 4b way
                for a, b in _recursive_spans(full, chunk_start, sentence_end, size, SEPARATORS):
                    if full[a:b].strip():
                        chunks.append(_make_chunk(book, len(chunks), a, b, book_text))
                if not last:
                    chunk_start = spans[i + 1][0]
    return chunks


# A sentence ends at . ! or ? followed by space and a capital letter or "(" (so "3.5" is not
# a sentence end), or at a blank line.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])|\n\s*\n")


def _sentence_spans(full: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for match in _SENTENCE_BREAK.finditer(full):
        if full[start:match.start()].strip():
            spans.append((start, match.start()))
        start = match.end()
    if full[start:].strip():
        spans.append((start, len(full)))
    return spans


# =
# Shared helpers (names starting with "_" are private to this file by convention)
# =
class _BookText:
    """A whole book as one string, plus where each page starts, to map positions to pages."""

    def __init__(self, text: str, page_starts: list[int], page_numbers: list[int]):
        self.text = text
        self.page_starts = page_starts       # e.g. [0, 2950, 6100, ...]
        self.page_numbers = page_numbers     # e.g. [1, 2, 3, ...]

    def page_at(self, offset: int) -> int:
        """Which page holds character number `offset`? (bisect_right = fast binary search)"""
        return self.page_numbers[bisect_right(self.page_starts, offset) - 1]


def _join_pages(book_pages: list[Page]) -> _BookText:
    starts, numbers, position = [], [], 0
    for p in book_pages:
        starts.append(position)
        numbers.append(p.page)
        position += len(p.text) + 1          # +1 for the "\n" placed between pages
    return _BookText("\n".join(p.text for p in book_pages), starts, numbers)


def _make_chunk(book: str, number: int, start: int, end: int, book_text: _BookText,
                section: str = "", kind: str = "content", header: str = "") -> Chunk:
    return Chunk(chunk_id=f"{book}-{number:05d}", book=book,
                 first_page=book_text.page_at(start), last_page=book_text.page_at(end - 1),
                 text=header + book_text.text[start:end], section=section, kind=kind)


def _group_by_book(pages: list[Page]) -> dict[str, list[Page]]:
    """{'olivier': [its pages in order], 'godwin': [...]}. Dicts keep insertion order."""
    grouped: dict[str, list[Page]] = {}
    for p in pages:
        grouped.setdefault(p.book, []).append(p)
    return grouped
