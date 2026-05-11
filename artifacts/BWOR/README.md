# BWOR Resource Artifacts

This directory contains public artifacts for the BWOR benchmark and its CIKM Resource paper.

## Files

- `figures/bwor_dataset_overview.png`: dataset overview figure generated from `data/datasets/bwor.jsonl`.
- `figures/bwor_reasoning_contrast.png`: reasoning-vs-non-reasoning contrast figure used in the paper.
- `data_card.md`: compact data card for the public BWOR JSONL release.
- `prompts.md`: prompt templates used by the OR-LLM-Agent baseline pipeline.
- `baselines/bwor_baseline_summary.csv`: aggregate baseline counts reported over 82 BWOR records.

## Public Dataset

- GitHub JSONL: `data/datasets/bwor.jsonl`
- Hugging Face: https://huggingface.co/datasets/SJTU/BWOR
- Zenodo DOI: https://doi.org/10.5281/zenodo.20120692
- License: CC-BY-4.0

## Regeneration

```bash
uv run scripts/build_bwor_release.py
uv run scripts/plot_bwor_dataset_overview.py
uv run scripts/plot_bwor_reasoning_contrast.py
```

Raw provider logs are not committed because they can contain provider diagnostics and local execution traces. The committed summary table records the public aggregate counts, and the evaluation scripts can regenerate per-run outputs in a local environment.
