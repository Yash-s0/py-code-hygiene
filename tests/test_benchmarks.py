import tempfile
import textwrap
import unittest
from pathlib import Path

from pycodehygiene.benchmarks import benchmark_table, run_benchmark


class BenchmarkTests(unittest.TestCase):
    def test_run_benchmark_outputs_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text(
                textwrap.dedent(
                    """
                    def _dead_one(x):
                        value = x + 1
                        if value > 2:
                            return value
                        return value - 1

                    def _dead_two(y):
                        value = y + 1
                        if value > 2:
                            return value
                        return value - 1
                    """
                ),
                encoding="utf-8",
            )

            result = run_benchmark(root, runs=1, warmups=0)

        self.assertIn("timings", result)
        self.assertIn("dead_code_ms", result["timings"])
        self.assertIn("duplicates_ms", result["timings"])
        self.assertIn("full_scan_ms", result["timings"])
        self.assertGreaterEqual(result["timings"]["dead_code_ms"]["mean"], 0)
        table = benchmark_table(result)
        self.assertIn("Benchmark Results", table)


if __name__ == "__main__":
    unittest.main()
