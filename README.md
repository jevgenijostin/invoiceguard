# InvoiceGuard

An entirely offline CLI that reviews invoice/payment CSV exports for likely duplicate invoices. Python 3.10+; Python standard library only at runtime. No accounts, backend, telemetry, or network calls. Findings are review hints, not proof of fraud.

## Run

From this checkout:

```sh
python -m invoiceguard scan examples/invoices.csv
python -m invoiceguard scan examples/invoices.csv --format json --threshold 0.80 --date-window 7
```

Optionally install with `python -m pip install .` to expose the `invoiceguard` console command. Setuptools is only a build tool. Tests use development-only pytest:

```sh
python -m pip install pytest
python -m pytest -q
```

## Input and output

UTF-8 CSV (optional BOM) with required `invoice_id,vendor,amount,date` headers and optional `description`. Extra named columns are ignored. Dates must be YYYY-MM-DD. Amounts use decimal notation without currency symbols or thousands separators; negative amounts and zero are accepted. Finite amounts up to 1e15 in magnitude and at most 12 decimal places are supported. All rows must have the header's field count. Required values cannot be blank.

Malformed rows are skipped and reported with their source file and physical line number. Invalid headers produce a file error. Broken quoting or invalid UTF-8 stops that file; rows already parsed remain available. File errors count in the `malformed_rows` summary alongside row errors. Unreadable files fail the command with exit code 2. Completed reports (including findings or skipped rows) return 0. JSON failures contain an `error` field; text failures go to stderr.

Text reports show severity, reason, fuzzy score, invoice IDs, vendors, amounts, dates, and source locations. JSON also includes descriptions, all parsing errors, and summary totals. Summary severity counts include hidden findings; `pairs_shown` and `pairs_hidden` explain the free limit.

## Matching

Every unordered pair of distinct input rows is evaluated once. Separate identical rows remain candidates. Vendor normalization lowercases, removes Unicode punctuation, collapses whitespace, and repeatedly removes trailing Inc, LLC, Ltd, GmbH, Co, Corp, Corporation, AG, or KG suffixes (including dotted forms). It does not strip these words from the middle of a name.

The score is **50% vendor similarity + 35% amount closeness + 15% date proximity**:

- Vendor similarity is `1 - Levenshtein distance / max name length`, using our own implementation. Empty normalized names contribute zero.
- Amount closeness is `max(0, 1 - relative difference / 0.02)`, relative to the larger absolute amount. Exact amounts score 1; 1% differences score 0.5; 2% or greater score 0. Two zero amounts score 1.
- Date proximity is `max(0, 1 - days apart / (window + 1))`. The default window is 14 days; day 14 contributes a small amount, day 15 contributes zero. `--date-window 0` rewards only the same day.

Scores at or above `--threshold` (default 0.75) are HIGH fuzzy; scores from 0.55 up to that threshold are MEDIUM possible. Lower scores are omitted. Threshold must be 0.55–1.0. The date window is nonnegative. These are reasonable, **untuned defaults**, not validated against a real dataset. Matching is additive: strong vendor and amount evidence can flag a pair even outside the date window.

An exact, case-sensitive invoice ID match (after surrounding whitespace removal) is always HIGH exact-id regardless of other fields. Exact IDs rank first with effective confidence 1, then fuzzy findings rank by descending score; the displayed score always remains the actual fuzzy score. Stable ties follow input order. Invoice IDs may be reused across vendors in real exports, so even this override needs human review.

## Demo monetization gate

| Feature | Free (missing/invalid key) | Paid demo (valid key) |
| --- | --- | --- |
| Valid rows compared | First 200 | All |
| Findings displayed | Top 5 | All |
| Cross-file batch | Blocked | Enabled |

The free cap counts valid rows only. The full CSV is still parsed to report malformed rows and the number excluded by the cap. Exact-ID findings also count toward the top-five display limit, and are prioritized as described above.

Batch combines all immediate `.csv` files (case insensitive, sorted by path) into one scan, detecting cross-file duplicates. It does not recurse into subdirectories.

This is a **local HMAC-SHA256 demo gate, not real payment enforcement**. The fixed secret is public source code. Anyone can issue a key. No payments or license servers exist. This valid test key unlocks the paid path:

```text
demo.a78c3eb87eb21d59caa1f82953992aa9ec7ab866d63080cff17e4b7add7e24dc
```

```sh
python -m invoiceguard batch examples --format json --license-key demo.a78c3eb87eb21d59caa1f82953992aa9ec7ab866d63080cff17e4b7add7e24dc
python -c "from invoiceguard.licensing import issue_license; print(issue_license('my-demo'))"
```

Paid means the feature tier here, not a purchase. Never use this design as a real licensing security boundary.

## Limits and contributing

Pair comparison is quadratic in row count; edit distance is quadratic in name lengths. All parsed rows and flagged pairs are held in memory. Paid scans have no artificial cap and can be slow or consume substantial memory for large exports. Start with small exports. Currency is not modeled: only compare amounts in a common currency. Descriptions are preserved but not scored. See [TODO.md](TODO.md) for deferred work. Contributions should include focused pytest coverage. Licensed under MIT.
