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

    def test_string_annotations_do_not_trigger_high_confidence_unused_import(self):
        report = self._scan(
            {
                "models.py": """
                class User:
                    pass
                """,
                "service.py": """
                from __future__ import annotations
                from models import User

                def render(user: "User") -> "User":
                    return user
                """,
            }
        )

        findings = [
            f
            for f in report["dead_code"]["findings"]
            if f["file"].endswith("service.py") and f["category"] == "unused-import"
        ]
        self.assertEqual(findings, [])

    def test_local_shadowing_does_not_mark_import_used(self):
        report = self._scan(
            {
                "calc.py": """
                from math import sqrt

                def compute():
                    sqrt = 42
                    return sqrt + 1
                """
            }
        )

        import_findings = [
            f
            for f in report["dead_code"]["findings"]
            if f["file"].endswith("calc.py") and f["category"] == "unused-import"
        ]
        self.assertTrue(import_findings)
        self.assertEqual(import_findings[0]["symbol"], "sqrt")

    def test_reexported_top_level_import_is_not_high_confidence_unused(self):
        report = self._scan(
            {
                "dep.py": """
                value = 7
                """,
                "bridge.py": """
                from dep import value as exported
                """,
                "consumer.py": """
                from bridge import exported

                def read():
                    return exported
                """,
            }
        )

        active = [
            f
            for f in report["dead_code"]["findings"]
            if f["file"].endswith("bridge.py") and f["category"] == "unused-import"
        ]
        self.assertEqual(active, [])

        suppressed = [
            f
            for f in report["dead_code"]["suppressed_findings"]
            if f["file"].endswith("bridge.py") and f["category"] == "unused-import"
        ]
        self.assertTrue(suppressed)
        joined = "; ".join(suppressed[0].get("evidence", []))
        self.assertIn("Imported by another module", joined)

    def test_registry_module_import_gets_side_effect_hint(self):
        report = self._scan(
            {
                "app/registry.py": """
                def register():
                    return 1
                """,
                "main.py": """
                from app.registry import register as ticket_register
                """,
            }
        )

        active = [
            f
            for f in report["dead_code"]["findings"]
            if f["file"].endswith("main.py") and f["category"] == "unused-import"
        ]
        self.assertEqual(active, [])

        suppressed = [
            f
            for f in report["dead_code"]["suppressed_findings"]
            if f["file"].endswith("main.py") and f["category"] == "unused-import"
        ]
        self.assertTrue(suppressed)
        joined = "; ".join(suppressed[0].get("evidence", []))
        self.assertIn("registry/plugin side effects", joined)


if __name__ == "__main__":
    unittest.main()
