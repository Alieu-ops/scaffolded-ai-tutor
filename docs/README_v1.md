# AI tutor prototype: higher education (Quantitative Methods and Business Mathematics)

A research instrument for a three-arm study (scaffolded AI tutor / unrestricted AI
assistant / no-AI control) with higher-education students in The Gambia. It is a
separate copy of the senior secondary version (repo `ai-tutor`), with its own content,
settings, logs and search index. **Prototype only: not evaluated.**

## Status
- Skill map (6 skills, 20 sub-skills) and 37 original items: **DRAFT**, based on typical
  first-year course outlines; to be adapted to partner institutions' outlines.
- Prompts: same tutoring rules as the senior secondary version, worded for university students.
- Knowledge notes for retrieval (RAG): one **DRAFT** file per skill in `data/knowledge/`
  (32 passages). After editing them, rebuild the index: `python -m tutor.retrieval build`.
  A test checks that no note contains an item's answer.

## Set up (first time, on a new computer)
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
(On my laptop, where this folder sits inside `ai-tutor`, the launchers use the
parent's `..\.venv` instead.)

## Run
```
streamlit run app.py --server.port 8502   # or double-click start_app.bat
python -m tutor.cli                       # whole session in the terminal
python -m tutor.skills                    # summary of the skill map and items
pytest                                    # offline tests
pytest -m live -s                         # live "never give the answer" test
```

## Where things are
```
config.yaml          all settings: arm, model, file paths, session length
data/skills.yaml     skill map
data/items.csv       practice questions (status: draft / reviewed)
data/prompts.yaml    system prompt for each arm
data/knowledge/      course notes for retrieval (to do)
tutor/               the code (same design as the senior secondary version)
```

## Research rules
Both AI arms use the same model and settings; the scaffolded tutor never gives the final
answer (checked in code, leaks logged); no fine-tuning; original questions only; no real
student data before ethics approval; participant codes only; never commit API keys or logs.
