# PWL Conditional-Greedy Audit: Current 30-Bus BASE Case

- Status: **ACCEPTED AS AN INTERNAL DIAGNOSTIC**
- D-CHP price source: `results\paper_main\prices_schedule_all_units_30base.csv`
- Cost representation: three-segment convex PWL costs; 24-period horizon.
- Ordinary ON intervals tested: 857
- Initially-online intervals excluded from this diagnostic: 39
- Certified conditional-greedy intervals: 699
- Intervals without a conditional-greedy certificate (handled by the exact LP): 158
- Maximum absolute interval-profit difference from the exact LP: 5.531e-07 dollars
- Maximum certified linearization gap: 8.570e-07
- Maximum output-vector difference: 26.666667 MW
- Median conditional-greedy time: 0.002453 s
- Median exact interval-LP time: 0.000580 s

The acceptance criterion is interval-profit agreement within 1e-05 dollars
for every interval that obtains a conditional-greedy certificate.
Output vectors may differ at degenerate optima; the profit comparison is the
relevant criterion for ON-arc evaluation and the outer alternating-path
calculation.  The production routine uses the exact compact LP for PWL costs;
this conditional-greedy procedure is retained only as a structural diagnostic.
