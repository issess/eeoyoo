"""App configuration loader for SPEC-MOUSE-001.

Loads YAML config into frozen dataclasses.  No pydantic — pure dataclass
+ yaml.safe_load + manual validation.

# @MX:ANCHOR: [AUTO] load_config — composition root config entry point.
# @MX:REASON: Both CLI entry points (eou host / eou remote) call load_config()
#             before constructing Host or Remote.  fan_in == 2 at cli.py level;
#             becomes 3+ if additional bootstrap paths are added.  Changing the
#             return type or raising contract here breaks both entry points.

REQ: SPEC-MOUSE-001 Slice 4 — config loader (T-030/T-031).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Literal

import yaml


# ---------------------------------------------------------------------------
# ConfigError
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """Raised when the YAML config is invalid, missing required fields,
    contains unknown keys, or cannot be parsed.

    REQ: strategy.md — unknown top-level keys → ConfigError(ValueError).
    """


# ---------------------------------------------------------------------------
# Sub-config dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class EdgeConfig:
    """Configuration for edge detection thresholds.

    Maps to the 'edge:' YAML section.
    """

    threshold_px: int = 2
    dwell_ticks: int = 2


@dataclasses.dataclass(frozen=True)
class TakebackConfig:
    """Configuration for takeback detection thresholds.

    Maps to the 'takeback:' YAML section.
    """

    pixel_threshold: int = 5
    event_count_threshold: int = 2
    time_window_ms: int = 100


# ---------------------------------------------------------------------------
# Root config dataclass
# ---------------------------------------------------------------------------

_KNOWN_TOP_LEVEL_KEYS = frozenset(
    {"role", "endpoint", "edge", "takeback", "hide_cursor"}
)

_VALID_ROLES: frozenset[str] = frozenset({"host", "remote"})


@dataclasses.dataclass(frozen=True)
class EouConfig:
    """Root application configuration.

    Attributes:
        role: Node role — 'host' or 'remote'.
        endpoint: TCP endpoint string in "host:port" format.
        edge: Edge detection configuration.
        takeback: Takeback detection configuration.
        hide_cursor: Whether to hide the HOST cursor while CONTROLLING.
            Defaults to True (REQ-MOUSE-VISIBILITY-002).
    """

    role: Literal["host", "remote"]
    endpoint: str
    edge: EdgeConfig
    takeback: TakebackConfig
    hide_cursor: bool = True


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(path: Path) -> EouConfig:
    """Load and validate a YAML configuration file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        A fully validated, frozen EouConfig instance.

    Raises:
        ConfigError: If the file cannot be parsed, contains unknown top-level
            keys, is missing required fields, or has invalid field values.

    # @MX:ANCHOR: [AUTO] load_config — config load entry point.
    # @MX:REASON: Both host and remote CLI entry points call this function;
    #             all config validation is centralised here.
    """
    # 1. Parse YAML
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML parse error in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(
            f"Config file {path} must contain a YAML mapping at the top level."
        )

    data: dict[str, object] = raw  # type: ignore[assignment]

    # 2. Unknown key check
    unknown = set(data.keys()) - _KNOWN_TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(
            f"Unknown top-level config key(s): {sorted(unknown)}. "
            f"Allowed keys: {sorted(_KNOWN_TOP_LEVEL_KEYS)}"
        )

    # 3. Required fields
    if "role" not in data:
        raise ConfigError("Missing required config field: 'role'.")
    if "endpoint" not in data:
        raise ConfigError("Missing required config field: 'endpoint'.")

    # 4. Validate role
    role = data["role"]
    if role not in _VALID_ROLES:
        raise ConfigError(
            f"Invalid role {role!r}. Must be one of: {sorted(_VALID_ROLES)}"
        )

    # 5. Build sub-configs
    edge_raw = data.get("edge", {})
    if not isinstance(edge_raw, dict):
        raise ConfigError("'edge' must be a YAML mapping.")
    try:
        edge_cfg = EdgeConfig(**edge_raw)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ConfigError(f"Invalid 'edge' config: {exc}") from exc

    takeback_raw = data.get("takeback", {})
    if not isinstance(takeback_raw, dict):
        raise ConfigError("'takeback' must be a YAML mapping.")
    try:
        takeback_cfg = TakebackConfig(**takeback_raw)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ConfigError(f"Invalid 'takeback' config: {exc}") from exc

    hide_cursor: bool = bool(data.get("hide_cursor", True))

    return EouConfig(
        role=role,  # type: ignore[arg-type]
        endpoint=str(data["endpoint"]),
        edge=edge_cfg,
        takeback=takeback_cfg,
        hide_cursor=hide_cursor,
    )
