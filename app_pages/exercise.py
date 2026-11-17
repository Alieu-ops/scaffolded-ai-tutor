"""
Exercise page. Shows the active protected exercise, or lets the student start
or resume one. All decisions (is a hint allowed? is the answer right? may the
student resume? which exercise is recommended?) are made by ExerciseService;
this page only displays results.

Layout (owner feedback, 3 Oct 2026): the "paper" (question, workings, final answer)
on the left and the tools (calculator, tutor) on the right, so the tools stay beside
the work instead of scrolling away. On a phone the columns stack: paper first.
"""

import streamlit as st

from qmtutor import labels as L
from qmtutor.domain.models import ExerciseState, StudyArm
from qmtutor.mathcheck.reasoning_format import format_reasoning
from qmtutor.mathcheck.safe_parser import latex_preview
from qmtutor.mathcheck.verifier import allowed_variables_for
from qmtutor.services.exercise_service import ExerciseError, ExerciseService
from qmtutor.ui_keypad import maths_keypad
from qmtutor.ui_support import flash, get_context, require_user, show_flash

ctx = get_context()
student = require_user()
service = ExerciseService(ctx)

st.title("Exercise", anchor=False)
show_flash()


def run(action, success_message=None):
    """Call a service action and turn rule violations into friendly messages."""
    try:
        result = action()
    except ExerciseError as error:
        flash("warning", str(error))
        return None
    if success_message:
        flash("success", success_message)
    return result


def show_marking() -> None:
    """The computer's check of the last workings handed in (see config: show_step_check_to_students)."""
    marking = st.session_state.get("last_marking")
    if not marking:
        return
    checked = [line for line in marking["lines"] if line.good is not None]
    waiting = len(marking["lines"]) - len(checked)
    with st.container(border=True):
        st.markdown("**Computer check of your workings**")
        # Only lines that were actually checked are listed (a list of "not checked" lines, each
        # with a grey dash that looked like a minus sign, told the student nothing).
        for line in checked:
            icon = ":green[:material/check_circle:]" if line.good else ":red[:material/cancel:]"
            st.markdown(f"{icon} Line {line.line_number}: {format_reasoning(line.text)}")
            st.caption(line.message)
        if waiting and not marking["finished"]:
            st.caption(f"{'All ' if not checked else ''}{waiting} line(s) contain letters such as x, so the computer "
                       "checks them after you finish the exercise. Until then it only checks calculations "
                       "with numbers, like 145 - 40 = 105.")
        elif waiting:
            st.caption(f"{waiting} line(s) could not be checked by the computer.")
        if not checked and not waiting:
            st.caption("No calculations were found to check.")
        st.caption("The computer checks calculations only. Your method and explanation are reviewed separately.")


def start_button(item, key_prefix: str, primary: bool = True) -> None:
    if st.button("Start", key=f"{key_prefix}_{item.item_id}", type="primary" if primary else "secondary"):
        st.session_state.pop("last_marking", None)
        run(lambda: service.start(student, item.item_id))
        st.rerun()


session = service.active_session(student)

# -
# No active exercise: recommendations, saved exercises, all exercises
# -
if session is None:
    show_marking()
    try:
        items = service.available_items(student)
    except ExerciseError as error:
        st.warning(str(error))
        st.stop()
    if not items:
        st.info("No approved exercises yet. A lecturer must approve content first.")
        st.stop()
    outcomes = {o.outcome_id: o.description for o in ctx.content.outcomes()}
    done = {s.item_id for s in ctx.exercises.for_student(student.user_id, {ExerciseState.COMPLETED})}

    # Adaptive practice (scaffolded group): weakest topics and possible mix-ups first, with a reason.
    _, recommendations = service.focus(student)
    if recommendations:
        st.subheader("Recommended for you", anchor=False)
        st.caption("Chosen from your answers so far: more practice where you need it most.")
        for rec in recommendations:
            with st.container(border=True):
                st.caption(f"{outcomes.get(rec.item.outcome_id, rec.item.outcome_id)} · {rec.item.difficulty}")
                st.markdown(rec.item.stem)
                st.markdown(f":material/tips_and_updates: *{rec.reason}*")
                start_button(rec.item, "rec")

    for saved in service.saved_sessions(student):
        saved_item = service.item_for(saved)
        with st.container(border=True):
            st.markdown(f"**Saved:** {saved_item.stem}")
            row = st.container(horizontal=True)
            if row.button("Resume", key=f"resume_{saved.session_id}", icon=":material/play_arrow:"):
                run(lambda: service.resume(student, saved.session_id))
                st.rerun()
            if row.button("End without answer", key=f"end_{saved.session_id}", icon=":material/stop:"):
                run(lambda: service.terminate(student, saved.session_id, None), "Exercise ended.")
                st.rerun()

    st.subheader("All exercises" if recommendations else "Choose an exercise", anchor=False)
    for item in items:
        with st.container(border=True):
            st.caption(f"{outcomes.get(item.outcome_id, item.outcome_id)} · {item.difficulty}"
                       + (" · completed" if item.item_id in done else ""))
            st.markdown(item.stem)
            start_button(item, "start", primary=not recommendations)
    st.stop()

# -
# Active exercise: the "paper" on the left, tools (calculator, tutor) on the right
# -
item = service.item_for(session)
is_transfer = service.task_type(session) == "transfer"
arm = session.arm
spec = item.answer_specification
sid = session.session_id
answer_key, workings_key = f"answer_{sid}", f"workings_{sid}"
review_key, draft_key = f"review_{sid}", f"draft_{sid}"
variables = sorted(allowed_variables_for(spec))
can_chat = not is_transfer and arm != StudyArm.EXISTING_SUPPORT
show_steps = ctx.settings["features"].get("show_step_check_to_students", False)


def queue_tutor_message(text: str) -> None:
    """The keypad's "Send to tutor" runs before this script; the message is sent further down."""
    st.session_state["pending_tutor_message"] = text


def answer_preview(text: str) -> None:
    preview = latex_preview(text, set(variables))
    if preview:
        st.latex(preview)
    elif text.strip():
        st.caption("The preview will appear when the answer can be read.")


paper, tools = st.columns([3, 2], gap="large")

with paper:
    with st.container(border=True):
        st.caption("Independent check: no hints or tutor" if is_transfer else f"Practice · {item.subskill}")
        st.markdown(f"#### {item.stem}")
        if spec.units:
            st.caption(f"Give your answer in {spec.units}. Rounding: {spec.rounding_rule}.")
    show_marking()

    # Like a paper script: workings first, then the final answer, then review before handing in.
    if not st.session_state.get(review_key):
        # Widgets that were hidden during the review lose their values, so restore the draft.
        draft = st.session_state.get(draft_key, {})
        st.session_state.setdefault(workings_key, draft.get("workings", ""))
        st.session_state.setdefault(answer_key, draft.get("answer", ""))
        workings = st.text_area("Workings (show your steps)", key=workings_key, height=200,
                                placeholder="One step per line, words and maths, e.g.\n"
                                            "Fixed fee is 40, so 15u = 145 - 40 = 105\nu = 105 / 15 = 7",
                                help="Marked separately from the final answer, like workings on paper.")
        answer = st.text_input("Final answer", key=answer_key, help="Examples: 7, u = 7, 2000×1.05², 13,382.26.")
        answer_preview(answer)
        if st.button("Review my work", type="primary", icon=":material/visibility:"):
            if not answer.strip():
                st.warning("Please write a final answer before reviewing.")
            else:
                st.session_state[draft_key] = {"workings": workings, "answer": answer}
                st.session_state[review_key] = True
                st.rerun()
    else:
        draft = st.session_state[draft_key]
        with st.container(border=True):
            st.caption("Check your work. This is how it will be handed in.")
            st.markdown("**Workings**")
            st.markdown(format_reasoning(draft["workings"]) if draft["workings"].strip() else "*No workings written.*")
            st.markdown("**Final answer**")
            answer_preview(draft["answer"])
            row = st.container(horizontal=True)
            if row.button("Edit", icon=":material/edit:"):
                st.session_state[review_key] = False
                st.rerun()
            if row.button("Confirm and submit", type="primary", icon=":material/check:"):
                with st.spinner("Marking your work..."):
                    outcome = run(lambda: service.submit_attempt(student, sid, draft["answer"], draft["workings"]))
                st.session_state[review_key] = False
                if outcome:
                    flash("success" if outcome.completed else "warning",
                          "Correct. Well done!" if outcome.completed else outcome.feedback)
                    if show_steps and outcome.student_lines:
                        st.session_state["last_marking"] = {"stem": item.stem, "finished": outcome.completed,
                                                            "lines": outcome.student_lines}
                    else:
                        st.session_state.pop("last_marking", None)
                st.rerun()

    st.divider()
    row = st.container(horizontal=True)
    if row.button("Save and leave", icon=":material/save:"):
        run(lambda: service.save(student, sid), "Saved. You can resume it later.")
        st.rerun()
    with row.popover("End exercise", icon=":material/stop_circle:"):
        st.caption("Ending does not show the answer. You can tell us why (optional).")
        reason = st.text_input("Reason (optional)", key="end_reason")
        if st.button("End now"):
            run(lambda: service.terminate(student, sid, reason or None), "Exercise ended.")
            st.rerun()
    if not is_transfer:
        with row.popover("Ask a person for help", icon=":material/support_agent:"):
            st.caption("This ends the exercise and tells your lecturer you would like help.")
            help_reason = st.text_input("What are you stuck on? (optional)", key="help_reason")
            if st.button("Request help"):
                run(lambda: service.refer(student, sid, help_reason or None),
                    "Your lecturer has been told you would like help.")
                st.rerun()

with tools:
    st.session_state.setdefault("keypad_on", True)
    keypad_on = st.toggle("Maths keypad and calculator", key="keypad_on",
                          help="Powers (xⁿ), subscripts (log₂), √, log₁₀, ln, π. Calculate, then add the line to "
                               "your workings, put the result in your answer"
                               + (", or send it to the tutor." if can_chat else "."))
    if keypad_on and not st.session_state.get(review_key):
        maths_keypad(key=f"keypad_{sid}", variables=variables, can_chat=can_chat, answer_key=answer_key,
                     workings_key=workings_key, on_send_to_tutor=queue_tutor_message)

    # Tutor: hints (scaffolded) and chat (AI groups). None in the independent check.
    if can_chat:
        st.subheader("Tutor" if arm == StudyArm.SCAFFOLDED else "AI assistant", anchor=False)
        if arm == StudyArm.SCAFFOLDED:
            level = int(session.current_level)
            st.caption(("No hints used yet. " if level == 0 else
                        f"Hints used so far: level {level} of 6 ({L.HINT_LEVELS[level].lower()}). ")
                       + "Each hint is a little stronger than the last; the tutor will not give the answer.")
            if st.button("Give me a hint", icon=":material/lightbulb:"):
                with st.spinner("Choosing a hint..."):
                    run(lambda: service.request_hint(student, sid))
                st.rerun()
        history = service.history(student, sid)
        # The conversation scrolls inside its own box, so the page does not grow without end.
        with st.container(height=420 if history else "content", border=bool(history)):
            for message in history:
                is_student = message["sender"] == "student"
                with st.chat_message("user" if is_student else "assistant"):
                    st.markdown(format_reasoning(message["content"], keep_markdown=not is_student))
        prompt = st.chat_input("Ask the tutor about this exercise") or st.session_state.pop("pending_tutor_message", None)
        if prompt:
            with st.spinner("The tutor is thinking..."):
                run(lambda: service.chat(student, sid, prompt))
            st.rerun()
