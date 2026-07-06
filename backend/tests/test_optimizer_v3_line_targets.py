import unittest
from unittest.mock import patch

from tailor_tom.optimizer.v3.stage0_preprocess import BulletConstraint
from tailor_tom.optimizer.v3.stage1_generator import _format_bullets_for_llm
from tailor_tom.optimizer.v3.stage2_validation import _verify_line_counts


class OptimizerLineTargetTests(unittest.TestCase):
    def _bullet(self, *, line_count=4, target_line_count=3):
        return BulletConstraint(
            bullet_id=1,
            section="Experience",
            original_text="Optimized portfolio analytics across multiple asset classes.",
            latex_snippet="Optimized portfolio analytics across multiple asset classes.",
            line_count=line_count,
            word_count=7,
            char_count=58,
            target_line_count=target_line_count,
            source_item_index=0,
            mapping_status="mapped",
        )

    def test_overlong_bullet_passes_when_repaired_to_target(self):
        bullet = self._bullet(line_count=4, target_line_count=3)
        metrics = {"bullets": [{"item_index": 0, "line_count": 3}]}

        with patch("tailor_tom.optimizer.v3.stage2_validation.extract_line_metrics", return_value=metrics):
            failures, missing = _verify_line_counts([bullet], b"%PDF", "latex")

        self.assertEqual(failures, {})
        self.assertEqual(missing, {})

    def test_overlong_bullet_fails_when_still_over_target(self):
        bullet = self._bullet(line_count=4, target_line_count=3)
        metrics = {"bullets": [{"item_index": 0, "line_count": 4}]}

        with patch("tailor_tom.optimizer.v3.stage2_validation.extract_line_metrics", return_value=metrics):
            failures, missing = _verify_line_counts([bullet], b"%PDF", "latex")

        self.assertEqual(failures, {1: (4, 4)})
        self.assertEqual(missing, {})

    def test_normal_bullet_still_preserves_exact_line_count(self):
        bullet = self._bullet(line_count=2, target_line_count=2)
        metrics = {"bullets": [{"item_index": 0, "line_count": 3}]}

        with patch("tailor_tom.optimizer.v3.stage2_validation.extract_line_metrics", return_value=metrics):
            failures, missing = _verify_line_counts([bullet], b"%PDF", "latex")

        self.assertEqual(failures, {1: (2, 3)})
        self.assertEqual(missing, {})

    def test_stage1_prompt_mentions_repair_target_for_overlong_bullet(self):
        prompt = _format_bullets_for_llm([self._bullet(line_count=4, target_line_count=3)])

        self.assertIn("MUST shrink from 4 to <= 3 line(s)", prompt)


if __name__ == "__main__":
    unittest.main()
