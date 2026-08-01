"""
listener.py - Speech-to-text module for the Voice Assistant.

Responsibilities
----------------
1. Accept raw audio bytes that the browser POSTs to /voice/listen.
2. Guarantee the bytes are in WAV (PCM RIFF) format before handing them
   to SpeechRecognition, which only supports WAV, AIFF, and FLAC.
3. Send the validated WAV to Google's free Web Speech API and return the
   recognised text as a plain Python string.
4. Return a human-readable error string (never raise) so the Flask route
   can always hand something back to the browser.

Two public functions are exported
----------------------------------
listen_from_bytes(audio_bytes)  -- primary path: used by the Flask route
listen_from_microphone()        -- secondary path: server-side mic capture
                                   (requires PyAudio to be installed)

WAV conversion strategy
------------------------
SpeechRecognition.AudioFile only understands PCM WAV, AIFF, and FLAC.
Chrome / Edge MediaRecorder produces WebM/Opus by default; Firefox produces
OGG/Opus.  Neither format is natively understood.

The reliable zero-external-dependency solution is to move the conversion
to the BROWSER using the Web Audio API (see index.html):
  - The browser decodes its own MediaRecorder blob via AudioContext.decodeAudioData()
  - It re-encodes the raw PCM samples into a proper RIFF/WAV blob
  - It POSTs that WAV blob to /voice/listen

The server-side _to_wav_bytes() helper then:
  1. Accepts the bytes and checks for a RIFF header - if present, passes
     straight through (browser already sent WAV).
  2. If no RIFF header is found (edge-case fallback or non-Chrome browser),
     it wraps the raw bytes as 16-bit 16 kHz mono PCM WAV using stdlib wave.
  3. Returns the guaranteed-WAV bytes ready for sr.AudioFile.

No external packages (pydub, ffmpeg, soundfile) are required.
"""

import io
import logging
import os
import struct
import tempfile
import wave

import speech_recognition as sr

# Module-level logger - messages appear in Flask's console output.
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Recognizer instance is created once at module load time and reused across
# all requests.  Creating it inside every call would add unnecessary overhead.
# ---------------------------------------------------------------------------
_recognizer = sr.Recognizer()

# ---------------------------------------------------------------------------
# Tuning parameters
# ---------------------------------------------------------------------------

# How long (seconds) listen_from_microphone() waits for speech to begin
# before giving up.
_MIC_LISTEN_TIMEOUT_SECONDS = 5

# Maximum duration (seconds) of a single microphone utterance.
_MIC_PHRASE_LIMIT_SECONDS = 10

# WAV parameters used when wrapping raw PCM bytes that arrive without a
# RIFF header (emergency fallback path only).
_WAV_SAMPLE_RATE = 16000   # 16 kHz - matches Google Speech best-practice
_WAV_CHANNELS    = 1       # mono
_WAV_SAMPLE_WIDTH = 2      # 16-bit PCM (2 bytes per sample)

# First 4 bytes of any RIFF/WAV file
_RIFF_MAGIC = b"RIFF"


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

def _to_wav_bytes(audio_bytes: bytes) -> bytes:
    """
    Ensure *audio_bytes* is a valid PCM WAV file and return the (possibly
    unchanged) bytes.

    Decision tree
    -------------
    1. If the bytes start with b"RIFF" they are already a WAV file.
       Return them unchanged - no allocation, no conversion.

    2. Otherwise treat the bytes as raw 16-bit little-endian PCM samples
       (the fallback format the browser sends when WAV encoding is not
       supported) and wrap them in a proper RIFF/WAV container using the
       stdlib `wave` module.  The parameters (_WAV_SAMPLE_RATE etc.) at
       the top of this file control the assumed format.

    Parameters
    ----------
    audio_bytes : bytes
        Raw bytes received from the browser POST body.

    Returns
    -------
    bytes
        Valid PCM WAV bytes ready for sr.AudioFile.
    """
    # Fast path: already a WAV file (browser sent encoded WAV via Web Audio API)
    if audio_bytes[:4] == _RIFF_MAGIC:
        logger.debug("_to_wav_bytes: RIFF header detected, passing through unchanged.")
        return audio_bytes

    # Fallback path: wrap raw PCM samples in a RIFF/WAV container.
    # This covers browsers that cannot encode WAV and send raw PCM instead,
    # or any other unrecognised container that slipped through.
    logger.warning(
        "_to_wav_bytes: No RIFF header found in %d bytes. "
        "Wrapping as raw PCM WAV (%d Hz, %d ch, %d-bit).",
        len(audio_bytes),
        _WAV_SAMPLE_RATE,
        _WAV_CHANNELS,
        _WAV_SAMPLE_WIDTH * 8,
    )

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_writer:
        wav_writer.setnchannels(_WAV_CHANNELS)
        wav_writer.setsampwidth(_WAV_SAMPLE_WIDTH)
        wav_writer.setframerate(_WAV_SAMPLE_RATE)
        wav_writer.writeframes(audio_bytes)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def listen_from_bytes(audio_bytes: bytes) -> str:
    """
    Convert a raw audio byte-string into a recognised text transcript.

    The browser records audio with MediaRecorder, then re-encodes it to
    WAV via the Web Audio API before POSTing to /voice/listen (see the
    index.html script block for the client-side encoding).  This function:

      1. Guards against an empty upload.
      2. Calls _to_wav_bytes() to guarantee a RIFF/WAV container.
      3. Writes the WAV bytes to a named temp file (delete=False because
         Windows locks files that are still open).
      4. Opens the file with sr.AudioFile, records it into AudioData.
      5. Sends the AudioData to Google's Web Speech API.
      6. Returns the transcript string, or a descriptive error string.

    Parameters
    ----------
    audio_bytes : bytes
        Raw audio data exactly as received from request.files['audio'].read().

    Returns
    -------
    str
        Recognised transcript, or one of:
        - "Could not understand audio"             -- speech was unclear/silent
        - "Speech recognition service unavailable" -- network / API error
    """
    # Guard: empty upload - fail fast before touching the filesystem.
    if not audio_bytes:
        logger.warning("listen_from_bytes received empty audio_bytes.")
        return "Could not understand audio"

    tmp_path = None
    try:
        # Step 1: guarantee WAV format before SpeechRecognition sees the bytes.
        wav_bytes = _to_wav_bytes(audio_bytes)

        # Step 2: write to a named temporary file.
        # delete=False is required on Windows: with delete=True the OS holds
        # a file lock on the first open() call and sr.AudioFile cannot open
        # the same path again until the first handle is closed.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_file.write(wav_bytes)
            tmp_path = tmp_file.name   # remember for cleanup in finally

        # Step 3: open as an AudioFile source and read into memory as AudioData.
        # sr.AudioFile natively supports PCM WAV - no external codec needed.
        with sr.AudioFile(tmp_path) as source:
            audio_data = _recognizer.record(source)

        # Step 4: send to Google's free Web Speech API.
        # language="en-IN" targets Indian English accents.
        # Change to "en-US" for American English, or remove the kwarg for
        # the API default.
        transcript = _recognizer.recognize_google(audio_data, language="en-IN")
        logger.info("Recognised transcript: %r", transcript)
        return transcript

    except sr.UnknownValueError:
        # Google received the audio but could not find recognisable speech
        # (silence, background noise, mumbling, too-short utterance).
        logger.warning("Google Speech Recognition could not understand the audio.")
        return "Could not understand audio"

    except sr.RequestError as exc:
        # Network failure, bad API response, quota exceeded, or DNS error.
        logger.error("Google Speech Recognition request failed: %s", exc)
        return "Speech recognition service unavailable"

    except Exception as exc:
        # Catch-all: corrupted WAV header, unexpected wave module error, etc.
        logger.exception("Unexpected error in listen_from_bytes: %s", exc)
        return "Could not understand audio"

    finally:
        # Always delete the temporary file - even if an exception occurred.
        # Skipping this would fill up disk space on a long-running server.
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as cleanup_err:
                logger.warning(
                    "Could not delete temp file %s: %s", tmp_path, cleanup_err
                )


def listen_from_microphone() -> str:
    """
    Capture speech directly from the laptop's default microphone and
    return it as a text transcript.

    This function is an alternative input path for cases where the server
    itself needs to listen (e.g. a standalone desktop mode or testing
    without a browser).  For the normal web flow, listen_from_bytes() is
    used instead.

    Requires PyAudio to be installed:
        pip install PyAudio
    On Python 3.12+ / 3.13+ a pre-built wheel may be needed:
        pip install pipwin && pipwin install pyaudio

    Parameters
    ----------
    None

    Returns
    -------
    str
        Recognised transcript, or one of:
        - "Could not understand audio"             -- speech was unclear
        - "Speech recognition service unavailable" -- network / API error
        - "Microphone not available"               -- PyAudio not installed
    """
    try:
        with sr.Microphone() as mic_source:
            # Spend up to 1 second calibrating for ambient noise so that
            # quiet environments don't trigger false positives.
            _recognizer.adjust_for_ambient_noise(mic_source, duration=1)

            logger.info("Microphone open - listening for speech ...")

            # listen() blocks until it detects a phrase or the timeout elapses.
            # phrase_time_limit caps the length of a single voice command.
            audio_data = _recognizer.listen(
                mic_source,
                timeout=_MIC_LISTEN_TIMEOUT_SECONDS,
                phrase_time_limit=_MIC_PHRASE_LIMIT_SECONDS,
            )

        transcript = _recognizer.recognize_google(audio_data, language="en-IN")
        logger.info("Microphone transcript: %r", transcript)
        return transcript

    except sr.WaitTimeoutError:
        # No speech was detected within the timeout window.
        logger.warning("Microphone listen timed out - no speech detected.")
        return "Could not understand audio"

    except sr.UnknownValueError:
        logger.warning("Microphone audio could not be understood.")
        return "Could not understand audio"

    except sr.RequestError as exc:
        logger.error("Speech Recognition API error (microphone): %s", exc)
        return "Speech recognition service unavailable"

    except (OSError, AttributeError):
        # OSError        -- no microphone hardware connected.
        # AttributeError -- PyAudio is not installed (SpeechRecognition raises
        #                   AttributeError("Could not find PyAudio") when the
        #                   package is missing).
        logger.error(
            "Microphone not available. Install PyAudio: pip install PyAudio"
        )
        return "Microphone not available"

    except Exception as exc:
        logger.exception("Unexpected error in listen_from_microphone: %s", exc)
        return "Could not understand audio"
