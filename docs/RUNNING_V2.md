# Quantitative Methods tutor: version 2 (`qmtutor`)

Technical guide for version 2. It runs next to version 1 (`app.py`, `tutor/`),
which is unchanged.

**Status: local demonstration prototype with synthetic data. Not pilot-ready.**
Content is draft and was approved only by a *synthetic* demo lecturer. No real student
data may be used before ethics and institutional approval.

## Run it (Windows)

**Easiest:** double-click `start_tutor_v2.bat` (or open `run_tutor_v2.py` in Spyder/VS Code and press Run).
It starts Ollama if needed, creates the demo database the first time, and opens http://localhost:8504.

Manual steps (Ollama must be running with the model pulled: `ollama pull llama3.2:3b`):

```
python -m qmtutor.seed              # create the demo database (once)
streamlit run streamlit_app.py --server.port 8504
```
Then sign in with a demo account:

| Account | What it shows |
|---|---|
| S001 | scaffolded tutor (hints, never the answer) |
| S002 | unrestricted AI (same model, no policy) |
| S003 | existing support (no AI): kept from an earlier version, not used |
| L001 | lecturer: dashboard, content review, policy |
| R001 | researcher: assignment, assessments, export |
| A001 | administrator: system health |

Reset the demo data: `python -m qmtutor.seed --reset`

## Tests

```
python -m pytest                       # offline: v1 + v2 (fast)
python -m pytest tests/v2 -m live -s   # live: real Ollama model (slow)
python -m pytest -m regression        # the tests written after real bugs
python scripts/retrieval_benchmark.py  # lexical vs embedding retrieval
python -m qmtutor.content.importer     # validate content files only
```

## Architecture (inside out)

```
qmtutor/domain/      models.py (Pydantic shapes), scaffold_policy.py (levels 0-7),
                     exercise_state.py (state machine), evidence.py (profile rules)
qmtutor/mathcheck/   safe_parser.py (no eval), verifier.py (SymPy + tolerance)
qmtutor/storage/     db.py (SQLite + migrations), migrations/001_initial.sql,
                     repositories.py (all SQL), events.py (event envelope)
qmtutor/content/     importer.py (lecturer assets -> validated draft versions)
qmtutor/llm/         providers.py (Ollama / Anthropic / Fake), schemas.py,
                     prompts.py (no answer in context), leak_guard.py
qmtutor/retrieval/   search.py (FTS5 baseline + embedding option)
qmtutor/services/    exercise, study, profile, lecturer, research, auth (permissions)
streamlit_app.py + app_pages/   the interface; pages only call services
content/             curriculum map, misconceptions, rubric, items/*.yaml, notes/*.md
policies/            scaffold_policy_v1.yaml   prompts/  tutor_prompts_v2.yaml
config_v2.yaml       model, database path, retrieval backend, feature flags
```

Key rules and where they are enforced:

| Rule | Where |
|---|---|
| The LLM never sees the answer or worked solution | `llm/prompts.py`, test `test_prompt_never_contains_answer_or_hidden_steps` |
| Every scaffolded reply is checked for leaks before display | `llm/leak_guard.py`, `ExerciseService._guarded_generation` |
| Hint level chosen by code, not the LLM | `domain/scaffold_policy.py` |
| Maths checked deterministically, never with eval | `mathcheck/` |
| Study mode locked during an active exercise | `StudyService.ask`, plus a database unique index |
| Policy changes need lecturer approval | `LecturerService.decide_policy` |
| Research export has research ids only, no raw text | `ResearchService.export` |

## Not built / not validated (honest list)

- Docker Compose / campus LAN deployment: **planned**, not written (Docker not installed).
- Refreshing the browser signs you out (sign-in lives in Streamlit session state; progress is safe
  in the database). Real sign-in would fix this.
- The 3B model's replies are sometimes generic or slightly off (e.g. "That looks reasonable" when
  no work was shown).
- Real sign-in (passwords/OIDC): **planned**; demo accounts only.
- Multi-part answers (e.g. `P = 30, Q = 80`) and unit conversion: **planned**.
- Anthropic adapter: **implemented, not live-tested** (no API key).
- Phone / Android usability, concurrent users, offline PWA: **not tested**.
- Misconception candidate discovery from logs: table exists, workflow **planned**.
- Assignments created by lecturers: **planned** (students choose from approved items).
