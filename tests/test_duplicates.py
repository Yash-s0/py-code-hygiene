import tempfile
import textwrap
import unittest
from pathlib import Path

from pycodehygiene.scanner import scan_project


class DuplicateDetectionTests(unittest.TestCase):
    def _scan(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, content in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(content), encoding="utf-8")

            return scan_project(root)

    def test_exact_group_detected_after_normalization(self):
        report = self._scan(
            {
                "a.py": """
                def one(value):
                    result = value + 10
                    marker = result * 1
                    if result > 20:
                        return result * 2
                    return marker - 1
                """,
                "b.py": """
                def two(x):
                    tmp = x + 10
                    marker = tmp * 1
                    if tmp > 20:
                        return tmp * 2
                    return marker - 1
                """,
            }
        )

        kinds = {group["kind"] for group in report["duplicates"]["groups"]}
        self.assertIn("exact", kinds)

    def test_near_group_detected(self):
        report = self._scan(
            {
                "x.py": """
                def transform(data):
                    total = 0
                    for item in data:
                        if item % 2 == 0:
                            total += item
                        else:
                            total += item * 2
                    return total
                """,
                "y.py": """
                def transform_alt(values):
                    total = 1
                    for item in values:
                        if item % 2 == 0:
                            total += item
                        else:
                            total += item * 3
                    return total
                """,
            }
        )

        groups = report["duplicates"]["groups"]
        self.assertTrue(any(group["kind"] in {"near", "exact"} for group in groups))

    def test_duplicate_preview_includes_peer_locations(self):
        report = self._scan(
            {
                "a.py": """
                def alpha(value):
                    count = value + 1
                    marker = count + 0
                    if count > 2:
                        return count * 2
                    return marker - 1
                """,
                "b.py": """
                def beta(amount):
                    total = amount + 1
                    marker = total + 0
                    if total > 2:
                        return total * 2
                    return marker - 1
                """,
            }
        )

        groups = report["duplicates"]["groups"]
        self.assertTrue(groups)
        first_group = groups[0]
        self.assertTrue(first_group["items"])
        self.assertIn("normalized_snippet", first_group["items"][0])

        top_files = report["summary"]["top_files"]
        self.assertTrue(top_files)
        duplicate_issues = [
            issue
            for row in top_files
            for issue in row.get("issues", [])
            if issue.get("analyzer") == "duplicates"
        ]
        self.assertTrue(duplicate_issues)
        self.assertTrue(duplicate_issues[0].get("related"))

    def test_short_wrapper_functions_with_different_call_targets_not_grouped(self):
        report = self._scan(
            {
                "a.py": """
                def get_affiliate_summary(email=None):
                    \"\"\"Fetch affiliate summary metrics.\"\"\"
                    return get_affiliate_summary_service(
                        email=email,
                    )
                """,
                "b.py": """
                def get_traders_summary(email=None):
                    \"\"\"Fetch traders summary metrics.\"\"\"
                    return get_traders_summary_service(
                        email=email,
                    )
                """,
            }
        )

        self.assertEqual(report["duplicates"]["summary"]["groups"], 0)


if __name__ == "__main__":
    unittest.main()
