import numpy as np

from src import sweep2


def test_all_three_conditions_required():
    thr, md = 0.55, 3.0
    # both cameras + near in 3D
    assert sweep2.decide([0.8], [0.8], [0.5], thr, md)[0]
    # one camera short
    assert not sweep2.decide([0.8], [0.3], [0.5], thr, md)[0]
    assert not sweep2.decide([0.3], [0.8], [0.5], thr, md)[0]
    # both cameras agree but the point is in the wrong place -- THE case that
    # exposed the original bug: 0.79 / 0.74 with a 3D distance of 3.85
    assert not sweep2.decide([0.79], [0.74], [3.85], thr, md)[0]


def test_nan_distance_is_never_present():
    # NaN means the pair was never triangulated; it must not slip through a
    # comparison that silently evaluates False either way.
    assert not sweep2.decide([0.9], [0.9], [np.nan], 0.55, 3.0)[0]


def test_decide_is_vectorised_elementwise():
    out = sweep2.decide([0.9, 0.9, 0.2], [0.9, 0.9, 0.9], [0.1, 9.0, 0.1], 0.55, 3.0)
    assert out.tolist() == [True, False, False]


def test_threshold_is_inclusive():
    assert sweep2.decide([0.55], [0.55], [3.0], 0.55, 3.0)[0]
