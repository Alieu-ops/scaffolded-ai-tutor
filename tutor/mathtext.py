"""
Converting maths between the two forms the app uses:

  pretty  (what students see):  2¹⁰ × 3,  log₁₀(1000),  √25,  x²
  plain   (what the code checks): 2^10 x 3, log_10(1000), sqrt25, x^2

Students type the pretty form with the maths keyboard; the answer checker
turns it into plain text before comparing. Questions and tutor replies,
which are written in plain text, are shown in the pretty form.
"""

import re

SUPERSCRIPTS = str.maketrans("0123456789+-=()nx", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿˣ")
SUBSCRIPTS = str.maketrans("0123456789+-=()x", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₓ")
FROM_SUPERSCRIPTS = {v: k for k, v in zip("0123456789+-=()nx", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿˣ")}
FROM_SUBSCRIPTS = {v: k for k, v in zip("0123456789+-=()x", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₓ")}

SUP_RUN = "[" + "".join(FROM_SUPERSCRIPTS) + "]+"
SUB_RUN = "[" + "".join(FROM_SUBSCRIPTS) + "]+"


def to_plain(text):
    """Pretty maths -> plain text: "2¹⁰" -> "2^10", "log₁₀" -> "log_10"."""
    text = str(text)
    text = re.sub(SUP_RUN, lambda m: "^" + "".join(FROM_SUPERSCRIPTS[c] for c in m.group()), text)
    text = re.sub(SUB_RUN, lambda m: "_" + "".join(FROM_SUBSCRIPTS[c] for c in m.group()), text)
    return (text.replace("√", "sqrt").replace("π", "pi").replace("÷", "/")
                .replace("×", "x").replace("·", "x").replace("−", "-"))


def pretty(text):
    """Plain maths -> pretty display: "2^3 x 2^4" -> "2³ × 2⁴"."""
    text = str(text)
    # Powers: ^ followed by digits (optionally negative), or by a single letter.
    text = re.sub(r"\^(-?\d+)", lambda m: m.group(1).translate(SUPERSCRIPTS), text)
    text = re.sub(r"\^([nx])\b", lambda m: m.group(1).translate(SUPERSCRIPTS), text)
    text = re.sub(r"\blog ?\(base (\d+)\)", lambda m: "log" + m.group(1).translate(SUBSCRIPTS), text)
    text = re.sub(r"\blog_?(\d+)(?=\s*\()", lambda m: "log" + m.group(1).translate(SUBSCRIPTS), text)
    text = re.sub(r"sqrt\(", "√(", text)
    # " x " between numbers means multiply: "2 x 5" -> "2 × 5" (but not "3x").
    text = re.sub(r"(?<=[\d)⁰¹²³⁴⁵⁶⁷⁸⁹]) x (?=[\d(])", " × ", text)
    return text
