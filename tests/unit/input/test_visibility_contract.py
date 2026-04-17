"""Tests for CursorVisibility Protocol contract.

T-026 RED phase — tests must FAIL before T-027 GREEN.

REQ-MOUSE-VISIBILITY-001: pre_hide_position captured at IDLE→CONTROLLING.
REQ-MOUSE-VISIBILITY-002: hide() parks cursor and installs hook.
REQ-MOUSE-VISIBILITY-003: show() restores cursor and removes hook.
REQ-MOUSE-VISIBILITY-004: no ShowCursor/SetSystemCursor/overlay.
REQ-MOUSE-VISIBILITY-005: HOST CONTROLLED state — no ops applied.
"""
from __future__ import annotations

import sys


class TestCursorVisibilityProtocol:
    """CursorVisibility is a runtime-checkable Protocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """CursorVisibility can be used in isinstance checks."""
        from eou.input.visibility import CursorVisibility

        # runtime_checkable Protocol allows isinstance()
        assert hasattr(CursorVisibility, "__protocol_attrs__") or callable(
            getattr(CursorVisibility, "__instancecheck__", None)
        )

    def test_protocol_has_required_methods(self) -> None:
        """CursorVisibility declares hide, show, is_hidden."""
        from eou.input.visibility import CursorVisibility

        for method in ("hide", "show", "is_hidden"):
            assert hasattr(CursorVisibility, method), (
                f"CursorVisibility missing method: {method}"
            )


class TestNullCursorVisibility:
    """NullCursorVisibility is the default no-op implementation for non-Windows."""

    def test_initial_state_not_hidden(self) -> None:
        from eou.input.visibility import NullCursorVisibility

        nv = NullCursorVisibility()
        assert nv.is_hidden() is False

    def test_hide_sets_hidden(self) -> None:
        from eou.input.visibility import NullCursorVisibility

        nv = NullCursorVisibility()
        nv.hide(pre_hide_position=(100, 200))
        assert nv.is_hidden() is True

    def test_hide_stores_pre_hide_position(self) -> None:
        from eou.input.visibility import NullCursorVisibility

        nv = NullCursorVisibility()
        nv.hide(pre_hide_position=(123, 456))
        assert nv._pre_hide_position == (123, 456)

    def test_show_clears_hidden(self) -> None:
        from eou.input.visibility import NullCursorVisibility

        nv = NullCursorVisibility()
        nv.hide(pre_hide_position=(50, 50))
        nv.show()
        assert nv.is_hidden() is False

    def test_show_before_hide_is_no_op(self) -> None:
        from eou.input.visibility import NullCursorVisibility

        nv = NullCursorVisibility()
        nv.show()  # Must not raise
        assert nv.is_hidden() is False

    def test_null_satisfies_protocol(self) -> None:
        from eou.input.visibility import CursorVisibility, NullCursorVisibility

        nv = NullCursorVisibility()
        assert isinstance(nv, CursorVisibility)

    def test_hide_idempotent_updates_position(self) -> None:
        """Second hide call while already hidden updates pre_hide_position.

        REQ-MOUSE-VISIBILITY-002: new transition preempts in-flight restore.
        """
        from eou.input.visibility import NullCursorVisibility

        nv = NullCursorVisibility()
        nv.hide(pre_hide_position=(10, 20))
        nv.hide(pre_hide_position=(30, 40))  # Second call — update position
        assert nv._pre_hide_position == (30, 40)
        assert nv.is_hidden() is True


class TestFakeCursorVisibility:
    """FakeCursorVisibility tracks calls for test assertions."""

    def test_initial_state(self) -> None:
        from tests.fakes.visibility import FakeCursorVisibility

        fv = FakeCursorVisibility()
        assert fv.hidden is False
        assert fv.pre_hide_position is None
        assert fv.hook_installed is False
        assert fv.show_call_count == 0
        assert fv.hide_call_count == 0

    def test_hide_sets_hidden_and_records_position(self) -> None:
        from tests.fakes.visibility import FakeCursorVisibility

        fv = FakeCursorVisibility()
        fv.hide(pre_hide_position=(100, 200))
        assert fv.hidden is True
        assert fv.pre_hide_position == (100, 200)
        assert fv.hide_call_count == 1

    def test_show_clears_hidden(self) -> None:
        from tests.fakes.visibility import FakeCursorVisibility

        fv = FakeCursorVisibility()
        fv.hide(pre_hide_position=(10, 20))
        fv.show()
        assert fv.hidden is False
        assert fv.show_call_count == 1

    def test_show_while_not_hidden_increments_counter_but_no_op(self) -> None:
        """show() while not hidden is a no-op but still increments counter."""
        from tests.fakes.visibility import FakeCursorVisibility

        fv = FakeCursorVisibility()
        fv.show()
        assert fv.show_call_count == 1
        assert fv.hidden is False

    def test_hide_while_already_hidden_updates_position(self) -> None:
        """Second hide while hidden updates pre_hide_position (re-entry case).

        REQ-MOUSE-VISIBILITY-002: new-transition-preempts-in-flight-restore.
        """
        from tests.fakes.visibility import FakeCursorVisibility

        fv = FakeCursorVisibility()
        fv.hide(pre_hide_position=(10, 20))
        fv.hide(pre_hide_position=(30, 40))
        assert fv.pre_hide_position == (30, 40)
        assert fv.hide_call_count == 2

    def test_is_hidden_delegates_to_hidden_flag(self) -> None:
        from tests.fakes.visibility import FakeCursorVisibility

        fv = FakeCursorVisibility()
        assert fv.is_hidden() is False
        fv.hide(pre_hide_position=(0, 0))
        assert fv.is_hidden() is True

    def test_fake_satisfies_protocol(self) -> None:
        from eou.input.visibility import CursorVisibility
        from tests.fakes.visibility import FakeCursorVisibility

        fv = FakeCursorVisibility()
        assert isinstance(fv, CursorVisibility)


class TestCreateCursorVisibilityFactory:
    """create_cursor_visibility factory returns the right implementation."""

    def test_non_windows_returns_null(self) -> None:
        """On non-win32 platforms, factory returns NullCursorVisibility."""
        from eou.input.visibility import NullCursorVisibility, create_cursor_visibility

        cv = create_cursor_visibility(platform_name="linux")
        assert isinstance(cv, NullCursorVisibility)

    def test_darwin_returns_null(self) -> None:
        from eou.input.visibility import NullCursorVisibility, create_cursor_visibility

        cv = create_cursor_visibility(platform_name="darwin")
        assert isinstance(cv, NullCursorVisibility)

    def test_win32_returns_windows_impl(self) -> None:
        """On win32 platform, factory returns WindowsCursorVisibility."""
        from eou.input.visibility import create_cursor_visibility

        cv = create_cursor_visibility(platform_name="win32")
        # Import here to avoid requiring ctypes on Linux at module level
        from eou.input._visibility_windows import WindowsCursorVisibility

        assert isinstance(cv, WindowsCursorVisibility)

    def test_default_uses_sys_platform(self) -> None:
        """Calling factory with no args uses sys.platform."""
        from eou.input.visibility import (
            NullCursorVisibility,
            create_cursor_visibility,
        )

        cv = create_cursor_visibility()
        # On Linux/macOS CI this should be NullCursorVisibility
        if sys.platform == "win32":
            from eou.input._visibility_windows import WindowsCursorVisibility

            assert isinstance(cv, WindowsCursorVisibility)
        else:
            assert isinstance(cv, NullCursorVisibility)
