"""Export options dialog.

Collects the three export decisions in one place before the save-file
dialog: sheet layout, whether to keep the hidden raw-OCR audit columns,
and whether to export only reviewed pages. Choosing "reviewed pages
only" is the clean path past the unreviewed-pages warning — it exports
exactly the human-checked subset.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
)


class ExportDialog(QDialog):
    def __init__(self, parent, default_layout: str,
                 n_total: int, n_reviewed: int):
        super().__init__(parent)
        self.setWindowTitle("Export options")

        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["sheet_per_page", "merged_by_label"])
        self.layout_combo.setCurrentText(default_layout)
        self.layout_combo.setToolTip(
            "sheet_per_page: one worksheet per PDF page.\n"
            "merged_by_label: pages sharing a document-type label are "
            "concatenated into one worksheet.")

        self.raw_check = QCheckBox("Include hidden raw-OCR audit columns")
        self.raw_check.setChecked(True)
        self.raw_check.setToolTip(
            "Keeps the exact OCR string next to every parsed value in a "
            "hidden column block — recommended for finance tie-out.")

        self.reviewed_check = QCheckBox(
            f"Export only reviewed pages ({n_reviewed} of {n_total})")
        self.reviewed_check.setChecked(False)
        self.reviewed_check.setEnabled(n_reviewed > 0)
        if n_reviewed == 0:
            self.reviewed_check.setToolTip(
                "No page is marked reviewed yet.")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow(QLabel("Sheet layout:"), self.layout_combo)
        form.addRow(self.raw_check)
        form.addRow(self.reviewed_check)
        form.addRow(buttons)

    # ------------------------------------------------------------ result

    @property
    def layout(self) -> str:
        return self.layout_combo.currentText()

    @property
    def include_raw(self) -> bool:
        return self.raw_check.isChecked()

    @property
    def reviewed_only(self) -> bool:
        return self.reviewed_check.isChecked()
