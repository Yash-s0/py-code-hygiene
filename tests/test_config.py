import tempfile
import textwrap
import unittest
from pathlib import Path

from pycodehygiene.config import load_config


class ConfigTests(unittest.TestCase):
    def test_loads_pycodehygiene_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pycodehygiene.toml").write_text(
                textwrap.dedent(
                    """
                    [tool.pycodehygiene]
                    minimum_confidence_to_report = "low"
                    duplicate_min_lines = 8
                    duplicate_similarity_threshold = 0.9
                    complexity_threshold = 13
                    include = ["src/**/*.py"]
                    """
                ),
                encoding="utf-8",
            )

            config = load_config(root)

        self.assertEqual(config.minimum_confidence_to_report, "low")
        self.assertEqual(config.duplicate_min_lines, 8)
        self.assertAlmostEqual(config.duplicate_similarity_threshold, 0.9)
        self.assertEqual(config.complexity_threshold, 13)
        self.assertEqual(config.include, ["src/**/*.py"])

    def test_invalid_threshold_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pycodehygiene.toml").write_text(
                textwrap.dedent(
                    """
                    [tool.pycodehygiene]
                    duplicate_similarity_threshold = 1.4
                    """
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_config(root)


if __name__ == "__main__":
    unittest.main()
