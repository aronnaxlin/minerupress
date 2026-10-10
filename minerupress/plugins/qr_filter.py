from __future__ import annotations
import warnings
from pathlib import Path

from .base import ExportPlugin

try:
    import cv2 as _cv2
    import numpy as _np
    _DETECTOR = _cv2.QRCodeDetector()
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

# A detected quad must cover this fraction of the image and be this close to
# a square.  Small QR crops fill almost the whole image, whereas the false
# positives seen on matrices / chessboards / graph drawings are small, skewed
# quads that cover well under a third of it.
_MIN_QUAD_AREA = 0.4
_MIN_QUAD_SQUARENESS = 0.7


def _pad(img, border: int):
    return _cv2.copyMakeBorder(
        img, border, border, border, border, _cv2.BORDER_CONSTANT, value=255
    )


def _variants(frame):
    """
    Yield (image, scale, border) preprocessing variants of a BGR frame.

    Small QR crops often have no quiet zone and only ~3 px per module, which
    makes the plain detector miss about a third of them.  Upscaling, adding a
    white border and binarising recovers those; every variant still has to
    pass the geometry check in _is_qr_quad().
    """
    gray = _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY)

    def scaled(scale: float, interpolation=_cv2.INTER_CUBIC):
        return _cv2.resize(gray, None, fx=scale, fy=scale, interpolation=interpolation)

    def border_for(img) -> int:
        return max(10, int(max(img.shape[:2]) * 0.12))

    def blurred(scale: float):
        up = scaled(scale)
        return _cv2.GaussianBlur(up, (0, 0), scale * 0.6)

    yield frame, 1.0, 0
    for scale in (2.0, 1.5, 3.0):
        up = blurred(scale)
        yield _pad(up, border_for(up)), scale, border_for(up)
    nearest = scaled(1.5, _cv2.INTER_NEAREST)
    yield _pad(nearest, border_for(nearest)), 1.5, border_for(nearest)
    up = scaled(4.0)
    binary = _cv2.threshold(up, 0, 255, _cv2.THRESH_BINARY + _cv2.THRESH_OTSU)[1]
    yield _pad(binary, border_for(binary)), 4.0, border_for(binary)
    clahe = _cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    for scale in (1.5, 2.0, 5.0):
        up = scaled(scale)
        enhanced = clahe.apply(up)
        yield _pad(enhanced, border_for(enhanced)), scale, border_for(enhanced)


def _is_qr_quad(points, scale: float, border: int, width: int, height: int) -> bool:
    quad = (points.reshape(-1, 2).astype("float32") - border) / scale
    if quad.shape != (4, 2):
        return False
    area = _cv2.contourArea(quad) / float(width * height)
    sides = [float(_np.linalg.norm(quad[i] - quad[(i + 1) % 4])) for i in range(4)]
    if min(sides) <= 0:
        return False
    squareness = min(sides) / max(sides)
    return _MIN_QUAD_AREA <= area <= 1.3 and squareness >= _MIN_QUAD_SQUARENESS


def _looks_like_qr(frame) -> bool:
    height, width = frame.shape[:2]
    for image, scale, border in _variants(frame):
        _, points = _DETECTOR.detect(image)
        if points is not None and _is_qr_quad(points, scale, border, width, height):
            return True
    return False


class QRFilterPlugin(ExportPlugin):
    """
    Drop images that are QR codes.

    Detection strategy: OpenCV QRCodeDetector.detect() (finder-pattern
    only, no decode required) run on the original image and on a few
    upscaled / bordered / binarised variants.  A hit only counts when the
    detected quad fills most of the image and is close to square, so grid-like
    matrices, chessboards and graph drawings are not mistaken for QR codes.
    A max_side cap additionally skips large diagrams.

    Every dropped image is printed (file name and size) so the filtering
    can be audited.

    Parameters
    ----------
    max_side : int
        Images larger than this on either dimension are never considered
        QR codes.  Default 250 covers all known course QR variants in
        MinerU output (typically 112-142 px wide, up to ~200 px tall when
        a caption is included in the crop).

    book.yml
    --------
    plugins:
      - qr_filter:
          max_side: 250
    """

    def __init__(self, max_side: int = 250) -> None:
        self.max_side = int(max_side)
        self._cache: dict[Path, bool] = {}
        if not _AVAILABLE:
            warnings.warn(
                "opencv-python not installed; QRFilterPlugin is disabled. "
                "Run: pip install opencv-python",
                stacklevel=2,
            )

    def on_image(self, item: dict, img_path: Path | None) -> bool:
        if not _AVAILABLE or img_path is None or not img_path.exists():
            return True
        if img_path in self._cache:
            return self._cache[img_path]
        keep = True
        try:
            frame = _cv2.imread(str(img_path))
            if frame is not None:
                h, w = frame.shape[:2]
                if max(w, h) <= self.max_side and _looks_like_qr(frame):
                    print(f"  [qr_filter] dropped {img_path.name} ({w}x{h})")
                    keep = False
        except Exception:
            keep = True
        self._cache[img_path] = keep
        return keep
