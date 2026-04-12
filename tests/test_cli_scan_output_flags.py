import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

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
            self.assertNotIn("HTML report:", stdout.getvalue())
            self.assertNotIn("JSON report:", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
