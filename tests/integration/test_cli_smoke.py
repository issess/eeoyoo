"""CLI smoke tests — T-036 RED phase.

Tests:
    - `eou --version` exits 0 with correct version string.
    - `eou host /nonexistent.yaml` exits non-zero with ConfigError message.
    - `eou remote /nonexistent.yaml` exits non-zero.
"""
from __future__ import annotations


class TestCliVersion:
    """eou --version prints version and exits 0."""

    def test_version_exits_zero(self) -> None:
        """eou --version exits with code 0."""
        from typer.testing import CliRunner

        from eou import __version__
        from eou.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestCliHostNonexistentConfig:
    """eou host <missing> exits non-zero with error message."""

    def test_host_nonexistent_config_exits_nonzero(self) -> None:
        """eou host /nonexistent/path.yaml exits with non-zero code."""
        from typer.testing import CliRunner

        from eou.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["host", "/nonexistent/path.yaml"])
        assert result.exit_code != 0

    def test_remote_nonexistent_config_exits_nonzero(self) -> None:
        """eou remote /nonexistent/path.yaml exits with non-zero code."""
        from typer.testing import CliRunner

        from eou.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["remote", "/nonexistent/path.yaml"])
        assert result.exit_code != 0
