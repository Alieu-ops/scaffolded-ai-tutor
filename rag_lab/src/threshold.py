r"""
Choose a "not in the books" cut-off on the DEVELOPMENT results, then test it, unchanged, on
the HELD-OUT results. This is the honest way to set a threshold: pick on one set, judge on another.

Run from the app folder (after the dev and held-out evaluate.py runs exist):
    .\.venv\Scripts\python.exe rag_lab\src\threshold.py

THE RULE BEING TESTED, in plain language:
    "If the best passage's score is at or below the cut-off, say the books do not cover this
     question instead of answering from a weak match."
Two kinds of mistake are possible:
    missed absent  = an uncovered question gets answered anyway (risk: invented answer)
    wrong refusal  = a covered question is refused (risk: unhelpful tutor)

Two ways of choosing the cut-off on development:
    balanced  : maximise the average of (absent caught %) and (answerable kept %)
    cautious  : catch as many absent questions as possible while wrongly refusing at most 5%
                of answerable ones (a tutor that refuses too often is not used)

Signals compared:
    dense   the cosine similarity of the best chunk from meaning search (0 to 1)
    rerank  the cross-encoder relevance score of the best chunk (unbounded)
The gate can sit in front of any retriever: e.g. rank with hybrid, but decide "not found" with
the dense similarity of the question to its closest chunk.
"""

from __future__ import annotations

import csv
from statistics import mean

from common import RESULTS_DIR, use_utf8_output

STRUCTURE = "structure-1000-ov0-excl-case_study+formulas+front_back+solutions+summary-clean"
SIGNALS = {
    "dense": f"L3a-dense-{STRUCTURE}",
    "rerank": f"L3c-hybrid+rerank-{STRUCTURE}",
}
MAX_WRONG_REFUSALS = 0.05


def load(label: str, tag: str) -> list[dict]:
    path = RESULTS_DIR / f"{label}-{tag}_questions.csv"
    if not path.exists():
        raise SystemExit(f"Missing {path.name}. Run that setup with --testset {tag.lower()} first.")
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rates(rows: list[dict], cutoff: float) -> tuple[float, float, list[dict]]:
    """(share of absent questions refused, share of answerable questions refused, the wrongly refused rows)."""
    absent = [r for r in rows if r["type"] == "absent"]
    answerable = [r for r in rows if r["type"] != "absent"]
    refused = lambda r: float(r["top_score"]) <= cutoff
    wrong = [r for r in answerable if refused(r)]
    return mean(refused(r) for r in absent), len(wrong) / len(answerable), wrong


def choose(rows: list[dict]) -> dict[str, float]:
    """Try every observed score as a cut-off; return the best one under each criterion."""
    candidates = sorted({float(r["top_score"]) for r in rows})
    best_balanced = max(candidates, key=lambda c: (lambda a, w: (a + (1 - w)) / 2)(*rates(rows, c)[:2]))
    allowed = [c for c in candidates if rates(rows, c)[1] <= MAX_WRONG_REFUSALS]
    best_cautious = max(allowed, key=lambda c: rates(rows, c)[0]) if allowed else min(candidates)
    return {"balanced": best_balanced, "cautious": best_cautious}


def main() -> None:
    use_utf8_output()
    print("Cut-offs are CHOSEN on V2_DEV and then APPLIED UNCHANGED to V2_HELDOUT.\n")
    print(f"{'signal':<8}{'rule':<10}{'cut-off':>9}   {'DEV absent caught':>18}{'wrong refusals':>16}"
          f"   {'HELD-OUT absent caught':>23}{'wrong refusals':>16}")
    for signal, label in SIGNALS.items():
        dev, held = load(label, "V2_DEV"), load(label, "V2_HELDOUT")
        for rule, cutoff in choose(dev).items():
            dev_caught, dev_wrong, _ = rates(dev, cutoff)
            held_caught, held_wrong, wrong_rows = rates(held, cutoff)
            print(f"{signal:<8}{rule:<10}{cutoff:>9.3f}   {dev_caught:>18.0%}{dev_wrong:>16.0%}"
                  f"   {held_caught:>23.0%}{held_wrong:>16.0%}")
            # How much did the wrong refusals cost? Were the right passages actually found?
            found = sum(1 for r in wrong_rows if r["first_hit_rank"] and int(r["first_hit_rank"]) <= 3)
            if wrong_rows:
                print(f"{'':<27}held-out wrong refusals: {len(wrong_rows)}, of which {found} had the right "
                      f"passage in the top 3 (genuinely lost answers)")
        # Which absent questions slip through on held-out with the balanced rule?
        cutoff = choose(dev)["balanced"]
        missed = [r for r in held if r["type"] == "absent" and float(r["top_score"]) > cutoff]
        by_kind = {k: sum(r["subtype"] == k for r in missed) for k in ("near_miss", "far", "off_topic")}
        print(f"{'':<27}held-out absent questions NOT caught (balanced): {len(missed)} {by_kind}\n")


if __name__ == "__main__":
    main()
