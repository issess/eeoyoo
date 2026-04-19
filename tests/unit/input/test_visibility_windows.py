"""Tests for WindowsCursorVisibility with injected FakeWindowsAPI.

T-028 RED phase — tests must FAIL before T-029 GREEN.

These tests run on ALL platforms (no @pytest.mark.windows) because the Windows
API is mocked via FakeWindowsAPI — no real ctypes.windll needed.

REQ-MOUSE-VISIBILITY-002: hide() parks cursor, installs hook.
REQ-MOUSE-VISIBILITY-003: show() restores cursor, removes hook.
"""
from __future__ import annotations

from collections.abc import Callable


class FakeWindowsAPI:
    """In-memory fake for the WindowsAPI Protocol."""

    def __init__(
        self,
        hook_handle: int = 42,
        hook_fail: bool = False,
        sm_x: int = 0,
        sm_y: int = 0,
    ) -> None:
        self.hook_handle = hook_handle if not hook_fail else 0
        self.sm_x = sm_x
        self.sm_y = sm_y

        self.set_cursor_pos_calls: list[tuple[int, int]] = []
        self.get_system_metrics_calls: list[int] = []
        self.set_hook_calls: list[Callable[..., int]] = []
        self.unhook_calls: list[int] = []

    def set_cursor_pos(self, x: int, y: int) -> bool:
        self.set_cursor_pos_calls.append((x, y))
        return True

    def get_system_metrics(self, index: int) -> int:
        self.get_system_metrics_calls.append(index)
        if index == 76:  # SM_XVIRTUALSCREEN
            return self.sm_x
        if index == 77:  # SM_YVIRTUALSCREEN
            return self.sm_y
        return 0

    def set_windows_hook_ex(self, hook_proc: Callable[..., int]) -> int:
        self.set_hook_calls.append(hook_proc)
        return self.hook_handle  # 0 means failure

    def unhook_windows_hook_ex(self, handle: int) -> bool:
        self.unhook_calls.append(handle)
        return True


class TestWindowsCursorVisibilityHide:
    """hide() behaviour with FakeWindowsAPI."""

    def test_hide_queries_system_metrics(self) -> None:
        """hide() calls GetSystemMetrics for SM_XVIRTUALSCREEN and SM_YVIRTUALSCREEN."""
        from eou.input._visibility_windows import (
            SM_XVIRTUALSCREEN,
            SM_YVIRTUALSCREEN,
            WindowsCursorVisibility,
        )

        api = FakeWindowsAPI(sm_x=0, sm_y=0)
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(100, 200))

        assert SM_XVIRTUALSCREEN in api.get_system_metrics_calls
        assert SM_YVIRTUALSCREEN in api.get_system_metrics_calls

    def test_hide_parks_at_fallback_when_sm_zero(self) -> None:
        """When SM_XVIRTUALSCREEN=SM_YVIRTUALSCREEN=0, park at (-32000, -32000)."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI(sm_x=0, sm_y=0)
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(100, 200))

        assert (-32000, -32000) in api.set_cursor_pos_calls

    def test_hide_parks_using_virtual_screen_offset(self) -> None:
        """When SM_XVIRTUALSCREEN=-2560, park at (-2560-1000, -1000) = (-3560, -1000)."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI(sm_x=-2560, sm_y=0)
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(100, 200))

        # park_x = sm_x(-2560) - 1000 = -3560, park_y = sm_y(0) - 1000 = -1000
        assert (-3560, -1000) in api.set_cursor_pos_calls

    def test_hide_installs_hook(self) -> None:
        """hide() calls set_windows_hook_ex once."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI(hook_handle=42)
        wv = WindowsCursorVisibility(api=api, install_hook=True)
        wv.hide(pre_hide_position=(50, 60))

        assert len(api.set_hook_calls) == 1

    def test_hide_sets_is_hidden(self) -> None:
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI()
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(0, 0))
        assert wv.is_hidden() is True

    def test_hide_records_pre_hide_position(self) -> None:
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI()
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(123, 456))
        assert wv._pre_hide_position == (123, 456)


class TestWindowsCursorVisibilityHookFailure:
    """R-08: degraded mode when hook install fails."""

    def test_hook_failure_continues_without_raising(self) -> None:
        """When hook install returns 0, no exception is raised."""
        import warnings

        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI(hook_fail=True)
        wv = WindowsCursorVisibility(api=api, install_hook=True)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            wv.hide(pre_hide_position=(10, 20))

        assert wv.is_hidden() is True  # Still parks
        assert len(w) >= 1  # Warning emitted

    def test_hook_failure_show_still_works(self) -> None:
        """show() works even when hook was never installed (degraded mode)."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI(hook_fail=True)
        wv = WindowsCursorVisibility(api=api, install_hook=True)
        import warnings
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            wv.hide(pre_hide_position=(10, 20))
        wv.show()

        assert wv.is_hidden() is False
        # SetCursorPos called for restore
        assert (10, 20) in api.set_cursor_pos_calls


class TestWindowsCursorVisibilityShow:
    """show() behaviour."""

    def test_show_calls_unhook(self) -> None:
        """show() calls unhook_windows_hook_ex with the hook handle."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI(hook_handle=99)
        wv = WindowsCursorVisibility(api=api, install_hook=True)
        wv.hide(pre_hide_position=(10, 20))
        wv.show()

        assert 99 in api.unhook_calls

    def test_show_restores_pre_hide_position(self) -> None:
        """show() calls SetCursorPos with the stored pre_hide_position."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI()
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(777, 888))
        wv.show()

        assert (777, 888) in api.set_cursor_pos_calls

    def test_show_clears_is_hidden(self) -> None:
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI()
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(0, 0))
        wv.show()
        assert wv.is_hidden() is False

    def test_show_idempotent_when_not_hidden(self) -> None:
        """show() called when not hidden does not call unhook or SetCursorPos."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI()
        wv = WindowsCursorVisibility(api=api)
        wv.show()  # Never hidden — should not raise

        assert len(api.unhook_calls) == 0


class TestWindowsCursorVisibilityIdempotency:
    """hide() called twice updates position and re-parks but installs hook once."""

    def test_double_hide_updates_position(self) -> None:
        """Second hide() updates pre_hide_position."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI()
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(10, 20))
        wv.hide(pre_hide_position=(30, 40))

        assert wv._pre_hide_position == (30, 40)

    def test_double_hide_installs_hook_only_once(self) -> None:
        """Hook is installed on the first hide() only."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI(hook_handle=55)
        wv = WindowsCursorVisibility(api=api, install_hook=True)
        wv.hide(pre_hide_position=(10, 20))
        wv.hide(pre_hide_position=(30, 40))

        assert len(api.set_hook_calls) == 1

    def test_double_hide_re_parks_cursor_both_times(self) -> None:
        """SetCursorPos is called on each hide() to re-park the cursor."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI(sm_x=0, sm_y=0)
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(10, 20))
        wv.hide(pre_hide_position=(30, 40))

        park_calls = [c for c in api.set_cursor_pos_calls if c == (-32000, -32000)]
        assert len(park_calls) == 2

    def test_multi_monitor_negative_virtual_screen(self) -> None:
        """SM_XVIRTUALSCREEN=-2560, SM_YVIRTUALSCREEN=0 → park at (-3560, -1000)."""
        from eou.input._visibility_windows import WindowsCursorVisibility

        api = FakeWindowsAPI(sm_x=-2560, sm_y=0)
        wv = WindowsCursorVisibility(api=api)
        wv.hide(pre_hide_position=(800, 600))

        assert (-3560, -1000) in api.set_cursor_pos_calls
