"""CLI entry point for SPEC-MOUSE-001.

Thin typer-based CLI.  Only two subcommands: host and remote.
All wiring (Transport, Backend, Visibility) is done here via DI.

This module MUST NOT import transport.tcp directly — it receives Transport
via the factory helpers below (REQ-MOUSE-TRANSPORT-003).

Usage:
    eou host path/to/eou.yaml
    eou remote path/to/eou.yaml
    eou --version
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from eou import __version__
from eou.config import ConfigError, EouConfig, load_config

app = typer.Typer(name="eou", add_completion=False, no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"eou version {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    """EOU — Edge-triggered mouse ownership transfer (SPEC-MOUSE-001)."""


@app.command()
def host(
    config_path: Path = typer.Argument(..., help="Path to eou.yaml config file."),
) -> None:
    """Run as HOST node.

    Loads config, wires Host with TCPTransport + real/Null visibility,
    and runs until Ctrl+C or session end.
    """
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=1)
    except FileNotFoundError:
        typer.echo(f"Config file not found: {config_path}", err=True)
        raise typer.Exit(code=1)

    try:
        asyncio.run(_run_host(cfg))
    except KeyboardInterrupt:
        typer.echo("Host stopped.")


@app.command()
def remote(
    config_path: Path = typer.Argument(..., help="Path to eou.yaml config file."),
) -> None:
    """Run as REMOTE node.

    Loads config, wires Remote with TCPTransport + Null visibility,
    and runs until Ctrl+C or session end.
    """
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=1)
    except FileNotFoundError:
        typer.echo(f"Config file not found: {config_path}", err=True)
        raise typer.Exit(code=1)

    try:
        asyncio.run(_run_remote(cfg))
    except KeyboardInterrupt:
        typer.echo("Remote stopped.")


# ---------------------------------------------------------------------------
# Internal runners
# ---------------------------------------------------------------------------


async def _run_host(cfg: EouConfig) -> None:
    """Wire and run the Host orchestrator."""
    # Lazy imports to keep cli.py decoupled from concrete implementations.
    # cli.py uses Host/Remote constructors — it does NOT import transport.tcp directly.
    from eou.host import Host
    from eou.input.visibility import create_cursor_visibility
    from eou.ownership.edge_detector import EdgeConfig
    from eou.ownership.takeback_detector import TakebackConfig

    transport = _make_transport(cfg)
    await transport.connect(cfg.endpoint)

    backend = _make_backend()
    visibility = (
        create_cursor_visibility() if cfg.hide_cursor else create_cursor_visibility("linux")
    )

    edge_cfg = EdgeConfig(
        edge="right",  # Default; full per-edge config is post-MVP
        screen_bounds=_get_screen_bounds(),
        threshold_px=cfg.edge.threshold_px,
        dwell_ticks=cfg.edge.dwell_ticks,
    )
    takeback_cfg = TakebackConfig(
        pixel_threshold=cfg.takeback.pixel_threshold,
        event_count_threshold=cfg.takeback.event_count_threshold,
        time_window_ms=cfg.takeback.time_window_ms,
    )

    h = Host(
        transport=transport,
        backend=backend,
        visibility=visibility,
        edge_config=edge_cfg,
        takeback_config=takeback_cfg,
    )
    await h.run()


async def _run_remote(cfg: EouConfig) -> None:
    """Wire and run the Remote orchestrator."""
    from eou.input.visibility import NullCursorVisibility
    from eou.ownership.edge_detector import EdgeConfig
    from eou.ownership.takeback_detector import TakebackConfig
    from eou.remote import Remote

    transport = _make_transport(cfg)
    await transport.connect(cfg.endpoint)

    backend = _make_backend()
    visibility = NullCursorVisibility()  # Remote never manipulates cursor

    edge_cfg = EdgeConfig(
        edge="left",
        screen_bounds=_get_screen_bounds(),
        threshold_px=cfg.edge.threshold_px,
        dwell_ticks=cfg.edge.dwell_ticks,
    )
    takeback_cfg = TakebackConfig(
        pixel_threshold=cfg.takeback.pixel_threshold,
        event_count_threshold=cfg.takeback.event_count_threshold,
        time_window_ms=cfg.takeback.time_window_ms,
    )

    r = Remote(
        transport=transport,
        backend=backend,
        visibility=visibility,
        edge_config=edge_cfg,
        takeback_config=takeback_cfg,
    )
    await r.run()


def _make_transport(cfg: EouConfig) -> object:
    """Construct the appropriate Transport (TCPTransport for MVP).

    cli.py does not import transport.tcp directly.  TCPTransport is
    constructed via a factory function that lives inside transport/,
    keeping the layer boundary intact (REQ-MOUSE-TRANSPORT-003).
    """
    from eou.transport._factory import make_tcp_transport  # type: ignore[import]

    return make_tcp_transport()


def _make_backend() -> object:
    """Construct the OS mouse backend (pynput on Windows/Linux/macOS)."""
    try:
        from eou.input._pynput_backend import PynputMouseBackend  # type: ignore[import]

        return PynputMouseBackend()
    except ImportError:
        # Fallback: NullBackend when pynput is not available

        class _NullBackend:
            def start_capture(self, on_event: object) -> None:
                pass

            def stop_capture(self) -> None:
                pass

            def move(self, dx: int, dy: int) -> None:
                pass

            def move_abs(self, x: int, y: int) -> None:
                pass

            def get_position(self) -> tuple[int, int]:
                return (0, 0)

            def is_running(self) -> bool:
                return False

        return _NullBackend()


def _get_screen_bounds() -> tuple[int, int, int, int]:
    """Return (0, 0, width-1, height-1) for the primary screen."""
    try:
        import screeninfo

        monitors = screeninfo.get_monitors()
        if monitors:
            m = monitors[0]
            return (0, 0, m.width - 1, m.height - 1)
    except Exception:
        pass
    return (0, 0, 1919, 1079)  # Fallback: 1920×1080
