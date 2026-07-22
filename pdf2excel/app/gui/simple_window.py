"""Jendela utama sederhana — untuk pengguna lansia / awam komputer.

Prinsip desain:
  * SATU layar, alur lurus tiga langkah: buka PDF → ubah ke Excel →
    selesai (buka Excel / buka folder). Tidak ada dialog simpan-file;
    hasil otomatis tersimpan di folder Dokumen dengan nama yang jelas.
  * Bahasa Indonesia polos. Tidak ada istilah teknis (OCR, engine, DPI)
    di alur utama.
  * Huruf dan tombol besar, kontras tinggi — asumsikan penglihatan
    menurun.
  * Semua kesalahan dijelaskan dengan bahasa sehari-hari plus apa yang
    harus dilakukan; detail teknis disembunyikan di "Lihat detail".
  * Pemeriksaan hasil (QA keuangan) tetap ada tapi OPSIONAL — tombol
    kecil "Periksa hasil (opsional)" membuka tampilan gambar + tabel.
  * Pengaturan teknis ada di balik tautan kecil "Pengaturan lanjutan".

Teknis yang dipertahankan dari jendela lama: konversi berjalan di
thread terpisah (UI tidak pernah beku), hasil per halaman disimpan ke
file sesi di samping PDF (berhenti/mati listrik → tinggal lanjut),
rotasi otomatis, dan angka format Indonesia.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QStandardPaths, QThread, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QComboBox, QProgressBar, QPushButton, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from app.config import PipelineConfig
from app.gui.review_view import ReviewView
from app.gui.worker import OcrWorker, SinglePageWorker
from app.pipeline import pdf_loader
from app.pipeline.engines import ENGINES, available_engines
from app.pipeline.models import PageResult
from app.session import SessionStore

STYLE = """
QWidget { font-size: 13pt; color: #14181d; background: #ffffff; }
QLabel#title { font-size: 24pt; font-weight: 700; }
QLabel#subtitle { font-size: 12pt; color: #45505c; }
QLabel#status { font-size: 14pt; }
QLabel#done { font-size: 14pt; font-weight: 600; color: #0d6832; }
QPushButton {
    background: #0b5cad; color: #ffffff; border: none; border-radius: 12px;
    padding: 16px 24px; font-size: 15pt; font-weight: 700;
}
QPushButton:hover:enabled { background: #094b8d; }
QPushButton:disabled { background: #c3ccd6; color: #f4f6f8; }
QPushButton#success { background: #0d6832; }
QPushButton#success:hover:enabled { background: #0a5528; }
QPushButton#danger { background: #b02a37; }
QPushButton#quiet {
    background: transparent; color: #0b5cad; font-size: 12pt;
    font-weight: 600; text-decoration: underline; padding: 8px;
}
QPushButton#link {
    background: transparent; color: #6a7683; font-size: 10.5pt;
    font-weight: 400; text-decoration: underline; padding: 4px;
}
QProgressBar {
    min-height: 30px; border: 1px solid #9aa7b4; border-radius: 8px;
    text-align: center; font-size: 12pt; background: #eef2f6;
}
QProgressBar::chunk { background: #0b5cad; border-radius: 7px; }
"""


def unique_output_path(directory: str, stem: str) -> str:
    """Documents/<stem>.xlsx, never overwriting an existing file."""
    stem = stem.strip() or "hasil"
    candidate = os.path.join(directory, f"{stem}.xlsx")
    i = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem} ({i}).xlsx")
        i += 1
    return candidate


def friendly_error(exc: Exception | str, context: str = "") -> tuple[str, str]:
    """(pesan sederhana, detail teknis) untuk sebuah kegagalan."""
    detail = str(exc)
    low = detail.lower()
    if isinstance(exc, PermissionError) or "permission denied" in low:
        return ("File Excel-nya sepertinya sedang terbuka.\n\n"
                "Tutup dulu jendela Excel, lalu coba lagi.", detail)
    if context == "open":
        return ("File ini tidak bisa dibuka sebagai PDF.\n\n"
                "Coba pilih file lain yang berakhiran .pdf.", detail)
    return ("Maaf, terjadi kendala saat memproses dokumen.\n\n"
            "Coba tutup aplikasi ini, buka lagi, lalu ulangi. "
            "Kalau masih gagal, minta bantuan dan tunjukkan "
            "tombol “Show Details”.", detail)


def _error_box(parent, title: str, exc: Exception | str, context: str = "") -> None:
    msg, detail = friendly_error(exc, context)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(msg)
    box.setDetailedText(detail)   # teknis, tersembunyi secara default
    box.exec()


class SimpleMainWindow(QMainWindow):
    def __init__(self, output_dir: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("PDF ke Excel")
        self.resize(780, 680)
        self.setStyleSheet(STYLE)

        self._output_dir = output_dir or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation) or os.getcwd()

        self._pdf_path: str | None = None
        self._pdf_info: pdf_loader.PdfInfo | None = None
        self._results: dict[int, PageResult] = {}
        self._store: SessionStore | None = None
        self._out_path: str | None = None
        self._thread: QThread | None = None
        self._worker: OcrWorker | None = None

        # nilai "Pengaturan lanjutan" (default aman; tak pernah tampil
        # di alur utama)
        self._adv = PipelineConfig()

        self._build_ui()
        self._reset_after_file()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(40, 28, 40, 16)
        lay.setSpacing(14)

        title = QLabel("PDF ke Excel")
        title.setObjectName("title")
        subtitle = QLabel("Mengubah dokumen PDF hasil scan menjadi tabel Excel. "
                          "Semua diproses di komputer ini — tidak lewat internet.")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(subtitle)
        lay.addSpacing(8)

        self.open_btn = QPushButton("1.  Buka file PDF")
        self.open_btn.setMinimumHeight(72)
        self.open_btn.clicked.connect(self.choose_pdf)
        lay.addWidget(self.open_btn)

        self.file_label = QLabel("")
        self.file_label.setWordWrap(True)
        lay.addWidget(self.file_label)

        self.convert_btn = QPushButton("2.  Ubah ke Excel")
        self.convert_btn.setMinimumHeight(72)
        self.convert_btn.clicked.connect(self.convert)
        lay.addWidget(self.convert_btn)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        self.cancel_btn = QPushButton("Berhenti dulu")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setMinimumHeight(56)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel)
        lay.addWidget(self.cancel_btn)

        self.done_label = QLabel("")
        self.done_label.setObjectName("done")
        self.done_label.setWordWrap(True)
        self.done_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.done_label)

        row = QHBoxLayout()
        self.open_excel_btn = QPushButton("Buka file Excel")
        self.open_excel_btn.setObjectName("success")
        self.open_excel_btn.setMinimumHeight(64)
        self.open_excel_btn.clicked.connect(self.open_excel)
        self.open_folder_btn = QPushButton("Buka foldernya")
        self.open_folder_btn.setMinimumHeight(64)
        self.open_folder_btn.clicked.connect(self.open_folder)
        row.addWidget(self.open_excel_btn)
        row.addWidget(self.open_folder_btn)
        lay.addLayout(row)

        self.review_btn = QPushButton("Periksa hasil (opsional)")
        self.review_btn.setObjectName("quiet")
        self.review_btn.clicked.connect(self.open_review)
        lay.addWidget(self.review_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addStretch(1)

        self.settings_btn = QPushButton("Pengaturan lanjutan")
        self.settings_btn.setObjectName("link")
        self.settings_btn.clicked.connect(self.open_settings)
        lay.addWidget(self.settings_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.setCentralWidget(root)

    def _reset_after_file(self) -> None:
        """Kembalikan layar ke keadaan sesuai data yang ada."""
        has_file = self._pdf_path is not None
        complete = self._is_complete()
        self.convert_btn.setEnabled(has_file)
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.done_label.setVisible(bool(self._out_path))
        self.open_excel_btn.setVisible(bool(self._out_path))
        self.open_folder_btn.setVisible(bool(self._out_path))
        self.review_btn.setVisible(bool(self._results) and has_file)
        if has_file and self._results and not complete:
            n = len([r for r in self._results.values() if not r.error])
            self.status_label.setText(
                f"{n} halaman sudah selesai dibaca sebelumnya. Tekan "
                f"“2. Ubah ke Excel” untuk melanjutkan sisanya.")

    # ------------------------------------------------------- langkah 1

    def choose_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih file PDF", "", "File PDF (*.pdf)")
        if not path:
            return
        self.load_pdf(path)

    def load_pdf(self, path: str) -> None:
        try:
            info = pdf_loader.inspect_pdf(path)
        except Exception as exc:
            _error_box(self, "File tidak bisa dibuka", exc, context="open")
            return

        self._close_store()
        self._pdf_path = path
        self._pdf_info = info
        self._results = {}
        self._out_path = None
        self.done_label.clear()
        self.status_label.clear()

        self._open_session(path)

        name = os.path.basename(path)
        self.file_label.setText(f"✓  {name} — {info.n_pages} halaman")
        self._reset_after_file()

    def _open_session(self, path: str) -> None:
        try:
            had = SessionStore.exists_for_pdf(path)
            self._store = SessionStore.for_pdf(path)
        except Exception:
            self._store = None   # folder hanya-baca: tetap jalan, tanpa simpan
            return
        if not had:
            self._store.bind_pdf(path)
            return
        n, _rev = self._store.summary()
        if n == 0:
            self._store.bind_pdf(path)
            return

        # Guard against resuming into the wrong document: if the PDF's
        # fingerprint doesn't match what this session was built from, the
        # saved pages describe a different file.
        if self._store.fingerprint_status(path) == "mismatch":
            answer = QMessageBox.question(
                self, "File PDF sepertinya sudah berbeda",
                "Ada pekerjaan tersimpan untuk nama file ini, tetapi isi "
                "PDF-nya sekarang berbeda dari saat terakhir diproses "
                "(mungkin file diganti atau di-scan ulang).\n\n"
                "Mulai dari awal untuk file yang sekarang? (Pilih “No” "
                "untuk tetap memakai hasil lama — tidak disarankan.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if answer == QMessageBox.StandardButton.Yes:
                self._store.clear_pages()
                self._store.rebind_pdf(path)
                return
            self._results = self._store.load_pages()
            return

        answer = QMessageBox.question(
            self, "Lanjutkan pekerjaan sebelumnya?",
            f"File ini pernah diproses: {n} halaman sudah selesai dibaca.\n\n"
            "Mau melanjutkan dari situ? (Pilih “No” untuk mengulang "
            "dari awal.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer == QMessageBox.StandardButton.Yes:
            self._results = self._store.load_pages()
        else:
            self._store.clear_pages()
            self._store.rebind_pdf(path)

    # ------------------------------------------------------- langkah 2

    def _is_complete(self) -> bool:
        if not self._pdf_info:
            return False
        return all(p in self._results and not self._results[p].error
                   for p in range(1, self._pdf_info.n_pages + 1))

    def _missing_pages(self) -> list[int]:
        assert self._pdf_info is not None
        return [p for p in range(1, self._pdf_info.n_pages + 1)
                if p not in self._results or self._results[p].error]

    def convert(self) -> None:
        if not self._pdf_path or self._thread is not None:
            return
        if self._is_complete():
            self._export_and_finish()
            return

        missing = self._missing_pages()
        if self._store:
            try:
                self._store.save_config(self._config())
            except Exception:
                pass

        self._worker = OcrWorker(self._pdf_path, self._config(), pages=missing)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.page_done.connect(self._on_page_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        self.open_btn.setEnabled(False)
        self.convert_btn.setEnabled(False)
        self.settings_btn.setEnabled(False)
        self.review_btn.setVisible(False)
        self.done_label.setVisible(False)
        self.open_excel_btn.setVisible(False)
        self.open_folder_btn.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(missing))
        self.progress.setValue(0)
        self.status_label.setText("Bersiap membaca dokumen…")
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self._thread.start()

    def cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status_label.setText(
                "Berhenti sebentar — menyelesaikan halaman yang sedang "
                "dibaca…")

    def _config(self) -> PipelineConfig:
        # salinan pengaturan lanjutan (default: rapidocr, 300 dpi, auto)
        import dataclasses
        return dataclasses.replace(self._adv)

    def _on_progress(self, done: int, total: int, _msg: str) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        if done < total:
            self.status_label.setText(
                f"Sedang memproses halaman {done + 1} dari {total}… "
                f"Mohon tunggu, ya.")

    def _on_page_done(self, result: PageResult) -> None:
        self._results[result.page_number] = result
        if self._store:
            try:
                self._store.save_page(result)
            except Exception:
                pass

    def _on_finished(self, _results: list, was_cancelled: bool) -> None:
        self._teardown()
        if was_cancelled:
            n_done = len([r for r in self._results.values() if not r.error])
            self.status_label.setText(
                f"Dihentikan. {n_done} halaman sudah tersimpan — lain kali "
                f"tinggal tekan “2. Ubah ke Excel” lagi untuk melanjutkan.")
            self._reset_after_file()
            return
        self._export_and_finish()

    def _on_failed(self, message: str) -> None:
        self._teardown()
        self.status_label.clear()
        self._reset_after_file()
        _error_box(self, "Ada kendala", message)

    def _teardown(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
        if self._worker:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None
        self.open_btn.setEnabled(True)
        self.settings_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)

    # ------------------------------------------------------- langkah 3

    def _export_and_finish(self) -> None:
        assert self._pdf_path is not None
        pages = [self._results[k] for k in sorted(self._results)]

        from app.export.excel import export_workbook
        from app.export.policy import (filename_suffix, final_eligibility,
                                       status_label)
        eligibility = final_eligibility(pages)

        # DRAF by default: the file is always named and labeled by its
        # verification state, never plainly "…xlsx" until it is truly
        # final. A fresh file path per state avoids a stale DRAF sitting
        # next to a FINAL of the same name.
        stem = os.path.splitext(os.path.basename(self._pdf_path))[0]
        stem += filename_suffix(eligibility.final_ok)
        self._out_path = unique_output_path(self._output_dir, stem)

        try:
            export_workbook(pages, self._out_path, self._config(),
                            source_pdf=self._pdf_path, eligibility=eligibility)
        except Exception as exc:
            _error_box(self, "File Excel tidak bisa disimpan", exc)
            self._reset_after_file()
            return

        self.status_label.clear()
        if eligibility.final_ok:
            head = f"Selesai! File Excel FINAL tersimpan di:\n{self._out_path}"
        else:
            reasons = "\n• ".join(eligibility.reasons)
            head = (
                f"File DRAF tersimpan di:\n{self._out_path}\n\n"
                f"⚠ Angka BELUM selesai diperiksa, jadi file ini DRAF — "
                f"jangan dipakai sebagai laporan final. Tekan "
                f"“Periksa hasil” untuk memeriksa dan membetulkan, "
                f"lalu ubah lagi.\n\nBelum final karena:\n• {reasons}")
        self.done_label.setText(head)
        self.done_label.setStyleSheet(
            "" if eligibility.final_ok else "color:#8a5a00;")
        self.done_label.setVisible(True)
        self.open_excel_btn.setVisible(True)
        self.open_folder_btn.setVisible(True)
        self.review_btn.setVisible(True)
        # Nudge review when not final — it is optional but not trivial.
        self.review_btn.setText("Periksa hasil"
                                if not eligibility.final_ok
                                else "Periksa hasil (opsional)")
        self.convert_btn.setEnabled(True)

    def open_excel(self) -> None:
        if self._out_path and os.path.exists(self._out_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._out_path))
        else:
            _error_box(self, "File tidak ditemukan",
                       "File Excel-nya sudah tidak ada di tempat semula. "
                       "Tekan “2. Ubah ke Excel” untuk membuatnya lagi.")

    def open_folder(self) -> None:
        if self._out_path:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(self._out_path)))

    # -------------------------------------------------- periksa hasil

    def open_review(self) -> None:
        if not self._pdf_path or not self._results:
            return
        dialog = ReviewDialog(self, self._pdf_path, self._results,
                              self._store, self._config())
        dialog.exec()
        if dialog.changed:
            # Review may have flipped DRAF→FINAL (or vice-versa), which
            # changes the filename; re-export through the same policy
            # path so the file is named/labeled for its new state.
            self._out_path = None
            self._export_and_finish()

    # ---------------------------------------------------- pengaturan

    def open_settings(self) -> None:
        dialog = AdvancedSettingsDialog(self, self._adv)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._adv = dialog.result_config()

    # --------------------------------------------------------- events

    def _close_store(self) -> None:
        if self._store:
            self._store.close()
            self._store = None

    def closeEvent(self, event) -> None:
        if self._worker:
            self._worker.cancel()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._close_store()
        event.accept()


class ReviewDialog(QDialog):
    """Pemeriksaan hasil: daftar halaman + gambar & tabel yang bisa
    dikoreksi. Opsional — bukan bagian alur utama."""

    def __init__(self, parent, pdf_path: str, results: dict[int, PageResult],
                 store: SessionStore | None, config: PipelineConfig):
        super().__init__(parent)
        self.setWindowTitle("Periksa hasil")
        self.resize(1200, 760)
        self.setStyleSheet("QWidget { font-size: 12pt; }")
        self.changed = False

        self._pdf_path = pdf_path
        self._results = results
        self._store = store
        self._config = config
        self._sp_thread: QThread | None = None
        self._sp_worker: SinglePageWorker | None = None

        hint = QLabel(
            "Sel kuning = bacaan yang kurang yakin, silakan cocokkan dengan "
            "gambar di sebelah kiri. Klik dua kali sel untuk memperbaiki; "
            "sel yang sudah dikoreksi menjadi hijau.")
        hint.setWordWrap(True)

        self.page_list = QListWidget()
        self.page_list.setMinimumWidth(190)
        for pno in sorted(results):
            r = results[pno]
            label = f"Halaman {pno}"
            if r.error:
                label += "  (gagal)"
            elif r.reviewed:
                label += "  ✓"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, pno)
            self.page_list.addItem(item)
        self.page_list.currentItemChanged.connect(self._show_page)

        self.review = ReviewView()
        self.review.result_changed.connect(self._on_changed)
        self.review.request_reocr.connect(self._on_reocr)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.page_list)
        split.addWidget(self.review)
        split.setSizes([190, 1010])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        close_btn.setText("Selesai memeriksa")
        close_btn.setMinimumHeight(48)

        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(split, 1)
        lay.addWidget(buttons)

        labels = sorted({r.doc_type_label for r in results.values()
                         if r.doc_type_label})
        self.review.set_known_labels(labels)
        if self.page_list.count():
            self.page_list.setCurrentRow(0)

    def _show_page(self, current, _previous=None) -> None:
        if current is None:
            return
        pno = current.data(Qt.ItemDataRole.UserRole)
        self.review.set_page(self._pdf_path, pno, self._results.get(pno))

    def _on_changed(self, result: PageResult) -> None:
        self.changed = True
        if self._store:
            try:
                self._store.save_page(result)
            except Exception:
                pass
        item = self.page_list.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole) == result.page_number:
            label = f"Halaman {result.page_number}"
            if result.reviewed:
                label += "  ✓"
            item.setText(label)

    def _on_reocr(self, page_number: int, rotation: int) -> None:
        if self._sp_thread is not None:
            return
        result = self._results.get(page_number)
        if result is not None and any(
                c.edited for row in result.grid for c in row if c):
            answer = QMessageBox.question(
                self, "Baca ulang halaman ini?",
                "Koreksi yang pernah dibuat di halaman ini akan hilang "
                "dan diganti hasil pembacaan baru. Lanjutkan?")
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._sp_worker = SinglePageWorker(
            self._pdf_path, page_number, self._config, rotation)
        self._sp_thread = QThread(self)
        self._sp_worker.moveToThread(self._sp_thread)
        self._sp_thread.started.connect(self._sp_worker.run)
        self._sp_worker.done.connect(self._on_reocr_done)
        self._sp_worker.failed.connect(self._on_reocr_failed)
        self.review.set_busy(True)
        self._sp_thread.start()

    def _on_reocr_done(self, result: PageResult) -> None:
        self._teardown_sp()
        old = self._results.get(result.page_number)
        if old is not None:
            result.doc_type_label = old.doc_type_label
        self._results[result.page_number] = result
        self._on_changed(result)
        self.review.set_busy(False)
        item = self.page_list.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole) == result.page_number:
            self.review.set_page(self._pdf_path, result.page_number, result)

    def _on_reocr_failed(self, message: str) -> None:
        self._teardown_sp()
        self.review.set_busy(False)
        _error_box(self, "Halaman tidak bisa dibaca ulang", message)

    def _teardown_sp(self) -> None:
        if self._sp_thread:
            self._sp_thread.quit()
            self._sp_thread.wait()
            self._sp_thread.deleteLater()
        if self._sp_worker:
            self._sp_worker.deleteLater()
        self._sp_thread = None
        self._sp_worker = None

    def closeEvent(self, event) -> None:
        if self._sp_thread:
            self._sp_thread.quit()
            self._sp_thread.wait()
        event.accept()


class AdvancedSettingsDialog(QDialog):
    """Pengaturan teknis — untuk pendamping/teknisi, bukan alur utama."""

    def __init__(self, parent, current: PipelineConfig):
        super().__init__(parent)
        self.setWindowTitle("Pengaturan lanjutan")
        self.setStyleSheet("QWidget { font-size: 11pt; }")

        self.engine_combo = QComboBox()
        avail = available_engines()
        for name, cls in ENGINES.items():
            self.engine_combo.addItem(name)
            if not avail[name]:
                item = self.engine_combo.model().item(
                    self.engine_combo.count() - 1)
                item.setEnabled(False)
                item.setToolTip(f"Belum terpasang — {cls.unavailable_hint()}")
        self.engine_combo.setCurrentText(current.engine)

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(150, 600)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(current.dpi)
        self.dpi_spin.setToolTip(
            "Ketajaman pemindaian. 300 adalah nilai teruji; nilai lebih "
            "rendah membuat tabel padat salah terbaca.")

        self.rotation_combo = QComboBox()
        self.rotation_combo.addItems(["auto", "0", "90", "180", "270"])
        self.rotation_combo.setCurrentText(str(current.rotation))
        self.rotation_combo.setToolTip(
            "auto = arah halaman dideteksi sendiri per halaman.")

        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["sheet_per_page", "merged_by_label"])
        self.layout_combo.setCurrentText(current.output_layout)
        self.layout_combo.setToolTip(
            "sheet_per_page: satu lembar Excel per halaman PDF.\n"
            "merged_by_label: halaman ber-jenis dokumen sama digabung.")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow("Mesin pembaca teks:", self.engine_combo)
        form.addRow("Ketajaman (DPI):", self.dpi_spin)
        form.addRow("Rotasi halaman:", self.rotation_combo)
        form.addRow("Tata letak Excel:", self.layout_combo)
        form.addRow(buttons)

    def result_config(self) -> PipelineConfig:
        rot = self.rotation_combo.currentText()
        return PipelineConfig(
            engine=self.engine_combo.currentText(),
            dpi=self.dpi_spin.value(),
            rotation="auto" if rot == "auto" else int(rot),
            output_layout=self.layout_combo.currentText(),
        )


def main(argv: list[str] | None = None) -> int:
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(argv if argv is not None else sys.argv)
    app.setFont(QFont(app.font().family(), 12))
    win = SimpleMainWindow()
    win.show()
    return app.exec()
