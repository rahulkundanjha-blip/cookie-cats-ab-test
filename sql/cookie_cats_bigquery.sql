-- =============================================================================
-- Cookie Cats A/B test: gate at level 30 (control) vs level 40 (treatment)
-- BigQuery Standard SQL. Run as one script; each SELECT returns one result set.
--
-- Load data/cookie_cats.csv into a table first, e.g.
--   bq load --autodetect --source_format=CSV your_dataset.cookie_cats data/cookie_cats.csv
-- then replace `your_project.your_dataset.cookie_cats` below.
--
-- Columns: userid INT64, version STRING, sum_gamerounds INT64,
--          retention_1 BOOL, retention_7 BOOL
--
-- The notebook (cookie_cats_ab_test.ipynb) computes the same numbers in Python;
-- the two should agree to the last decimal.
-- =============================================================================

-- Standard normal CDF. BigQuery has no built-in, so this uses the
-- Abramowitz & Stegun 7.1.26 approximation of erf (max abs error 1.5e-7),
-- which is far tighter than any decision here needs.
CREATE TEMP FUNCTION _as_t(x FLOAT64) AS (1 / (1 + 0.3275911 * x));
CREATE TEMP FUNCTION _erf_pos(x FLOAT64) AS (
  1 - ((((1.061405429 * _as_t(x) - 1.453152027) * _as_t(x) + 1.421413741) * _as_t(x)
        - 0.284496736) * _as_t(x) + 0.254829592) * _as_t(x) * EXP(-x * x)
);
CREATE TEMP FUNCTION normal_cdf(z FLOAT64) AS (
  IF(z >= 0, 0.5 * (1 + _erf_pos(z / SQRT(2))), 0.5 * (1 - _erf_pos(-z / SQRT(2))))
);
CREATE TEMP FUNCTION two_sided_p(z FLOAT64) AS (2 * (1 - normal_cdf(ABS(z))));


-- @query 1_validation ----------------------------------------------------------
-- Integrity checks before any result is trusted.
SELECT
  COUNT(*)                                                    AS row_count,
  COUNT(DISTINCT userid)                                      AS distinct_players,
  COUNTIF(userid IS NULL OR version IS NULL OR sum_gamerounds IS NULL
          OR retention_1 IS NULL OR retention_7 IS NULL)      AS rows_with_nulls,
  COUNTIF(version NOT IN ('gate_30', 'gate_40'))              AS unexpected_versions,
  MIN(sum_gamerounds)                                         AS rounds_min,
  MAX(sum_gamerounds)                                         AS rounds_max,
  COUNTIF(sum_gamerounds = 0)                                 AS zero_round_players,
  COUNTIF(retention_7 AND NOT retention_1)                    AS d7_without_d1
FROM `your_project.your_dataset.cookie_cats`;


-- @query 2_sample_ratio_mismatch ----------------------------------------------
-- Chi-square (1 dof) against the intended 50/50 split. For 1 dof,
-- p = two-sided normal p of sqrt(chi2).
WITH n AS (
  SELECT
    COUNTIF(version = 'gate_30') AS n_control,
    COUNTIF(version = 'gate_40') AS n_treatment
  FROM `your_project.your_dataset.cookie_cats`
),
chi AS (
  SELECT
    *,
    (n_control + n_treatment) / 2.0 AS expected,
    POW(n_control - (n_control + n_treatment) / 2.0, 2) / ((n_control + n_treatment) / 2.0)
      + POW(n_treatment - (n_control + n_treatment) / 2.0, 2) / ((n_control + n_treatment) / 2.0) AS chi2
  FROM n
)
SELECT
  n_control,
  n_treatment,
  SAFE_DIVIDE(n_control, n_control + n_treatment) AS control_share,
  chi2,
  two_sided_p(SQRT(chi2))                         AS p_value
FROM chi;


-- @query 3_retention_tests -----------------------------------------------------
-- Two-proportion z-test (pooled SE) and 95% Wald CI (unpooled SE)
-- for control minus treatment, for D1 and D7.
WITH long AS (
  SELECT version, 'D1 retention' AS metric, retention_1 AS retained
  FROM `your_project.your_dataset.cookie_cats`
  UNION ALL
  SELECT version, 'D7 retention' AS metric, retention_7 AS retained
  FROM `your_project.your_dataset.cookie_cats`
),
agg AS (
  SELECT
    metric,
    COUNTIF(version = 'gate_30')                 AS n_control,
    COUNTIF(version = 'gate_30' AND retained)    AS x_control,
    COUNTIF(version = 'gate_40')                 AS n_treatment,
    COUNTIF(version = 'gate_40' AND retained)    AS x_treatment
  FROM long
  GROUP BY metric
),
rates AS (
  SELECT
    *,
    SAFE_DIVIDE(x_control, n_control)                                 AS rate_control,
    SAFE_DIVIDE(x_treatment, n_treatment)                             AS rate_treatment,
    SAFE_DIVIDE(x_control + x_treatment, n_control + n_treatment)     AS rate_pooled
  FROM agg
),
se AS (
  SELECT
    *,
    rate_control - rate_treatment AS diff,
    SQRT(rate_pooled * (1 - rate_pooled) * (1.0 / n_control + 1.0 / n_treatment)) AS se_pooled,
    SQRT(rate_control * (1 - rate_control) / n_control
         + rate_treatment * (1 - rate_treatment) / n_treatment)                    AS se_unpooled
  FROM rates
)
SELECT
  metric,
  n_control,
  n_treatment,
  rate_control,
  rate_treatment,
  diff,
  diff - 1.959963985 * se_unpooled                       AS ci_low,
  diff + 1.959963985 * se_unpooled                       AS ci_high,
  SAFE_DIVIDE(rate_treatment - rate_control, rate_control) AS relative_change_treatment_vs_control,
  diff / se_pooled                                       AS z,
  two_sided_p(diff / se_pooled)                          AS p_value,
  -- Smallest gap this sample could detect with 80% power at alpha 0.05.
  (1.959963985 + 0.841621234)
    * SQRT(rate_treatment * (1 - rate_treatment) * (1.0 / n_control + 1.0 / n_treatment)) AS mde_80
FROM se
ORDER BY metric;


-- @query 4_segment_retention ---------------------------------------------------
-- D7 retention by 14-day rounds bucket. Rounds are measured AFTER assignment,
-- so the gate can move players between buckets: read as description, not as
-- causal effects. Only query 3 is a clean experimental comparison.
WITH seg AS (
  SELECT
    version,
    retention_7,
    CASE
      WHEN sum_gamerounds = 0   THEN 1
      WHEN sum_gamerounds < 30  THEN 2
      WHEN sum_gamerounds < 40  THEN 3
      WHEN sum_gamerounds < 100 THEN 4
      ELSE 5
    END AS segment_order
  FROM `your_project.your_dataset.cookie_cats`
),
agg AS (
  SELECT
    segment_order,
    COUNTIF(version = 'gate_30')                  AS n_control,
    COUNTIF(version = 'gate_30' AND retention_7)  AS x_control,
    COUNTIF(version = 'gate_40')                  AS n_treatment,
    COUNTIF(version = 'gate_40' AND retention_7)  AS x_treatment
  FROM seg
  GROUP BY segment_order
),
rates AS (
  SELECT
    *,
    SAFE_DIVIDE(x_control, n_control)                             AS rate_control,
    SAFE_DIVIDE(x_treatment, n_treatment)                         AS rate_treatment,
    SAFE_DIVIDE(x_control + x_treatment, n_control + n_treatment) AS rate_pooled
  FROM agg
)
SELECT
  CASE segment_order
    WHEN 1 THEN '0 rounds' WHEN 2 THEN '1-29' WHEN 3 THEN '30-39'
    WHEN 4 THEN '40-99' ELSE '100+'
  END                                                         AS segment,
  n_control,
  n_treatment,
  SAFE_DIVIDE(n_control, SUM(n_control) OVER ())              AS share_of_control,
  SAFE_DIVIDE(n_treatment, SUM(n_treatment) OVER ())          AS share_of_treatment,
  rate_control,
  rate_treatment,
  rate_control - rate_treatment                               AS diff,
  two_sided_p((rate_control - rate_treatment)
    / SQRT(rate_pooled * (1 - rate_pooled) * (1.0 / n_control + 1.0 / n_treatment))) AS p_value
FROM rates
ORDER BY segment_order;


-- @query 5_engagement_distribution ---------------------------------------------
-- Exact percentiles of 14-day rounds by variant. The mean is sensitive to the
-- extreme tail (one player logs ~50k rounds), so medians and percentiles lead.
WITH pct AS (
  SELECT DISTINCT
    version,
    PERCENTILE_CONT(sum_gamerounds, 0.50) OVER (PARTITION BY version) AS median,
    PERCENTILE_CONT(sum_gamerounds, 0.75) OVER (PARTITION BY version) AS p75,
    PERCENTILE_CONT(sum_gamerounds, 0.90) OVER (PARTITION BY version) AS p90,
    PERCENTILE_CONT(sum_gamerounds, 0.99) OVER (PARTITION BY version) AS p99
  FROM `your_project.your_dataset.cookie_cats`
)
SELECT
  a.version,
  a.players,
  a.mean_rounds,
  a.mean_rounds_excl_outliers,
  p.median, p.p75, p.p90, p.p99,
  a.max_rounds
FROM (
  SELECT
    version,
    COUNT(*)                                          AS players,
    AVG(sum_gamerounds)                               AS mean_rounds,
    AVG(IF(sum_gamerounds <= 10000, sum_gamerounds, NULL)) AS mean_rounds_excl_outliers,
    MAX(sum_gamerounds)                               AS max_rounds
  FROM `your_project.your_dataset.cookie_cats`
  GROUP BY version
) AS a
JOIN pct AS p USING (version)
ORDER BY a.version;


-- @query 6_rounds_survival_curve ------------------------------------------------
-- Share of each variant that played at least N rounds, N = 0..120.
-- Feed this to any BI line chart; a gap opening after N = 30 would show the
-- earlier gate pushing players out.
SELECT
  n AS rounds_at_least,
  version,
  SAFE_DIVIDE(COUNTIF(sum_gamerounds >= n), COUNT(*)) AS share_of_players
FROM `your_project.your_dataset.cookie_cats`
CROSS JOIN UNNEST(GENERATE_ARRAY(0, 120)) AS n
GROUP BY n, version
ORDER BY n, version;
