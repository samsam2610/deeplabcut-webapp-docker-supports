import pytest
import numpy as np
import cv2
import pandas as pd
from pathlib import Path


@pytest.fixture
def mock_model(monkeypatch):
    """Replace the CLIP model singleton with a deterministic fake."""
    import processor
    rng = np.random.default_rng(42)

    class FakeModel:
        def encode(self, images, convert_to_numpy=True, batch_size=64, show_progress_bar=False):
            if isinstance(images, list):
                return rng.random((len(images), 512)).astype(np.float32)
            return rng.random(512).astype(np.float32)

    monkeypatch.setattr(processor, "_model", FakeModel())
    return FakeModel()


@pytest.fixture
def tiny_video(tmp_path):
    """50-frame 64×48 MJPEG AVI for I/O tests."""
    path = tmp_path / "test.avi"
    out = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 48)
    )
    for i in range(50):
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        frame[:, :] = (i * 5 % 256, 100, (200 - i * 4) % 256)
        out.write(frame)
    out.release()
    return path


@pytest.fixture
def tiny_csv(tmp_path):
    """Matching 50-row CSV for tiny_video (frame_number 1-based)."""
    path = tmp_path / "test.csv"
    df = pd.DataFrame({
        "timestamp": range(50),
        "frame_number": range(1, 51),
        "frame_line_status": [10] * 50,
        "note": [""] * 50,
    })
    df.to_csv(path, index=False)
    return path
