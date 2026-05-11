# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "matplotlib==3.10.1",
# ]
# ///
"""Generate the BWOR dataset overview figure from the public JSONL release.

Run:
    uv run scripts/plot_bwor_dataset_overview.py
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = REPO_ROOT / "data" / "datasets" / "bwor.jsonl"
OUTPUT_PATH = REPO_ROOT / "artifacts" / "BWOR" / "figures" / "bwor_dataset_overview.png"

TEAL = "#2F9290"
TEAL_DARK = "#1E6564"
BLUE = "#355C9E"
BLUE_DARK = "#223C72"
GRAY = "#5F6368"
LIGHT_GRAY = "#E8EAED"
PALE = "#F7F9FA"

DOMAIN_LABELS = {
    "production_planning": "Production planning",
    "resource_allocation": "Resource allocation",
    "transportation": "Transportation",
    "scheduling": "Scheduling",
    "inventory": "Inventory",
    "assignment": "Assignment",
    "blending": "Blending",
    "finance": "Finance",
    "network": "Network",
}

TYPE_LABELS = {
    "LP": "LP",
    "IP": "IP",
    "MIP": "MIP",
    "NLP": "NLP",
    "goal_programming": "Goal prog.",
}


def load_records(path: Path) -> list[dict]:
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def normalized_word_count(text: str) -> int:
    text = re.sub(r"\\begin\{[^}]+\}|\\end\{[^}]+\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})?", " ", text)
    text = re.sub(r"[$&_{}^%#|\\\\]", " ", text)
    return len(re.findall(r"[A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)*", text))


def add_panel_label(ax, label: str, title: str) -> None:
    ax.text(
        0.0,
        1.06,
        f"{label} {title}",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=15,
        fontweight="bold",
        color="#202124",
    )


def draw_record_panel(ax, records: list[dict]) -> None:
    ax.set_axis_off()
    add_panel_label(ax, "(a)", "Release record schema")

    record = records[0]
    snippet_lines = [
        "{",
        f'  "id": "{record["id"]}",',
        '  "en_question": "<normalized English statement>",',
        '  "cn_question": "<original Chinese statement>",',
        f'  "answer": {record["answer"]},',
        f'  "solution_status": "{record["solution_status"]}",',
        f'  "domain": "{record["domain"]}",',
        f'  "problem_type": "{record["problem_type"]}",',
        f'  "difficulty": "{record["difficulty"]}"',
        "}",
    ]

    card = FancyBboxPatch(
        (0.01, 0.04),
        0.98,
        0.88,
        boxstyle="round,pad=0.018,rounding_size=0.025",
        linewidth=1.2,
        edgecolor=LIGHT_GRAY,
        facecolor=PALE,
        transform=ax.transAxes,
    )
    ax.add_patch(card)

    ax.text(
        0.05,
        0.86,
        "BWOR public JSONL",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=16,
        fontweight="bold",
        color=BLUE_DARK,
    )
    ax.text(
        0.05,
        0.74,
        "\n".join(snippet_lines),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10.4,
        family="monospace",
        color="#202124",
        linespacing=1.18,
    )

    optimal = sum(1 for r in records if r["solution_status"] == "optimal")
    no_optimal = len(records) - optimal
    ax.text(
        0.05,
        0.11,
        f"{len(records)} bilingual records  |  {optimal} optimal, {no_optimal} no_optimal  |  tolerance = 0.1",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=10.8,
        color=GRAY,
    )


def draw_domain_panel(ax, records: list[dict]) -> None:
    add_panel_label(ax, "(b)", "Domain distribution")
    counts = Counter(r["domain"] for r in records)
    items = sorted(counts.items(), key=lambda kv: (-kv[1], DOMAIN_LABELS.get(kv[0], kv[0])))
    labels = [DOMAIN_LABELS.get(k, k) for k, _ in items]
    values = [v for _, v in items]
    y_pos = list(range(len(items)))

    ax.barh(y_pos, values, color=TEAL, edgecolor=TEAL_DARK, linewidth=0.7)
    ax.set_yticks(y_pos, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Records")
    ax.set_xlim(0, max(values) + 4)
    ax.grid(axis="x", color=LIGHT_GRAY, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)

    total = len(records)
    for y, v in zip(y_pos, values):
        ax.text(v + 0.25, y, f"{v} ({v / total:.0%})", va="center", fontsize=10.5, color="#202124")


def draw_length_panel(ax, records: list[dict]) -> None:
    add_panel_label(ax, "(c)", "English statement length")
    lengths = [normalized_word_count(r["en_question"]) for r in records]
    ax.hist(lengths, bins=12, color=TEAL, edgecolor="white", linewidth=0.9)
    ax.set_xlabel("English words (LaTeX stripped)")
    ax.set_ylabel("Records")
    ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)

    summary = (
        f"n = {len(lengths)}\n"
        f"min = {min(lengths)}\n"
        f"median = {statistics.median(lengths):.0f}\n"
        f"mean = {statistics.mean(lengths):.0f}\n"
        f"max = {max(lengths)}"
    )
    ax.text(
        0.98,
        0.95,
        summary,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=11,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": LIGHT_GRAY},
    )


def draw_type_panel(ax, records: list[dict]) -> None:
    add_panel_label(ax, "(d)", "Mathematical-programming type")
    counts = Counter(r["problem_type"] for r in records)
    order = ["IP", "LP", "MIP", "NLP", "goal_programming"]
    labels = [TYPE_LABELS[t] for t in order if t in counts]
    values = [counts[t] for t in order if t in counts]
    colors = [BLUE, TEAL, "#91B9D4", "#D58C5A", "#A64C4C"][: len(values)]

    wedges, _ = ax.pie(
        values,
        startangle=95,
        colors=colors,
        wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1.2},
    )
    ax.text(0, 0, f"n={len(records)}", ha="center", va="center", fontsize=18, fontweight="bold")
    ax.set_aspect("equal")

    total = len(records)
    legend_labels = [f"{label}: {value} ({value / total:.0%})" for label, value in zip(labels, values)]
    ax.legend(
        wedges,
        legend_labels,
        loc="center left",
        bbox_to_anchor=(0.96, 0.5),
        frameon=False,
        fontsize=11,
        handlelength=1.0,
    )


def main() -> None:
    records = load_records(INPUT_PATH)

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titlesize": 14,
            "axes.labelsize": 11.5,
            "xtick.labelsize": 10.5,
            "ytick.labelsize": 10.5,
        }
    )

    fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.4), dpi=300)
    draw_record_panel(axes[0, 0], records)
    draw_domain_panel(axes[0, 1], records)
    draw_length_panel(axes[1, 0], records)
    draw_type_panel(axes[1, 1], records)

    fig.tight_layout(rect=(0.02, 0.01, 0.98, 0.98), w_pad=3.0, h_pad=3.0)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PATH, bbox_inches="tight", facecolor="white")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
