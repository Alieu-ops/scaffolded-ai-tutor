# Scaffolded AI tutor for Quantitative Methods (exploratory prototype)

An AI tutor for first-year Quantitative Methods and Business Mathematics
students in The Gambia. I built it to find out whether a tutor can help
students reason through a problem instead of doing it for them, and to learn
how language models and retrieval work together. It is an exploration, not a
product.

**Status: local prototype with synthetic data. Not evaluated and not used
with students.** No real student data would be used without ethics and
institutional approval.

## Why I built it

As an undergraduate I tutored fellow students in economics and mathematics
because there were not enough tutors. AI tutors could help with that
shortage, but a chatbot that hands out answers lets students skip the
thinking. I wanted to see whether a tutor can be designed to help students
reason through a problem instead of doing it for them. While building it, I
realised that every message a student sends records how they use the AI, so a
tutor could also show how students work with AI.

## How it was built

I designed how the tutor should behave: the scaffolding levels, the rules
and what the lecturer controls. The code was written with
an AI coding assistant, and I tested it, ran it and decided on every change.
The design decisions are recorded in `docs/DESIGN_DECISIONS.md`. The course
notes, practice items and retrieval test questions are drafts written with AI
assistance that I am still reviewing.

## Main ideas

- **The AI is not in charge of correctness.** Answers and each line of a
  student's working are checked by code (a safe parser and SymPy), never by
  the language model. The model only phrases feedback.
- **It never gives the final answer.** The model never sees the answer or the
  worked solution, and every reply is checked by a leak guard before the
  student sees it. In a live test with the local Llama 3.2 3B model, it tried
  to give away the answer in 5 of 30 replies; all 5 were caught.
- **Hints are chosen by code, not by the model.** A hint ladder with levels
  0 to 7, from a light nudge up to an analogous worked example, follows a policy
  file that the lecturer approves.
- **The lecturer stays in the loop.** Lecturers review content, approve the
  scaffolding policy and see a dashboard of where students struggle.
- **A comparison mode.** An unrestricted AI assistant uses the same model
  and settings without the tutoring rules, so the effect of the rules can be
  seen side by side.
- **Privacy by design.** Demo codes only, exports with anonymous IDs and no
  raw text, and logs never committed.
- **Runs offline** on a 16 GB laptop with no GPU, using a local model through
  Ollama, because internet access is not reliable for many students.

## What is in this repository

| Folder | What it is |
|---|---|
| `qmtutor/` | Version 2: the domain rules, maths checking, storage, retrieval, LLM layer and services |
| `app_pages/`, `streamlit_app.py` | Version 2 interface (student, lecturer, researcher and administrator views) |
| `content/`, `policies/`, `prompts/` | Curriculum map, items, misconceptions, scaffolding policy and prompts (drafts) |
| `rag_lab/` | Experiments on retrieval (RAG): chunking and search methods compared on a test set of 429 questions, then confirmed on a held-out set |
| `tests/` | Automated tests (215 offline tests for version 2) |
| `tutor/`, `app.py`, `data/` | Version 1: the first, simpler tutor, built for an earlier design (see below) |
| `docs/` | Design decisions, how to run version 2, notes on version 1 and test outputs |

## Run it

```
pip install -r requirements.txt
ollama pull llama3.2:3b
python -m qmtutor.seed
streamlit run streamlit_app.py --server.port 8504
```

Sign in with a demo account: S001 (scaffolded tutor), S002 (unrestricted AI),
L001 (lecturer), R001 (researcher) or A001 (administrator).
More detail in `docs/RUNNING_V2.md`.

Tests: `pytest tests/v2` (offline). The live tests need Ollama running.

## Limits (honest list)

- The code still contains a no-AI option from an earlier version (demo
  account S003). It is not used: work done by hand cannot be recorded in the
  tutor.
- The small local model sometimes gives generic or slightly wrong feedback.
- Demo accounts only; no real sign-in yet.
- Multi-part answers and unit conversion are not handled yet.
- Not tested on phones or with many users at once.
- Textbooks are never stored in the repository (copyright). Only openly
  licensed books are used for retrieval experiments.

## What I learned

- Running a language model locally and grounding its answers in course
  materials.
- Controlling what a model can reveal with code, not only with the prompt.
- Evaluating retrieval properly, with a held-out test set.
- What I cannot yet do well: how these models work underneath, securing
  student data, and judging when a system is responsible to deploy. This is
  what I want to learn in a PhD.
