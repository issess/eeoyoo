"""Unit tests for config loader — T-030 RED phase.

REQ: SPEC-MOUSE-001 Slice 4 config loader contract.

Tests:
    - AppConfig/EouConfig dataclass field mapping from YAML.
    - load_config raises ConfigError on unknown top-level keys.
    - load_config raises ConfigError on missing required field.
    - load_config raises ConfigError on malformed YAML.
    - hide_cursor defaults to True when omitted.
    - role field is required; absent role raises ConfigError.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


def _write_yaml(tmp_path: Path, content: str) -> Path:
    """Helper: write YAML text to a temp file and return its path."""
    p = tmp_path / "eou.yaml"
    p.write_text(textwrap.dedent(content))
    return p


class TestLoadConfigHappyPath:
    """load_config parses well-formed YAML into EouConfig."""

    def test_host_role_basic(self, tmp_path: Path) -> None:
        """Host role with minimal required fields loads correctly."""
        from eou.config import EouConfig, load_config

        path = _write_yaml(
            tmp_path,
            """\
            role: host
            endpoint: "192.168.1.5:7001"
            edge:
              threshold_px: 2
              dwell_ticks: 2
            takeback:
              pixel_threshold: 5
              event_count_threshold: 2
              time_window_ms: 100
            """,
        )
        cfg = load_config(path)
        assert isinstance(cfg, EouConfig)
        assert cfg.role == "host"
        assert cfg.endpoint == "192.168.1.5:7001"
        assert cfg.edge.threshold_px == 2
        assert cfg.edge.dwell_ticks == 2
        assert cfg.takeback.pixel_threshold == 5
        assert cfg.takeback.event_count_threshold == 2
        assert cfg.takeback.time_window_ms == 100

    def test_remote_role(self, tmp_path: Path) -> None:
        """Remote role loads correctly."""
        from eou.config import load_config

        path = _write_yaml(
            tmp_path,
            """\
            role: remote
            endpoint: "192.168.1.1:7001"
            edge:
              threshold_px: 3
              dwell_ticks: 3
            takeback:
              pixel_threshold: 10
              event_count_threshold: 3
              time_window_ms: 200
            """,
        )
        cfg = load_config(path)
        assert cfg.role == "remote"
        assert cfg.endpoint == "192.168.1.1:7001"

    def test_hide_cursor_defaults_to_true(self, tmp_path: Path) -> None:
        """hide_cursor defaults to True when not present in YAML.

        REQ: AppConfig default contract.
        """
        from eou.config import load_config

        path = _write_yaml(
            tmp_path,
            """\
            role: host
            endpoint: "127.0.0.1:7001"
            edge:
              threshold_px: 2
              dwell_ticks: 2
            takeback:
              pixel_threshold: 5
              event_count_threshold: 2
              time_window_ms: 100
            """,
        )
        cfg = load_config(path)
        assert cfg.hide_cursor is True

    def test_hide_cursor_explicit_false(self, tmp_path: Path) -> None:
        """hide_cursor can be explicitly set to False."""
        from eou.config import load_config

        path = _write_yaml(
            tmp_path,
            """\
            role: host
            endpoint: "127.0.0.1:7001"
            edge:
              threshold_px: 2
              dwell_ticks: 2
            takeback:
              pixel_threshold: 5
              event_count_threshold: 2
              time_window_ms: 100
            hide_cursor: false
            """,
        )
        cfg = load_config(path)
        assert cfg.hide_cursor is False


class TestLoadConfigErrors:
    """load_config raises ConfigError on invalid inputs."""

    def test_unknown_top_level_key_raises(self, tmp_path: Path) -> None:
        """Unknown top-level key raises ConfigError.

        REQ: strategy.md — unknown keys → ConfigError(ValueError).
        """
        from eou.config import ConfigError, load_config

        path = _write_yaml(
            tmp_path,
            """\
            role: host
            endpoint: "127.0.0.1:7001"
            edge:
              threshold_px: 2
              dwell_ticks: 2
            takeback:
              pixel_threshold: 5
              event_count_threshold: 2
              time_window_ms: 100
            unknown_key: bad_value
            """,
        )
        with pytest.raises(ConfigError):
            load_config(path)

    def test_missing_required_role_raises(self, tmp_path: Path) -> None:
        """Absent role field raises ConfigError."""
        from eou.config import ConfigError, load_config

        path = _write_yaml(
            tmp_path,
            """\
            endpoint: "127.0.0.1:7001"
            edge:
              threshold_px: 2
              dwell_ticks: 2
            takeback:
              pixel_threshold: 5
              event_count_threshold: 2
              time_window_ms: 100
            """,
        )
        with pytest.raises(ConfigError):
            load_config(path)

    def test_missing_required_endpoint_raises(self, tmp_path: Path) -> None:
        """Absent endpoint field raises ConfigError."""
        from eou.config import ConfigError, load_config

        path = _write_yaml(
            tmp_path,
            """\
            role: host
            edge:
              threshold_px: 2
              dwell_ticks: 2
            takeback:
              pixel_threshold: 5
              event_count_threshold: 2
              time_window_ms: 100
            """,
        )
        with pytest.raises(ConfigError):
            load_config(path)

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        """Malformed YAML (syntax error) raises ConfigError."""
        from eou.config import ConfigError, load_config

        path = tmp_path / "bad.yaml"
        path.write_text("role: host\n  bad_indent: [\n")
        with pytest.raises(ConfigError):
            load_config(path)

    def test_invalid_role_value_raises(self, tmp_path: Path) -> None:
        """Invalid role value (not 'host' or 'remote') raises ConfigError."""
        from eou.config import ConfigError, load_config

        path = _write_yaml(
            tmp_path,
            """\
            role: master
            endpoint: "127.0.0.1:7001"
            edge:
              threshold_px: 2
              dwell_ticks: 2
            takeback:
              pixel_threshold: 5
              event_count_threshold: 2
              time_window_ms: 100
            """,
        )
        with pytest.raises(ConfigError):
            load_config(path)

    def test_config_error_is_value_error(self) -> None:
        """ConfigError is a subclass of ValueError."""
        from eou.config import ConfigError

        assert issubclass(ConfigError, ValueError)
