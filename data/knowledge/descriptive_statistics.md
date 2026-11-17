# Descriptive statistics (draft notes, written with AI assistance, under my review)

## Mean
Mean = sum of all values / number of values. It uses every value, so it is affected by extreme values (outliers). Common mistake: adding the values correctly but dividing by the wrong count.

## Median and mode
Median: sort the values first. For n values the median is in position (n + 1)/2; with an even number of values it is the mean of the two middle values. The median is not affected by extreme values, so it suits skewed data such as incomes. Mode: the most frequent value; there may be none or several. Common mistake: taking the middle of the unsorted list.

## Range, variance and standard deviation
Range = largest value - smallest value. Variance measures the average squared distance from the mean. Steps: find the mean; subtract it from each value (deviations); square each deviation; add the squares. Population variance divides this sum by n; SAMPLE variance divides by n - 1. Standard deviation = square root of the variance, in the same units as the data. Check: the deviations must add up to zero. Common mistake: dividing by n when the question asks for the sample standard deviation, or forgetting the square root.

## Grouped frequency data: mean
When data are grouped into classes, use the class midpoint as each class's value. Midpoint = (lower boundary + upper boundary) / 2. Estimated mean = sum of (frequency x midpoint) / sum of frequencies. It is an estimate because the exact values inside each class are unknown.

## Grouped frequency data: median
Find n/2. Make a cumulative frequency column to find the median class, the class where the cumulative frequency first reaches n/2. Then interpolate: median = L + ((n/2 - F) / f) x w, where L = lower boundary of the median class, F = cumulative frequency BEFORE the median class, f = frequency of the median class, w = class width. Common mistake: using the cumulative frequency of the median class itself as F.
