"""
Client module to interact with the official Suno API hosted at
`https://api.sunoapi.org`.

This client replaces the previous stub/wrapper used in the original
project.  It exposes two async functions—``custom_generate`` and
``extend_audio``—that mirror the behaviour of the prior API but are
implemented against the endpoints documented at
`https://api.sunoapi.org/api/v1`.  Both functions perform all network
communication using ``aiohttp`` and handle polling and downloading of
results internally.

Configuration is driven via environment variables:

* ``SUNO_API_URL`` – optional override of the base URL (defaults to
  ``https://api.sunoapi.org/api/v1``).  You should not include a
  trailing slash.
* ``SUNO_API_KEY`` – the API key used for Bearer authentication.
* ``OUTPUT_DIR`` – directory where downloaded audio files are saved
  (defaults to ``./generated_audio``).  This path is created if it
  does not exist.

The functions return a tuple of ``(audio_id, urls, is_wav)`` where
``audio_id`` is the identifier returned by the API, ``urls`` is a
dictionary containing the local path to the saved audio file and the
original URL reported by the API, and ``is_wav`` is a boolean flag
indicating whether the downloaded file has a WAV extension.

Raising exceptions on non‑successful responses is preferred so that
callers can handle errors uniformly.
"""

import asyncio
import os
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional, List, Any

import aiohttp

logger = logging.getLogger(__name__)

# Determine API base and authentication.  The default points at the
# official Suno API.  You can override this for testing or staging by
# providing ``SUNO_API_URL`` in the environment.
API_BASE = os.environ.get("SUNO_API_URL", "https://api.sunoapi.org/api/v1").rstrip("/")
API_KEY = os.environ.get("SUNO_API_KEY")

# Destination directory for downloaded audio.  The caller should
# configure this in the environment when running inside Docker.
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./generated_audio"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Polling parameters for status checks.  Increase ``MAX_WAIT`` if you
# expect very long generation times.
POLL_INTERVAL = float(os.environ.get("SUNO_POLL_INTERVAL", 5.0))
MAX_WAIT = float(os.environ.get("SUNO_MAX_WAIT", 600.0))


def _get_auth_headers() -> Dict[str, str]:
    """Return common headers including Authorization if an API key is set."""
    headers: Dict[str, str] = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return headers


async def _wait_for_completion(session: aiohttp.ClientSession, task_id: str) -> List[Dict[str, Any]]:
    """Poll the ``/generate/record-info`` endpoint until the task completes.

    The Suno API returns a task identifier when you start a generation or
    extension.  Completion is indicated when the ``status`` field in the
    response equals ``SUCCESS``.  If the status indicates failure an
    exception will be raised.  On success this helper returns the list
    of track dictionaries contained in the response.
    """
    elapsed = 0.0
    params = {"taskId": task_id}
    headers = _get_auth_headers()
    while elapsed < MAX_WAIT:
        try:
            async with session.get(f"{API_BASE}/generate/record-info", params=params, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(f"Status check returned HTTP {resp.status}: {text}")
                    await asyncio.sleep(POLL_INTERVAL)
                    elapsed += POLL_INTERVAL
                    continue
                data: Dict[str, Any] = await resp.json()
                info = data.get("data", {})
                status = info.get("status")
                if status == "SUCCESS":
                    # The API nests track data under data.response.data
                    response = info.get("response", {}) or {}
                    # The API nests track data under response.data; however some
                    # versions use ``tracks`` or ``sunoData``.  Normalise to a list.
                    tracks: Any = (
                        response.get("data")
                        or response.get("tracks")
                        or response.get("sunoData")
                        or []
                    )
                    if not isinstance(tracks, list):
                        # If the response contains a single track dict, wrap it
                        if isinstance(tracks, dict):
                            tracks = [tracks]
                        else:
                            raise Exception(f"Unexpected track list type: {type(tracks)} in {response}")
                    return tracks
                elif status in {"FAILURE", "FAILED", "ERROR"}:
                    message = info.get("msg") or data.get("msg") or "unknown error"
                    raise Exception(f"Suno API reported failure: {status} - {message}")
        except Exception as exc:
            logger.warning(f"Error while polling status: {exc}")
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    raise TimeoutError(f"Timed out after {MAX_WAIT} seconds waiting for task {task_id}")


async def _download_audio(session: aiohttp.ClientSession, url: str, output_path: str) -> None:
    """Download a remote audio file to a local path.

    Uses a fairly large timeout since some audio files can be large.  If the
    download fails due to HTTP errors a corresponding exception is raised.
    """
    timeout = aiohttp.ClientTimeout(total=MAX_WAIT)
    async with session.get(url, timeout=timeout) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"Failed to download audio: HTTP {resp.status} - {text}")
        with open(output_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(8192):
                f.write(chunk)
    logger.info(f"Downloaded audio to {output_path}")


def _map_model(model: str) -> str:
    """Map the project's model identifiers to the values expected by Suno API.

    The Suno API defines models ``V3_5``, ``V4``, ``V4_5``, ``V4_5PLUS`` and
    ``V5``.  The incoming values used by the batch processor are
    historically ``v5`` and ``v4.5``; this helper converts those to the
    appropriate Suno names.  Unknown models are upper‑cased with dots
    replaced by underscores.
    """
    m = model.lower().strip()
    if m in {"v5", "v5.0", "v5_0"}:
        return "V5"
    if m in {"v4.5", "v4_5", "v4.5plus", "v4_5plus", "v4.5plus"}:
        return "V4_5"
    if m in {"v4", "v4.0", "v4_0"}:
        return "V4"
    if m in {"v3.5", "v3_5", "chirp-v3-5"}:
        return "V3_5"
    # Default mapping
    return model.upper().replace(".", "_")


async def custom_generate(
    title: str,
    style: str,
    prompt: str,
    model: str = "V3_5",
    duration_target: float = 240.0,
    prefer_wav: bool = True,
    allow_mp3_to_wav: bool = True,
    make_instrumental: bool = False,
    call_back_url: Optional[str] = None,
    wait_audio: bool = True,
) -> Tuple[str, Dict[str, str], bool]:
    """Generate a new piece of music using the Suno API.

    Parameters mirror those of the legacy client but are translated into
    Suno API fields.  ``duration_target`` is currently unused because
    Suno's API does not allow arbitrary durations; it always returns
    full‑length tracks.  ``make_instrumental`` maps to the API's
    ``instrumental`` field.
    """
    headers = _get_auth_headers()
    headers["Content-Type"] = "application/json"
    async with aiohttp.ClientSession() as session:
        # Always include a callback URL.  Some versions of the Suno API
        # require this field even if polling is used.  The caller may
        # provide one explicitly; otherwise an environment variable or
        # a sensible local default is used.
        cb_url = (
            call_back_url
            or os.environ.get("SUNO_CALLBACK_URL")
            or "http://localhost:8000/suno-callback"
        )
        mapped_model = _map_model(model)
        # Build payload according to Suno API specification.  We include
        # negativeTags as an empty string to satisfy the required field and
        # supply default weights for style/weirdness/audio.  These values can
        # be adjusted as desired via environment variables.
        payload = {
            "prompt": prompt,
            "customMode": True,
            "style": style,
            "title": title,
            "instrumental": bool(make_instrumental),
            "model": mapped_model,
            "negativeTags": "",
            # Default weighting parameters (optional in API).  See docs for
            # details: styleWeight controls adherence to style, weirdnessConstraint
            # controls creative variation, audioWeight biases audio quality.
            "styleWeight": float(os.environ.get("SUNO_STYLE_WEIGHT", 0.65)),
            "weirdnessConstraint": float(os.environ.get("SUNO_WEIRDNESS_CONSTRAINT", 0.65)),
            "audioWeight": float(os.environ.get("SUNO_AUDIO_WEIGHT", 0.65)),
            "callBackUrl": cb_url,
        }
        logger.info(f"Sending generation request for '{title}' (model={model})")
        async with session.post(f"{API_BASE}/generate", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Suno API generation error: HTTP {resp.status} - {text}")
            result: Dict[str, Any] = await resp.json()
            # Expecting { code, msg, data: { taskId: ... } }
            data = result.get("data") or {}
            task_id: Optional[str] = data.get("taskId") or data.get("task_id") or None
            if not task_id:
                raise Exception(f"Task ID not found in response: {result}")
        # Poll for completion
        tracks = await _wait_for_completion(session, task_id)
        if not tracks:
            raise Exception("No tracks returned from API on completion")
        track = tracks[0]
        # Extract identifiers.  Suno's response uses ``id`` and ``audioUrl``.
        audio_id: str = track.get("id") or track.get("audioId") or track.get("audio_id")
        # Accept both camelCase and snake_case keys for the audio URL
        audio_url: Optional[str] = (
            track.get("audioUrl")
            or track.get("audio_url")
            or track.get("url")
            or track.get("streamAudioUrl")
        )
        if not audio_id or not audio_url:
            raise Exception(f"Incomplete track information: {track}")
        # Determine extension and download.  If the URL ends with .wav then it's WAV,
        # otherwise default to MP3.
        ext = "wav" if audio_url.lower().endswith(".wav") else "mp3"
        output_path = OUTPUT_DIR / f"{audio_id}.{ext}"
        await _download_audio(session, audio_url, str(output_path))
        urls = {
            "audio_url": str(output_path),
            "original_audio_url": audio_url,
        }
        return audio_id, urls, ext == "wav"


async def extend_audio(
    original_id: str,
    extend_seconds: float = 60.0,
    prefer_wav: bool = True,
    continue_at: Optional[float] = None,
    model: str = "V3_5",
    call_back_url: Optional[str] = None,
) -> Tuple[str, Dict[str, str], bool]:
    """Extend an existing audio clip via the Suno API.

    ``extend_seconds`` and ``continue_at`` are used together: if
    ``continue_at`` is provided it specifies the point in seconds from
    which the extension should begin.  Otherwise this function will
    assume the extension should start at the end of the clip minus the
    requested extension length.  The Suno API does not support
    arbitrary durations directly; it simply appends additional music
    using the provided prompt.  The ``prompt`` is optional and left
    blank here.  ``model`` is mapped using the same helper as
    ``custom_generate``.
    """
    headers = _get_auth_headers()
    headers["Content-Type"] = "application/json"
    async with aiohttp.ClientSession() as session:
        payload: Dict[str, Any] = {
            "audioId": original_id,
            # Use Suno's default parameter flag to reuse prior settings
            "defaultParamFlag": True,
            "prompt": "",
            "model": _map_model(model),
        }
        if continue_at is not None:
            # Suno expects an integer for continueAt
            payload["continueAt"] = int(continue_at)
        if call_back_url:
            payload["callBackUrl"] = call_back_url
        logger.info(f"Requesting extension for '{original_id}'")
        async with session.post(f"{API_BASE}/generate/extend", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Suno API extend error: HTTP {resp.status} - {text}")
            result: Dict[str, Any] = await resp.json()
            data = result.get("data") or {}
            task_id: Optional[str] = data.get("taskId") or data.get("task_id")
            if not task_id:
                raise Exception(f"Task ID not returned from extend call: {result}")
        # Poll for completion
        tracks = await _wait_for_completion(session, task_id)
        if not tracks:
            raise Exception("No tracks returned for extension task")
        track = tracks[0]
        audio_id: str = track.get("id") or track.get("audioId") or track.get("audio_id")
        audio_url: Optional[str] = (
            track.get("audioUrl")
            or track.get("audio_url")
            or track.get("url")
            or track.get("streamAudioUrl")
        )
        if not audio_id or not audio_url:
            raise Exception(f"Incomplete track info in extension result: {track}")
        ext = "wav" if audio_url.lower().endswith(".wav") else "mp3"
        output_path = OUTPUT_DIR / f"{audio_id}_ext.{ext}"
        await _download_audio(session, audio_url, str(output_path))
        urls = {
            "audio_url": str(output_path),
            "original_audio_url": audio_url,
        }
        return audio_id, urls, ext == "wav"