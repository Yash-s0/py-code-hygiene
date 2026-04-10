from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Dict

try:
    from jinja2 import Template
except ModuleNotFoundError:  # pragma: no cover
    Template = None  # type: ignore


class ReportGenerator:
    def __init__(self):
        self.template = None
        if Template is not None:
            template_path = Path(__file__).resolve().parent.parent / "templates" / "report_template.html"
            self.template = Template(template_path.read_text(encoding="utf-8"))

    def generate(self, output_file: Path | str, context: Dict[str, object]) -> None:
        if self.template is not None:
            rendered = self.template.render(
                report=context,
                report_json=json.dumps(context, indent=2),
            )
        else:
            rendered = _render_fallback_html(context)
        Path(output_file).write_text(rendered, encoding="utf-8")


def _render_fallback_html(context: Dict[str, object]) -> str:
    summary = context.get("summary", {}) if isinstance(context.get("summary"), dict) else {}
    findings = context.get("findings", []) if isinstance(context.get("findings"), list) else []

    rows = []
    for item in findings[:200]:
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('analyzer', '-')))}</td>"
            f"<td>{html.escape(str(item.get('confidence', '-')))}</td>"
            f"<td>{html.escape(str(item.get('category', '-')))}</td>"
            f"<td>{html.escape(str(item.get('file', '-')))}:{html.escape(str(item.get('line_start', '-')))}</td>"
            f"<td>{html.escape(str(item.get('symbol', '-')))}</td>"
            f"<td>{html.escape(str(item.get('message', '-')))}</td>"
            "</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>Py Code Hygiene Report</title>
<style>
body {{ font-family: 'Trebuchet MS', 'Segoe UI', sans-serif; margin: 20px; color: #112; }}
.card {{ border: 1px solid #d7e0ea; border-radius: 10px; padding: 14px; margin-bottom: 14px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ text-align: left; border-bottom: 1px solid #e7edf3; padding: 8px; font-size: 13px; }}
th {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: #445; }}
</style>
</head>
<body>
  <h1>Py Code Hygiene Report</h1>
  <div class=\"card\">
    <strong>Files:</strong> {summary.get('files_analyzed', 0)}<br>
    <strong>Total findings:</strong> {summary.get('total_findings', 0)}<br>
    <strong>Health:</strong> {summary.get('health_score', 0)}%
  </div>
  <div class=\"card\">
    <h2>Dead Code Findings</h2>
    <table>
      <thead>
        <tr><th>Analyzer</th><th>Confidence</th><th>Category</th><th>Location</th><th>Symbol</th><th>Message</th></tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
