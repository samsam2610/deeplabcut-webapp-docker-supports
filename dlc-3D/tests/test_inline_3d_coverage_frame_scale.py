"""Static guards: the seek + finalize marker-coverage bars must be bucketed in
VIDEO-frame (seek-bar) space.

An overlay/analyzed h5 often has FEWER rows than the video has frames (DLC
analyzed a prefix of the video). The pose-coverage endpoint therefore takes an
optional `nframes` = video frame count so it can place each mark at its ABSOLUTE
video frame instead of compressing the coverage into the h5 length. The frontend
must pass `_frameCount` on BOTH pose-coverage fetches (seek + finalize), mirroring
the 3D triangulate-coverage bar which already scales with `&nframes=`.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _js():
    return JS.read_text()


def test_seek_coverage_fetch_passes_nframes():
    s = _js()
    # _refreshCoverage builds an nf fragment from _frameCount and appends it to the
    # pose-coverage fetch so the seek bar is scaled to the video frame count.
    assert re.search(r"_frameCount\s*>\s*0\s*\?\s*`&nframes=\$\{_frameCount\}`", s), \
        "coverage fetches must build a `&nframes=${_frameCount}` fragment"
    assert re.search(r"/dlc/viewer/pose-coverage\?[^`]*buckets=\$\{w\}\$\{nf\}", s), \
        "the seek pose-coverage fetch must append the ${nf} nframes fragment"


def test_finalize_coverage_fetch_passes_nframes():
    s = _js()
    # The finalize-coverage (presence) fetch must also append ${nf} so the finalize
    # bar aligns with the seek + 3D timelines.
    assert re.search(
        r"/dlc/viewer/pose-coverage\?[^`]*mode=presence&buckets=\$\{w\}\$\{nf\}", s
    ), "the finalize pose-coverage fetch must append the ${nf} nframes fragment"


def test_coverage_cache_key_includes_frame_count():
    s = _js()
    # Coverage now depends on the video frame count → it must be part of the cache
    # key, or a cached bar from a different video would be reused at the wrong scale.
    assert re.search(
        r"`\$\{_overlayPrimaryH5\}:\$\{thr\.toFixed\(2\)\}:\$\{w\}:\$\{_frameCount\}`", s
    ), "the coverage cache key must include _frameCount"
