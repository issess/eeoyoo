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
import logging
import os
import subprocess
import sys
from pathlib import Path

import typer

from eou import __version__
from eou.config import ConfigError, EouConfig, load_config

_logger = logging.getLogger("eou.cli")

app = typer.Typer(name="eou", add_completion=False, no_args_is_help=True)


def _init_logging() -> None:
    """Configure root logging so INFO messages are visible on stderr.

    Without this, Python's lastResort handler only emits WARNING+, hiding
    the diagnostic INFO/DEBUG logs added throughout host.py / remote.py.
    Set ``EOU_DEBUG=1`` in the environment to raise the level to DEBUG.
    """
    level = logging.DEBUG if os.environ.get("EOU_DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

# Default config paths (relative to CWD). Used when CONFIG_PATH argument is omitted.
_DEFAULT_HOST_CONFIG = Path("configs/eou.host.yaml")
_DEFAULT_REMOTE_CONFIG = Path("configs/eou.remote.yaml")


def _format_network_error(exc: OSError, endpoint: str, role: str) -> str:
    """Translate common OS-level socket errors into a user-friendly diagnostic.

    Returns a short, actionable message (Korean) instead of dumping a raw
    asyncio traceback. Covers the Windows error codes we see most often
    on LAN setups.
    """
    code = getattr(exc, "winerror", None) or exc.errno

    # Generic header
    header = f"[{role}] 연결 실패: {endpoint} (error {code}: {exc.strerror or exc})"

    if code in (121, 10060):  # WinError 121 semaphore timeout / 10060 timed out
        cause = "원격 PC에서 응답이 없습니다 (SYN 타임아웃)."
        hints = [
            "1. REMOTE PC에서 `eou remote`가 실행 중인지 확인",
            "2. REMOTE의 `ipconfig`로 확인한 LAN IP와 endpoint가 일치하는지 확인",
            "3. REMOTE의 Windows 방화벽이 해당 포트(TCP)를 허용하는지 확인",
            "   (관리자 PS) New-NetFirewallRule -DisplayName 'eou remote' "
            "-Direction Inbound -Protocol TCP -LocalPort <port> -Action Allow",
            "4. 두 PC가 같은 서브넷/네트워크에 있는지 `ping <remote-ip>` 로 확인",
        ]
    elif code == 1214:  # invalid network name — e.g. dialing 0.0.0.0
        cause = "유효하지 않은 dial 대상입니다 (0.0.0.0 같은 주소로는 연결할 수 없음)."
        hints = [
            "1. HOST의 endpoint는 REMOTE의 실제 LAN IP여야 합니다 "
            "(예: 192.168.1.5:7001)",
            "2. REMOTE의 endpoint만 0.0.0.0:<port> (모든 인터페이스 listen) 가능합니다",
        ]
    elif code in (10061, 111):  # connection refused
        cause = "대상 포트는 열려 있지 않습니다 (상대가 listen 중이 아님)."
        hints = [
            "1. REMOTE PC에서 `eou remote`를 먼저 실행하세요",
            "2. REMOTE의 endpoint 포트와 HOST의 endpoint 포트가 같은지 확인",
        ]
    elif code in (10013, 13):  # permission denied (port in use / firewall)
        cause = "해당 포트에 바인드할 권한이 없거나 이미 사용 중입니다."
        hints = [
            "1. `netstat -ano | findstr :<port>` 로 점유 프로세스 확인",
            "2. 1024 미만 포트는 관리자 권한이 필요합니다 — 7001 등 > 1024 사용",
        ]
    elif code in (10048, 98):  # address already in use
        cause = "해당 포트가 이미 다른 프로세스에 의해 사용 중입니다."
        hints = [
            "1. `netstat -ano | findstr :<port>` 로 점유 PID 확인 후 종료",
            "2. 다른 포트 번호로 endpoint 변경",
        ]
    elif code in (11001, -2, -3, 8):  # host not found / name resolution
        cause = "호스트 이름을 해석할 수 없습니다."
        hints = [
            "1. endpoint가 도메인 이름이라면 IP 주소로 바꿔 보세요",
            "2. `ping <host>` 로 이름 해석 여부 확인",
        ]
    else:
        cause = "원인을 특정할 수 없는 네트워크 오류입니다."
        hints = [
            f"1. 상대 endpoint `{endpoint}` 에 도달 가능한지 `ping` / "
            f"`Test-NetConnection <host> -Port <port>` 로 확인",
            "2. 방화벽/VPN/네트워크 어댑터 설정 확인",
        ]

    lines = [header, f"원인: {cause}", "확인 사항:"]
    lines.extend(f"  {h}" for h in hints)
    return "\n".join(lines)


def _parse_port(endpoint: str) -> int | None:
    """Extract TCP port from an endpoint string like 'host:port' or ':port'."""
    if ":" not in endpoint:
        return None
    try:
        return int(endpoint.rsplit(":", 1)[1])
    except ValueError:
        return None


def _check_windows_firewall(port: int) -> tuple[bool, str | None]:
    """Check whether an enabled inbound Allow rule exists for TCP <port> on Windows.

    Returns:
        (True,  None)         : matching rule found OR check could not be
                                performed (fail-open to avoid false alarms).
        (False, None)         : positively determined no matching rule exists.
    Non-Windows platforms always return (True, None).
    """
    if sys.platform != "win32":
        return True, None

    # PowerShell: look for any enabled, Allow, Inbound rule whose port filter
    # matches this TCP port (or "Any").
    ps_script = (
        f"$p={port};"
        "$r=Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow "
        "-ErrorAction SilentlyContinue;"
        "if(-not $r){exit 2};"
        "$m=$r|Get-NetFirewallPortFilter|Where-Object "
        "{$_.Protocol -eq 'TCP' -and ($_.LocalPort -eq $p -or $_.LocalPort -eq 'Any')};"
        "if($m){exit 0}else{exit 1}"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return True, None  # fail-open: can't check, don't block user

    if proc.returncode == 0:
        return True, None
    if proc.returncode == 1:
        return False, None
    return True, None  # fail-open on unexpected exit codes


def _format_firewall_warning(port: int, endpoint: str) -> str:
    rule_name = f"eou remote {port}"
    return (
        f"[REMOTE] 경고: Windows 방화벽에 TCP {port} 포트 인바운드 허용 규칙이 없습니다.\n"
        f"        HOST PC에서 이 포트로 연결을 시도하면 차단될 수 있습니다.\n"
        "        관리자 PowerShell에서 다음 명령으로 규칙을 추가하세요:\n"
        f"          New-NetFirewallRule -DisplayName '{rule_name}' "
        f"-Direction Inbound -Protocol TCP -LocalPort {port} -Action Allow\n"
        f"        (현재 endpoint: {endpoint})"
    )


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
    """EOU - Edge-triggered mouse ownership transfer (SPEC-MOUSE-001)."""
    _init_logging()


@app.command()
def host(
    config_path: Path = typer.Argument(
        _DEFAULT_HOST_CONFIG,
        help="Path to eou.yaml config file (default: configs/eou.host.yaml).",
    ),
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

    typer.echo(f"[HOST] Loaded config: {config_path} (endpoint={cfg.endpoint})")

    try:
        asyncio.run(_run_host(cfg))
    except KeyboardInterrupt:
        typer.echo("Host stopped.")
    except OSError as exc:
        typer.echo(_format_network_error(exc, cfg.endpoint, "HOST"), err=True)
        raise typer.Exit(code=2)


@app.command()
def remote(
    config_path: Path = typer.Argument(
        _DEFAULT_REMOTE_CONFIG,
        help="Path to eou.yaml config file (default: configs/eou.remote.yaml).",
    ),
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

    typer.echo(f"[REMOTE] Loaded config: {config_path} (endpoint={cfg.endpoint})")

    port = _parse_port(cfg.endpoint)
    if port is not None:
        ok, _detail = _check_windows_firewall(port)
        if not ok:
            typer.echo(_format_firewall_warning(port, cfg.endpoint), err=True)

    try:
        asyncio.run(_run_remote(cfg))
    except KeyboardInterrupt:
        typer.echo("Remote stopped.")
    except OSError as exc:
        typer.echo(_format_network_error(exc, cfg.endpoint, "REMOTE"), err=True)
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# Internal runners
# ---------------------------------------------------------------------------


async def _connect_with_retry(
    transport: object, endpoint: str,
    *, initial_delay: float = 1.0, max_delay: float = 30.0,
) -> None:
    """Dial *endpoint* with unbounded exponential-backoff retry.

    Retries only on OSError from the TCP connect itself (peer unreachable,
    refused, listener not up yet, etc.). The first failure emits the full
    diagnostic from :func:`_format_network_error`; subsequent failures are
    logged as single-line messages to keep the console readable during long
    waits. Ctrl+C aborts the retry loop cleanly via KeyboardInterrupt,
    which the CLI entry point catches.
    """
    attempt = 0
    delay = initial_delay
    while True:
        attempt += 1
        try:
            typer.echo(
                f"[HOST] Connecting to {endpoint} (attempt {attempt}) ..."
            )
            await transport.connect(endpoint)  # type: ignore[attr-defined]
            typer.echo(f"[HOST] Connected to {endpoint}.")
            return
        except OSError as exc:
            if attempt == 1:
                # Full diagnostic on the first failure so the user sees the
                # root cause + actionable checks without having to re-run.
                typer.echo(
                    _format_network_error(exc, endpoint, "HOST"), err=True
                )
            else:
                code = getattr(exc, "winerror", None) or exc.errno
                typer.echo(
                    f"[HOST] Attempt {attempt} failed "
                    f"(error {code}: {exc.strerror or exc})",
                    err=True,
                )
            typer.echo(
                f"[HOST] Retrying in {delay:.0f}s (Ctrl+C to stop) ...",
                err=True,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)


async def _run_host(cfg: EouConfig) -> None:
    """Wire and run the Host orchestrator."""
    # Lazy imports to keep cli.py decoupled from concrete implementations.
    # cli.py uses Host/Remote constructors — it does NOT import transport.tcp directly.
    from eou.host import Host
    from eou.input.visibility import create_cursor_visibility
    from eou.ownership.edge_detector import EdgeConfig
    from eou.ownership.takeback_detector import TakebackConfig

    transport = _make_transport(cfg)
    await _connect_with_retry(transport, cfg.endpoint)

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
    _logger.info(
        "Host wiring: endpoint=%s screen_bounds=%s edge=%s threshold_px=%d "
        "dwell_ticks=%d hide_cursor=%s",
        cfg.endpoint, edge_cfg.screen_bounds, edge_cfg.edge,
        edge_cfg.threshold_px, edge_cfg.dwell_ticks, cfg.hide_cursor,
    )
    typer.echo(
        f"[HOST] Ready. edge={edge_cfg.edge} threshold={edge_cfg.threshold_px}px "
        f"dwell={edge_cfg.dwell_ticks}ticks. Press Ctrl+C to stop."
    )
    await h.run()


async def _run_remote(cfg: EouConfig) -> None:
    """Wire and run the Remote orchestrator.

    Runs an unbounded session loop: after each HOST disconnects, we close
    the transport and immediately re-listen for the next HOST connection.
    Ctrl+C (KeyboardInterrupt) aborts the loop cleanly.
    """
    from eou.input.visibility import NullCursorVisibility
    from eou.ownership.edge_detector import EdgeConfig
    from eou.ownership.takeback_detector import TakebackConfig
    from eou.remote import Remote

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

    _logger.info(
        "Remote wiring: endpoint=%s screen_bounds=%s edge=%s threshold_px=%d "
        "dwell_ticks=%d",
        cfg.endpoint, edge_cfg.screen_bounds, edge_cfg.edge,
        edge_cfg.threshold_px, edge_cfg.dwell_ticks,
    )
    typer.echo(
        f"[REMOTE] Ready. edge={edge_cfg.edge} threshold={edge_cfg.threshold_px}px "
        f"dwell={edge_cfg.dwell_ticks}ticks. Press Ctrl+C to stop."
    )

    session = 0
    while True:
        session += 1
        transport = _make_transport(cfg)
        typer.echo(
            f"[REMOTE] Session {session}: listening on {cfg.endpoint} "
            f"(waiting for host)..."
        )
        _logger.info(
            "Remote: session %d — listening on %s, waiting for host",
            session, cfg.endpoint,
        )
        try:
            await transport.listen(cfg.endpoint)  # type: ignore[attr-defined]
            typer.echo(f"[REMOTE] Session {session}: host connected.")
            _logger.info("Remote: session %d — host connected", session)

            r = Remote(
                transport=transport,
                backend=backend,
                visibility=visibility,
                edge_config=edge_cfg,
                takeback_config=takeback_cfg,
            )
            await r.run()
            _logger.info(
                "Remote: session %d — run() returned (host disconnected or "
                "session ended normally)", session,
            )
        finally:
            try:
                await transport.close()
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass

        typer.echo(
            f"[REMOTE] Session {session} ended. "
            f"Re-listening for next host connection..."
        )
        _logger.info(
            "Remote: session %d closed; restarting listener shortly",
            session,
        )
        await asyncio.sleep(0.5)


def _make_transport(cfg: EouConfig) -> object:
    """Construct the appropriate Transport (TCPTransport for MVP).

    cli.py does not import transport.tcp directly.  TCPTransport is
    constructed via a factory function that lives inside transport/,
    keeping the layer boundary intact (REQ-MOUSE-TRANSPORT-003).
    """
    from eou.transport._factory import make_tcp_transport  # type: ignore[import]

    return make_tcp_transport()


def _make_backend() -> object:
    """Construct the OS mouse backend (pynput on Windows/Linux/macOS).

    Falls back to a no-op backend only when pynput (or the backend module)
    cannot be imported. The fallback is loud: a WARNING is emitted and a
    stderr banner tells the user that no mouse events will ever arrive, so
    the bug never hides silently the way it used to.
    """
    try:
        from eou.input._pynput_backend import PynputMouseBackend  # type: ignore[import]

        return PynputMouseBackend()
    except ImportError as exc:
        _logger.warning(
            "pynput backend unavailable (%s); falling back to NullBackend — "
            "mouse capture is DISABLED and no edge detection will occur. "
            "Install the 'pynput' package: pip install -e '.[dev]' (or '.[full]').",
            exc,
        )
        typer.echo(
            "[HOST] WARNING: pynput backend unavailable — running with "
            "NullBackend. Mouse events will NOT be captured. "
            f"(ImportError: {exc})",
            err=True,
        )

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
