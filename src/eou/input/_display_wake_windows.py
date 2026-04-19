"""Windows display-wake helpers.

Two complementary mechanisms keep the REMOTE display awake while a
session is in progress:

1. ``prevent_display_sleep()`` — calls ``SetThreadExecutionState`` with
   ``ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED`` so the
   OS treats the thread as actively requiring the display, preventing
   the screen from blanking and the system from sleeping. Reset on
   ``allow_display_sleep()``.

2. ``wake_display_now()`` — issues a no-op ``SendInput`` mouse event
   (dx=0, dy=0). Mouse activity wakes a screen that has already
   blanked but is not in deep sleep. Safe to call repeatedly; falls
   back silently on non-Windows or when ctypes does not expose
   ``windll`` (e.g., during static type-checking).

Both functions are no-ops on non-Windows platforms so callers do not
need to platform-gate their use site.

# @MX:NOTE: [AUTO] No-op mouse SendInput (MOUSEEVENTF_MOVE with dx=0,
# dy=0) is the smallest legal wake stimulus that does not perturb the
# cursor position or generate a visible click.
"""
from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

# Windows constants — see WinUser.h.
ES_CONTINUOUS: int = 0x80000000
ES_SYSTEM_REQUIRED: int = 0x00000001
ES_DISPLAY_REQUIRED: int = 0x00000002

INPUT_MOUSE: int = 0
MOUSEEVENTF_MOVE: int = 0x0001


def _is_windows() -> bool:
    return sys.platform == "win32"


def prevent_display_sleep() -> bool:
    """Tell Windows the calling thread requires the display to stay on.

    Returns True on success, False on non-Windows or API failure.
    Idempotent: re-calling extends the request without adverse effect.
    """
    if not _is_windows():
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        flags = ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
        prev = kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
        if prev == 0:
            logger.warning(
                "SetThreadExecutionState returned 0 — request to keep "
                "display awake may not have taken effect"
            )
            return False
        logger.info(
            "Display sleep prevented (ES_CONTINUOUS | ES_DISPLAY_REQUIRED "
            "| ES_SYSTEM_REQUIRED). Previous flags=0x%x", prev,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "Failed to call SetThreadExecutionState: %r", exc,
        )
        return False


def allow_display_sleep() -> bool:
    """Cancel the display-required request issued by prevent_display_sleep().

    Returns True on success, False on non-Windows or API failure.
    """
    if not _is_windows():
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        prev = kernel32.SetThreadExecutionState(ctypes.c_uint(ES_CONTINUOUS))
        logger.info(
            "Display sleep allowed (ES_CONTINUOUS only). Previous flags=0x%x",
            prev,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to clear SetThreadExecutionState: %r", exc,
        )
        return False


# --- SendInput wake ---------------------------------------------------------

# MOUSEINPUT struct fields per WinUser.h.
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_uint),
        ("dwFlags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_uint), ("u", _INPUT_UNION)]


def wake_display_now() -> bool:
    """Send a 0,0 mouse-move via SendInput to wake a blanked display.

    The event is large enough for Windows to register input activity
    (which wakes the monitor from low-power state) but small enough
    that the cursor does not move and no click is generated. Returns
    True if SendInput accepted the event.
    """
    if not _is_windows():
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        inp = _INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = _MOUSEINPUT(
            dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_MOVE,
            time=0, dwExtraInfo=None,
        )
        user32.SendInput.argtypes = [
            ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int,
        ]
        user32.SendInput.restype = ctypes.c_uint
        sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if sent != 1:
            logger.warning(
                "SendInput accepted %d/1 events (GetLastError=%d)",
                sent, ctypes.get_last_error(),
            )
            return False
        logger.info("Display wake stimulus sent (SendInput dx=0 dy=0)")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to call SendInput for display wake: %r", exc)
        return False
