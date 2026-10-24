#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The D.Ai OS promo video (English, 16:9, about 70 seconds), built from the CI screenshots.

  python3 build/assets/make_promo.py [OUT_DIR]        -> OUT_DIR/dai-os-promo.mp4, narration.srt, SCRIPT.md

Deterministic: title cards are drawn with PIL on the Night 2 wallpaper, every screenshot gets a slow zoom,
scenes cross-fade, captions are burned in, and the music is a soft synthesized pad (no third-party assets,
nothing to license). The narration is written as text with timings, for a person or a TTS voice to record.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots"
WALLPAPER = ROOT / "build/live-build/common/includes.chroot_after_packages/usr/share/dai/branding/wallpaper-night.jpg"
FONTS = Path("/usr/share/fonts/opentype/inter")
W, H, FPS = 1920, 1080, 30
TEXT, MUTED, ACCENT, CYAN, MAGENTA = "#E6E9F5", "#9AA3C7", "#7C5CFF", "#22D3EE", "#FF7A9E"
FADE = 0.8


@dataclass(frozen=True)
class Scene:
    seconds: float
    narration: str
    shot: str = ""                 # a screenshot file name, or "" for a title card
    title: str = ""                # the card's big line / the caption's first line
    sub: str = ""                  # the card's second line / the caption's second line


SCENES = (
    Scene(5.0, "D.Ai OS. A computer that speaks your language.",
          title="D.Ai OS", sub="The computer that does what you say, and keeps it to itself"),
    Scene(8.0, "Ask for what you want, in a sentence. Block USB storage. Lock the screen after five minutes. "
               "Diamond shows the plan, you approve, and anything can be undone.",
          shot="ai-answer.png", title="Say it. See the plan. Approve.", sub="Every change is shown first, and can be undone"),
    Scene(6.5, "Your AI runs here, on your computer. Nothing leaves it unless you say so.",
          shot="start-menu.png", title="Your AI, on your computer", sub="No account. No cloud. Nothing sent unless you choose a provider"),
    Scene(7.5, "Describe an app, and D.Ai Forge writes it, tests it, and runs it in a sandbox.",
          shot="forge-app.png", title="Build an app by describing it", sub="D.Ai Forge writes, tests, and runs it in a sandbox"),
    Scene(7.0, "Safe by design: full-disk encryption, a firewall, sandboxed readers, and a security score you can read.",
          shot="settings.png", title="Safe by design", sub="Disk encryption, a firewall, sandboxed readers, a score you can read"),
    Scene(6.5, "Hebrew, Arabic, Russian and more, right to left or left to right, from the very first screen.",
          shot="welcome-ar.png", title="In your language, from the first screen", sub="Hebrew, Arabic, Russian, Spanish, French, German, Portuguese, English"),
    Scene(6.0, "Find files by what is inside them. Live captions for anything that plays.",
          shot="find.png", title="Find files by what is inside them", sub="A local index; nothing leaves the computer"),
    Scene(6.0, "Encrypted messages between your computers, with no account and no server.",
          shot="captions.png", title="Live captions, encrypted chat", sub="For anything that plays; messages end to end, with no account"),
    Scene(6.0, "Beautiful, fast, and free. Open source, built on Debian.",
          shot="desktop.png", title="Beautiful. Fast. Free.", sub="Open source, built on Debian 13"),
    Scene(6.0, "D.Ai OS. Download it at rubinny.com.",
          title="D.Ai OS", sub="rubinny.com  ·  free and open source"),
)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def background() -> Image.Image:
    img = Image.open(WALLPAPER).convert("RGB").resize((W, H), Image.LANCZOS)
    dark = Image.new("RGB", (W, H), "#070A18")
    return Image.blend(img, dark, 0.35)


def diamond(size: int) -> Image.Image:
    """The brand diamond: a faceted gem in the brand colours, drawn with polygons."""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top, mid, bottom = int(s * 0.18), int(s * 0.42), int(s * 0.95)
    left, right = int(s * 0.08), int(s * 0.92)
    cx = s // 2
    crown = [(left, mid), (int(s * 0.30), top), (int(s * 0.70), top), (right, mid)]
    d.polygon(crown, fill="#B8A6FF")
    d.polygon([(int(s * 0.30), top), (cx, mid), (int(s * 0.70), top)], fill="#E6E9F5")
    d.polygon([(left, mid), (int(s * 0.30), top), (cx, mid)], fill="#7C5CFF")
    d.polygon([(right, mid), (int(s * 0.70), top), (cx, mid)], fill="#22D3EE")
    d.polygon([(left, mid), (cx, mid), (cx, bottom)], fill="#5B3FD6")
    d.polygon([(right, mid), (cx, mid), (cx, bottom)], fill="#0EA5C0")
    d.polygon([(int(s * 0.30), mid), (int(s * 0.70), mid), (cx, bottom)], fill="#9AA3C7")
    # a sparkle
    sx, sy, r = int(s * 0.86), int(s * 0.10), int(s * 0.07)
    d.polygon([(sx, sy - r), (sx + r // 3, sy), (sx, sy + r), (sx - r // 3, sy)], fill="#FFFFFF")
    return img


def glow(layer: Image.Image, radius: int) -> Image.Image:
    return layer.filter(ImageFilter.GaussianBlur(radius))


def card(scene: Scene, path: Path) -> None:
    img = background()
    d = ImageDraw.Draw(img)
    gem = diamond(260)
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    halo.paste(Image.new("RGBA", (420, 420), (124, 92, 255, 120)), (W // 2 - 210, 170))
    img.paste(glow(halo, 90), (0, 0), glow(halo, 90))
    img.paste(gem, (W // 2 - 130, 200), gem)
    big = font("InterDisplay-ExtraBold.otf", 128)
    small = font("Inter-Regular.otf", 44)
    tw = d.textlength(scene.title, font=big)
    d.text(((W - tw) / 2, 500), scene.title, font=big, fill=TEXT)
    sw = d.textlength(scene.sub, font=small)
    d.text(((W - sw) / 2, 680), scene.sub, font=small, fill=MUTED)
    img.save(path, "PNG")


def framed_shot(scene: Scene, path: Path) -> None:
    """The screenshot on the wallpaper, with rounded corners and a soft shadow, room for the caption below."""
    img = background()
    shot = Image.open(SHOTS / scene.shot).convert("RGB")
    sw, sh = 1340, int(1340 * shot.height / shot.width)   # 1340 x 838: the caption band below stays clear
    shot = shot.resize((sw, sh), Image.LANCZOS)
    x, y = (W - sw) // 2, 56
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x - 10, y + 24, x + sw + 10, y + sh + 44), 28, fill=(0, 0, 0, 170))
    shadow = glow(shadow, 30)
    img.paste(shadow, (0, 0), shadow)
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw, sh), 22, fill=255)
    img.paste(shot, (x, y), mask)
    ImageDraw.Draw(img).rounded_rectangle((x, y, x + sw, y + sh), 22, outline="#2A3563", width=2)
    img.save(path, "PNG")


def caption(scene: Scene, path: Path) -> None:
    """A transparent overlay: the caption under the screenshot (it does not zoom with the picture)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for row in range(880, H):  # a dark band that fades in under the picture, so the words always read
        alpha = int(190 * min(1.0, (row - 880) / 60))
        ImageDraw.Draw(img).line((0, row, W, row), fill=(7, 10, 24, alpha))
    d = ImageDraw.Draw(img)
    big = font("InterDisplay-Bold.otf", 60)
    small = font("Inter-Regular.otf", 34)
    tw = d.textlength(scene.title, font=big)
    d.text(((W - tw) / 2, 930), scene.title, font=big, fill=TEXT)
    sw = d.textlength(scene.sub, font=small)
    d.text(((W - sw) / 2, 1008), scene.sub, font=small, fill=MUTED)
    d.rounded_rectangle((W // 2 - 36, 916, W // 2 + 36, 921), 3, fill=ACCENT)
    img.save(path, "PNG")


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def render_scene(index: int, scene: Scene, work: Path) -> Path:
    still = work / f"scene{index}.png"
    out = work / f"scene{index}.mp4"
    frames = int(scene.seconds * FPS)
    if scene.shot:
        framed_shot(scene, still)
        overlay = work / f"caption{index}.png"
        caption(scene, overlay)
        zoom = f"zoompan=z='1+0.07*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}"
        ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", str(still), "-i", str(overlay),
               "-filter_complex", f"[0:v]scale={W * 2}:{H * 2}:flags=lanczos,{zoom}[z];[z][1:v]overlay=0:0,format=yuv420p",
               "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out))
    else:
        card(scene, still)
        ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", str(still), "-vf", "format=yuv420p",
               "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out))
    return out


def music(seconds: float, path: Path) -> None:
    """A soft pad: a detuned A minor-ish chord with slow swells, quiet, faded in and out."""
    voices = ["sin(2*PI*110*t)*0.28", "sin(2*PI*110.4*t)*0.22", "sin(2*PI*164.8*t)*0.20", "sin(2*PI*220.3*t)*0.14",
              "sin(2*PI*261.6*t)*0.10*(0.5+0.5*sin(2*PI*0.05*t))", "sin(2*PI*329.6*t)*0.07*(0.5+0.5*sin(2*PI*0.08*t+1))"]
    expr = "(" + "+".join(voices) + ")*(0.75+0.25*sin(2*PI*0.11*t))*0.5"
    ffmpeg("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={seconds}",
           "-af", f"lowpass=f=900,afade=t=in:d=2,afade=t=out:st={seconds - 3}:d=3,volume=0.5", "-c:a", "aac", "-b:a", "128k", str(path))


def assemble(parts: list[Path], scenes: tuple[Scene, ...], audio: Path, out: Path) -> None:
    inputs = [arg for part in parts for arg in ("-i", str(part))]
    chain, last, offset = [], "[0:v]", 0.0
    for i in range(1, len(parts)):
        offset += scenes[i - 1].seconds - FADE
        name = f"[v{i}]"
        chain.append(f"{last}[{i}:v]xfade=transition=fade:duration={FADE}:offset={offset:.3f}{name}")
        last = name
    graph = ";".join(chain) + f";{last}format=yuv420p[v]"
    ffmpeg(*inputs, "-i", str(audio), "-filter_complex", graph, "-map", "[v]", "-map", f"{len(parts)}:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "128k", "-shortest", str(out))


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_script(out_dir: Path) -> None:
    lines, md, start = [], ["# D.Ai OS promo: narration (English)", "",
                          "Read calmly, one line per scene; the captions on screen carry the same message.", "",
                          "| # | Start | Seconds | Scene | Narration |", "|---|-------|---------|-------|-----------|"], 0.0
    for n, scene in enumerate(SCENES, 1):
        end = start + scene.seconds
        lines += [str(n), f"{srt_time(start + 0.4)} --> {srt_time(end - 0.4)}", scene.narration, ""]
        md.append(f"| {n} | {start:5.1f}s | {scene.seconds:.1f} | {scene.shot or 'title card'} | {scene.narration} |")
        start = end - FADE
    (out_dir / "narration.srt").write_text("\n".join(lines), encoding="utf-8")
    md += ["", f"Total: about {start + FADE:.0f} seconds. Built by `build/assets/make_promo.py` from `docs/screenshots/`;",
           "the music is synthesized in the script (no third-party assets). Trademarks: \"D.Ai\" and the diamond logo (TRADEMARKS.md).", ""]
    (out_dir / "SCRIPT.md").write_text("\n".join(md), encoding="utf-8")


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else ROOT / "docs" / "promo"
    out_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg") is None:
        print("ffmpeg is needed", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        parts = [render_scene(i, scene, work) for i, scene in enumerate(SCENES)]
        total = sum(s.seconds for s in SCENES) - FADE * (len(SCENES) - 1)
        audio = work / "pad.m4a"
        music(total, audio)
        assemble(parts, SCENES, audio, out_dir / "dai-os-promo.mp4")
    write_script(out_dir)
    print(out_dir / "dai-os-promo.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
