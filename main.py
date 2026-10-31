#!/usr/bin/env python3
"""
Automated Video De-duplication & Batch Sanitizer Tool
=====================================================

A standalone desktop utility for creators who own the rights to their
videos and want to produce a visually identical, re-encoded variant
for a second platform, account, or archive.

What it does, per file:
  1. Micro-crop: randomly removes 0.5% - 1.5% of the frame edges.
  2. Colour micro-tuning: tiny hue / brightness / contrast /
     saturation changes that are imperceptible in normal viewing.
  3. Audio sanitisation: a tiny tempo shift (default 1.002x) and,
     optionally, a high-frequency low-pass.
  4. Metadata wipe: strips source encoder, camera, author and
     chapter metadata.

Important honesty note
----------------------
Filters require re-encoding, so the output is *visually* near-lossless
(CRF 18 by default), not bit-identical to the source. This tool does
not guarantee that any third-party platform will treat the output as
"original", and it must only be used on content you own or are
licensed to re-publish. Respect every platform's terms of service
and copyright law.

Requirements
------------
* Python 3.9+ (standard library only -- no pip packages are needed
  to run this file).
* A working ``ffmpeg`` and ``ffprobe`` binary on PATH, or in the
  same folder as this script / the built .exe. See README.md.

Run:
    python main.py
"""

from __future__ import annotations

import json
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

APP_NAME = "Video De-duplication & Batch Sanitizer"
APP_VERSION = "1.0.0"

SUPPORTED_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv"}
TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    input_dir: Path = Path("")
    output_dir: Path = Path("")
    enable_crop: bool = True
    crop_percent: float = 1.0          # total edge reduction, %
    randomize_crop: bool = True
    enable_color: bool = True
    brightness: float = 0.01           # eq range: -1.0 .. 1.0
    contrast: float = 1.01
    saturation: float = 1.01
    hue_degrees: float = 1.0
    randomize_color: bool = True
    enable_audio: bool = True
    audio_shift: float = 1.002         # atempo factor
    strip_high_freq: bool = False
    high_freq_cutoff: int = 17000
    wipe_metadata: bool = True
    output_suffix: str = "_clean"
    output_ext: str = "mp4"
    crf: int = 18
    preset: str = "medium"
    overwrite: bool = False
    recursive: bool = False


# ---------------------------------------------------------------------------
# ffmpeg discovery / probing
# ---------------------------------------------------------------------------

def _candidate_dirs() -> list[Path]:
    """Directories to search for ffmpeg/ffprobe, besides PATH."""
    dirs = []
    try:
        dirs.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    try:
        dirs.append(Path(__file__).resolve().parent)
    except Exception:
        pass
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        dirs.append(Path(sys.executable).resolve().parent)
    return dirs


def find_tool(name: str) -> str | None:
    """Find ffmpeg/ffprobe, honouring PATH and the app folder."""
    found = shutil.which(name)
    if found:
        return found
    exe = name + ".exe" if os.name == "nt" else name
    for d in _candidate_dirs():
        candidate = d / exe
        if candidate.is_file():
            return str(candidate)
    return None


def find_ffmpeg() -> tuple[str | None, str | None]:
    return find_tool("ffmpeg"), find_tool("ffprobe")


def probe_media(ffprobe: str, path: Path) -> dict:
    """Return width/height/duration and stream presence, or {} on failure."""
    cmd = [
        ffprobe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=False,
        )
        data = json.loads(out.stdout or "{}")
    except Exception:
        return {}
    info: dict = {}
    streams = data.get("streams") or []
    if streams:
        info["width"] = streams[0].get("width")
        info["height"] = streams[0].get("height")
    fmt = data.get("format") or {}
    try:
        info["duration"] = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        info["duration"] = 0.0
    # Audio presence: a second, cheap probe.
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=False,
        )
        info["has_audio"] = bool(out.stdout.strip())
    except Exception:
        info["has_audio"] = False
    return info


def make_even(value: int) -> int:
    """H.264 yuv420p needs even dimensions."""
    return value - (value % 2)


# ---------------------------------------------------------------------------
# Filter / command construction (pure, unit-testable)
# ---------------------------------------------------------------------------

def build_video_filter(width: int | None, height: int | None,
                       settings: Settings, rng: random.Random) -> str:
    filters: list[str] = []

    if settings.enable_crop and width and height and width > 16 and height > 16:
        pct = (
            rng.uniform(0.5, 1.5)
            if settings.randomize_crop else settings.crop_percent
        )
        pct = max(0.5, min(1.5, pct))
        red_w = make_even(max(2, int(width * pct / 100.0)))
        red_h = make_even(max(2, int(height * pct / 100.0)))
        crop_w = make_even(width - red_w)
        crop_h = make_even(height - red_h)
        if crop_w >= 16 and crop_h >= 16:
            x = rng.randrange(0, red_w + 1, 2) if red_w >= 2 else 0
            y = rng.randrange(0, red_h + 1, 2) if red_h >= 2 else 0
            filters.append(f"crop={crop_w}:{crop_h}:{x}:{y}")

    if settings.enable_color:
        if settings.randomize_color:
            bright = rng.uniform(-0.02, 0.02)
            contrast = rng.uniform(0.99, 1.02)
            saturation = rng.uniform(0.99, 1.02)
            hue = rng.uniform(-2.0, 2.0)
        else:
            bright = settings.brightness
            contrast = settings.contrast
            saturation = settings.saturation
            hue = settings.hue_degrees
        filters.append(
            f"eq=brightness={bright:.4f}:contrast={contrast:.4f}"
            f":saturation={saturation:.4f}"
        )
        if abs(hue) >= 0.1:
            filters.append(f"hue=h={hue:.2f}")

    filters.append("format=yuv420p")
    return ",".join(filters)


def build_audio_filter(settings: Settings) -> str:
    parts: list[str] = []
    if settings.enable_audio:
        parts.append(f"atempo={settings.audio_shift:.4f}")
    if settings.strip_high_freq:
        parts.append(f"lowpass=f={int(settings.high_freq_cutoff)}")
    return ",".join(parts)


def unique_output_path(output_dir: Path, stem: str, suffix: str,
                       ext: str, overwrite: bool) -> Path:
    candidate = output_dir / f"{stem}{suffix}.{ext}"
    if overwrite or not candidate.exists():
        return candidate
    i = 1
    while True:
        candidate = output_dir / f"{stem}{suffix}_{i}.{ext}"
        if not candidate.exists():
            return candidate
        i += 1


def build_command(ffmpeg: str, src: Path, dst: Path, settings: Settings,
                  info: dict, rng: random.Random) -> list[str]:
    """Build an ffmpeg argv list. No shell=True anywhere, so spaces and
    Chinese / non-ASCII characters in paths are passed safely."""
    vf = build_video_filter(info.get("width"), info.get("height"),
                            settings, rng)
    af = build_audio_filter(settings)

    cmd: list[str] = [ffmpeg, "-hide_banner", "-y", "-i", str(src)]
    if vf:
        cmd += ["-vf", vf]
    if info.get("has_audio") and af:
        cmd += ["-af", af]
    elif not info.get("has_audio"):
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-crf", str(int(settings.crf)),
            "-preset", settings.preset, "-movflags", "+faststart"]
    if info.get("has_audio"):
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    if settings.wipe_metadata:
        cmd += ["-map_metadata", "-1", "-map_chapters", "-1"]
    cmd += [str(dst)]
    return cmd


def scan_inputs(input_dir: Path, recursive: bool) -> list[Path]:
    if not input_dir.is_dir():
        return []
    if recursive:
        files = [p for p in input_dir.rglob("*") if p.is_file()]
    else:
        files = [p for p in input_dir.iterdir() if p.is_file()]
    return sorted(
        (p for p in files if p.suffix.lower() in SUPPORTED_EXTS),
        key=lambda p: p.name.lower(),
    )


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class Worker(threading.Thread):
    def __init__(self, ffmpeg: str, ffprobe: str, files: list[Path],
                 settings: Settings, msg_queue: queue.Queue,
                 stop_event: threading.Event):
        super().__init__(daemon=True)
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.files = files
        self.settings = settings
        self.q = msg_queue
        self.stop_event = stop_event
        self.current_proc: subprocess.Popen | None = None

    def log(self, text: str) -> None:
        self.q.put(("log", text))

    def run(self) -> None:
        rng = random.Random()
        total = len(self.files)
        ok = failed = skipped = 0
        try:
            self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.q.put(("error", f"Cannot create output folder: {exc}"))
            self.q.put(("done", (ok, failed, skipped)))
            return

        for idx, src in enumerate(self.files, start=1):
            if self.stop_event.is_set():
                self.log("Stopped by user.")
                break
            self.q.put(("file", (idx, total, src.name)))
            dst = unique_output_path(
                self.settings.output_dir, src.stem,
                self.settings.output_suffix, self.settings.output_ext,
                self.settings.overwrite,
            )
            if dst.exists() and self.settings.overwrite is False and dst != src:
                # unique_output_path already avoids collisions; this is a
                # defensive guard for a same-folder, same-name edge case.
                pass
            if dst.resolve() == src.resolve():
                self.log(f"SKIP {src.name}: output would overwrite the source.")
                skipped += 1
                continue
            info = probe_media(self.ffprobe, src)
            cmd = build_command(self.ffmpeg, src, dst, self.settings, info, rng)
            self.log(f"[{idx}/{total}] {src.name} -> {dst.name}")
            duration = info.get("duration") or 0.0
            try:
                self.current_proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE, text=True,
                    encoding="utf-8", errors="replace",
                )
                assert self.current_proc.stderr is not None
                for line in self.current_proc.stderr:
                    if self.stop_event.is_set():
                        try:
                            self.current_proc.terminate()
                        except Exception:
                            pass
                        break
                    m = TIME_RE.search(line)
                    if m and duration > 0:
                        secs = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                                + float(m.group(3)))
                        pct = max(0, min(100, int(secs / duration * 100)))
                        self.q.put(("progress", pct))
                rc = self.current_proc.wait()
            except Exception as exc:
                self.log(f"ERROR {src.name}: {exc}")
                failed += 1
                continue
            finally:
                self.current_proc = None
            self.q.put(("progress", 100))
            if rc == 0 and dst.exists() and dst.stat().st_size > 0:
                ok += 1
                self.log(f"OK {dst.name}")
            else:
                failed += 1
                self.log(
                    f"FAILED {src.name} (ffmpeg exit code {rc}). "
                    "Check the file, codecs, and disk space, then retry."
                )
            self.q.put(("overall", int(idx * 100 / max(total, 1))))
        self.q.put(("done", (ok, failed, skipped)))


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME}  v{APP_VERSION}")
        self.geometry("1020x880")
        self.minsize(900, 760)

        self.settings = Settings()
        self.msg_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: Worker | None = None
        self.ffmpeg, self.ffprobe = find_ffmpeg()

        self._build_style()
        self._build_widgets()
        self._refresh_ffmpeg_status()
        self.after(120, self._pump_queue)

    # -- styling -----------------------------------------------------------
    def _build_style(self) -> None:
        style = ttk.Style(self)
        for theme in ("clam", "vista", "xpnative", "default"):
            try:
                style.theme_use(theme)
                break
            except tk.TclError:
                continue
        style.configure("TButton", padding=6)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    # -- widgets -----------------------------------------------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        header = ttk.Label(
            self, text=APP_NAME, font=("Segoe UI", 14, "bold"))
        header.pack(anchor="w", **pad)
        ttk.Label(
            self,
            text="Use only on videos you own or are licensed to re-publish. "
                 "Outputs are visually near-lossless re-encodes (CRF 18 by default).",
            wraplength=840, foreground="#555555",
        ).pack(anchor="w", **pad)

        # Folders
        folders = ttk.LabelFrame(self, text="Folders")
        folders.pack(fill="x", **pad)
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        ttk.Label(folders, text="Input folder:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(folders, textvariable=self.input_var, width=62).grid(row=0, column=1, **pad)
        ttk.Button(folders, text="Browse…", command=self._pick_input).grid(row=0, column=2, **pad)
        ttk.Label(folders, text="Output folder:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(folders, textvariable=self.output_var, width=62).grid(row=1, column=1, **pad)
        ttk.Button(folders, text="Browse…", command=self._pick_output).grid(row=1, column=2, **pad)
        self.recursive_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(folders, text="Include subfolders",
                        variable=self.recursive_var).grid(row=2, column=1, sticky="w", **pad)

        # Options
        opts = ttk.LabelFrame(self, text="Sanitisation options")
        opts.pack(fill="x", **pad)

        self.crop_var = tk.BooleanVar(value=True)
        self.crop_slider = self._slider(opts, "Micro-crop (%)", 0.5, 1.5, 1.0, row=0)
        ttk.Checkbutton(opts, text="Enable micro-crop",
                        variable=self.crop_var).grid(row=0, column=3, sticky="w", **pad)
        self.rand_crop_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Randomise per file",
                        variable=self.rand_crop_var).grid(row=0, column=4, sticky="w", **pad)

        self.color_var = tk.BooleanVar(value=True)
        self.bright_slider = self._slider(opts, "Brightness", -0.05, 0.05, 0.01, row=1)
        self.contrast_slider = self._slider(opts, "Contrast", 0.98, 1.02, 1.01, row=2)
        self.sat_slider = self._slider(opts, "Saturation", 0.98, 1.02, 1.01, row=3)
        self.hue_slider = self._slider(opts, "Hue (deg)", -3.0, 3.0, 1.0, row=4)
        ttk.Checkbutton(opts, text="Enable colour tuning",
                        variable=self.color_var).grid(row=1, column=3, sticky="w", **pad)
        self.rand_color_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Randomise per file",
                        variable=self.rand_color_var).grid(row=2, column=3, sticky="w", **pad)

        self.audio_var = tk.BooleanVar(value=True)
        self.audio_slider = self._slider(opts, "Audio tempo (x)", 1.000, 1.005, 1.002, row=5)
        ttk.Checkbutton(opts, text="Enable audio shift",
                        variable=self.audio_var).grid(row=5, column=3, sticky="w", **pad)
        self.hf_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Strip >17 kHz (low-pass)",
                        variable=self.hf_var).grid(row=6, column=1, sticky="w", **pad)
        self.meta_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Wipe metadata (recommended)",
                        variable=self.meta_var).grid(row=6, column=2, sticky="w", **pad)

        # Output options
        out = ttk.LabelFrame(self, text="Output")
        out.pack(fill="x", **pad)
        ttk.Label(out, text="Suffix:").grid(row=0, column=0, sticky="w", **pad)
        self.suffix_var = tk.StringVar(value="_clean")
        ttk.Entry(out, textvariable=self.suffix_var, width=14).grid(row=0, column=1, **pad)
        ttk.Label(out, text="Format:").grid(row=0, column=2, sticky="w", **pad)
        self.ext_var = tk.StringVar(value="mp4")
        ttk.Combobox(out, textvariable=self.ext_var,
                     values=["mp4", "mkv", "mov"], width=10,
                     state="readonly").grid(row=0, column=3, **pad)
        ttk.Label(out, text="CRF (lower = better):").grid(row=0, column=4, sticky="w", **pad)
        self.crf_var = tk.IntVar(value=18)
        ttk.Spinbox(out, from_=16, to=23, textvariable=self.crf_var, width=6).grid(row=0, column=5, **pad)
        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(out, text="Overwrite existing outputs",
                        variable=self.overwrite_var).grid(row=1, column=1, sticky="w", **pad)

        # Controls
        controls = ttk.Frame(self)
        controls.pack(fill="x", **pad)
        self.ffmpeg_label = ttk.Label(controls, text="Checking ffmpeg…")
        self.ffmpeg_label.pack(side="left", **pad)
        ttk.Button(controls, text="Check FFmpeg",
                   command=self._refresh_ffmpeg_status).pack(side="right", **pad)
        self.start_btn = ttk.Button(controls, text="Start Batch",
                                    command=self._start, style="Accent.TButton")
        self.start_btn.pack(side="right", **pad)
        self.stop_btn = ttk.Button(controls, text="Stop",
                                   command=self._stop, state="disabled")
        self.stop_btn.pack(side="right", **pad)
        ttk.Button(controls, text="Open Output Folder",
                   command=self._open_output).pack(side="right", **pad)

        # Progress
        prog = ttk.Frame(self)
        prog.pack(fill="x", **pad)
        self.file_label = ttk.Label(prog, text="Ready.")
        self.file_label.pack(anchor="w", **pad)
        self.progress = ttk.Progressbar(prog, orient="horizontal",
                                        length=820, mode="determinate")
        self.progress.pack(fill="x", **pad)
        self.overall = ttk.Progressbar(prog, orient="horizontal",
                                       length=820, mode="determinate")
        self.overall.pack(fill="x", **pad)
        ttk.Label(prog, text="Top: current file  •  Bottom: whole batch").pack(anchor="w", **pad)

        # Log
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = ScrolledText(log_frame, height=12, state="disabled",
                                     wrap="word")
        self.log_text.pack(fill="both", expand=True, **pad)

    def _slider(self, parent, label, lo, hi, default, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                           padx=8, pady=4)
        var = tk.DoubleVar(value=default)
        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var,
                          orient="horizontal", length=260)
        scale.grid(row=row, column=1, padx=8, pady=4)
        val = ttk.Label(parent, text=f"{default:g}")
        val.grid(row=row, column=2, sticky="w", padx=4)
        def _update(*_args, v=var, lbl=val):
            lbl.config(text=f"{v.get():.3g}")
        var.trace_add("write", _update)
        return var

    # -- folder helpers ----------------------------------------------------
    def _pick_input(self) -> None:
        d = filedialog.askdirectory(title="Choose input folder")
        if d:
            self.input_var.set(d)

    def _pick_output(self) -> None:
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.output_var.set(d)

    def _open_output(self) -> None:
        out = self.output_var.get().strip()
        if not out:
            messagebox.showinfo(APP_NAME, "Choose an output folder first.")
            return
        path = Path(out)
        if not path.exists():
            messagebox.showinfo(APP_NAME, "Output folder does not exist yet.")
            return
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Cannot open folder: {exc}")

    def _refresh_ffmpeg_status(self) -> None:
        self.ffmpeg, self.ffprobe = find_ffmpeg()
        if self.ffmpeg and self.ffprobe:
            self.ffmpeg_label.config(
                text=f"ffmpeg OK: {self.ffmpeg}  •  ffprobe OK")
            self._log("ffmpeg and ffprobe found.")
        else:
            self.ffmpeg_label.config(text="ffmpeg / ffprobe NOT found — see README.")
            self._log("WARNING: ffmpeg/ffprobe not found on PATH. "
                      "Install FFmpeg and restart, or place the binaries "
                      "next to this app.")

    # -- batch control -----------------------------------------------------
    def _collect_settings(self) -> Settings | None:
        inp = self.input_var.get().strip()
        out = self.output_var.get().strip()
        if not inp or not out:
            messagebox.showwarning(APP_NAME, "Choose both input and output folders.")
            return None
        input_dir, output_dir = Path(inp), Path(out)
        if not input_dir.is_dir():
            messagebox.showwarning(APP_NAME, "Input folder does not exist.")
            return None
        try:
            if input_dir.resolve() == output_dir.resolve():
                # Same-folder is allowed only with a suffix; warn clearly.
                if not self.suffix_var.get().strip():
                    messagebox.showwarning(
                        APP_NAME,
                        "Input and output are the same folder: set a suffix "
                        "so outputs do not overwrite sources.")
                    return None
        except Exception:
            pass
        return Settings(
            input_dir=input_dir, output_dir=output_dir,
            enable_crop=self.crop_var.get(),
            crop_percent=float(self.crop_slider.get()),
            randomize_crop=self.rand_crop_var.get(),
            enable_color=self.color_var.get(),
            brightness=float(self.bright_slider.get()),
            contrast=float(self.contrast_slider.get()),
            saturation=float(self.sat_slider.get()),
            hue_degrees=float(self.hue_slider.get()),
            randomize_color=self.rand_color_var.get(),
            enable_audio=self.audio_var.get(),
            audio_shift=float(self.audio_slider.get()),
            strip_high_freq=self.hf_var.get(),
            wipe_metadata=self.meta_var.get(),
            output_suffix=self.suffix_var.get().strip() or "_clean",
            output_ext=self.ext_var.get().strip() or "mp4",
            crf=int(self.crf_var.get()),
            preset="medium",
            overwrite=self.overwrite_var.get(),
            recursive=self.recursive_var.get(),
        )

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.ffmpeg or not self.ffprobe:
            self._refresh_ffmpeg_status()
            messagebox.showerror(
                APP_NAME, "ffmpeg/ffprobe not found. Install FFmpeg first — "
                          "see README.md, then click Check FFmpeg.")
            return
        settings = self._collect_settings()
        if settings is None:
            return
        files = scan_inputs(settings.input_dir, settings.recursive)
        if not files:
            messagebox.showinfo(APP_NAME, "No supported video files found in the input folder.")
            return
        self._log(f"Found {len(files)} file(s). Starting batch…")
        self.stop_event.clear()
        self.progress["value"] = 0
        self.overall["value"] = 0
        self.worker = Worker(self.ffmpeg, self.ffprobe, files, settings,
                             self.msg_queue, self.stop_event)
        self.worker.start()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

    def _stop(self) -> None:
        self.stop_event.set()
        if self.worker and self.worker.current_proc:
            try:
                self.worker.current_proc.terminate()
            except Exception:
                pass
        self._log("Stop requested — finishing the current file, then stopping.")

    # -- queue pump / logging ----------------------------------------------
    def _log(self, text: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _pump_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "file":
                    idx, total, name = payload
                    self.file_label.config(text=f"[{idx}/{total}] {name}")
                    self.progress["value"] = 0
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "overall":
                    self.overall["value"] = payload
                elif kind == "error":
                    messagebox.showerror(APP_NAME, str(payload))
                elif kind == "done":
                    ok, failed, skipped = payload
                    self.file_label.config(
                        text=f"Done: {ok} succeeded, {failed} failed, {skipped} skipped.")
                    self._log(f"Batch finished: {ok} ok, {failed} failed, {skipped} skipped.")
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    messagebox.showinfo(
                        APP_NAME,
                        f"Batch finished.\n{ok} succeeded\n{failed} failed\n{skipped} skipped")
        except queue.Empty:
            pass
        self.after(120, self._pump_queue)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
