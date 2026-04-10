import tempfile
import textwrap
import unittest
from pathlib import Path

from pycodehygiene.scanner import scan_project


class DeadCodeFalsePositiveTests(unittest.TestCase):
    def _scan(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, content in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(content), encoding="utf-8")

            report = scan_project(root)
            return report

    def test_framework_routes_not_flagged(self):
        report = self._scan(
            {
                "app.py": """
                from fastapi import APIRouter
                from flask import Flask

                router = APIRouter()
                app = Flask(__name__)

                @router.get('/items')
                def _route_items():
                    return {'ok': True}

                @app.route('/health')
                def _health():
                    return 'ok'
                """,
            }
        )

        findings = [
            f for f in report["dead_code"]["findings"] if f["file"].endswith("app.py")
        ]
        self.assertEqual(findings, [])

    def test_public_symbol_not_flagged_by_default(self):
        report = self._scan(
            {
                "service.py": """
                def public_handler():
                    return 1
                """
            }
        )

        names = {f["symbol"] for f in report["dead_code"]["findings"]}
        self.assertNotIn("public_handler", names)

    def test_inline_suppression_works(self):
        report = self._scan(
            {
                "mod.py": """
                # pycodehygiene: ignore[unused-function]
                def _dead():
                    return 1
                """
            }
        )

        self.assertEqual(report["dead_code"]["findings"], [])
        self.assertTrue(report["dead_code"]["suppressed_findings"])


if __name__ == "__main__":
    unittest.main()
