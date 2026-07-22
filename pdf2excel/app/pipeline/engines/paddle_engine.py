"""PaddleOCR PP-StructureV3 engine — optional, native table structure.

Installed via wheels, NOT by cloning the PaddleOCR repo (the GitHub
``ppstructure/`` directory is the deprecated V2 pipeline):

    pip install paddlepaddle paddleocr "paddlex[ocr]"

Models (~a few hundred MB) download to ``~/.paddlex/official_models``
on first run. When the packages are missing the engine reports
unavailable and the UI greys it out with the hint — never crash on
import.

What this engine provides beyond RapidOCR:

* ``ocr_table`` — PP-StructureV3 recognizes table STRUCTURE natively
  and returns real HTML tables; we parse those into the cell grid
  (html_table.py), so the geometric row/column reconstruction is not
  needed. Multiple tables on a page are stacked with a blank separator
  row. If the page has no table region at all, the grid is rebuilt
  geometrically from the pipeline's own OCR tokens as a fallback.
* ``detect_orientation`` — the PP-LCNet_x1_0_doc_ori page classifier
  gives 0/90/180/270 directly (label = the rotation the page currently
  has, clockwise; correction = 360 - label). Much cheaper and more
  robust than the generic OCR-probe heuristic, which stays as the
  fallback when the classifier is unsure.

Cell confidence: the structure model does not score cells, so each
cell is matched back to the pipeline's overall OCR tokens — exact text
match first, then space-insensitive, then substring containment — and
takes the MINIMUM matched token score (finance bias: over-flag). Cells
that match nothing keep a conservative default.

PaddleX pipelines expect BGR images (cv2 convention); the pipeline
hands us RGB, so channels are reversed at every boundary.

Model instances are class-level singletons: loading takes seconds and
the GUI may create engine objects per worker run.
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np

from app.pipeline.engines.base import EngineUnavailableError, OCREngine
from app.pipeline.html_table import parse_html_tables
from app.pipeline.models import Cell, OCRToken

#: confidence given to cells whose text can't be matched to an OCR token
UNMATCHED_CELL_CONFIDENCE = 0.75


class PaddleStructureEngine(OCREngine):
    name = "paddle-ppstructure"
    supports_table_structure = True

    _structure = None
    _ocr = None
    _doc_ori = None

    # ------------------------------------------------------ availability

    @classmethod
    def is_available(cls) -> bool:
        # find_spec, not import: importing paddleocr takes seconds and
        # probes the network for model hosts — far too heavy for a GUI
        # startup check. ALL THREE packages are required: plain paddleocr
        # cannot build the PP-StructureV3 pipeline without paddlex.
        try:
            from importlib.util import find_spec
            return all(find_spec(m) is not None
                       for m in ("paddle", "paddleocr", "paddlex"))
        except Exception:
            return False

    @classmethod
    def models_present(cls) -> bool:
        """True when PP-StructureV3's models are already cached locally.

        Offline-first: the engine must NOT be presented as usable if
        selecting it would trigger a first-run download. Checks the
        PaddleX official-models cache for the pipeline's core models.
        """
        import pathlib
        cache = pathlib.Path(os.path.expanduser("~/.paddlex/official_models"))
        required = ["PP-LCNet_x1_0_doc_ori", "PP-OCRv5_server_det",
                    "PP-OCRv5_server_rec"]
        return cache.is_dir() and all((cache / m).is_dir() for m in required)

    @classmethod
    def unavailable_hint(cls) -> str:
        return ('pip install paddlepaddle paddleocr "paddlex[ocr]" lalu '
                "sekali jalankan dengan internet untuk mengunduh model "
                "(setelah itu offline). Mesin ini opsional.")

    def _require(self) -> None:
        if not self.is_available():
            raise EngineUnavailableError(self.unavailable_hint())
        # Never let the pipeline reach out at runtime — offline-first.
        os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
        # Fail closed BEFORE any rasterization/OCR if the model pack is
        # incomplete, rather than silently attempting a download.
        if not self.models_present():
            raise EngineUnavailableError(
                "Model PP-StructureV3 belum lengkap di komputer ini. "
                "Aplikasi tidak akan mengunduh otomatis (data rahasia, "
                "harus offline). " + self.unavailable_hint())

    # ---------------------------------------------------------- models

    @classmethod
    def _get_structure(cls):
        if cls._structure is None:
            from paddleocr import PPStructureV3
            cls._structure = PPStructureV3(
                use_doc_orientation_classify=False,  # pipeline pre-rotates
                use_doc_unwarping=False,
                use_seal_recognition=False,
                use_chart_recognition=False,
                use_formula_recognition=False,
            )
        return cls._structure

    @classmethod
    def _get_ocr(cls):
        if cls._ocr is None:
            from paddleocr import PaddleOCR
            cls._ocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
            )
        return cls._ocr

    @classmethod
    def _get_doc_ori(cls):
        if cls._doc_ori is None:
            from paddlex import create_model
            cls._doc_ori = create_model("PP-LCNet_x1_0_doc_ori")
        return cls._doc_ori

    # -------------------------------------------------------- interface

    def detect_orientation(self, image: np.ndarray) -> Optional[int]:
        """Page rotation via the dedicated classifier; None when unsure."""
        self._require()
        try:
            out = list(self._get_doc_ori().predict(image[:, :, ::-1]))
            d = out[0]
            label = int(d["label_names"][0])
            score = float(d["scores"][0])
        except Exception:
            return None
        if score < 0.6:
            return None
        # label = current clockwise rotation of the page;
        # returning the clockwise correction to apply.
        return (360 - label) % 360

    def ocr_tokens(self, image: np.ndarray, use_cls: bool = True) -> list[OCRToken]:
        # ``use_cls`` is not switchable per call in the paddle pipeline
        # (textline orientation is fixed at construction). That's fine:
        # this engine never relies on the no-cls flip heuristic because
        # detect_orientation() answers 0-vs-180 directly.
        self._require()
        res = self._get_ocr().predict(image[:, :, ::-1])[0]
        texts = list(res.get("rec_texts") or [])
        scores = list(res.get("rec_scores") or [])
        boxes = np.asarray(res.get("rec_boxes"))
        tokens: list[OCRToken] = []
        for i, text in enumerate(texts):
            text = (text or "").strip()
            if not text:
                continue
            x0, y0, x1, y1 = (float(v) for v in boxes[i][:4])
            tokens.append(OCRToken(text=text, confidence=float(scores[i]),
                                   x0=x0, y0=y0, x1=x1, y1=y1))
        return tokens

    def ocr_table(self, image: np.ndarray) -> Optional[list[list[Optional[Cell]]]]:
        self._require()
        out = list(self._get_structure().predict(image[:, :, ::-1]))
        if not out:
            return []
        res = dict(out[0])

        score_map = self._score_map(res.get("overall_ocr_res"))
        grids: list[list[list[Optional[Cell]]]] = []
        for table in res.get("table_res_list") or []:
            html = table.get("pred_html") if hasattr(table, "get") else None
            for text_grid in parse_html_tables(html or ""):
                grid = [[self._make_cell(t, score_map) for t in row]
                        for row in text_grid]
                if any(c for row in grid for c in row):
                    grids.append(grid)

        if not grids:
            # No table region on this page (letter, memo, stamp page):
            # rebuild geometrically from this pipeline's own tokens so
            # the page still yields its content.
            from app.pipeline import table_builder
            tokens = self._tokens_from_overall(res.get("overall_ocr_res"))
            return table_builder.build_grid(tokens)

        merged: list[list[Optional[Cell]]] = []
        width = max(len(r) for g in grids for r in g)
        for i, grid in enumerate(grids):
            if i:
                merged.append([None] * width)   # separator between tables
            for row in grid:
                merged.append(row + [None] * (width - len(row)))
        return merged

    # ---------------------------------------------------------- helpers

    @staticmethod
    def _score_map(overall) -> dict[str, float]:
        """text -> min OCR score (min: a repeated text is only as good
        as its worst reading)."""
        score_map: dict[str, float] = {}
        if not overall:
            return score_map
        texts = list(overall.get("rec_texts") or [])
        scores = list(overall.get("rec_scores") or [])
        for text, score in zip(texts, scores):
            text = (text or "").strip()
            if not text:
                continue
            score = float(score)
            score_map[text] = min(score, score_map.get(text, 1.0))
        return score_map

    @staticmethod
    def _tokens_from_overall(overall) -> list[OCRToken]:
        tokens: list[OCRToken] = []
        if not overall:
            return tokens
        texts = list(overall.get("rec_texts") or [])
        scores = list(overall.get("rec_scores") or [])
        boxes = np.asarray(overall.get("rec_boxes"))
        for i, text in enumerate(texts):
            text = (text or "").strip()
            if not text:
                continue
            x0, y0, x1, y1 = (float(v) for v in boxes[i][:4])
            tokens.append(OCRToken(text=text, confidence=float(scores[i]),
                                   x0=x0, y0=y0, x1=x1, y1=y1))
        return tokens

    @staticmethod
    def _make_cell(text: Optional[str], score_map: dict[str, float]) -> Optional[Cell]:
        if text is None or not text.strip():
            return None
        text = text.strip()
        conf = _match_confidence(text, score_map)
        return Cell.from_text(text, conf)


def _match_confidence(text: str, score_map: dict[str, float]) -> float:
    """Best-effort mapping of a structure-model cell back to OCR scores."""
    if text in score_map:
        return score_map[text]
    squashed = text.replace(" ", "")
    for candidate, score in score_map.items():
        if candidate.replace(" ", "") == squashed:
            return score
    # A cell merged from several tokens: take the min over contained
    # tokens (only meaningful lengths, to avoid matching single chars).
    contained = [s for t, s in score_map.items()
                 if len(t) >= 3 and t in text]
    if contained:
        return min(contained)
    return UNMATCHED_CELL_CONFIDENCE
