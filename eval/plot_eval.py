"""Render the session-3.3 eval figures from run_eval.py's JSON.

    uv run --with matplotlib --with seaborn python eval/plot_eval.py \\
        results/eval-amd-v1.json --out docs/figures
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"

RC = {
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "figure.dpi": 150,
    "axes.edgecolor": BASELINE, "axes.labelcolor": INK2,
    "axes.titlecolor": INK, "axes.titlesize": 11, "axes.labelsize": 9.5,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
    "legend.fontsize": 8.5, "legend.frameon": False,
    "lines.linewidth": 2, "lines.markersize": 6.5,
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"],
    "axes.spines.top": False, "axes.spines.right": False,
}

CONFIG_LABELS = {
    "eval-base": "base (structural)",
    "eval-token": "token chunking",
    "eval-noheads": "no heading paths",
    "eval-nooverlap": "no overlap",
    "eval-pairs": "tables as pairs",
    "eval-pdf-pypdf": "pdf: pypdf",
    "eval-pdf-hybrid": "pdf: hybrid",
}
VARIANT_LABELS = {
    "hybrid": "hybrid (tsquery arm)",
    "vector": "vector only",
    "lexical": "lexical only (tsquery)",
    "lexical+strip": "tsquery + stopword strip",
    "hybrid+strip": "hybrid + stopword strip",
    "lexical-bm25": "lexical only (BM25)",
    "hybrid-bm25": "hybrid (BM25 arm)",
    "hybrid-bm25-w03": "hybrid (BM25, vector w=0.3)",
}


def save(fig, out: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(out / name, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}")


def grouped_recall_barh(items, title, out, name, note=None):
    """items: list of (label, agg-dict)."""
    metrics = [("recall@1", BLUE), ("recall@3", AQUA), ("recall@8", ORANGE)]
    n = len(items)
    y = np.arange(n)[::-1]
    height = 0.26
    fig, ax = plt.subplots(figsize=(7, 0.62 * n + 1.6))
    for j, (metric, color) in enumerate(metrics):
        vals = [agg[metric] for _, agg in items]
        bars = ax.barh(y + (1 - j) * height, vals, height=height,
                       color=color, edgecolor=SURFACE, linewidth=1,
                       label=metric)
        for bar, v in zip(bars, vals):
            ax.annotate(f"{v:.2f}", (v, bar.get_y() + bar.get_height() / 2),
                        xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=7.5, color=INK2)
    ax.set_yticks(y, [label for label, _ in items])
    ax.set_xlim(0, 1.12)
    ax.set_xlabel("recall (share of queries answered in top k)")
    ax.set_title(title)
    ax.legend(loc="upper center", ncols=3,
              bbox_to_anchor=(0.5, -0.14 - 0.5 / n))
    ax.grid(axis="y", visible=False)
    if note:
        ax.annotate(note, (0.5, -0.34 - 0.9 / n), xycoords="axes fraction",
                    ha="center", fontsize=8, color=MUTED)
    save(fig, out, name)


def fig_configs(data, out: Path) -> None:
    items = [(CONFIG_LABELS.get(k, k), v)
             for k, v in data["configs"].items()]
    grouped_recall_barh(
        items, "Ingest-side ablations — hybrid search, same 104 queries",
        out, "eval_configs.png",
        note="each config = its own tenant; identical corpus re-ingested "
             "with one knob flipped")


def fig_variants(data, out: Path) -> None:
    items = [(VARIANT_LABELS.get(k, k), v)
             for k, v in data["search_variants"].items()]
    grouped_recall_barh(
        items, "Search-side ablations — base ingest config",
        out, "eval_search_variants.png",
        note="query-side only: no re-ingest, no re-embedding")


def fig_per_class(data, out: Path) -> None:
    items = [(f"{cls}  (n={agg['n']})", agg)
             for cls, agg in sorted(data["per_class"].items())]
    grouped_recall_barh(
        items, "Recall by query class — base config, hybrid search",
        out, "eval_per_class.png")


def fig_table_class(data, out: Path) -> None:
    """The table-question story: same 12 queries, four ingest treatments."""
    picks = ["eval-base", "eval-pairs", "eval-token", "eval-noheads"]
    items = []
    for k in picks:
        rows = [r for r in data["configs"][k]["rows"]
                if r["class"] == "table"]
        n = len(rows)
        ranks = [r["rank"] for r in rows]
        items.append((CONFIG_LABELS.get(k, k), {
            "recall@1": sum(1 for r in ranks if r == 1) / n,
            "recall@3": sum(1 for r in ranks if r and r <= 3) / n,
            "recall@8": sum(1 for r in ranks if r and r <= 8) / n,
        }))
    grouped_recall_barh(
        items, "Table questions only (n=12) — same queries, four treatments",
        out, "eval_table_class.png",
        note="token 'wins' by putting the whole 30-row table in one giant "
             "chunk — see the caveat in the docs")


def fig_mrr(data, out: Path) -> None:
    labels, vals = [], []
    for k, v in data["configs"].items():
        labels.append(CONFIG_LABELS.get(k, k))
        vals.append(v["mrr"])
    for k, v in data["search_variants"].items():
        if k == "hybrid":
            continue  # same tenant+mode as eval-base
        labels.append("search: " + VARIANT_LABELS.get(k, k))
        vals.append(v["mrr"])
    y = np.arange(len(labels))[::-1]
    fig, ax = plt.subplots(figsize=(7, 0.42 * len(labels) + 1.4))
    colors = [AQUA if v >= max(vals) - 1e-9 else BLUE for v in vals]
    bars = ax.barh(y, vals, height=0.6, color=colors,
                   edgecolor=SURFACE, linewidth=1)
    for bar, v in zip(bars, vals):
        ax.annotate(f"{v:.3f}", (v, bar.get_y() + bar.get_height() / 2),
                    xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8, color=INK2)
    ax.set_yticks(y, labels)
    ax.set_xlim(0, 1.12)
    ax.set_xlabel("mean reciprocal rank (1.0 = right answer always first)")
    ax.set_title("Every ablation on one axis — MRR")
    ax.grid(axis="y", visible=False)
    save(fig, out, "eval_mrr.png")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("results")
    p.add_argument("--out", default="docs/figures")
    a = p.parse_args()
    data = json.loads(Path(a.results).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", rc=RC)
    print(f"figures -> {out}/")
    fig_configs(data, out)
    fig_variants(data, out)
    fig_per_class(data, out)
    fig_table_class(data, out)
    fig_mrr(data, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
