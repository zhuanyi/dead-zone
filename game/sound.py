"""Synthesised sound effects (raw WAV buffers - no audio files, no numpy).

play(name, volume, pan) positions a sound in stereo; the engine uses it to
place zombie groans, growls and swipes where the zombie actually is, so you
can hear one coming from behind. Degrades to a no-op without audio.
"""
import array
import math
import random
import struct
import pygame

_SAMPLE = 22050


def _wav(samples):
    data = array.array("h", (int(max(-1.0, min(1.0, v)) * 30000)
                             for v in samples)).tobytes()
    header = struct.pack("<4sI4s4sIHHIIHH4sI",
                         b"RIFF", 36 + len(data), b"WAVE",
                         b"fmt ", 16, 1, 1, _SAMPLE, _SAMPLE * 2, 2, 16,
                         b"data", len(data))
    return header + data


def _n(sec):
    return int(_SAMPLE * sec)


def _noise(n, rnd):
    return [rnd.uniform(-1.0, 1.0) for _ in range(n)]


def _lowpass(xs, a):
    y, out = 0.0, []
    for x in xs:
        y += a * (x - y)
        out.append(y)
    return out


def _saw(freqs):
    ph, out = 0.0, []
    for f in freqs:
        ph = (ph + f / _SAMPLE) % 1.0
        out.append(2.0 * ph - 1.0)
    return out


# ---- generators: rnd -> list of floats in [-1, 1] ---------------------
def gen_shoot(rnd):
    n = _n(0.22)
    crack, body = _noise(n, rnd), _lowpass(_noise(n, rnd), 0.3)
    out = []
    for i in range(n):
        t = i / n
        thump = math.sin(2 * math.pi * (120 - 70 * t) * i / _SAMPLE)
        out.append(crack[i] * max(0.0, 1 - t * 12) * 0.7
                   + body[i] * (1 - t) ** 3 * 2.0 + thump * (1 - t) ** 2 * 0.7)
    return out


def gen_hit(rnd):
    n = _n(0.09)
    body = _lowpass(_noise(n, rnd), 0.2)
    return [body[i] * 2.4 * (1 - i / n) ** 2
            + math.sin(2 * math.pi * 160 * i / _SAMPLE) * (1 - i / n) * 0.5
            for i in range(n)]


def gen_kill(rnd):
    n = _n(0.38)
    body = _lowpass(_noise(n, rnd), 0.12)
    out = []
    for i in range(n):
        t = i / n
        wob = 0.6 + 0.4 * math.sin(2 * math.pi * 11 * t)
        tone = math.sin(2 * math.pi * (190 - 120 * t) * i / _SAMPLE)
        out.append(body[i] * 3.0 * wob * (1 - t) ** 1.5 + tone * 0.35 * (1 - t))
    return out


def gen_hurt(rnd):
    n = _n(0.22)
    saw = _lowpass(_saw([130 - 40 * i / n for i in range(n)]), 0.15)
    nz = _lowpass(_noise(n, rnd), 0.3)
    return [(saw[i] * 1.6 + nz[i] * 0.5) * math.sin(math.pi * i / n) for i in range(n)]


def gen_reload(rnd):
    n = _n(0.5)
    nz = _noise(n, rnd)
    out = []
    for i in range(n):
        t = i / n
        v = 0.0
        for start in (0.0, 0.78):
            if start <= t < start + 0.06:
                k = 1 - (t - start) / 0.06
                v += (nz[i] * 0.7 + math.sin(2 * math.pi * 2100 * i / _SAMPLE) * 0.4) * k ** 2
        out.append(v)
    return out


def gen_pickup(rnd):
    n = _n(0.14)
    return [math.sin(2 * math.pi * (600 + 800 * i / n) * i / _SAMPLE) * (1 - i / n) * 0.6
            for i in range(n)]


def gen_empty(rnd):
    n = _n(0.04)
    nz = _noise(n, rnd)
    return [nz[i] * (1 - i / n) ** 4 * 0.6 for i in range(n)]


def gen_swipe(rnd):
    n = _n(0.28)
    nz = _lowpass(_noise(n, rnd), 0.25)
    return [nz[i] * 2.2 * math.sin(math.pi * i / n) ** 2 for i in range(n)]


def gen_alert(rnd):
    n = _n(0.6)
    saw = _lowpass(_saw([95 + 25 * math.sin(2 * math.pi * 7 * i / _SAMPLE)
                         for i in range(n)]), 0.1)
    nz = _lowpass(_noise(n, rnd), 0.2)
    return [(saw[i] * 1.8 + nz[i] * 0.8) * math.sin(math.pi * i / n) ** 0.6
            for i in range(n)]


def _gen_groan(f0):
    def gen(rnd):
        n = _n(1.0)
        saw = _lowpass(_saw([f0 * (1 + 0.04 * math.sin(2 * math.pi * 4 * i / _SAMPLE)
                                   - 0.12 * i / n) for i in range(n)]), 0.07)
        nz = _lowpass(_noise(n, rnd), 0.1)
        return [(saw[i] * 2.4 + nz[i] * 0.6) * math.sin(math.pi * i / n) ** 1.5
                for i in range(n)]
    return gen


def gen_win(rnd):
    n = _n(0.6)
    return [math.sin(2 * math.pi * 523 * 2 ** (min(3, int(i / n * 4)) * 0.25) * i / _SAMPLE)
            * (1 - i / n) * 0.5 for i in range(n)]


def gen_lose(rnd):
    n = _n(0.8)
    return [math.sin(2 * math.pi * (300 - 200 * i / n) * i / _SAMPLE) * (1 - i / n) * 0.6
            for i in range(n)]


GENERATORS = {
    "shoot": [gen_shoot], "hit": [gen_hit], "kill": [gen_kill],
    "hurt": [gen_hurt], "reload": [gen_reload], "pickup": [gen_pickup],
    "empty": [gen_empty], "swipe": [gen_swipe], "alert": [gen_alert],
    "groan": [_gen_groan(62), _gen_groan(74), _gen_groan(88)],
    "win": [gen_win], "lose": [gen_lose],
}


class Sfx:
    def __init__(self):
        self.ok = False
        self.sounds = {}
        self._rnd = random.Random()
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(_SAMPLE, -16, 2, 512)
            pygame.mixer.set_num_channels(24)
        except Exception:
            return
        if pygame.mixer.get_init() is None:
            return
        rnd = random.Random(1234)
        for name, gens in GENERATORS.items():
            for gen in gens:
                try:
                    self.sounds.setdefault(name, []).append(
                        pygame.mixer.Sound(buffer=_wav(gen(rnd))))
                except Exception:
                    pass
        self.ok = True

    def play(self, name, vol=1.0, pan=0.0):
        """Play `name` at volume 0..1, panned -1 (left) .. +1 (right)."""
        if not self.ok or not self.sounds.get(name):
            return
        try:
            ch = self._rnd.choice(self.sounds[name]).play()
            if ch is not None:
                vol = max(0.0, min(1.0, vol))
                pan = max(-1.0, min(1.0, pan))
                ch.set_volume(vol * min(1.0, 1.0 - pan), vol * min(1.0, 1.0 + pan))
        except Exception:
            pass
