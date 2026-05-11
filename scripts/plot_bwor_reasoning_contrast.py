# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "matplotlib==3.10.1",
#   "numpy==2.2.3",
# ]
# ///
"""Generate the compact BWOR reasoning-contrast figure (grouped horizontal bar chart).

Run:
    uv run scripts/plot_bwor_reasoning_contrast.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "artifacts" / "BWOR" / "figures" / "bwor_reasoning_contrast.png"

BENCHMARKS = ["IndustryOR", "ComplexLP", "EasyLP", "NL4OPT", "BWOR"]
MODELS = ["GPT-o3", "GPT-o4-mini", "Gemini", "DeepSeek"]
VALUES = np.array(
    [
        [1.00, -5.00, 3.00, -1.00],
        [3.32, 3.32, -7.11, 5.69],
        [-14.11, -1.84, -17.79, -8.28],
        [5.31, 6.53, -4.90, -1.63],
        [35.37, 32.93, 21.95, 10.97],
    ]
)


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.5,
            "axes.labelsize": 7.8,
            "xtick.labelsize": 7.0,
            "ytick.labelsize": 7.2,
        }
    )

    n_benchmarks = len(BENCHMARKS)
    n_models = len(MODELS)
    bar_height = 0.17
    group_gap = 0.12
    group_height = n_models * bar_height + group_gap

    fig_height = n_benchmarks * group_height + 0.35
    fig, ax = plt.subplots(figsize=(3.35, fig_height), dpi=360)

    colors = ["#4C78A8", "#59A14F", "#E15759", "#B07AA1"]
    hatches = ["//", "\\\\", "xx", ".."]

    y_centers = []
    for i in range(n_benchmarks):
        center = (n_benchmarks - 1 - i) * group_height
        y_centers.append(center)
        for j in range(n_models):
            y = center + (n_models / 2 - 0.5 - j) * bar_height
            val = VALUES[i, j]
            is_bwor = BENCHMARKS[i] == "BWOR"
            ax.barh(
                y,
                val,
                height=bar_height * 0.88,
                color=colors[j],
                edgecolor="#333333",
                linewidth=0.4,
                hatch=hatches[j],
                alpha=1.0 if is_bwor else 0.75,
                label=MODELS[j] if i == 0 else None,
                zorder=2,
            )

    ax.axvline(0, color="#404040", linewidth=0.8, zorder=1)

    ax.set_yticks(y_centers)
    ax.set_yticklabels(BENCHMARKS)
    for label in ax.get_yticklabels():
        if label.get_text() == "BWOR":
            label.set_fontweight("bold")

    ax.set_xlabel("Reasoning − Non-reasoning Accuracy (pp)", labelpad=2)
    ax.set_xlim(-22, 40)
    ax.set_xticks([-20, -10, 0, 10, 20, 30, 40])
    ax.grid(axis="x", color="#E8EAED", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.spines[["top", "right", "left"]].set_visible(False)

    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.0),
        ncol=4,
        frameon=False,
        columnspacing=0.7,
        handletextpad=0.3,
        fontsize=6.5,
        handlelength=1.2,
    )

    plt.tight_layout(pad=0.15)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PATH, bbox_inches="tight", pad_inches=0.02, facecolor="white")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
