# Estimation, testing and regression (draft notes, written with AI assistance, under my review)

## Standard error
The sample mean varies from sample to sample. Its standard deviation is the standard error: SE = sigma / sqrt(n), where sigma is the population standard deviation and n the sample size. Larger samples give smaller standard errors, so more precise estimates. Common mistake: dividing by n instead of sqrt(n).

## Confidence intervals for a mean
A confidence interval gives a range of plausible values for the population mean: sample mean ± z x SE. Common z values: 1.645 for 90%, 1.96 for 95%, 2.576 for 99%. The part z x SE is the margin of error. Lower limit = mean - margin; upper limit = mean + margin. A higher confidence level gives a wider interval. Interpretation: we are 95% confident that the interval contains the true population mean.

## Hypothesis tests: steps
(1) State the null hypothesis H0 (e.g. the mean equals the claimed value) and the alternative H1 (not equal, greater, or less). (2) Choose the significance level, often 5%. (3) Calculate the test statistic z = (sample mean - claimed mean) / SE. (4) Compare with the critical value (1.96 for a two-tailed test at 5%) or find the p-value. (5) Conclude in the context of the question.

## p-values
The p-value is the probability of getting a result at least as extreme as the one observed if H0 is true. For a two-tailed z-test, p = 2 x P(Z > |z|); for a one-tailed test, p = P(Z > z) (or P(Z < z)). If p is less than the significance level, reject H0. A small p-value is evidence against H0; it does not prove H1 and does not measure the size of an effect.

## Correlation
The correlation coefficient r (between -1 and 1) measures the strength and direction of a LINEAR relationship. Close to 1: strong positive; close to -1: strong negative; near 0: no linear relationship. Correlation does not prove causation.

## Least squares regression
The regression line of y on x is y = a + bx. Slope b = Sxy / Sxx, where Sxy = sum of (x - x-bar)(y - y-bar) and Sxx = sum of (x - x-bar)^2. Intercept a = y-bar - b x x-bar; the line always passes through (x-bar, y-bar). To predict, substitute the x value into the line. Predictions outside the range of the data (extrapolation) are less reliable. Common mistake: swapping x and y, or finding a before b.
