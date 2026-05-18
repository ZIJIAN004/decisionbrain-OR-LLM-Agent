from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from or_llm_agent.cli import ProblemSpecAgentResult, main
from or_llm_agent.or_ci import VerificationResult
from or_llm_agent.prompts import build_problem_metadata_template, build_problem_spec_prompt


class ProblemSpecGenerationTests(unittest.TestCase):
    def test_problem_spec_prompt_documents_constraint_relaxation_schema(self) -> None:
        prompt = build_problem_spec_prompt("CASE-001", "A capacity-constrained LP.")

        self.assertIn('"paths": [', prompt)
        self.assertIn('"instance.<resource_or_requirement_field>"', prompt)
        self.assertIn('"factor": 1.2', prompt)
        self.assertIn("do not use `path`, `amount`, or `direction`", prompt)
        self.assertIn("Preserve primitive statement quantities", prompt)
        self.assertIn("profit and transport cost", prompt)

    def test_problem_metadata_template_uses_requested_problem_id(self) -> None:
        template = json.loads(build_problem_metadata_template("CASE-123"))

        self.assertEqual(template["id"], "CASE-123")
        self.assertEqual(template["problem_type"], "LP")
        self.assertIn("cost_scaling", template["metamorphic"])
        relaxation = template["metamorphic"]["constraint_relaxation"]["relaxations"][0]
        self.assertIn("paths", relaxation)
        self.assertIn("factor", relaxation)

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
            self.assertEqual(status["spec_attempt_count"], 1)
            self.assertEqual(status["spec_repair_status"], "not_needed")

    def test_spec_repairs_metadata_after_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            problem_path = root / "spec" / "problem.json"
            raw_path = root / "raw" / "spec.txt"
            status_path = root / "spec" / "status.json"
            statement_path.write_text("Maximize profit subject to capacity.", encoding="utf-8")
            calls = []

            def fake_run(**kwargs):
                calls.append(kwargs)
                payload = _invalid_constraint_relaxation_problem() if len(calls) == 1 else _valid_problem()
                return _agent_result(root, payload)

            with patch("or_llm_agent.cli._run_problem_spec_agent", fake_run):
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
                        "--max-repair-attempts",
                        "2",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["attempt"], 1)
            self.assertEqual(calls[1]["attempt"], 2)
            self.assertIn("paths must be a non-empty list", calls[1]["repair_error"])
            self.assertEqual(json.loads(problem_path.read_text(encoding="utf-8"))["id"], "CASE-001")
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["spec_validation_status"], "passed")
            self.assertEqual(status["spec_attempt_count"], 2)
            self.assertEqual(status["spec_repair_status"], "repaired")
            self.assertEqual(status["spec_attempts"][0]["spec_validation_status"], "failed")
            self.assertEqual(status["spec_attempts"][1]["spec_validation_status"], "passed")
            self.assertTrue((root / "raw" / "spec-attempt-1.txt").exists())
            self.assertTrue((root / "raw" / "spec-attempt-2.txt").exists())

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
            self.assertEqual(summary["spec_repair_status"], "failed")
            self.assertEqual(summary["spec_fidelity_status"], "not_reviewed")
            self.assertEqual(summary["spec_fidelity_review"], "spec/fidelity-review.md")
            self.assertEqual(summary["model_generation_status"], "skipped")
            self.assertFalse((artifact_dir / "submissions" / "CASE-FAIL.py").exists())
            review = (artifact_dir / "spec" / "fidelity-review.md").read_text(encoding="utf-8")
            self.assertIn("Fidelity status: `not_reviewed`", review)
            self.assertIn("OR-CI result is interpreted", review)

    def test_solve_writes_spec_fidelity_review_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            statement_path.write_text("Minimize one production cost.", encoding="utf-8")

            def fake_generate_agent_submission(inputs, paths, args):
                paths.submission_path.parent.mkdir(parents=True, exist_ok=True)
                paths.raw_path.parent.mkdir(parents=True, exist_ok=True)
                paths.submission_path.write_text("def build_model(data):\n    return None\n", encoding="utf-8")
                paths.raw_path.write_text("generated model", encoding="utf-8")
                return {
                    "generation_status": "generated",
                    "generation_error": "",
                    "raw_response": paths.raw_path,
                    "submission": paths.submission_path,
                    "generation_mode": "agent",
                    "agent_returncode": 0,
                    "agent_timed_out": False,
                }

            verification = VerificationResult(
                returncode=0,
                stdout="",
                stderr="",
                report={"classification": "SUCCESS", "status": "PASS", "checks": []},
            )

            with (
                patch("or_llm_agent.cli._run_problem_spec_agent", return_value=_agent_result(root, _valid_problem())),
                patch("or_llm_agent.cli.generate_agent_submission", fake_generate_agent_submission),
                patch("or_llm_agent.cli.run_or_ci_verify", return_value=verification),
            ):
                exit_code = main(
                    [
                        "solve",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-001",
                        "--artifact-dir",
                        str(artifact_dir),
                    ]
                )

            self.assertEqual(exit_code, 0)
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["spec_validation_status"], "passed")
            self.assertEqual(summary["spec_repair_status"], "not_needed")
            self.assertEqual(summary["model_generation_status"], "generated")
            self.assertEqual(summary["verification_status"], "PASS")
            self.assertEqual(summary["classification"], "SUCCESS")
            self.assertEqual(summary["spec_fidelity_status"], "not_reviewed")
            self.assertEqual(summary["spec_fidelity_review"], "spec/fidelity-review.md")
            review = (artifact_dir / "spec" / "fidelity-review.md").read_text(encoding="utf-8")
            self.assertIn("Model generation: `generated`", review)
            self.assertIn("Verification: `PASS`", review)
            self.assertIn("Fidelity status: `not_reviewed`", review)


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


def _invalid_constraint_relaxation_problem() -> dict:
    problem = _valid_problem()
    problem["metamorphic"]["constraint_relaxation"] = {
        "relaxations": [
            {
                "path": "instance.capacity",
                "direction": "increase",
                "amount": 1.0,
                "objective_relation": "non_decrease",
            }
        ],
        "tolerance_abs": 1e-6,
        "tolerance_rel": 1e-6,
    }
    return problem


if __name__ == "__main__":
    unittest.main()
