# Cookie Cats: should the first gate move to level 40?

*Rahul Jha, KinetiArc. Independent analysis of a public dataset; not affiliated with Tactile Entertainment.*

## 1. Decision

**Keep the first gate at level 30, because moving it to level 40 significantly lowered day-7 retention.** One warning: the player split was not the 50/50 we intended, and a split this uneven would arise by chance only 0.86% of the time (a sample ratio mismatch). That could mean an assignment bug, logging loss, or bot filtering applied unevenly. This data can't tell us which, so trust the direction of the gap more than its exact size (section 4).

## 2. What we tested

90,189 new players were randomised at install: 44,700 with the first gate at level 30, and 45,489 at level 40.
The main measure was day-7 retention, with day-1 retention as a safety check.

## 3. What happened

| | Level 30 | Level 40 | Gap (percentage points) | 95% range of gap | Relative change, level 40 | Significant? |
|---|---|---|---|---|---|---|
| **Day 7** | 19.02% | 18.20% | 0.82 | 0.31 to 1.33 | 4.3% lower | Yes |
| **Day 1** | 44.82% | 44.23% | 0.59 | −0.06 to 1.24 | 1.3% lower | No |

When we resampled the results 10,000 times, level 30 came out ahead on day 7 in 99.9% of runs, and on day 1 in 96.5%.

| Retention and gap | Resampled gap |
|---|---|
| ![Retention by variant](out/01_retention_by_variant.png) | ![Bootstrap gap](out/02_bootstrap_gap.png) |

## 4. Can we trust it?

- **Player split:** level 40 has 789 more players than level 30. If those are surplus, the result stops being significant only if at least 784 of them (99.4%) weren't retained on day 7, against 81.8% for a typical level 40 player. Even then, the gap is still 0.50 points in the same direction.
- **Outlier:** one level 30 player logged 49,854 rounds in 14 days. Removing them leaves the day-7 gap at 0.82 points.
- **Test sensitivity:** the smallest gap this test could reliably catch is 0.72 points on day 7 and 0.93 on day 1. The day-1 gap is below that, so "not significant" doesn't mean "no effect".

## 5. What it means for the business

Per 100,000 installs, the day-7 gap works out to about 820 players lost by day 7 (range 312 to 1,328). This is arithmetic on retention, not a revenue claim.

## 6. Next experiment

First find the cause of the uneven split. Each test below checks the split before anyone reads results, with day-1 retention and rounds played as guardrails, and logs revenue.

- **Level 25 vs level 30.** Hypothesis: an earlier gate raises day-7 retention. Metric: day-7 retention. Sample: 35,948 players per arm, to catch a gap the size of this one (0.82 points).
- **Shorter wait at level 30 vs the current wait.** Hypothesis: a softer gate keeps more players to day 7, and logged revenue shows what that costs. Metric: day-7 retention. Sample: 96,714 players per arm, to catch a smaller 0.5-point gap.

## 7. Limitations

- There is no revenue data, so a later gate's effect on monetisation is unmeasured.
- Rounds aren't levels: failed attempts count, so we can't see who reached a gate. Players with under 30 rounds (62.7% and 63.5% of the two groups) can't have reached either one.
- Rounds are measured after assignment, so any split by rounds is descriptive, not causal.
- The cause of the uneven split is unknown, and the file has no dates or device data to diagnose it.
