"""Execute the Cookie Cats analysis cells and write an executed .ipynb.

No Jupyter kernel is installed here, so this runs each code cell in one shared
namespace, captures stdout, the value of a trailing expression, and every
matplotlib figure, and writes them as standard nbformat-4 outputs.

usage: python tools/build_notebook.py <repo_root> [narrative.json]
  e.g. python tools/build_notebook.py . narrative.json
"""
import ast
import base64
import contextlib
import io
import json
import os
import re
import sys
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = os.path.abspath(sys.argv[1])
NARRATIVE = sys.argv[2] if len(sys.argv) > 2 else "-"

# --------------------------------------------------------------------------
# Notebook cells. ("md", key) cells take their text from the narrative file so
# prose is written after the numbers exist; ("code", src) cells are executed.
# --------------------------------------------------------------------------
CELLS = [
    ("md", "title"),
    ("code", '''\
import sys, json
sys.path.insert(0, "src")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import cookiecats as cc

DATA_PATH = "data/cookie_cats.csv"   # Kaggle / DataCamp "Cookie Cats" file
SEED = 42
OUTLIER_CAP = 10_000                 # rounds in 14 days; above this is not human play

# Chart style: two fixed series colours, recessive grid, text in ink colours.
COLORS = {cc.CONTROL: "#2a78d6", cc.TREATMENT: "#eb6834"}
NEUTRAL = "#6250d6"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
    "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 1,
    "xtick.color": MUTED, "ytick.color": MUTED, "ytick.left": False,
    "text.color": INK, "font.size": 10.5, "axes.titlesize": 11.5,
    "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False, "lines.linewidth": 2, "lines.solid_capstyle": "round",
})
pd.set_option("display.width", 120)
print("pandas", pd.__version__, "| numpy", np.__version__)
'''),
    ("md", "s1_data"),
    ("code", '''\
df = cc.load(DATA_PATH)
checks = cc.validate(df)
print(json.dumps(checks, indent=2))
'''),
    ("code", '''\
df.head()
'''),
    ("md", "s2_srm"),
    ("code", '''\
srm = cc.srm_test(checks["versions"][cc.CONTROL], checks["versions"][cc.TREATMENT])
print(f"gate_30: {srm['n_control']:,}  gate_40: {srm['n_treatment']:,}  "
      f"control share {srm['control_share']:.3%}")
print(f"chi-square = {srm['chi2']:.2f}, p = {srm['p_value']:.4f} (against an intended 50/50 split)")
'''),
    ("md", "s3_retention"),
    ("code", '''\
results = {m: cc.compare_metric(df, m) for m in cc.METRICS}

def fmt_row(name, r):
    return {
        "metric": name,
        "gate_30": f"{r['rate_control']:.2%}",
        "gate_40": f"{r['rate_treatment']:.2%}",
        "gap (pp, 30 minus 40)": f"{100*r['diff']:+.2f}",
        "95% CI (pp)": f"[{100*r['ci_low']:+.2f}, {100*r['ci_high']:+.2f}]",
        "gate_40 vs gate_30": f"{r['relative_change_treatment_vs_control']:+.1%}",
        "z": f"{r['z']:.2f}",
        "p-value": f"{r['p_value']:.4f}",
    }

retention_table = pd.DataFrame([fmt_row(cc.METRICS[m], r) for m, r in results.items()]).set_index("metric")
retention_table
'''),
    ("code", '''\
# fig: 01_retention_by_variant
fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [1.25, 1]})

# Left: rates by variant, from a zero baseline, Wilson 95% intervals.
ax = axes[0]
labels = list(cc.METRICS.values())
x = np.arange(len(labels))
w = 0.34
for i, v in enumerate([cc.CONTROL, cc.TREATMENT]):
    rates, lo, hi = [], [], []
    for m in cc.METRICS:
        r = results[m]
        k = "control" if v == cc.CONTROL else "treatment"
        a, b = cc.rate_ci(r[f"x_{k}"], r[f"n_{k}"])
        rates.append(r[f"rate_{k}"]); lo.append(r[f"rate_{k}"] - a); hi.append(b - r[f"rate_{k}"])
    xs = x + (i - 0.5) * (w + 0.02)
    ax.bar(xs, rates, width=w, color=COLORS[v], label=v, zorder=2)
    ax.errorbar(xs, rates, yerr=[lo, hi], fmt="none", ecolor=INK2, elinewidth=1, capsize=3, zorder=3)
    for xx, rr in zip(xs, rates):
        ax.text(xx, rr + 0.012, f"{rr:.1%}", ha="center", va="bottom", fontsize=9.5, color=INK)
ax.set_xticks(x, labels)
ax.set_ylim(0, 0.62)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
ax.set_title("Retention by variant")
ax.legend(loc="upper right", ncols=2)
ax.tick_params(axis="x", colors=INK2, length=0)

# Right: the gap with its 95% CI, against zero.
ax = axes[1]
for j, m in enumerate(cc.METRICS):
    r = results[m]
    y = len(cc.METRICS) - 1 - j
    ax.plot([100*r["ci_low"], 100*r["ci_high"]], [y, y], color=NEUTRAL, lw=2, zorder=2)
    ax.scatter([100*r["diff"]], [y], s=64, color=NEUTRAL, edgecolor="#fcfcfb", linewidth=2, zorder=3)
    ax.text(100*r["ci_high"] + 0.06, y, f"{100*r['diff']:+.2f} pp", va="center", fontsize=9.5, color=INK)
ax.axvline(0, color=INK2, lw=1)
ax.set_yticks(range(len(cc.METRICS)), list(reversed(labels)))
ax.set_ylim(-0.7, len(cc.METRICS) - 0.3)
lo_ = min(0, min(100*r["ci_low"] for r in results.values()))
hi_ = max(0, max(100*r["ci_high"] for r in results.values()))
ax.set_xlim(lo_ - 0.4, hi_ + 0.9)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.tick_params(axis="y", colors=INK2, length=0)
ax.set_xlabel("gate_30 minus gate_40 (pp, 95% CI)")
ax.set_title("Gap in favour of gate_30")
fig.tight_layout()
plt.show()
'''),
    ("md", "s3b_srm_sensitivity"),
    ("code", '''\
# How far could the 50/50 imbalance move the primary result?
r7 = results["retention_7"]
sens = cc.srm_sensitivity(r7["x_control"], r7["n_control"], r7["x_treatment"], r7["n_treatment"])
scenarios = {"as observed": r7,
             "extras typical, dropped": sens["typical_extras_dropped"],
             "worst case: extras dropped": sens["worst_extras_dropped"],
             "worst case: missing added": sens["worst_missing_added"]}
print(f"imbalance: {sens['excess_players']} players; gap loses significance only if at least "
      f"{sens['breakeven_non_retained']} of them ({sens['breakeven_share']:.1%}) were non-retained "
      f"(typical gate_40 non-retained share: {sens['typical_non_retained_share']:.1%})")
pd.DataFrame({k: {"gate_30": f"{r['rate_control']:.2%}", "gate_40": f"{r['rate_treatment']:.2%}",
                  "gap (pp)": f"{100*r['diff']:+.2f}",
                  "95% CI (pp)": f"[{100*r['ci_low']:+.2f}, {100*r['ci_high']:+.2f}]",
                  "p-value": f"{r['p_value']:.4f}"} for k, r in scenarios.items()}).T
'''),
    ("code", '''\
# The same retention tests without the one player above the outlier cap.
df_capped = df[df["sum_gamerounds"] <= OUTLIER_CAP]
results_capped = {m: cc.compare_metric(df_capped, m) for m in cc.METRICS}
pd.DataFrame([fmt_row(cc.METRICS[m], r) for m, r in results_capped.items()]).set_index("metric")
'''),
    ("md", "s4_bootstrap"),
    ("code", '''\
boot = {m: cc.bootstrap_diff(r["x_control"], r["n_control"], r["x_treatment"], r["n_treatment"],
                             n_boot=10_000, seed=SEED)
        for m, r in results.items()}
boot_summary = {cc.METRICS[m]: cc.summarise_bootstrap(d) for m, d in boot.items()}
pd.DataFrame({
    k: {"mean gap (pp)": f"{100*s['mean']:+.2f}",
        "95% interval (pp)": f"[{100*s['ci_low']:+.2f}, {100*s['ci_high']:+.2f}]",
        "P(gate_30 retains better)": f"{s['prob_control_better']:.1%}"}
    for k, s in boot_summary.items()
}).T
'''),
    ("code", '''\
# fig: 02_bootstrap_gap
fig, axes = plt.subplots(1, 2, figsize=(10, 3.2), sharey=False)
for ax, (m, d) in zip(axes, boot.items()):
    s = boot_summary[cc.METRICS[m]]
    ax.hist(100*d, bins=60, color=NEUTRAL, alpha=0.85, edgecolor="#fcfcfb", linewidth=0.5, zorder=2)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_title(f"{cc.METRICS[m]}: P(gate_30 better) = {s['prob_control_better']:.1%}")
    ax.set_xlabel("bootstrap gap, gate_30 minus gate_40 (pp)")
    ax.set_yticks([])
    ax.grid(False)
fig.tight_layout()
plt.show()
'''),
    ("md", "s5_power"),
    ("code", '''\
power_rows = []
for m, r in results.items():
    base = r["rate_treatment"]          # gate_40 is the arm being judged
    mde_ = cc.mde(base, r["n_control"], r["n_treatment"])
    power_rows.append({
        "metric": cc.METRICS[m],
        "baseline": f"{base:.2%}",
        "MDE at 80% power (pp)": f"{100*mde_:.2f}",
        "observed gap (pp)": f"{100*r['diff']:+.2f}",
        "power for observed gap": f"{cc.power_for(r['diff'], base, r['n_control'], r['n_treatment']):.0%}",
        "players per arm for 80% power": f"{cc.n_per_arm(base, abs(r['diff'])):,}",
    })
power_table = pd.DataFrame(power_rows).set_index("metric")
power_table
'''),
    ("md", "s6_engagement"),
    ("code", '''\
cc.rounds_summary(df).round(1)
'''),
    ("code", '''\
rt_all = cc.rounds_test(df)
rt_cap = cc.rounds_test(df, cap=OUTLIER_CAP)
for name, rt in [("all players", rt_all), (f"rounds <= {OUTLIER_CAP:,}", rt_cap)]:
    print(f"{name:>18}: dropped {rt['players_dropped']}, mean {rt['mean_control']:.1f} vs {rt['mean_treatment']:.1f}, "
          f"Mann-Whitney p = {rt['p_value']:.3f}, P(gate_30 player plays more) = {rt['prob_control_plays_more']:.3f}")
'''),
    ("code", '''\
# fig: 03_rounds_survival
# Share of players who played at least N rounds in their first 14 days.
N = np.arange(0, 121)
fig, ax = plt.subplots(figsize=(10, 3.6))
for v in [cc.CONTROL, cc.TREATMENT]:
    r = np.sort(df.loc[df["version"] == v, "sum_gamerounds"].to_numpy())
    still = 1 - np.searchsorted(r, N, side="left") / len(r)
    ax.plot(N, still, color=COLORS[v], label=v)
for g, ha, dx in ((30, "right", -1), (40, "left", 1)):
    ax.axvline(g, color=MUTED, lw=1, zorder=0)
    ax.text(g + dx, 0.93, f"{g} rounds", color=INK2, fontsize=9, ha=ha)
ax.set_ylim(0, 1)
ax.set_xlim(0, 120)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
ax.set_xlabel("game rounds played in first 14 days (N)")
ax.set_title("Share of players reaching at least N rounds")
ax.legend(loc="upper right")
fig.tight_layout()
plt.show()
'''),
    ("md", "s7_segments"),
    ("code", '''\
seg7 = cc.segment_table(df, "retention_7")
seg1 = cc.segment_table(df, "retention_1")
mix = cc.mix_shift_test(df)
print(f"Did the gate change how far players got? chi-square = {mix['chi2']:.1f}, "
      f"dof = {mix['dof']}, p = {mix['p_value']:.4f}")
show = seg7.assign(
    **{"share of gate_30": seg7.share_control.map("{:.1%}".format),
       "share of gate_40": seg7.share_treatment.map("{:.1%}".format),
       "D7 gate_30": seg7.rate_control.map("{:.1%}".format),
       "D7 gate_40": seg7.rate_treatment.map("{:.1%}".format),
       "gap (pp)": (100*seg7["diff"]).map("{:+.2f}".format),
       "95% CI (pp)": [f"[{100*a:+.2f}, {100*b:+.2f}]" for a, b in zip(seg7.ci_low, seg7.ci_high)],
       "p-value": seg7.p_value.map("{:.4f}".format)}
)
show.set_index("segment")[["players_control", "players_treatment", "share of gate_30", "share of gate_40",
                           "D7 gate_30", "D7 gate_40", "gap (pp)", "95% CI (pp)", "p-value"]]
'''),
    ("code", '''\
# fig: 04_d7_by_engagement_bucket
fig, ax = plt.subplots(figsize=(10, 3.6))
y = np.arange(len(seg7))[::-1]
for v, col, off in [(cc.CONTROL, "rate_control", 0.14), (cc.TREATMENT, "rate_treatment", -0.14)]:
    ax.scatter(seg7[col], y + off, s=64, color=COLORS[v], edgecolor="#fcfcfb", linewidth=2, zorder=3, label=v)
for yy, a, b in zip(y, seg7.rate_control, seg7.rate_treatment):
    ax.plot([a, b], [yy + 0.14, yy - 0.14], color=GRID, lw=1, zorder=1)
ax.set_yticks(y, seg7.segment)
ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
ax.set_xlim(0, 1)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.tick_params(axis="y", colors=INK2, length=0)
ax.set_xlabel("D7 retention")
ax.set_ylabel("rounds in first 14 days")
ax.set_title("D7 retention by engagement bucket (descriptive: buckets are post-treatment)")
ax.legend(loc="lower right")
fig.tight_layout()
plt.show()
'''),
    ("md", "s8_save"),
    ("code", '''\
import os
os.makedirs("out", exist_ok=True)

def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    return o

facts = clean({
    "checks": checks,
    "srm": srm,
    "results": results,
    "bootstrap": boot_summary,
    "power": {cc.METRICS[m]: {
        "mde": cc.mde(r["rate_treatment"], r["n_control"], r["n_treatment"]),
        "power_observed": cc.power_for(r["diff"], r["rate_treatment"], r["n_control"], r["n_treatment"]),
        "n_per_arm_for_observed": cc.n_per_arm(r["rate_treatment"], abs(r["diff"]))}
        for m, r in results.items()},
    "srm_sensitivity_d7": sens,
    "results_without_outlier": results_capped,
    "under_30_rounds": {
        "players_control": int(seg7.players_control[:2].sum()),
        "players_treatment": int(seg7.players_treatment[:2].sum()),
        "share_control": float(seg7.share_control[:2].sum()),
        "share_treatment": float(seg7.share_treatment[:2].sum())},
    "per_100k_installs_d7": {
        "players_lost": 100_000 * r7["diff"],
        "players_lost_ci_low": 100_000 * r7["ci_low"],
        "players_lost_ci_high": 100_000 * r7["ci_high"]},
    "next_experiments": {
        "baseline_d7_gate_30": r7["rate_control"],
        "n_per_arm_for_observed_gap": cc.n_per_arm(r7["rate_control"], abs(r7["diff"])),
        "planning_gap_small": 0.005,
        "n_per_arm_for_small_gap": cc.n_per_arm(r7["rate_control"], 0.005)},
    "rounds": {"all": rt_all, "capped": rt_cap,
               "summary": cc.rounds_summary(df).reset_index().to_dict(orient="records")},
    "mix_shift": {k: v for k, v in mix.items() if k != "table"},
    "mix_table": mix["table"].reset_index().astype({"sum_gamerounds": str}).to_dict(orient="records"),
    "segments_d7": seg7.to_dict(orient="records"),
    "segments_d1": seg1.to_dict(orient="records"),
})
with open("out/results.json", "w") as f:
    json.dump(facts, f, indent=2, default=float)
seg7.to_csv("out/segments_d7.csv", index=False)
seg1.to_csv("out/segments_d1.csv", index=False)
print("saved out/results.json, out/segments_d7.csv, out/segments_d1.csv")
'''),
    ("md", "s9_conclusion"),
]

# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------
def to_lines(s):
    return s.splitlines(True)


def run_cell(code, ns, count):
    outputs = []
    tag = re.search(r"#\s*fig:\s*(\S+)", code)
    fig_name = tag.group(1) if tag else f"fig_cell{count}"
    tree = ast.parse(code)
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        exec(compile(tree, f"<cell {count}>", "exec"), ns)
        value = eval(compile(last, f"<cell {count}>", "eval"), ns) if last else None
    if buf.getvalue():
        outputs.append({"output_type": "stream", "name": "stdout", "text": to_lines(buf.getvalue())})
    for num in plt.get_fignums():
        fig = plt.figure(num)
        b = io.BytesIO()
        fig.savefig(b, format="png", dpi=110, bbox_inches="tight")
        outputs.append({"output_type": "display_data", "metadata": {},
                        "data": {"image/png": base64.b64encode(b.getvalue()).decode(),
                                 "text/plain": [f"<Figure size {fig.get_figwidth()*100:.0f}x{fig.get_figheight()*100:.0f}>"]}})
        suffix = "" if len(plt.get_fignums()) == 1 else f"_{num}"
        fig.savefig(os.path.join(REPO, "out", f"{fig_name}{suffix}.png"), dpi=150, bbox_inches="tight")
    plt.close("all")
    if value is not None:
        data = {"text/plain": to_lines(repr(value))}
        if hasattr(value, "_repr_html_"):
            html = value._repr_html_()
            if html:
                data["text/html"] = to_lines(html)
        outputs.append({"output_type": "execute_result", "execution_count": count,
                        "metadata": {}, "data": data})
    return outputs


def main():
    narrative = {}
    if NARRATIVE != "-":
        with open(NARRATIVE) as f:
            narrative = json.load(f)
    os.chdir(REPO)
    os.makedirs("out", exist_ok=True)
    ns = {"__name__": "__main__"}
    cells, count = [], 0
    for kind, body in CELLS:
        if kind == "md":
            text = narrative.get(body, f"## [{body}]\n\n_Narrative pending._")
            cells.append({"cell_type": "markdown", "metadata": {}, "source": to_lines(text)})
            continue
        count += 1
        outs = run_cell(body, ns, count)
        cells.append({"cell_type": "code", "execution_count": count, "metadata": {},
                      "outputs": outs, "source": to_lines(body)})
    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": sys.version.split()[0]},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    for i, c in enumerate(nb["cells"]):
        c["id"] = f"cell-{i:02d}"
    with open("cookie_cats_ab_test.ipynb", "w") as f:
        json.dump(nb, f, indent=1)
    print(f"wrote cookie_cats_ab_test.ipynb ({count} code cells executed)")


if __name__ == "__main__":
    main()
