"""Render the session-3.2 figures from benchmark_search.py's JSON.

    uv run --with matplotlib --with seaborn python scripts/plot_search.py \\
        results/search-amd-v1.json --out docs/figures
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
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
    ax.legend(loc="lower right")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
