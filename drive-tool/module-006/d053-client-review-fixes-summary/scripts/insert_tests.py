p = 'tests/test_service_client.py'
s = open(p, encoding='utf-8').read()

block = '''

# ---------------------------------------------------------------------------
# Response-body transport errors (D053)
#
# D051 primary finding: a transport failure while the response *body* is read
# (stall / truncation / reset / malformed chunk) escaped as a raw stdlib
# exception instead of a safe DriveClientError. These regressions pin the fix.
# ---------------------------------------------------------------------------


class _RaisingResponse:
    """A fake response whose body ``read`` raises a configured exception."""

    def __init__(self, exc, status=200, pairs=()):
        self.status = status
        self.headers = _FakeHeaders(pairs)
        self._exc = exc
        self.closed = False
        self.read_calls = 0

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, amt=None):
        self.read_calls += 1
        raise self._exc

    def close(self):
        self.closed = True


class _RawSocketServer:
    """One-shot raw loopback server that writes a fixed byte sequence."""

    def __init__(self, raw, stall=False):
        self._raw = raw
        self._stall = stall
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]

    def __enter__(self):
        def run():
            import time

            try:
                conn, _ = self._srv.accept()
                conn.settimeout(2.0)
                try:
                    buf = b""
                    while b"\\r\\n\\r\\n" not in buf:
                        data = conn.recv(4096)
                        if not data:
                            break
                        buf += data
                except OSError:
                    pass
                conn.sendall(self._raw)
                if self._stall:
                    time.sleep(1.5)
                try:
                    conn.recv(4096)
                except OSError:
                    pass
                conn.close()
            except OSError:
                pass
            finally:
                self._srv.close()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._thread.join(timeout=3)
        return False


class TestResponseBodyTransportErrors(unittest.TestCase):
    """A mid-body transport failure must map to a safe DriveClientError."""

    def _seam_client(self, resp):
        conn = _FakeConnection(resp)
        client = _client(1)
        return client, conn, resp, _Seam(client, [conn])

    def test_read_body_timeout_is_safe_timeout(self):
        resp = _RaisingResponse(socket.timeout("stalled"))
        client, conn, resp, seam = self._seam_client(resp)
        with seam:
            with self.assertRaises(DriveClientError) as ctx:
                client.read("src", "p/a.bin", offset=0, length=8)
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertIs(ctx.exception.outcome_uncertain, False)
        self.assertIs(ctx.exception.retry_safe, True)
        self.assertTrue(resp.closed)
        self.assertTrue(conn.closed)
        self.assertEqual(seam.calls, 1)

    def test_save_body_timeout_is_uncertain_not_retry_safe(self):
        resp = _RaisingResponse(socket.timeout("stalled"))
        client, conn, resp, seam = self._seam_client(resp)
        with seam:
            with self.assertRaises(DriveClientError) as ctx:
                client.save("src", "p/a.bin", b"x")
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertIs(ctx.exception.outcome_uncertain, True)
        self.assertIs(ctx.exception.retry_safe, False)
        self.assertTrue(resp.closed)
        self.assertTrue(conn.closed)

    def test_read_body_incomplete_read_is_unavailable(self):
        resp = _RaisingResponse(http.client.IncompleteRead(b"ab", 10))
        client, conn, resp, seam = self._seam_client(resp)
        with seam:
            with self.assertRaises(DriveClientError) as ctx:
                client.read("src", "p/a.bin", offset=0, length=8)
        self.assertEqual(ctx.exception.code, "unavailable")
        self.assertIs(ctx.exception.outcome_uncertain, False)
        self.assertIs(ctx.exception.retry_safe, True)

    def test_read_body_malformed_chunk_is_unavailable(self):
        resp = _RaisingResponse(http.client.HTTPException("bad chunk"))
        client, conn, resp, seam = self._seam_client(resp)
        with seam:
            with self.assertRaises(DriveClientError) as ctx:
                client.read("src", "p/a.bin", offset=0, length=8)
        self.assertEqual(ctx.exception.code, "unavailable")

    def test_save_body_connection_reset_is_uncertain(self):
        resp = _RaisingResponse(ConnectionResetError("reset"))
        client, conn, resp, seam = self._seam_client(resp)
        with seam:
            with self.assertRaises(DriveClientError) as ctx:
                client.save("src", "p/a.bin", b"x")
        self.assertEqual(ctx.exception.code, "unavailable")
        self.assertIs(ctx.exception.outcome_uncertain, True)
        self.assertIs(ctx.exception.retry_safe, False)

    def test_error_path_body_timeout_maps_to_timeout(self):
        resp = _RaisingResponse(socket.timeout("stalled"), status=500)
        client, conn, resp, seam = self._seam_client(resp)
        with seam:
            with self.assertRaises(DriveClientError) as ctx:
                client.list("src")
        self.assertEqual(ctx.exception.code, "timeout")

    def test_body_error_is_redacted(self):
        resp = _RaisingResponse(
            ConnectionResetError("Bearer " + TOKEN + " /srv/secret")
        )
        client, conn, resp, seam = self._seam_client(resp)
        with seam:
            with self.assertRaises(DriveClientError) as ctx:
                client.list("src")
        text = str(ctx.exception) + repr(ctx.exception)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("/srv/secret", text)

    def test_no_retry_on_body_transport_error(self):
        resp = _RaisingResponse(socket.timeout("stalled"))
        client, conn, resp, seam = self._seam_client(resp)
        with seam:
            with self.assertRaises(DriveClientError):
                client.read("src", "p/a.bin", offset=0, length=8)
        self.assertEqual(seam.calls, 1)
        self.assertEqual(resp.read_calls, 1)


class TestResponseBodyTransportErrorsFakeServer(unittest.TestCase):
    """Real tiny raw-socket servers: stalled and malformed/truncated chunked."""

    _READ_PREFIX = (
        b"HTTP/1.1 200 OK\\r\\nContent-Type: application/octet-stream\\r\\n"
        b"X-Drive-Offset: 0\\r\\nX-Drive-Observed-Size: 3\\r\\n"
        b"X-Drive-Observed-Mtime-Ns: 1\\r\\nX-Drive-EOF-Observed: true\\r\\n"
    )

    def test_stalled_body_read_is_timeout(self):
        raw = self._READ_PREFIX + b"Content-Length: 100\\r\\n\\r\\n"
        with _RawSocketServer(raw, stall=True) as server:
            with self.assertRaises(DriveClientError) as ctx:
                _client(server.port, timeout=0.4).read(
                    "src", "p/a.bin", offset=0, length=8
                )
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertIs(ctx.exception.outcome_uncertain, False)
        self.assertIs(ctx.exception.retry_safe, True)

    def test_malformed_chunk_body_is_unavailable(self):
        raw = (
            b"HTTP/1.1 200 OK\\r\\nContent-Type: application/octet-stream\\r\\n"
            b"Transfer-Encoding: chunked\\r\\n\\r\\nZZZ\\r\\n"
        )
        with _RawSocketServer(raw) as server:
            with self.assertRaises(DriveClientError) as ctx:
                _client(server.port, timeout=1.5).read(
                    "src", "p/a.bin", offset=0, length=8
                )
        self.assertEqual(ctx.exception.code, "unavailable")
        self.assertIs(ctx.exception.retry_safe, True)

    def test_truncated_chunked_body_is_unavailable(self):
        # Declares a 5-byte chunk but sends only 3 bytes, then closes.
        raw = (
            b"HTTP/1.1 200 OK\\r\\nContent-Type: application/octet-stream\\r\\n"
            b"Transfer-Encoding: chunked\\r\\n\\r\\n5\\r\\nabc"
        )
        with _RawSocketServer(raw) as server:
            with self.assertRaises(DriveClientError) as ctx:
                _client(server.port, timeout=1.5).read(
                    "src", "p/a.bin", offset=0, length=8
                )
        self.assertEqual(ctx.exception.code, "unavailable")


'''

marker = '\nif __name__ == "__main__":  # pragma: no cover\n    unittest.main()\n'
assert s.count(marker) == 1, s.count(marker)
s = s.replace(marker, block + marker)
open(p, 'w', encoding='utf-8').write(s)
print("tests inserted")
