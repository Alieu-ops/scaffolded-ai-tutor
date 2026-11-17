"""
On-screen maths keyboard for the Streamlit app.

Streamlit text boxes cannot show superscripts, so students used to type
"2^10" with the Shift key. This keyboard inserts real maths symbols
(2¹⁰, log₁₀, √, π, °) into the answer box or the chat box.

How it works: the keyboard is a small web page (HTML + JavaScript) that
Streamlit shows in a frame. When a key is pressed, the JavaScript finds
the chosen text box on the main page and inserts the symbol at the cursor.

Keys:
  xⁿ  superscript mode: digits typed next are raised (2¹⁰); press again to stop
  x₂  subscript mode:  digits typed next are lowered (log₂); press again to stop
"""

import json

import streamlit.components.v1 as components

# CSS selectors for the text boxes the keyboard can type into.
ANSWER_BOX = 'input[aria-label="{label}"]'
CHAT_BOX = 'textarea[placeholder="{placeholder}"]'

# (label shown on key, text inserted). "MODE:..." and "DO:..." are commands.
KEYS = [
    [("7", "7"), ("8", "8"), ("9", "9"), ("÷", "÷"), ("(", "("), (")", ")")],
    [("4", "4"), ("5", "5"), ("6", "6"), ("×", "×"), ("xⁿ", "MODE:sup"), ("x²", "²")],
    [("1", "1"), ("2", "2"), ("3", "3"), ("−", "-"), ("x₂", "MODE:sub"), ("√", "√(")],
    [("0", "0"), (".", "."), ("/", "/"), ("+", "+"), ("log₁₀", "log₁₀("), ("log", "log")],
    [("sin", "sin("), ("cos", "cos("), ("tan", "tan("), ("°", "°"), ("π", "π"), ("=", "=")],
    [("x", "x"), ("y", "y"), (",", ", "), ("␣", " "), ("⌫", "DO:back"), ("Clear", "DO:clear")],
]

HTML = """
<style>
  * { box-sizing: border-box; font-family: "Source Sans Pro", sans-serif; }
  body { margin: 0; }
  .targets { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; font-size: 14px; color: #555; }
  .targets button { flex: 1; }
  .grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 4px; }
  button { height: 40px; min-width: 0; padding: 0; font-size: 16px; color: #31333f;
           border: 1px solid #ccc; border-radius: 8px; background: #fff;
           cursor: pointer; touch-action: manipulation; white-space: nowrap; overflow: hidden; }
  button:active { background: #eee; }
  button.cmd { background: #f3f3f6; font-size: 14px; }
  button.on { background: #ff4b4b; color: #fff; border-color: #ff4b4b; }  /* after .cmd so it wins */
  .hint { font-size: 12px; color: #888; margin-top: 4px; min-height: 16px; }
</style>
<div class="targets" id="targets">Type into:</div>
<div class="grid" id="grid"></div>
<div class="hint" id="hint"></div>
<script>
const KEYS = __KEYS__;
const TARGETS = __TARGETS__;          // e.g. {"answer": [label, selector], "chat": [...]}
const P = window.parent, D = P.document;
const SUP = {"0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶","7":"⁷","8":"⁸","9":"⁹",
             "+":"⁺","-":"⁻","=":"⁼","(":"⁽",")":"⁾","n":"ⁿ","x":"ˣ"};
const SUB = {"0":"₀","1":"₁","2":"₂","3":"₃","4":"₄","5":"₅","6":"₆","7":"₇","8":"₈","9":"₉",
             "+":"₊","-":"₋","=":"₌","(":"₍",")":"₎","x":"ₓ"};

// Remember the chosen box and mode on the main page, because Streamlit
// rebuilds this keyboard after every click on the page.
let target = TARGETS[P.__mkTarget] ? P.__mkTarget : Object.keys(TARGETS)[0];
let mode = P.__mkMode || null;

function box() { return D.querySelector(TARGETS[target][1]); }

// Change a text box's value in a way the web page notices (React needs
// the native setter plus an "input" event).
function setValue(el, value, caret) {
  const proto = el.tagName === "TEXTAREA" ? P.HTMLTextAreaElement.prototype : P.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
  el.dispatchEvent(new P.Event("input", { bubbles: true }));
  try { el.setSelectionRange(caret, caret); } catch (e) {}
}

function insert(text) {
  const el = box();
  if (!el) { hint("Box not found. Click in the box first."); return; }
  if (mode) text = [...text].map(c => (mode === "sup" ? SUP : SUB)[c] ?? c).join("");
  const s = el.selectionStart ?? el.value.length, e = el.selectionEnd ?? el.value.length;
  setValue(el, el.value.slice(0, s) + text + el.value.slice(e), s + text.length);
}

function command(cmd) {
  const el = box(); if (!el) return;
  if (cmd === "clear") return setValue(el, "", 0);
  const s = el.selectionStart ?? el.value.length, e = el.selectionEnd ?? el.value.length;
  if (s !== e) return setValue(el, el.value.slice(0, s) + el.value.slice(e), s);
  if (s > 0) {
    const chars = [...el.value.slice(0, s)];   // [...] keeps symbols like ² whole
    chars.pop();
    const before = chars.join("");
    setValue(el, before + el.value.slice(s), before.length);
  }
}

function hint(text) { document.getElementById("hint").textContent = text; }

function outline() {
  // Show which box the keyboard types into.
  for (const [name, [, sel]] of Object.entries(TARGETS)) {
    const el = D.querySelector(sel);
    if (el) el.style.outline = name === target ? "2px solid #ff4b4b" : "";
  }
}

function render() {
  const t = document.getElementById("targets");
  t.innerHTML = "Type into:";
  for (const [name, [label]] of Object.entries(TARGETS)) {
    const b = document.createElement("button");
    b.textContent = label; b.className = "cmd" + (name === target ? " on" : "");
    b.onclick = () => { target = P.__mkTarget = name; render(); };
    t.appendChild(b);
  }
  const g = document.getElementById("grid");
  g.innerHTML = "";
  for (const row of KEYS) for (const [label, value] of row) {
    const b = document.createElement("button");
    b.textContent = label;
    if (value.startsWith("MODE:") || value.startsWith("DO:")) b.className = "cmd";
    if (value === "MODE:" + mode) b.className = "cmd on";
    b.onclick = () => {
      if (value.startsWith("MODE:")) {
        const m = value.slice(5);
        mode = P.__mkMode = (mode === m ? null : m);
        render();
      } else if (value.startsWith("DO:")) {
        command(value.slice(3));
      } else {
        insert(value);
      }
    };
    g.appendChild(b);
  }
  hint(mode === "sup" ? "Superscript ON: next digits are raised, e.g. 2¹⁰. Press xⁿ to stop."
     : mode === "sub" ? "Subscript ON: next digits are lowered, e.g. log₂. Press x₂ to stop." : "");
  outline();
}
render();
</script>
"""


def maths_keyboard(answer_label, chat_placeholder=None):
    """
    Show the keyboard. It types into the answer box (found by its label),
    and also into the chat box if `chat_placeholder` is given.
    """
    targets = {"answer": ["Answer box", ANSWER_BOX.format(label=answer_label)]}
    if chat_placeholder:
        targets["chat"] = ["Chat", CHAT_BOX.format(placeholder=chat_placeholder)]
    html = HTML.replace("__KEYS__", json.dumps(KEYS)).replace("__TARGETS__", json.dumps(targets))
    components.html(html, height=335)
