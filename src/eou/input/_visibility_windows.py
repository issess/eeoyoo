"""WindowsCursorVisibility — Windows-specific cursor hide/show via ctypes user32.

Private module (underscore prefix).  Do NOT import this directly from outside
the input package; use create_cursor_visibility() from visibility.py instead.

REQ-MOUSE-VISIBILITY-002: IDLE→CONTROLLING hides cursor and installs WH_MOUSE_LL hook.
REQ-MOUSE-VISIBILITY-003: CONTROLLING→IDLE removes hook and restores pre_hide_position.
REQ-MOUSE-VISIBILITY-004: No ShowCursor/SetSystemCursor/overlay — only SetCursorPos + hook.

# @MX:WARN: [AUTO] WindowsCursorVisibility uses a WH_MOUSE_LL low-level hook.
# @MX:REASON: The hook callback (_hook_proc) is dispatched on a kernel-spawned
#             message-loop thread.  It MUST NOT block, acquire Python locks with
#             contention, or perform any I/O.  A stall in this callback freezes
#             the entire system mouse input (R-06 in plan.md).

# @MX:NOTE: [AUTO] park_offset parameter implements R-07 multi-monitor mitigation.
# The park coordinate is computed as (SM_XVIRTUALSCREEN - park_offset,
# SM_YVIRTUALSCREEN - park_offset) so that on standard single-monitor setups the
# cursor lands well outside the visible area.  The literal (-32000, -32000) is used
# as a fallback only when GetSystemMetrics returns 0 for the virtual screen origin.
"""
from __future__ import annotations

import ctypes
import logging
import warnings
from collections.abc import Callable
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Windows constants
WH_MOUSE_LL: int = 14
SM_XVIRTUALSCREEN: int = 76
SM_YVIRTUALSCREEN: int = 77

# Windows mouse message constants (winuser.h)
WM_MOUSEMOVE: int = 0x0200

# Fallback park coordinate (REQ-MOUSE-VISIBILITY-002 default, R-07 fallback)
_FALLBACK_PARK: tuple[int, int] = (-32000, -32000)


class _POINT(ctypes.Structure):
    """Windows POINT struct (LONG x, LONG y)."""

    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    """Windows MSLLHOOKSTRUCT passed via lParam to WH_MOUSE_LL callbacks."""

    _fields_ = [
        ("pt", _POINT),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


@runtime_checkable
class WindowsAPI(Protocol):
    """Protocol for Windows user32 API calls used by WindowsCursorVisibility.

    Allows test code to inject FakeWindowsAPI without touching ctypes.
    """

    def set_cursor_pos(self, x: int, y: int) -> bool:
        """Call SetCursorPos(x, y). Returns True on success."""
        ...

    def get_system_metrics(self, index: int) -> int:
        """Call GetSystemMetrics(index). Returns the metric value."""
        ...

    def set_windows_hook_ex(self, hook_proc: Callable[..., int]) -> int:
        """Call SetWindowsHookExW(WH_MOUSE_LL, hook_proc, ...).

        Returns a non-zero hook handle on success, 0 on failure.
        """
        ...

    def unhook_windows_hook_ex(self, handle: int) -> bool:
        """Call UnhookWindowsHookEx(handle). Returns True on success."""
        ...


class _CtypesWindowsAPI:
    """Production WindowsAPI implementation backed by a dedicated user32 handle.

    Uses ``ctypes.WinDLL("user32", ...)`` rather than the shared
    ``ctypes.windll.user32`` cache. pynput also installs a ``WH_MOUSE_LL``
    hook through ``ctypes.windll.user32`` and, as a side effect, sets its
    own HOOKPROC ``WINFUNCTYPE`` on ``SetWindowsHookExW.argtypes[1]``.
    If we shared that handle, our ``c_hook`` (a different ``WINFUNCTYPE``
    instance) would fail pynput's argtype check with
    ``TypeError: expected WinFunctionType instance instead of
    WinFunctionType``. A private handle keeps our argtypes isolated and
    lets both libraries coexist.
    """

    def __init__(self) -> None:
        # Lazy imports inside __init__ so the module remains importable on
        # non-Windows platforms.
        from ctypes import wintypes  # type: ignore[attr-defined]

        # Private user32 handle — its argtypes do not leak to other ctypes
        # consumers (e.g. pynput).
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]

        # HOOKPROC: LRESULT CALLBACK(int nCode, WPARAM wParam, LPARAM lParam)
        # Using wintypes matches the 64-bit Windows ABI (WPARAM/LPARAM are
        # pointer-sized; LRESULT is pointer-sized).
        self._HOOKPROC = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
            wintypes.LPARAM,   # LRESULT
            ctypes.c_int,      # nCode
            wintypes.WPARAM,   # wParam
            wintypes.LPARAM,   # lParam
        )

        # Pin argtypes/restype explicitly so no foreign module can rewrite
        # them on us mid-run.
        self._user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,         # idHook
            self._HOOKPROC,       # lpfn
            wintypes.HINSTANCE,   # hmod
            wintypes.DWORD,       # dwThreadId
        ]
        self._user32.SetWindowsHookExW.restype = wintypes.HHOOK

        self._user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        self._user32.UnhookWindowsHookEx.restype = wintypes.BOOL

        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL

        self._user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self._user32.GetSystemMetrics.restype = ctypes.c_int

        # The WINFUNCTYPE wrapper around the Python callback must stay
        # alive for as long as Windows may call the hook. Keeping it on
        # self prevents premature garbage collection that would leave a
        # dangling function pointer inside the kernel hook chain.
        self._c_hook: object | None = None

    def set_cursor_pos(self, x: int, y: int) -> bool:
        return bool(self._user32.SetCursorPos(x, y))

    def get_system_metrics(self, index: int) -> int:
        return int(self._user32.GetSystemMetrics(index))

    def set_windows_hook_ex(self, hook_proc: Callable[..., int]) -> int:
        c_hook = self._HOOKPROC(hook_proc)
        self._c_hook = c_hook  # retain to prevent GC of the trampoline
        handle = self._user32.SetWindowsHookExW(WH_MOUSE_LL, c_hook, None, 0)
        return int(handle) if handle else 0

    def unhook_windows_hook_ex(self, handle: int) -> bool:
        ok = bool(self._user32.UnhookWindowsHookEx(handle))
        if ok:
            self._c_hook = None
        return ok


class WindowsCursorVisibility:
    """Hides the HOST cursor by parking it outside the virtual screen.

    Uses SetCursorPos to park the cursor and SetWindowsHookExW(WH_MOUSE_LL)
    to consume all subsequent mouse events so they do not reach the HOST
    desktop (REQ-MOUSE-VISIBILITY-002).

    Args:
        api: WindowsAPI implementation.  Defaults to the real ctypes backend
            when running on Windows; tests inject FakeWindowsAPI.
        park_offset: Pixels to subtract from the virtual screen origin when
            computing the park coordinate.  Default 1000 satisfies R-07.
    """

    def __init__(
        self,
        api: WindowsAPI | None = None,
        park_offset: int = 1000,
    ) -> None:
        # _api is resolved lazily in _get_api() so that the class is
        # instantiable on Linux (where ctypes.windll does not exist) when
        # a non-None api is injected (e.g., FakeWindowsAPI in tests).
        self._api_injected: WindowsAPI | None = api
        self._api_resolved: WindowsAPI | None = None
        self._park_offset = park_offset
        self._hidden: bool = False
        self._pre_hide_position: tuple[int, int] | None = None
        self._hook_handle: int = 0
        self._hook_installed: bool = False
        # Hook-thread callback set by hide(). Receives (dx, dy, abs_x, abs_y)
        # for every WM_MOUSEMOVE while hidden. Runs on the OS hook thread —
        # any downstream processing MUST be thread-safe (HOST routes this
        # through MouseEventBridge.submit which already uses
        # loop.call_soon_threadsafe).
        self._on_mouse_event: Callable[[int, int, int, int], None] | None = None
        self._last_hook_pt: tuple[int, int] | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_api(self) -> WindowsAPI:
        """Return the WindowsAPI, instantiating the ctypes backend lazily."""
        if self._api_injected is not None:
            return self._api_injected
        if self._api_resolved is None:
            self._api_resolved = _CtypesWindowsAPI()
        return self._api_resolved

    # ------------------------------------------------------------------
    # CursorVisibility Protocol implementation
    # ------------------------------------------------------------------

    def hide(
        self,
        pre_hide_position: tuple[int, int],
        on_mouse_event: Callable[[int, int, int, int], None] | None = None,
    ) -> None:
        """Park cursor outside virtual screen and install WH_MOUSE_LL hook.

        Idempotent: if called while already hidden, updates pre_hide_position
        and re-parks the cursor (handles re-entry during 50 ms restore window).

        Args:
            pre_hide_position: Cursor position to restore on show().
            on_mouse_event: Optional callback invoked from the hook thread
                with (dx, dy, abs_x, abs_y) for every WM_MOUSEMOVE while
                hidden. Callers use this to receive mouse deltas while the
                hook consumes events (preventing them from reaching pynput).

        # @MX:WARN: [AUTO] _hook_proc is invoked on the kernel message-loop thread.
        # @MX:REASON: Blocking here freezes system-wide mouse input (R-06).
        """
        self._pre_hide_position = pre_hide_position
        self._on_mouse_event = on_mouse_event
        self._last_hook_pt = None
        self._hidden = True

        # Compute park coordinate (R-07 multi-monitor mitigation)
        api = self._get_api()
        sm_x = api.get_system_metrics(SM_XVIRTUALSCREEN)
        sm_y = api.get_system_metrics(SM_YVIRTUALSCREEN)
        if sm_x == 0 and sm_y == 0:
            park_x, park_y = _FALLBACK_PARK
        else:
            park_x = sm_x - self._park_offset
            park_y = sm_y - self._park_offset

        api.set_cursor_pos(park_x, park_y)

        # Install hook only once (idempotent guard)
        if not self._hook_installed:
            handle = api.set_windows_hook_ex(self._hook_proc)
            if handle == 0:
                # Anti-cheat / secure desktop refused the hook (R-08)
                # @MX:WARN: [AUTO] Hook install failure path — degraded mode.
                # @MX:REASON: Anti-cheat or secure desktop can refuse hook install;
                #             the app continues with cursor parking only, no event
                #             consumption.  Takeback accuracy is reduced (R-08).
                warnings.warn(
                    "WH_MOUSE_LL hook installation failed (handle=0). "
                    "Running in degraded mode: cursor parking only, "
                    "local mouse events will not be consumed. "
                    "Check GetLastError() for details (anti-cheat or secure desktop?).",
                    stacklevel=2,
                )
                logger.warning(
                    "SetWindowsHookExW returned NULL — degraded mode active."
                )
                self._hook_installed = False
            else:
                self._hook_handle = handle
                self._hook_installed = True

    def show(self) -> None:
        """Remove hook and restore cursor to pre_hide_position.

        Idempotent: safe to call when not hidden.
        """
        if not self._hidden:
            return

        api = self._get_api()
        if self._hook_installed and self._hook_handle:
            api.unhook_windows_hook_ex(self._hook_handle)
            self._hook_handle = 0
            self._hook_installed = False

        if self._pre_hide_position is not None:
            api.set_cursor_pos(*self._pre_hide_position)

        self._hidden = False
        self._pre_hide_position = None
        self._on_mouse_event = None
        self._last_hook_pt = None

    def is_hidden(self) -> bool:
        """Return True when the cursor is currently parked."""
        return self._hidden

    # ------------------------------------------------------------------
    # Hook callback
    # ------------------------------------------------------------------

    def _hook_proc(self, nCode: int, wParam: int, lParam: int) -> int:
        """Low-level mouse hook procedure.

        Returns 1 to consume the event (prevent forwarding to next hook / app).
        This callback is invoked on the dedicated hook thread's message loop.

        While a ``on_mouse_event`` callback is registered (set by ``hide()``),
        WM_MOUSEMOVE events are decoded from MSLLHOOKSTRUCT and forwarded as
        (dx, dy, abs_x, abs_y). The callback itself must be non-blocking and
        thread-safe (HOST uses MouseEventBridge.submit, which hops to the
        asyncio loop via call_soon_threadsafe).

        HARD CONSTRAINT: Do not block, acquire Python locks with contention,
        or perform any I/O here.  See @MX:WARN above.
        """
        callback = self._on_mouse_event
        if (
            nCode >= 0
            and wParam == WM_MOUSEMOVE
            and callback is not None
        ):
            try:
                mhs = ctypes.cast(
                    lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)
                ).contents
                x, y = int(mhs.pt.x), int(mhs.pt.y)
                last = self._last_hook_pt
                self._last_hook_pt = (x, y)
                dx = 0 if last is None else x - last[0]
                dy = 0 if last is None else y - last[1]
                callback(dx, dy, x, y)
            except Exception:
                # Never let a downstream error crash the hook thread —
                # a stalled hook freezes system-wide mouse input.
                pass
        # Consume all events while hidden
        return 1
