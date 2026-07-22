"""Small Qt helpers shared by GUI modules."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage, QPixmap


def ndarray_to_pixmap(image: np.ndarray) -> QPixmap:
    """Convert an HxWx3 RGB uint8 array to a QPixmap (copies the data)."""
    h, w, _ = image.shape
    qimg = QImage(np.ascontiguousarray(image).data, w, h, 3 * w,
                  QImage.Format.Format_RGB888)
    # .copy() detaches from the numpy buffer before it goes out of scope.
    return QPixmap.fromImage(qimg.copy())
