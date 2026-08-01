"""
Voice Assistant routes — all /voice/* HTTP endpoints.

Endpoints
---------
GET  /voice/           Renders the browser control panel (voice/index.html).
POST /voice/listen     Runs the full speech-to-action pipeline and returns JSON.

Pipeline flow for POST /voice/listen
--------------------------------------

    Browser (WAV blob)
          |
          v  multipart/form-data, field name = "audio"
    [1] listen_from_bytes(audio_bytes)  --> transcript: str
          |
          v
    [2] route_intent(transcript)        --> {"intent": "...", "payload": "..."}
          |
          v
    [3] execute(intent_result)          --> {"success": bool, "message": "..."}
          |
          v
    jsonify({
        "transcript": transcript,
        "intent":     intent_result["intent"],
        "success":    result["success"],
        "message":    result["message"],
    })

Error handling strategy
-----------------------
Each stage is wrapped independently so a failure in one stage returns a
meaningful JSON error response rather than an HTML 500 page.

  • Missing / empty audio field → 400 Bad Request
  • Listener returns empty string  → 200, transcript = "", intent = UNKNOWN,
      message = "I didn't catch that — please try again."
  • Any unexpected exception in the pipeline → 500 with JSON body
    (never an HTML traceback visible to the client)

All error responses follow the same JSON shape as success responses so the
browser JavaScript can always handle them uniformly.
"""

from __future__ import annotations

import logging

from flask import jsonify, render_template, request

from voice_assistant import voice_bp
from voice_assistant.executor      import execute
from voice_assistant.intent_router import UNKNOWN, route_intent
from voice_assistant.listener      import listen_from_bytes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GET /voice/  — control panel UI
# ---------------------------------------------------------------------------

@voice_bp.route("/")
def index():
    """Render the Voice Assistant browser control panel."""
    return render_template("voice/index.html")


# ---------------------------------------------------------------------------
# POST /voice/listen  — full speech-to-action pipeline
# ---------------------------------------------------------------------------

@voice_bp.route("/listen", methods=["POST"])
def listen():
    """
    Accept a WAV audio upload, run the full pipeline, and return JSON.

    Request
    -------
    Content-Type : multipart/form-data
    Field name   : "audio"
    Field value  : WAV audio blob (produced by the browser's encodeWAV()
                   function in index.html)

    Response (HTTP 200 on success, 400/500 on error)
    --------
    {
        "transcript" : "open chrome",   // what the user said
        "intent"     : "OPEN_CHROME",   // matched intent constant
        "success"    : true,            // whether the action succeeded
        "message"    : "Opening Google Chrome for you!"  // TTS reply text
    }

    On pipeline error the same shape is returned with success=false and
    a human-readable message field so the browser always has something
    to display.
    """

    # ------------------------------------------------------------------
    # Stage 0 — validate the upload
    # ------------------------------------------------------------------
    audio_file = request.files.get("audio")

    if audio_file is None:
        logger.warning("/listen called with no 'audio' field in form data")
        return _error_response(
            "No audio file received. "
            "Make sure the request includes a field named 'audio'.",
            status=400,
        )

    try:
        audio_bytes = audio_file.read()
    except Exception as exc:
        logger.exception("Failed to read uploaded audio file: %s", exc)
        return _error_response(f"Could not read the uploaded audio: {exc}", status=400)

    if not audio_bytes:
        logger.warning("/listen received an empty audio file")
        return _error_response("The uploaded audio file is empty.", status=400)

    # ------------------------------------------------------------------
    # Stage 1 — speech-to-text
    # ------------------------------------------------------------------
    try:
        transcript = listen_from_bytes(audio_bytes)
    except Exception as exc:
        # listen_from_bytes() is documented never to raise, but be defensive.
        logger.exception("Unexpected exception in listen_from_bytes: %s", exc)
        transcript = ""

    logger.info("/listen  transcript=%r", transcript)

    # If the recogniser returned one of its error strings or an empty
    # string, there is nothing useful to route — reply immediately.
    _RECOGNITION_FAILURES = {
        "",
        "could not understand audio",
        "speech recognition service unavailable",
        "microphone not available",
    }
    if transcript.lower().strip() in _RECOGNITION_FAILURES:
        reply = (
            "I didn't catch that — please speak clearly and try again."
            if transcript.lower().strip() in ("", "could not understand audio")
            else transcript   # pass "Speech recognition service unavailable" through
        )
        return jsonify({
            "transcript": transcript,
            "intent":     UNKNOWN,
            "success":    False,
            "message":    reply,
        })

    # ------------------------------------------------------------------
    # Stage 2 — intent classification
    # ------------------------------------------------------------------
    try:
        intent_result = route_intent(transcript)
    except Exception as exc:
        logger.exception("Unexpected exception in route_intent: %s", exc)
        intent_result = {"intent": UNKNOWN, "payload": ""}

    logger.info(
        "/listen  intent=%r  payload=%r",
        intent_result.get("intent"),
        intent_result.get("payload"),
    )

    # ------------------------------------------------------------------
    # Stage 3 — execution
    # ------------------------------------------------------------------
    try:
        result = execute(intent_result)
    except Exception as exc:
        logger.exception("Unexpected exception in execute: %s", exc)
        result = {"success": False, "message": f"Execution error: {exc}"}

    logger.info(
        "/listen  success=%s  message=%r",
        result.get("success"),
        result.get("message"),
    )

    # ------------------------------------------------------------------
    # Stage 4 — build and return the JSON response
    # ------------------------------------------------------------------
    return jsonify({
        "transcript": transcript,
        "intent":     intent_result.get("intent", UNKNOWN),
        "success":    result.get("success", False),
        "message":    result.get("message", ""),
    })


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

def _error_response(message: str, status: int = 500):
    """
    Return a JSON error response that has the same shape as a normal
    pipeline response so the browser JavaScript can handle it uniformly.

    Parameters
    ----------
    message : str   Human-readable description of the error.
    status  : int   HTTP status code (400 for client errors, 500 for server).
    """
    return jsonify({
        "transcript": "",
        "intent":     UNKNOWN,
        "success":    False,
        "message":    message,
    }), status
