"""Render the session-3.2 figures from benchmark_search.py's JSON.

    uv run --with matplotlib --with seaborn python scripts/plot_search.py \\
        results/search-amd-v1.json --out docs/figures
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

MODE_STYLE = {
    "vector": {"color": BLUE, "label": "vector (HNSW)"},
    "lexical": {"color": ORANGE, "label": "lexical (GIN, worst-case corpus)"},
    "hybrid": {"color": AQUA, "label": "hybrid (both + RRF)"},
}


def save(fig, out: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(out / name, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}")


def fig_scaling(data, out: Path) -> None:
    rows = data["search"]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for mode, style in MODE_STYLE.items():
        points = [(r["corpus_chunks"], r["db_p50_ms"])
                  for r in rows if r["mode"] == mode]
        xs, ys = zip(*sorted(points))
        ax.plot(xs, ys, marker="o", **style)
        ax.annotate(f'{ys[-1]:.0f}ms', (xs[-1], ys[-1]), xytext=(8, 0),
                    textcoords="offset points", va="center",
                    fontsize=8.5, color=INK2)
    ax.set_xlabel("chunks in the corpus")
    ax.set_ylabel("Postgres search time, p50 (ms)")
    ax.set_title("Search vs corpus size — HNSW is flat, exhaustive ranking is not")
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left")
    save(fig, out, "search_scaling.png")


def fig_split(data, out: Path) -> None:
    rows = [r for r in data["search"]
            if r["corpus_chunks"] == max(x["corpus_chunks"]
                                         for x in data["search"])]
    modes = ["vector", "hybrid", "lexical"]
    by_mode = {r["mode"]: r for r in rows}
    fig, ax = plt.subplots(figsize=(7, 3.2))
    y = range(len(modes))[::-1]
    embed = [by_mode[m]["embed_query_p50_ms"] for m in modes]
    db = [by_mode[m]["db_p50_ms"] for m in modes]
    ax.barh(y, embed, height=0.55, color=BLUE, edgecolor=SURFACE,
            linewidth=2, label="embed the query (rag-embedder)")
    ax.barh(y, db, left=embed, height=0.55, color=ORANGE,
            edgecolor=SURFACE, linewidth=2, label="search (Postgres)")
    for yi, m in zip(y, modes):
        total = by_mode[m]["wall_p50_ms"]
        ax.annotate(f'{total:.0f}ms wall', (embed[modes.index(m)] + db[modes.index(m)], yi),
                    xytext=(8, 0), textcoords="offset points", va="center",
                    fontsize=8.5, color=INK2)
    ax.set_yticks(list(y), modes)
    ax.set_xlabel("p50 per query at 20K chunks (ms)")
    ax.set_title("Where a search request spends its time")
    ax.legend(loc="upper center", ncols=2, bbox_to_anchor=(0.5, -0.28))
    ax.grid(axis="y", visible=False)
    save(fig, out, "search_split.png")


def fig_persist(data, out: Path) -> None:
    rows = data["persist"]
    fig, ax = plt.subplots(figsize=(7, 4.0))
    ax.scatter([r["n_chunks"] for r in rows],
               [r["persist_ms"] for r in rows],
               s=14, color=BLUE, alpha=0.35, edgecolors="none")
    ax.set_xlabel("chunks in the document")
    ax.set_ylabel("persist time (ms) — one transaction per document")
    ax.set_title(f"Persist scaling across {len(rows):,} real documents")
    ax.set_ylim(bottom=0)
    save(fig, out, "persist_scaling.png")


def fig_arms_scale(out: Path) -> None:
    """Every search arm at three real corpus scales (post-BM25 platform)."""
    import json as _json
    rows = _json.loads(Path("results/search-arms-scale-v1.json").read_text())
    arms = ["vector", "lexical-tsquery", "lexical-bm25", "hybrid-bm25-w03"]
    labels = {"vector": "vector (HNSW)", "lexical-tsquery": "tsquery arm",
              "lexical-bm25": "BM25 arm (pg_textsearch)",
              "hybrid-bm25-w03": "hybrid (BM25 + vector, w=0.3)"}
    colors = {"vector": BLUE, "lexical-tsquery": ORANGE,
              "lexical-bm25": AQUA, "hybrid-bm25-w03": INK2}
    scales = [(174, "174 chunks\n(eval tenant)"),
              (20153, "20K chunks\n(worst-case vocab)"),
              (1980726, "2M chunks\n(ERB corpus)")]
    x = np.arange(len(scales))
    width = 0.2
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for i, arm in enumerate(arms):
        vals = []
        for chunks, _ in scales:
            vals.append(next(r["db_p50_ms"] for r in rows
                             if r["chunks"] == chunks and r["arm"] == arm))
        bars = ax.bar(x + (i - 1.5) * width, vals, width,
                      color=colors[arm], edgecolor=SURFACE,
                      label=labels[arm])
        for bar, v in zip(bars, vals):
            text = f"{v / 1000:.1f}s" if v >= 1000 else f"{v:.0f}ms"
            ax.annotate(text, (bar.get_x() + bar.get_width() / 2, v),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=7, color=INK2)
    ax.set_yscale("log")
    ax.set_xticks(x, [s for _, s in scales])
    ax.set_ylabel("Postgres search time, p50 (ms, log scale)")
    ax.set_title("Every arm has a pathology — search latency across corpus scales")
    ax.legend(loc="upper left", ncols=2)
    save(fig, out, "search_arms_scale.png")


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
    fig_scaling(data, out)
    fig_split(data, out)
    fig_persist(data, out)
    fig_arms_scale(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
