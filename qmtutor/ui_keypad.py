"""
On-screen maths keypad and scientific calculator (Streamlit Custom Component v2).

Brought over from v1's keyboard.py, rebuilt with Streamlit's current component
API. v1 reached into the page with JavaScript to edit the text boxes, which is
fragile. Here the keypad keeps its own display and sends ACTIONS back to
Python, where the safe parser does the arithmetic:

    Calculate        -> result shown under the display
    Add to workings  -> "2000×1.05² = 2205" is added as a new line of the workings
    Put in answer    -> the result (or the expression) goes into the answer box
    Send to tutor    -> "I calculated ... = ..." is posted in the tutor chat

Keys: digits, + − × ÷, brackets, xⁿ (superscript mode: 2¹⁰), x² , x₂
(subscript mode: log₂), √, log₁₀, ln, π, e, %, = and the item's variable.
The student can also type with the computer keyboard; in superscript or
subscript mode, typed digits are raised or lowered too.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from qmtutor.mathcheck.keypad import KeypadResult, calculate, text_for_answer, text_for_tutor, text_for_workings

HTML = """
<div class="keypad">
  <input class="display" type="text" aria-label="Calculator display" autocomplete="off"
         placeholder="Type or tap, e.g. 2000×1.05²" />
  <div class="result" aria-live="polite"></div>
  <div class="grid"></div>
  <div class="actions"></div>
  <div class="hint"></div>
</div>
"""

CSS = """
.keypad { font-family: var(--st-font, sans-serif); color: var(--st-text-color); }
.display { width: 100%; box-sizing: border-box; font-size: 1.25rem; padding: 0.5rem 0.6rem;
           border: 1px solid var(--st-border-color, #ccc); border-radius: var(--st-base-radius, 8px);
           background: var(--st-secondary-background-color); color: var(--st-text-color); }
.result { min-height: 1.5rem; margin: 0.3rem 0 0.5rem; font-size: 1.05rem; }
.result.error { color: var(--st-red-color, #d33); font-size: 0.9rem; }
.grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 4px; }
/* Action buttons wrap onto a second row on phones instead of cutting off their text
   (found in a 375px-wide phone check, 3 Oct 2026). */
.actions { display: grid; grid-template-columns: repeat(auto-fit, minmax(105px, 1fr)); gap: 4px; margin-top: 6px; }
button { height: 40px; min-width: 0; padding: 0; font-size: 1rem; cursor: pointer;
         border: 1px solid var(--st-border-color, #ccc); border-radius: var(--st-base-radius, 8px);
         background: var(--st-background-color, #fff); color: var(--st-text-color);
         touch-action: manipulation; white-space: nowrap; overflow: hidden; }
button:active { filter: brightness(0.92); }
button.cmd { background: var(--st-secondary-background-color); font-size: 0.9rem; }
button.on, button.primary { background: var(--st-primary-color); color: #fff; border-color: var(--st-primary-color); }
.hint { font-size: 0.8rem; opacity: 0.7; min-height: 1rem; margin-top: 4px; }
"""

JS = """
const SUP = {"0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶","7":"⁷","8":"⁸","9":"⁹",
             "+":"⁺","-":"⁻","(":"⁽",")":"⁾"};
const SUB = {"0":"₀","1":"₁","2":"₂","3":"₃","4":"₄","5":"₅","6":"₆","7":"₇","8":"₈","9":"₉"};
const memory = new WeakMap();   // per-instance mode and last applied display version

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const display = parentElement.querySelector(".display");
  const result = parentElement.querySelector(".result");
  const grid = parentElement.querySelector(".grid");
  const actions = parentElement.querySelector(".actions");
  const hint = parentElement.querySelector(".hint");
  if (!display) return;

  const state = memory.get(parentElement) || { mode: null, version: null };
  memory.set(parentElement, state);

  // Python -> JS: restore the display only when Python sends a new version
  // (first mount, or after a calculation), so typing is never overwritten.
  if (data.display_version !== state.version) {
    display.value = data.expression || "";
    state.version = data.display_version;
  }
  result.textContent = data.result_text || "";
  result.className = "result" + (data.is_error ? " error" : "");

  function insert(text) {
    if (state.mode) text = [...text].map(c => (state.mode === "sup" ? SUP : SUB)[c] ?? c).join("");
    const s = display.selectionStart ?? display.value.length;
    const e = display.selectionEnd ?? display.value.length;
    display.value = display.value.slice(0, s) + text + display.value.slice(e);
    const caret = s + text.length;
    display.focus();
    display.setSelectionRange(caret, caret);
  }
  function backspace() {
    const s = display.selectionStart ?? display.value.length;
    const e = display.selectionEnd ?? display.value.length;
    if (s !== e) { display.value = display.value.slice(0, s) + display.value.slice(e); display.setSelectionRange(s, s); return; }
    const before = [...display.value.slice(0, s)]; before.pop();     // [...] keeps symbols like ² whole
    const head = before.join("");
    display.value = head + display.value.slice(s);
    display.setSelectionRange(head.length, head.length);
  }
  function send(type) { setTriggerValue("action", { type: type, expression: display.value }); }

  // Physical keyboard: Enter calculates; in a mode, digits are raised/lowered.
  display.onkeydown = (event) => {
    if (event.key === "Enter") { event.preventDefault(); send("calculate"); return; }
    const table = state.mode === "sup" ? SUP : state.mode === "sub" ? SUB : null;
    if (table && table[event.key] && !event.ctrlKey && !event.metaKey) { event.preventDefault(); insert(event.key); }
  };

  const variables = data.variables && data.variables.length ? data.variables : ["x"];
  const keys = [
    ["7","8","9","÷","(",")"],
    ["4","5","6","×","MODE:sup","²"],
    ["1","2","3","−","MODE:sub","√("],
    ["0",".","%","+","log₁₀(","ln("],
    ["π","e", variables[0], variables[1] || ",", "=", "DO:back"],
  ];
  const labels = {"MODE:sup":"xⁿ","MODE:sub":"x₂","²":"x²","√(":"√","log₁₀(":"log₁₀","ln(":"ln","DO:back":"⌫"};

  function render() {
    grid.replaceChildren();
    for (const row of keys) for (const value of row) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = labels[value] || value;
      if (value.startsWith("MODE:") || value.startsWith("DO:")) button.className = "cmd";
      if (value === "MODE:" + state.mode) button.className = "cmd on";
      button.onclick = () => {
        if (value.startsWith("MODE:")) { const m = value.slice(5); state.mode = state.mode === m ? null : m; render(); }
        else if (value === "DO:back") backspace();
        else insert(value);
      };
      grid.appendChild(button);
    }
    actions.replaceChildren();
    const buttons = [["Clear", () => { display.value = ""; result.textContent = ""; display.focus(); }, "cmd"],
                     ["Calculate", () => send("calculate"), "primary"],
                     ["Add to workings", () => send("to_workings"), "cmd"],
                     ["Put in answer", () => send("to_answer"), "cmd"]];
    if (data.can_chat) buttons.push(["Send to tutor", () => send("to_chat"), "cmd"]);
    for (const [label, handler, cls] of buttons) {
      const button = document.createElement("button");
      button.type = "button"; button.textContent = label; button.className = cls; button.onclick = handler;
      actions.appendChild(button);
    }
    hint.textContent = state.mode === "sup" ? "Superscript on: next digits are raised (2¹⁰). Tap xⁿ to stop."
                     : state.mode === "sub" ? "Subscript on: next digits are lowered (log₂). Tap x₂ to stop."
                     : "Tip: press Enter to calculate.";
  }
  render();
}
"""

_KEYPAD = st.components.v2.component("qmtutor_maths_keypad", html=HTML, css=CSS, js=JS)


def maths_keypad(*, key: str, variables: list[str], can_chat: bool, answer_key: str, workings_key: str,
                 on_send_to_tutor: Callable[[str], None] | None = None) -> KeypadResult | None:
    """
    Show the keypad. Actions are handled in a callback, which Streamlit runs
    BEFORE the page script, so "Put in answer" can safely set the answer box's value.
    Returns the latest calculation (for a LaTeX preview), or None.
    """
    memory_key = f"{key}__last"

    def handle_action():
        action = (st.session_state.get(key) or {}).get("action")
        if not action:
            return
        outcome = calculate(action.get("expression", ""), set(variables))
        st.session_state[memory_key] = {"result": outcome,
                                        "version": st.session_state.get(memory_key, {}).get("version", 0) + 1}
        if not outcome.ok:
            return
        if action.get("type") == "to_answer":
            st.session_state[answer_key] = text_for_answer(outcome)
        elif action.get("type") == "to_workings":
            # Append the calculation as a new line, like writing it on the paper.
            existing = st.session_state.get(workings_key, "").rstrip()
            st.session_state[workings_key] = (existing + "\n" if existing else "") + text_for_workings(outcome)
        elif action.get("type") == "to_chat" and on_send_to_tutor:
            on_send_to_tutor(text_for_tutor(outcome))

    last = st.session_state.get(memory_key, {})
    outcome: KeypadResult | None = last.get("result")
    if outcome is None:
        result_text, is_error = "", False
    elif not outcome.ok:
        result_text, is_error = outcome.message, True
    else:
        result_text, is_error = (f"= {outcome.value_text}" if outcome.value_text else outcome.message), False

    _KEYPAD(key=key, on_action_change=handle_action,
            data={"expression": outcome.expression if outcome else "", "display_version": last.get("version", 0),
                  "result_text": result_text, "is_error": is_error, "variables": variables, "can_chat": can_chat})
    return outcome
