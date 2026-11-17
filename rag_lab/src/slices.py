r"""
Break results down by question type, subtype and style, and compare RAW vs CLEAN text fairly.

Run from the app folder, e.g.:
    .\.venv\Scripts\python.exe rag_lab\src\slices.py V2_DEV
    .\.venv\Scripts\python.exe rag_lab\src\slices.py V2_HELDOUT

It reads every per-question results file whose name ends with that test-set tag.

Part 1  one row per setup: overall scores, then Hit@3 for each question type and subtype.
Part 2  raw vs clean, for each setup run both ways: on how many questions did clean do better,
        worse, or the same (comparing the rank of the first correct chunk), plus a sign test.

THE SIGN TEST, in plain language: ignore the ties; if cleaning made no real difference, wins
and losses would be like coin flips (50/50). The p-value is the chance of seeing a split at
least this lopsided from fair coin flips. Small p (below 0.05) suggests a real effect; large p
means the difference could easily be chance. It is a paired test: each question is compared
with itself, which is fairer than comparing two averages.
"""

from __future__ import annotations

import csv
import sys
from math import comb
from statistics import mean

from common import RESULTS_DIR, use_utf8_output


def load(path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rank(row: dict) -> int:
    """Rank of the first correct chunk; 11 = not in the top 10 (worse than any real rank)."""
    return int(row["first_hit_rank"]) if row["first_hit_rank"] else 11


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact binomial test with p = 0.5 on the non-tied questions."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    p = sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def short(label: str, tag: str) -> str:
    """Make long labels readable: drop the exclude list and the test-set tag."""
    name = label.replace(f"-{tag}", "").replace("-excl-case_study+formulas+front_back+solutions+summary", "+excl")
    return name.replace("-1000-ov0", "")


def main(argv: list[str]) -> None:
    use_utf8_output()
    tag = (argv[0] if argv else "V2_DEV").upper()
    files = sorted(RESULTS_DIR.glob(f"*-{tag}_questions.csv"))
    if not files:
        raise SystemExit(f"No results for {tag}. Run evaluate.py with --testset {tag.lower()} first.")
    runs = {f.name[: -len("_questions.csv")]: load(f) for f in files}

    # Part 1: scores by slice
    slices = [("type", "direct"), ("type", "paraphrase"), ("subtype", "light"), ("subtype", "medium"),
              ("subtype", "deep"), ("type", "spanning"), ("type", "grammar_error"), ("type", "spelling_error")]
    print(f"\nPART 1. Scores on {tag} (Hit@3 per slice; 'paraphrase light/medium/deep' are its subtypes)\n")
    header = f"{'setup':<44}{'Hit@1':>6}{'Hit@3':>6}{'MRR':>6}" + "".join(f"{v[:6]:>8}" for _, v in slices) + f"{'both@5':>8}"
    print(header)
    for label, rows in runs.items():
        answerable = [r for r in rows if r["type"] != "absent"]
        cells = [mean(int(r["hit@1"]) for r in answerable), mean(int(r["hit@3"]) for r in answerable),
                 mean(float(r["reciprocal_rank"]) for r in answerable)]
        line = f"{short(label, tag)[:43]:<44}" + "".join(f"{c:>6.2f}" for c in cells)
        for field, value in slices:
            group = [r for r in answerable if r.get(field) == value and (field == "type" or r["type"] == "paraphrase")]
            line += f"{mean(int(r['hit@3']) for r in group):>8.2f}" if group else f"{'-':>8}"
        spanning = [r for r in rows if r["type"] == "spanning"]
        line += f"{mean(int(r['all_expected@5']) for r in spanning):>8.2f}" if spanning and "all_expected@5" in spanning[0] else f"{'-':>8}"
        print(line)

    # Part 2: raw vs clean, paired
    print(f"\nPART 2. Raw vs clean, question by question (answerable questions; better = higher rank with clean)\n")
    print(f"{'setup':<44}{'clean better':>13}{'worse':>7}{'same':>6}{'sign-test p':>13}  verdict")
    for label, rows in runs.items():
        if "-clean" in label:
            continue
        clean_label = label.replace(f"-{tag}", f"-clean-{tag}")
        if clean_label not in runs:
            continue
        raw = {r["id"]: rank(r) for r in rows if r["type"] != "absent"}
        cln = {r["id"]: rank(r) for r in runs[clean_label] if r["type"] != "absent"}
        better = sum(cln[q] < raw[q] for q in raw)
        worse = sum(cln[q] > raw[q] for q in raw)
        same = len(raw) - better - worse
        p = sign_test(better, worse)
        verdict = ("clean better" if better > worse else "raw better") if p < 0.05 else "no clear difference"
        print(f"{short(label, tag)[:43]:<44}{better:>13}{worse:>7}{same:>6}{p:>13.3f}  {verdict}")

    # Part 3: setups against each other (clean text), paired
    clean_runs = {label: rows for label, rows in runs.items() if "-clean" in label}
    references = [label for label in clean_runs if label.startswith(("L5-fixed", "L3b-hybrid-"))]
    if references:
        print(f"\nPART 3. Setups compared with the baseline (L5 fixed) and with hybrid, clean text, paired\n")
        print(f"{'setup':<36}{'vs':<14}{'better':>8}{'worse':>7}{'p':>8}  verdict")
    for reference in references:
        ref = {r["id"]: rank(r) for r in clean_runs[reference] if r["type"] != "absent"}
        ref_name = "L5 fixed" if reference.startswith("L5") else "hybrid"
        for label, rows in clean_runs.items():
            if label == reference:
                continue
            other = {r["id"]: rank(r) for r in rows if r["type"] != "absent"}
            better = sum(other[q] < ref[q] for q in ref)
            worse = sum(other[q] > ref[q] for q in ref)
            p = sign_test(better, worse)
            verdict = ("better" if better > worse else "worse") + f" than {ref_name}" if p < 0.05 else "no clear difference"
            print(f"{short(label, tag).replace('-clean', '')[:35]:<36}{ref_name:<14}{better:>8}{worse:>7}{p:>8.3f}  {verdict}")


if __name__ == "__main__":
    main(sys.argv[1:])
