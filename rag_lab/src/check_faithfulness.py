r"""
Offline test of a small FACT-CHECKER model on answers we already have (no new AI calls).

Question: can a specialised checker catch what our quote and number checks missed?
  - n021, n016 (v3): absent questions "answered" with real but irrelevant quotes
  - p037 (v3): "114.9287 dalasis per euro" (a real table number, relabelled)
  - s019 (v2): loan steps mixed in from the wrong section
...while still passing answers I judged correct and faithful (d033, d071, d038).

Model: HHEM-2.1-Open (Vectara, Apache-2.0, built on Flan-T5-base, ~600 MB RAM, CPU is fine).
It takes (premise, hypothesis) and returns 0..1: 1 = the premise supports the hypothesis.

How we use it:
  each sentence of the answer is checked against each passage the AI was given;
  sentence score = best passage score  (supported by at least one passage?)
  answer score   = weakest sentence    (one unsupported sentence is enough to fail)

Security: the model needs trust_remote_code=True (its own small Python file). That file was read
on 15 Oct 2026 (it only wraps Flan-T5 with a fixed prompt) and is PINNED to that exact revision,
so a later change on Hugging Face cannot run on this computer without us noticing.

Run from the app folder (first run downloads ~1 GB: the checker + the flan-t5-base tokenizer):
    .\.venv\Scripts\python.exe rag_lab\src\check_faithfulness.py
"""

from __future__ import annotations

import re
import time

import pandas as pd

from answer import cite
from common import RESULTS_DIR, load_pages, load_testset, use_utf8_output
from evaluate import build_chunks
from evaluate_answers import EXCLUDE

HHEM = "vectara/hallucination_evaluation_model"
HHEM_REVISION = "de9a5e6ba9ba49531a022dba17e35ffeb2a6fad8"      # code reviewed 15 Oct 2026
FILES = {"v2": "answers-v2-majority-llama3.2_3b-V2_DEV.csv", "v3": "answers-v3-majority-llama3.2_3b-V2_DEV.csv"}

# What we already know about some answers: my review (good) and the cases found on 15 Oct (bad)
KNOWN = {("v2", "d033"): "good", ("v2", "d071"): "good", ("v2", "d038"): "good", ("v3", "d057"): "good",
         ("v3", "n021"): "bad", ("v3", "n016"): "bad", ("v3", "p037"): "bad", ("v2", "s019"): "bad",
         ("v2", "p097"): "bad"}


def sentences(text: str) -> list[str]:
    text = re.split(r"\s*(?:Claims?:|Missing_part:)", str(text))[0]     # drop claims spilled into the answer
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if len(p.split()) >= 4]                 # skip tiny fragments like "e.g."


def main() -> None:
    use_utf8_output()
    from transformers import AutoModelForSequenceClassification      # imported here: slow to load

    testset = load_testset("v2_dev")
    chunks = build_chunks(load_pages(testset["books_indexed"], "clean"), "structure", 1000, exclude=EXCLUDE)
    by_cite: dict[str, list[str]] = {}
    for c in chunks:                                                  # citation label -> passage texts
        by_cite.setdefault(cite(c), []).append(c.text)

    model = AutoModelForSequenceClassification.from_pretrained(HHEM, revision=HHEM_REVISION, trust_remote_code=True)

    rows = []
    for version, name in FILES.items():
        data = pd.read_csv(RESULTS_DIR / name, encoding="utf-8-sig")
        for _, r in data[data.ai_draft.notna()].iterrows():
            premises = list(dict.fromkeys(t for label in str(r.passages).split(" || ")
                                          for t in by_cite.get(label.strip(), [])))
            claims = sentences(r.ai_draft)
            if not premises or not claims:
                continue
            started = time.perf_counter()
            pairs = [(p, s) for s in claims for p in premises]
            scores = model.predict(pairs).tolist()
            per_sentence = [max(scores[i * len(premises):(i + 1) * len(premises)]) for i in range(len(claims))]
            weakest = min(range(len(claims)), key=lambda i: per_sentence[i])
            rows.append({"version": version, "id": r.id, "type": r.type, "decision": r.decision,
                         "known": KNOWN.get((version, r.id), ""), "hhem_answer": round(per_sentence[weakest], 3),
                         "hhem_mean": round(sum(per_sentence) / len(per_sentence), 3),
                         "weakest_sentence": claims[weakest], "sentences": len(claims), "pairs": len(pairs),
                         "seconds": round(time.perf_counter() - started, 1), "question": r.question})
            print(f"{version} {r.id:<5} {r.decision:<9} {rows[-1]['known']:<4} score {rows[-1]['hhem_answer']:.2f}"
                  f"  ({len(pairs)} pairs, {rows[-1]['seconds']} s)")

    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / "faithfulness-hhem.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 90)
    print("\nKNOWN CASES (bad should score LOW, good should score HIGH):")
    print(out[out.known != ""].sort_values("hhem_answer")[["version", "id", "known", "hhem_answer", "weakest_sentence"]]
          .to_string(index=False))
    print("\nAnswers to ABSENT questions vs answerable ones (answer score):")
    out["group"] = out.type.where(out.type == "absent", "answerable")
    print(out.groupby(["group", "decision"]).hhem_answer.describe()[["count", "mean", "min", "50%", "max"]])
    for cut in (0.3, 0.5, 0.7):
        answered = out[out.decision == "answered"]
        flagged = answered[answered.hhem_answer < cut]
        print(f"cut-off {cut}: would block {len(flagged)}/{len(answered)} shown answers; "
              f"bad caught {sum(flagged.known == 'bad')}/{sum(answered.known == 'bad')}, "
              f"good blocked {sum(flagged.known == 'good')}/{sum(answered.known == 'good')}")
    print(f"\nseconds per answer: median {out.seconds.median()}, max {out.seconds.max()}")
    print(f"Saved {RESULTS_DIR / 'faithfulness-hhem.csv'}")


if __name__ == "__main__":
    main()
