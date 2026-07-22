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
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSlider, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.config import PipelineConfig
from app.gui.qt_utils import ndarray_to_pixmap
from app.pipeline import orientation, pdf_loader
from app.pipeline.models import Cell, PageResult

LOW_CONF_COLOR = QColor("#FFF3CD")   # amber — needs review
EDITED_COLOR = QColor("#D4EDDA")     # green — human-corrected
ANOMALY_COLOR = QColor("#F8D7DA")    # red — anomaly flagged
LEGACY_COLOR = QColor("#E2E3E5")     # gray — OCR original lost (legacy)
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
        from app.pipeline.models import local_reviewer
        self._reviewer = local_reviewer()
        self._highlight_bbox: tuple[float, float, float, float] | None = None
        # (row, col, previous ocr_original/corrected snapshot) for undo
        self._undo: tuple[int, int, dict] | None = None
        self._build_ui()
        self.set_page(None, None, None)

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        # Controls row
        self.rotation_combo = QComboBox()
        self.rotation_combo.addItems(["0", "90", "180", "270"])
        self.rotation_combo.setToolTip(
            "Memutar tampilan halaman ini (derajat, searah jarum jam). "
            "Gambar langsung berubah; tekan “Baca ulang halaman ini” "
            "untuk memperbarui tabelnya.")
        self.rotation_combo.currentTextChanged.connect(self._on_rotation_changed)

        self.reocr_btn = QPushButton("Baca ulang halaman ini")
        self.reocr_btn.clicked.connect(self._on_reocr_clicked)

        self.label_combo = QComboBox()
        self.label_combo.setEditable(True)
        self.label_combo.setMinimumWidth(180)
        self.label_combo.setToolTip(
            "Jenis dokumen halaman ini (mis. rekening koran, faktur, "
            "nota debet). Dipakai untuk mengelompokkan halaman saat "
            "diekspor ke Excel.")
        self.label_combo.currentTextChanged.connect(self._on_label_changed)

        self.reviewed_check = QCheckBox("Sudah diperiksa")
        self.reviewed_check.setToolTip(
            "Centang setelah tabel dicocokkan dengan gambar halamannya.")
        self.reviewed_check.toggled.connect(self._on_reviewed_toggled)

        self.next_issue_btn = QPushButton("Masalah berikutnya")
        self.next_issue_btn.setToolTip(
            "Loncat ke sel berikutnya yang perlu dicek (kuning/merah).")
        self.next_issue_btn.clicked.connect(self.goto_next_issue)

        self.undo_btn = QPushButton("Batalkan koreksi terakhir")
        self.undo_btn.clicked.connect(self.undo_last_edit)
        self.undo_btn.setEnabled(False)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Putar halaman:"))
        controls.addWidget(self.rotation_combo)
        controls.addWidget(self.reocr_btn)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Jenis dokumen:"))
        controls.addWidget(self.label_combo)
        controls.addWidget(self.next_issue_btn)
        controls.addWidget(self.undo_btn)
        controls.addStretch(1)
        controls.addWidget(self.reviewed_check)

        # Zoom control for the page image (reduced-eyesight friendly).
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(50, 300)   # percent of fit-to-pane
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(160)
        self.zoom_slider.valueChanged.connect(lambda _v: self._render_image())
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("Perbesar gambar:"))
        zoom_row.addWidget(self.zoom_slider)
        zoom_row.addStretch(1)

        # Stale-grid banner (hidden unless rotation differs from the grid's)
        self.stale_banner = QLabel()
        self.stale_banner.setStyleSheet(
            "background:#FFF3CD; padding:4px; border:1px solid #E0C060;")
        self.stale_banner.setVisible(False)

        # Image side (zoomable, scrollable; clicked cell draws a box here)
        self.image_label = QLabel("Belum ada halaman dipilih.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.setWidgetResizable(True)

        # Table side
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(self._on_current_cell_changed)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.image_scroll)
        split.addWidget(self.table)
        split.setSizes([520, 520])

        legend = QLabel(
            "Keterangan warna: kuning = kurang yakin · merah = perlu "
            "dicek · hijau = sudah dikoreksi · abu-abu = OCR asli hilang.")
        legend.setWordWrap(True)
        legend.setStyleSheet("color:#45505c;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(controls)
        lay.addLayout(zoom_row)
        lay.addWidget(self.stale_banner)
        lay.addWidget(split, 1)
        lay.addWidget(legend)

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

            self._highlight_bbox = None
            self._undo = None

            has_page = pdf_path is not None and page_number is not None
            usable = has_page and result is not None and not result.error
            for w in (self.rotation_combo, self.reocr_btn, self.label_combo,
                      self.reviewed_check, self.table, self.next_issue_btn,
                      self.zoom_slider):
                w.setEnabled(usable)
            self.rotation_combo.setEnabled(has_page)
            self.reocr_btn.setEnabled(has_page)
            self.undo_btn.setEnabled(False)

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
            self.image_label.setText("Belum ada halaman dipilih.")
            return
        try:
            image = pdf_loader.rasterize_page(
                self._pdf_path, self._page_number, dpi=PREVIEW_DPI)
            rot = self.current_rotation()
            if rot:
                image = orientation.rotate_image(image, rot)
            pixmap = ndarray_to_pixmap(image)

            # Draw the selected cell's source box (bbox is in the
            # extraction-DPI space of the un-scaled, rotation-applied
            # image; scale to preview DPI). Only meaningful when the
            # displayed rotation matches the grid's.
            src_dpi = self._result.dpi if self._result else 0
            if (self._highlight_bbox and src_dpi
                    and rot == (self._result.rotation_applied % 360)):
                scale = PREVIEW_DPI / src_dpi
                x0, y0, x1, y1 = (v * scale for v in self._highlight_bbox)
                painter = QPainter(pixmap)
                pen = QPen(QColor("#0b5cad"))
                pen.setWidth(3)
                painter.setPen(pen)
                painter.drawRect(int(x0), int(y0),
                                 int(x1 - x0), int(y1 - y0))
                painter.end()

            zoom = self.zoom_slider.value() / 100.0
            target = self.image_scroll.viewport().size() * 0.98 * zoom
            self.image_label.setPixmap(pixmap.scaled(
                target, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        except Exception as exc:
            self.image_label.setText(f"Gambar tidak bisa ditampilkan: {exc}")

    def _on_current_cell_changed(self, row: int, col: int, *_a) -> None:
        """Highlight the source region of the selected cell on the image."""
        if not self._result or row < 0 or col < 0:
            self._highlight_bbox = None
            return
        cell = None
        if row < len(self._result.grid) and col < len(self._result.grid[row]):
            cell = self._result.grid[row][col]
        self._highlight_bbox = cell.bbox if cell else None
        self._render_image()

    # ----------------------------------------- issue navigation / undo

    def _issue_positions(self) -> list[tuple[int, int]]:
        """(row, col) of every cell worth a human look, in reading order."""
        if not self._result:
            return []
        anomaly_cells = self._anomaly_cells()
        out: list[tuple[int, int]] = []
        for r, row in enumerate(self._result.grid):
            for c, cell in enumerate(row):
                if cell is None or cell.edited:
                    continue
                if ((r, c) in anomaly_cells
                        or cell.confidence < self._threshold
                        or cell.legacy_audit_incomplete):
                    out.append((r, c))
        return out

    def goto_next_issue(self) -> None:
        issues = self._issue_positions()
        if not issues:
            self.stale_banner.setText(
                "✓ Tidak ada lagi sel yang perlu dicek di halaman ini.")
            self.stale_banner.setVisible(True)
            return
        cur = (self.table.currentRow(), self.table.currentColumn())
        nxt = next((p for p in issues if p > cur), issues[0])
        self.table.setCurrentCell(*nxt)
        self.table.scrollToItem(self.table.item(*nxt))

    def undo_last_edit(self) -> None:
        if not self._undo or not self._result:
            return
        r, c, snap = self._undo
        if r < len(self._result.grid) and c < len(self._result.grid[r]):
            cell = self._result.grid[r][c]
            if cell is not None:
                cell.corrected_text = snap["corrected_text"]
                cell.edited = snap["edited"]
                cell.edited_at = snap["edited_at"]
                cell.reviewer = snap["reviewer"]
                from app.locale_id import parse_id_number
                p = parse_id_number(cell.effective_text)
                cell.value, cell.parse_kind, cell.parse_reason = (
                    p.value, p.kind, p.reason)
        self._undo = None
        self.undo_btn.setEnabled(False)
        self._recompute_anomalies()
        self._populate_table()
        self.result_changed.emit(self._result)

    # ----------------------------------------------------------- table

    def _anomaly_cells(self) -> set[tuple[int, int]]:
        if not self._result:
            return set()
        return {(a.row, a.col) for a in self._result.anomalies
                if a.row is not None and a.col is not None}

    def _style_item(self, item: QTableWidgetItem, cell: Cell,
                    anomaly: bool = False) -> None:
        tip = f"tingkat keyakinan {cell.confidence:.2f}"
        if cell.value is not None:
            tip += f" — terbaca sebagai angka: {cell.value}"
        if cell.ocr_original is not None and cell.corrected_text is not None:
            tip += f" — OCR asli: “{cell.ocr_original}”"
        # Status is shown by BOTH background color and a text marker
        # prefix in the tooltip, so it does not rely on color alone.
        marker = ""
        if cell.edited:
            marker = "[dikoreksi] "
            item.setBackground(EDITED_COLOR)
        elif anomaly:
            marker = "[perlu dicek] "
            item.setBackground(ANOMALY_COLOR)
        elif cell.legacy_audit_incomplete:
            marker = "[OCR asli hilang] "
            item.setBackground(LEGACY_COLOR)
        elif cell.confidence < self._threshold:
            marker = "[kurang yakin] "
            item.setBackground(LOW_CONF_COLOR)
        else:
            item.setBackground(QColor("transparent"))
        item.setToolTip(marker + tip)

    def _populate_table(self) -> None:
        self._populating = True
        try:
            self.table.clear()
            result = self._result
            if not result or not result.grid:
                self.table.setRowCount(0)
                self.table.setColumnCount(0)
                return
            anomaly_cells = self._anomaly_cells()
            n_cols = result.n_cols
            self.table.setRowCount(result.n_rows)
            self.table.setColumnCount(n_cols)
            for r, row in enumerate(result.grid):
                for c in range(n_cols):
                    cell = row[c] if c < len(row) else None
                    item = QTableWidgetItem(cell.effective_text if cell else "")
                    if cell:
                        self._style_item(item, cell, (r, c) in anomaly_cells)
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
            # Human typed into an empty slot: no OCR source exists.
            self._undo = (r, c, {"corrected_text": None, "edited": False,
                                 "edited_at": None, "reviewer": ""})
            cell = Cell.human_created(text, reviewer=self._reviewer)
            row[c] = cell
        else:
            if text == cell.effective_text:
                return
            # Snapshot for undo, then record the correction WITHOUT
            # overwriting ocr_original.
            self._undo = (r, c, {"corrected_text": cell.corrected_text,
                                 "edited": cell.edited,
                                 "edited_at": cell.edited_at,
                                 "reviewer": cell.reviewer})
            cell.apply_correction(text, reviewer=self._reviewer)
        self.undo_btn.setEnabled(True)

        self._recompute_anomalies()
        self._populating = True
        try:
            self._style_item(item, cell, False)
        finally:
            self._populating = False
        self.result_changed.emit(self._result)

    def _recompute_anomalies(self) -> None:
        """Edits can clear or introduce anomalies; keep them current."""
        if self._result:
            from app.pipeline.runner import refresh_anomalies
            refresh_anomalies(self._result)

    # --------------------------------------------------------- controls

    def _on_rotation_changed(self, _text: str) -> None:
        if self._populating:
            return
        self._render_image()
        if self._result and not self._result.error:
            stale = self.current_rotation() != self._result.rotation_applied % 360
            self.stale_banner.setText(
                f"⚠ Tabel di bawah dibaca saat posisi halaman "
                f"{self._result.rotation_applied}° — tekan “Baca ulang "
                f"halaman ini” untuk memperbaruinya.")
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
        # A page whose grid is stale (rotation changed but not re-read)
        # must not be marked reviewed — the reviewer would be signing
        # off on a table that no longer matches the image.
        if checked and not self.stale_banner.isHidden():
            self._populating = True
            self.reviewed_check.setChecked(False)
            self._populating = False
            self.stale_banner.setText(
                "⚠ Baca ulang halaman ini dulu sebelum menandainya "
                "sudah diperiksa — tabelnya belum sesuai posisi gambar.")
            self.stale_banner.setVisible(True)
            return
        if self._result.reviewed != checked:
            self._result.set_reviewed(checked)
            self.result_changed.emit(self._result)

    # ----------------------------------------------------------- events

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_image()
