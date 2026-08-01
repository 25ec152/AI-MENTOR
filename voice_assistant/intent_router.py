"""
intent_router.py - Keyword-based intent classifier for the Voice Assistant.

Public API
----------
route_intent(text: str) -> dict
    Accepts a raw transcript string (any case) and returns:

        {
            "intent":  "OPEN_CHROME",        # one of the INTENT_* constants below
            "payload": "python tutorials"     # extra argument, or "" when unused
        }

How matching works
------------------
Each intent has an ordered list of trigger phrases.  The text is normalised
to lowercase, then each phrase is tested with a whole-string token check
(the phrase must be a contiguous sub-sequence of whitespace-separated tokens,
not just a substring — this prevents "calculator" from matching "open
calculates something").

Intents are tested in PRIORITY ORDER (most-specific first).  Multi-word app
names like "visual studio code" are listed before single-word names like
"code" so the longest match always wins.

Search intent is special: the matched trigger phrase is stripped from the
left of the transcript and the remainder becomes the payload (the search query).

Supported intents
-----------------
OPEN_CHROME      OPEN_NOTEPAD     OPEN_CALCULATOR
OPEN_VSCODE      OPEN_PAINT       OPEN_YOUTUBE
SEARCH_GOOGLE    GET_TIME         GET_DATE
BATTERY_STATUS   SHUTDOWN         RESTART
LOCK_PC          UNKNOWN
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent name constants
# ---------------------------------------------------------------------------
OPEN_CHROME      = "OPEN_CHROME"
OPEN_NOTEPAD     = "OPEN_NOTEPAD"
OPEN_CALCULATOR  = "OPEN_CALCULATOR"
OPEN_VSCODE      = "OPEN_VSCODE"
OPEN_PAINT       = "OPEN_PAINT"
OPEN_YOUTUBE     = "OPEN_YOUTUBE"
SEARCH_GOOGLE    = "SEARCH_GOOGLE"
GET_TIME         = "GET_TIME"
GET_DATE         = "GET_DATE"
BATTERY_STATUS   = "BATTERY_STATUS"
SHUTDOWN         = "SHUTDOWN"
RESTART          = "RESTART"
LOCK_PC          = "LOCK_PC"
UNKNOWN          = "UNKNOWN"

# ---------------------------------------------------------------------------
# Intent trigger-phrase table
# ---------------------------------------------------------------------------
# Each entry is  (INTENT_CONSTANT, [trigger_phrase, ...])
# Rules:
#   - All phrases must be lowercase.
#   - Phrases are matched as token sub-sequences, so word boundaries are
#     respected automatically.
#   - List the most-specific (longest) phrases FIRST within each intent.
#   - The whole table is evaluated top-to-bottom; first match wins.
#   - Intents with overlapping vocabulary (vscode / code) must be ordered
#     so the more-specific intent appears earlier in the list.
# ---------------------------------------------------------------------------

_INTENT_TABLE: List[Tuple[str, List[str]]] = [

    # ── Applications ────────────────────────────────────────────────────────
    # VS Code must be above any generic "code" entry.
    (OPEN_VSCODE, [
        "open visual studio code",
        "launch visual studio code",
        "start visual studio code",
        "open vs code",
        "launch vs code",
        "start vs code",
        "open vscode",
        "launch vscode",
        "start vscode",
        "open code editor",
        "launch code editor",
    ]),

    (OPEN_CHROME, [
        "open google chrome",
        "launch google chrome",
        "start google chrome",
        "open chrome",
        "launch chrome",
        "start chrome",
        "open browser",
        "launch browser",
        "start browser",
        "open google",           # common casual phrasing
        "launch google",
    ]),

    (OPEN_NOTEPAD, [
        "open notepad",
        "launch notepad",
        "start notepad",
        "open text editor",
        "launch text editor",
        "open notes",
        "launch notes",
    ]),

    (OPEN_CALCULATOR, [
        "open calculator",
        "launch calculator",
        "start calculator",
        "open calc",
        "launch calc",
        "start calc",
    ]),

    (OPEN_PAINT, [
        "open microsoft paint",
        "launch microsoft paint",
        "start microsoft paint",
        "open mspaint",
        "open paint",
        "launch paint",
        "start paint",
        "open drawing",
        "launch drawing",
    ]),

    # ── Websites ─────────────────────────────────────────────────────────────
    (OPEN_YOUTUBE, [
        "open youtube",
        "launch youtube",
        "go to youtube",
        "play youtube",
        "watch youtube",
        "start youtube",
    ]),

    # ── Web search ───────────────────────────────────────────────────────────
    # These phrases are stripped as prefixes; everything after them becomes
    # the search query payload.
    (SEARCH_GOOGLE, [
        "search google for",
        "google search for",
        "search for",
        "search google",
        "google for",
        "google",
        "search",
        "look up",
        "find",
    ]),

    # ── Time & date ──────────────────────────────────────────────────────────
    (GET_TIME, [
        "what is the current time",
        "what's the current time",
        "what is the time",
        "what's the time",
        "current time",
        "tell me the time",
        "what time is it",
        "time please",
        "the time",
        "time",
    ]),

    (GET_DATE, [
        "what is today's date",
        "what's today's date",
        "what is the date today",
        "what's the date today",
        "what is today",
        "today's date",
        "current date",
        "tell me the date",
        "what date is it",
        "date today",
        "the date",
        "date",
    ]),

    # ── System information ───────────────────────────────────────────────────
    (BATTERY_STATUS, [
        "battery percentage",
        "how much battery do i have",
        "how much battery",
        "check battery",
        "battery level",
        "battery status",
        "battery life",
        "battery",
    ]),

    # ── Power controls ───────────────────────────────────────────────────────
    # Shutdown must be above restart/lock so "shut down and restart" still
    # maps to SHUTDOWN (first match wins).
    (SHUTDOWN, [
        "shut down the laptop",
        "shut down the computer",
        "shut down laptop",
        "shut down computer",
        "shutdown the laptop",
        "shutdown laptop",
        "shutdown computer",
        "turn off the laptop",
        "turn off laptop",
        "turn off the computer",
        "turn off computer",
        "switch off the laptop",
        "switch off laptop",
        "switch off computer",
        "power off",
        "shut down",
        "shutdown",
        "turn off",
        "switch off",
    ]),

    (RESTART, [
        "restart the laptop",
        "restart the computer",
        "restart laptop",
        "restart computer",
        "reboot the laptop",
        "reboot laptop",
        "reboot computer",
        "restart",
        "reboot",
    ]),

    (LOCK_PC, [
        "lock the screen",
        "lock the laptop",
        "lock the computer",
        "lock screen",
        "lock laptop",
        "lock computer",
        "lock my laptop",
        "lock my computer",
        "lock pc",
        "lock",
    ]),
]


# ---------------------------------------------------------------------------
# Pre-compile trigger phrases into token lists for fast matching
# ---------------------------------------------------------------------------
# A "token sequence" is the phrase split on whitespace, e.g.
#   "open google chrome" -> ["open", "google", "chrome"]
# Matching tests whether the transcript's token list contains this
# sub-sequence starting at any position.

_COMPILED: List[Tuple[str, List[List[str]]]] = [
    (intent, [phrase.split() for phrase in phrases])
    for intent, phrases in _INTENT_TABLE
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """
    Lowercase, collapse whitespace, and strip leading/trailing spaces.
    Also removes punctuation characters that speech-to-text sometimes adds
    (commas, question marks, periods) so "What time is it?" still matches.
    """
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)   # strip punctuation
    text = re.sub(r"\s+", " ", text)       # collapse whitespace
    return text.strip()


def _token_subseq_index(tokens: List[str], phrase_tokens: List[str]) -> int:
    """
    Return the START index of *phrase_tokens* inside *tokens* if it exists
    as a contiguous sub-sequence, or -1 if not found.

    Example:
        tokens        = ["open", "google", "chrome", "please"]
        phrase_tokens = ["open", "google", "chrome"]
        -> returns 0

        tokens        = ["please", "open", "chrome"]
        phrase_tokens = ["open", "chrome"]
        -> returns 1
    """
    plen = len(phrase_tokens)
    tlen = len(tokens)
    for i in range(tlen - plen + 1):
        if tokens[i : i + plen] == phrase_tokens:
            return i
    return -1


def _strip_prefix(tokens: List[str], phrase_tokens: List[str]) -> str:
    """
    Remove *phrase_tokens* from the start of *tokens* and return the
    remainder joined as a string.  Used to extract the search query after
    stripping the trigger phrase.

    Example:
        tokens        = ["search", "for", "python", "tutorials"]
        phrase_tokens = ["search", "for"]
        -> returns "python tutorials"
    """
    idx = _token_subseq_index(tokens, phrase_tokens)
    if idx == -1:
        return " ".join(tokens)
    end = idx + len(phrase_tokens)
    return " ".join(tokens[end:]).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_intent(text: str) -> Dict[str, str]:
    """
    Map a raw transcript string to an intent and an optional payload.

    Parameters
    ----------
    text : str
        The transcript produced by the speech recogniser (any case, any
        punctuation).

    Returns
    -------
    dict with keys:
        "intent"  : str  -- one of the INTENT_* constants defined in this module
        "payload" : str  -- extra argument (search query, or "" when unused)

    Examples
    --------
    >>> route_intent("Open Google Chrome please")
    {'intent': 'OPEN_CHROME', 'payload': ''}

    >>> route_intent("Search for the best Python tutorials")
    {'intent': 'SEARCH_GOOGLE', 'payload': 'the best python tutorials'}

    >>> route_intent("What time is it?")
    {'intent': 'GET_TIME', 'payload': ''}

    >>> route_intent("shut down the laptop")
    {'intent': 'SHUTDOWN', 'payload': ''}

    >>> route_intent("play some jazz music")
    {'intent': 'UNKNOWN', 'payload': ''}
    """
    if not text or not text.strip():
        logger.debug("route_intent received empty text -> UNKNOWN")
        return {"intent": UNKNOWN, "payload": ""}

    normalised = _normalise(text)
    tokens     = normalised.split()

    logger.debug("route_intent: normalised=%r  tokens=%s", normalised, tokens)

    for intent, phrase_token_lists in _COMPILED:
        for phrase_tokens in phrase_token_lists:
            idx = _token_subseq_index(tokens, phrase_tokens)
            if idx == -1:
                continue

            # Match found.
            if intent == SEARCH_GOOGLE:
                # For search, the payload is everything AFTER the trigger phrase.
                payload = _strip_prefix(tokens, phrase_tokens)
                # If the user only said "search" with nothing after it, treat
                # the whole utterance as unknown rather than an empty search.
                if not payload:
                    logger.debug(
                        "SEARCH_GOOGLE matched but no query found; "
                        "falling through to UNKNOWN"
                    )
                    break   # break inner loop -> move to next intent in table
            else:
                payload = ""

            logger.info(
                "Intent matched: intent=%r  phrase=%r  payload=%r",
                intent, " ".join(phrase_tokens), payload,
            )
            return {"intent": intent, "payload": payload}

    logger.info("No intent matched for %r -> UNKNOWN", text)
    return {"intent": UNKNOWN, "payload": ""}
