# Deferred work

- OFX/QBO imports, PDF invoice parsing, and configurable column mappings.
- Currency-aware comparisons and exchange rates; currently assume one currency.
- Real payment backend and secure license issuance; current gate is self-issuable.
- Calibration against labeled real-world bookkeeping data and false-positive analysis.
- Vendor aliases, accent/transliteration rules, invoice-number similarity, and description scoring.
- Vendor-scoped invoice IDs as an optional alternative to the required global exact-ID override.
- Candidate indexing, streaming ingestion, and bounded-memory ranking for large exports.
- Explicit per-file statistics and richer file-error versus malformed-row accounting.
- Handling damaged CSV records beyond unrecoverable quote/encoding errors.
- Automated release publishing and broader Python/OS CI coverage.
