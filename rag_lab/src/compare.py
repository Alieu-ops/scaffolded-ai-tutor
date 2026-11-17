r"""
Show every run in output/results/summary.csv side by side, so levels can be compared at a glance.

Run from the app folder:
    .\.venv\Scripts\python.exe rag_lab\src\compare.py

If the same setup was run more than once, only its latest row is shown.
"""

from __future__ import annotations

import csv

from common import RESULTS_DIR

COLUMNS = [  # (column in summary.csv, heading to print, width)
    ("label", "run", 52), ("chunks", "chunks", 7), ("hit@1", "Hit@1", 6), ("hit@3", "Hit@3", 6),
    ("hit@5", "Hit@5", 6), ("mrr", "MRR", 6), ("direct_hit@3", "direct", 7),
    ("paraphrase_hit@3", "para", 6), ("spanning_hit@3", "span", 6),
    ("top1_not_content", "top1 non-content", 17), ("avg_top_score_absent", "absent score", 13),
    ("index_seconds", "index s", 8),
]


def main() -> None:
    path = RESULTS_DIR / "summary.csv"
    if not path.exists():
        raise SystemExit("No results yet. Run evaluate.py first.")
    with path.open(newline="", encoding="utf-8") as f:
        latest = {row["label"]: row for row in csv.DictReader(f)}    # later rows replace earlier ones
    print("".join(f"{heading:<{width}}" for _, heading, width in COLUMNS))
    for row in latest.values():
        print("".join(f"{str(row.get(key, '')):<{width}}" for key, _, width in COLUMNS))


if __name__ == "__main__":
    main()
