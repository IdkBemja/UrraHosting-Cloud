"""Minimal clamd INSTREAM client (Fase 3, optional). No extra dependency
beyond the stdlib `socket` module - clamd's INSTREAM protocol is a small,
stable, well-documented wire format (send `zINSTREAM\\0`, then the
payload as <4-byte big-endian length><chunk> pairs, terminated by a
zero-length chunk, then read one reply line), so a small dependency-free
client is more reviewable here than pulling in a whole clamd client
library for three protocol messages.

Verification note: like S3Backend, this has been reviewed against
clamd's documented protocol but not exercised against a real clamd
daemon in this session (none is available here, and none ships in this
repo's compose.yml by default - see CLAMAV_HOST in .env.example).
"""

from __future__ import annotations

import socket
import struct
from typing import BinaryIO

_CHUNK_SIZE = 1024 * 1024
_SOCKET_TIMEOUT_SECONDS = 30


class AntivirusUnavailable(Exception):
    pass


def scan_stream(host: str, port: int, stream: BinaryIO) -> tuple[bool, str]:
    """Returns (is_infected, detail). Raises AntivirusUnavailable if the
    clamd daemon can't be reached at all (caller should decide whether
    that's a hard failure or a soft skip - see worker/tasks.py).
    """
    try:
        with socket.create_connection((host, port), timeout=_SOCKET_TIMEOUT_SECONDS) as sock:
            sock.sendall(b"zINSTREAM\0")
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                sock.sendall(struct.pack("!L", len(chunk)) + chunk)
            sock.sendall(struct.pack("!L", 0))

            response = sock.recv(4096).decode("utf-8", errors="replace").strip()
    except OSError as exc:
        raise AntivirusUnavailable(f"No se pudo conectar a ClamAV en {host}:{port}") from exc

    # clamd replies "stream: OK" or "stream: <SignatureName> FOUND"
    infected = response.endswith("FOUND")
    return infected, response
