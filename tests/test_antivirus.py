"""Functional tests for the hand-rolled clamd INSTREAM client
(app/worker/antivirus.py) against a real TCP socket speaking the
documented clamd wire protocol - no actual ClamAV daemon needed to
verify the framing/parsing logic itself.
"""

from __future__ import annotations

import io
import socket
import struct
import threading

import pytest

from app.worker import antivirus


def _run_fake_clamd(port: int, reply: bytes, received: list[bytes]) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    conn, _ = srv.accept()
    try:
        assert conn.recv(10) == b"zINSTREAM\x00"
        data = b""
        while True:
            length = struct.unpack("!L", conn.recv(4))[0]
            if length == 0:
                break
            chunk = b""
            while len(chunk) < length:
                chunk += conn.recv(length - len(chunk))
            data += chunk
        received.append(data)
        conn.sendall(reply)
    finally:
        conn.close()
        srv.close()


def _start_fake_clamd(port: int, reply: bytes) -> tuple[threading.Thread, list[bytes]]:
    received: list[bytes] = []
    thread = threading.Thread(target=_run_fake_clamd, args=(port, reply, received), daemon=True)
    thread.start()
    return thread, received


def test_clean_file_roundtrips_content_and_reports_not_infected():
    thread, received = _start_fake_clamd(18901, b"stream: OK")
    payload = b"just a normal file, nothing malicious here"

    infected, detail = antivirus.scan_stream("127.0.0.1", 18901, io.BytesIO(payload))
    thread.join(timeout=2)

    assert infected is False
    assert detail == "stream: OK"
    assert received[0] == payload  # chunk framing reconstructed the exact bytes


def test_infected_file_is_flagged():
    thread, _ = _start_fake_clamd(18902, b"stream: Eicar-Test-Signature FOUND")

    infected, detail = antivirus.scan_stream("127.0.0.1", 18902, io.BytesIO(b"eicar-like-payload"))
    thread.join(timeout=2)

    assert infected is True
    assert "FOUND" in detail


def test_unreachable_daemon_raises_antivirus_unavailable():
    with pytest.raises(antivirus.AntivirusUnavailable):
        antivirus.scan_stream("127.0.0.1", 18999, io.BytesIO(b"x"))
