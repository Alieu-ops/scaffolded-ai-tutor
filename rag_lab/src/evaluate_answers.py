r"""
Evaluate Level 2 part 2: does the pipeline in answer.py answer, refuse and cite correctly?

Run from the app folder (Ollama running), e.g. 10 questions of each type from the development set:
    .\.venv\Scripts\python.exe rag_lab\src\evaluate_answers.py --testset v2_dev --per-type 10

Answering is slow on a CPU (HyDE + one or two answer calls per question), so a stratified SAMPLE
is used: the same random questions each time (fixed seed), so runs are comparable.

Automatic measures (no AI judge):
    correct refusal   absent question -> "not covered" (by the gate or by the AI)
    wrong refusal     answerable question -> "not covered"           (should be rare)
    answered          answerable question -> a verified answer was shown
    fallback          the AI's answer failed verification -> passages shown instead
    citation hit      a cited passage lies in the expected pages (answered questions)
    context hit       the passages given to the AI contained the expected pages at all
    all parts found   spanning questions: every expected section was among the passages
    quotes verified   share of the AI's quotes found in the passage they cite
Human review: answers_<label>.csv has empty columns for me to judge correctness and
faithfulness of a sample, which no automatic check can fully replace.
"""

from __future__ import annotations

import argparse
import csv
import random
import time

import requests
from statistics import mean, median

from answer import PIPELINE_VERSION, POLICY, AnswerPipeline, cite
from common import RESULTS_DIR, load_pages, load_testset, use_utf8_output
from evaluate import build_chunks, is_hit
from llm import DEFAULT_MODEL, check_ollama

EXCLUDE = {"summary", "front_back", "case_study", "solutions", "formulas"}


def sample(questions: list[dict], per_type: int, seed: int) -> list[dict]:
    by_type: dict[str, list[dict]] = {}
    for q in questions:
        by_type.setdefault(q["type"], []).append(q)
    rng = random.Random(seed)
    chosen = []
    for kind in sorted(by_type):
        group = sorted(by_type[kind], key=lambda q: q["id"])
        chosen += rng.sample(group, min(per_type, len(group)))
    return chosen


def answer_with_retry(pipeline, question: str):
    """One retry after a pause if the connection to Ollama fails (timeout, restart, laptop sleep)."""
    for attempt in (1, 2):
        try:
            return pipeline.answer(question)
        except requests.RequestException as error:
            print(f"    connection problem ({type(error).__name__}); {'retrying in 15 s' if attempt == 1 else 'giving up'}")
            if attempt == 1:
                time.sleep(15)
        except Exception as error:                     # an unexpected reply shape etc.: report it, keep going
            print(f"    pipeline error: {type(error).__name__}: {error}")
            return None
    return None


def save(rows: list[dict], path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:        # utf-8-sig: opens cleanly in Excel
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    use_utf8_output()
    parser = argparse.ArgumentParser()
    parser.add_argument("--testset", default="v2_dev")
    parser.add_argument("--per-type", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--llm", default=DEFAULT_MODEL)
    parser.add_argument("--no-hyde", action="store_true")
    parser.add_argument("--no-agent", action="store_true")
    args = parser.parse_args()
    check_ollama(args.llm)

    testset = load_testset(args.testset)
    questions = sample(testset["questions"], args.per_type, args.seed)
    chunks = build_chunks(load_pages(testset["books_indexed"], "clean"), "structure", 1000, exclude=EXCLUDE)
    pipeline = AnswerPipeline(chunks, args.llm, use_hyde=not args.no_hyde, agent=not args.no_agent)
    label = (f"answers-{PIPELINE_VERSION}-{POLICY}-{args.llm.replace(':', '_')}{'-nohyde' if args.no_hyde else ''}"
             f"{'-noagent' if args.no_agent else ''}-{args.testset.upper()}")

    rows = []
    for n, q in enumerate(questions, start=1):
        started = time.perf_counter()
        r = answer_with_retry(pipeline, q["question"])
        seconds = time.perf_counter() - started
        if r is None:                                  # Ollama failed twice: record it and carry on
            print(f"{n:>3}/{len(questions)} {q['id']:<6} ERROR (see message above); skipped")
            continue
        expected = q.get("expected") or []
        cited = [r.passages[c["passage"] - 1] for c in r.claims if c["passage"]] if r.decision == "answered" else []
        refused = r.decision in ("not_found_gate", "not_found_model")
        rows.append({
            "id": q["id"], "type": q["type"], "subtype": q.get("subtype", ""), "question": q["question"],
            "decision": r.decision, "refused": int(refused),
            "correct_refusal": int(q["type"] == "absent" and refused),
            "wrong_refusal": int(q["type"] != "absent" and refused),
            "context_hit": int(any(is_hit(c, expected) for c in r.passages)) if expected else "",
            "citation_hit": int(any(is_hit(c, expected) for c in cited)) if expected and cited else "",
            "all_parts_in_context": int(all(any(is_hit(c, [t]) for c in r.passages) for t in expected))
                                    if len(expected) > 1 else "",
            "retried": int(r.retried),
            "passes_strict": int(r.passes_strict), "passes_majority": int(r.passes_majority),
            "quotes": len(r.claims), "quotes_verified": sum(c["quote_ok"] for c in r.claims),
            "quotes_moved": sum(c["quote_status"].endswith("_moved") for c in r.claims),
            "gate_similarity": round(r.gate_similarity, 3),
            "problems": " | ".join(r.problems),
            "shown_to_student": r.answer, "ai_draft": r.model_answer,
            "passages": " || ".join(cite(c) for c in r.passages),
            "expected": "; ".join(f"{e['book']} p{e['pages'][0]}-{e['pages'][1]}" for e in expected),
            "seconds": round(seconds, 1),
            "human_correct (yes/partly/no)": "", "human_faithful (yes/no)": "", "human_notes": "",
        })
        print(f"{n:>3}/{len(questions)} {q['id']:<6} {q['type']:<14} {r.decision:<15} {seconds:6.1f}s")
        save(rows, RESULTS_DIR / f"{label}.csv")       # after EVERY question, so a crash loses nothing

    out = RESULTS_DIR / f"{label}.csv"

    absent = [r for r in rows if r["type"] == "absent"]
    answerable = [r for r in rows if r["type"] != "absent"]
    answered = [r for r in answerable if r["decision"] == "answered"]
    spanning = [r for r in rows if r["all_parts_in_context"] != ""]
    pct = lambda xs: f"{100 * mean(xs):.0f}%" if xs else "-"
    print(f"\n{label}: {len(rows)} questions ({len(answerable)} answerable, {len(absent)} absent)")
    print(f"  absent questions correctly refused:  {pct([r['correct_refusal'] for r in absent])}")
    print(f"  answerable wrongly refused:          {pct([r['wrong_refusal'] for r in answerable])}")
    print(f"  answerable answered (verified):      {pct([r['decision'] == 'answered' for r in answerable])}")
    print(f"  answerable sent to fallback:         {pct([r['decision'] == 'fallback' for r in answerable])}")
    print(f"  right pages given to the AI:         {pct([r['context_hit'] for r in answerable if r['context_hit'] != ''])}")
    print(f"  answered with a correct citation:    {pct([r['citation_hit'] for r in answered if r['citation_hit'] != ''])}")
    print(f"  spanning: all parts in context:      {pct([r['all_parts_in_context'] for r in spanning])}"
          f"  (agent retried on {sum(r['retried'] for r in rows)} questions)")
    print(f"  would pass, strict policy:           {pct([r['passes_strict'] for r in answerable])}")
    print(f"  would pass, majority policy:         {pct([r['passes_majority'] for r in answerable])}")
    quotes = sum(r["quotes"] for r in rows)
    print(f"  quotes verified in code:             {sum(r['quotes_verified'] for r in rows)}/{quotes}")
    print(f"  seconds per question: median {median(r['seconds'] for r in rows):.1f}, "
          f"max {max(r['seconds'] for r in rows):.1f}")
    print(f"\nSaved {out}  <- open in Excel; fill the human_ columns for a sample")


if __name__ == "__main__":
    main()
