"""
Retrievers: ways of finding the best chunks for a question. (Chunkers decide HOW the book is
cut; retrievers decide HOW a question is matched against the pieces.)

All retrievers have the same method, so evaluate.py can swap them:
    search(question, k) -> list of (chunk, score), best first

    Level 4/5  BM25Retriever    word matching (bm25.py)
    Level 3a   DenseRetriever   MEANING matching with embeddings: the question and every chunk
                                become vectors of 384 numbers; nearby vectors = similar meaning
    Level 3b   HybridRetriever  run both, then merge the two rankings (Reciprocal Rank Fusion)
    Level 3c   Reranked         a slower, more careful model re-reads the top 20 candidates of
                                any retriever and re-orders them

Models (downloaded once from Hugging Face, then used offline):
    multi-qa-MiniLM-L6-cos-v1   embedding model trained on QUESTION -> ANSWER-PASSAGE pairs, so
                                it suits "student question vs textbook passage". (4d used
                                all-MiniLM-L6-v2, trained on sentence-vs-sentence similarity.)
    ms-marco-MiniLM-L-6-v2      cross-encoder re-ranker trained on real search queries
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from bm25 import BM25Index
from common import LAB, Chunk

CACHE_DIR = LAB / "output" / "cache"              # chunk embeddings saved here (git-ignored)
DENSE_MODEL = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _need_sentence_transformers():
    try:
        import sentence_transformers  # noqa: F401  (only checking it is installed)
    except ImportError:
        raise SystemExit("Level 3 needs sentence-transformers:\n"
                         "  .\\.venv\\Scripts\\python.exe -m pip install sentence-transformers")


# =
# Level 4/5: word matching
# =
class BM25Retriever:
    def __init__(self, chunks: list[Chunk]):
        self.index = BM25Index(chunks)

    def search(self, query: str, k: int = 10) -> list[tuple[Chunk, float]]:
        return self.index.search(query, k)


# =
# Level 3a: dense retrieval (meaning matching)
# =
class DenseRetriever:
    """
    Plain language: the model reads a text and places it as a point in a 384-dimensional
    "meaning space". Texts about the same idea land close together even if they share no
    words, e.g. "stops losing money" near "break-even point". We place every chunk once,
    then for each question find the chunks nearest to the question's point.

    Technical: bi-encoder (question and passage encoded separately); vectors are normalised to
    length 1, so the dot product equals cosine similarity (1 = same direction, 0 = unrelated).
    Scores are on the same 0-1 scale for every question, unlike BM25 scores, which matters for
    deciding "nothing relevant" later (Level 2).
    """

    def __init__(self, chunks: list[Chunk], model_name: str = DENSE_MODEL):
        _need_sentence_transformers()
        import numpy as np
        from sentence_transformers import SentenceTransformer
        self.np = np
        self.chunks = chunks
        self.model = SentenceTransformer(model_name)
        self.vectors = self._chunk_vectors(model_name)

    def _chunk_vectors(self, model_name: str):
        """
        Embedding thousands of chunks takes a minute or two on a CPU, so the result is saved.
        The file name is a fingerprint (hash) of the model and all chunk texts: if either
        changes, the fingerprint changes and the embeddings are recomputed automatically.
        """
        fingerprint = hashlib.sha1((model_name + "\x00" + "\x00".join(c.text for c in self.chunks))
                                   .encode("utf-8")).hexdigest()[:16]
        path = CACHE_DIR / f"dense-{fingerprint}.npy"
        if path.exists():
            return self.np.load(path)
        print(f"  embedding {len(self.chunks):,} chunks with {model_name} (saved for next time) ...")
        vectors = self.model.encode([c.text for c in self.chunks], normalize_embeddings=True,
                                    batch_size=32, show_progress_bar=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.np.save(path, vectors)
        return vectors

    def search(self, query: str, k: int = 10) -> list[tuple[Chunk, float]]:
        question_vector = self.model.encode([query], normalize_embeddings=True)[0]
        similarity = self.vectors @ question_vector          # one number per chunk
        best = self.np.argsort(-similarity)[:k]               # indexes of the k highest
        return [(self.chunks[i], float(similarity[i])) for i in best]


# =
# Level 3b: hybrid (words + meaning), merged by Reciprocal Rank Fusion
# =
class HybridRetriever:
    """
    Plain language: ask both searchers for their top 50, then give each chunk points for how
    high it appears in EACH list. A chunk that both searchers like rises to the top.

    Technical: Reciprocal Rank Fusion (RRF). score(chunk) = sum over lists of 1 / (60 + rank).
    It uses ranks, not raw scores, so BM25 scores (0-30) and cosine scores (0-1) never need to
    be put on the same scale. 60 is the customary constant: it stops the very top rank from
    dominating.
    """

    def __init__(self, chunks: list[Chunk], dense_model: str = DENSE_MODEL, pool: int = 50, rrf_k: int = 60):
        self.lexical = BM25Retriever(chunks)
        self.dense = DenseRetriever(chunks, dense_model)
        self.pool, self.rrf_k = pool, rrf_k

    def search(self, query: str, k: int = 10) -> list[tuple[Chunk, float]]:
        fused: dict[str, float] = defaultdict(float)
        by_id: dict[str, Chunk] = {}
        for results in (self.lexical.search(query, self.pool), self.dense.search(query, self.pool)):
            for rank, (chunk, _) in enumerate(results, start=1):
                fused[chunk.chunk_id] += 1 / (self.rrf_k + rank)
                by_id[chunk.chunk_id] = chunk
        best = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:k]
        return [(by_id[chunk_id], score) for chunk_id, score in best]


# =
# Level 3c: re-ranking
# =
class Reranked:
    """
    Plain language: the first searcher quickly shortlists 20 candidates; then a slower, more
    careful reader looks at the question and each candidate TOGETHER and scores how well the
    passage answers the question. It can only re-order the shortlist: if the right passage is
    not among the 20, the re-ranker cannot find it.

    Technical: cross-encoder. The question and passage are fed into one model jointly (unlike
    the bi-encoder in 3a), so it can compare words across the two directly. More accurate,
    but it must run once per (question, candidate) pair, so it is only used on a short list.
    Scores are unbounded relevance logits (higher = more relevant).
    """

    def __init__(self, base, model_name: str = RERANK_MODEL, pool: int = 20):
        _need_sentence_transformers()
        from sentence_transformers import CrossEncoder
        self.base, self.pool = base, pool
        self.model = CrossEncoder(model_name)

    @property
    def last_variants(self):
        # When wrapped around a query step (HyDE etc.), pass its variants through for the results file.
        # The re-ranker itself always scores passages against the ORIGINAL question it receives.
        return getattr(self.base, "last_variants", [])

    def search(self, query: str, k: int = 10) -> list[tuple[Chunk, float]]:
        candidates = self.base.search(query, self.pool)
        if not candidates:
            return []
        scores = self.model.predict([(query, chunk.text) for chunk, _ in candidates])
        ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)[:k]
        return [(chunk, float(score)) for (chunk, _), score in ranked]


# =
# Factory: build any combination by name (used by evaluate.py and ask.py)
# =
RETRIEVERS = ("bm25", "dense", "hybrid")


def make_retriever(chunks: list[Chunk], retriever: str = "bm25", rerank: bool = False,
                   dense_model: str = DENSE_MODEL, rerank_model: str = RERANK_MODEL):
    if retriever == "bm25":
        base = BM25Retriever(chunks)
    elif retriever == "dense":
        base = DenseRetriever(chunks, dense_model)
    elif retriever == "hybrid":
        base = HybridRetriever(chunks, dense_model)
    else:
        raise ValueError(f"unknown retriever {retriever!r}; choose from {RETRIEVERS}")
    return Reranked(base, rerank_model) if rerank else base


# =
# Final stage for two-part answers (Level 2): diversity + neighbouring sections
# =
class DiversifyRetriever:
    """
    Two cheap fixes for questions whose answer spans two places (no AI involved):

    DIVERSITY (max_per_section): do not let one section fill the shortlist. Plain language:
    if the top 5 are five slices of section 9.2, the second topic never gets a place. Keep at
    most `max_per_section` chunks per section; the rest move down the list, making room.

    NEIGHBOURS (neighbours): explanations often continue into the next section (9.1 -> 9.2,
    13.2 -> 13.3). For each of the top `neighbours` results, insert the first chunk of the NEXT
    section of the same book right after it, if it is not already in the list.

    Sections come from the structure chunker; other chunkers have no section names, so for them
    each chunk counts as its own "section" and these rules change nothing.
    """

    def __init__(self, base, chunks: list[Chunk], max_per_section: int = 0, neighbours: int = 0, pool: int = 30):
        self.base, self.max_per_section, self.neighbours, self.pool = base, max_per_section, neighbours, pool
        self.next_section_start: dict[str, Chunk] = {}       # chunk_id -> first chunk of the following section
        for i, chunk in enumerate(chunks):
            if not chunk.section:
                continue
            for later in chunks[i + 1:]:
                if later.book != chunk.book:
                    break
                if later.section and later.section != chunk.section:
                    self.next_section_start[chunk.chunk_id] = later
                    break

    @property
    def last_variants(self):
        return getattr(self.base, "last_variants", [])

    def search(self, query: str, k: int = 10) -> list[tuple[Chunk, float]]:
        results = self.base.search(query, self.pool)
        if self.max_per_section:
            kept, overflow, per_section = [], [], defaultdict(int)
            for chunk, score in results:
                key = chunk.section or chunk.chunk_id
                per_section[key] += 1
                (kept if per_section[key] <= self.max_per_section else overflow).append((chunk, score))
            results = kept + overflow                           # overflow is moved down, not deleted
        if self.neighbours:
            present = {c.chunk_id for c, _ in results}
            expanded = []
            for position, (chunk, score) in enumerate(results):
                expanded.append((chunk, score))
                neighbour = self.next_section_start.get(chunk.chunk_id)
                if position < self.neighbours and neighbour and neighbour.chunk_id not in present:
                    expanded.append((neighbour, score))
                    present.add(neighbour.chunk_id)
            results = expanded
        return results[:k]
