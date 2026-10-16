"""Command-line reporting and local feature gates."""

import argparse
import json
import sys
from pathlib import Path

from .core import find_duplicates, read_csv
from .licensing import valid_license


def scan_files(paths, paid=False, threshold=0.75, date_window=14):
    invoices, errors = [], []
    capped = 0
    for path in paths:
        rows, problems = read_csv(path)
        errors.extend(problems)
        remaining = len(rows) if paid else max(0, 200 - len(invoices))
        invoices.extend(rows[:remaining])
        capped += max(0, len(rows) - remaining)
    all_pairs = find_duplicates(invoices, threshold, date_window)
    pairs = all_pairs if paid else all_pairs[:5]
    return {"tier": "paid" if paid else "free", "pairs": pairs, "errors": errors,
            "summary": {"rows_scanned": len(invoices), "rows_skipped_cap": capped,
                        "malformed_rows": len(errors), "pairs_flagged": len(all_pairs),
                        "high": sum(p["severity"] == "HIGH" for p in all_pairs),
                        "medium": sum(p["severity"] == "MEDIUM" for p in all_pairs),
                        "pairs_shown": len(pairs), "pairs_hidden": len(all_pairs) - len(pairs)}}


def text_report(report):
    lines = []
    for pair in report["pairs"]:
        sides = [f'{p["invoice_id"]} | {p["vendor"]} | {p["amount"]} | {p["date"]} ({p["source"]}:{p["row"]})'
                 for p in (pair["left"], pair["right"])]
        lines.append(f'{pair["severity"]} {pair["reason"]} score={pair["score"]:.3f}: ' + " <-> ".join(sides))
    for error in report["errors"]:
        lines.append(f'SKIPPED {error["source"]}:{error["row"]}: {error["error"]}')
    s = report["summary"]
    lines.append(f'{report["tier"]} tier: {s["rows_scanned"]} rows scanned; {s["high"]} HIGH, {s["medium"]} MEDIUM pairs; '
                 f'{s["pairs_shown"]} shown, {s["pairs_hidden"]} hidden; {s["malformed_rows"]} malformed rows/file errors; '
                 f'{s["rows_skipped_cap"]} rows skipped by cap.')
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="invoiceguard", description="Find likely duplicate invoices entirely offline.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("scan", "batch"):
        sub = subparsers.add_parser(command)
        sub.add_argument("path", type=Path)
        sub.add_argument("--format", choices=("text", "json"), default="text")
        sub.add_argument("--threshold", type=float, default=0.75)
        sub.add_argument("--date-window", type=int, default=14)
        sub.add_argument("--license-key")
    args = parser.parse_args(argv)
    try:
        paid = valid_license(args.license_key)
        if args.command == "batch":
            if not paid:
                raise ValueError("batch requires a valid demo license key")
            if not args.path.is_dir():
                raise ValueError("batch path must be a directory")
            paths = sorted(p for p in args.path.iterdir() if p.is_file() and p.suffix.lower() == ".csv")
            if not paths:
                raise ValueError("directory contains no CSV files")
        else:
            paths = [args.path]
        report = scan_files(paths, paid, args.threshold, args.date_window)
    except (OSError, ValueError) as exc:
        if args.format == "json":
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"invoiceguard: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.format == "json" else text_report(report))
    return 0
