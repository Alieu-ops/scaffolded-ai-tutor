"""
BM25: the classic word-matching search used by most search engines before neural models.
(The tutor's current retriever uses the same idea, through SQLite's FTS5.)

Written out by hand here, in about 40 lines, so you can see exactly how a score is made.

THE IDEA IN PLAIN LANGUAGE. A chunk scores higher for a query word when:
  1. the word is RARE across the whole book collection   -> it is informative
     ("annuity" tells you far more than "money");          this is IDF
  2. the word appears OFTEN in this chunk                  -> the chunk is about it;
     but with diminishing returns: 10 mentions are         this is TF, saturated by k1
     not 10x better than 1
  3. the chunk is SHORT                                    -> a mention in a short chunk
     (long chunks mention everything a bit)                matters more; this is b
A chunk's score is the sum of these contributions over the query words it contains.

THE FORMULA (for one query word in one chunk):
    idf(word) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * chunk_length / average_length))
    idf(word) = log(1 + (N - n + 0.5) / (n + 0.5))
        N = number of chunks, n = number of chunks containing the word, tf = count in this chunk
Usual settings: k1 = 1.5 (how quickly repeats stop helping), b = 0.75 (how much length matters).
"""

from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict

from common import Chunk, tokenize


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b

        # Build an "inverted index": for each word, the list of chunks containing it and how
        # often. Like the index at the back of a book: word -> where it appears.
        # This is what makes search fast: we only look at chunks that contain a query word.
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)   # word -> [(chunk no., count)]
        self.lengths: list[int] = []                                          # words per chunk
        for number, chunk in enumerate(chunks):
            counts = Counter(tokenize(chunk.text))        # Counter: {'annuity': 4, 'payment': 2, ...}
            self.lengths.append(sum(counts.values()))
            for word, count in counts.items():
                self.postings[word].append((number, count))

        self.n_chunks = len(chunks)
        self.average_length = sum(self.lengths) / self.n_chunks if self.n_chunks else 0.0
        # IDF for every word, computed once in advance.
        self.idf = {word: math.log(1 + (self.n_chunks - len(where) + 0.5) / (len(where) + 0.5))
                    for word, where in self.postings.items()}

    def search(self, query: str, k: int = 10) -> list[tuple[Chunk, float]]:
        """Return the k best (chunk, score) pairs, best first. Empty if no query word occurs anywhere."""
        scores: dict[int, float] = defaultdict(float)
        for word in set(tokenize(query)):                 # set(): a repeated query word counts once
            if word not in self.postings:
                continue                                  # word never appears: contributes nothing
            idf = self.idf[word]
            for number, tf in self.postings[word]:
                length_factor = 1 - self.b + self.b * self.lengths[number] / self.average_length
                scores[number] += idf * tf * (self.k1 + 1) / (tf + self.k1 * length_factor)
        best = heapq.nlargest(k, scores.items(), key=lambda item: item[1])   # top k without sorting all
        return [(self.chunks[number], score) for number, score in best]
