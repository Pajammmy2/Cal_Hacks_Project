"""Cartesia HTTP client: TTS bytes, voice clone, voice delete. Keys come from CARTESIA_API_KEY only.

Request shape checked against docs.cartesia.ai on 2026-10-23 (Authorization: Bearer, Cartesia-Version header,
voice {"id"}, output_format {container mp3, sample_rate 44100, bit_rate}, generation_config.speed).
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from . import config

API = "https://api.cartesia.ai"
DEFAULT_SPEED = 0.85   # calm, slower default voice (spec)
FALLBACK_MODEL = "sonic-3"


class CartesiaError(Exception):
    pass


def api_key():
    return config.env("CARTESIA_API_KEY")


def version():
    return config.env("CARTESIA_VERSION", "2026-08-14")


def model_id():
    return config.env("EMBER_CARTESIA_MODEL", "sonic-2")


def headers():
    k = api_key()
    if not k:
        raise CartesiaError("CARTESIA_API_KEY not set")
    return {"Authorization": f"Bearer {k}", "X-API-Key": k, "Cartesia-Version": version()}


class TTS:
    """One instance per pre-generation run; remembers if the API forced a model fallback."""

    def __init__(self, voice_id, speed=DEFAULT_SPEED, client=None):
        self.voice_id = voice_id
        self.speed = speed
        self.model = model_id()
        self.client = client or httpx.Client(timeout=30.0)
        self.model_note = None

    def body(self, text, language):
        b = {"model_id": self.model, "transcript": text, "voice": {"id": self.voice_id},
             "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000},
             "language": language or "en"}
        if self.speed is not None:
            b["generation_config"] = {"speed": self.speed}
        return b

    def synth(self, text, language="en"):
        r = self.client.post(f"{API}/tts/bytes", json=self.body(text, language), headers=headers())
        if r.status_code in (400, 404, 422) and self.model == model_id() and self.model != FALLBACK_MODEL \
                and re.search(r"model|generation_config|speed", r.text, re.I):
            self.model_note = f"{self.model} rejected by the API ({r.status_code}); using {FALLBACK_MODEL}"
            self.model = FALLBACK_MODEL
            r = self.client.post(f"{API}/tts/bytes", json=self.body(text, language), headers=headers())
        if r.status_code != 200:
            raise CartesiaError(f"tts/bytes {r.status_code}: {r.text[:200]}")
        return r.content


def clone_voice(clip_bytes, filename, name, language="en", description=None, client=None):
    files = {"clip": (filename, clip_bytes, "audio/webm" if filename.endswith(".webm") else "application/octet-stream")}
    data = {"name": name, "language": language}
    if description:
        data["description"] = description
    c = client or httpx.Client(timeout=120.0)
    r = c.post(f"{API}/voices/clone", files=files, data=data, headers=headers())
    if r.status_code not in (200, 201):
        raise CartesiaError(f"voices/clone {r.status_code}: {r.text[:200]}")
    vid = r.json().get("id")
    if not vid:
        raise CartesiaError("clone response had no id")
    return vid


def delete_voice(voice_id, client=None):
    c = client or httpx.Client(timeout=20.0)
    r = c.delete(f"{API}/voices/{voice_id}", headers=headers())
    if r.status_code not in (200, 202, 204, 404):
        raise CartesiaError(f"delete voice {r.status_code}: {r.text[:200]}")


# ---------------------------------------------------------------- loudness

def ffmpeg():
    return shutil.which("ffmpeg")


def normalize_peak(mp3_bytes, target_dbfs=-1.0):
    """Peak-normalize to -1 dBFS with ffmpeg (volumedetect + volume). Returns input unchanged without ffmpeg."""
    ff = ffmpeg()
    if not ff:
        return mp3_bytes
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.mp3", Path(td) / "out.mp3"
        src.write_bytes(mp3_bytes)
        p = subprocess.run([ff, "-hide_banner", "-nostats", "-i", str(src), "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=60)
        m = re.search(r"max_volume:\s*(-?[\d.]+) dB", p.stderr)
        if not m:
            return mp3_bytes
        gain = target_dbfs - float(m.group(1))
        if abs(gain) < 0.1:
            return mp3_bytes
        q = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-af", f"volume={gain:.2f}dB",
                            "-ar", "44100", "-codec:a", "libmp3lame", "-b:a", "128k", str(dst)],
                           capture_output=True, timeout=60)
        if q.returncode != 0 or not dst.exists():
            return mp3_bytes
        return dst.read_bytes()
