"""
Pretty preview of written reasoning: words stay as words, maths becomes LaTeX.

A student types with a normal keyboard, mixing sentences and working:
    "Subtract 3x from both sides: 5x - 3x = 20 + 12, so 2x = 32 and x = 16"
The preview shows the equations typeset ($5x - 3x = 20 + 12$ ...) and the
words unchanged.

How: find spans that look like maths (numbers, single-letter variables,
operators, = signs), check each one with the safe parser, and only convert
a span that parses. Anything unclear is left exactly as typed.

Why code and not the LLM: the preview must never change what the student
wrote. An LLM asked to "format" reasoning tends to tidy it, and can quietly
correct a mistake or add a step, which would corrupt the evidence we assess
and could even leak the answer. Here the raw text is always what is saved;
this function only affects the display.
"""

from __future__ import annotations

import re

from qmtutor.mathcheck.safe_parser import MathParseError, parse_answer

# One "maths token": a number, a single letter standing alone (a variable), a
# function name, or an operator / maths symbol.
_TOKEN = (r"(?:\d+(?:[.,]\d+)*|(?<![a-zA-Z])[a-zA-Z](?![a-zA-Z])|sqrt|ln|log(?:_\d+)?|pi"
          # Short letter groups touching a bracket or operator are products of variables, e.g.
          # the "nm" in "(1 + r/m)^(nm)"; ordinary words in sentences are not touched.
          r"|(?<=[(^*/])[a-zA-Z]{2,3}(?![a-zA-Z])|(?<![a-zA-Z])[a-zA-Z]{2,3}(?=[)^*/])"
          r"|[+\-*/^()=×÷−·√%π²³¹⁰⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾₀₁₂₃₄₅₆₇₈₉])")
_FUNCTION_NAMES = {"sqrt", "ln", "log", "exp", "pi"}
_SPAN = re.compile(rf"{_TOKEN}(?:[ \t]*{_TOKEN})*")
_OPERATOR = re.compile(r"[+\-*/^=×÷−·√%²³¹⁰⁴⁵⁶⁷⁸⁹]")
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]<>#|$~])")


def _escape_all(text: str) -> str:
    """Escape Markdown characters in the student's words so they display literally."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


_SUP = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾", "0123456789+-()"))
_SUB = dict(zip("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
_RENDER_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|log_\d+|sqrt|ln|log|exp|pi|[a-zA-Z]|[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾]+"
                           r"|[₀₁₂₃₄₅₆₇₈₉]+|\s+|.")
_SYMBOLS = {"*": r" \times ", "×": r" \times ", "·": r" \times ", "÷": r" \div ", "−": "-", "%": r"\%",
            "π": r"\pi ", "pi": r"\pi ", "ln": r"\ln ", "log": r"\log ", "exp": r"\exp "}


def _render(text: str) -> str:
    """
    Turn one maths expression into LaTeX WITHOUT reordering or simplifying it:
    the student's own symbols, in the student's order. (SymPy would rewrite
    "5x - 3x" as "-3x + 5x"; fine for checking, wrong for display.)
    """
    tokens = [t for t in _RENDER_TOKEN.findall(text)]
    out, i = [], 0

    def group(start: int) -> tuple[str, int]:
        """Render the atom starting at tokens[start]; a bracket group is rendered whole."""
        while start < len(tokens) and tokens[start].isspace():
            start += 1
        if start >= len(tokens):
            return "", start
        if tokens[start] == "(":
            depth, end = 0, start
            for end in range(start, len(tokens)):
                depth += tokens[end] == "("
                depth -= tokens[end] == ")"
                if depth == 0:
                    break
            return "(" + _render("".join(tokens[start + 1:end])) + ")", end + 1
        return _render(tokens[start]), start + 1

    while i < len(tokens):
        tok = tokens[i]
        if tok == "^":
            body, i = group(i + 1)
            out.append("^{" + body.strip("()") + "}" if body.startswith("(") and body.endswith(")") else "^{" + body + "}")
            continue
        if tok in ("√", "sqrt"):
            body, i = group(i + 1)
            out.append(r"\sqrt{" + (body[1:-1] if body.startswith("(") and body.endswith(")") else body) + "}")
            continue
        if tok.startswith("log_"):
            out.append(r"\log_{" + tok[4:] + "}")
        elif tok[0] in _SUP:
            out.append("^{" + "".join(_SUP[c] for c in tok) + "}")
        elif tok[0] in _SUB:
            out.append("_{" + "".join(_SUB[c] for c in tok) + "}")
        elif tok == "x" and _is_times_x(tokens, i):
            out.append(r" \times ")
        elif tok in _SYMBOLS:
            out.append(_SYMBOLS[tok])
        elif tok.isspace():
            out.append(" ")
        else:
            out.append(tok.replace(",", "{,}"))
        i += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _is_times_x(tokens: list[str], i: int) -> bool:
    """'2000 x 1.05' means multiply: an 'x' with spaces around it between a number/bracket and a number/bracket."""
    before = tokens[i - 2] if i >= 2 and tokens[i - 1].isspace() else ""
    after = tokens[i + 2] if i + 2 < len(tokens) and tokens[i + 1].isspace() else ""
    return bool(before) and bool(after) and (before[0].isdigit() or before == ")") and (after[0].isdigit() or after == "(")


def _span_to_latex(span: str) -> str | None:
    """LaTeX for a maths span such as '5x - 3x = 20 + 12', or None if any part is not valid maths."""
    runs = re.findall(r"(?<![a-zA-Z])[a-zA-Z]{1,3}(?![a-zA-Z])", span)
    variables = {ch.lower() for run in runs if run.lower() not in _FUNCTION_NAMES for ch in run}
    sides = span.split("=")
    if any(not side.strip() for side in sides):
        return None
    for side in sides:
        try:
            parse_answer(side, variables, evaluate=False)   # validation only: is this real maths?
        except MathParseError:
            return None
    return " = ".join(_render(side) for side in sides)


def render_expression(text: str) -> str:
    """Public: LaTeX for one answer or calculation as typed (sides of '=' rendered separately)."""
    return " = ".join(_render(side) for side in str(text).split("="))


def _last_token_start(span: str) -> int:
    """Index where the last maths token of a span begins (0 if there is only one)."""
    starts = [m.start() for m in re.finditer(_TOKEN, span)]
    return starts[-1] if len(starts) > 1 else 0


def _trim(span: str) -> tuple[str, str, str]:
    """Move trailing punctuation-like characters (commas, a lone article 'a') out of the span."""
    core = span.rstrip(" ,")
    return "", core, span[len(core):]


def format_reasoning(text: str, keep_markdown: bool = False) -> str:
    """
    Return Markdown where parseable maths spans are $LaTeX$ and everything else is text.
    Student text: all Markdown characters escaped (shown exactly as typed).
    Tutor text (keep_markdown=True): the tutor's **bold** headings are kept; only "$" is escaped,
    so an amount like "$5" can never be mistaken for the start of a formula.
    """
    _escape = _escape_all if not keep_markdown else (lambda s: s.replace("$", r"\$"))
    lines = []
    for line in str(text).splitlines():
        out, position = [], 0
        for match in _SPAN.finditer(line):
            span = match.group(0)
            # Maths cannot start with these; they are usually Markdown ("**bold**") or punctuation.
            lead = len(span) - len(span.lstrip("*/^=)%·× \t"))
            span_start = match.start() + lead
            _, core, tail = _trim(span[lead:])
            # Only convert spans that contain real maths (an operator or = sign) and a digit or variable.
            if not _OPERATOR.search(core) or not re.search(r"[0-9a-zA-Z]", core):
                continue
            latex = _span_to_latex(core)
            # A span can run into the next words, e.g. "3000 x 1.10^2 = 3630 (the rate...)".
            # If it does not parse, drop tokens from the end until it does (or nothing is left).
            while latex is None:
                cut = _last_token_start(core)
                if cut <= 0:
                    break
                core = core[:cut].rstrip(" ,")
                if "=" not in core and not _OPERATOR.search(core):
                    break
                latex = _span_to_latex(core) if _OPERATOR.search(core) else None
            if latex is None:
                continue
            end = span_start + len(core)
            out.append(_escape(line[position:span_start]))
            out.append(f"${latex}$")
            position = end
        out.append(_escape(line[position:]))
        lines.append("".join(out))
    # Two trailing spaces force a Markdown line break, so the student's line structure is kept.
    return "  \n".join(lines)
