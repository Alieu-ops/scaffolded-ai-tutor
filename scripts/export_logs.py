"""
Export the interaction logs from SQLite to a CSV file for analysis in
Python, R or Stata.

Run from the project folder:
    python scripts/export_logs.py
Output: exports/events_<date-time>.csv
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tutor.skills import PROJECT_ROOT, load_config  # noqa: E402

config = load_config()
db_path = PROJECT_ROOT / config["logging"]["db_file"]
if not db_path.exists():
    sys.exit(f"No log database yet at {db_path}. Run a session first.")

with sqlite3.connect(db_path) as conn:
    events = pd.read_sql_query("SELECT * FROM events ORDER BY id", conn)
events["correct"] = events["correct"].astype("Int64")   # 0/1, blank if not an attempt

out_dir = PROJECT_ROOT / "exports"
out_dir.mkdir(exist_ok=True)
out_file = out_dir / f"events_{datetime.now():%Y%m%d_%H%M%S}.csv"
events.to_csv(out_file, index=False, encoding="utf-8")

print(f"Exported {len(events)} events from "
      f"{events['participant_code'].nunique()} participants to {out_file}")
print(events.groupby(["arm", "event_type"]).size().to_string())
