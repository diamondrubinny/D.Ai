# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Recording (PipeWire) and transcription (whisper.cpp in a sandbox).

State lives in $XDG_RUNTIME_DIR/dai (tmpfs, 0700): the recorder's PID and the
WAV file. Nothing is written anywhere else, and the WAV is deleted as soon as
it has been transcribed (or a new recording starts).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from dai_ai.models import ModelError, default_model_id, load_catalog
from dai_ai.paths import config_file, runtime_dir

WHISPER_DIR = Path(os.environ.get("DAI_WHISPER_DIR", "/opt/dai/whisper"))
MAX_SECONDS = 120
LANGS = ("auto", "he", "en", "ar", "ru", "fr", "de", "es")
# whisper prints these for silence or noise; they are not text.
NON_SPEECH = re.compile(r"\[(?:BLANK_AUDIO|MUSIC|NOISE|SILENCE|INAUDIBLE)[^\]]*\]|\((?:music|silence|noise)\)",
                        re.IGNORECASE)

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class VoiceError(RuntimeError):
    pass


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=600, check=False)


@dataclass(frozen=True)
class Settings:
    lang: str = "auto"
    model: str | None = None


def settings() -> Settings:
    """~/.config/dai/voice.json: {"lang": "auto"|"he"|"en"..., "model": "whisper-small"}."""
    path = config_file().with_name("voice.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    lang = data.get("lang") if data.get("lang") in LANGS else "auto"
    if os.environ.get("DAI_VOICE_LANG") in LANGS:
        lang = os.environ["DAI_VOICE_LANG"]
    model = data.get("model") if isinstance(data.get("model"), str) else None
    return Settings(lang=lang, model=model)


def model_path(chosen: str | None = None) -> Path:
    try:
        models = load_catalog()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise VoiceError(f"cannot read the model catalog: {exc}") from exc
    model_id = chosen if chosen in models and models[chosen].installed and "speech" in models[chosen].tasks \
        else default_model_id(models, "speech")
    if model_id is None:
        raise VoiceError("no speech model installed — run: dai-models install whisper-small")
    return models[model_id].path


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def _state_file() -> Path:
    return runtime_dir() / "voice.json"


def wav_path() -> Path:
    return runtime_dir() / "voice.wav"


def _alive_recorder(pid: int) -> bool:
    """True only if pid is still our recorder (PIDs can be reused)."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return any(part.endswith((b"pw-record", b"timeout")) for part in cmdline[:2])


def recording() -> dict | None:
    try:
        state = json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or not isinstance(state.get("pid"), int):
        return None
    return state if _alive_recorder(state["pid"]) else {**state, "finished": True}


def start(spawn: Callable[[list[str]], int] | None = None) -> dict:
    """Start recording 16 kHz mono from the default microphone (max MAX_SECONDS)."""
    current = recording()
    if current and not current.get("finished"):
        raise VoiceError("already recording")
    if not shutil.which("pw-record"):
        raise VoiceError("pw-record (PipeWire) is not installed")
    wav = wav_path()
    wav.unlink(missing_ok=True)
    argv = ["timeout", "--signal=INT", str(MAX_SECONDS),
            "pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", str(wav)]

    def default_spawn(cmd: list[str]) -> int:
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True).pid

    pid = (spawn or default_spawn)(argv)
    state = {"pid": pid, "wav": str(wav), "started": time.time()}
    tmp = _state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(_state_file())
    return state


def stop(wait: float = 3.0) -> Path:
    """Stop the recorder and return the WAV file."""
    state = recording()
    if state is None:
        raise VoiceError("not recording")
    if not state.get("finished"):
        try:
            os.killpg(state["pid"], signal.SIGINT)  # pw-record writes the WAV header on SIGINT
        except (ProcessLookupError, PermissionError):
            pass
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and _alive_recorder(state["pid"]):
            time.sleep(0.05)
    _state_file().unlink(missing_ok=True)
    wav = Path(state["wav"])
    if not wav.is_file() or wav.stat().st_size <= 44:
        wav.unlink(missing_ok=True)
        raise VoiceError("nothing was recorded (is a microphone connected?)")
    return wav


def cancel() -> None:
    try:
        wav = stop(wait=1.0)
        wav.unlink(missing_ok=True)
    except VoiceError:
        pass


# --------------------------------------------------------------------------
# Transcription
# --------------------------------------------------------------------------


def whisper_argv(audio: Path, model: Path, lang: str, threads: int | None = None) -> list[str]:
    """whisper-cli inside bubblewrap: no network, no home, read-only inputs."""
    if lang not in LANGS:
        raise VoiceError(f"unsupported language: {lang}")
    threads = threads or max(1, min(8, (os.cpu_count() or 2)))
    cli = [str(WHISPER_DIR / "whisper-cli"), "-m", "/model.bin", "-f", "/audio.wav",
           "-l", lang, "-t", str(threads), "-nt", "-np"]
    if not shutil.which("bwrap"):
        raise VoiceError("bubblewrap is missing; speech is only processed inside the sandbox")
    return [
        "bwrap",
        # Mount points that replace directories first, so later binds stay visible.
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache",
        "--ro-bind", str(WHISPER_DIR), str(WHISPER_DIR),
        "--ro-bind", str(model), "/model.bin",
        "--ro-bind", str(audio), "/audio.wav",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop", "ALL",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin",
        "--",
        *cli,
    ]


def clean_text(output: str) -> str:
    text = NON_SPEECH.sub(" ", output)
    return re.sub(r"\s+", " ", text).strip()


def transcribe(audio: Path, lang: str | None = None, model: Path | None = None, runner: Runner = _run,
               delete: bool = False) -> str:
    try:
        conf = settings()
        argv = whisper_argv(audio, model or model_path(conf.model), lang or conf.lang)
        if not (WHISPER_DIR / "whisper-cli").exists():
            raise VoiceError(f"whisper.cpp is not installed in {WHISPER_DIR}")
        result = runner(argv)
        if result.returncode != 0:
            detail = (result.stderr or "").strip().splitlines()[-1:] or [f"exit {result.returncode}"]
            raise VoiceError(f"transcription failed: {detail[0]}")
        return clean_text(result.stdout)
    except ModelError as exc:
        raise VoiceError(str(exc)) from exc
    finally:
        if delete:
            audio.unlink(missing_ok=True)
