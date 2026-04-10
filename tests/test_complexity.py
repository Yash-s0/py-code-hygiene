import tempfile
import textwrap
import unittest
from pathlib import Path

from pycodehygiene.scanner import scan_project


class ComplexityTests(unittest.TestCase):
    def test_hotspot_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "c.py").write_text(
                textwrap.dedent(
                    """
                    def busy(x):
                        total = 0
                        for i in range(x):
                            if i % 2 == 0:
                                total += 1
                            elif i % 3 == 0:
                                total += 2
                            else:
                                try:
                                    if i > 5 and i < 9:
                                        total += i
                                except Exception:
                                    total -= 1
                        return total
                    """
                ),
                encoding="utf-8",
            )

            report = scan_project(root, complexity_threshold=4)

        hotspots = report["complexity"]["hotspots"]
        self.assertTrue(hotspots)
        self.assertGreaterEqual(hotspots[0]["complexity"], 4)


if __name__ == "__main__":
    unittest.main()
