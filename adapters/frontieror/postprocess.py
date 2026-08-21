"""CLI entry point for post-deadline candidate recovery and schema adaptation."""

from __future__ import annotations

import argparse
import json

from .result_adapter import adapt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    print(json.dumps(adapt(args.problem, args.model), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
