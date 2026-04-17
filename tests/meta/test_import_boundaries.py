"""Layer boundary enforcement meta-test.

Walks src/eou/**/*.py using the ast module and asserts that no module
outside src/eou/transport/ imports transport.tcp or transport.ble directly.

REQ-MOUSE-TRANSPORT-003: direct import of transport.tcp/transport.ble outside
    transport/ must fail the build-time layer check.

Architecture reference: strategy.md §2 "Layer Boundary 강제"

Allowed imports from outside transport/:
    - eou.transport          (package init — provides ABC exports only)
    - eou.transport.base     (explicit ABC import)

Forbidden imports from outside transport/:
    - eou.transport.tcp
    - eou.transport.ble
    - src.eou.transport.tcp
    - src.eou.transport.ble
"""

from __future__ import annotations

import ast
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FORBIDDEN_MODULES = frozenset(
    {
        "eou.transport.tcp",
        "eou.transport.ble",
        "src.eou.transport.tcp",
        "src.eou.transport.ble",
    }
)


def _is_forbidden_import(node: ast.stmt) -> bool:
    """Return True if *node* is an import of a forbidden concrete transport module."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name in _FORBIDDEN_MODULES:
                return True
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module in _FORBIDDEN_MODULES:
            return True
        # Also catch: from eou.transport import tcp
        # (module = "eou.transport", names include "tcp" or "ble")
        if module in ("eou.transport", "src.eou.transport"):
            for alias in node.names:
                if alias.name in ("tcp", "ble"):
                    return True
    return False


def _collect_violations(src_root: Path) -> list[str]:
    """Return a list of human-readable violation strings."""
    transport_dir = src_root / "eou" / "transport"
    violations: list[str] = []

    for py_file in sorted(src_root.rglob("*.py")):
        # Files inside transport/ are allowed to import tcp/ble
        try:
            py_file.relative_to(transport_dir)
            continue  # skip transport/ directory itself
        except ValueError:
            pass

        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError:
            continue

        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if _is_forbidden_import(node):
                rel = py_file.relative_to(src_root.parent)
                violations.append(
                    f"{rel}:{getattr(node, 'lineno', '?')} — "
                    f"forbidden concrete transport import"
                )

    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLayerBoundaries:
    """Layer boundary enforcement: transport concrete impl import prohibition."""

    def test_no_forbidden_transport_imports_outside_transport_package(self) -> None:
        """No source file outside transport/ may import tcp or ble directly.

        REQ-MOUSE-TRANSPORT-003: build-time layer check must fail on violation.
        Strategy §2: banned-module-level-imports enforced via ast walk.
        """
        src_root = Path(__file__).parent.parent.parent / "src"
        violations = _collect_violations(src_root)

        assert violations == [], (
            "Layer boundary violation(s) detected:\n"
            + "\n".join(f"  {v}" for v in violations)
            + "\n\nModules outside src/eou/transport/ must depend only on "
            "eou.transport or eou.transport.base (the ABC), never on "
            "eou.transport.tcp or eou.transport.ble directly. "
            "Pass concrete instances via dependency injection."
        )

    def test_transport_init_does_not_export_tcp_transport(self) -> None:
        """transport/__init__.py must not re-export TCPTransport.

        Callers who import from eou.transport should only get the ABC and
        error types — never the concrete TCPTransport class.
        """
        import eou.transport as transport_pkg

        assert not hasattr(transport_pkg, "TCPTransport"), (
            "transport/__init__.py must not export TCPTransport. "
            "Upper layers receive concrete transports via DI only."
        )

    def test_protocol_does_not_import_transport_tcp(self) -> None:
        """eou.protocol modules must not import eou.transport.tcp."""
        import importlib

        protocol_codec = importlib.import_module("eou.protocol.codec")
        protocol_messages = importlib.import_module("eou.protocol.messages")

        for mod in (protocol_codec, protocol_messages):
            mod_file = getattr(mod, "__file__", "") or ""
            if not mod_file:
                continue
            source = Path(mod_file).read_text(encoding="utf-8")
            tree = ast.parse(source)
            violations = [
                node
                for node in ast.walk(tree)
                if _is_forbidden_import(node)  # type: ignore[arg-type]
            ]
            assert violations == [], (
                f"{mod.__name__} must not import transport.tcp/ble. "
                "Found: " + str(violations)
            )

    def test_forbidden_modules_set_is_complete(self) -> None:
        """Verify the forbidden module set covers all expected patterns."""
        expected = {
            "eou.transport.tcp",
            "eou.transport.ble",
            "src.eou.transport.tcp",
            "src.eou.transport.ble",
        }
        assert _FORBIDDEN_MODULES == expected
