# Financial mathematics (draft notes, written with AI assistance, under my review)

## Simple interest
Interest is paid only on the original amount (principal). I = P x r x t, where r is the yearly rate as a decimal (8% = 0.08) and t is the time in years. Amount at the end A = P + I = P(1 + rt). Common mistake: using 8 instead of 0.08, or giving the amount when the question asks for the interest.

## Compound interest
Interest is added to the balance and then earns interest itself. A = P(1 + r)^n for annual compounding over n years. If interest is compounded m times a year, use rate r/m per period and n x m periods: A = P(1 + r/m)^(nm). Compound interest earned = A - P. Common mistake: multiplying the rate by the number of years (that is simple interest).

## Annuities and savings plans
An annuity is a series of equal payments at regular intervals, for example saving the same amount every month or every year, paying a pension, or repaying a loan in equal instalments. Future value of payments R made at the END of each period: S = R((1 + r)^n - 1) / r. Present value of such payments: PV = R(1 - (1 + r)^-n) / r. A loan repayment is found by rearranging the present value formula for R. Common mistake: using the compound interest formula for a single payment instead of the annuity formula.

## Present value and discounting
Present value is what a future amount is worth today. PV = FV / (1 + r)^n. The discount factor for year n is 1 / (1 + r)^n. The higher the interest (discount) rate or the longer the wait, the lower the present value.

## Net present value (NPV)
NPV = sum of the present values of all future cash flows - initial cost. Discount each year's cash flow separately using its own discount factor, then add. If NPV is positive, the project earns more than the discount rate and is worth accepting; if negative, it earns less. Keep enough decimal places in the discount factors, and round only at the end.

## Depreciation
Straight-line method: the value falls by the same amount each year: annual depreciation = (cost - residual value) / useful life. Reducing balance method: the value falls by the same PERCENTAGE each year, so value after n years = cost x (1 - d)^n, where d is the rate as a decimal. Common mistake: subtracting the percentage of the ORIGINAL cost every year under reducing balance.
