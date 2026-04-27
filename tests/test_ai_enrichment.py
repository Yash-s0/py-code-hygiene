import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from pycodehygiene.ai_enrichment import detect_provider, enrich_findings, read_env_file
from pycodehygiene.scanner import scan_project


class AiEnrichmentTests(unittest.TestCase):
    def test_read_env_file_parses_comments_whitespace_and_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                textwrap.dedent(
                    """
                    # comments should be ignored
                    OPENAI_API_KEY = "openai-key"
                    ANTHROPIC_API_KEY='anthropic-key'
                    INVALID_LINE
                    EMPTY=
                    """
                ),
                encoding="utf-8",
            )
            values = read_env_file(root / ".env")
            self.assertEqual(values["OPENAI_API_KEY"], "openai-key")
            self.assertEqual(values["ANTHROPIC_API_KEY"], "anthropic-key")
            self.assertIn("EMPTY", values)

    def test_detect_provider_prefers_openai_then_anthropic(self):
        provider, key = detect_provider(
            {
                "OPENAI_API_KEY": "openai-first",
                "ANTHROPIC_API_KEY": "anthropic-second",
            }
        )
        self.assertEqual(provider, "openai")
        self.assertEqual(key, "openai-first")

        provider2, key2 = detect_provider({"ANTHROPIC_API_KEY": "anthropic-only"})
        self.assertEqual(provider2, "anthropic")
        self.assertEqual(key2, "anthropic-only")

    def test_enrich_findings_without_key_works_and_returns_disabled_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            findings = [{"id": "1", "message": "Unused import"}]
            meta = enrich_findings(findings, env_path=root / ".env")
            self.assertFalse(meta["enabled"])
            self.assertEqual(meta["provider"], "none")
            self.assertIn("working without AI guidance", meta["reason"])
            self.assertEqual(meta["enriched_count"], 0)

    def test_enrich_findings_with_openai_key_enriches_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("OPENAI_API_KEY=test-openai\n", encoding="utf-8")
            findings = [
                {
                    "id": "f1",
                    "category": "unused-import",
                    "kind": "import",
                    "confidence": "high",
                    "file": "mod.py",
                    "line_start": 1,
                    "line_end": 1,
                    "symbol": "os",
                    "message": "Unused import",
                    "evidence": ["No inbound references found in repository index"],
                    "suggested_action": "Review before removing",
                }
            ]

            with patch("pycodehygiene.ai_enrichment._post_json") as mock_post:
                mock_post.return_value = {
                    "choices": [
                        {
                            "message": {
                                "content": '{"explanation":"Import is never used.","improvement":"Remove it or use it."}'
                            }
                        }
                    ]
                }
                meta = enrich_findings(findings, env_path=root / ".env")

            self.assertTrue(meta["enabled"])
            self.assertEqual(meta["provider"], "openai")
            self.assertEqual(meta["enriched_count"], 1)
            self.assertEqual(findings[0]["ai_explanation"], "Import is never used.")
            self.assertEqual(findings[0]["ai_improvement"], "Remove it or use it.")

    def test_enrich_findings_provider_error_is_non_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("OPENAI_API_KEY=test-openai\n", encoding="utf-8")
            findings = [
                {
                    "id": "f1",
                    "category": "unused-import",
                    "kind": "import",
                    "confidence": "high",
                    "file": "mod.py",
                    "line_start": 1,
                    "line_end": 1,
                    "symbol": "os",
                    "message": "Unused import",
                    "evidence": ["No inbound references found in repository index"],
                    "suggested_action": "Review before removing",
                }
            ]

            with patch("pycodehygiene.ai_enrichment._post_json", side_effect=RuntimeError("timeout")):
                meta = enrich_findings(findings, env_path=root / ".env")

            self.assertTrue(meta["enabled"])
            self.assertEqual(meta["provider"], "openai")
            self.assertEqual(meta["enriched_count"], 0)
            self.assertIn("failed", meta["reason"])

    def test_scan_project_sets_ai_metadata_and_enriched_fields(self):
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
            (root / ".env").write_text("OPENAI_API_KEY=test-openai\n", encoding="utf-8")

            with patch("pycodehygiene.ai_enrichment._default_env_path", return_value=root / ".env"), patch(
                "pycodehygiene.ai_enrichment._post_json"
            ) as mock_post:
                mock_post.return_value = {
                    "choices": [
                        {
                            "message": {
                                "content": '{"explanation":"This symbol appears unused.","improvement":"Remove it after verifying no external usage."}'
                            }
                        }
                    ]
                }
                report = scan_project(root)

            self.assertIn("ai", report)
            self.assertTrue(report["ai"]["enabled"])
            self.assertEqual(report["ai"]["provider"], "openai")
            self.assertGreaterEqual(report["ai"]["enriched_count"], 1)
            enriched = [f for f in report["findings"] if f.get("ai_explanation") or f.get("ai_improvement")]
            self.assertTrue(enriched)


if __name__ == "__main__":
    unittest.main()
