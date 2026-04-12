import tempfile
import unittest
from pathlib import Path

from pycodehygiene.cli import _reports_dir, _resolve_scan_output_path


class CliOutputPathTests(unittest.TestCase):
    def test_relative_default_name_is_rooted_to_reports_dir(self):
        target = Path("/tmp/crm-backend")
        output = _resolve_scan_output_path(target, "pycodehygiene_report.json", ".json")
        self.assertEqual(output, _reports_dir() / "crm-backend_report.json")

    def test_relative_custom_name_is_rooted_to_reports_dir(self):
        target = Path("/tmp/crm-backend")
        output = _resolve_scan_output_path(target, "team_audit.html", ".html")
        self.assertEqual(output, _reports_dir() / "team_audit.html")

    def test_absolute_path_is_also_rooted_to_reports_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path("/tmp/crm-backend")
            absolute = Path(tmp) / "custom_report.json"
            output = _resolve_scan_output_path(target, str(absolute), ".json")
            self.assertEqual(output, _reports_dir() / "custom_report.json")


if __name__ == "__main__":
    unittest.main()
