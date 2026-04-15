import argparse
import datetime as dt
import html
import pathlib
import xml.etree.ElementTree as ET


def _collect_cases(root: ET.Element):
    if root.tag == "testsuite":
        suites = [root]
    else:
        suites = list(root.findall("testsuite"))

    if not suites and root.tag == "testsuites":
        suites = list(root.iter("testsuite"))

    cases = []
    totals = {
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "time": 0.0,
    }

    for suite in suites:
        totals["tests"] += int(suite.attrib.get("tests", 0) or 0)
        totals["failures"] += int(suite.attrib.get("failures", 0) or 0)
        totals["errors"] += int(suite.attrib.get("errors", 0) or 0)
        totals["skipped"] += int(suite.attrib.get("skipped", 0) or 0)
        totals["time"] += float(suite.attrib.get("time", 0.0) or 0.0)

        for case in suite.findall("testcase"):
            status = "passed"
            details = ""

            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")

            if failure is not None:
                status = "failed"
                details = (failure.text or "").strip()
            elif error is not None:
                status = "error"
                details = (error.text or "").strip()
            elif skipped is not None:
                status = "skipped"
                details = (skipped.text or "").strip()

            cases.append(
                {
                    "classname": case.attrib.get("classname", ""),
                    "name": case.attrib.get("name", ""),
                    "time": float(case.attrib.get("time", 0.0) or 0.0),
                    "status": status,
                    "details": details,
                }
            )

    return totals, cases


def _status_class(status: str) -> str:
    return {
        "passed": "ok",
        "failed": "bad",
        "error": "err",
        "skipped": "skip",
    }.get(status, "unk")


def _render_html(totals, cases):
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for idx, case in enumerate(cases, 1):
        status = html.escape(case["status"])
        klass = _status_class(case["status"])
        classname = html.escape(case["classname"])
        name = html.escape(case["name"])
        duration = f"{case['time']:.3f}s"
        details = html.escape(case["details"]) if case["details"] else ""

        details_cell = ""
        if details:
            details_cell = (
                "<details><summary>Trace</summary>"
                f"<pre>{details}</pre></details>"
            )

        rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{classname}</td>"
            f"<td>{name}</td>"
            f"<td><span class='pill {klass}'>{status}</span></td>"
            f"<td>{duration}</td>"
            f"<td>{details_cell}</td>"
            "</tr>"
        )

    passed = max(totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"], 0)
    pass_rate = (passed / totals["tests"] * 100.0) if totals["tests"] else 0.0

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Selenium Test Report</title>
  <style>
    :root {{
      --bg: #f4f6fb;
      --surface: #ffffff;
      --border: #d9dfef;
      --text: #162036;
      --muted: #5d6a85;
      --ok: #1f9d55;
      --bad: #d12b2b;
      --err: #a73aa8;
      --skip: #a17915;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Segoe UI, Arial, sans-serif;
      padding: 24px;
    }}
    .wrap {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 18px;
      margin-bottom: 16px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 26px;
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .stat {{
      background: #f7f9ff;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
    }}
    .stat .k {{
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .stat .v {{
      font-size: 24px;
      font-weight: 700;
      margin-top: 4px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      text-align: left;
      padding: 10px 8px;
      vertical-align: top;
    }}
    th {{
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .pill {{
      display: inline-block;
      border-radius: 999px;
      padding: 3px 10px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: #fff;
    }}
    .pill.ok {{ background: var(--ok); }}
    .pill.bad {{ background: var(--bad); }}
    .pill.err {{ background: var(--err); }}
    .pill.skip {{ background: var(--skip); }}
    .pill.unk {{ background: #64748b; }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin-top: 8px;
      padding: 10px;
      background: #0f172a;
      color: #e2e8f0;
      border-radius: 8px;
      max-height: 300px;
      overflow: auto;
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"card\">
      <h1>Selenium Test Report</h1>
      <div class=\"meta\">Generated: {html.escape(timestamp)}</div>
      <div class=\"grid\">
        <div class=\"stat\"><div class=\"k\">Total</div><div class=\"v\">{totals['tests']}</div></div>
        <div class=\"stat\"><div class=\"k\">Passed</div><div class=\"v\">{passed}</div></div>
        <div class=\"stat\"><div class=\"k\">Failed</div><div class=\"v\">{totals['failures']}</div></div>
        <div class=\"stat\"><div class=\"k\">Errors</div><div class=\"v\">{totals['errors']}</div></div>
        <div class=\"stat\"><div class=\"k\">Skipped</div><div class=\"v\">{totals['skipped']}</div></div>
        <div class=\"stat\"><div class=\"k\">Pass Rate</div><div class=\"v\">{pass_rate:.1f}%</div></div>
        <div class=\"stat\"><div class=\"k\">Duration</div><div class=\"v\">{totals['time']:.2f}s</div></div>
      </div>
    </div>

    <div class=\"card\">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Class</th>
            <th>Test</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an HTML report from pytest JUnit XML")
    parser.add_argument("--input", required=True, help="Path to junit xml")
    parser.add_argument("--output", required=True, help="Path to output html report")
    args = parser.parse_args()

    input_path = pathlib.Path(args.input)
    output_path = pathlib.Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"JUnit XML not found: {input_path}")

    tree = ET.parse(input_path)
    root = tree.getroot()

    totals, cases = _collect_cases(root)
    report_html = _render_html(totals, cases)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_html, encoding="utf-8")

    print(f"HTML report written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
