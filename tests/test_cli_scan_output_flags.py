import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import re

from pycodehygiene.cli import _reports_dir, main


class CliScanOutputFlagTests(unittest.TestCase):
    def _write_sample_project(self, root: Path) -> None:
        (root / "mod.py").write_text(
            textwrap.dedent(
                """
                def _dead():
                    return 1
                """
            ),
            encoding="utf-8",
        )

    def test_scan_no_json_generates_only_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_sample_project(root)

            html_name = f"{root.name}_only_html.html"
            json_name = f"{root.name}_only_html.json"
            html_path = _reports_dir() / html_name
            json_path = _reports_dir() / json_name
            html_path.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "scan",
                        str(root),
                        "--html-output",
                        html_name,
                        "--json-output",
                        json_name,
                        "--no-json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(html_path.exists())
            self.assertFalse(json_path.exists())
            self.assertIn("HTML report:", stdout.getvalue())
            self.assertNotIn("JSON report:", stdout.getvalue())

            html_path.unlink(missing_ok=True)

    def test_scan_no_html_and_no_json_generates_no_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_sample_project(root)

            html_name = f"{root.name}_no_reports.html"
            json_name = f"{root.name}_no_reports.json"
            html_path = _reports_dir() / html_name
            json_path = _reports_dir() / json_name
            html_path.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "scan",
                        str(root),
                        "--html-output",
                        html_name,
                        "--json-output",
                        json_name,
                        "--no-html",
                        "--no-json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse(html_path.exists())
            self.assertFalse(json_path.exists())
            self.assertIn("Output reports skipped (--no-json and --no-html)", stdout.getvalue())
            self.assertIn("working without AI", stdout.getvalue())
            self.assertNotIn("HTML report:", stdout.getvalue())
            self.assertNotIn("JSON report:", stdout.getvalue())

    def test_scan_min_confidence_override_surfaces_low_confidence_dead_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir(parents=True, exist_ok=True)
            (root / "app" / "registry.py").write_text(
                textwrap.dedent(
                    """
                    def register():
                        return 1
                    """
                ),
                encoding="utf-8",
            )
            (root / "main.py").write_text(
                textwrap.dedent(
                    """
                    from app.registry import register as ticket_register
                    """
                ),
                encoding="utf-8",
            )

            default_stdout = StringIO()
            with redirect_stdout(default_stdout):
                default_exit = main(["scan", str(root), "--no-html", "--no-json"])
            self.assertEqual(default_exit, 0)
            self.assertIn("dead_code_suppressed=1", default_stdout.getvalue())
            default_match = re.search(r"dead_code=(\d+)", default_stdout.getvalue())
            self.assertIsNotNone(default_match)
            default_dead = int(default_match.group(1))

            low_stdout = StringIO()
            with redirect_stdout(low_stdout):
                low_exit = main(
                    [
                        "scan",
                        str(root),
                        "--no-html",
                        "--no-json",
                        "--min-confidence",
                        "low",
                    ]
                )
            self.assertEqual(low_exit, 0)
            low_match = re.search(r"dead_code=(\d+)", low_stdout.getvalue())
            self.assertIsNotNone(low_match)
            low_dead = int(low_match.group(1))
            self.assertGreater(low_dead, default_dead)


if __name__ == "__main__":
    unittest.main()
