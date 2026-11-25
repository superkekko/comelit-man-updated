"""Pick a good doorbell snapshot from the first seconds of the video stream.

The first decoded frame of a passive inbound session is almost always black
(a 1.8 KB JPEG while real frames are 11-13 KB), and the camera needs a moment
to settle exposure.  Instead of grabbing whatever frame is latest when the
video becomes ready, sample the stream for a short window and keep the best
frame, scored by contrast and brightness.

Kept free of Home Assistant imports so it can be tested standalone.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

# How long after the video becomes ready we keep looking for a better frame.
SNAPSHOT_WINDOW = 2.5
# How often the latest decoded frame is sampled.
SNAPSHOT_POLL = 0.15
# Scores below this are treated as a black / blank frame.
BLACK_THRESHOLD = 6.0
# A later frame replaces a non-black one only if it scores clearly better.
IMPROVEMENT_FACTOR = 1.10


def score_jpeg(jpeg: bytes) -> float:
    """Score a JPEG: higher means more picture, ~0 means black or blank.

    Luminance standard deviation (detail/contrast) plus a quarter of the mean
    brightness.  Falls back to JPEG size in KB when Pillow can't decode it —
    on this device black frames are ~1.8 KB and real ones 11+ KB, so the same
    threshold works for both scales.
    """
    try:
        from PIL import Image, ImageStat

        with Image.open(io.BytesIO(jpeg)) as im:
            stat = ImageStat.Stat(im.convert("L"))
        return float(stat.stddev[0] + 0.25 * stat.mean[0])
    except Exception:
        return len(jpeg) / 1000.0


async def capture_best_frame(
    get_frame: Callable[[], bytes | None],
    is_active: Callable[[], bool],
    on_best: Callable[[bytes, float], None],
    window: float = SNAPSHOT_WINDOW,
    poll: float = SNAPSHOT_POLL,
    score: Callable[[bytes], float] = score_jpeg,
) -> tuple[bytes | None, float]:
    """Sample frames for `window` seconds and report each clear improvement.

    `on_best(frame, score)` is called as soon as the first usable (non-black)
    frame arrives, and again only if a clearly better frame shows up later.
    Black frames are never reported while the window is open, so anything
    waiting on the snapshot entity (an automation sending the photo) is not
    woken up by the black first frame.  If the window ends with nothing but
    black frames, the best of them is reported once so listeners still get
    an update.  Returns the best frame and its score (None, -1.0 if no frame
    arrived).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + window
    best: bytes | None = None
    best_score = -1.0
    reported = False
    last: bytes | None = None

    while loop.time() < deadline and is_active():
        frame = get_frame()
        if frame is not None and frame is not last:
            last = frame
            s = await loop.run_in_executor(None, score, frame)
            if best is None or s > best_score:
                if s >= BLACK_THRESHOLD and (not reported or s > best_score * IMPROVEMENT_FACTOR):
                    on_best(frame, s)
                    reported = True
                    best, best_score = frame, s
                elif not reported:
                    # Black so far: remember it, but don't announce it yet.
                    best, best_score = frame, s
        await asyncio.sleep(poll)

    if best is not None and not reported:
        on_best(best, best_score)
    return best, best_score
