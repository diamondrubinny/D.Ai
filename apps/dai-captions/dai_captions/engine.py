# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The captions pipeline: sound in chunks → whisper.cpp in D.Ai Voice's sandbox → lines of text.

Sound comes from the default output's monitor through PipeWire (pw-record with stream.capture.sink), five
seconds at a time, into the user's tmpfs; each chunk goes through dai_voice.engine.transcribe (bubblewrap,
no network, no home) and is deleted at once. Nothing is written anywhere else. A file can stand in for the
speakers (--from-file), which is how the VM checks the pipeline without sound hardware.
"""

from __future__ import annotations

import os
import struct
import subprocess
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from dai_ai.paths import runtime_dir
from dai_voice.engine import VoiceError, transcribe

CHUNK_SECONDS = 5
RATE = 16000
MAX_LINES = 3
Transcriber = Callable[[Path], str]


def chunk_path(index: int) -> Path:
    return runtime_dir() / f"captions-{index % 4}.wav"


def record_argv(path: Path, seconds: int = CHUNK_SECONDS) -> list[str]:
    """pw-record on the default output's monitor (no device to choose), 16 kHz mono, SIGINT writes the header."""
    return ["timeout", "--signal=INT", str(seconds), "pw-record",
            "-P", "{ stream.capture.sink = true }", "--rate", str(RATE), "--channels", "1", "--format", "s16", str(path)]


def record_chunk(index: int, run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 seconds: int = CHUNK_SECONDS) -> Path | None:
    """One chunk from the speakers, or None when nothing could be recorded."""
    path = chunk_path(index)
    path.unlink(missing_ok=True)
    try:
        run(record_argv(path, seconds), stdin=subprocess.DEVNULL, capture_output=True, timeout=seconds + 10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if not path.is_file() or path.stat().st_size <= 44:
        path.unlink(missing_ok=True)
        return None
    return path


def file_chunks(source: Path, seconds: int = CHUNK_SECONDS) -> Iterator[Path]:
    """A WAV file as the chunks the speakers would have given (16 kHz mono s16 after a plain resample)."""
    with wave.open(str(source), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise VoiceError("only 16-bit WAV files can stand in for the speakers")
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    if channels > 1:
        samples = samples[::channels]
    if rate != RATE:
        step = rate / RATE
        samples = tuple(samples[int(i * step)] for i in range(int(len(samples) / step)))
    per_chunk = RATE * seconds
    for index, start in enumerate(range(0, len(samples), per_chunk)):
        part = samples[start:start + per_chunk]
        path = chunk_path(index)
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(RATE)
            out.writeframes(struct.pack(f"<{len(part)}h", *part))
        os.chmod(path, 0o600)
        yield path


def silent(path: Path, threshold: int = 200) -> bool:
    """True when the chunk is (near) silence: nothing to send through whisper."""
    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.readframes(wav.getnframes())
    except (OSError, wave.Error, EOFError):
        return True
    if not frames:
        return True
    samples = struct.unpack(f"<{len(frames) // 2}h", frames[: (len(frames) // 2) * 2])
    peak = max((abs(s) for s in samples), default=0)
    return peak < threshold


@dataclass
class Captions:
    """The lines shown: the last MAX_LINES, newest last; a chunk's text joins the previous line's sentence."""
    lines: list[str] = field(default_factory=list)
    max_lines: int = MAX_LINES

    def add(self, text: str) -> str:
        text = text.strip()
        if not text:
            return self.text
        if self.lines and not self.lines[-1].rstrip().endswith((".", "?", "!", "。", "؟")):
            self.lines[-1] = (self.lines[-1] + " " + text).strip()
        else:
            self.lines.append(text)
        del self.lines[:-self.max_lines]
        return self.text

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def transcribe_chunk(path: Path, lang: str | None = None) -> str:
    """The text of one chunk; the chunk is deleted whatever happens."""
    return transcribe(path, lang=lang, delete=True)


def run_pipeline(chunks: Iterator[Path], transcriber: Transcriber = transcribe_chunk,
                 emit: Callable[[str], None] = print, captions: Captions | None = None,
                 stop: Callable[[], bool] = lambda: False) -> Captions:
    """Chunks → lines; emit() gets the current text after each chunk that had speech."""
    captions = captions or Captions()
    for path in chunks:
        if stop():
            path.unlink(missing_ok=True)
            break
        if silent(path):
            path.unlink(missing_ok=True)
            continue
        text = transcriber(path)
        if text:
            emit(captions.add(text))
    return captions


def live_chunks(stop: Callable[[], bool], run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                seconds: int = CHUNK_SECONDS) -> Iterator[Path]:
    """Chunks from the speakers until stop() says so; a failed recording waits a moment and tries again."""
    index = 0
    while not stop():
        path = record_chunk(index, run, seconds)
        index += 1
        if path is None:
            time.sleep(1.0)
            continue
        yield path
