"""Cookie Cats A/B test: analysis helpers.

Experiment: Tactile Entertainment moved the first progression gate in Cookie Cats
from level 30 (control, `gate_30`) to level 40 (treatment, `gate_40`).
Data: one row per player who installed during the test window.

    userid          unique player id
    version         gate_30 | gate_40
    sum_gamerounds  game rounds played in the first 14 days after install
    retention_1     came back 1 day after install
    retention_7     came back 7 days after install

Every function here is pure, with no I/O except `load`, so the notebook and the
report call the same code.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

EXPECTED_COLUMNS = ["userid", "version", "sum_gamerounds", "retention_1", "retention_7"]
CONTROL, TREATMENT = "gate_30", "gate_40"
METRICS = {"retention_1": "D1 retention", "retention_7": "D7 retention"}


# ----------------------------------------------------------------------------
# Load and validate
# ----------------------------------------------------------------------------
def _to_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    mapped = s.astype(str).str.strip().str.lower().map(
        {"true": True, "false": False, "1": True, "0": False}
    )
    if mapped.isna().any():
        bad = s[mapped.isna()].unique()[:5]
        raise ValueError(f"Unparseable boolean values: {bad}")
    return mapped.astype(bool)


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    df = df[EXPECTED_COLUMNS].copy()
    for c in METRICS:
        df[c] = _to_bool(df[c])
    df["sum_gamerounds"] = df["sum_gamerounds"].astype(int)
    df["version"] = df["version"].astype(str).str.strip()
    return df


def validate(df: pd.DataFrame) -> dict:
    """Integrity checks a reviewer would ask for before trusting any result."""
    v = df["version"].value_counts().to_dict()
    r = df["sum_gamerounds"]
    return {
        "rows": int(len(df)),
        "columns": list(df.columns),
        "duplicate_userids": int(df["userid"].duplicated().sum()),
        "null_cells": int(df.isna().sum().sum()),
        "versions": {k: int(n) for k, n in v.items()},
        "unexpected_versions": sorted(set(v) - {CONTROL, TREATMENT}),
        "rounds_min": int(r.min()),
        "rounds_max": int(r.max()),
        "zero_round_players": int((r == 0).sum()),
        "zero_round_retained_d1": int((df["retention_1"] & (r == 0)).sum()),
        "zero_round_retained_d7": int((df["retention_7"] & (r == 0)).sum()),
        "d7_without_d1": int((df["retention_7"] & ~df["retention_1"]).sum()),
    }


# ----------------------------------------------------------------------------
# Sample ratio mismatch
# ----------------------------------------------------------------------------
def srm_test(n_control: int, n_treatment: int, expected_share: float = 0.5) -> dict:
    """Chi-square goodness-of-fit against the intended split.

    A small p-value means assignment or logging did not behave as designed,
    and every downstream comparison needs that caveat.
    """
    n = n_control + n_treatment
    expected = np.array([n * expected_share, n * (1 - expected_share)])
    observed = np.array([n_control, n_treatment])
    chi2, p = stats.chisquare(observed, expected)
    return {
        "n_control": int(n_control),
        "n_treatment": int(n_treatment),
        "control_share": n_control / n,
        "chi2": float(chi2),
        "p_value": float(p),
    }


# ----------------------------------------------------------------------------
# Two-proportion comparison
# ----------------------------------------------------------------------------
def two_proportion(x_c: int, n_c: int, x_t: int, n_t: int, alpha: float = 0.05) -> dict:
    """Control minus treatment, in proportions.

    z-test uses the pooled SE (null of no difference); the CI uses the unpooled
    SE (Wald), which is accurate at these sample sizes.
    """
    p_c, p_t = x_c / n_c, x_t / n_t
    diff = p_c - p_t
    p_pool = (x_c + x_t) / (n_c + n_t)
    se_pool = np.sqrt(p_pool * (1 - p_pool) * (1 / n_c + 1 / n_t))
    z = diff / se_pool
    p_value = 2 * stats.norm.sf(abs(z))
    se = np.sqrt(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)
    zc = stats.norm.ppf(1 - alpha / 2)
    return {
        "n_control": int(n_c), "n_treatment": int(n_t),
        "x_control": int(x_c), "x_treatment": int(x_t),
        "rate_control": p_c, "rate_treatment": p_t,
        "diff": diff, "ci_low": diff - zc * se, "ci_high": diff + zc * se,
        "relative_change_treatment_vs_control": (p_t - p_c) / p_c,
        "z": float(z), "p_value": float(p_value),
    }


def srm_sensitivity(x_c: int, n_c: int, x_t: int, n_t: int, alpha: float = 0.05) -> dict:
    """How far could the sample imbalance move the comparison?

    Assumes treatment is the larger arm and control has the higher rate, so the
    worst cases below all shrink the gap. The `excess` players are treated as
    extra in treatment, or as missing from control.

    worst_extras_dropped: drop `excess` treatment players, none of them retained.
    worst_missing_added:  add `excess` control players, none of them retained.
    typical_extras_dropped: drop `excess` treatment players retained at that arm's rate.
    breakeven_*: how many of the dropped players must be non-retained before
    the gap stops being significant.
    """
    excess = n_t - n_c
    breakeven = None
    for k in range(excess + 1):
        if two_proportion(x_c, n_c, x_t - (excess - k), n_t - excess)["p_value"] >= alpha:
            breakeven = k
            break
    return {
        "excess_players": int(excess),
        "worst_extras_dropped": two_proportion(x_c, n_c, x_t, n_t - excess),
        "worst_missing_added": two_proportion(x_c, n_c + excess, x_t, n_t),
        "typical_extras_dropped": two_proportion(x_c, n_c, round(x_t * (n_t - excess) / n_t), n_t - excess),
        "breakeven_non_retained": breakeven,
        "breakeven_share": None if breakeven is None else breakeven / excess,
        "typical_non_retained_share": 1 - x_t / n_t,
    }


def rate_ci(x: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson interval for a single rate (used for chart error bars)."""
    z = stats.norm.ppf(1 - alpha / 2)
    p = x / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return centre - half, centre + half


def compare_metric(df: pd.DataFrame, metric: str) -> dict:
    g = df.groupby("version")[metric].agg(["sum", "count"])
    return two_proportion(
        int(g.loc[CONTROL, "sum"]), int(g.loc[CONTROL, "count"]),
        int(g.loc[TREATMENT, "sum"]), int(g.loc[TREATMENT, "count"]),
    )


# ----------------------------------------------------------------------------
# Bootstrap
# ----------------------------------------------------------------------------
def bootstrap_diff(x_c: int, n_c: int, x_t: int, n_t: int,
                   n_boot: int = 10_000, seed: int = 42) -> np.ndarray:
    """Bootstrap distribution of (control rate - treatment rate).

    Resampling n rows with replacement from a 0/1 column is the same as drawing
    Binomial(n, observed rate), so this is the ordinary row bootstrap without
    materialising 90k-row samples 10,000 times.
    """
    rng = np.random.default_rng(seed)
    bc = rng.binomial(n_c, x_c / n_c, n_boot) / n_c
    bt = rng.binomial(n_t, x_t / n_t, n_boot) / n_t
    return bc - bt


def summarise_bootstrap(d: np.ndarray) -> dict:
    lo, hi = np.percentile(d, [2.5, 97.5])
    return {
        "mean": float(d.mean()), "ci_low": float(lo), "ci_high": float(hi),
        "prob_control_better": float((d > 0).mean()),
    }


# ----------------------------------------------------------------------------
# Power and minimum detectable effect
# ----------------------------------------------------------------------------
def mde(p: float, n_c: int, n_t: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest absolute difference detectable with the given power."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return float(z * np.sqrt(p * (1 - p) * (1 / n_c + 1 / n_t)))


def power_for(effect: float, p: float, n_c: int, n_t: int, alpha: float = 0.05) -> float:
    """Two-sided power to detect an absolute difference `effect`."""
    se = np.sqrt(p * (1 - p) * (1 / n_c + 1 / n_t))
    zc = stats.norm.ppf(1 - alpha / 2)
    shift = abs(effect) / se
    return float(stats.norm.sf(zc - shift) + stats.norm.cdf(-zc - shift))


def n_per_arm(p: float, effect: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Players per arm needed to detect `effect` (equal arms)."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return int(np.ceil(2 * p * (1 - p) * (z / effect) ** 2))


# ----------------------------------------------------------------------------
# Engagement (sum_gamerounds)
# ----------------------------------------------------------------------------
def rounds_summary(df: pd.DataFrame) -> pd.DataFrame:
    q = df.groupby("version")["sum_gamerounds"]
    out = pd.DataFrame({
        "players": q.size(),
        "mean": q.mean(),
        "median": q.median(),
        "p75": q.quantile(0.75),
        "p90": q.quantile(0.90),
        "p99": q.quantile(0.99),
        "max": q.max(),
    })
    return out.loc[[CONTROL, TREATMENT]]


def rounds_test(df: pd.DataFrame, cap: int | None = None) -> dict:
    """Mann-Whitney U on rounds (rank-based, so robust to the extreme tail).

    `cap`, if set, drops players above it, to show the outlier does not drive
    the result.
    """
    d = df if cap is None else df[df["sum_gamerounds"] <= cap]
    a = d.loc[d["version"] == CONTROL, "sum_gamerounds"]
    b = d.loc[d["version"] == TREATMENT, "sum_gamerounds"]
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    # Probability a random control player out-plays a random treatment player.
    auc = u / (len(a) * len(b))
    return {"players_dropped": int(len(df) - len(d)), "u": float(u),
            "p_value": float(p), "prob_control_plays_more": float(auc),
            "mean_control": float(a.mean()), "mean_treatment": float(b.mean())}


# ----------------------------------------------------------------------------
# Segments (descriptive)
# ----------------------------------------------------------------------------
SEGMENT_BINS = [-1, 0, 29, 39, 99, np.inf]
SEGMENT_LABELS = ["0 rounds", "1–29", "30–39", "40–99", "100+"]


def segment_table(df: pd.DataFrame, metric: str = "retention_7",
                  bins=SEGMENT_BINS, labels=SEGMENT_LABELS) -> pd.DataFrame:
    """Retention by 14-day rounds bucket and variant.

    Rounds are measured after assignment, so the gate itself can move players
    between buckets. Read these as descriptions, not causal effects; only the
    all-player comparison is a clean experiment.
    """
    seg = pd.cut(df["sum_gamerounds"], bins=bins, labels=labels)
    rows = []
    for label in labels:
        s = df[seg == label]
        g = s.groupby("version")[metric].agg(["sum", "count"])
        if not {CONTROL, TREATMENT} <= set(g.index):
            continue
        r = two_proportion(int(g.loc[CONTROL, "sum"]), int(g.loc[CONTROL, "count"]),
                           int(g.loc[TREATMENT, "sum"]), int(g.loc[TREATMENT, "count"]))
        rows.append({
            "segment": label,
            "players_control": r["n_control"], "players_treatment": r["n_treatment"],
            "share_control": r["n_control"] / int((df["version"] == CONTROL).sum()),
            "share_treatment": r["n_treatment"] / int((df["version"] == TREATMENT).sum()),
            "rate_control": r["rate_control"], "rate_treatment": r["rate_treatment"],
            "diff": r["diff"], "ci_low": r["ci_low"], "ci_high": r["ci_high"],
            "p_value": r["p_value"],
        })
    return pd.DataFrame(rows)


def mix_shift_test(df: pd.DataFrame, bins=SEGMENT_BINS, labels=SEGMENT_LABELS) -> dict:
    """Did the gate change how far players got? Chi-square on bucket x variant."""
    seg = pd.cut(df["sum_gamerounds"], bins=bins, labels=labels)
    table = pd.crosstab(seg, df["version"])[[CONTROL, TREATMENT]]
    chi2, p, dof, _ = stats.chi2_contingency(table)
    return {"chi2": float(chi2), "dof": int(dof), "p_value": float(p),
            "table": table}
