# RAG lab

A place to build and measure retrieval, level by level, **outside the tutor**. A technique moves into the tutor (`qmtutor/retrieval/`) only after it shows a measured improvement here (design decisions D16, D17).

The books stay outside the repo (`materials/textbooks/`). Everything built from their text goes in `output/`, which is git-ignored. This README and the results table hold numbers only, never book text, so they are safe to commit.

## How testing works

We do not test through the tutor's web page. Each level is a script run from the terminal:

```
question ──► retriever (this level) ──► top 5 chunks, each with book + pages
                                              │
test set: question ──► expected book + pages ─┴──► hit or miss? ──► scores
```

- **Retrieval levels (5, 4, 3)** need no AI model: we only check *which text comes back*. This is fast, free and repeatable: the same input always gives the same score.
- **Level 2** adds generation (the local Ollama model writes an answer from the chunks). We then also check whether the answer **sticks to the sources** (faithfulness) and **says "not in the notes"** when it should.
- You can also ask a single question interactively and read the chunks that come back. That builds intuition; the scores give the evidence.

## The test set (`testset/questions.yaml`)

Each entry is a question and where the answer lives: book plus PDF page range. A retrieved chunk is a **hit** if its pages overlap the expected pages. Labelling by pages, not by chunk, means one test set can score every chunking method.

Planned mix of about 30 questions: 10 direct (the book's own words), 10 paraphrased (a student's words), 5 not in any book, and 5 spanning two books or topics.

**Metrics**
- **Hit@k**: share of questions with at least one correct chunk in the top k (k = 1, 3, 5). Plain language: "did the right passage make the shortlist?"
- **MRR** (mean reciprocal rank): 1 if the first correct chunk is ranked 1st, 1/2 if 2nd, 1/3 if 3rd, and so on, averaged. Plain language: "how near the top was it?"
- **No-answer accuracy**: for the "not in any book" questions, did the system correctly return nothing, or score below a threshold?
- **Cost**: indexing time, time per query, memory. On a CPU server these matter.

Scores are always reported **by question type**, because an average can hide a level that helps paraphrases but hurts direct questions.

## The levels (we climb from 5 to 2)

| Level | Plain language | Technical idea | What we expect to learn |
|---|---|---|---|
| **5 Naive** | Cut the book into equal slices of text and search by matching words | Fixed-size character chunks, no overlap; BM25 lexical ranking | A baseline. Slices cut through sentences, formulas and worked examples; paraphrases fail. |
| **4a Overlap** | Let slices overlap so ideas cut at an edge still appear whole in one of them | Sliding window with overlap | Fewer cut ideas; more chunks (more storage and time) |
| **4b Sentence/paragraph-aware** | Cut only at sentence or paragraph ends | Recursive splitting on separators (`\n\n` → `\n` → `. `) up to a size limit | Works on any text, **even without page numbers or a table of contents** |
| **4c Structure-aware** | Cut at the book's own sections; keep worked examples whole; attach chapter/section metadata | Heading detection, PDF outline (TOC), metadata | Best for well-structured books; shows how much structure is worth |
| **4d Semantic** | Cut where the *topic changes* | Embedding similarity between neighbouring sentences | For text with no headings at all |
| **3a Meaning search** | Find passages with the same meaning in different words | Dense retrieval: sentence embeddings + cosine similarity | Paraphrased questions improve; exact terms (e.g. "NPV") may get worse |
| **3b Hybrid** | Use both word search and meaning search, then merge the lists | BM25 + dense, merged by Reciprocal Rank Fusion (RRF) | Usually the best of both |
| **3c Re-rank** | A more careful reader rescores the top 20 and keeps the best | Cross-encoder re-ranker | Better ordering (MRR), at a time cost |
| **2 Advanced** | Ask better, filter, know when to say "not found", answer with citations | Query rewriting, metadata filters (book/topic), score threshold, grounded generation + faithfulness check | Correct refusals; trustworthy answers |
| *(1 Agentic)* | *The AI decides when to search again* | *Iterative retrieval loop* | *Deferred (D16)* |

## Results (filled in as we go: numbers only)

| Level / variant | Chunks | Hit@1 | Hit@3 | Hit@5 | MRR | Paraphrase Hit@3 | No-answer acc. | Query time | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 5 naive, fixed 1000 chars, no overlap (13 Oct, test set v0.1 draft) | 2,435 | 0.36 | 0.64 | 0.72 | 0.54 | 0.40 (direct 0.80) | 0 | 0.55 ms | indexed in 0.19 s |
| 5 naive, fixed 500 | 4,869 | 0.48 | 0.68 | 0.76 | 0.61 | 0.40 (direct 0.90) | 0 | 0.39 ms | |
| 5 naive, fixed 2000 | 1,218 | 0.36 | 0.72 | 0.72 | 0.54 | 0.40 (direct 0.90) | 0 | 0.26 ms | spanning Hit@3 1.0 |
| 4a overlap, fixed 1000 + 200 overlap | 3,043 | 0.44 | 0.68 | 0.80 | 0.57 | 0.40 (direct 0.90) | 0 | 0.39 ms | absent top score rose to 12.1 |
| 4b recursive (sentence/line-aware), 1000 | 2,877 | 0.44 | 0.56 | 0.80 | 0.56 | 0.20 (direct 0.80) | 0 | | |
| 4c structure (TOC sections), 1000 | 2,988 | 0.48 | 0.68 | 0.80 | 0.61 | 0.30 (direct 0.90) | 0 | | top result non-content in 16% |
| 4c + section headers | 2,988 | 0.48 | 0.64 | 0.80 | 0.60 | 0.30 (direct 0.80) | 0 | | non-content top 20% |
| **4c + headers + exclude summary/front/back/case study/solutions/formulas** | 2,545 | **0.60** | **0.76** | 0.80 | **0.69** | 0.40 (direct **1.00**) | 0 | | non-content top 0%; best so far |
| 4c + exclude, **no headers** (ablation) | 2,545 | 0.60 | 0.76 | **0.84** | 0.69 | 0.40 (direct 1.00) | 0 | 0.35 ms | indexed in 0.15 s; **Level 4 winner** |
| 4d semantic (MiniLM, cut at bottom 20% similarity), 1000 | 3,710 | 0.40 | 0.56 | 0.68 | 0.53 | 0.20 (direct 0.90) | 0 | 1.2 ms | **indexed in 303 s** |

**Level 3 (all on the Level 4 winner's chunks: structure + exclude, 2,545 chunks)**

| Retrieval | Hit@1 | Hit@3 | Hit@5 | MRR | Paraphrase Hit@3 | Spanning Hit@3 | Query time | Indexing |
|---|---|---|---|---|---|---|---|---|
| BM25 (Level 4 winner) | 0.60 | 0.76 | 0.84 | 0.69 | 0.40 | 1.00 | 0.35 ms | 0.15 s |
| 3a dense (multi-qa-MiniLM) | 0.64 | **0.80** | 0.84 | 0.74 | 0.50 | 1.00 | 19 ms | 171 s first run (embeddings cached) |
| 3b hybrid (RRF) | 0.56 | **0.80** | 0.84 | 0.69 | **0.60** | 0.80 | 13 ms | 12 s (cache) |
| 3c BM25 + re-rank | 0.72 | **0.80** | 0.84 | 0.77 | 0.50 | 1.00 | 752 ms | |
| 3c dense + re-rank | 0.72 | 0.76 | 0.84 | 0.77 | 0.50 | 0.80 | 862 ms | |
| **3c hybrid + re-rank** | **0.76** | **0.80** | 0.84 | **0.80** | 0.50 | 1.00 | 916 ms | |

### What Level 3 taught us (13 Oct)

1. **Meaning search finally reached the "impossible" paraphrases.** p01 (interest on interest) and p02 (stops losing money) were never found by any word-based setup. Dense search found them for the first time (4th and 8th). It also fixed the tokenization casualty: "p-value" (d07) went to 1st.
2. **But dense also lost what words do well:** p09 (sales from advertising) fell from 1st to outside the top 10; p06 and p07 dropped out. Meaning search can blur specific terms.
3. **Hybrid gave the best paraphrase coverage (Hit@3 0.60)** but a lower Hit@1 (0.56): fusing ranks pulls the two searchers' favourites together, which helps recall but can push a single strong first answer down (p01 lost again; s04 1st → 5th).
4. **Re-ranking gave the best ordering:** hybrid + re-rank has Hit@1 0.76 and MRR 0.80, against 0.36 and 0.54 at the Level 5 baseline. Every direct question now ranks 1st.
5. **A re-ranker cannot rescue what the shortlist missed:** BM25 + re-rank still never finds p01/p02, because word search never put them in the top 20.
6. **Cost:** re-ranking costs about 0.8–0.9 s per question on this CPU (20 question–passage pairs), roughly 50 times dense search. Acceptable for study mode, where the AI answer itself takes several seconds, but it matters on a busy server.
7. **"Not in the books" becomes detectable with model scores.** Dense similarity: absent questions 0.25–0.48 vs answerable median 0.65. Re-ranker: absent −8.8 to −2.5 vs answerable median +4.8. A cut-off just below the absent maximum would have rejected all 5 absent questions while wrongly rejecting 2 of 25 answerable ones (one of which had the right passage first). **Caution:** those cut-offs were read off this same test set, so they are optimistic; they must be checked on held-out questions.
8. **Paraphrase is improved, not solved:** 0.40 → 0.50–0.60, with p01/p02 still ranked 4th–10th. Candidates at Level 2: query rewriting, a lecturer glossary.

**Raw vs cleaned text (clean.py, 13 Oct).** Same settings, only the input text differs. "4c" and "3x" use structure + exclude chunks.

| Run | Hit@1 raw → clean | Hit@3 raw → clean | MRR raw → clean | Paraphrase Hit@3 raw → clean | Questions whose rank changed |
|---|---|---|---|---|---|
| L5 fixed | 0.36 → **0.48** | 0.64 → 0.64 | 0.54 → **0.59** | 0.40 → 0.40 | 11 (8 up, 3 down) |
| L4b recursive | 0.44 → **0.52** | 0.56 → **0.64** | 0.56 → **0.61** | 0.20 → **0.40** | 8 |
| L4c structure | 0.60 → 0.56 | 0.76 → 0.72 | 0.69 → 0.66 | 0.40 → 0.40 | 7 (mixed) |
| L4d semantic | 0.40 → 0.44 | 0.56 → **0.64** | 0.53 → **0.57** | 0.20 → 0.30 | 6; spanning 0.60 → 0.80 |
| L3a dense | 0.64 → **0.68** | 0.80 → **0.84** | 0.74 → 0.75 | 0.50 → **0.60** | 8; p01 4th → 2nd |
| L3b hybrid | 0.56 → 0.60 | 0.80 → **0.84** | 0.69 → 0.70 | 0.60 → **0.70** (best yet) | 11 |
| L3c hybrid + re-rank | 0.76 → **0.64** | 0.80 → 0.80 | 0.80 → **0.72** | 0.50 → 0.50 | 7; p10 1st → 7th, p01/p09 out of top 10 |

### What cleaning taught us (13 Oct)

- **Cleaning helped the weaker setups and the embedding-based ones:** naive, recursive and semantic chunking, and dense and hybrid search all improved. Hybrid on clean text reached the best paraphrase score so far (0.70), and dense moved p01 (interest on interest) from 4th to 2nd. Joined sentences and removed debris give embedding models proper sentences to read, as P2 predicted.
- **It did not help the two strongest setups.** Structure-aware BM25 dipped slightly; hybrid + re-rank lost 3 questions at the top (Hit@1 0.76 → 0.64). On p10 the re-ranker now prefers Olivier's "3.2 Averages" (which never mentions the median) over Godwin's mean-vs-median section: a genuine error, not a labelling issue.
- **Most changes are 1–3 questions,** within what 25 questions can resolve. Cleaning is not a clear win or loss overall; it reshuffles which questions succeed.
- **Recommendation:** keep cleaning (cleaner chunks matter even more at Level 2, where the AI reads them and cites them), but do not assume it improves retrieval. Re-check on the reviewed test set and the held-out set. A later ablation could switch steps off one at a time (e.g. keep Godwin's "section + page" running heads, which carried section names).

**Held-out confirmation (questions_heldout.yaml v0.1: 20 new questions on new topics; 16 answerable, so one question = 0.06)**

| Setup | Hit@1 dev → held-out | Hit@3 dev → held-out | MRR dev → held-out | Paraphrase Hit@3 dev → held-out |
|---|---|---|---|---|
| L5 fixed (baseline) | 0.36 → 0.75 | 0.64 → 0.75 | 0.54 → 0.78 | 0.40 → 0.63 |
| L4c structure + exclude | 0.60 → 0.75 | 0.76 → **0.88** | 0.69 → **0.81** | 0.40 → **0.75** |
| L3a dense | 0.64 → 0.75 | 0.80 → 0.75 | 0.74 → 0.78 | 0.50 → 0.50 |
| L3b hybrid | 0.56 → 0.69 | 0.80 → **0.88** | 0.69 → 0.78 | 0.60 → **0.75** |
| L3b hybrid, clean | 0.60 → 0.75 | 0.84 → **0.88** | 0.70 → **0.81** | 0.70 → **0.75** |
| L3c hybrid + re-rank | 0.76 → 0.63 | 0.80 → **0.88** | 0.80 → 0.75 | 0.50 → **0.75** |
| L3c hybrid + re-rank, clean | 0.64 → 0.75 | 0.80 → **0.88** | 0.72 → **0.82** | 0.50 → **0.75** |

### What the held-out set taught us (13 Oct)

1. **The held-out questions were easier**, so scores rose instead of falling. 10 of 16 answerable questions ranked 1st for *every* setup, including the baseline. The development set contained deliberate traps (p-value tokenization, "residual", summary-heavy topics); the new topics have distinctive terms. **Compare setups within one set, never scores across sets.**
2. **This ceiling hides most differences.** On held-out, all improved setups tie at Hit@3 0.88; they differ by 1–2 questions.
3. **What replicated:** structure + exclude beats the baseline on both sets (e.g. h-d01 annuity PV 4th → 1st, h-p04 early payment 7th → 3rd); **hybrid is among the best on both sets**; clean text is at least as good as raw for hybrid.
4. **What did not replicate:** the re-ranker's top-1 advantage (dev Hit@1 0.76, held-out 0.63 on raw). **Dense alone is not reliable:** on held-out it lost h-p05 (prorating) and h-p06 (correlation), which word search ranked 1st.
5. **Shared failures:** h-p08 (t-test described as "don't know the population spread") was missed by every setup, which retrieved the z-test / p-value pages; h-p01 (sale price → markdown) reached only 5th–9th.
6. **The development cut-offs for "not in the books" did NOT generalise.** Dense ≤ 0.48 rejected only 2 of 4 absent questions (two scored 0.485 and 0.486). Re-ranker ≤ −2.5 rejected 3 of 4, but scored "logistic regression" at +1.2 (it retrieved multiple regression), and wrongly rejected a correct answer (h-p06, ranked 1st). **A single score cut-off is not a dependable "not found" rule.** This is exactly the overfitting the held-out set exists to catch.

**Provisional decision (D18, proposed):** structure + exclude chunks on **clean** text, **hybrid** retrieval (BM25 + dense). Re-ranker optional, not default (no replicated gain, about 1 s per question). "Not found" needs more than a score threshold (Level 2). Re-confirm after my review and a harder, larger held-out set.

## Test set v2 (13 Oct): 429 ChatGPT-drafted questions, checked and split 257 development / 172 held-out

Development part: 60 direct, 60 paraphrase (light/medium/deep), 60 spanning, 9 grammar-error, 9 spelling-error (198 answerable) + 59 absent. One question = 0.005.

| Setup (clean text) | Hit@1 | Hit@3 | Hit@5 | MRR | Direct | Para light | Para medium | **Para deep** | Spanning (either) | **Spanning both@5** | Grammar | **Spelling** | ms/query |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L5 fixed | 0.42 | 0.63 | 0.73 | 0.54 | 0.90 | 0.38 | 0.50 | 0.29 | 0.70 | 0.33 | 0.56 | 0.00 | <1 |
| L4b recursive | 0.43 | 0.63 | 0.69 | 0.55 | 0.87 | 0.38 | 0.68 | 0.18 | 0.70 | 0.23 | 0.44 | 0.11 | <1 |
| L4c structure + exclude | 0.45 | 0.62 | 0.71 | 0.56 | 0.87 | 0.38 | 0.64 | 0.18 | 0.68 | 0.25 | 0.56 | 0.00 | <1 |
| L4d semantic | 0.40 | 0.60 | 0.67 | 0.52 | 0.85 | 0.33 | 0.55 | 0.24 | 0.65 | 0.23 | 0.56 | 0.00 | <1 |
| L3a dense | 0.48 | 0.67 | 0.75 | 0.59 | 0.90 | 0.48 | 0.68 | 0.12 | 0.73 | 0.32 | 0.44 | 0.44 | 14 |
| **L3b hybrid** | 0.52 | 0.72 | 0.79 | 0.63 | 0.92 | 0.48 | 0.73 | 0.41 | 0.77 | 0.37 | 0.67 | 0.22 | 12 |
| L3c hybrid + re-rank | 0.49 | 0.75 | 0.84 | 0.64 | 0.92 | 0.52 | 0.68 | 0.41 | 0.82 | 0.53 | 0.67 | 0.56 | 1,107 |

Paired sign tests (each question compared with itself; rank of first correct chunk):

| Comparison | Better / worse | p | Net Hit@3 |
|---|---|---|---|
| clean vs raw, every setup | e.g. hybrid 36/37, re-rank 31/27 | 0.30–1.00 | −2 to +6 |
| L4c structure vs L5 fixed | 36 / 36 | 1.00 | −2 |
| L4d semantic vs L5 fixed | 30 / 48 | 0.054 | −7 |
| dense vs L4c (word search) | 66 / 49 | 0.14 | +10 |
| **hybrid vs L4c (word search)** | **66 / 28** | **0.0001** | **+19** |
| **hybrid vs L5 baseline** | **62 / 35** | **0.008** | **+17** |
| hybrid vs dense | 50 / 35 | 0.13 | +9 |
| re-rank vs hybrid | 41 / 45 | 0.75 | +6 |

"Not in the books" separation, AUC (0.5 = none, 1 = perfect): word-search score 0.80, **dense similarity 0.95**, re-ranker 0.88.

### What test set v2 taught us (13 Oct)

1. **Cleaning makes no measurable retrieval difference** at any level (all p ≥ 0.30). Keep it for readability and citations at Level 2, not for retrieval.
2. **The Level 4 chunking gains did not hold up.** On 198 questions, structure-aware chunking ties the naive baseline (36 better, 36 worse). The earlier gain (Hit@1 0.36 → 0.60) came from a few summary-dominated questions in the 30-question set. Semantic chunking is borderline worse (p = 0.054). Structure-aware chunking is still worth keeping for non-retrieval reasons: it removes answer keys/solutions (safety in exercise mode) and gives section names for citations.
3. **Hybrid search is the one clearly significant improvement:** better than word search on 66 questions, worse on 28 (p = 0.0001); +17 to +19 questions in the top 3.
4. **The re-ranker is not significantly better than hybrid** (41 vs 45, p = 0.75) at about 90 times the cost. It does help two slices: spanning "both sections found" (0.37 → 0.53) and spelling errors (0.22 → 0.56, only 9 questions).
5. **Deep paraphrases are the hardest slice** (0.12–0.41). Dense alone scores lowest (0.12); hybrid reaches 0.41. Misses describe the concept without its name ("how many students fall into different age intervals" = histogram).
6. **Word search fails on spelling errors** (0.00–0.11): "presnt valu" matches nothing. Meaning-based search tolerates them (0.44–0.56). Small slice (9).
7. **Finding both halves of a spanning answer is hard** (0.23–0.53), even when one half is found 70–82% of the time.
8. **Dense similarity separates absent questions well** (AUC 0.95; medians 0.35 absent vs 0.56 answerable). A "not found" rule based on it is promising, but its cut-off must be chosen on development and confirmed on held-out (the earlier cut-off failed on 20 held-out questions).

## Held-out confirmation on test set v2 (13 Oct): 172 questions, 132 answerable, clean text

| Setup | Hit@1 | Hit@3 | Hit@5 | MRR | Direct | Para light | Para medium | Para deep | Spanning | both@5 | ms/query |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L5 fixed | 0.36 | 0.57 | 0.68 | 0.49 | 0.75 | 0.67 | 0.50 | 0.15 | 0.57 | 0.17 | 1 |
| L4c structure + exclude | 0.31 | 0.55 | 0.62 | 0.46 | 0.75 | 0.44 | 0.50 | 0.08 | 0.57 | 0.20 | <1 |
| L3a dense | 0.47 | 0.70 | 0.80 | 0.60 | 0.90 | 0.33 | 0.56 | 0.31 | 0.80 | 0.23 | 16 |
| **L3b hybrid** | **0.52** | **0.70** | 0.79 | **0.62** | 0.90 | 0.78 | 0.61 | 0.38 | 0.70 | 0.25 | 61* |
| L3c hybrid + re-rank | 0.40 | 0.68 | 0.76 | 0.56 | 0.82 | 0.78 | 0.50 | 0.46 | 0.72 | 0.33 | 2,445 |

*Timing varies with laptop load (12 ms on the development run).

Paired, held-out: hybrid vs word search 59/15 (p < 0.0001); hybrid vs baseline 49/21 (p = 0.001); dense vs word search 61/28 (p = 0.0006); hybrid vs dense 39/30 (p = 0.34); re-rank vs hybrid 33/41 (p = 0.42); structure vs fixed 28/37 (p = 0.32).

"Not found" cut-offs chosen on development, applied unchanged to held-out (held-out AUC: dense 0.91, re-rank 0.85):

| Signal / rule | Cut-off | Dev: absent caught / wrong refusals | Held-out: absent caught / wrong refusals |
|---|---|---|---|
| dense, balanced | 0.476 | 98% / 20% | 88% / **22%** (29 real questions refused; 13 had the right passage in the top 3) |
| dense, cautious | 0.403 | 69% / 3% | 62% / 6% |
| re-rank, balanced | −4.13 | 78% / 16% | 60% / 17% |
| re-rank, cautious | −7.72 | 41% / 4% | 35% / 2% |

### Final verdict before Level 2 (13 Oct)

1. **Meaning-based search is the confirmed improvement.** Hybrid beats word search on both development (66/28) and held-out (59/15), p ≤ 0.0001, about +20 questions in the top 3. Its held-out scores (Hit@3 0.70, MRR 0.62) match development (0.72, 0.63): the result generalises.
2. **Hybrid vs dense alone: no significant difference on either set.** Hybrid is chosen because it is never worse overall, keeps exact-term matching (e.g. "p-value", "NPV"), and was stronger on deep paraphrases on both sets.
3. **Re-ranking: rejected as a default.** Not better on either set (held-out Hit@1 actually 0.40 vs 0.52) at 90–200 times the cost.
4. **Chunking method: no retrieval effect, confirmed twice** (structure vs fixed n.s. on both sets). Structure-aware chunking is kept for safety (it excludes solutions/answer keys) and citations (section names).
5. **Cleaning: retrieval-neutral; kept for Level 2 readability.**
6. **A single score cut-off is not a good enough "not found" rule.** Dense similarity is a strong signal (AUC 0.91 held-out), but one cut-off forces a bad trade: refuse 1 in 5 real questions, or let about 40% of uncovered questions through. Near-miss topics are the ones that slip through. → Level 2: a cautious dense cut-off as a first filter, plus an AI "does this passage answer the question?" check for the grey zone.
7. **Known weak spots for Level 2:** deep paraphrases (0.38 hybrid), finding both halves of a two-part answer (0.25), near-miss absent questions.
8. **Caveats:** AI-drafted questions (cleaner than real student questions), two open books only, one run per setup, page-range relevance labels, timings from one laptop.

## Level 2, part 1: improving the question before search (13 Oct; llama3.2:3b; hybrid on clean structure chunks; v2 development, 198 answerable)

The original question is always searched too and merged with the variant(s).

| Mode | Hit@1 | Hit@3 | Hit@5 | MRR | Direct | Para light | Para medium | **Para deep** | Spanning | both@5 | Grammar | **Spelling** | vs hybrid (better/worse, p) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hybrid (Level 3) | 0.52 | 0.72 | 0.79 | 0.63 | 0.92 | 0.48 | 0.73 | 0.41 | 0.77 | 0.37 | 0.67 | 0.22 | n/a |
| spell (no AI) | 0.53 | 0.72 | 0.81 | 0.64 | 0.92 | 0.48 | 0.73 | 0.41 | 0.77 | 0.38 | 0.67 | 0.33 | 8 / 2, p = 0.11 |
| rewrite | 0.54 | 0.76 | 0.84 | 0.67 | 0.88 | 0.48 | **0.82** | 0.41 | **0.87** | 0.35 | 0.78 | 0.44 | **45 / 19, p = 0.002** |
| multi (3 queries) | 0.58 | 0.77 | 0.84 | 0.69 | 0.87 | **0.71** | 0.68 | **0.71** | 0.77 | 0.38 | 0.67 | **0.78** | 62 / 44, p = 0.10 |
| **HyDE** | **0.58** | **0.81** | **0.87** | **0.71** | **0.93** | 0.62 | 0.68 | **0.76** | **0.87** | 0.38 | **0.89** | 0.44 | **61 / 26, p = 0.0002** |
| decompose | 0.53 | 0.77 | 0.83 | 0.66 | 0.87 | 0.67 | 0.59 | 0.53 | 0.83 | 0.40 | 0.89 | 0.67 | 54 / 52, p = 0.92 |

Latency: rewrite about 4 s and decompose about 6 s per question (first-time AI calls). multi and HyDE were mostly served from the cache in the final run, so their timings are not valid; re-measure on held-out (fresh calls).

### What Level 2 part 1 taught us (13 Oct)

1. **HyDE is the strongest and clearly significant** (61 better / 26 worse, p = 0.0002; still significant after allowing for testing 5 modes). Deep paraphrases jumped from 0.41 to 0.76: the AI's imaginary textbook paragraph "sounds like" the book, so it lands next to the right section.
2. **Rewrite is also significant** (45/19, p = 0.002), with gains on medium paraphrases and spanning, but no gain on deep paraphrases and a small loss on direct questions.
3. **Multi-query helps the hardest slices** (deep 0.71, spelling 0.78) but also loses more questions elsewhere (62/44, not significant): more queries, more noise.
4. **Spell correction is cheap and harmless but small** (8/2; spelling slice 0.22 → 0.33). It also "corrected" valid words absent from the books (gathered → gather, persons → person); harmless after fusion.
5. **Decompose did not help** (54/52, p = 0.92), and "both halves" stayed at about 0.40. **No query method solved two-part answers**; that needs to be handled at answer time (e.g. more passages, one per part).
6. **Direct questions are mostly unaffected** (0.87–0.93), thanks to always fusing with the original question.
7. **Cost:** every AI mode adds one model call before the search (seconds on this CPU). HyDE writes a paragraph, so it is likely the slowest; confirm on held-out.

### What Level 4d taught us, and the Level 4 conclusion (13 Oct)

- **Headers contributed nothing.** Excluding non-teaching sections without headers scored the same or better (Hit@5 0.84) and indexed faster. The whole 4c gain comes from section boundaries plus excluding summaries/contents/solutions.
- **Semantic chunking (4d) was worse overall than the naive baseline** (Hit@3 0.56 vs 0.64; spanning 0.60 vs 0.80; paraphrase 0.20) and **about 1,500 times slower to index** (303 s vs 0.2 s).
- It did produce very topical chunks: d01, d03 and d04 all moved to 1st place. But it made 3,710 smaller chunks (about 650 characters), so related ideas were split apart (s04 normal distribution 1st → 6th; s05 4th → 6th).
- **Mismatch of signals:** 4d cuts by *meaning*, but the search is still by *words*, so meaning-aware chunks cannot fix the paraphrase problem on their own. PDF text full of formulas, tables and broken lines also gives the embedding model noisy sentences, which triggers false topic changes.
- 4d cannot see summaries or contents pages either (d08 still returned Godwin's front matter; p02 still a chapter summary).
- **Level 4 decision:** for books with a table of contents use **4c structure + exclude non-teaching sections (no headers), size 1000**. For text with no structure, use **4b recursive** (cheap, comparable to the baseline) rather than 4d (slow, no better here). Revisit 4d once search itself uses meaning (Level 3).

### What Level 4b–4c taught us (13 Oct)

- **Following the book's structure helps most at the top of the list.** Structure-aware chunking with non-teaching sections excluded gave the best scores so far (Hit@1 0.36 → 0.60, MRR 0.54 → 0.69, every direct and spanning question in the top 3).
- **The gain comes mainly from removing summaries and contents pages.** Plain 4c labelled 4 of 25 top results as non-content (Ch. 11 and Ch. 7 summaries, Ch. 3 summary, Godwin front matter). Excluding them moved d03 from 4th to 1st and d08 from 2nd to 1st.
- **Section headers did not help** (Hit@3 0.68 → 0.64). Every chunk in a section gets the same header words, so they do not separate chunks within a section, and they lower those words' rarity (IDF). Headers cannot add the student's own words either. Still to do: run "exclude" *without* headers to separate the two effects.
- **Sentence-aware cutting (4b) alone was mixed.** It helped some direct questions (d04 2 → 1, d07 7 → 5) but paraphrase fell 0.40 → 0.20 (2 questions lost from the top 3). With 10 paraphrase questions, that is likely boundary luck rather than a principle.
- **Paraphrase stayed at 0.20–0.40 at every Level 4 variant.** p01 (interest on interest) and p02 (stops losing money) were never found by any chunker. Chunking cannot solve vocabulary mismatch. → Level 3.
- **Real-world note:** Olivier's PDF outline has only 2 levels (chapter, section); Godwin's has 3. Section-internal exercises are not in the outline, so they stay labelled "content".

### What Level 4a taught us (13 Oct)

- Overlap made 25% more chunks (2,435 → 3,043) and improved every top-k score a little (Hit@1 0.36 → 0.44, Hit@5 0.72 → 0.80, MRR 0.54 → 0.57).
- 10 of 30 questions changed rank: 6 moved up, 4 moved down. Small, mixed shifts, consistent with "ideas cut at an edge now appear whole once", not a big change.
- Paraphrase Hit@3 stayed at 0.40. Overlap, like size, does not create missing words.
- Absent questions got a higher average top score (10.5 → 12.1), so "not in the books" became slightly *harder* to separate by score: more, overlapping chunks give more chances of a chance match.

### What Level 5 taught us (13 Oct)

1. **Everyday wording fails.** Paraphrase Hit@3 was 0.40 against 0.80 for direct questions. "How many items does a shop need to sell before it stops losing money?" never reached break-even, because no word is shared. → meaning search (Level 3).
2. **Summaries and contents pages win the top spot.** They pack key terms densely (Olivier Ch. 11 and Ch. 13 summaries, Ch. 7 summary; Godwin's table of contents), but they are poor answers for a student. → structure-aware chunking that labels or excludes them (Level 4c).
3. **Tokenization matters.** "p-value" became `p` + `value` and matched simple interest (I = Prt) in Olivier first. → keep hyphenated terms, or handle single letters.
4. **"Not in the books" cannot be detected by score.** Absent questions averaged a top score of 10.5 against 17.4 for answerable ones, with overlap (absent "marginal cost" 12.9 > answerable "average" 7.0). → Level 2 needs more than a fixed threshold.
5. **One word, two meanings.** "Residual" (regression vs lease) ranked the right chunk only 4th.
6. **Chunk size trades precision against context, but cannot fix vocabulary.** 500-character chunks put the right passage first most often (Hit@1 0.48, MRR 0.61); 2,000-character chunks caught more answers in the top 3 (0.72) and every spanning question. Paraphrase Hit@3 stayed at 0.40 at every size: a size setting cannot match words that are not there.
7. **Read small differences with care.** There are 25 answerable questions, so one question moves a score by 0.04. Most differences here are 1–3 questions: suggestive, not conclusive. Bigger chunks also cover more pages each, which makes a page-overlap "hit" slightly easier to get, a bias in the measure itself.
8. **Cost is tiny.** Word search on about 2,400 chunks is effectively free (0.2 s to index, under 1 ms per query).

## Files

- `books.yaml`: the books, their licences and whether they may be used in the deployed tutor
- `src/extract.py`: step 1 for every level: PDF → text per page (`output/pages/*.jsonl`)
- `requirements-lab.txt`: lab-only packages
- *coming*: `testset/questions.yaml`, `src/chunkers.py`, `src/search.py`, `src/evaluate.py`

## Level 2: model comparison, llama3.2:3b vs qwen3.5:4b (14 Oct; v2 development, 198 answerable)

| Run | Hit@1 | Hit@3 | Hit@5 | MRR | Para light | Para medium | Para deep | Spelling | both@5 | Median s/question |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid (no AI step) | 0.52 | 0.72 | 0.79 | 0.63 | 0.48 | 0.73 | 0.41 | 0.22 | 0.37 | ~0 |
| rewrite, llama3.2:3b | 0.54 | 0.76 | 0.84 | 0.67 | 0.48 | 0.82 | 0.41 | 0.44 | 0.35 | 4.0 |
| rewrite, qwen3.5:4b | 0.57 | 0.80 | 0.85 | 0.69 | 0.71 | 0.77 | 0.65 | 0.33 | 0.40 | 9.8 |
| HyDE, llama3.2:3b | 0.58 | 0.81 | 0.87 | 0.71 | 0.62 | 0.68 | 0.76 | 0.44 | 0.38 | (cached; p90 12.3) |
| HyDE, qwen3.5:4b | 0.59 | 0.81 | 0.88 | 0.71 | 0.67 | 0.77 | 0.65 | 0.44 | 0.42 | **19.3** (p90 26.0) |

Paired: HyDE-qwen vs hybrid 62/25 (p = 0.0001); rewrite-qwen vs hybrid 45/17 (p = 0.0005); **HyDE qwen vs llama 41/35 (p = 0.57)**; **rewrite qwen vs llama 39/31 (p = 0.40)**.

### What the model comparison taught us
1. **The larger model is not significantly better** for either query step (p = 0.57 and 0.40). Both models give the same overall HyDE quality (Hit@3 0.81, MRR 0.71).
2. **Qwen is 2–5 times slower on this CPU** (HyDE median about 19 s vs a few seconds; rewrite about 10 s vs 4 s), partly because it writes longer, more formal paragraphs.
3. Qwen made rewrite much better on light and deep paraphrases (0.48 → 0.71, 0.41 → 0.65), narrowing the gap between rewrite and HyDE; this is suggestive only (slices of about 20 questions).
4. **Decision (proposed): llama3.2:3b + HyDE** for the query step: same quality, much faster. Model size matters more for the answer-writing step (Level 2 part 2), where it must be re-tested.

## Level 2: final re-rank and two-part fixes on top of HyDE (14 Oct; v2 development, llama3.2:3b)

| Run | Hit@1 | Hit@3 | MRR | Deep para | both@5 (all / cross-book / within) | Median s |
|---|---|---|---|---|---|---|
| hybrid | 0.52 | 0.72 | 0.63 | 0.41 | 0.37 / 0.28 / 0.45 | 0.01 |
| hybrid + diversity(2) + neighbours(2) | 0.52 | 0.65 | 0.60 | 0.29 | 0.33 / 0.28 / 0.39 | 0.01 |
| **HyDE** | **0.58** | **0.81** | **0.71** | **0.76** | 0.38 / 0.31 / 0.45 | 0.07 (cached) |
| HyDE + final re-rank (original question) | 0.51 | 0.78 | 0.66 | 0.59 | 0.47 / 0.52 / 0.42 | 1.4 |
| HyDE + diversity + neighbours | 0.58 | 0.75 | 0.69 | 0.71 | 0.35 / 0.24 / 0.45 | 0.09 |
| HyDE + all three | 0.51 | 0.71 | 0.63 | 0.41 | 0.48 / 0.45 / 0.52 | 1.5 |

Paired vs HyDE: + re-rank 37 better / 58 worse (p = 0.04); + diversity/neighbours 6/52 (p < 0.0001); all three 29/68 (p = 0.0001). "Both halves" gains were not significant (re-rank 10 gained / 5 lost, p = 0.30; all three 12/6, p = 0.24).

### What this taught us
1. **Diversity + neighbours clearly hurt** (6 better, 52 worse). Inserting the next section's chunk pushes correct passages down, and capping chunks per section removes the second chunk of the right section, which is often the answer itself. They also did not raise "both halves".
2. **The final re-rank also hurt overall** (Hit@1 0.58 → 0.51, deep paraphrases 0.76 → 0.59): the cross-encoder, trained on web search queries, prefers passages that repeat the question's words, undoing HyDE's meaning-based gains. It did help cross-book "both halves" (0.31 → 0.52), but not significantly.
3. **Decision (proposed): HyDE alone on hybrid search, no re-rank, no diversity/neighbour rules.** Two-part answers move to the answer stage (bounded agent with a coverage check).

## Held-out confirmation of HyDE (14 Oct; v2 held-out, 132 answerable, fresh AI calls)

| Run | Hit@1 | Hit@3 | Hit@5 | MRR | Direct | Para deep | Spanning | both@5 | Median s | 90th pct s |
|---|---|---|---|---|---|---|---|---|---|---|
| L5 fixed (baseline) | 0.36 | 0.57 | 0.68 | 0.49 | 0.75 | 0.15 | 0.57 | 0.17 | <0.01 | <0.01 |
| hybrid | 0.52 | 0.70 | 0.79 | 0.62 | 0.90 | 0.38 | 0.70 | 0.25 | 0.02 | 0.14 |
| **hybrid + HyDE (llama3.2:3b)** | **0.55** | **0.77** | **0.86** | **0.68** | 0.93 | **0.62** | 0.72 | 0.35 | **11.7** | **15.7** |

Paired: HyDE vs hybrid 47 better / 21 worse (p = 0.002, +8 questions in the top 3); HyDE vs baseline 68 / 19 (p < 0.00001, +26).

**Verdict:** HyDE's gain replicates on new questions (deep paraphrases 0.38 → 0.62). **Cost: about 12 s per question on this CPU (90% under 16 s)**, before any answer is written. Options to cut it at the tutor stage: cap the paragraph length, run HyDE only when plain hybrid search looks weak, or a faster server.

## Level 2, part 2: grounded answers, hallucination checks and a bounded agent (14–15 Oct; v2 development, stratified sample of 58: 48 answerable + 10 absent; llama3.2:3b)

Pipeline (`src/answer.py`, evaluated by `src/evaluate_answers.py`): gate (dense similarity ≥ 0.40, on the question and its spell-corrected form) → hybrid + HyDE search, 5 passages → ONE AI call returning schema-forced JSON (answerable, answer, claims with exact quotes, missing_part) → bounded agent (one extra search for a missing part) → checks in code (quotes found in the cited passage; every "=" step recomputed with the tutor's SymPy checker; numbers must come from the passages/question; complete-sentence answer) → if checks fail, the student sees the best passages instead (fallback).

| Version | Absent refused | Answerable answered | Fallback | Wrongly refused | Correct citation (answered) | Quotes verified | Median s (new calls) |
|---|---|---|---|---|---|---|---|
| v2 (14 Oct) | **10/10** | 56% | 31% | 12.5% | 70% | 68/83 | 55 |
| v3 (15 Oct) | 8/10 ❌ | 71% | 29% | 0% | 71% | 46/52 | 49 |
| **v4-lite (15 Oct)** | **10/10** | **73%** | **19%** | 8% | 69% | 40/45 | 46 |

v4-lite vs v2: 13 questions gained an answer, 5 lost (sign test p = 0.10, not significant on 48 questions); vs v3: 7 / 6.

### What part 2 taught us
1. **A small model must be forced into a simple output shape.** v2's nested JSON ("parts" with "covered_by" lists) broke in about 1 in 8 replies and lost the answer. A flat schema enforced by Ollama, plus an example in the prompt, fixed it (schema alone made the model loop).
2. **Safety and usefulness pull against each other.** v3's looser prompt ("different names or currencies are still answerable") answered 2 absent questions with real but irrelevant passages and turned a real exchange-rate table value into "114.9287 dalasis per euro". Prompt-based refusal is unreliable for small models (matches RINSE 2026; Sufficient Context, ICLR 2025). Removed in v4-lite.
3. **Each check catches a different error.** Quote checks prove the words are from the book, not that they answer the question; number checks prove a number exists, not what it means; SymPy caught real arithmetic slips (e.g. dividing by 21 credit hours that sum to 19). A small fact-checker (HHEM-2.1-Open, `src/check_faithfulness.py`) scored all human-approved answers ≥ 0.97 and the bad ones 0.08–0.57, but would block 44% of answers at cut-off 0.6 and costs ~12 s per answer on CPU → parked (workspace `03_PARKED_IDEAS.md` P3).
4. **Comparing PDF text must ignore extraction glitches** ("anycontrol"): quotes are compared on letters and digits only; a quote credited to the wrong passage is re-attributed by code and recorded as `_moved`.
5. **Latency is the deployment problem**: ~46 s per answer on this CPU laptop (HyDE + answer call). To reduce at tutor integration (fewer passages, shorter answers, caching, HyDE only when the first search is weak).

Remaining misses (v4-lite): 4 wrong refusals (two dalasi questions: the books use dollars, contextualisation parked as P4; "trade discount" and "mark-up" wording), 9 fallbacks (5 quote mismatches, 2 empty, 2 incomplete). Human review of answers: `output/results/answers-v2-REVIEW.csv` (my review, 5 rows so far).
