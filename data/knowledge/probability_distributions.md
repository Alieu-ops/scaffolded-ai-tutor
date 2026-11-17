# Probability and distributions (draft notes, written with AI assistance, under my review)

## Basic probability
For equally likely outcomes, P(event) = number of favourable outcomes / total number of outcomes. Probabilities lie between 0 and 1. P(not A) = 1 - P(A). Simplify fractions at the end.

## Addition and multiplication rules
Addition rule: P(A or B) = P(A) + P(B) - P(A and B); subtract the overlap so it is not counted twice. If A and B cannot happen together (mutually exclusive), P(A and B) = 0. Multiplication rule for independent events: P(A and B) = P(A) x P(B). Common mistake: confusing independent (one does not affect the other) with mutually exclusive (cannot both happen).

## Conditional probability and choosing without replacement
When items are chosen without replacement, the second probability changes: both the number of favourable items and the total go down by one. P(A and B) = P(A) x P(B given A). A tree diagram helps: multiply along the branches, add between branches.

## Binomial distribution
Use it when there is a fixed number n of independent trials, each with two outcomes (success/failure) and the same success probability p. P(X = k) = nCk x p^k x (1 - p)^(n - k), where nCk = n! / (k!(n - k)!) is the number of ways to choose which k trials are successes. Mean = np; variance = np(1 - p). Common mistake: forgetting the nCk term, or using p for the failures as well.

## Normal distribution
Many measurements (times, weights, sales) follow a bell-shaped normal distribution with mean mu and standard deviation sigma. Standardise with z = (x - mu) / sigma, which tells how many standard deviations x is from the mean. Then read P(Z < z) from the standard normal table. P(Z > z) = 1 - P(Z < z). P(a < X < b) = P(Z < z_b) - P(Z < z_a). For a negative z, use symmetry: P(Z < -z) = 1 - P(Z < z). Sketching the curve and shading the required area helps avoid mistakes.
