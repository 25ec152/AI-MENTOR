"""
executor.py - Command dispatcher for the Voice Assistant.

Public API
----------
execute(intent_result: dict) -> dict

    Accepts the dictionary returned by route_intent() and executes the
    corresponding Windows action.  Always returns a JSON-friendly dict:

        {"success": True,  "message": "Opened Chrome"}
        {"success": False, "message": "Could not open Chrome: <reason>"}

    The caller (the Flask route) passes this dict straight to jsonify().

Supported intents
-----------------
    OPEN_CHROME        -- launches Google Chrome
    OPEN_NOTEPAD       -- launches Notepad
    OPEN_CALCULATOR    -- launches Calculator
    OPEN_VSCODE        -- launches Visual Studio Code
    OPEN_PAINT         -- launches Microsoft Paint
    OPEN_YOUTUBE       -- opens youtube.com in the default browser
    SEARCH_GOOGLE      -- opens a Google search in the default browser
    GET_TIME           -- returns the current system time as a string
    GET_DATE           -- returns today's date as a string
    BATTERY_STATUS     -- returns current battery % and plug status

Safety-disabled intents (not executed, returns an info message)
-----------------
    SHUTDOWN           -- system shutdown
    RESTART            -- system restart
    LOCK_PC            -- lock workstation

UNKNOWN and any unrecognised intent returns a polite "not understood" reply.

Implementation notes
--------------------
* Apps are launched with subprocess.Popen() using a STARTUPINFO object that
  hides the console window — the app opens silently in the background.
* Executable paths are resolved in priority order:
    1. A known absolute path (hardcoded from common install locations).
    2. The Windows 'start' shell command as a final fallback, which asks the
       OS to find the app by its registered name.
* Websites and searches use webbrowser.open() — stdlib, no install needed.
* Battery info comes from psutil (already in requirements.txt).
* All exceptions are caught; failures return {"success": False, "message": ...}
  so the Flask route never gets an unhandled 500.
"""

from __future__ import annotations

import datetime
import logging
import os
import subprocess
import urllib.parse
import webbrowser
from typing import Dict

import psutil

from voice_assistant.intent_router import (
    OPEN_CHROME, OPEN_NOTEPAD, OPEN_CALCULATOR, OPEN_VSCODE, OPEN_PAINT,
    OPEN_YOUTUBE, SEARCH_GOOGLE, GET_TIME, GET_DATE, BATTERY_STATUS,
    SHUTDOWN, RESTART, LOCK_PC, UNKNOWN,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias for the result dict
# ---------------------------------------------------------------------------
Result = Dict[str, object]   # {"success": bool, "message": str}

# ---------------------------------------------------------------------------
# Executable path registry
# ---------------------------------------------------------------------------
# Each entry is a list of candidate absolute paths, tried left-to-right.
# The first path that exists on disk is used.  If none exist, the launcher
# falls back to the Windows 'start' shell command.
#
# Paths use os.path.expandvars() at resolution time so %LOCALAPPDATA%,
# %PROGRAMFILES%, etc. are expanded on the actual machine.

_APP_PATHS: Dict[str, list] = {
    "chrome": [
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
    ],
    "notepad": [
        r"%WINDIR%\notepad.exe",
        r"%WINDIR%\System32\notepad.exe",
    ],
    "calc": [
        r"%WINDIR%\System32\calc.exe",
        r"%WINDIR%\SysWOW64\calc.exe",
    ],
    "vscode": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%PROGRAMFILES%\Microsoft VS Code\Code.exe",
    ],
    "mspaint": [
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\mspaint.exe",
        r"%WINDIR%\System32\mspaint.exe",
        r"%WINDIR%\mspaint.exe",
    ],
}

# Human-readable display names used in reply messages.
_APP_DISPLAY: Dict[str, str] = {
    "chrome":  "Google Chrome",
    "notepad": "Notepad",
    "calc":    "Calculator",
    "vscode":  "VS Code",
    "mspaint": "Paint",
}

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _ok(message: str) -> Result:
    """Build a success result dict."""
    return {"success": True, "message": message}


def _err(message: str) -> Result:
    """Build a failure result dict."""
    return {"success": False, "message": message}


def _resolve_exe(app_key: str) -> str | None:
    """
    Return the first existing absolute path for *app_key*, or None if none
    of the candidates exist on disk.

    Each candidate path is passed through os.path.expandvars() so that
    environment variables like %LOCALAPPDATA% are expanded correctly for
    the current user account.
    """
    for template in _APP_PATHS.get(app_key, []):
        expanded = os.path.expandvars(template)
        if os.path.exists(expanded):
            logger.debug("Resolved %s -> %s", app_key, expanded)
            return expanded
    logger.debug("No absolute path found for %s; will use shell fallback", app_key)
    return None


def _launch_app(app_key: str) -> Result:
    """
    Launch a desktop application identified by *app_key* (one of the keys
    in _APP_PATHS).

    Strategy
    --------
    1. Try to find an absolute executable path via _resolve_exe().
       If found, launch it directly with subprocess.Popen() and a hidden
       console window (STARTUPINFO with SW_HIDE).
    2. If no absolute path is found, fall back to the Windows 'start' shell
       command: subprocess.Popen(['cmd', '/c', 'start', app_key], shell=False).
       'start' asks the OS to find the app by its registered association.

    Returns a Result dict.
    """
    display = _APP_DISPLAY.get(app_key, app_key)

    try:
        exe_path = _resolve_exe(app_key)

        # Build a STARTUPINFO to suppress any console window that the child
        # process might otherwise flash up.
        si = subprocess.STARTUPINFO()
        si.dwFlags    |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE

        if exe_path:
            # Primary path: absolute exe known, launch directly.
            subprocess.Popen(
                [exe_path],
                startupinfo=si,
                # Detach from the Flask process so the app keeps running
                # after Flask exits.
                creationflags=subprocess.DETACHED_PROCESS,
            )
        else:
            # Fallback: ask Windows to find the app by name.
            # 'start' is a cmd.exe built-in so we must use shell=True.
            subprocess.Popen(
                f'start "" "{app_key}"',
                shell=True,
                startupinfo=si,
            )

        logger.info("Launched application: %s", display)
        return _ok(f"Opening {display} for you!")

    except FileNotFoundError:
        msg = (
            f"Could not find {display}. "
            f"Please make sure it is installed on your computer."
        )
        logger.error("FileNotFoundError launching %s", display)
        return _err(msg)

    except Exception as exc:
        logger.exception("Unexpected error launching %s: %s", display, exc)
        return _err(f"Could not open {display}: {exc}")


def _open_url(url: str, description: str) -> Result:
    """
    Open *url* in the system default browser using webbrowser.open().

    webbrowser.open() is stdlib and works on Windows, macOS, and Linux
    without any additional packages.  It returns True if a browser was
    found, False otherwise.

    Parameters
    ----------
    url         : the full URL to open (must start with http:// or https://)
    description : human-readable name used in the reply message, e.g. "YouTube"
    """
    try:
        opened = webbrowser.open(url)
        if opened:
            logger.info("Opened URL: %s", url)
            return _ok(f"Opening {description} for you!")
        else:
            logger.warning("webbrowser.open returned False for %s", url)
            return _err(f"Could not open {description}. No default browser found.")
    except Exception as exc:
        logger.exception("Error opening URL %s: %s", url, exc)
        return _err(f"Could not open {description}: {exc}")


# ---------------------------------------------------------------------------
# Individual intent handlers
# ---------------------------------------------------------------------------

def _handle_open_chrome(_payload: str) -> Result:
    return _launch_app("chrome")


def _handle_open_notepad(_payload: str) -> Result:
    return _launch_app("notepad")


def _handle_open_calculator(_payload: str) -> Result:
    return _launch_app("calc")


def _handle_open_vscode(_payload: str) -> Result:
    return _launch_app("vscode")


def _handle_open_paint(_payload: str) -> Result:
    return _launch_app("mspaint")


def _handle_open_youtube(_payload: str) -> Result:
    return _open_url("https://www.youtube.com", "YouTube")


def _handle_search_google(query: str) -> Result:
    """
    Build a Google search URL from *query* and open it in the default browser.

    urllib.parse.urlencode() safely encodes any special characters in the
    query string (spaces become '+', punctuation is percent-encoded).
    """
    if not query or not query.strip():
        return _err("What would you like me to search for?")

    encoded = urllib.parse.urlencode({"q": query.strip()})
    url = f"https://www.google.com/search?{encoded}"
    logger.info("Google search query: %r  url: %s", query, url)
    return _open_url(url, f'Google search for "{query.strip()}"')


def _handle_get_time(_payload: str) -> Result:
    """
    Return the current system time formatted as a spoken-friendly string.
    Example: "The current time is 03:45 PM"
    """
    now  = datetime.datetime.now()
    # %-I on Linux, %#I on Windows strips the leading zero from the hour.
    # Using a manual check is more portable than relying on platform-specific
    # format codes.
    hour   = now.strftime("%I").lstrip("0") or "12"
    minute = now.strftime("%M")
    ampm   = now.strftime("%p")
    msg = f"The current time is {hour}:{minute} {ampm}."
    logger.info("GET_TIME -> %s", msg)
    return _ok(msg)


def _handle_get_date(_payload: str) -> Result:
    """
    Return today's date formatted as a spoken-friendly string.
    Example: "Today is Monday, 14 July 2025"
    """
    today = datetime.date.today()
    # strftime %B = full month name, %A = full weekday name, %d = zero-padded day
    day   = str(today.day)                # no leading zero
    month = today.strftime("%B")          # e.g. "July"
    year  = today.strftime("%Y")          # e.g. "2025"
    weekday = today.strftime("%A")        # e.g. "Monday"
    msg = f"Today is {weekday}, {day} {month} {year}."
    logger.info("GET_DATE -> %s", msg)
    return _ok(msg)


def _handle_battery_status(_payload: str) -> Result:
    """
    Query psutil for the battery state and return a spoken-friendly string.

    psutil.sensors_battery() returns a named tuple with fields:
        percent      -- integer 0-100
        secsleft     -- seconds remaining (or psutil.POWER_TIME_UNLIMITED /
                        psutil.POWER_TIME_UNKNOWN)
        power_plugged -- bool

    Returns a graceful message if no battery is detected (desktop PC).
    """
    battery = psutil.sensors_battery()

    if battery is None:
        msg = "No battery detected. This device may be a desktop computer."
        logger.info("BATTERY_STATUS -> no battery")
        return _ok(msg)

    pct     = int(battery.percent)
    plugged = battery.power_plugged

    if plugged:
        status = "charging" if pct < 100 else "fully charged"
    else:
        status = "on battery"

    # Describe remaining time only if the OS can estimate it.
    secs_left = battery.secsleft
    if (
        not plugged
        and secs_left > 0
        and secs_left not in (
            psutil.POWER_TIME_UNLIMITED,
            psutil.POWER_TIME_UNKNOWN,
        )
    ):
        hours, rem  = divmod(int(secs_left), 3600)
        minutes, _  = divmod(rem, 60)
        if hours:
            time_str = f"{hours} hour{'s' if hours != 1 else ''} and {minutes} minute{'s' if minutes != 1 else ''} remaining"
        else:
            time_str = f"{minutes} minute{'s' if minutes != 1 else ''} remaining"
        msg = f"Battery is at {pct}%, {status} — {time_str}."
    else:
        msg = f"Battery is at {pct}%, {status}."

    logger.info("BATTERY_STATUS -> %s", msg)
    return _ok(msg)


def _handle_safety_disabled(intent: str) -> Result:
    """
    Return a safety notice for power-control intents that are intentionally
    disabled.  The intent name is included so the UI can display which
    command was blocked.
    """
    names = {SHUTDOWN: "Shutdown", RESTART: "Restart", LOCK_PC: "Lock PC"}
    display = names.get(intent, intent)
    msg = (
        f"{display} is currently disabled for safety. "
        f"Please use the Windows Start menu or power button instead."
    )
    logger.info("Safety-disabled intent: %s", intent)
    return _ok(msg)   # success=True: the system behaved correctly


def _handle_unknown(_payload: str) -> Result:
    return _ok(
        "Sorry, I didn't understand that command. "
        "Try saying something like 'Open Chrome', 'What time is it', "
        "or 'Search for Python tutorials'."
    )


# ---------------------------------------------------------------------------
# Dispatcher table  (intent constant -> handler function)
# ---------------------------------------------------------------------------
# Using a dict instead of if/elif makes it trivial to add new intents later
# — just add one line to this table and write the handler function.

_DISPATCH: Dict[str, object] = {
    OPEN_CHROME:     _handle_open_chrome,
    OPEN_NOTEPAD:    _handle_open_notepad,
    OPEN_CALCULATOR: _handle_open_calculator,
    OPEN_VSCODE:     _handle_open_vscode,
    OPEN_PAINT:      _handle_open_paint,
    OPEN_YOUTUBE:    _handle_open_youtube,
    SEARCH_GOOGLE:   _handle_search_google,
    GET_TIME:        _handle_get_time,
    GET_DATE:        _handle_get_date,
    BATTERY_STATUS:  _handle_battery_status,
    # Safety-disabled power commands
    SHUTDOWN:        lambda p: _handle_safety_disabled(SHUTDOWN),
    RESTART:         lambda p: _handle_safety_disabled(RESTART),
    LOCK_PC:         lambda p: _handle_safety_disabled(LOCK_PC),
    UNKNOWN:         _handle_unknown,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute(intent_result: Dict[str, str]) -> Result:
    """
    Execute the action described by *intent_result* and return a result dict.

    Parameters
    ----------
    intent_result : dict
        The dictionary returned by route_intent(), e.g.:
            {"intent": "OPEN_CHROME",  "payload": ""}
            {"intent": "SEARCH_GOOGLE","payload": "python tutorials"}

    Returns
    -------
    dict
        Always a JSON-friendly dict with keys:
            "success" : bool   -- True if the action completed without error
            "message" : str    -- Human-readable reply for the TTS engine /
                                  browser UI

    Examples
    --------
    >>> execute({"intent": "OPEN_CHROME", "payload": ""})
    {'success': True, 'message': 'Opening Google Chrome for you!'}

    >>> execute({"intent": "SEARCH_GOOGLE", "payload": "flask tutorial"})
    {'success': True, 'message': 'Google search for "flask tutorial"'}

    >>> execute({"intent": "SHUTDOWN", "payload": ""})
    {'success': True, 'message': 'Shutdown is currently disabled for safety...'}

    >>> execute({"intent": "UNKNOWN", "payload": ""})
    {'success': True, 'message': "Sorry, I didn't understand that command..."}
    """
    # Defensive: handle completely missing or malformed input gracefully.
    if not isinstance(intent_result, dict):
        logger.error("execute() received non-dict argument: %r", intent_result)
        return _err("Internal error: invalid intent result passed to executor.")

    intent  = intent_result.get("intent",  UNKNOWN)
    payload = intent_result.get("payload", "")

    logger.info("execute: intent=%r  payload=%r", intent, payload)

    handler = _DISPATCH.get(intent)

    if handler is None:
        # intent string is not in the dispatch table at all
        logger.warning("No handler for intent %r; treating as UNKNOWN", intent)
        return _handle_unknown(payload)

    return handler(payload)
