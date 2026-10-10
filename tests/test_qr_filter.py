from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from minerupress.plugins.qr_filter import QRFilterPlugin


def _qr_image(text: str, side: int, *, quiet_zone: bool = False, jpeg_quality: int = 45):
    """A small, slightly degraded QR crop like the ones MinerU extracts from scans."""
    modules = cv2.QRCodeEncoder.create().encode(text)
    img = cv2.resize(modules, (side, side), interpolation=cv2.INTER_AREA)
    if quiet_zone:
        pad = side // 8
        img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    assert ok
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def _write(tmp_path: Path, name: str, img) -> Path:
    path = tmp_path / name
    assert cv2.imwrite(str(path), img)
    return path


def _checkerboard(rows: int, cols: int, cell: int):
    board = np.indices((rows, cols)).sum(axis=0) % 2
    return (board * 255).astype("uint8").repeat(cell, axis=0).repeat(cell, axis=1)


def _matrix(side: int):
    img = np.full((side, side), 255, np.uint8)
    cv2.rectangle(img, (4, 4), (side - 5, side - 5), 0, 1)
    step = (side - 8) // 3
    for i in range(1, 3):
        cv2.line(img, (4, 4 + i * step), (side - 5, 4 + i * step), 0, 1)
        cv2.line(img, (4 + i * step, 4), (4 + i * step, side - 5), 0, 1)
    for r in range(3):
        for c in range(3):
            cv2.putText(img, str(r * 3 + c + 1), (12 + c * step, 4 + (r + 1) * step - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)
    return img


def _graph(w: int, h: int):
    img = np.full((h, w), 255, np.uint8)
    pts = [(25, 25), (w - 25, 30), (w // 2, h // 2), (30, h - 25), (w - 30, h - 30)]
    for a, b in [(0, 1), (0, 2), (1, 2), (2, 3), (2, 4), (1, 4), (0, 3)]:
        cv2.line(img, pts[a], pts[b], 0, 1)
    for p in pts:
        cv2.circle(img, p, 14, 255, -1)
        cv2.circle(img, p, 14, 0, 1)
    return img


@pytest.mark.parametrize("side", [112, 115, 176])
@pytest.mark.parametrize("quiet_zone", [False, True])
def test_drops_small_qr_codes(tmp_path: Path, side: int, quiet_zone: bool, capsys) -> None:
    img = _qr_image("https://example.com/books/algorithms/courseware/chapter-5/section-2", side,
                    quiet_zone=quiet_zone)
    path = _write(tmp_path, "qr.png", img)

    assert QRFilterPlugin().on_image({}, path) is False

    out = capsys.readouterr().out
    assert "qr.png" in out and f"{img.shape[1]}x{img.shape[0]}" in out


@pytest.mark.parametrize(
    "name, make",
    [
        ("checkerboard.png", lambda: _checkerboard(8, 8, 15)),
        ("matrix.png", lambda: _matrix(160)),
        ("graph.png", lambda: _graph(220, 180)),
        ("noise.png", lambda: np.random.default_rng(0).integers(0, 255, (120, 120), dtype=np.uint8)),
        ("blank.png", lambda: np.full((100, 100), 255, np.uint8)),
    ],
)
def test_keeps_non_qr_small_images(tmp_path: Path, name: str, make, capsys) -> None:
    path = _write(tmp_path, name, make())

    assert QRFilterPlugin().on_image({}, path) is True
    assert capsys.readouterr().out == ""


def test_max_side_is_respected(tmp_path: Path) -> None:
    path = _write(tmp_path, "big_qr.png", _qr_image("https://example.com/x", 300, quiet_zone=True,
                                                    jpeg_quality=90))

    assert QRFilterPlugin(max_side=250).on_image({}, path) is True
    assert QRFilterPlugin(max_side=400).on_image({}, path) is False


def test_missing_or_unreadable_files_are_kept(tmp_path: Path) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    plugin = QRFilterPlugin()

    assert plugin.on_image({}, None) is True
    assert plugin.on_image({}, tmp_path / "missing.png") is True
    assert plugin.on_image({}, broken) is True


class _FakeDetector:
    """Stand-in for cv2.QRCodeDetector with a scripted answer per image size."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def detect(self, image):
        self.calls += 1
        return self.answer(image)


def _inner_quad(image) -> np.ndarray:
    """Quad around the middle 80% of the image, i.e. the content of a bordered crop."""
    h, w = image.shape[:2]
    x0, x1, y0, y1 = 0.1 * w, 0.9 * w, 0.1 * h, 0.9 * h
    return np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], dtype=np.float32)


def test_retries_on_upscaled_variants(tmp_path: Path, monkeypatch) -> None:
    from minerupress.plugins import qr_filter

    path = _write(tmp_path, "tiny.png", _checkerboard(4, 4, 20))
    # Only "finds" a code once the image has been enlarged beyond the original 80 px.
    detector = _FakeDetector(
        lambda img: (True, _inner_quad(img)) if max(img.shape[:2]) > 80 else (False, None)
    )
    monkeypatch.setattr(qr_filter, "_DETECTOR", detector)

    assert QRFilterPlugin().on_image({}, path) is False
    assert detector.calls > 1


def test_small_or_skewed_quads_are_not_qr_codes(tmp_path: Path, monkeypatch) -> None:
    from minerupress.plugins import qr_filter

    path = _write(tmp_path, "diagram.png", _matrix(160))

    def corner_quad(img):  # a 40x40 quad in a 160x160 image: only 6% of the area
        return True, np.array([[[0, 0], [40, 0], [40, 40], [0, 40]]], dtype=np.float32)

    def sliver_quad(img):  # fills the image but is nowhere near square
        h, w = img.shape[:2]
        return True, np.array([[[0, 0], [w, 0], [w, h // 4], [0, h // 4]]], dtype=np.float32)

    for answer in (corner_quad, sliver_quad):
        monkeypatch.setattr(qr_filter, "_DETECTOR", _FakeDetector(answer))
        assert QRFilterPlugin().on_image({}, path) is True


def test_decisions_are_cached_per_file(tmp_path: Path, monkeypatch) -> None:
    from minerupress.plugins import qr_filter

    path = _write(tmp_path, "any.png", _matrix(120))
    detector = _FakeDetector(lambda img: (False, None))
    monkeypatch.setattr(qr_filter, "_DETECTOR", detector)
    plugin = QRFilterPlugin()

    assert plugin.on_image({}, path) is True
    calls = detector.calls
    assert plugin.on_image({}, path) is True
    assert detector.calls == calls
