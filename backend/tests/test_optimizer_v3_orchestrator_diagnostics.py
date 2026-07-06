import unittest
from unittest.mock import patch

from tailor_tom.latex_compiler import CompileResult
from tailor_tom.layout_analyzer import QualityResult
from tailor_tom.optimizer.v3.llm_usage import usage_from_counts
from tailor_tom.optimizer.v3.orchestrator import optimize_resume_v3
from tailor_tom.optimizer.v3.stage0_preprocess import BulletConstraint, Stage0Result
from tailor_tom.optimizer.v3.stage1_generator import GeneratedCandidate
from tailor_tom.optimizer.v3.stage2_validation import FeasibilityResult
from tailor_tom.optimizer.v3.stage3_chooser import ChooserResult
from tailor_tom.optimizer.v3.types import V3OptimizationResult
from worker.tasks import _v3_result_to_db_payload


class OptimizerOrchestratorDiagnosticsTests(unittest.TestCase):
    def test_passes_done_counts_generation_calls_not_early_stop_loop(self):
        bullet = BulletConstraint(
            bullet_id=1,
            section="Experience",
            original_text="Built APIs.",
            latex_snippet="Built APIs.",
            line_count=1,
            word_count=2,
            char_count=11,
            target_line_count=1,
            source_item_index=0,
            mapping_status="mapped",
        )
        stage0 = Stage0Result(
            success=True,
            original_latex="orig",
            compile_result=CompileResult(success=True, pdf_bytes=b"%PDF", page_count=1),
            eligible_bullets=[bullet],
            original_options={1: {"option_id": "b1_orig", "latex": "Built APIs."}},
            stage0_diagnostics={},
        )
        quality = QualityResult(True, 1, 1, [])

        with patch("tailor_tom.optimizer.v3.orchestrator.run_stage0", return_value=stage0), \
             patch("tailor_tom.optimizer.v3.orchestrator.check_quality", return_value=quality), \
             patch(
                 "tailor_tom.optimizer.v3.orchestrator.generate_candidates",
                 return_value=(
                     [GeneratedCandidate(1, "b1_c1_it0", "Built resilient APIs.")],
                     usage_from_counts(1, 1, 0.0, "estimated"),
                     None,
                 ),
             ), \
             patch(
                 "tailor_tom.optimizer.v3.orchestrator.run_feasibility",
                 return_value=FeasibilityResult(feasible_option_ids={"b1_c1_it0"}),
             ), \
             patch(
                 "tailor_tom.optimizer.v3.orchestrator.run_chooser",
                 return_value=(ChooserResult({1: "b1_c1_it0"}, usage_from_counts(1, 1, 0.0, "estimated")), None),
             ), \
             patch(
                 "tailor_tom.optimizer.v3.orchestrator.apply_and_verify",
                 return_value=(True, "", b"%PDF", 1, True, "All criteria pass", "final", {1: "b1_c1_it0"}, [], {"attempted": False}),
             ):
            result = optimize_resume_v3("orig", "job", target_pages=1, max_iterations=3)

        self.assertTrue(result.success)
        self.assertEqual(result.passes_done, 1)
        self.assertTrue(result.diagnostics["early_stop"])
        self.assertEqual(result.diagnostics["max_iterations_used"], 1)

    def test_worker_payload_promotes_baseline_and_final_quality(self):
        result = V3OptimizationResult(
            success=False,
            optimized_latex="latex",
            error_message="Long bullets: 1",
            passes_done=1,
            diagnostics={
                "baseline_page_count": 1,
                "baseline_quality_passes": False,
                "baseline_quality_issues_summary": "Long bullets: 2",
                "baseline_long_bullet_count": 2,
                "baseline_long_bullets": [{"bullet_id": 20, "line_count": 4}],
                "final_page_count": 1,
                "final_quality_passes": False,
                "final_quality_issues_summary": "Long bullets: 1",
                "final_long_bullet_count": 1,
                "final_long_bullets": [{"bullet_id": 21, "line_count": 4}],
            },
        )

        payload = _v3_result_to_db_payload(result)
        analysis = payload["analysis_json"]

        self.assertEqual(analysis["baseline_quality"]["issues_summary"], "Long bullets: 2")
        self.assertEqual(analysis["final_quality"]["issues_summary"], "Long bullets: 1")
        self.assertEqual(analysis["diagnostics"]["baseline_long_bullet_count"], 2)


if __name__ == "__main__":
    unittest.main()
