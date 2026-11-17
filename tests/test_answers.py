"""Tests for the answer checker and the answer-leak detector. Run: pytest"""

from tutor.answers import check_answer, copies_solution, reveals_answer


def test_equivalent_forms_accepted():
    assert check_answer("5", "x = 5")
    assert check_answer("x=5", "x = 5")
    assert check_answer("0.375", "3/8")
    assert check_answer("3 / 8", "3/8")
    assert check_answer("D600", "600")
    assert check_answer("600 dalasi", "600")
    assert check_answer("720", "720 degrees")
    assert check_answer("720°", "720 degrees")
    assert check_answer("60", "060")          # bearings
    assert check_answer("0.33", "1/3")        # rounded decimal
    assert check_answer("1.4167", "17/12")
    assert check_answer("30cm^2", "30 cm^2")
    assert check_answer("2^7", "128")         # found in my testing
    assert not check_answer("10^3", "3")      # log question: 10^3 is not the answer


def test_multiple_values():
    assert check_answer("x = 3 or x = 2", "x = 2 or x = 3")
    assert check_answer("2, 3", "x = 2 or x = 3")
    assert check_answer("x=4, y=3", "x = 4, y = 3")
    assert check_answer("y = 3, x = 4", "x = 4, y = 3")
    assert not check_answer("x=3, y=4", "x = 4, y = 3")   # swapped values
    assert not check_answer("2", "x = 2 or x = 3")        # only one root


def test_factorisation():
    assert check_answer("(x+3)(x-3)", "(x - 3)(x + 3)")
    assert not check_answer("(x-3)(x-3)", "(x - 3)(x + 3)")


def test_wrong_answers_rejected():
    assert not check_answer("6", "x = 5")
    assert not check_answer("", "x = 5")
    assert not check_answer("I don't know", "x = 5")
    assert not check_answer("0.4", "3/8")


def test_decimal_precision():
    # Decimal answers: the student's number must round to the correct one.
    assert check_answer("0.0214", "0.0214")
    assert check_answer("0.02140", "0.0214")
    assert not check_answer("0.02", "0.0214")     # too rough
    assert not check_answer("0.05", "0.0456")     # p-value found too loose in v1 checker
    assert check_answer("0.32805", "0.3281")      # more decimal places is fine
    assert check_answer("1.5811", "1.58")
    assert not check_answer("1.6", "1.58")
    assert not check_answer("13382", "13382.26")  # question asks for 2 decimal places
    # Whole numbers must be exact.
    assert check_answer("10500", "10500")
    assert not check_answer("10550", "10500")
    assert not check_answer("59.8", "60")
    # Signs matter.
    assert check_answer("-525.92", "-525.92")
    assert not check_answer("525.92", "-525.92")


def test_money_and_interval_formats():
    assert check_answer("13,382.26", "13382.26")      # thousands comma
    assert check_answer("GMD 12,210.20", "12210.20")
    assert check_answer("D40,960", "40960")
    assert check_answer("820.6-879.4", "820.6, 879.4")   # interval with a dash
    assert check_answer("820.6 – 879.4", "820.6, 879.4")  # en dash
    assert check_answer("(820.6, 879.4)", "820.6, 879.4")
    assert check_answer("820.6 to 879.4", "820.6, 879.4")
    assert not check_answer("820.6", "820.6, 879.4")     # one limit only
    assert check_answer("P = 30, Q = 80", "P = 30, Q = 80")
    assert check_answer("q=10 or q=50", "q = 10 or q = 50")
    assert check_answer("50, 10", "q = 10 or q = 50")
    assert check_answer("7.40", "7.4")


def test_leak_detector_business_formats():
    q = "GMD 10000 is invested at 6% per year, compounded annually. Amount after 5 years?"
    assert reveals_answer("You should get 13,382.26.", "13382.26", q)
    assert reveals_answer("It comes to about GMD 13382.", "13382.26", q)   # rounded still a leak
    assert not reveals_answer("Use A = P(1 + r)^n with r = 0.06.", "13382.26", q)
    q = "Find a 95% confidence interval. Mean 850, sd 120, n = 64."
    assert reveals_answer("The interval is 820.6-879.4.", "820.6, 879.4", q)


def test_copying_the_worked_solution_is_a_leak():
    q = "A firm's profit is π = -q^2 + 80q - 700. Find the maximum profit."
    solution = ("dπ/dq = -2q + 80 = 0 gives q = 40. The second derivative is -2 "
                "(negative), so this is a maximum. Maximum profit = -(40^2) + 80(40) "
                "- 700 = -1600 + 3200 - 700 = 900.")
    # Found in the live test with llama3.2: every step except the last sum.
    leaked = ("I can't give you the final answer. But I can provide the worked solution "
              "up to the step where you need to calculate the maximum profit: dπ/dq = "
              "-2q + 80 = 0 gives q = 40. The second derivative is -2 (negative), so "
              "this is a maximum. Maximum profit = -(40^2) + 80(40) - 700")
    assert copies_solution(leaked, solution, q)
    # Allowed: naming the method, or restating the question.
    assert not copies_solution("Differentiate the profit function and set dπ/dq = 0.", solution, q)
    assert not copies_solution("Your profit function is π = -q^2 + 80q - 700.", solution, q)
    # Allowed: repeating the student's own working back to them.
    student = "I got -2q + 80 = 0 gives q = 40"
    assert not copies_solution("Good: -2q + 80 = 0 gives q = 40. What next?",
                               solution, f"{q} {student}")


def test_naming_a_formula_is_not_copying():
    q = "GMD 10000 is invested at 6% per year, compounded annually. Amount after 5 years?"
    solution = "A = P(1 + r)^n = 10000 x 1.06^5 = 10000 x 1.3382256 = 13382.26."
    assert not copies_solution("Use the formula A = P(1 + r)^n. What is r here?", solution, q)
    assert copies_solution("So A = 10000 x 1.06^5 = 10000 x 1.3382256, now round.", solution, q)


def test_leak_detector():
    q = "A shirt costs D500. The price is increased by 20%. What is the new price in dalasi?"
    assert reveals_answer("So the new price is D600.", "600", q)
    assert not reveals_answer("What is 20% of 500? Add it to the old price.", "600", q)

    q = "Evaluate 3/4 + 2/3. Give your answer as a fraction."
    assert reveals_answer("The answer is 17/12.", "17/12", q)
    assert not reveals_answer("Try writing both fractions with denominator 12.", "17/12", q)

    q = "Solve x^2 - 5x + 6 = 0."
    assert reveals_answer("x = 2 or x = 3", "x = 2 or x = 3", q)
    assert not reveals_answer("Find two numbers that multiply to 6.", "x = 2 or x = 3", q)
    # Found in the live test with llama3.2: factorised form gives the roots away.
    assert reveals_answer("The factorization is (x - 2)(x - 3) = 0.", "x = 2 or x = 3", q)

    q = "Factorise x^2 - 9."
    assert reveals_answer("It is (x+3)(x-3).", "(x - 3)(x + 3)", q)
    assert not reveals_answer("Is 9 a perfect square?", "(x - 3)(x + 3)", q)
