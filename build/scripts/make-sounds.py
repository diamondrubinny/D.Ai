#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Synthesizes the D.Ai sound theme, "the diamond family" (docs/SOUNDS.md).

  python3 build/scripts/make-sounds.py

Every sound is a struck crystal: glass-like overtones (x1, x2.32, x4.25, x6.63) that fade faster the
higher they are, a soft 5 ms attack and a short, gentle reverb. All the notes are from D major
pentatonic, so any two sounds go together. Writes Ogg Vorbis files (ffmpeg) to
build/live-build/common/includes.chroot_after_packages/usr/share/sounds/dai/stereo/. The files are
committed; run this again only to change the sounds. Needs numpy and ffmpeg.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build/live-build/common/includes.chroot_after_packages/usr/share/sounds/dai/stereo"
RATE = 48000
PEAK = 10 ** (-12 / 20)  # -12 dBFS

# D major pentatonic, by name (Hz)
NOTE = {"F#4": 369.99, "A4": 440.00, "B4": 493.88, "D5": 587.33, "E5": 659.26, "F#5": 739.99, "A5": 880.00,
        "B5": 987.77, "D6": 1174.66, "E6": 1318.51, "F#6": 1479.98, "A6": 1760.00, "B6": 1975.53, "D7": 2349.32}
PARTIALS = ((1.0, 1.0, 1.0), (2.32, 0.45, 2.4), (4.25, 0.22, 4.0), (6.63, 0.10, 6.5))  # ratio, level, decay speed


def crystal(freq: float, length: float, decay: float = 3.2, level: float = 1.0, warmth: float = 0.0) -> np.ndarray:
    """One struck crystal, stereo: a slight detune between the ears gives width without blur."""
    t = np.arange(int(RATE * length)) / RATE
    attack = np.minimum(1.0, t / 0.005)
    left = np.zeros_like(t)
    right = np.zeros_like(t)
    for ratio, amp, speed in PARTIALS:
        envelope = np.exp(-t * decay * speed / 2.0)
        phase = 2 * np.pi * freq * ratio * t
        left += amp * envelope * np.sin(phase)
        right += amp * envelope * np.sin(phase * 1.0012 + 0.3)
    if warmth:  # a soft octave below for warnings and errors: weight, not alarm
        envelope = np.exp(-t * decay)
        left += warmth * envelope * np.sin(np.pi * freq * t)
        right += warmth * envelope * np.sin(np.pi * freq * t * 1.001)
    return np.stack([left, right], axis=1) * attack[:, None] * level


def place(track: np.ndarray, sound: np.ndarray, at: float) -> None:
    start = int(RATE * at)
    end = min(len(track), start + len(sound))
    track[start:end] += sound[: end - start]


def notes(sequence: list[tuple[str, float, float]], length: float, decay: float = 3.2,
          warmth: float = 0.0) -> np.ndarray:
    """(note, when, level) one after another on one track."""
    track = np.zeros((int(RATE * length), 2))
    for name, when, level in sequence:
        place(track, crystal(NOTE[name], length - when, decay, level, warmth), when)
    return track


def click(length: float = 0.02) -> np.ndarray:
    """A soft, filtered "tick" (a camera without the shutter noise)."""
    rng = np.random.default_rng(7)
    n = int(RATE * length)
    noise = rng.standard_normal(n)
    smooth = np.convolve(noise, np.ones(24) / 24, mode="same") * np.exp(-np.arange(n) / (RATE * 0.004))
    return np.stack([smooth, smooth], axis=1) * 0.6


def reverb(signal: np.ndarray, amount: float = 0.18) -> np.ndarray:
    """A short, light room: a few comb filters, mixed in quietly."""
    tail = np.zeros_like(signal)
    for delay_ms, feedback in ((29.7, 0.55), (37.1, 0.5), (41.1, 0.45), (43.7, 0.42)):
        delay = int(RATE * delay_ms / 1000)
        echo = np.zeros_like(signal)
        for start in range(delay, len(signal), delay):
            echo[start:] += signal[: len(signal) - start] * feedback ** (start // delay)
            if feedback ** (start // delay) < 0.02:
                break
        tail += echo
    return signal + amount * tail / 4


def finish(signal: np.ndarray, fade: float = 0.08) -> np.ndarray:
    signal = reverb(signal)
    n = int(RATE * fade)
    signal[-n:] *= np.linspace(1, 0, n)[:, None]  # always end in silence: no click
    return signal / (np.abs(signal).max() or 1) * PEAK


def theme() -> dict[str, np.ndarray]:
    login = notes([("D5", 0.0, 0.8), ("F#5", 0.09, 0.8), ("A5", 0.18, 0.85), ("D6", 0.27, 1.0)], 1.6, decay=2.4)
    information = notes([("A5", 0.0, 0.8), ("D6", 0.11, 1.0)], 0.8)
    sounds = {
        "desktop-login": login,
        "desktop-logout": notes([("D6", 0.0, 0.9), ("A5", 0.12, 0.85), ("F#5", 0.24, 0.8), ("D5", 0.36, 0.8)], 1.4,
                                decay=2.6),
        "message-new-instant": information,
        "dialog-information": information,
        "complete": notes([("D5", 0.0, 0.85), ("A5", 0.08, 1.0)], 0.7),
        "dialog-warning": notes([("F#5", 0.0, 1.0)], 0.6, decay=4.0, warmth=0.35),
        "dialog-error": notes([("B4", 0.0, 1.0), ("F#4", 0.13, 0.9)], 0.7, decay=4.0, warmth=0.45),
        "bell": notes([("E6", 0.0, 0.6)], 0.3, decay=9.0),
        "device-added": notes([("D5", 0.0, 0.8), ("A5", 0.06, 1.0)], 0.5, decay=5.0),
        "device-removed": notes([("A5", 0.0, 1.0), ("D5", 0.06, 0.8)], 0.5, decay=5.0),
        "power-plug": notes([("A4", 0.0, 0.8), ("D5", 0.0, 0.5), ("A5", 0.07, 1.0)], 0.6, decay=4.5),
        "power-unplug": notes([("A5", 0.0, 1.0), ("D5", 0.07, 0.6), ("A4", 0.07, 0.8)], 0.6, decay=4.5),
        "audio-volume-change": notes([("A5", 0.0, 1.0)], 0.15, decay=14.0),
        "trash-empty": notes([("B6", 0.0, 0.7), ("A6", 0.05, 0.7), ("F#6", 0.10, 0.8)], 0.45, decay=7.0),
    }
    capture = notes([("D7", 0.03, 0.5)], 0.4, decay=8.0)
    place(capture, click(), 0.0)
    sounds["screen-capture"] = capture
    return {name: finish(signal) for name, signal in sounds.items()}


def write(name: str, signal: np.ndarray) -> Path:
    pcm = (signal * 32767).astype("<i2")
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / f"{name}.wav"
        with wave.open(str(raw), "wb") as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(RATE)
            out.writeframes(pcm.tobytes())
        target = OUT / f"{name}.oga"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw), "-c:a", "libvorbis", "-q:a", "5",
                        "-map_metadata", "-1", "-fflags", "+bitexact", "-f", "ogg", str(target)], check=True)
    return target


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, signal in theme().items():
        path = write(name, signal)
        print(f"{path.name}: {len(signal) / RATE:.2f} s, {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
