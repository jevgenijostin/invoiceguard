import csv
import json
import subprocess
import sys
import unicodedata
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from invoiceguard.cli import main, scan_files
from invoiceguard.core import Invoice, duplicate_score, find_duplicates, levenshtein_distance, normalize_vendor, read_csv, similarity
from invoiceguard.licensing import issue_license, valid_license

KEY = "demo.a78c3eb87eb21d59caa1f82953992aa9ec7ab866d63080cff17e4b7add7e24dc"


def invoice(**changes):
    return replace(Invoice("A", "Acme Inc.", Decimal("100"), date(2026, 1, 1)), **changes)


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["invoice_id", "vendor", "amount", "date", "description"])
        writer.writerows(rows)
    return path


@pytest.mark.parametrize("a,b,expected", [("kitten", "sitting", 3), ("", "", 0), ("abc", "", 3),
    ("same", "same", 0), ("flaw", "lawn", 2), ("a", "b", 1), ("ab", "ba", 2), ("café", "cafe", 1)])
def test_distance(a, b, expected):
    assert levenshtein_distance(a, b) == expected
    assert levenshtein_distance(b, a) == expected


@pytest.mark.parametrize("suffix", ["Inc", "Inc.", "LLC", "Ltd", "Ltd.", "GmbH", "Co", "Corp", "Corporation", "AG", "KG", "L.L.C."])
def test_suffix(suffix):
    assert normalize_vendor("  ACME   Works " + suffix) == "acme works"


@pytest.mark.parametrize("value,expected", [("Acme, Co. Ltd.", "acme"), ("O'Reilly & Sons", "oreilly sons"),
    ("Inc Design", "inc design"), ("  A\t B\nC  ", "a b c"), ("LLC", ""), ("Müller GmbH", "müller")])
def test_normalization(value, expected):
    assert normalize_vendor(value) == expected


def test_duplicates_with_canonically_equivalent_vendors(tmp_path):
    nfc = unicodedata.normalize("NFC", "Müller GmbH")
    nfd = unicodedata.normalize("NFD", "Müller GmbH")
    assert nfc != nfd
    path = write_csv(tmp_path / "repro.csv", [
        ["INV-1001", nfc, "490.00", "2026-03-01", ""],
        ["INV-1002", nfd, "500.00", "2026-03-06", ""],
    ])
    rows, errors = read_csv(path)
    assert not errors
    pair, = find_duplicates(rows)
    assert pair["left"]["invoice_id"] == "INV-1001"
    assert pair["right"]["invoice_id"] == "INV-1002"
    assert pair["severity"] == "MEDIUM"
    assert pair["score"] == pytest.approx(0.6)
    assert normalize_vendor(nfc) == normalize_vendor(nfd) == "müller"


def test_similarity():
    assert similarity("", "") == 1
    assert similarity("", "abc") == 0
    assert similarity("kitten", "sitting") == pytest.approx(4 / 7)


def test_scores():
    a = invoice()
    assert duplicate_score(a, invoice(invoice_id="B", vendor="ACME LLC")) == 1
    assert duplicate_score(a, invoice(vendor="Zzzzz", amount=Decimal("900"), date=date(2020, 1, 1))) < 0.55
    assert duplicate_score(a, invoice(amount=Decimal("99"))) == pytest.approx(0.825)
    assert duplicate_score(a, invoice(amount=Decimal("98"))) == pytest.approx(0.65)
    assert duplicate_score(a, invoice(date=date(2026, 1, 15))) > duplicate_score(a, invoice(date=date(2026, 1, 16)))
    assert duplicate_score(a, invoice(date=date(2026, 1, 2)), 0) == pytest.approx(0.85)
    assert duplicate_score(invoice(amount=Decimal(0)), invoice(amount=Decimal(0))) == 1
    assert duplicate_score(invoice(vendor="LLC"), invoice(vendor="Inc")) == 0.5


def test_exact_override_and_bands():
    a = invoice()
    b = invoice(vendor="ZZZZ", amount=Decimal("900"), date=date(2020, 1, 1))
    pair, = find_duplicates([a, b], threshold=1)
    assert (pair["severity"], pair["reason"]) == ("HIGH", "exact-id")
    assert pair["score"] < 0.55
    pair, = find_duplicates([a, invoice(invoice_id="B", amount=Decimal("98"))])
    assert pair["severity"] == "MEDIUM"
    assert find_duplicates([a, replace(b, invoice_id="B")]) == []


def test_pairs_once():
    assert find_duplicates([invoice()]) == []
    pairs = find_duplicates([invoice(invoice_id=str(i)) for i in range(4)])
    assert len(pairs) == 6
    assert len({frozenset((p["left"]["invoice_id"], p["right"]["invoice_id"])) for p in pairs}) == 6


@pytest.mark.parametrize("threshold", [0.54, 1.1, float("nan")])
def test_bad_threshold(threshold):
    with pytest.raises(ValueError):
        find_duplicates([], threshold)


def test_bad_window():
    with pytest.raises(ValueError):
        find_duplicates([], date_window=-1)


def test_csv_errors(tmp_path):
    path = write_csv(tmp_path / "input.csv", [
        ["A", "Acme", "10.50", "2026-01-01", "hello, world"],
        ["B", "Acme", "10", "2026-02-30", ""],
        ["C", "Acme", "nope", "2026-01-01", ""],
        ["D", "", "10", "2026-01-01", ""], ["E", "Acme"],
        ["F", "Acme", "NaN", "2026-01-01", ""],
        ["G", "Acme", "10", "20260101", ""],
        ["H", "Acme", "Infinity", "2026-01-01", ""],
        ["I", "Acme", "1e999999", "2026-01-01", ""],
        ["J", "Acme", "1e-999999", "2026-01-01", ""],
        ["K", "Acme", "-10", "2026-01-01", "valid credit"]])
    rows, errors = read_csv(path)
    assert len(rows) == 2 and len(errors) == 9
    assert rows[0].amount == Decimal("10.50")
    assert rows[0].description == "hello, world"
    assert errors[0]["row"] == 3
    assert all(e["source"] == str(path) and e["error"] for e in errors)


@pytest.mark.parametrize("content,count", [("", 1), ("invoice_id,vendor\nA,B\n", 1),
    ("invoice_id,vendor,amount,date,date\n", 1),
    ('invoice_id,vendor,amount,date\nA,Acme,1,2026-01-01\n"broken', 1)])
def test_bad_headers_and_quoting(tmp_path, content, count):
    path = tmp_path / "bad.csv"
    path.write_text(content, encoding="utf-8")
    assert len(read_csv(path)[1]) == count


def test_optional_description_bom(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("invoice_id,vendor,amount,date\nA,Acme,1,2026-01-01\n", encoding="utf-8-sig")
    rows, errors = read_csv(path)
    assert not errors and rows[0].description == ""


@pytest.mark.parametrize("key", [None, "invalid", "", "demo.bad", "é.bad", ".bad", "x.y.z"])
def test_free(key, tmp_path, capsys):
    path = write_csv(tmp_path / "many.csv", [[str(i), "Acme", "100", "2026-01-01", ""] for i in range(202)])
    args = ["scan", str(path), "--format", "json"]
    if key is not None:
        args += ["--license-key", key]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["rows_scanned"] == 200
    assert report["summary"]["rows_skipped_cap"] == 2
    assert len(report["pairs"]) == 5
    assert report["summary"]["pairs_hidden"] == 19895


def test_paid(tmp_path, capsys):
    assert valid_license(KEY) and issue_license("demo") == KEY
    assert not valid_license(KEY[:-1] + "0")
    path = write_csv(tmp_path / "many.csv", [[str(i), "Acme", "100", "2026-01-01", ""] for i in range(201)])
    assert main(["scan", str(path), "--format", "json", "--license-key", KEY]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["rows_scanned"] == 201
    assert report["summary"]["rows_skipped_cap"] == 0
    assert len(report["pairs"]) == 20100


def test_batch(tmp_path, capsys):
    write_csv(tmp_path / "a.csv", [["A", "Acme", "100", "2026-01-01", ""]])
    write_csv(tmp_path / "b.CSV", [["B", "Acme LLC", "100", "2026-01-01", ""]])
    (tmp_path / "ignored.txt").write_text("ignored")
    assert main(["batch", str(tmp_path), "--format", "json"]) == 2
    assert "license" in json.loads(capsys.readouterr().out)["error"]
    assert main(["batch", str(tmp_path), "--format", "json", "--license-key", KEY]) == 0
    report = json.loads(capsys.readouterr().out)
    pair, = report["pairs"]
    assert pair["left"]["source"] != pair["right"]["source"]
    assert pair["severity"] == "HIGH"


def test_ranking_and_error_accounting(tmp_path):
    path = write_csv(tmp_path / "mixed.csv", [[str(i), "Acme", "100", "2026-01-01", ""] for i in range(8)] +
                     [["7", "Zzzzz", "900", "2020-01-01", ""], ["bad"]])
    report = scan_files([path])
    assert report["pairs"][0]["reason"] == "exact-id"
    assert report["summary"]["malformed_rows"] == 1
    assert report["summary"]["rows_scanned"] == 9


def test_cli_errors_and_text(tmp_path, capsys):
    assert main(["scan", str(tmp_path / "missing.csv")]) == 2
    assert "invoiceguard:" in capsys.readouterr().err
    assert main(["batch", str(tmp_path), "--license-key", KEY]) == 2
    assert "no CSV" in capsys.readouterr().err
    path = write_csv(tmp_path / "a.csv", [["A", "Acme", "100", "2026-01-01", ""], ["B", "Acme", "100", "2026-01-01", ""]])
    assert main(["scan", str(path)]) == 0
    output = capsys.readouterr().out
    assert "HIGH fuzzy score=1.000" in output and "2 rows scanned" in output
    result = subprocess.run([sys.executable, "-m", "invoiceguard", "scan", str(path), "--format", "json"], capture_output=True, text=True)
    assert result.returncode == 0
    assert len(json.loads(result.stdout)["pairs"]) == 1
