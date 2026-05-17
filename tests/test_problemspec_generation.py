from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from or_llm_agent.cli import ProblemSpecAgentResult, main


class ProblemSpecGenerationTests(unittest.TestCase):
    def test_generate_accepts_explicit_problem_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            problem_path = root / "problem.json"
            statement_path = root / "problem.txt"
            submission_path = root / "submission.py"
            raw_path = root / "raw.txt"
            problem_path.write_text(json.dumps(_valid_problem()), encoding="utf-8")
            statement_path.write_text("Explicit statement context.", encoding="utf-8")

            def fake_query(messages, model_name):
                self.assertEqual(model_name, "mock-model")
                self.assertIn("Explicit statement context.", messages[1]["content"])
                return "```python\nimport gurobipy as gp\n\ndef build_model(data: dict):\n    return gp.Model()\n```"

            with patch("or_llm_agent.cli.query_llm", fake_query):
                exit_code = main(
                    [
                        "generate",
                        "--mode",
                        "api",
                        "--problem",
                        str(problem_path),
                        "--statement-file",
                        str(statement_path),
                        "--model",
                        "mock-model",
                        "--out",
                        str(submission_path),
                        "--raw",
                        str(raw_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("def build_model", submission_path.read_text(encoding="utf-8"))
            self.assertIn("def build_model", raw_path.read_text(encoding="utf-8"))

    def test_spec_writes_problem_raw_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            problem_path = root / "spec" / "problem.json"
            raw_path = root / "raw" / "spec.txt"
            status_path = root / "spec" / "status.json"
            statement_path.write_text("Minimize one production cost.", encoding="utf-8")

            with patch("or_llm_agent.cli._run_problem_spec_agent", return_value=_agent_result(root, _valid_problem())):
                exit_code = main(
                    [
                        "spec",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-001",
                        "--out",
                        str(problem_path),
                        "--raw",
                        str(raw_path),
                        "--status",
                        str(status_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(problem_path.read_text(encoding="utf-8"))["id"], "CASE-001")
            self.assertIn('"id": "CASE-001"', raw_path.read_text(encoding="utf-8"))
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["spec_generation_status"], "generated")
            self.assertEqual(status["spec_validation_status"], "passed")
            self.assertEqual(status["validation_returncode"], 0)

    def test_solve_stops_before_model_generation_when_spec_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            statement_path.write_text("This statement will yield an invalid spec.", encoding="utf-8")

            invalid_problem = {
                "id": "CASE-FAIL",
                "problem_type": "LP",
                "metamorphic": {
                    "cost_scaling": {
                        "coefficient_paths": ["instance.price"],
                        "factors": [2.0],
                    }
                },
            }

            with (
                patch("or_llm_agent.cli._run_problem_spec_agent", return_value=_agent_result(root, invalid_problem)),
                patch("or_llm_agent.cli.generate_agent_submission") as generate_agent_submission,
            ):
                exit_code = main(
                    [
                        "solve",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-FAIL",
                        "--artifact-dir",
                        str(artifact_dir),
                    ]
                )

            self.assertEqual(exit_code, 1)
            generate_agent_submission.assert_not_called()
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["spec_generation_status"], "generated")
            self.assertEqual(summary["spec_validation_status"], "failed")
            self.assertEqual(summary["model_generation_status"], "skipped")
            self.assertFalse((artifact_dir / "submissions" / "CASE-FAIL.py").exists())


def _agent_result(root: Path, payload: dict) -> ProblemSpecAgentResult:
    return ProblemSpecAgentResult(
        raw_text=json.dumps(payload, indent=2),
        returncode=0,
        timed_out=False,
        events_path=root / "events.jsonl",
        last_message_path=root / "last-message.md",
        stderr="",
    )


def _valid_problem() -> dict:
    return {
        "id": "CASE-001",
        "problem_type": "LP",
        "instance": {"price": 4.0},
        "metamorphic": {
            "cost_scaling": {
                "coefficient_paths": ["instance.price"],
                "factors": [2.0],
                "tolerance_abs": 1e-6,
                "tolerance_rel": 1e-6,
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
