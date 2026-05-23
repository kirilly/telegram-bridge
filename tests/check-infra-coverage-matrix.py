#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def parse_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] | None = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and all(set(cell) <= {"-"} for cell in cells):
            continue
        if headers is None:
            headers = cells
            continue
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        if row.get("ID", "").startswith(("C", "H")):
            rows.append(row)
    return rows


def covered(row: dict[str, str]) -> bool:
    return row.get("Gap", "").lower() == "covered" and bool(row.get("Evidence", "").strip())


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    matrix = repo / "tests" / "infra-coverage-matrix.md"
    rows = parse_rows(matrix)
    failures: list[str] = []
    required = {"ID", "Repo", "Risk", "Behavior", "Required test type", "Evidence", "Gap", "QA note"}

    critical = [row for row in rows if row.get("Risk") == "critical"]
    high = [row for row in rows if row.get("Risk") == "high"]
    critical_covered = sum(1 for row in critical if covered(row))
    high_covered = sum(1 for row in high if covered(row))
    high_pct = high_covered / len(high) if high else 0.0

    if not critical:
        failures.append("matrix has no critical rows")
    if not high:
        failures.append("matrix has no high rows")
    if critical and critical_covered != len(critical):
        failures.append(f"critical coverage is {critical_covered}/{len(critical)}")
    if high and high_pct < 0.8:
        failures.append(f"high coverage is {high_covered}/{len(high)}")
    for index, row in enumerate(rows, 1):
        missing = [name for name in required if not row.get(name, "").strip()]
        if missing:
            failures.append(f"row {index} missing: {', '.join(sorted(missing))}")
        if row.get("Risk") not in {"critical", "high"}:
            failures.append(f"row {index} has unsupported risk: {row.get('Risk')}")

    print(f"infra matrix: critical {critical_covered}/{len(critical)}")
    print(f"infra matrix: high {high_covered}/{len(high)} ({high_pct:.0%})")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
