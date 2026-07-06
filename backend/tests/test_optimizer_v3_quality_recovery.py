import unittest
from unittest.mock import patch

from tailor_tom.latex_compiler import CompileResult
from tailor_tom.layout_analyzer import QualityResult
from tailor_tom.optimizer.v3.stage0_preprocess import BulletConstraint
from tailor_tom.optimizer.v3.stage3_chooser import apply_and_verify


class OptimizerQualityRecoveryTests(unittest.TestCase):
    def test_apply_and_verify_reverts_changed_bullet_until_quality_passes(self):
        original = (
            "\\begin{document}\\begin{itemize}"
            "\\item Original concise bullet."
            "\\end{itemize}\\end{document}"
        )
        bullet = BulletConstraint(
            bullet_id=1,
            section="Experience",
            original_text="Original concise bullet.",
            latex_snippet="Original concise bullet.",
            line_count=1,
            word_count=3,
            char_count=24,
            target_line_count=1,
            source_item_index=0,
            mapping_status="mapped",
        )
        choices = {1: "b1_c1_it0"}
        option_id_to_latex = {
            "b1_orig": "Original concise bullet.",
            "b1_c1_it0": "Expanded replacement bullet with enough added wording to overflow.",
        }

        def fake_compile(latex):
            page_count = 2 if "Expanded replacement" in latex else 1
            return CompileResult(success=True, pdf_bytes=b"%PDF", page_count=page_count)

        def fake_quality(pdf_bytes, target_pages, latex):
            page_count = 2 if "Expanded replacement" in latex else 1
            passes = page_count <= target_pages
            issue = "Page count: 2 (target: 1)" if not passes else "All criteria pass"
            return QualityResult(
                passes=passes,
                page_count=page_count,
                page_target=target_pages,
                long_bullets=[],
            )

        with patch("tailor_tom.optimizer.v3.stage3_chooser.compile_latex", side_effect=fake_compile), \
             patch("tailor_tom.optimizer.v3.stage3_chooser.check_quality", side_effect=fake_quality):
            result = apply_and_verify(original, [bullet], choices, option_id_to_latex, target_pages=1)

        (
            success,
            err,
            _pdf,
            page_count,
            quality_passes,
            _quality_issues,
            final_latex,
            effective_choices,
            _dropped,
            fallback,
        ) = result

        self.assertTrue(success, err)
        self.assertTrue(quality_passes)
        self.assertEqual(page_count, 1)
        self.assertNotIn("Expanded replacement", final_latex)
        self.assertEqual(effective_choices[1], "b1_orig")
        self.assertTrue(fallback["attempted"])
        self.assertTrue(fallback["success"])
        self.assertEqual(fallback["reverted_bullet_ids"], [1])


if __name__ == "__main__":
    unittest.main()
