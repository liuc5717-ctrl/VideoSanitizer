# VideoSanitizer: Batch Video Sanitization & Anti-Duplication Toolchain

[![Platform](https://img.shields.io/badge/Platform-Windows%20x64-blue.svg)](https://github.com/liuc5717-ctrl/VideoSanitizer)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://python.org)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-5.0%2B-orange.svg)](https://ffmpeg.org)
[![Gumroad Full Bundle](https://img.shields.io/badge/Gumroad-Download%20Full%20Bundle-ff385c.svg?style=for-the-badge&logo=gumroad)](https://gumroad.com)

A high-performance, deterministic media engineering pipeline designed for cross-platform video syndication, container sanitization, and cryptographic/perceptual deduplication. Powered by native Python and FFmpeg filtergraphs.

---

## What It Does

`VideoSanitizer` automates the operational friction of distributing short-form and long-form video across modern syndication destinations (TikTok, YouTube Shorts, Instagram Reels, Facebook).

- **Dynamic Micro-Crop (0.5%-1.5%)**: Breaks exact spatial frame hashes while enforcing strict even-integer chroma boundaries.
- **Affine Color Perturbation**: Sub-perceptual matrix shifts across brightness, contrast, saturation, and hue to eliminate deterministic ordinal signatures.
- **Acoustic Drift Mitigation**: Applies precise WSOLA time-scaling and ultrasonic low-pass filtration (>17 kHz) against exact acoustic matching.
- **Zero-Metadata Scrubbing**: Complete container-level atom cleansing preventing client, workstation, and device metadata leakage.

---

## Free Source vs Commercial Distribution Bundle

| Feature | Open-Source CLI (`main.py`) | Commercial Bundle (Gumroad / KDP) |
| :--- | :---: | :---: |
| **Python Source Engine** | Yes | Yes |
| **Zero-Install GUI (`.exe`)** | Manual Build Required | **Pre-compiled Single Binary** |
| **Sibling FFmpeg Toolchain** | Manual Download Required | **Bundled & Verified** |
| **Complete 40+ Page Engineering Handbook** | Table of Contents Only | **Full PDF & EPUB Whitepaper** |
| **Mathematical Derivation & Proofs** | Limited | **Full DCT / Affine Proofs** |
| **v1.1 Hardening Patchbook** | Manual Implementation | **Pre-applied Source & Scripts** |
| **Docker / Headless VPS Script** | No | **Included (`Appendix A`)** |

👉 **[Get the Zero-Install Executable, Pre-compiled Binaries & Full Handbook on Gumroad](https://gumroad.com)**

---

## Quickstart (Running from Source)

### Prerequisites
- Python 3.10+
- FFmpeg and FFprobe added to your system PATH (or placed alongside `main.py`).

### Execution
git clone [https://github.com/liuc5717-ctrl/VideoSanitizer.git](https://github.com/liuc5717-ctrl/VideoSanitizer.git)
cd VideoSanitizer
python main.py

---

## The Handbook

The complete technical reference, *The Batch Video Sanitization & Anti-Duplication Handbook*, documents the exact mathematics, filtergraph mechanics, and operational security guidelines for multi-platform media pipelines. Available in official **PDF** and **Kindle EPUB** formats.

---

## Compliance & Legal Notice
This software and accompanying documentation are strictly intended for copyright owners, licensed syndication agencies, and authorized content publishers. The toolchain does not circumvent digital rights management (DRM) systems and is designed for operational privacy, internal asset de-duplication, and technical format hygiene.
