import numpy as np
import pytest

from vedit import multicam, sfx
from vedit.ff import run
from vedit.probe import probe
from vedit.timeline import SFX_KINDS


# ---------------------------------------------------------------- SFX

def test_kinds_match_timeline():
    assert set(SFX_KINDS) == set(sfx.durations) == set(sfx.SFX_HELP)


@pytest.mark.parametrize("kind", SFX_KINDS)
def test_sfx_synth_and_file(kind, vhome):
    x = sfx.synth(kind)
    assert x.dtype == np.float32 and x.ndim == 2 and x.shape[1] == 2
    assert not np.isnan(x).any()
    dur = len(x) / sfx.SR
    assert abs(dur - sfx.duration(kind)) <= 0.1 * sfx.duration(kind)
    peak_db = 20 * np.log10(np.abs(x).max())
    assert -4 <= peak_db <= -2
    assert np.array_equal(x, sfx.synth(kind))  # determinist

    p = sfx.sfx_path(kind)
    assert p.exists() and p.parent.name == ".sfx"
    info = probe(str(p))
    assert info.has_audio
    assert abs(info.duration - dur) < 0.02
    mtime = p.stat().st_mtime_ns
    assert sfx.sfx_path(kind).stat().st_mtime_ns == mtime  # din cache


def test_whoosh_energy_centered():
    x = sfx.synth("whoosh").astype(float)
    e = (x ** 2).sum(axis=1)
    t = np.arange(len(e)) / sfx.SR
    centroid = (e * t).sum() / e.sum()
    assert abs(centroid - len(e) / sfx.SR / 2) < 0.08


def test_impact_is_low():
    x = sfx.synth("impact").astype(float).mean(axis=1)
    spec = np.abs(np.fft.rfft(x)) ** 2
    fr = np.fft.rfftfreq(len(x), 1 / sfx.SR)
    assert spec[fr < 200].sum() / spec.sum() > 0.6


def test_riser_ends_loud():
    x = sfx.synth("riser").astype(float)
    n = len(x) // 10
    assert np.abs(x[-n:]).mean() > 5 * np.abs(x[:n]).mean()


def test_unknown_kind(vhome):
    with pytest.raises(ValueError, match="necunoscut"):
        sfx.synth("laser")
    with pytest.raises(ValueError):
        sfx.sfx_path("../x")


# ---------------------------------------------------------------- sincronizare

SR = 48000


def _speechy(seconds: float, seed: int) -> np.ndarray:
    """Rafale de zgomot colorat cu pauze aleatoare ("vorbire" sintetică)."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * SR))
    t = 0.0
    while t < seconds:
        t += rng.uniform(0.05, 0.6)
        ln = rng.uniform(0.08, 0.5)
        a, b = int(t * SR), min(len(out), int((t + ln) * SR))
        if a >= b:
            break
        n = b - a
        burst = np.cumsum(rng.standard_normal(n)) * 0.02 + rng.standard_normal(n) * 0.5
        burst -= np.convolve(burst, np.ones(200) / 200, mode="same")
        out[a:b] = burst * np.hanning(n) * rng.uniform(0.3, 1.0)
        t += ln
    return out / np.abs(out).max() * 0.8


def _write(path, y):
    wav = path.with_suffix(".wav")
    sfx.write_wav(wav, np.stack([y, y], axis=1).astype(np.float32), SR)
    run(["-y", "-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(path)])
    return str(path)


@pytest.fixture(scope="module")
def cams(tmp_path_factory):
    d = tmp_path_factory.mktemp("cams")
    rng = np.random.default_rng(7)
    sig = _speechy(20, seed=1)
    delay = 3.217
    lead = _speechy(delay, seed=99) * 0.5                 # altceva înainte ca B să "prindă" scena
    b = np.concatenate([lead, sig]) * 0.3
    rms = np.sqrt(np.mean(b[np.abs(b) > 1e-4] ** 2))
    b = b + rng.standard_normal(len(b)) * rms * 0.1      # zgomot alb la -20 dB față de vorbire
    a_path = _write(d / "a.m4a", sig)
    b_path = _write(d / "b.m4a", b[: int(21 * SR)])
    other = _write(d / "c.m4a", _speechy(18, seed=42))
    return a_path, b_path, other, delay


def test_find_offset_positive(cams):
    a, b, _, delay = cams
    off, conf = multicam.find_offset(a, b, max_offset=10)
    assert abs(off - delay) < 0.01, off
    assert conf > 0.4


def test_find_offset_negative(cams):
    a, b, _, delay = cams
    off, conf = multicam.find_offset(b, a, max_offset=10)
    assert abs(off + delay) < 0.01, off
    assert conf > 0.4


def test_find_offset_unrelated(cams):
    a, b, other, _ = cams
    _, good = multicam.find_offset(a, b, max_offset=10)
    _, bad = multicam.find_offset(a, other, max_offset=10)
    assert bad < 0.3
    assert bad < good / 2


# ---------------------------------------------------------------- planuri

def _check_cover(ranges, duration):
    assert ranges[0][0] == 0 and ranges[-1][1] == pytest.approx(duration)
    for (s0, e0, _), (s1, _, _) in zip(ranges, ranges[1:]):
        assert e0 == s1
    assert all(e > s for s, e, _ in ranges)


def _angle_at(ranges, t):
    return next(a for s, e, a in ranges if s <= t < e)


def test_plan_switches_basic():
    segs = [(0.5, 6, "S0"), (6.2, 12, "S1"), (12, 12.8, "S0"), (12.8, 20, "S1"), (20, 26, "S0")]
    mapping = {"S0": "a1", "S1": "a2"}
    r = multicam.plan_switches(segs, mapping, 28, min_shot=1.5)
    _check_cover(r, 28)
    assert all(e - s >= 1.5 for s, e, _ in r)
    assert {a for *_, a in r} <= {"a1", "a2"}
    assert _angle_at(r, 3) == "a1" and _angle_at(r, 9) == "a2" and _angle_at(r, 23) == "a1"
    assert _angle_at(r, 12.4) == "a2"      # replica scurtă a lui S0 nu produce un plan de 0.8 s
    assert _angle_at(r, 27) == "a1"        # liniștea de la final păstrează unghiul


def test_plan_switches_wide_for_overlap():
    segs = [(0, 5, "S0"), (4, 9, "S1"), (9, 14, "S0")]
    r = multicam.plan_switches(segs, {"S0": "a1", "S1": "a2"}, 14, wide="w", min_shot=0.5)
    _check_cover(r, 14)
    assert _angle_at(r, 4.5) == "w"
    assert _angle_at(r, 2) == "a1" and _angle_at(r, 7) == "a2" and _angle_at(r, 12) == "a1"


def test_plan_switches_wide_every():
    segs = [(0, 10, "S0"), (10, 20, "S1"), (20, 30, "S0"), (30, 40, "S1")]
    r = multicam.plan_switches(segs, {"S0": "a1", "S1": "a2"}, 40, wide="w", min_shot=1.5, wide_every=15)
    _check_cover(r, 40)
    wides = [(s, e) for s, e, a in r if a == "w"]
    assert wides and all(abs((e - s) - 2) < 1e-6 for s, e in wides)
    assert all(e - s >= 1.5 for s, e, _ in r)


def test_rotate_switches():
    words = list(np.arange(0.37, 30, 0.83))
    r = multicam.rotate_switches(30, ["a1", "a2", "a3"], 4, boundaries=words)
    _check_cover(r, 30)
    assert [a for *_, a in r[:4]] == ["a1", "a2", "a3", "a1"]
    for s, *_ in r[1:]:
        assert any(abs(s - w) < 1e-6 for w in words)
    assert all(2.0 <= e - s <= 6.5 for s, e, _ in r)
    plain = multicam.rotate_switches(10, ["x", "y"], 3)
    assert plain == [(0.0, 3.0, "x"), (3.0, 6.0, "y"), (6.0, 10.0, "x")]
