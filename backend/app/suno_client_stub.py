"""
Suno API client stub.

This module provides stub functions that mimic the behaviour of the
unofficial Suno API. It does not contact the real service; instead it
generates dummy audio files on the fly and returns predictable
structures. This allows the rest of the application to be developed
and tested without hitting external dependencies.

When integrating with the actual ``suno-api`` service, replace the
functions here with HTTP requests to the endpoints provided by the
wrapper. See the README of the upstream project for details.
"""

import asyncio
import os
import wave
import random
import struct
from pathlib import Path
from typing import Dict, List, Tuple

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./generated_audio"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def generate_sine_wave(
    filename: str, duration: float, sample_rate: int = 44100, freq: float = 440.0
) -> None:
    """Generate a simple sine wave WAV file.

    Args:
        filename: Path where the WAV file will be written.
        duration: Duration of the audio in seconds.
        sample_rate: Sample rate in Hz.
        freq: Frequency of the sine wave in Hz.
    """
    n_samples = int(sample_rate * duration)
    with wave.open(filename, 'w') as wav_file:
        nchannels = 1
        sampwidth = 2  # bytes per sample (16‑bit)
        wav_file.setparams((nchannels, sampwidth, sample_rate, n_samples, 'NONE', 'not compressed'))
        max_amp = 32767
        for i in range(n_samples):
            # Generate a sine wave at the given frequency
            sample = int(max_amp * 0.1 * (random.random() * 2 - 1))  # random noise low amplitude
            wav_file.writeframes(struct.pack('<h', sample))


async def custom_generate(
    title: str,
    style: str,
    prompt: str,
    model: str,
    duration_target: float,
    prefer_wav: bool = True,
    allow_mp3_to_wav: bool = True,
) -> Tuple[str, Dict[str, str], bool]:
    """Simulate a call to /api/custom_generate.

    Returns a tuple containing a generated ID, a dictionary of URLs, and
    a flag indicating whether the returned audio is a native WAV.
    """
    # Simulate network delay and processing time
    await asyncio.sleep(random.uniform(1.0, 3.0))

    # Create a dummy file duration between 60% and 100% of target
    actual_duration = duration_target * random.uniform(0.6, 1.0)
    wav = prefer_wav  # Always produce WAV for simplicity
    file_ext = 'wav' if wav else 'mp3'
    generated_id = f"fake_{random.randint(100000, 999999)}"
    filename = OUTPUT_DIR / f"{generated_id}.{file_ext}"
    await generate_sine_wave(str(filename), actual_duration)

    return generated_id, {"audio_url": str(filename)}, wav


async def extend_audio(
    original_id: str,
    extend_seconds: float,
    prefer_wav: bool = True,
) -> Tuple[str, Dict[str, str], bool]:
    """Simulate extending an existing audio clip.

    Args:
        original_id: ID of the original audio clip.
        extend_seconds: Number of seconds to extend.
        prefer_wav: Whether to return WAV format if possible.

    Returns:
        A tuple like ``custom_generate`` containing a new ID, URLs and
        WAV flag.
    """
    await asyncio.sleep(random.uniform(0.5, 1.5))
    # We'll just create a new file with the extension length
    generated_id = f"{original_id}_ext_{random.randint(100000, 999999)}"
    file_ext = 'wav' if prefer_wav else 'mp3'
    filename = OUTPUT_DIR / f"{generated_id}.{file_ext}"
    await generate_sine_wave(str(filename), extend_seconds)
    return generated_id, {"audio_url": str(filename)}, prefer_wav