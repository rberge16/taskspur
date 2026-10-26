import math

from app.downsample import lttb


def test_short_series_unchanged():
    xs = list(range(10)); ys = [float(i) for i in xs]
    assert lttb(xs, ys, 50) == (xs, ys)


def test_reduces_size_and_keeps_ends_and_peak():
    n = 20000
    xs = list(range(n))
    ys = [math.sin(i / 300) * 100 for i in xs]
    ys[12345] = 500.0                                  # einzelne Spitze darf nicht verschwinden
    ox, oy = lttb(xs, ys, 400)
    assert 300 <= len(ox) <= 420 and len(ox) == len(oy)
    assert ox[0] == 0 and ox[-1] == n - 1
    assert 500.0 in oy
    assert ox == sorted(ox)


def test_gaps_are_preserved():
    xs = list(range(3000)); ys = [float(i % 50) for i in xs]
    for i in range(1000, 1100):
        ys[i] = None
    ox, oy = lttb(xs, ys, 200)
    assert oy.count(None) == 100                       # Lücke bleibt eine Lücke, wird nicht überzeichnet
    assert len(ox) < 400


def test_length_mismatch_rejected():
    import pytest
    with pytest.raises(ValueError):
        lttb([1, 2, 3], [1, 2], 10)
