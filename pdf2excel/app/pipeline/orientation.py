"""Per-page orientation detection.

Landscape tables scanned into portrait pages (rotated 90°) are the norm
in this corpus, and OCR on the un-rotated image is garbage — so every
page is checked before OCR.

Strategy, in order:
  1. Tesseract OSD (--psm 0) via pytesseract, if a tesseract binary is
     installed on the machine. Fast and accurate when available.
  1b. The engine's own page-orientation classifier, if it has one
     (OCREngine.detect_orientation — PP-StructureV3 ships a dedicated
     PP-LCNet doc_ori model). Falls through on low confidence.
  2. Fallback heuristic (always available), two stages on a downscaled
     copy of the page. A naive "score OCR text volume at each rotation"
     does NOT work with modern engines: RapidOCR reads vertical lines
     (tall crops are auto-rotated internally) and its angle classifier
     silently fixes upside-down lines, so all four rotations score
     almost identically. Instead:

       a. Axis: run OCR once at 0° and compare the confidence-weighted
          text volume in landscape boxes (width >= height) vs portrait
          boxes. Horizontal text lines mean the page is upright-or-180;
          vertical detection boxes mean it is sideways (90-or-270).
       b. Flip: within the chosen pair, run OCR with the angle
          classifier OFF at both candidate rotations and keep the one
          with more confidently recognized horizontal text — with cls
          disabled, upside-down text recognizes as low-confidence
          garbage, which is exactly the discriminating signal.

     Measured on the synthetic corpus, the correct rotation wins by
     ~30x (305.7 vs 9.9), so the decision is robust to scan noise.

The GUI layers a manual per-page override on top of whatever this
module decides; that override is recorded in PageResult.rotation_source.
"""

from __future__ import annotations

import numpy as np

from app.pipeline.engines.base import OCREngine

ROTATIONS = (0, 90, 180, 270)


def rotate_image(image: np.ndarray, degrees_cw: int) -> np.ndarray:
    """Rotate an HxWxC image clockwise by a multiple of 90°."""
    degrees_cw = degrees_cw % 360
    if degrees_cw == 0:
        return image
    # np.rot90 rotates counter-clockwise per k.
    k = {90: 3, 180: 2, 270: 1}[degrees_cw]
    return np.ascontiguousarray(np.rot90(image, k))


def _downscale(image: np.ndarray, max_side: int) -> np.ndarray:
    h, w = image.shape[:2]
    side = max(h, w)
    if side <= max_side:
        return image
    step = int(np.ceil(side / max_side))
    return np.ascontiguousarray(image[::step, ::step])


def _tesseract_osd(image: np.ndarray) -> int | None:
    """Try Tesseract OSD; return rotation-to-apply (cw) or None."""
    try:
        import pytesseract
        from PIL import Image
        osd = pytesseract.image_to_osd(
            Image.fromarray(image), output_type=pytesseract.Output.DICT)
        conf = float(osd.get("orientation_conf", 0))
        if conf < 1.0:
            return None
        # OSD's "rotate" field is the clockwise correction to apply.
        rot = int(osd.get("rotate", 0)) % 360
        return rot if rot in ROTATIONS else None
    except Exception:
        return None


def _landscape_score(tokens) -> float:
    """Confidence-weighted text volume in horizontal (landscape) boxes."""
    return sum(len(t.text) * t.confidence for t in tokens
               if (t.x1 - t.x0) >= (t.y1 - t.y0))


def _portrait_score(tokens) -> float:
    """Confidence-weighted text volume in vertical (portrait) boxes."""
    return sum(len(t.text) * t.confidence for t in tokens
               if (t.y1 - t.y0) > (t.x1 - t.x0))


def detect_rotation_scored(image: np.ndarray, engine: OCREngine,
                           probe_max_side: int = 1200) -> tuple[int, float]:
    """Clockwise rotation (0/90/180/270) to apply before OCR, plus a
    decision margin.

    Margin semantics: -1.0 = decided by a trusted classifier (OSD or the
    engine's native detector), no ratio applies. Otherwise it is
    best_score / runner_up_score of the flip stage — measured ~30x on
    clean scans; values near 1.0 mean the detector barely preferred one
    orientation and the page deserves human eyes (anomaly framework
    flags margins below its threshold).
    """
    osd = _tesseract_osd(image)
    if osd is not None:
        return osd, -1.0

    probe = _downscale(image, probe_max_side)

    try:
        native = engine.detect_orientation(probe)
    except Exception:
        native = None
    if native is not None:
        return native, -1.0

    # Stage a: axis. Are the text lines horizontal or vertical?
    try:
        axis_tokens = engine.ocr_tokens(probe)
    except Exception:
        return 0, 1.0
    if not axis_tokens:
        return 0, 1.0
    pair = ((0, 180) if _landscape_score(axis_tokens) >= _portrait_score(axis_tokens)
            else (90, 270))

    # Stage b: flip. With the angle classifier off, only the right-way-up
    # candidate recognizes confidently.
    scores: dict[int, float] = {}
    for rot in pair:
        try:
            tokens = engine.ocr_tokens(rotate_image(probe, rot), use_cls=False)
        except Exception:
            scores[rot] = 0.0
            continue
        scores[rot] = _landscape_score(tokens)

    best_rot = max(pair, key=lambda r: (scores.get(r, 0.0), r == pair[0]))
    best = scores.get(best_rot, 0.0)
    other = max((s for r, s in scores.items() if r != best_rot), default=0.0)
    margin = best / other if other > 0 else (100.0 if best > 0 else 1.0)
    return best_rot, margin


def detect_rotation(image: np.ndarray, engine: OCREngine,
                    probe_max_side: int = 1200) -> int:
    """Back-compat wrapper around detect_rotation_scored."""
    rotation, _margin = detect_rotation_scored(image, engine, probe_max_side)
    return rotation
