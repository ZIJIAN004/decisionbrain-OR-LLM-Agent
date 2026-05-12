# BWOR Data Card

## Dataset Summary

BWOR is a bilingual benchmark for natural-language operations research (OR) modeling and solving. It contains 82 textbook-style OR problems with Chinese and English problem statements, verified answers, and metadata for domain and mathematical-programming type.

## Schema

Each row in `data/datasets/bwor.jsonl` is a JSON object with the following fields:

- `id`: stable public identifier, from `BWOR-001` to `BWOR-082`.
- `en_question`: normalized English problem statement.
- `cn_question`: original Chinese problem statement.
- `answer`: numeric objective value when `solution_status` is `optimal`; otherwise `null`.
- `solution_status`: `optimal` or `no_optimal`.
- `domain`: coarse OR application domain.
- `problem_type`: mathematical-programming type, such as `LP`, `IP`, `MIP`, `NLP`, or `goal_programming`.
- `difficulty`: source difficulty label.

## Evaluation Protocol

The default metric is exact instance-level correctness under solver-grounded evaluation. For records with `solution_status = optimal`, a prediction is counted as correct when the extracted objective value is within an absolute tolerance of `0.1` from the verified answer. For records with `solution_status = no_optimal`, a prediction is counted as correct when it matches the no-optimal status rather than a numeric objective value.

Reported aggregate accuracy uses all 82 records as the denominator: 80 numeric optimal records and 2 no-optimal records.

Use `scripts/evaluate_bwor_predictions.py` to evaluate JSONL prediction files keyed by `id`.

## Provenance

The source problems are derived from Chinese OR teaching materials cited in the paper, translated and normalized into English while preserving the original Chinese statements. The public release is intended for research evaluation of OR modeling, solver-code generation, and LLM-based OR assistants.

## Intended Use

BWOR is designed for benchmarking systems that convert natural-language OR word problems into executable solver code or equivalent verified solutions. It is not a comprehensive OR corpus, and it should not be used as evidence that an LLM system is safe for high-stakes deployment without additional domain-expert validation.

## License

The released dataset is licensed under CC-BY-4.0. Please cite the BWOR paper and retain provenance information when reusing the data.
