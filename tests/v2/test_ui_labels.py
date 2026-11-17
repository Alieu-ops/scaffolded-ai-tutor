"""
No developer labels on screen.

Opens every page for every role with realistic synthetic activity, collects all
visible text (headings, text, captions, alerts, buttons, widget labels and options,
table headers AND table cells) and fails if it finds machine names such as
"in_progress_or_saved", raw timestamps like "2026-10-03T14:55:29", item keys like
"LIN-001@1.0", or raw JSON. LaTeX inside $...$ is ignored (it legitimately uses _).
"""

import re
import sys

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from qmtutor.services.auth import record_consent
from qmtutor.services.exercise_service import ExerciseService
from qmtutor.services.profile_service import ProfileService
from qmtutor.services.research_service import ResearchService
from qmtutor.ui_support import get_context

PATTERNS = {
    "snake_case name": re.compile(r"\b[a-z]+_[a-z0-9_]+\b"),
    "raw timestamp": re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"),
    "item key": re.compile(r"[A-Z]{3}-\d{3}@\d"),
    "raw JSON": re.compile(r"\{\s*\""),
}

PAGES = {
    "S001": ["app_pages/student_home.py", "app_pages/study.py", "app_pages/exercise.py",
             "app_pages/independent_check.py", "app_pages/progress.py", "app_pages/sign_in.py"],
    "L001": ["app_pages/lecturer_dashboard.py", "app_pages/lecturer_content.py", "app_pages/lecturer_policy.py"],
    "R001": ["app_pages/research.py", "app_pages/lecturer_policy.py"],
    "A001": ["app_pages/admin.py"],
}


@pytest.fixture
def populated(tmp_path, monkeypatch):
    monkeypatch.setenv("QMTUTOR_DB", str(tmp_path / "labels.db"))
    monkeypatch.setenv("QMTUTOR_PROVIDER", "fake")
    sys.modules.pop("qmtutor.ui_keypad", None)
    st.cache_resource.clear()
    ctx = get_context()
    s1, s4 = ctx.users.get("S001"), ctx.users.get("S004")
    for user in (s1, s4):
        record_consent(ctx, user, True)
    service = ExerciseService(ctx)
    done = service.start(s1, "LIN-001")
    service.request_hint(s1, done.session_id)
    service.submit_attempt(s1, done.session_id, "7", "15u = 145 - 40 = 115\nu = 7")       # correct answer, wrong workings
    evidence = ctx.evidence.for_student("S001")[0]
    ProfileService(ctx).submit_challenge(s1, evidence.evidence_id, "I think this is wrong")
    help_me = service.start(s4, "INT-001")
    service.refer(s4, help_me.session_id, "stuck on year two")
    open_one = service.start(s1, "INT-002")                                              # leave one open
    service.submit_attempt(s1, open_one.session_id, "6492.8")       # typical wrong answer -> possible mix-up
    ResearchService(ctx).export(ctx.users.get("R001"), tmp_path, "label check")
    yield
    st.cache_resource.clear()


def visible_text(at: AppTest) -> list[str]:
    texts = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "success", "error"):
        texts += [str(e.value) for e in getattr(at, kind)]
    for widget_kind in ("button", "toggle", "checkbox", "text_input", "text_area", "number_input"):
        texts += [str(w.label) for w in getattr(at, widget_kind)]
    for widget_kind in ("selectbox", "segmented_control", "pills"):
        for w in at.get(widget_kind):
            texts.append(str(getattr(w, "label", "")))
            texts += [str(o) for o in (getattr(w, "options", None) or [])]
    for frame in at.dataframe:
        df: pd.DataFrame = frame.value
        texts += [str(c) for c in df.columns]
        texts += [str(v) for v in df.astype(str).values.ravel()]
    for element in at.get("json"):
        texts.append(str(element.value))
    return texts


def problems_in(texts: list[str]) -> list[str]:
    found = []
    for text in texts:
        cleaned = re.sub(r"\$[^$]*\$", "", text)          # ignore LaTeX
        cleaned = re.sub(r":material/[a-z_]+:", "", cleaned)   # icon codes render as icons, not text
        for name, pattern in PATTERNS.items():
            for match in pattern.findall(cleaned):
                found.append(f"{name}: {match!r} in {text[:80]!r}")
    return found


@pytest.mark.parametrize("user_id", list(PAGES))
def test_no_developer_labels_on_any_page(populated, user_id):
    problems = []
    for page in PAGES[user_id]:
        at = AppTest.from_file("../../streamlit_app.py", default_timeout=30)
        at.session_state["user_id"] = user_id
        at.run()
        at.switch_page(page).run()
        assert not at.exception, (page, at.exception)
        problems += [f"[{page}] {p}" for p in problems_in(visible_text(at))]
    assert not problems, "\n".join(problems)


def _app(user_id, page):
    at = AppTest.from_file("../../streamlit_app.py", default_timeout=30)
    at.session_state["user_id"] = user_id
    at.run()
    at.switch_page(page).run()
    return at


def test_no_developer_labels_in_lecturer_student_review(populated):
    at = _app("L001", "app_pages/lecturer_dashboard.py")
    at.selectbox[0].select("S001").run()
    assert len(at.dataframe) >= 2                      # the per-student table is now shown
    assert not problems_in(visible_text(at)), "\n".join(problems_in(visible_text(at)))


def test_no_developer_labels_in_review_and_marking(populated):
    at = _app("S001", "app_pages/exercise.py")        # INT-002 is open
    next(t for t in at.text_area if t.label.startswith("Workings")).set_value("25000 x 0.08 = 2000\n2000 x 3 = 6100")
    next(t for t in at.text_input if t.label == "Final answer").set_value("6100")
    next(b for b in at.button if b.label == "Review my work").click().run()
    review_problems = problems_in(visible_text(at))
    next(b for b in at.button if b.label == "Confirm and submit").click().run()
    texts = visible_text(at)
    assert any("Computer check of your workings" in t for t in texts)
    assert any("2000 x 3 = 6100" in t or "2000 \times 3 = 6100" in t for t in texts)
    assert not review_problems + problems_in(texts), "\n".join(review_problems + problems_in(texts))


@pytest.mark.regression
def test_error_messages_people_can_trigger_are_plain():
    """Messages raised to students or lecturers must not contain machine names either."""
    from qmtutor.seed import seed
    from qmtutor.services.context import build_context, load_settings
    from qmtutor.services.exercise_service import ExerciseError
    from qmtutor.services.lecturer_service import LecturerService, ReviewError
    from qmtutor.llm.providers import FakeProvider
    ctx = build_context(load_settings(), db_path=":memory:", provider=FakeProvider())
    seed(ctx)
    student = ctx.users.get("S001")
    record_consent(ctx, student, True)
    service = ExerciseService(ctx)
    session = service.start(student, "LIN-001")
    service.submit_attempt(student, session.session_id, "7")
    messages = []
    for action in (lambda: service.resume(student, session.session_id),
                   lambda: service.request_hint(student, session.session_id),
                   lambda: service.start(student, "LIN-ANA-001")):
        with pytest.raises(ExerciseError) as error:
            action()
        messages.append(str(error.value))
    lecturer = ctx.users.get("L001")
    LecturerService(ctx).decide_item(lecturer, "LIN-001", "1.1", "retired", "testing")
    with pytest.raises(ReviewError) as error:
        LecturerService(ctx).decide_item(lecturer, "LIN-001", "1.1", "approved", "again")
    messages.append(str(error.value))
    assert not problems_in(messages), messages


def test_focus_box_and_class_misconceptions_are_shown_plainly(populated):
    at = _app("S001", "app_pages/student_home.py")
    texts = visible_text(at)
    assert any("Your focus" in t for t in texts)
    assert any("Possible mix-up seen in your answers" in t for t in texts)
    assert not problems_in(texts), problems_in(texts)
    at = _app("L001", "app_pages/lecturer_dashboard.py")
    assert any("Simple and compound interest confused" in t for t in visible_text(at))
