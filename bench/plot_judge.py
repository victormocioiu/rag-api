"""Figures for the official ERB judge run (and later the model ladder).

    uv run --with matplotlib --with seaborn python bench/plot_judge.py \\
        results/erb-official-judge-v1.json --out docs/figures
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
    "basic": "basic", "semantic": "semantic",
    "intra_document_reasoning": "intra-doc reasoning",
    "project_related": "project related", "constrained": "constrained",
    "conflicting_info": "conflicting info", "completeness": "completeness",
    "miscellaneous": "miscellaneous", "high_level": "high level",
    "info_not_found": "info not found",
}


def save(fig, out: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(out / name, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}")


def fig_judged_categories(data, out: Path) -> None:
    stats = data["question_type_stats"]
    items = sorted(stats.items(),
                   key=lambda kv: -kv[1]["average_correctness_pct"])
    labels = [f"{TYPE_LABELS.get(k, k)} (n={v['count']})" for k, v in items]
    y = np.arange(len(items))[::-1]
    h = 0.27
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    for off, key, color, label in (
            (h, "average_correctness_pct", BLUE, "correctness"),
            (0, "average_completeness_pct", AQUA, "completeness"),
            (-h, "average_recall_pct", ORANGE, "document recall")):
        vals = [v[key] for _, v in items]
        bars = ax.barh(y + off, vals, height=h, color=color,
                       edgecolor=SURFACE, label=label)
        for bar, v in zip(bars, vals):
            ax.annotate(f"{v:.0f}", (v, bar.get_y() + bar.get_height() / 2),
                        xytext=(3, 0), textcoords="offset points",
                        va="center", fontsize=7, color=INK2)
    ax.set_yticks(y, labels)
    ax.set_xlim(0, 108)
    ax.set_xlabel("official judge score (%)")
    ax.set_title("The judge's verdict, per category — all 500 questions, their protocol")
    ax.legend(loc="upper center", ncols=3, bbox_to_anchor=(0.5, -0.10))
    ax.grid(axis="y", visible=False)
    save(fig, out, "judge_per_category.png")


def fig_overall_leaderboard(data, out: Path) -> None:
    board = [
        ("Troml", 76.79), ("OpenClaw", 68.22), ("OpenAI File Search", 61.03),
        ("RAGFlow", 50.24), ("Amazon Q (Kendra)", 48.96),
        ("Azure AI Search", 48.42), ("Vertex AI Search", 41.87),
        ("NVIDIA AI Blueprints", 37.73), ("AnythingLLM", 35.58),
        ("Weaviate Verba", 34.48),
        ("hRAG (us)", data["aggregate_stats"][
            "combined_correctness_completeness_score"]),
        ("LlamaIndex (defaults)", 27.20), ("LangChain (defaults)", 24.98),
        ("Open WebUI + Chroma", 24.89),
    ]
    board.sort(key=lambda r: -r[1])
    y = np.arange(len(board))[::-1]
    colors = [AQUA if "hRAG" in n else BLUE for n, _ in board]
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    bars = ax.barh(y, [v for _, v in board], height=0.6, color=colors,
                   edgecolor=SURFACE)
    for bar, (name, v) in zip(bars, board):
        ax.annotate(f"{v:.2f}", (v, bar.get_y() + bar.get_height() / 2),
                    xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=7.5,
                    color=INK if "hRAG" in name else INK2)
    ax.set_yticks(y, [n for n, _ in board])
    ax.set_xlabel("Overall Score = avg per-question correctness × completeness")
    ax.set_title("EnterpriseRAG-Bench overall — €116/month vs the industry")
    ax.grid(axis="y", visible=False)
    save(fig, out, "judge_overall_leaderboard.png")


LADDER = [
    ("baseline: mistral-small, 8 chunks", "baseline"),
    ("+ completeness prompt", "complete"),
    ("mistral-small, 16 chunks", "k16"),
    ("gpt-5-mini, 8 chunks", "mini"),
    ("gpt-5.6-luna, 8 chunks", "luna"),
    ("claude-haiku-4.5, 16 chunks", "haiku-k16"),
    ("claude-haiku-4.5, 8 chunks", "haiku"),
]


def fig_ladder(results_dir: Path, out: Path) -> None:
    rows = []
    for label, key in LADDER:
        d = json.loads((results_dir / f"erb-ladder-{key}.json").read_text())
        a = d if "combined" in str(d.keys()) else d.get("aggregate_stats", d)
        overall = a.get("combined_correctness_completeness_score",
                        a.get("overall_combined"))
        rows.append((label, overall))
    rows.sort(key=lambda r: r[1])
    y = np.arange(len(rows))
    best = max(v for _, v in rows)
    colors = [AQUA if v == best else BLUE for _, v in rows]
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    bars = ax.barh(y, [v for _, v in rows], height=0.6, color=colors,
                   edgecolor=SURFACE)
    for bar, (_, v) in zip(bars, rows):
        ax.annotate(f"{v:.2f}", (v, bar.get_y() + bar.get_height() / 2),
                    xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=INK2)
    ax.set_yticks(y, [r[0] for r in rows])
    ax.axvline(rows[[label for label, _ in rows].index(
        "baseline: mistral-small, 8 chunks")][1] if False else
        dict(rows)["baseline: mistral-small, 8 chunks"],
        color=BASELINE, linewidth=1.2, linestyle="--")
    ax.set_xlabel("Overall (avg per-question correctness × completeness), "
                  "100-q stratified slice")
    ax.set_title("The answering-model ladder — one variable per rung")
    ax.grid(axis="y", visible=False)
    save(fig, out, "judge_ladder.png")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("results")
    p.add_argument("--out", default="docs/figures")
    a = p.parse_args()
    data = json.loads(Path(a.results).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", rc=RC)
    fig_judged_categories(data, out)
    fig_overall_leaderboard(data, out)
    fig_ladder(Path("results"), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
