"""Render the session-3.4 EnterpriseRAG-Bench figures.

    uv run --with matplotlib --with seaborn python bench/plot_bench.py \\
        results/erb-amd-v1.json --out docs/figures
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
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"],
    "axes.spines.top": False, "axes.spines.right": False,
}

TYPE_LABELS = {
    "basic": "basic (single doc)",
    "semantic": "semantic (low keyword overlap)",
    "intra_document_reasoning": "intra-document reasoning",
    "project_related": "project related (multi-doc)",
    "constrained": "constrained",
    "conflicting_info": "conflicting info",
    "completeness": "completeness (all docs)",
    "miscellaneous": "miscellaneous",
}


def save(fig, out: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(out / name, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}")


def fig_per_type(data, out: Path) -> None:
    items = sorted(data["per_type"].items(),
                   key=lambda kv: -kv[1]["document_recall"])
    labels = [f"{TYPE_LABELS.get(k, k)}  (n={v['n_scored']})"
              for k, v in items]
    recall = [v["document_recall"] for _, v in items]
    full = [v["full_recall_rate"] for _, v in items]
    y = np.arange(len(items))[::-1]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.barh(y + 0.19, recall, height=0.36, color=BLUE,
            edgecolor=SURFACE, label="document recall (partial credit)")
    ax.barh(y - 0.19, full, height=0.36, color=ORANGE,
            edgecolor=SURFACE, label="full-recall rate (all gold docs)")
    for yi, r in zip(y, recall):
        ax.annotate(f"{r:.2f}", (r, yi + 0.19), xytext=(4, 0),
                    textcoords="offset points", va="center",
                    fontsize=7.5, color=INK2)
    overall = data["overall"]["document_recall"]
    ax.axvline(overall, color=AQUA, linewidth=1.4, linestyle="--")
    ax.annotate(f"overall {overall:.3f}", (overall, len(items) - 0.4),
                xytext=(6, 0), textcoords="offset points",
                fontsize=8.5, color=AQUA)
    ax.set_yticks(y, labels)
    ax.set_xlim(0, 0.62)
    ax.set_xlabel("share of gold documents retrieved (top-10 documents)")
    ax.set_title("EnterpriseRAG-Bench, 512K docs — e5-small on €65/month of Hetzner")
    ax.legend(loc="lower right")
    ax.grid(axis="y", visible=False)
    save(fig, out, "erb_per_type.png")


def fig_latency_wall(data, out: Path) -> None:
    """The scale wall: measured hybrid latency at 20K (session 3.2) vs
    1.6M chunks (this run), split by arm."""
    rows = [
        ("vector arm, 20K chunks", 2.7, BLUE),
        ("vector arm, 1.6M chunks", 139, BLUE),
        ("lexical arm, 1.6M chunks", 6900, ORANGE),
        ("full question (hybrid), 1.6M", data["p50_ms"], AQUA),
    ]
    y = np.arange(len(rows))[::-1]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    bars = ax.barh(y, [r[1] for r in rows], height=0.55,
                   color=[r[2] for r in rows], edgecolor=SURFACE)
    for bar, (label, v, _) in zip(bars, rows):
        text = f"{v / 1000:.1f}s" if v >= 1000 else f"{v:.0f}ms"
        ax.annotate(text, (v, bar.get_y() + bar.get_height() / 2),
                    xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=INK2)
    ax.set_yticks(y, [r[0] for r in rows])
    ax.set_xscale("log")
    ax.set_xlabel("p50 latency, log scale (ms)")
    ax.set_title("The scale wall is lexical ranking, not the vector index")
    ax.grid(axis="y", visible=False)
    save(fig, out, "erb_latency_wall.png")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("results")
    p.add_argument("--out", default="docs/figures")
    a = p.parse_args()
    data = json.loads(Path(a.results).read_text())
    ms = sorted(r["ms"] for r in data["rows"])
    data["p50_ms"] = ms[len(ms) // 2]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", rc=RC)
    print(f"figures -> {out}/")
    fig_per_type(data, out)
    fig_latency_wall(data, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
