"""Cross-check the BigQuery SQL against the Python results using SQLite.

The SQL file is run as written, with only these mechanical dialect swaps:
COUNTIF(x) -> SUM(CASE WHEN x THEN 1 ELSE 0 END), IF( -> IIF(, and the
BigQuery temp functions are evaluated from their own SQL bodies. Queries 5-6
use BigQuery-only syntax (PERCENTILE_CONT, GENERATE_ARRAY) and are skipped.

usage: python -I test_sql.py <repo_root>
"""
import json
import math
import os
import re
import sqlite3
import sys

import pandas as pd

REPO = os.path.abspath(sys.argv[1])
sys.path.insert(0, os.path.join(REPO, "src"))
import cookiecats as cc  # noqa: E402

sql = open(os.path.join(REPO, "sql", "cookie_cats_bigquery.sql")).read()


def countif(s):
    out, i = [], 0
    while True:
        j = s.find("COUNTIF(", i)
        if j < 0:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:j])
        k, depth = j + len("COUNTIF("), 1
        while depth:
            depth += {"(": 1, ")": -1}.get(s[k], 0)
            k += 1
        out.append(f"SUM(CASE WHEN {countif(s[j + 8:k - 1])} THEN 1 ELSE 0 END)")
        i = k


# --- temp functions, evaluated from their SQL bodies -------------------------
helper = sqlite3.connect(":memory:")
funcs = re.findall(r"CREATE TEMP FUNCTION (\w+)\((\w+) FLOAT64\) AS \((.*?)\);\n", sql, re.S)
for name, param, body in funcs:
    expr = re.sub(rf"\b{param}\b", "?", body).replace("IF(", "IIF(")
    n = expr.count("?")

    def make(expr=expr, n=n):
        return lambda x: helper.execute(f"SELECT {expr}", (x,) * n).fetchone()[0]

    helper.create_function(name, 1, make(), deterministic=True)

ncdf = lambda z: helper.execute("SELECT normal_cdf(?)", (z,)).fetchone()[0]
worst = max(abs(ncdf(z / 100) - cc.stats.norm.cdf(z / 100)) for z in range(-600, 601))
print(f"normal_cdf approximation: max abs error vs scipy over [-6, 6] = {worst:.2e}")

# --- data -------------------------------------------------------------------
df = cc.load(os.path.join(REPO, "data", "cookie_cats.csv"))
con = sqlite3.connect(":memory:")
for name, _, _ in funcs:
    con.create_function(name, 1, lambda x, name=name: helper.execute(f"SELECT {name}(?)", (x,)).fetchone()[0])
con.create_function("SAFE_DIVIDE", 2, lambda a, b: None if not b else a / b)
con.create_function("POW", 2, math.pow)
d = df.copy()
for c in ("retention_1", "retention_7"):
    d[c] = d[c].astype(int)
d.to_sql("your_project.your_dataset.cookie_cats", con, index=False)

blocks = re.split(r"-- @query (\w+) -+\n", sql)
queries = dict(zip(blocks[1::2], blocks[2::2]))
res = {}
for name in ["1_validation", "2_sample_ratio_mismatch", "3_retention_tests", "4_segment_retention"]:
    q = countif(queries[name]).strip().rstrip(";")
    res[name] = pd.read_sql_query(q, con)
    print(f"\n== {name}\n{res[name].to_string()}")

# --- compare with Python ------------------------------------------------------
problems = []
chk = cc.validate(df)
v = res["1_validation"].iloc[0]
for k_sql, k_py in [("row_count", "rows"), ("rounds_max", "rounds_max"), ("rounds_min", "rounds_min"),
                    ("zero_round_players", "zero_round_players"), ("d7_without_d1", "d7_without_d1")]:
    if int(v[k_sql]) != chk[k_py]:
        problems.append(f"validation {k_sql}: {v[k_sql]} vs {chk[k_py]}")
srm_py = cc.srm_test(chk["versions"][cc.CONTROL], chk["versions"][cc.TREATMENT])
s = res["2_sample_ratio_mismatch"].iloc[0]
for k in ("chi2", "p_value"):
    if not math.isclose(s[k], srm_py[k], rel_tol=1e-5, abs_tol=1e-7):
        problems.append(f"srm {k}: {s[k]} vs {srm_py[k]}")
for _, row in res["3_retention_tests"].iterrows():
    m = {"D1 retention": "retention_1", "D7 retention": "retention_7"}[row["metric"]]
    py = cc.compare_metric(df, m)
    for k in ("rate_control", "rate_treatment", "diff", "ci_low", "ci_high", "z", "p_value"):
        if not math.isclose(row[k], py[k], rel_tol=1e-5, abs_tol=1e-6):
            problems.append(f"{m} {k}: {row[k]} vs {py[k]}")
    mde_py = cc.mde(py["rate_treatment"], py["n_control"], py["n_treatment"])
    if not math.isclose(row["mde_80"], mde_py, rel_tol=1e-6):
        problems.append(f"{m} mde: {row['mde_80']} vs {mde_py}")
seg_py = cc.segment_table(df, "retention_7")
for (_, a), (_, b) in zip(res["4_segment_retention"].iterrows(), seg_py.iterrows()):
    for k in ("rate_control", "rate_treatment", "diff", "p_value"):
        if not math.isclose(a[k], b[k], rel_tol=1e-5, abs_tol=1e-6):
            problems.append(f"segment {a['segment']} {k}: {a[k]} vs {b[k]}")

print("\nSQL vs Python:", "ALL MATCH" if not problems else "\n".join(problems))
