"""Unit tests for cli.py helper functions and error paths — coverage boost.

These tests use typer.testing.CliRunner for CLI commands and directly
exercise factory helpers and edge paths.
"""
from __future__ import annotations

from pathlib import Path


class TestCliVersionFlag:
    """eou --version."""

    def test_version_flag(self) -> None:
        from typer.testing import CliRunner

        from eou import __version__
        from eou.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestCliHostErrors:
    """eou host with bad config."""

    def test_host_config_error_exits_1(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from eou.cli import app

        bad_cfg = tmp_path / "bad.yaml"
        bad_cfg.write_text(
            "role: badval\nendpoint: x\nedge:\n  threshold_px: 2\n  dwell_ticks: 2\n"
            "takeback:\n  pixel_threshold: 5\n  event_count_threshold: 2\n  time_window_ms: 100\n"
        )
        runner = CliRunner()
        result = runner.invoke(app, ["host", str(bad_cfg)])
        assert result.exit_code == 1

    def test_host_file_not_found_exits_1(self) -> None:
        from typer.testing import CliRunner

        from eou.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["host", "/nonexistent/missing.yaml"])
        assert result.exit_code == 1

    def test_remote_config_error_exits_1(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from eou.cli import app

        bad_cfg = tmp_path / "bad.yaml"
        bad_cfg.write_text(
            "role: badval\nendpoint: x\nedge:\n  threshold_px: 2\n  dwell_ticks: 2\n"
            "takeback:\n  pixel_threshold: 5\n  event_count_threshold: 2\n  time_window_ms: 100\n"
        )
        runner = CliRunner()
        result = runner.invoke(app, ["remote", str(bad_cfg)])
        assert result.exit_code == 1

    def test_remote_file_not_found_exits_1(self) -> None:
        from typer.testing import CliRunner

        from eou.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["remote", "/nonexistent/missing.yaml"])
        assert result.exit_code == 1


class TestGetScreenBounds:
    """_get_screen_bounds returns a valid tuple."""

    def test_returns_tuple_of_4(self) -> None:
        from eou.cli import _get_screen_bounds

        bounds = _get_screen_bounds()
        assert len(bounds) == 4
        assert bounds[0] == 0
        assert bounds[1] == 0


class TestMakeBackend:
    """_make_backend returns something with MouseBackend API."""

    def test_returns_backend_with_required_methods(self) -> None:
        from eou.cli import _make_backend

        backend = _make_backend()
        assert hasattr(backend, "start_capture")
        assert hasattr(backend, "stop_capture")
        assert hasattr(backend, "move")
        assert hasattr(backend, "get_position")


class TestMakeTransport:
    """_make_transport returns a Transport-compatible object."""

    def test_make_transport_host_config(self, tmp_path: Path) -> None:
        from eou.cli import _make_transport
        from eou.config import EdgeConfig, EouConfig, TakebackConfig

        cfg = EouConfig(
            role="host",
            endpoint="127.0.0.1:7001",
            edge=EdgeConfig(),
            takeback=TakebackConfig(),
        )
        transport = _make_transport(cfg)
        assert hasattr(transport, "connect")
        assert hasattr(transport, "send")
        assert hasattr(transport, "recv")
        assert hasattr(transport, "close")
