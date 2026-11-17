"""
Milestone 7 tests: Streamlit pages driven headlessly with AppTest.
They use a temporary database and the fake LLM provider (environment
variables read by qmtutor/ui_support.py), so no browser or model is needed.
AppTest does not test real browsers, phones or layout; that needs manual checks.
"""

import sys

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from qmtutor.services.auth import record_consent
from qmtutor.ui_support import get_context

TIMEOUT = 30


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("QMTUTOR_DB", str(tmp_path / "ui.db"))
    monkeypatch.setenv("QMTUTOR_PROVIDER", "fake")
    # Custom components register when their module is imported, and each AppTest run is a
    # fresh Streamlit runtime, so force a re-import of the keypad module for every test.
    sys.modules.pop("qmtutor.ui_keypad", None)
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def app_as(user_id=None, page=None):
    at = AppTest.from_file("../../streamlit_app.py", default_timeout=TIMEOUT)
    if user_id:
        at.session_state["user_id"] = user_id
    at.run()
    if page:
        at.switch_page(page).run()
    assert not at.exception, at.exception
    return at


def consent(user_id):
    ctx = get_context()
    record_consent(ctx, ctx.users.get(user_id), True)


def answer_box(at):
    return next(t for t in at.text_input if t.label == "Final answer")


def button(at, label):
    return next(b for b in at.button if b.label == label)


def hand_in(at, answer, workings=""):
    """Write workings and answer, review, then confirm, like handing in a paper script."""
    if workings:
        next(t for t in at.text_area if t.label.startswith("Workings")).set_value(workings)
    answer_box(at).set_value(answer)
    button(at, "Review my work").click().run()
    button(at, "Confirm and submit").click().run()


def all_text(at):
    parts = [m.value for m in at.markdown] + [e.value for e in at.info] + [w.value for w in at.warning]
    parts += [s.value for s in at.success] + [c.value for c in at.caption]
    return " ".join(str(p) for p in parts)


def test_sign_in_page_and_role_routing(app_env):
    at = app_as()
    assert at.selectbox[0].options                  # demo accounts listed
    at.selectbox[0].select("L001")
    at.button[0].click().run()
    assert at.session_state["user_id"] == "L001" and not at.exception


def test_student_must_acknowledge_notice(app_env):
    at = app_as("S001", "app_pages/sign_in.py")
    assert "Study notice" in " ".join(h.value for h in at.subheader)
    at.button[0].click().run()                       # "I have read this notice"
    assert get_context().users.has_consent("S001")


def test_exercise_start_hint_and_answer(app_env):
    app_as("S001")
    consent("S001")
    at = app_as("S001", "app_pages/exercise.py")
    start_buttons = [b for b in at.button if b.label == "Start"]
    start_buttons[0].click().run()
    assert "fixed fee of 40 dalasis" in all_text(at)
    next(b for b in at.button if b.label == "Give me a hint").click().run()
    assert any("What quantity is unknown" in m.value for m in at.markdown)
    hand_in(at, "7", "40 + 15u = 145")
    assert "Correct" in all_text(at) and not at.exception


def test_study_page_locked_during_exercise(app_env):
    app_as("S001")
    consent("S001")
    at = app_as("S001", "app_pages/exercise.py")
    next(b for b in at.button if b.label == "Start").click().run()
    at.switch_page("app_pages/study.py").run()
    assert any("closed while an exercise is in progress" in w.value for w in at.warning)


def test_save_then_resume(app_env):
    app_as("S001")
    consent("S001")
    at = app_as("S001", "app_pages/exercise.py")
    next(b for b in at.button if b.label == "Start").click().run()
    next(b for b in at.button if b.label == "Save and leave").click().run()
    assert "Saved" in all_text(at)
    next(b for b in at.button if b.label == "Resume").click().run()
    assert any(b.label == "Review my work" for b in at.button)


def test_existing_support_arm_has_no_tutor_controls(app_env):
    app_as("S003")
    consent("S003")
    at = app_as("S003", "app_pages/exercise.py")
    next(b for b in at.button if b.label == "Start").click().run()
    labels = {b.label for b in at.button}
    assert "Give me a hint" not in labels and not at.chat_input


def test_progress_page_and_challenge(app_env):
    app_as("S001")
    consent("S001")
    at = app_as("S001", "app_pages/exercise.py")
    next(b for b in at.button if b.label == "Start").click().run()
    hand_in(at, "7", "40 + 15u = 145")
    at.switch_page("app_pages/progress.py").run()
    assert at.dataframe and not at.exception
    at.text_area[0].set_value("I was helped by a classmate")
    next(b for b in at.button if b.label == "Send to my lecturer").click().run()
    assert "Sent" in all_text(at)


def test_lecturer_pages_render(app_env):
    for page in ("app_pages/lecturer_dashboard.py", "app_pages/lecturer_content.py", "app_pages/lecturer_policy.py"):
        app_as("L001", page)


def test_research_and_admin_pages_render(app_env):
    app_as("R001", "app_pages/research.py")
    app_as("A001", "app_pages/admin.py")


def test_student_cannot_open_lecturer_page(app_env):
    at = app_as("S001")
    with pytest.raises(ValueError):           # page not registered for the student role
        at.switch_page("app_pages/lecturer_content.py")


def test_keypad_toggle_replaces_old_calculator(app_env):
    app_as("S001")
    consent("S001")
    at = app_as("S001", "app_pages/exercise.py")
    next(b for b in at.button if b.label == "Start").click().run()
    assert not any(e.label == "Calculator" for e in at.expander)       # old calculator removed
    toggle = next(t for t in at.toggle if t.label == "Maths keypad and calculator")
    # In the two-column layout the keypad has its own column, so it starts on; it can be switched off.
    assert toggle.value is True
    toggle.set_value(False).run()
    assert not at.exception
    assert next(t for t in at.toggle if t.label == "Maths keypad and calculator").value is False


def test_review_shows_formatted_workings_then_edit_keeps_text(app_env):
    app_as("S001")
    consent("S001")
    at = app_as("S001", "app_pages/exercise.py")
    button(at, "Start").click().run()
    next(t for t in at.text_area if t.label.startswith("Workings")).set_value("15u = 145 - 40 = 105")
    answer_box(at).set_value("7")
    button(at, "Review my work").click().run()
    assert any("$15u = 145 - 40 = 105$" in m.value for m in at.markdown)      # typeset, student's order
    assert not any(t.label.startswith("Workings") for t in at.text_area)        # inputs hidden while reviewing
    button(at, "Edit").click().run()
    assert next(t for t in at.text_area if t.label.startswith("Workings")).value == "15u = 145 - 40 = 105"
    assert answer_box(at).value == "7"


def test_review_needs_a_final_answer(app_env):
    app_as("S001")
    consent("S001")
    at = app_as("S001", "app_pages/exercise.py")
    button(at, "Start").click().run()
    button(at, "Review my work").click().run()
    assert any("final answer" in w.value for w in at.warning)


def test_marking_panel_lists_only_checked_lines(app_env):
    """Regression: four 'not checked' lines with minus-like icons told the student nothing."""
    app_as("S001")
    consent("S001")
    at = app_as("S001", "app_pages/exercise.py")
    button(at, "Start").click().run()        # LIN-001: every workings line contains the letter u
    hand_in(at, "8", "15u = 120\nu = 8")
    texts = " ".join(str(c.value) for c in at.caption) + " ".join(str(m.value) for m in at.markdown)
    assert "Not checked by the computer" not in texts
    assert "contain letters such as x" in texts
