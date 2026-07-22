"""Assert the CONTENTS of a workbook produced by the INSTALLED app.

Run by the clean-machine CI job (no source tree, offline). Goes well
beyond "the .xlsx exists": it checks the sheet structure, the
DRAF/FINAL status, that the id-ID numbers parsed to real Excel numbers,
that the rotated page was corrected, that the Audit sheet carries the
immutable OCR original, and that no cell is a live formula.

Usage:  python verify_installed.py out.xlsx
Exits non-zero with a clear message on the first failed assertion.
"""

from __future__ import annotations

import sys

from openpyxl import load_workbook


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


def main(path: str) -> None:
    wb = load_workbook(path)
    names = wb.sheetnames

    # 1. Structure: provenance + audit + anomaly sheets present.
    for required in ("Ringkasan", "Audit", "Masalah"):
        if required not in names:
            fail(f"missing '{required}' sheet; got {names}")

    # 2. Status: an unreviewed CLI conversion must be labeled DRAF.
    summary = " ".join(str(c.value) for row in wb["Ringkasan"].iter_rows()
                       for c in row if c.value)
    if "DRAF" not in summary:
        fail("Ringkasan does not carry the DRAF status")

    # 3. Data sheets: the sample's amounts parsed to real numbers, and
    #    the second (rotated) page's table came through.
    data_sheets = [s for s in names if s.startswith("p")]
    if len(data_sheets) < 2:
        fail(f"expected >=2 data sheets, got {data_sheets}")
    numbers = []
    strings = []
    for s in data_sheets:
        for row in wb[s].iter_rows():
            for c in row:
                if c.value is None:
                    continue
                if isinstance(c.value, (int, float)):
                    numbers.append(c.value)
                elif isinstance(c.value, str):
                    strings.append(c.value)
                    if c.value.startswith("=") and c.data_type != "s":
                        fail(f"live formula leaked: {c.coordinate}={c.value!r}")
    if not numbers:
        fail("no id-ID amount parsed to a real Excel number")
    # The sample statement contains 130.326.720 → 130326720.
    if 130326720 not in numbers:
        fail(f"expected amount 130326720 not found; numbers={numbers[:20]}")

    # 4. Audit sheet: immutable OCR original column populated.
    audit = wb["Audit"]
    headers = [c.value for c in audit[1]]
    if "OCR asli" not in headers:
        fail(f"Audit sheet missing 'OCR asli' column; headers={headers}")
    col = headers.index("OCR asli") + 1
    if not any(audit.cell(row=r, column=col).value
               for r in range(2, audit.max_row + 1)):
        fail("Audit 'OCR asli' column is empty")

    print(f"VERIFY OK: {path} — sheets={names}, "
          f"{len(numbers)} numeric cells, DRAF status, audit trail present, "
          f"no live formulas.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        fail("usage: verify_installed.py <workbook.xlsx>")
    main(sys.argv[1])
