"""Focused tests for timeout-safe candidate and result handling."""

from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from adapters.frontieror import result_adapter, schedule, tool_loop
from adapters.frontieror.solver_runner import OptimizeTransformer, execute


class CandidatePipelineTests(unittest.TestCase):
    def test_transformer_replaces_optimize_calls(self) -> None:
        import ast

        tree = OptimizeTransformer().visit(ast.parse("result = model.optimize(callback)"))
        rendered = ast.unparse(tree)
        self.assertEqual(rendered, "result = __frontieror_optimize(model, callback)")

    def test_solver_limit_and_incumbent_are_checkpointed(self) -> None:
        class Variable:
            VarName = "x[0]"

        class Parameters:
            TimeLimit = float("inf")

        class Model:
            Params = Parameters()
            SolCount = 0
            ObjVal = 7.0
            ObjBound = 6.0
            Status = 9

            def getVars(self):
                return [Variable()]

            def getAttr(self, name, variables):
                self.assert_name = name
                return [1.0]

            def cbGetSolution(self, variables):
                return [1.0]

            def cbGet(self, code):
                return {2: 7.0, 3: 6.0}[code]

            def optimize(self, callback):
                callback(self, 1)
                self.SolCount = 1

        fake = types.ModuleType("gurobipy")
        fake.Model = Model
        fake.GurobiError = RuntimeError
        fake.GRB = types.SimpleNamespace(
            Callback=types.SimpleNamespace(MIPSOL=1, MIPSOL_OBJ=2, MIPSOL_OBJBND=3)
        )
        with tempfile.TemporaryDirectory() as raw_root:
            candidate = Path(raw_root) / "raw_candidate.json"
            with patch.dict("sys.modules", {"gurobipy": fake}):
                execute(
                    "import gurobipy as gp\nm = gp.Model()\nm.optimize()",
                    candidate,
                    600,
                )

            payload = json.loads(candidate.read_text(encoding="utf-8"))
            self.assertEqual(Model.Params.TimeLimit, 600)
            self.assertEqual(payload["objective"], 7.0)
            self.assertEqual(payload["variables"], {"x[0]": 1.0})
            self.assertTrue((Path(raw_root) / "raw_candidates" / "attempt-1.json").is_file())

    def test_result_adapter_retries_schema_errors(self) -> None:
        self.assertEqual(result_adapter.config.RESULT_ADAPTER_MAX_ATTEMPTS, 10)
        self.assertEqual(tool_loop.MAX_TOOL_ROUNDS, 10)
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            workspace = root / "workspaces" / "demo"
            hidden = root / "problems" / "demo" / "hidden"
            input_dir = root / "problems" / "demo" / "input"
            workspace.mkdir(parents=True)
            hidden.mkdir(parents=True)
            input_dir.mkdir(parents=True)
            (workspace / "raw_candidate.json").write_text(
                json.dumps({"variables": {"x[0]": 1}}), encoding="utf-8"
            )
            (workspace / "instance.json").write_text("{}", encoding="utf-8")
            (workspace / "solver.py").write_text("pass", encoding="utf-8")
            (hidden / "solution_schema.json").write_text(
                json.dumps(
                    {
                        "type": "object",
                        "properties": {"x": {"type": "integer"}},
                        "required": ["x"],
                        "additionalProperties": False,
                    }
                ),
                encoding="utf-8",
            )
            (input_dir / "problem.md").write_text("Return x.", encoding="utf-8")

            with (
                patch.object(result_adapter.config, "WORKSPACE_ROOT", root / "workspaces"),
                patch.object(result_adapter.config, "PROBLEM_ROOT", root / "problems"),
                patch.object(result_adapter, "query_llm_with_tools", return_value='{"wrong": 1}'),
            ):
                record = result_adapter.adapt("demo", "test-model")

            self.assertEqual(record["status"], "format_failed")
            self.assertEqual(record["attempts"], 10)
            self.assertFalse((workspace / "solution.json").exists())

    def test_scheduler_postprocesses_after_outer_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            workspace = root / "workspaces" / "demo"
            run_dir = root / "run"
            workspace.mkdir(parents=True)
            (run_dir / "logs").mkdir(parents=True)
            raw_candidate = workspace / "raw_candidate.json"
            raw_candidate.write_text('{"objective": 1}', encoding="utf-8")
            wrapper = CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"outcome":"task_timeout","timeout_s":7200}\n',
                stderr="",
            )
            postprocess = CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"status":"format_failed","raw_candidate_preserved":true}\n',
                stderr="",
            )
            with (
                patch.object(schedule.config, "REPO_ROOT", root),
                patch.object(schedule.config, "WORKSPACE_ROOT", root / "workspaces"),
                patch.object(schedule.subprocess, "run", side_effect=[wrapper, postprocess]),
            ):
                record = schedule._run_task(
                    "demo", "test-model", "test-batch.slice", 100, 8, run_dir
                )

            self.assertEqual(record["outcome"], "task_timeout")
            self.assertTrue(record["candidate_available"])
            self.assertTrue((run_dir / "logs" / "demo.final.json").is_file())
            self.assertTrue(raw_candidate.is_file())

    def test_batch_slice_gets_one_shared_memory_limit(self) -> None:
        completed = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch.object(schedule.uuid, "uuid4", return_value=types.SimpleNamespace(hex="abc")),
            patch.object(schedule.subprocess, "run", return_value=completed) as run,
        ):
            unit = schedule._create_batch_slice(100)

        self.assertEqual(unit, "or-llm-frontieror-batch-abc.slice")
        command = run.call_args.args[0]
        self.assertIn("MemoryMax=100G", command)
        self.assertIn("MemorySwapMax=0", command)


if __name__ == "__main__":
    unittest.main()
