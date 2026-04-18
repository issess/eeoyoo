"""Transport factory — provides concrete TCPTransport without exposing tcp.py.

Upper layers (cli.py) call make_tcp_transport() instead of importing
TCPTransport directly, preserving the layer boundary
(REQ-MOUSE-TRANSPORT-003).
"""
from __future__ import annotations

from eou.transport.tcp import TCPTransport


def make_tcp_transport() -> TCPTransport:
    """Create and return a new TCPTransport instance."""
    return TCPTransport()
