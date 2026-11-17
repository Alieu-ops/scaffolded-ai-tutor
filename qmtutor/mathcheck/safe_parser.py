"""
Safe mathematical parser: turns student text such as "40 + 15u", "2000(1.05)^2"
or "5%" into a SymPy expression WITHOUT ever executing the text as code.

Why not sympy.sympify / parse_expr? Both call Python's eval() internally, so
crafted input like "__import__('os').system(...)" can run code. This module
instead:
    1. normalises notation (unicode symbols, thousands commas, units);
    2. splits the text into tokens and rejects anything not on an allow-list;
    3. builds the SymPy object itself with a small recursive-descent parser.
Nothing the student types is ever handed to eval, exec or sympify.

Supported notation (deliberately small; extend only when a course item needs it):
    numbers 12, 3.5, 1,250 (thousands), percentages 5%
    + - * / ^ (also ** and x/× between numbers), brackets
    implicit multiplication: 15u, 2(3+4), (1+r)(1+r)
    functions sqrt, ln (natural log), log (base 10), log_b / log₂ (any base), exp
    constants pi, e
    single-letter variables (except e), when allowed by the caller

Complexity limits stop "denial of service" input such as 9^9^9^9.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sympy

from tutor.mathtext import to_plain   # reused from v1: "2¹⁰" -> "2^10", "√" -> "sqrt"

MAX_LENGTH = 200
MAX_TOKENS = 120
MAX_DEPTH = 25
MAX_EXPONENT = 400        # |numeric exponent| above this is rejected
MAX_ABS_VALUE = 10**60    # numeric results above this are rejected

FUNCTIONS = {
    "sqrt": sympy.sqrt,
    "ln": sympy.log,                               # natural log
    "log": lambda x: sympy.log(x, 10),             # base 10 (business-course convention)
    "exp": sympy.exp,
}
CONSTANTS = {"pi": sympy.pi, "e": sympy.E}

# Currency words that may precede or follow a money value. Removed before parsing.
CURRENCY_WORDS = ["gmd", "dalasis", "dalasi"]


class MathParseError(ValueError):
    """Raised for input the safe parser will not accept. `code` is machine-readable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Token:
    kind: str    # NUMBER, NAME, OP, LPAREN, RPAREN, PERCENT, EQUALS
    text: str


# -
# Step 1: normalise notation
# -
def normalise_text(text: str, unit_words: list[str] | None = None) -> str:
    """Lower-case, convert unicode maths, drop currency/unit words and thousands commas."""
    # "×" and "·" become "*" first: to_plain would turn them into the letter "x",
    # which broke "5%×2000" and "π×2" (found by a keypad test, 3 Oct 2026).
    text = str(text).replace("×", "*").replace("·", "*")
    text = to_plain(text).lower().strip()
    # The maths keyboard's "√16" arrives as "sqrt16": treat it as sqrt(16).
    text = re.sub(r"sqrt(\d+(?:\.\d+)?)", r"sqrt(\1)", text)
    text = text.replace("**", "^").replace("÷", "/").replace("−", "-")
    words = sorted(CURRENCY_WORDS + [w.lower() for w in (unit_words or [])], key=len, reverse=True)
    for word in words:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
    # "D 600" or "d600": the Gambian dalasi symbol before a number.
    text = re.sub(r"(?<![a-z])d\s*(?=\d)", "", text)
    # "13,382.26" -> "13382.26": a comma followed by exactly three digits.
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    # " x " between numbers or brackets means multiply ("2 x 5").
    text = re.sub(r"(?<=[\d)])\s*x\s*(?=[\d(])", "*", text)
    return re.sub(r"\s+", " ", text).strip()


# -
# Step 2: tokenise against an allow-list
# -
# The first group catches a logarithm with an explicit base, "log_2" (the keypad's "log₂").
TOKEN_PATTERN = re.compile(
    r"\s*(?:log_(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?|\.\d+)|([a-z]+)|(\^|\*|/|\+|-)|(\()|(\))|(%)|(=))")


def tokenise(text: str, allowed_variables: set[str]) -> list[Token]:
    if len(text) > MAX_LENGTH:
        raise MathParseError("too_long", f"Please keep the answer under {MAX_LENGTH} characters.")
    tokens: list[Token] = []
    position = 0
    while position < len(text):
        match = TOKEN_PATTERN.match(text, position)
        if not match or match.end() == position:
            bad = text[position:].strip()[:10]
            raise MathParseError("unsupported_symbol", f"I can't read '{bad}'. Use numbers, + - * / ^ and brackets.")
        log_base, number, name, op, lparen, rparen, percent, equals = match.groups()
        if log_base:
            if float(log_base) in (0, 1):
                raise MathParseError("bad_log_base", "A logarithm base must not be 0 or 1.")
            tokens.append(Token("LOGBASE", log_base))
        elif number:
            tokens.append(Token("NUMBER", number))
        elif name:
            tokens.extend(_split_name(name, allowed_variables))
        elif op:
            tokens.append(Token("OP", op))
        elif lparen:
            tokens.append(Token("LPAREN", "("))
        elif rparen:
            tokens.append(Token("RPAREN", ")"))
        elif percent:
            tokens.append(Token("PERCENT", "%"))
        elif equals:
            tokens.append(Token("EQUALS", "="))
        position = match.end()
        if len(tokens) > MAX_TOKENS:
            raise MathParseError("too_complex", "That expression is too long to check.")
    return tokens


def _split_name(name: str, allowed_variables: set[str]) -> list[Token]:
    """
    A run of letters is a known function/constant, or a product of allowed
    single-letter variables ("pr" -> p*r). Anything else is rejected, which is
    what blocks attempts like "import" or "lambda".
    """
    if name in FUNCTIONS or name in CONSTANTS:
        return [Token("NAME", name)]
    if all(ch in allowed_variables for ch in name):
        return [Token("NAME", ch) for ch in name]
    if name in NUMBER_WORDS:
        # A number spelled out is a format slip, not a maths error: say how to fix it.
        raise MathParseError("number_word", f"Please write '{name}' as digits, for example 12 instead of twelve.")
    raise MathParseError("unknown_name", f"I don't recognise '{name}' in a maths answer.")


# Spelled-out numbers students may type in place of digits (checked after functions and variables).
NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion", "half", "quarter",
}


# -
# Step 3: recursive-descent parser that builds SymPy objects directly
# -
class _Parser:
    """
    Grammar (lowest to highest precedence):
        expression := term (('+' | '-') term)*
        term       := unary (('*' | '/' | implicit) unary)*
        unary      := ('+' | '-') unary | power
        power      := postfix ('^' unary)?          right-associative
        postfix    := atom '%'?
        atom       := NUMBER | NAME | FUNCTION '(' expression ')' | LOGBASE '(' expression ')'
                      | '(' expression ')'
    So "-2^2" is -(2^2) = -4, as in standard mathematical convention.
    """

    def __init__(self, tokens: list[Token], exact_numbers: bool = True):
        self.tokens = tokens
        self.exact_numbers = exact_numbers   # False only for the preview: show 1.06, not 53/50
        self.index = 0
        self.depth = 0

    def peek(self) -> Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self) -> Token:
        token = self.peek()
        if token is None:
            raise MathParseError("incomplete", "The expression seems to be incomplete.")
        self.index += 1
        return token

    def _enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise MathParseError("too_complex", "That expression is nested too deeply to check.")

    def parse(self) -> sympy.Expr:
        result = self.expression()
        if self.peek() is not None:
            raise MathParseError("unexpected_token", f"Unexpected '{self.peek().text}'.")
        return result

    def expression(self) -> sympy.Expr:
        self._enter()
        value = self.term()
        while (tok := self.peek()) and tok.kind == "OP" and tok.text in "+-":
            self.take()
            right = self.term()
            value = value + right if tok.text == "+" else value - right
        self.depth -= 1
        return value

    def _starts_atom(self, token: Token | None) -> bool:
        return token is not None and token.kind in ("NUMBER", "NAME", "LPAREN", "LOGBASE")

    def term(self) -> sympy.Expr:
        value = self.unary()
        while True:
            tok = self.peek()
            if tok and tok.kind == "OP" and tok.text in "*/":
                self.take()
                right = self.unary()
                if tok.text == "/":
                    if right == 0:
                        raise MathParseError("division_by_zero", "That expression divides by zero.")
                    value = value / right
                else:
                    value = value * right
            elif self._starts_atom(tok):        # implicit multiplication: 15u, 2(3+4)
                value = value * self.unary()
            else:
                return value

    def unary(self) -> sympy.Expr:
        tok = self.peek()
        if tok and tok.kind == "OP" and tok.text in "+-":
            self.take()
            self._enter()
            operand = self.unary()
            self.depth -= 1
            return -operand if tok.text == "-" else operand
        return self.power()

    def power(self) -> sympy.Expr:
        base = self.postfix()
        tok = self.peek()
        if tok and tok.kind == "OP" and tok.text == "^":
            self.take()
            self._enter()
            exponent = self.unary()
            self.depth -= 1
            if exponent.is_number and abs(float(exponent)) > MAX_EXPONENT:
                raise MathParseError("too_complex", "That power is too large to check.")
            return sympy.Pow(base, exponent)
        return base

    def postfix(self) -> sympy.Expr:
        value = self.atom()
        if (tok := self.peek()) and tok.kind == "PERCENT":
            self.take()
            value = value / 100
        return value

    def atom(self) -> sympy.Expr:
        tok = self.take()
        if tok.kind == "NUMBER":
            # Rational keeps 0.1 exact (not 0.1000000000000000055...).
            if self.exact_numbers or "." not in tok.text:
                return sympy.Rational(tok.text)
            return sympy.Float(tok.text, len(tok.text))
        if tok.kind == "NAME":
            if tok.text in FUNCTIONS:
                if not (self.peek() and self.peek().kind == "LPAREN"):
                    raise MathParseError("function_needs_brackets", f"Write {tok.text}(...) with brackets.")
                self.take()
                argument = self.expression()
                self._expect_rparen()
                return FUNCTIONS[tok.text](argument)
            if tok.text in CONSTANTS:
                return CONSTANTS[tok.text]
            return sympy.Symbol(tok.text)
        if tok.kind == "LOGBASE":        # log₂(8) arrives as "log_2(8)"
            if not (self.peek() and self.peek().kind == "LPAREN"):
                raise MathParseError("function_needs_brackets", "Write log₂(...) with brackets.")
            self.take()
            argument = self.expression()
            self._expect_rparen()
            return sympy.log(argument, sympy.Rational(tok.text))
        if tok.kind == "LPAREN":
            value = self.expression()
            self._expect_rparen()
            return value
        raise MathParseError("unexpected_token", f"Unexpected '{tok.text}'.")

    def _expect_rparen(self):
        if self.peek() is None:
            raise MathParseError("unbalanced_brackets", "A bracket is not closed.")
        tok = self.take()
        if tok.kind != "RPAREN":
            raise MathParseError("unbalanced_brackets", "A bracket is not closed.")


# -
# Public functions
# -
@dataclass(frozen=True)
class ParsedAnswer:
    expression: sympy.Expr
    assigned_variable: str | None   # "u" when the student wrote "u = 7"
    normalised_text: str


def parse_answer(text: str, allowed_variables: set[str] | None = None,
                 unit_words: list[str] | None = None, evaluate: bool = True) -> ParsedAnswer:
    """
    Parse a student's final answer. Accepts either an expression ("7", "2000*1.05^2")
    or a single assignment ("u = 7"). Raises MathParseError for anything else.
    evaluate=False keeps the expression as typed (for the preview), e.g. 1.06^5
    instead of SymPy's automatically simplified fraction.
    """
    allowed = set(allowed_variables or set()) - {"e"}
    normalised = normalise_text(text, unit_words)
    if not normalised:
        raise MathParseError("empty", "Please type an answer.")
    if "," in normalised or ";" in normalised:
        # Multi-part answers (e.g. "P = 30, Q = 80") are planned, not implemented.
        raise MathParseError("multi_part_unsupported", "Please give one value only.")

    assigned = None
    if "=" in normalised:
        # Only the form "<single letter> = <expression>" is accepted. The letter
        # is returned so the verifier can say "wrong variable" rather than fail.
        match = re.fullmatch(r"([a-z])\s*=\s*([^=]+)", normalised)
        if not match:
            raise MathParseError("equation_form", "Write the answer as a value, e.g. 7 or u = 7.")
        assigned, normalised = match.group(1), match.group(2).strip()

    tokens = tokenise(normalised, allowed)
    with sympy.evaluate(evaluate):
        expression = _Parser(tokens, exact_numbers=evaluate).parse()
    if expression.is_number:
        value = expression.evalf(30)
        if value.is_real is False:
            raise MathParseError("not_real", "That expression is not a real number.")
        if value.is_finite is False or (value.is_real and abs(value) > MAX_ABS_VALUE):
            raise MathParseError("too_large", "That number is too large to check.")
    return ParsedAnswer(expression, assigned, normalised)


def evaluate_for_calculator(text: str) -> tuple[str, str]:
    """
    Calculator helper: evaluate a numeric expression with the same safe parser.
    Returns (decimal_result, latex_preview). Raises MathParseError.
    """
    parsed = parse_answer(text)
    if not parsed.expression.is_number:
        raise MathParseError("not_numeric", "The calculator only works with numbers.")
    value = parsed.expression.evalf(12)
    return f"{float(value):.10g}", sympy.latex(parse_answer(text, evaluate=False).expression, mul_symbol="times")


def latex_preview(text: str, allowed_variables: set[str] | None = None) -> str | None:
    """LaTeX for the equation preview, or None if the text cannot be parsed yet."""
    try:
        parse_answer(text, allowed_variables, evaluate=False)    # validation: is it readable maths?
    except MathParseError:
        return None
    # Display with the order-preserving renderer, not SymPy's LaTeX: SymPy dropped the base of
    # log₂(8) and once hid the × in 2000*1.05^2 (both found 3 Oct 2026).
    from qmtutor.mathcheck.reasoning_format import render_expression   # local import avoids a cycle
    return render_expression(text)
