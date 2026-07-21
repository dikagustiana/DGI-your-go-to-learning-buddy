"""Per-page review / QA view (milestone 3).

Side-by-side: the (rotation-corrected) page image on the left, the
extracted table on the right — editable, because finance tie-out demands
a human pass over OCR output before anything is exported.

Cell colors:
  amber  — OCR confidence below the threshold, needs a human look
  green  — human-edited (trusted; overrides the amber flag)

Every user action (cell edit, doc-type label, reviewed toggle) mutates
the PageResult in place and emits ``result_changed`` so the main window
can refresh the page list and the session store (milestone 4) can
persist it. Rotation override is different: the displayed image rotates
immediately, but the grid was extracted at the old rotation, so a stale
banner appears and ``request_reocr`` asks the main window to re-run that
single page at the chosen rotation.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.config import PipelineConfig
from app.gui.qt_utils import ndarray_to_pixmap
from app.locale_id import parse_id_number
from app.pipeline import orientation, pdf_loader
from app.pipeline.models import Cell, PageResult

LOW_CONF_COLOR = QColor("#FFF3CD")   # amber — needs review
EDITED_COLOR = QColor("#D4EDDA")     # green — human-corrected
PREVIEW_DPI = 110


class ReviewView(QWidget):
    #: the page's PageResult was mutated (edit / label / reviewed toggle)
    result_changed = Signal(object)
    #: user asked to re-run OCR: (page_number, rotation_degrees_cw)
    request_reocr = Signal(int, int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pdf_path: str | None = None
        self._result: PageResult | None = None
        self._page_number: int | None = None
        self._populating = False
        self._threshold = PipelineConfig().low_confidence_threshold
        self._build_ui()
        self.set_page(None, None, None)

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        # Controls row
        self.rotation_combo = QComboBox()
        self.rotation_combo.addItems(["0", "90", "180", "270"])
        self.rotation_combo.setToolTip(
            "Manual rotation override for this page (degrees clockwise). "
            "The image updates immediately; re-run OCR to update the table.")
        self.rotation_combo.currentTextChanged.connect(self._on_rotation_changed)

        self.reocr_btn = QPushButton("Re-run OCR at this rotation")
        self.reocr_btn.clicked.connect(self._on_reocr_clicked)

        self.label_combo = QComboBox()
        self.label_combo.setEditable(True)
        self.label_combo.setMinimumWidth(180)
        self.label_combo.setToolTip(
            "Document type of this page (e.g. rekening koran, faktur, "
            "nota debet). Used to group pages in merged exports.")
        self.label_combo.currentTextChanged.connect(self._on_label_changed)

        self.reviewed_check = QCheckBox("Reviewed")
        self.reviewed_check.setToolTip(
            "Tick after checking the table against the page image. "
            "Export warns while pages remain unreviewed.")
        self.reviewed_check.toggled.connect(self._on_reviewed_toggled)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Rotation:"))
        controls.addWidget(self.rotation_combo)
        controls.addWidget(self.reocr_btn)
        controls.addSpacing(24)
        controls.addWidget(QLabel("Document type:"))
        controls.addWidget(self.label_combo)
        controls.addStretch(1)
        controls.addWidget(self.reviewed_check)

        # Stale-grid banner (hidden unless rotation differs from the grid's)
        self.stale_banner = QLabel()
        self.stale_banner.setStyleSheet(
            "background:#FFF3CD; padding:4px; border:1px solid #E0C060;")
        self.stale_banner.setVisible(False)

        # Image side
        self.image_label = QLabel("No page selected.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.setWidgetResizable(True)

        # Table side
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._on_item_changed)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.image_scroll)
        split.addWidget(self.table)
        split.setSizes([520, 520])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(controls)
        lay.addWidget(self.stale_banner)
        lay.addWidget(split, 1)

    # ------------------------------------------------------------- state

    def set_known_labels(self, labels: list[str]) -> None:
        """Refresh the doc-type dropdown choices, keeping the current text."""
        self._populating = True
        try:
            current = self.label_combo.currentText()
            self.label_combo.clear()
            self.label_combo.addItems([""] + sorted(l for l in labels if l))
            self.label_combo.setCurrentText(current)
        finally:
            self._populating = False

    def set_page(self, pdf_path: str | None, page_number: int | None,
                 result: PageResult | None) -> None:
        """Bind the view to a page (or clear it with Nones)."""
        self._populating = True
        try:
            self._pdf_path = pdf_path
            self._page_number = page_number
            self._result = result

            has_page = pdf_path is not None and page_number is not None
            for w in (self.rotation_combo, self.reocr_btn, self.label_combo,
                      self.reviewed_check, self.table):
                w.setEnabled(has_page and result is not None and not result.error)
            self.rotation_combo.setEnabled(has_page)
            self.reocr_btn.setEnabled(has_page)

            rot = result.rotation_applied if result else 0
            self.rotation_combo.setCurrentText(str(rot % 360))
            self.label_combo.setCurrentText(result.doc_type_label if result else "")
            self.reviewed_check.setChecked(bool(result and result.reviewed))
            self.stale_banner.setVisible(False)
        finally:
            self._populating = False

        self._render_image()
        self._populate_table()

    def set_busy(self, busy: bool) -> None:
        """Disable interaction while a (re-)OCR run is in flight."""
        self.setEnabled(not busy)

    def current_rotation(self) -> int:
        return int(self.rotation_combo.currentText())

    def has_edits(self) -> bool:
        if not self._result:
            return False
        return any(c.edited for row in self._result.grid for c in row if c)

    # ----------------------------------------------------------- image

    def _render_image(self) -> None:
        if not self._pdf_path or self._page_number is None:
            self.image_label.clear()
            self.image_label.setText("No page selected.")
            return
        try:
            image = pdf_loader.rasterize_page(
                self._pdf_path, self._page_number, dpi=PREVIEW_DPI)
            rot = self.current_rotation()
            if rot:
                image = orientation.rotate_image(image, rot)
            pixmap = ndarray_to_pixmap(image)
            self.image_label.setPixmap(pixmap.scaled(
                self.image_scroll.viewport().size() * 0.98,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        except Exception as exc:
            self.image_label.setText(f"Preview failed: {exc}")

    # ----------------------------------------------------------- table

    def _style_item(self, item: QTableWidgetItem, cell: Cell) -> None:
        tip = f"confidence {cell.confidence:.2f}"
        if cell.value is not None:
            tip += f" — parsed: {cell.value}"
        if cell.edited:
            tip += " — edited by reviewer"
            item.setBackground(EDITED_COLOR)
        elif cell.confidence < self._threshold:
            item.setBackground(LOW_CONF_COLOR)
        else:
            item.setBackground(QColor("transparent"))
        item.setToolTip(tip)

    def _populate_table(self) -> None:
        self._populating = True
        try:
            self.table.clear()
            result = self._result
            if not result or not result.grid:
                self.table.setRowCount(0)
                self.table.setColumnCount(0)
                return
            n_cols = result.n_cols
            self.table.setRowCount(result.n_rows)
            self.table.setColumnCount(n_cols)
            for r, row in enumerate(result.grid):
                for c in range(n_cols):
                    cell = row[c] if c < len(row) else None
                    item = QTableWidgetItem(cell.raw if cell else "")
                    if cell:
                        self._style_item(item, cell)
                    self.table.setItem(r, c, item)
            self.table.resizeColumnsToContents()
        finally:
            self._populating = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._populating or not self._result:
            return
        r, c = item.row(), item.column()
        grid = self._result.grid
        if r >= len(grid):
            return
        row = grid[r]
        while len(row) <= c:  # pad ragged rows so the edit has a slot
            row.append(None)

        text = item.text().strip()
        cell = row[c]
        if cell is None:
            if not text:
                return
            cell = Cell(raw=text, confidence=1.0,
                        value=parse_id_number(text).value, edited=True)
            row[c] = cell
        else:
            if text == cell.raw:
                return
            cell.raw = text
            cell.value = parse_id_number(text).value
            cell.edited = True

        self._populating = True
        try:
            self._style_item(item, cell)
        finally:
            self._populating = False
        self.result_changed.emit(self._result)

    # --------------------------------------------------------- controls

    def _on_rotation_changed(self, _text: str) -> None:
        if self._populating:
            return
        self._render_image()
        if self._result and not self._result.error:
            stale = self.current_rotation() != self._result.rotation_applied % 360
            self.stale_banner.setText(
                f"⚠ The table below was extracted at "
                f"{self._result.rotation_applied}° — press “Re-run OCR at "
                f"this rotation” to update it.")
            self.stale_banner.setVisible(stale)

    def _on_reocr_clicked(self) -> None:
        if self._page_number is not None:
            self.request_reocr.emit(self._page_number, self.current_rotation())

    def _on_label_changed(self, text: str) -> None:
        if self._populating or not self._result:
            return
        if self._result.doc_type_label != text:
            self._result.doc_type_label = text
            self.result_changed.emit(self._result)

    def _on_reviewed_toggled(self, checked: bool) -> None:
        if self._populating or not self._result:
            return
        if self._result.reviewed != checked:
            self._result.reviewed = checked
            self.result_changed.emit(self._result)

    # ----------------------------------------------------------- events

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_image()
