"""Tests for best-frame ring snapshot selection."""

from __future__ import annotations

import io

import pytest

from custom_components.comelit_man.snapshot import capture_best_frame, score_jpeg


def _jpeg(color: int, noisy: bool = False) -> bytes:
    from PIL import Image

    im = Image.new("L", (32, 32), color)
    if noisy:
        im.putdata([(i * 37) % 256 for i in range(32 * 32)])
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


class TestScoreJpeg:
    def test_black_scores_low(self):
        assert score_jpeg(_jpeg(0)) < 6.0

    def test_picture_scores_higher_than_black(self):
        assert score_jpeg(_jpeg(120, noisy=True)) > score_jpeg(_jpeg(0))

    def test_undecodable_falls_back_to_size(self):
        assert score_jpeg(b"x" * 2000) == pytest.approx(2.0)


class _Frames:
    """Feeds a scripted sequence of frames, one per poll."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0

    def get(self):
        f = self.frames[min(self.i, len(self.frames) - 1)] if self.frames else None
        self.i += 1
        return f


def _score(frame: bytes) -> float:
    return float(frame[0])


class TestCaptureBestFrame:
    async def test_black_frames_not_announced_until_good_one(self):
        frames = _Frames([b"\x01a", b"\x02b", b"\x20c"])
        reported: list[float] = []
        best, s = await capture_best_frame(
            frames.get, lambda: True, lambda f, sc: reported.append(sc), window=0.2, poll=0.01, score=_score
        )
        assert reported == [32.0]
        assert best == b"\x20c"
        assert s == 32.0

    async def test_only_clear_improvements_reported(self):
        frames = _Frames([b"\x20a", b"\x21b", b"\x40c"])
        reported: list[float] = []
        await capture_best_frame(
            frames.get, lambda: True, lambda f, sc: reported.append(sc), window=0.2, poll=0.01, score=_score
        )
        assert reported == [32.0, 64.0]

    async def test_all_black_reported_once_at_end(self):
        frames = _Frames([b"\x01a", b"\x02b"])
        reported: list[float] = []
        best, s = await capture_best_frame(
            frames.get, lambda: True, lambda f, sc: reported.append(sc), window=0.1, poll=0.01, score=_score
        )
        assert reported == [2.0]
        assert best == b"\x02b"
        assert s == 2.0

    async def test_no_frames(self):
        reported: list = []
        best, s = await capture_best_frame(
            lambda: None, lambda: True, lambda f, sc: reported.append(sc), window=0.05, poll=0.01
        )
        assert (best, s) == (None, -1.0)
        assert reported == []

    async def test_stops_when_inactive(self):
        calls = 0

        def get():
            nonlocal calls
            calls += 1

        await capture_best_frame(get, lambda: False, lambda f, sc: None, window=1.0, poll=0.01)
        assert calls == 0
