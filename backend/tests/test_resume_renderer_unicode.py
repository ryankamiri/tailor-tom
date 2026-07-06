import shutil
import subprocess
import unittest
from unittest.mock import patch

from tailor_tom.latex_compiler import CompileResult, compile_latex
from tailor_tom.resume_renderer import fit_to_pages, get_spacing_config, render_resume_to_latex


def _cjk_resume():
    return {
        "header": {
            "name": "张伟",
            "contact_items": [{"text": "R&D | 99% | zhang@example.com", "url": ""}],
        },
        "sections": [
            {
                "title": "教育背景",
                "type": "entry_list",
                "entries": [
                    {
                        "primary": "清华大学",
                        "secondary": "软件工程",
                        "location": "北京",
                        "dates": "2020-2024",
                        "bullets": ["负责 R&D 平台，达成 99% 可用性"],
                    }
                ],
            }
        ],
    }


class ResumeRendererUnicodeTests(unittest.TestCase):
    def test_cjk_resume_uses_xelatex_preamble_and_preserves_text(self):
        latex = render_resume_to_latex(_cjk_resume(), get_spacing_config(0.5))

        self.assertIn("\\usepackage{fontspec}", latex)
        self.assertIn("\\usepackage{xeCJK}", latex)
        self.assertNotIn("\\usepackage[T1]{fontenc}", latex)
        self.assertIn("张伟", latex)
        self.assertIn("清华大学", latex)
        self.assertIn("R\\&D", latex)
        self.assertIn("99\\%", latex)

    def test_ascii_resume_keeps_legacy_preamble(self):
        resume = {
            "header": {"name": "Jane Doe", "contact_items": []},
            "sections": [{"title": "Experience", "type": "text", "content": "Built APIs."}],
        }

        latex = render_resume_to_latex(resume, get_spacing_config(0.5))

        self.assertIn("\\usepackage[T1]{fontenc}", latex)
        self.assertIn("\\usepackage[utf8]{inputenc}", latex)
        self.assertNotIn("\\usepackage{fontspec}", latex)
        self.assertNotIn("\\usepackage{xeCJK}", latex)

    def test_fit_to_pages_passes_cjk_latex_to_compiler(self):
        captured = []

        def fake_compile(latex):
            captured.append(latex)
            return CompileResult(success=True, pdf_bytes=b"%PDF-1.4", page_count=1)

        with patch("tailor_tom.resume_renderer.compile_latex", side_effect=fake_compile):
            latex, pdf_bytes = fit_to_pages(_cjk_resume(), target_pages=1)

        self.assertEqual(pdf_bytes, b"%PDF-1.4")
        self.assertIn("\\usepackage{xeCJK}", captured[0])
        self.assertIn("张伟", latex)

    def test_xelatex_required_document_does_not_fallback_to_pdflatex(self):
        latex = render_resume_to_latex(_cjk_resume(), get_spacing_config(0.5))

        def fake_find_engine(engine):
            return None if engine == "xelatex" else "/usr/bin/pdflatex"

        with patch("tailor_tom.latex_compiler._find_tex_engine", side_effect=fake_find_engine):
            result = compile_latex(latex)

        self.assertFalse(result.success)
        self.assertIn("xelatex not found", result.error_message or "")

    @unittest.skipUnless(
        shutil.which("xelatex") and subprocess.run(
            ["kpsewhich", "xeCJK.sty"],
            capture_output=True,
            text=True,
        ).returncode == 0,
        "requires local xelatex and xeCJK",
    )
    def test_real_xelatex_compiles_cjk_resume_when_available(self):
        latex = render_resume_to_latex(_cjk_resume(), get_spacing_config(0.9))

        result = compile_latex(latex)

        self.assertTrue(result.success, result.error_message)
        self.assertGreater(len(result.pdf_bytes or b""), 0)
        self.assertGreaterEqual(result.page_count, 1)


if __name__ == "__main__":
    unittest.main()
