"""Main application window (milestone 2).

Layout:
  toolbar   Open PDF… | Run OCR | Cancel | Export…   [engine] [DPI] [rotation] [layout]
  splitter  page list | (page image preview / extracted grid preview)
  statusbar progress bar + message

The preview pane here is read-only; milestone 3 turns it into the full
QA view (editable cells, rotation override, doc-type labels). OCR always
runs in a QThread via OcrWorker — the UI thread never touches the
pipeline directly.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QScrollArea, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout,
    QWidget,
)

from app.config import PipelineConfig
from app.gui.qt_utils import ndarray_to_pixmap
from app.gui.worker import OcrWorker
from app.pipeline import orientation, pdf_loader
from app.pipeline.engines import ENGINES, available_engines
from app.pipeline.models import PageResult

LOW_CONF_COLOR = QColor("#FFF3CD")   # matches the export highlight
ERROR_COLOR = QColor("#F8D7DA")
PREVIEW_DPI = 110                    # quick render for the preview pane


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pdf2excel — scanned PDF → Excel (offline)")
        self.resize(1280, 800)

        self._pdf_path: str | None = None
        self._pdf_info: pdf_loader.PdfInfo | None = None
        self._results: dict[int, PageResult] = {}   # page number → result
        self._thread: QThread | None = None
        self._worker: OcrWorker | None = None

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._update_actions()

    # ---------------------------------------------------------------- UI

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self.act_open = QAction("Open PDF…", self)
        self.act_open.triggered.connect(self.open_pdf)
        tb.addAction(self.act_open)

        self.act_run = QAction("Run OCR", self)
        self.act_run.triggered.connect(self.run_ocr)
        tb.addAction(self.act_run)

        self.act_cancel = QAction("Cancel", self)
        self.act_cancel.triggered.connect(self.cancel_ocr)
        tb.addAction(self.act_cancel)

        self.act_export = QAction("Export…", self)
        self.act_export.triggered.connect(self.export_xlsx)
        tb.addAction(self.act_export)

        tb.addSeparator()

        tb.addWidget(QLabel(" Engine: "))
        self.engine_combo = QComboBox()
        avail = available_engines()
        for name, cls in ENGINES.items():
            self.engine_combo.addItem(name)
            idx = self.engine_combo.count() - 1
            if not avail[name]:
                # Graceful degradation: visible but disabled, with a
                # tooltip explaining how to enable it.
                model = self.engine_combo.model()
                item = model.item(idx)
                item.setEnabled(False)
                item.setToolTip(f"Not installed — {cls.unavailable_hint()}")
        tb.addWidget(self.engine_combo)

        tb.addWidget(QLabel(" DPI: "))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(150, 600)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(300)
        self.dpi_spin.setToolTip(
            "OCR rendering resolution. 300 is the validated default; "
            "150 was too noisy for dense tables.")
        tb.addWidget(self.dpi_spin)

        tb.addWidget(QLabel(" Rotation: "))
        self.rotation_combo = QComboBox()
        self.rotation_combo.addItems(["auto", "0", "90", "180", "270"])
        self.rotation_combo.setToolTip(
            "auto = detect per page; a number forces that rotation "
            "for every page (per-page override arrives with the QA view).")
        tb.addWidget(self.rotation_combo)

        tb.addWidget(QLabel(" Layout: "))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["sheet_per_page", "merged_by_label"])
        tb.addWidget(self.layout_combo)

    def _build_central(self) -> None:
        self.page_list = QListWidget()
        self.page_list.currentItemChanged.connect(self._show_selected_page)

        self.image_label = QLabel("Open a PDF to begin.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.image_label)
        scroll.setWidgetResizable(True)

        self.grid_table = QTableWidget()
        self.grid_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(scroll)
        right.addWidget(self.grid_table)
        right.setSizes([500, 300])

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.page_list)
        split.addWidget(right)
        split.setSizes([240, 1040])

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)
        self.setCentralWidget(container)

    def _build_statusbar(self) -> None:
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(300)
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("Ready.")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress_bar)

    def _update_actions(self) -> None:
        running = self._thread is not None
        self.act_open.setEnabled(not running)
        self.act_run.setEnabled(self._pdf_path is not None and not running)
        self.act_cancel.setEnabled(running)
        self.act_export.setEnabled(bool(self._results) and not running)
        for w in (self.engine_combo, self.dpi_spin,
                  self.rotation_combo, self.layout_combo):
            w.setEnabled(not running)

    # ------------------------------------------------------------ actions

    def open_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open scanned PDF", "", "PDF files (*.pdf)")
        if not path:
            return
        self.load_pdf(path)

    def load_pdf(self, path: str) -> None:
        try:
            info = pdf_loader.inspect_pdf(path)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open PDF", str(exc))
            return

        self._pdf_path = path
        self._pdf_info = info
        self._results.clear()
        self.grid_table.clear()
        self.grid_table.setRowCount(0)
        self.grid_table.setColumnCount(0)

        self.page_list.clear()
        for pno in range(1, info.n_pages + 1):
            item = QListWidgetItem(f"Page {pno} — pending")
            item.setData(Qt.ItemDataRole.UserRole, pno)
            self.page_list.addItem(item)
        if self.page_list.count():
            self.page_list.setCurrentRow(0)

        self.status_label.setText(
            f"{os.path.basename(path)} — {info.n_pages} page(s), "
            + ("native text layer" if info.has_text_layer
               else "image-only (OCR required)"))
        self._update_actions()

        if info.has_text_layer:
            QMessageBox.warning(
                self, "PDF already has a text layer",
                "This PDF contains selectable text, so it is probably not "
                "a scan. OCR will still work but is slower and less exact "
                "than reading the text layer directly.\n\n"
                "A direct-parse path for native PDFs is planned; for now "
                "you can continue with OCR.")

    def run_ocr(self) -> None:
        if not self._pdf_path or self._thread is not None:
            return
        self._results.clear()
        for i in range(self.page_list.count()):
            item = self.page_list.item(i)
            pno = item.data(Qt.ItemDataRole.UserRole)
            item.setText(f"Page {pno} — queued")
            item.setBackground(QColor("transparent"))

        config = self._current_config()
        self._worker = OcrWorker(self._pdf_path, config)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.page_done.connect(self._on_page_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, self.page_list.count())
        self.progress_bar.setValue(0)
        self._thread.start()
        self._update_actions()

    def cancel_ocr(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.status_label.setText(
                "Cancelling — finishing the current page…")

    def export_xlsx(self) -> None:
        if not self._results:
            return
        default = ""
        if self._pdf_path:
            default = os.path.splitext(self._pdf_path)[0] + ".xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel", default, "Excel workbook (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        from app.export.excel import export_workbook
        pages = [self._results[k] for k in sorted(self._results)]
        try:
            export_workbook(pages, path, self._current_config())
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.status_label.setText(f"Exported {len(pages)} page(s) → {path}")

    def _current_config(self) -> PipelineConfig:
        rot = self.rotation_combo.currentText()
        return PipelineConfig(
            dpi=self.dpi_spin.value(),
            engine=self.engine_combo.currentText(),
            rotation="auto" if rot == "auto" else int(rot),
            output_layout=self.layout_combo.currentText(),
        )

    # ------------------------------------------------------ worker slots

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self.status_label.setText(f"{message}  ({done}/{total})")

    def _on_page_done(self, result: PageResult) -> None:
        self._results[result.page_number] = result
        item = self._item_for_page(result.page_number)
        if item is not None:
            if result.error:
                item.setText(f"Page {result.page_number} — ERROR")
                item.setBackground(ERROR_COLOR)
            else:
                rot = (f", rot {result.rotation_applied}°"
                       if result.rotation_applied else "")
                item.setText(
                    f"Page {result.page_number} — "
                    f"{result.n_rows}×{result.n_cols}{rot}")
        current = self.page_list.currentItem()
        if current and current.data(Qt.ItemDataRole.UserRole) == result.page_number:
            self._show_selected_page(current, None)

    def _on_finished(self, results: list, was_cancelled: bool) -> None:
        self._teardown_thread()
        n_err = sum(1 for r in results if r.error)
        msg = f"{'Cancelled after' if was_cancelled else 'Finished'} " \
              f"{len(results)} page(s)"
        if n_err:
            msg += f" — {n_err} page(s) failed"
        self.progress_bar.setVisible(False)
        self.status_label.setText(msg + ".")
        self._update_actions()

    def _on_failed(self, message: str) -> None:
        self._teardown_thread()
        self.progress_bar.setVisible(False)
        self.status_label.setText("OCR failed.")
        self._update_actions()
        QMessageBox.critical(self, "OCR failed", message)

    def _teardown_thread(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
        if self._worker:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    # ---------------------------------------------------------- preview

    def _item_for_page(self, page_number: int) -> QListWidgetItem | None:
        for i in range(self.page_list.count()):
            item = self.page_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == page_number:
                return item
        return None

    def _show_selected_page(self, current: QListWidgetItem | None,
                            _previous: QListWidgetItem | None = None) -> None:
        if current is None or self._pdf_path is None:
            return
        pno = current.data(Qt.ItemDataRole.UserRole)
        result = self._results.get(pno)

        try:
            image = pdf_loader.rasterize_page(self._pdf_path, pno,
                                              dpi=PREVIEW_DPI)
            if result and result.rotation_applied:
                image = orientation.rotate_image(image, result.rotation_applied)
            pixmap = ndarray_to_pixmap(image)
            self.image_label.setPixmap(pixmap.scaled(
                self.image_label.parentWidget().size() * 0.98,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        except Exception as exc:
            self.image_label.setText(f"Preview failed: {exc}")

        self._populate_grid(result)

    def _populate_grid(self, result: PageResult | None) -> None:
        self.grid_table.clear()
        if result is None or not result.grid:
            self.grid_table.setRowCount(0)
            self.grid_table.setColumnCount(0)
            return
        threshold = PipelineConfig().low_confidence_threshold
        self.grid_table.setRowCount(result.n_rows)
        self.grid_table.setColumnCount(result.n_cols)
        for r, row in enumerate(result.grid):
            for c, cell in enumerate(row):
                if cell is None:
                    continue
                item = QTableWidgetItem(cell.raw)
                tip = f"confidence {cell.confidence:.2f}"
                if cell.value is not None:
                    tip += f" — parsed: {cell.value}"
                item.setToolTip(tip)
                if cell.confidence < threshold:
                    item.setBackground(LOW_CONF_COLOR)
                self.grid_table.setItem(r, c, item)
        self.grid_table.resizeColumnsToContents()

    # ----------------------------------------------------------- events

    def closeEvent(self, event) -> None:
        if self._worker:
            self._worker.cancel()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        event.accept()


def main(argv: list[str] | None = None) -> int:
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(argv if argv is not None else sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()
