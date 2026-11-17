"""
Approved-content retrieval with provenance (the "R" in RAG).

One interface, two implementations, so the choice can be made on evidence:
    LexicalRetriever    SQLite FTS5 full-text search with BM25 ranking (baseline).
                        No extra libraries, transparent word matching.
    EmbeddingRetriever  Sentence Transformers embeddings + cosine similarity, in memory.
                        Finds paraphrases, but needs a ~90 MB model and more CPU.
scripts/retrieval_benchmark.py compares them on representative questions.

Only APPROVED notes are searchable: the FTS index is built from approved
notes only, and the embedding retriever filters on status. Every passage keeps
its note id, file and version so the student can see where an explanation came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from qmtutor.storage.db import Database

STOPWORDS = {"the", "a", "an", "is", "are", "of", "to", "in", "and", "or", "how", "do", "i", "what", "why",
             "does", "for", "on", "with", "it", "this", "that", "be", "can", "my", "me", "you", "when", "which"}


@dataclass(frozen=True)
class Passage:
    note_id: str
    heading: str
    body: str
    source: str
    version: str
    score: float


class Retriever(Protocol):
    def search(self, query: str, k: int = 3) -> list[Passage]: ...


def _query_terms(query: str) -> list[str]:
    words = re.findall(r"[a-z]+", query.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1][:12]


class LexicalRetriever:
    """FTS5 baseline. The query is reduced to plain words (no FTS operators can be injected)."""

    def __init__(self, db: Database):
        self.db = db

    def search(self, query: str, k: int = 3) -> list[Passage]:
        terms = _query_terms(query)
        if not terms:
            return []
        match = " OR ".join(f'"{t}"*' for t in terms)     # prefix match: "compound"* also finds "compounded"
        rows = self.db.query(
            """SELECT n.note_id, n.heading, n.body, n.source, n.version, bm25(knowledge_fts) AS rank
               FROM knowledge_fts JOIN knowledge_note n ON n.note_id = knowledge_fts.note_id
               WHERE knowledge_fts MATCH ? AND n.status = 'approved'
               ORDER BY rank LIMIT ?""", (match, k))
        # bm25 is lower-is-better; flip the sign so higher score = more relevant.
        return [Passage(r["note_id"], r["heading"], r["body"], r["source"], r["version"], -r["rank"]) for r in rows]


class EmbeddingRetriever:
    """Semantic retrieval over approved notes. Loads the embedding model once."""

    def __init__(self, db: Database, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        try:
            self.model = SentenceTransformer(model_name, local_files_only=True)   # offline after first download
        except Exception:
            self.model = SentenceTransformer(model_name)
        rows = db.query("SELECT * FROM knowledge_note WHERE status = 'approved' ORDER BY note_id")
        self.notes = [dict(r) for r in rows]
        texts = [f"{n['heading']}: {n['body']}" for n in self.notes]
        self.embeddings = self.model.encode(texts, normalize_embeddings=True) if texts else None

    def search(self, query: str, k: int = 3) -> list[Passage]:
        if self.embeddings is None:
            return []
        q = self.model.encode([query], normalize_embeddings=True)[0]
        scores = self.embeddings @ q       # cosine similarity (vectors are normalised)
        order = scores.argsort()[::-1][:k]
        return [Passage(self.notes[i]["note_id"], self.notes[i]["heading"], self.notes[i]["body"],
                        self.notes[i]["source"], self.notes[i]["version"], float(scores[i])) for i in order]
