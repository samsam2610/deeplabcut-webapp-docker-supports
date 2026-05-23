from pathlib import Path
from dlc_3d_bp import routes as r


def test_clip_output_path_naming():
    out = r._clip_output_path(Path("/data/vids/OM-2_cam0_x.avi"), 100, 50, "trial1")
    assert out.parent.name == "OM-2_cam0_x"
    assert out.name == "OM-2_cam0_x_100_150_trial1.avi", out.name
    out2 = r._clip_output_path(Path("/data/vids/v.avi"), 0, 10, "")
    assert out2.name == "v_0_10.avi", out2.name


def test_trim_frames_writes_expected_count(tmp_path):
    import cv2, numpy as np
    src = tmp_path / "src.avi"
    w = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"MJPG"), 20.0, (32, 24))
    for i in range(60):
        w.write(np.full((24, 32, 3), i % 255, dtype=np.uint8))
    w.release()
    out = tmp_path / "out.avi"
    n = r._trim_frames_cv2(src, out, start_frame=10, n_frames=15)
    assert n == 15
    cap = cv2.VideoCapture(str(out))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 15
    cap.release()
