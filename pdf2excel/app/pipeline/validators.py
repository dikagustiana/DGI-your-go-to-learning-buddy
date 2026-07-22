"""Per-document-type validators (tie-out rules).

A validator receives a page grid and returns anomalies for rows that
break an accounting identity. Validators are selected by the page's
``doc_type_label`` — no single global schema is assumed. They are
deliberately conservative: when the grid's shape doesn't clearly match
the rule (columns can't be identified confidently), they stay silent
rather than spraying false alarms.

Registering a new rule:

    @register(lambda label: "faktur" in label.lower())
    def my_validator(grid): ...
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable, Optional

from app.pipeline.models import Anomaly, Cell

Grid = list[list[Optional[Cell]]]
Validator = Callable[[Grid], list[Anomaly]]

_REGISTRY: list[tuple[Callable[[str], bool], Validator]] = []


def register(matches: Callable[[str], bool]):
    def deco(fn: Validator) -> Validator:
        _REGISTRY.append((matches, fn))
        return fn
    return deco


def validators_for(doc_type_label: str) -> list[Validator]:
    label = (doc_type_label or "").lower()
    return [fn for matches, fn in _REGISTRY if matches(label)]


def run_validators(doc_type_label: str, grid: Grid) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    for fn in validators_for(doc_type_label):
        try:
            anomalies.extend(fn(grid))
        except Exception:
            # A broken validator must never take down extraction.
            anomalies.append(Anomaly(
                code="validator-error", severity="warning",
                message=f"Pemeriksa aturan “{fn.__name__}” gagal dijalankan."))
    return anomalies


# --------------------------------------------------------------- helpers

def _value(grid: Grid, r: int, c: int) -> Optional[Decimal]:
    if 0 <= r < len(grid) and 0 <= c < len(grid[r]):
        cell = grid[r][c]
        if cell is not None:
            return cell.value
    return None


def _numeric_cols(grid: Grid) -> list[int]:
    n_cols = max((len(r) for r in grid), default=0)
    cols = []
    for c in range(n_cols):
        vals = sum(1 for row in grid
                   if c < len(row) and row[c] is not None
                   and row[c].value is not None)
        if vals >= 3:
            cols.append(c)
    return cols


# ------------------------------------------------------------ validators

@register(lambda label: "rekening" in label or "koran" in label
          or "statement" in label)
def running_balance(grid: Grid) -> list[Anomaly]:
    """rekening koran: saldo[i] must equal saldo[i-1] ± mutasi[i].

    Column roles are inferred: the RIGHTMOST numeric column is the
    balance; any other numeric column may be the movement. The rule
    only fires when most consecutive row pairs satisfy it — if fewer
    than 60% do, the layout probably doesn't match and we stay silent.
    """
    cols = _numeric_cols(grid)
    if len(cols) < 2:
        return []
    saldo_col = cols[-1]
    movement_cols = cols[:-1]

    checks: list[tuple[int, bool]] = []   # (row, ok)
    prev_saldo: Optional[Decimal] = None
    prev_row = -1
    for r in range(len(grid)):
        saldo = _value(grid, r, saldo_col)
        if saldo is None:
            continue
        if prev_saldo is not None:
            delta = saldo - prev_saldo
            movements = [m for c in movement_cols
                         if (m := _value(grid, r, c)) is not None]
            ok = (delta == 0 and not movements) or any(
                delta == m or delta == -m for m in movements)
            checks.append((r, ok))
        prev_saldo, prev_row = saldo, r

    if len(checks) < 3:
        return []
    ok_share = sum(1 for _, ok in checks if ok) / len(checks)
    if ok_share < 0.6:
        return []   # layout doesn't match the rule — don't guess
    return [Anomaly(
        code="balance-mismatch", row=r, col=saldo_col, severity="blocker",
        message="Saldo baris ini tidak cocok dengan saldo sebelumnya "
                "± mutasi — kemungkinan ada digit salah baca.")
        for r, ok in checks if not ok]


@register(lambda label: any(k in label for k in
                            ("faktur", "invoice", "klaim", "nota")))
def detail_total(grid: Grid) -> list[Anomaly]:
    """Rows whose text mentions total must equal the sum of the numeric
    cells above them (since the previous total) in the same column."""
    anomalies: list[Anomaly] = []
    n_cols = max((len(r) for r in grid), default=0)

    def row_text(r: int) -> str:
        return " ".join(cell.effective_text for cell in grid[r]
                        if cell is not None).lower()

    for c in _numeric_cols(grid):
        run: list[Decimal] = []
        for r in range(len(grid)):
            v = _value(grid, r, c)
            if "total" in row_text(r) or "jumlah" in row_text(r):
                if v is not None and len(run) >= 2 and sum(run) != v:
                    anomalies.append(Anomaly(
                        code="total-mismatch", row=r, col=c,
                        severity="blocker",
                        message="Nilai total tidak sama dengan jumlah "
                                "rinciannya — periksa angka di kolom ini."))
                run = []
            elif v is not None:
                run.append(v)
    return anomalies
