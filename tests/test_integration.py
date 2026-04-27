import tempfile
import textwrap
import unittest
from pathlib import Path

from pycodehygiene.report import ReportGenerator
from pycodehygiene.scanner import scan_project


class IntegrationTests(unittest.TestCase):
    def test_end_to_end_json_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text(
                textwrap.dedent(
                    """
                    def _dead():
                        return 1
                    """
                ),
                encoding="utf-8",
            )

            report = scan_project(root)

            out = root / "report.html"
            ReportGenerator().generate(out, report)

            self.assertTrue(out.exists())
            html = out.read_text(encoding="utf-8")
            self.assertIn("Py Code Hygiene Report", html)
            self.assertIn("Dead Code Findings", html)
            self.assertIn("AI Guidance:", html)
            self.assertIn("working without AI guidance", html)
            if "severityToggles" in html:
                self.assertIn("table.sortable", html)
            else:
                # Fallback renderer is used when jinja2 is unavailable.
                self.assertIn("<table>", html)

            self.assertIn("meta", report)
            self.assertIn("dead_code", report)
            self.assertIn("duplicates", report)
            self.assertIn("complexity", report)
            self.assertIn("ai", report)
            self.assertIn("findings", report)
            self.assertEqual(report["summary"]["total_findings"], len(report["findings"]))

    def test_html_renders_ai_guidance_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text(
                textwrap.dedent(
                    """
                    def _dead():
                        return 1
                    """
                ),
                encoding="utf-8",
            )

            report = scan_project(root)
            self.assertTrue(report["findings"])
            report["findings"][0]["ai_explanation"] = "This symbol is never referenced."
            report["findings"][0]["ai_improvement"] = "Remove it or wire it into usage."
            report["ai"] = {
                "enabled": True,
                "provider": "openai",
                "reason": "AI enrichment enabled via openai",
                "enriched_count": 1,
            }

            out = root / "report-ai.html"
            ReportGenerator().generate(out, report)
            html = out.read_text(encoding="utf-8")
            self.assertIn("AI enrichment enabled via openai", html)
            self.assertIn("What is wrong:", html)
            self.assertIn("How to improve:", html)

    def test_empty_and_syntax_error_resilience(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text("def x(:\n    pass\n", encoding="utf-8")

            report = scan_project(root)

            self.assertEqual(report["summary"]["files_analyzed"], 1)
            self.assertEqual(report["summary"]["parse_errors"], 1)
            self.assertIn(str(root / "broken.py"), report["parse_errors"])


if __name__ == "__main__":
    unittest.main()
