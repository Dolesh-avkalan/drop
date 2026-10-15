"""Bounded loopback HTTP/1.1 adapter over LocalFileService (D061 / D068).

The module exposes :class:`DriveHTTPAdapter`, a dependency-free standard
library HTTP adapter that wires the frozen DriveClient wire protocol to a
synchronous :class:`drive_tool.file_service.LocalFileService`.

Design highlights (see the D061 contract adopted by D068):

* Plain HTTP on ``127.0.0.1`` only; no TLS, no public binding.
* Fixed thread topology: 1 accept thread + 6 operation workers.
* Absolute monotonic deadlines for request reads, response writes, and
  best-effort early rejections.
* One request per connection; no second request is ever parsed or executed.
* Auth-first delegation through the public service methods. Malformed
  payloads are delegated with ``file_id=None`` so authentication and
  authorization always run before any filesystem access.
* Redacted error envelopes (``code`` / ``outcome_uncertain`` / ``retry_safe``
  only) — no tokens, paths, roots, or exception text are ever emitted.
"""

from __future__ import annotations

import json
import math
import socket
import threading
import time
import urllib.parse

from drive_tool.file_service import LocalFileService, ServiceError

__all__ = [
    "DriveHTTPAdapter",
    "HOST",
    "LISTEN_BACKLOG",
    "MAX_IN_FLIGHT_OPERATIONS",
    "MAX_REQUEST_LINE_BYTES",
    "MAX_HEADER_BLOCK_BYTES",
    "MAX_HEADER_COUNT",
    "MAX_JSON_BODY_BYTES",
    "MAX_SAVE_BODY_BYTES",
    "MAX_READ_BODY_BYTES",
    "DEFAULT_SOCKET_TIMEOUT_SECONDS",
    "DEFAULT_DRAIN_TIMEOUT_SECONDS",
    "ACCEPT_POLL_INTERVAL_SECONDS",
    "BUSY_REJECT_BUDGET_SECONDS",
    "MAX_BUSY_READ_BYTES",
    "POST_RESPONSE_DRAIN_SECONDS",
    "MAX_DRAIN_BYTES",
]

HOST = "127.0.0.1"
LISTEN_BACKLOG = 16
MAX_IN_FLIGHT_OPERATIONS = 6
MAX_REQUEST_LINE_BYTES = 8192
MAX_HEADER_BLOCK_BYTES = 16384
MAX_HEADER_COUNT = 64
MAX_JSON_BODY_BYTES = 65536
MAX_SAVE_BODY_BYTES = 1048576
MAX_READ_BODY_BYTES = 1048576
DEFAULT_SOCKET_TIMEOUT_SECONDS = 5.0
DEFAULT_DRAIN_TIMEOUT_SECONDS = 5.0
ACCEPT_POLL_INTERVAL_SECONDS = 0.05
BUSY_REJECT_BUDGET_SECONDS = 0.05
MAX_BUSY_READ_BYTES = 16384
POST_RESPONSE_DRAIN_SECONDS = 0.05
MAX_DRAIN_BYTES = 65536

# ---------------------------------------------------------------------------
# Internal constants

_MAX_CONTENT_LENGTH_DIGITS = 10
_RECV_CHUNK = 4096

_STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    413: "Payload Too Large",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}

_SERVICE_ERROR_STATUS = {
    "invalid": 400,
    "denied": 403,
    "not_found": 404,
    "exists": 409,
    "too_large": 413,
    "busy": 503,
    "unavailable": 503,
    "timeout": 504,
}

_TCHAR_BYTES = frozenset(
    b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)

# (required keys, optional keys) per JSON endpoint.
_JSON_KEY_RULES = {
    "list": (
        frozenset({"source_id", "file_id", "limit", "offset"}),
        frozenset({"name_contains"}),
    ),
    "find": (
        frozenset(
            {
                "source_id",
                "file_id",
                "name_contains",
                "limit",
                "max_entries",
                "max_depth",
            }
        ),
        frozenset(),
    ),
    "read": (
        frozenset({"source_id", "file_id", "offset", "length"}),
        frozenset(),
    ),
}

_SAVE_QUERY_KEYS = frozenset({"source_id", "file_id", "overwrite", "create_parents"})

# ---------------------------------------------------------------------------
# Internal signals

class _ReqErrorSignal(Exception):
    """Raised for a synthesizable HTTP error that maps to a best-effort envelope."""

    __slots__ = ("status", "code", "outcome_uncertain", "retry_safe")

    def __init__(self, status, code, outcome_uncertain, retry_safe):
        self.status = status
        self.code = code
        self.outcome_uncertain = outcome_uncertain
        self.retry_safe = retry_safe

class _TimeoutSignal(Exception):
    """Raised when a monotonic deadline elapses mid-request."""

    __slots__ = ()

class _DisconnectSignal(Exception):
    """Raised when the peer closed the socket mid-request."""

    __slots__ = ()

# ---------------------------------------------------------------------------
# Small helpers

class _ParsedRequest:
    """Carries the minimal parsed request surface used by the dispatcher."""

    __slots__ = ("endpoint", "query", "token", "body")

    def __init__(self, endpoint, query, token, body):
        self.endpoint = endpoint
        self.query = query
        self.token = token
        self.body = body

class _WorkerSlot:
    """One per worker thread: the connection assigned to it, if any."""

    __slots__ = ("conn", "thread")

    def __init__(self):
        self.conn = None
        self.thread = None

def _no_dup_keys(pairs):
    """``object_pairs_hook`` that rejects duplicate JSON keys anywhere."""

    seen = set()
    out = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate JSON key")
        seen.add(key)
        out[key] = value
    return out

def _no_nan_inf(value):
    """``parse_constant`` hook that rejects NaN / Infinity / -Infinity."""

    raise ValueError("non-finite JSON constant")

def _parse_json_strict(body):
    """Strict UTF-8 JSON decoder rejecting BOM, duplicates, NaN/Infinity."""

    if not isinstance(body, bytes):
        raise ValueError("body must be bytes")
    if body.startswith(b"\xef\xbb\xbf"):
        raise ValueError("UTF-8 BOM not permitted")
    text = body.decode("utf-8", errors="strict")
    return json.loads(text, object_pairs_hook=_no_dup_keys, parse_constant=_no_nan_inf)

def _parse_header_line(line):
    """Validate and split one header line (no trailing CRLF).

    Returns ``(lowercased_name_bytes, stripped_value_bytes)``.
    """

    if not line:
        raise _ReqErrorSignal(400, "invalid", False, False)
    first = line[0]
    if first == 0x20 or first == 0x09:
        # obs-fold or leading whitespace
        raise _ReqErrorSignal(400, "invalid", False, False)
    colon = line.find(b":")
    if colon <= 0:
        raise _ReqErrorSignal(400, "invalid", False, False)
    name = line[:colon]
    if name != name.rstrip(b" \t"):
        raise _ReqErrorSignal(400, "invalid", False, False)
    for b in name:
        if b not in _TCHAR_BYTES:
            raise _ReqErrorSignal(400, "invalid", False, False)
    value = line[colon + 1:].strip(b" \t")
    for b in value:
        if b == 0x09:
            continue
        if b < 0x20 or b >= 0x7F:
            raise _ReqErrorSignal(400, "invalid", False, False)
    return name.lower(), value

# ---------------------------------------------------------------------------
# Adapter

class DriveHTTPAdapter:
    """Bounded loopback HTTP/1.1 adapter over ``LocalFileService``."""

    # ----- construction ----------------------------------------------------

    def __init__(
        self,
        policies=None,
        *,
        service=None,
        port=0,
        socket_timeout=DEFAULT_SOCKET_TIMEOUT_SECONDS,
    ):
        if policies is None and service is None:
            raise ValueError("exactly one of policies or service must be provided")
        if policies is not None and service is not None:
            raise ValueError("exactly one of policies or service must be provided")

        if type(port) is bool or not isinstance(port, int):
            raise TypeError("port must be a non-bool int")
        if port < 0 or port > 65535:
            raise ValueError("port must be in 0..65535")

        if type(socket_timeout) is bool or not isinstance(socket_timeout, (int, float)):
            raise TypeError("socket_timeout must be a non-bool number")
        socket_timeout_f = float(socket_timeout)
        if not math.isfinite(socket_timeout_f) or socket_timeout_f <= 0.0:
            raise ValueError("socket_timeout must be finite and > 0")

        if service is not None:
            if not isinstance(service, LocalFileService):
                raise TypeError("service must be a LocalFileService instance")
            self._service = service
            self._owns_service = False
        else:
            self._service = LocalFileService(policies)
            self._owns_service = True

        self._socket_timeout = socket_timeout_f
        self._port = 0
        self._listener = None
        self._accept_thread = None
        self._slots = []
        self._workers = []
        self._draining = False
        self._closed = False

        self._pool_lock = threading.Lock()
        self._pool_cond = threading.Condition(self._pool_lock)
        self._idle_slots = []

        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.settimeout(ACCEPT_POLL_INTERVAL_SECONDS)
                listener.bind((HOST, port))
                listener.listen(LISTEN_BACKLOG)
                bound_port = listener.getsockname()[1]
            except BaseException:
                try:
                    listener.close()
                except Exception:
                    pass
                raise

            self._listener = listener
            self._port = bound_port

            for _ in range(MAX_IN_FLIGHT_OPERATIONS):
                self._slots.append(_WorkerSlot())

            self._accept_thread = threading.Thread(
                target=self._accept_loop,
                name="drive-http-accept",
                daemon=False,
            )
            for i, slot in enumerate(self._slots):
                worker = threading.Thread(
                    target=self._worker_loop,
                    args=(slot,),
                    name="drive-http-worker-%d" % i,
                    daemon=False,
                )
                slot.thread = worker
                self._workers.append(worker)

            self._accept_thread.start()
            for worker in self._workers:
                worker.start()
        except BaseException:
            self._rollback_startup()
            raise

    def _rollback_startup(self):
        with self._pool_cond:
            self._draining = True
            self._pool_cond.notify_all()
        self._wake_listener()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        with self._pool_cond:
            for slot in self._slots:
                if slot.conn is not None:
                    try:
                        slot.conn.close()
                    except OSError:
                        pass
                    slot.conn = None
        if self._accept_thread is not None and self._accept_thread.is_alive():
            try:
                self._accept_thread.join(timeout=1.0)
            except BaseException:
                pass
        for worker in self._workers:
            if worker.is_alive():
                try:
                    worker.join(timeout=1.0)
                except BaseException:
                    pass
        try:
            self._service.close(timeout=5.0)
        except BaseException:
            pass

    # ----- public properties ----------------------------------------------

    @property
    def host(self):
        return HOST

    @property
    def port(self):
        return self._port

    @property
    def socket_timeout(self):
        return self._socket_timeout

    @property
    def service(self):
        return self._service

    def __repr__(self):
        return (
            "DriveHTTPAdapter(host=%r, port=%r, socket_timeout=%r, closed=%r)"
            % (HOST, self._port, self._socket_timeout, self._closed)
        )

    # ----- shutdown -------------------------------------------------------

    def close(self, *, timeout=DEFAULT_DRAIN_TIMEOUT_SECONDS):
        if type(timeout) is bool or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a finite non-negative number")
        timeout_f = float(timeout)
        if not math.isfinite(timeout_f) or timeout_f < 0.0:
            raise ValueError("timeout must be a finite non-negative number")

        if self._closed:
            return True

        deadline = time.monotonic() + timeout_f

        with self._pool_cond:
            self._draining = True
            self._pool_cond.notify_all()

        self._wake_listener()

        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass

        remaining = max(0.0, deadline - time.monotonic())
        try:
            service_closed = self._service.close(timeout=remaining)
        except BaseException:
            service_closed = False

        if self._accept_thread is not None:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                self._accept_thread.join(timeout=remaining)
            except BaseException:
                pass

        for worker in self._workers:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                worker.join(timeout=remaining)
            except BaseException:
                pass

        accept_done = self._accept_thread is None or not self._accept_thread.is_alive()
        workers_done = all(not worker.is_alive() for worker in self._workers)

        if service_closed and accept_done and workers_done:
            self._closed = True
            return True
        return False

    def _wake_listener(self):
        port = self._port
        if port <= 0:
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.setblocking(False)
                sock.connect_ex((HOST, port))
            finally:
                sock.close()
        except Exception:
            pass

    # ----- accept / worker loops ------------------------------------------

    def _accept_loop(self):
        while True:
            with self._pool_lock:
                if self._draining:
                    return
            try:
                conn, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                with self._pool_lock:
                    if self._draining:
                        return
                # transient; loop with listener timeout
                continue

            assigned = False
            with self._pool_cond:
                if self._draining:
                    try:
                        conn.close()
                    except OSError:
                        pass
                    continue
                if self._idle_slots:
                    slot = self._idle_slots.pop()
                    slot.conn = conn
                    self._pool_cond.notify_all()
                    assigned = True
            if not assigned:
                self._busy_reject(conn)

    def _worker_loop(self, slot):
        while True:
            with self._pool_cond:
                while slot.conn is None and not self._draining:
                    if slot not in self._idle_slots:
                        self._idle_slots.append(slot)
                    self._pool_cond.wait()
                if slot.conn is None:
                    try:
                        self._idle_slots.remove(slot)
                    except ValueError:
                        pass
                    return
                conn = slot.conn
                slot.conn = None
                try:
                    self._idle_slots.remove(slot)
                except ValueError:
                    pass
            try:
                self._serve(conn)
            except BaseException:
                pass
            finally:
                self._finalize_connection(conn)

    # ----- busy rejection -------------------------------------------------

    def _busy_reject(self, conn):
        busy_deadline = time.monotonic() + BUSY_REJECT_BUDGET_SECONDS
        total_read = 0

        remaining = busy_deadline - time.monotonic()
        if remaining > 0:
            try:
                conn.settimeout(remaining)
                chunk = conn.recv(MAX_BUSY_READ_BYTES)
                if chunk:
                    total_read += len(chunk)
            except (socket.timeout, OSError, ValueError):
                pass

        body = (
            b'{"ok":false,"error":{"code":"busy",'
            b'"outcome_uncertain":false,"retry_safe":true}}'
        )
        response = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            + body
        )
        self._send_with_deadline(conn, response, busy_deadline)

        try:
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass

        while total_read < MAX_BUSY_READ_BYTES:
            remaining = busy_deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                conn.settimeout(remaining)
                chunk = conn.recv(MAX_BUSY_READ_BYTES - total_read)
            except (socket.timeout, OSError, ValueError):
                break
            if not chunk:
                break
            total_read += len(chunk)

        try:
            conn.close()
        except OSError:
            pass

    # ----- bounded IO helpers --------------------------------------------

    def _send_with_deadline(self, conn, data, deadline):
        view = memoryview(data)
        while len(view) > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                conn.settimeout(remaining)
            except (OSError, ValueError):
                return False
            try:
                sent = conn.send(view)
            except (socket.timeout, OSError, ValueError):
                return False
            if sent <= 0:
                return False
            view = view[sent:]
        return True

    def _safe_write(self, conn, data):
        deadline = time.monotonic() + self._socket_timeout
        self._send_with_deadline(conn, data, deadline)

    def _safe_send_error(
        self, conn, status, code, outcome_uncertain, retry_safe
    ):
        try:
            body = json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": code,
                        "outcome_uncertain": bool(outcome_uncertain),
                        "retry_safe": bool(retry_safe),
                    },
                },
                separators=(",", ":"),
            ).encode("utf-8")
        except BaseException:
            body = (
                b'{"ok":false,"error":{"code":"unavailable",'
                b'"outcome_uncertain":false,"retry_safe":true}}'
            )
            status = 503

        status_text = _STATUS_TEXT.get(status, "Error")
        head = (
            ("HTTP/1.1 %d %s\r\n" % (status, status_text)).encode("ascii")
            + b"Content-Type: application/json\r\n"
            + b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            + b"Connection: close\r\n"
            + b"\r\n"
        )
        self._safe_write(conn, head + body)

    def _finalize_connection(self, conn):
        drain_deadline = time.monotonic() + POST_RESPONSE_DRAIN_SECONDS
        try:
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        total_drained = 0
        while total_drained < MAX_DRAIN_BYTES:
            remaining = drain_deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                conn.settimeout(remaining)
            except (OSError, ValueError):
                break
            try:
                chunk = conn.recv(_RECV_CHUNK)
            except (socket.timeout, OSError, ValueError):
                break
            if not chunk:
                break
            total_drained += len(chunk)
        try:
            conn.close()
        except OSError:
            pass

    # ----- request reading -----------------------------------------------

    def _read_request(self, conn):
        deadline = time.monotonic() + self._socket_timeout
        buf = bytearray()

        # Phase A: read until the header terminator CRLFCRLF.
        while True:
            idx = buf.find(b"\r\n\r\n")
            if idx >= 0:
                break
            if len(buf) > MAX_REQUEST_LINE_BYTES + MAX_HEADER_BLOCK_BYTES:
                raise _ReqErrorSignal(400, "invalid", False, False)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _TimeoutSignal()
            try:
                conn.settimeout(remaining)
            except (OSError, ValueError):
                raise _DisconnectSignal()
            try:
                chunk = conn.recv(_RECV_CHUNK)
            except socket.timeout:
                raise _TimeoutSignal()
            except OSError:
                raise _DisconnectSignal()
            if not chunk:
                raise _DisconnectSignal()
            buf.extend(chunk)

        header_end = idx + 4
        first_crlf = buf.find(b"\r\n")
        if first_crlf < 0 or first_crlf + 2 > header_end:
            raise _ReqErrorSignal(400, "invalid", False, False)
        if first_crlf + 2 > MAX_REQUEST_LINE_BYTES:
            raise _ReqErrorSignal(400, "invalid", False, False)
        if header_end - (first_crlf + 2) > MAX_HEADER_BLOCK_BYTES:
            raise _ReqErrorSignal(400, "invalid", False, False)

        request_line_bytes = bytes(buf[:first_crlf])
        header_block_bytes = bytes(buf[first_crlf + 2:header_end])

        target = self._parse_request_line(request_line_bytes)
        endpoint, query = self._parse_target(target)
        headers = self._parse_headers(header_block_bytes)
        content_length, token = self._check_headers(headers, endpoint)

        leftover = bytes(buf[header_end:])
        body = self._read_body(conn, leftover, content_length, deadline)

        return _ParsedRequest(
            endpoint=endpoint, query=query, token=token, body=body
        )

    def _parse_request_line(self, line):
        for b in line:
            if b < 0x20 or b > 0x7E:
                raise _ReqErrorSignal(400, "invalid", False, False)
        parts = line.split(b" ")
        if len(parts) != 3:
            raise _ReqErrorSignal(400, "invalid", False, False)
        method, target, version = parts
        if method != b"POST" or version != b"HTTP/1.1":
            raise _ReqErrorSignal(400, "invalid", False, False)
        if b"#" in target:
            raise _ReqErrorSignal(400, "invalid", False, False)
        return target

    def _parse_target(self, target):
        if target == b"/v1/list":
            return ("list", "")
        if target == b"/v1/find":
            return ("find", "")
        if target == b"/v1/read":
            return ("read", "")
        if target.startswith(b"/v1/save?"):
            query = target[len(b"/v1/save?"):]
            if not query:
                raise _ReqErrorSignal(400, "invalid", False, False)
            return ("save", query.decode("ascii"))
        raise _ReqErrorSignal(400, "invalid", False, False)

    def _parse_headers(self, header_block):
        lines = header_block.split(b"\r\n")
        if len(lines) < 2 or lines[-1] != b"" or lines[-2] != b"":
            raise _ReqErrorSignal(400, "invalid", False, False)
        lines = lines[:-2]
        if len(lines) > MAX_HEADER_COUNT:
            raise _ReqErrorSignal(400, "invalid", False, False)
        headers = {}
        for line in lines:
            if not line:
                raise _ReqErrorSignal(400, "invalid", False, False)
            name, value = _parse_header_line(line)
            headers.setdefault(name, []).append(value)
        return headers

    def _check_headers(self, headers, endpoint):
        # 1. Transfer-Encoding
        if b"transfer-encoding" in headers:
            raise _ReqErrorSignal(400, "invalid", False, False)

        # 2. Expect
        if b"expect" in headers:
            raise _ReqErrorSignal(400, "invalid", False, False)

        # 3. Host
        hosts = headers.get(b"host", [])
        if len(hosts) != 1 or not hosts[0]:
            raise _ReqErrorSignal(400, "invalid", False, False)

        # 4. Connection (optional)
        conns = headers.get(b"connection", [])
        if conns:
            if len(conns) != 1 or conns[0].lower() != b"close":
                raise _ReqErrorSignal(400, "invalid", False, False)

        # 5. Content-Length
        cls = headers.get(b"content-length", [])
        if len(cls) != 1:
            raise _ReqErrorSignal(400, "invalid", False, False)
        cl_raw = cls[0]
        if not cl_raw:
            raise _ReqErrorSignal(400, "invalid", False, False)
        for b in cl_raw:
            if b < 0x30 or b > 0x39:
                raise _ReqErrorSignal(400, "invalid", False, False)
        if len(cl_raw) > _MAX_CONTENT_LENGTH_DIGITS:
            raise _ReqErrorSignal(413, "too_large", False, False)
        content_length = int(cl_raw)

        # 6. Content-Type
        cts = headers.get(b"content-type", [])
        if len(cts) != 1:
            raise _ReqErrorSignal(400, "invalid", False, False)
        expected_ct = (
            b"application/octet-stream" if endpoint == "save" else b"application/json"
        )
        if cts[0].lower() != expected_ct:
            raise _ReqErrorSignal(400, "invalid", False, False)

        # 7. Lexical Authorization header framing
        auths = headers.get(b"authorization", [])
        if len(auths) != 1:
            raise _ReqErrorSignal(403, "denied", False, False)
        auth = auths[0]
        if not auth.startswith(b"Bearer "):
            raise _ReqErrorSignal(403, "denied", False, False)
        token_bytes = auth[7:]
        if len(token_bytes) < 32 or len(token_bytes) > 256:
            raise _ReqErrorSignal(403, "denied", False, False)
        for b in token_bytes:
            if b < 0x21 or b > 0x7E:
                raise _ReqErrorSignal(403, "denied", False, False)
        token = token_bytes.decode("ascii")

        # 8. Wire payload size gate
        if endpoint == "save":
            if content_length > MAX_SAVE_BODY_BYTES:
                raise _ReqErrorSignal(413, "too_large", False, False)
        else:
            if content_length > MAX_JSON_BODY_BYTES:
                raise _ReqErrorSignal(413, "too_large", False, False)

        return content_length, token

    def _read_body(self, conn, initial, content_length, deadline):
        if len(initial) > content_length:
            # Trailing bytes after the single framed request: reject.
            raise _ReqErrorSignal(400, "invalid", False, False)
        if len(initial) == content_length:
            return initial
        body = bytearray(initial)
        while len(body) < content_length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _TimeoutSignal()
            need = content_length - len(body)
            try:
                conn.settimeout(remaining)
            except (OSError, ValueError):
                raise _DisconnectSignal()
            try:
                chunk = conn.recv(min(_RECV_CHUNK, need))
            except socket.timeout:
                raise _TimeoutSignal()
            except OSError:
                raise _DisconnectSignal()
            if not chunk:
                raise _DisconnectSignal()
            body.extend(chunk)
            if len(body) > content_length:
                raise _ReqErrorSignal(400, "invalid", False, False)
        return bytes(body)

    # ----- serving --------------------------------------------------------

    def _serve(self, conn):
        try:
            request = self._read_request(conn)
        except _ReqErrorSignal as sig:
            self._safe_send_error(
                conn, sig.status, sig.code, sig.outcome_uncertain, sig.retry_safe
            )
            return
        except _TimeoutSignal:
            self._safe_send_error(conn, 504, "timeout", False, True)
            return
        except _DisconnectSignal:
            return
        except (RecursionError, ValueError, UnicodeError):
            # Parser must never kill a worker; emit best-effort 400.
            self._safe_send_error(conn, 400, "invalid", False, False)
            return
        except BaseException:
            self._safe_send_error(conn, 400, "invalid", False, False)
            return

        self._dispatch(conn, request)

    def _dispatch(self, conn, request):
        endpoint = request.endpoint
        token = request.token
        try:
            if endpoint == "list":
                result = self._call_list(token, request.body)
            elif endpoint == "find":
                result = self._call_find(token, request.body)
            elif endpoint == "read":
                result = self._call_read(token, request.body)
            else:  # save
                result = self._call_save(token, request.query, request.body)
        except ServiceError as exc:
            status = _SERVICE_ERROR_STATUS.get(exc.code, 503)
            self._safe_send_error(
                conn, status, exc.code, exc.outcome_uncertain, exc.retry_safe
            )
            return
        except BaseException:
            if endpoint == "save":
                self._safe_send_error(conn, 503, "unavailable", True, False)
            else:
                self._safe_send_error(conn, 503, "unavailable", False, True)
            return

        if endpoint == "read":
            self._send_read_response(conn, result)
        else:
            self._send_json_response(conn, result, endpoint)

    # ----- auth-first public delegation ----------------------------------

    def _extract_candidate_source_id(self, obj):
        if isinstance(obj, dict):
            src = obj.get("source_id")
            if isinstance(src, str):
                return src
        return None

    def _validate_json_payload(self, obj, endpoint):
        rules = _JSON_KEY_RULES.get(endpoint)
        if rules is None:
            return False
        required, optional = rules
        keys = set(obj.keys())
        if not required.issubset(keys):
            return False
        if not keys.issubset(required | optional):
            return False
        if endpoint == "list":
            if "name_contains" in obj and obj["name_contains"] is None:
                return False
        return True

    def _call_list(self, token, body):
        obj = None
        try:
            parsed = _parse_json_strict(body)
            if isinstance(parsed, dict):
                obj = parsed
        except (ValueError, UnicodeError, RecursionError):
            obj = None

        candidate_source_id = self._extract_candidate_source_id(obj)

        if obj is not None and self._validate_json_payload(obj, "list"):
            return self._service.list(
                token,
                obj["source_id"],
                obj["file_id"],
                limit=obj["limit"],
                offset=obj["offset"],
                name_contains=obj.get("name_contains"),
            )
        return self._service.list(token, candidate_source_id, None)

    def _call_find(self, token, body):
        obj = None
        try:
            parsed = _parse_json_strict(body)
            if isinstance(parsed, dict):
                obj = parsed
        except (ValueError, UnicodeError, RecursionError):
            obj = None

        candidate_source_id = self._extract_candidate_source_id(obj)

        if obj is not None and self._validate_json_payload(obj, "find"):
            return self._service.find(
                token,
                obj["source_id"],
                obj["file_id"],
                name_contains=obj["name_contains"],
                limit=obj["limit"],
                max_entries=obj["max_entries"],
                max_depth=obj["max_depth"],
            )
        return self._service.find(
            token, candidate_source_id, None, name_contains="a"
        )

    def _call_read(self, token, body):
        obj = None
        try:
            parsed = _parse_json_strict(body)
            if isinstance(parsed, dict):
                obj = parsed
        except (ValueError, UnicodeError, RecursionError):
            obj = None

        candidate_source_id = self._extract_candidate_source_id(obj)

        if obj is not None and self._validate_json_payload(obj, "read"):
            return self._service.read(
                token,
                obj["source_id"],
                obj["file_id"],
                offset=obj["offset"],
                length=obj["length"],
            )
        return self._service.read(token, candidate_source_id, None)

    def _call_save(self, token, query, body):
        candidate_source_id = None
        pairs = None
        try:
            pairs = urllib.parse.parse_qsl(
                query,
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
            )
        except (ValueError, UnicodeError):
            pairs = None

        if pairs is not None:
            source_values = [value for key, value in pairs if key == "source_id"]
            if len(source_values) == 1:
                candidate_source_id = source_values[0]

            keys = [key for key, _ in pairs]
            if len(pairs) == 4 and set(keys) == _SAVE_QUERY_KEYS:
                q = dict(pairs)
                ow = q["overwrite"]
                cp = q["create_parents"]
                if ow in ("true", "false") and cp in ("true", "false"):
                    return self._service.save(
                        token,
                        q["source_id"],
                        q["file_id"],
                        body,
                        overwrite=(ow == "true"),
                        create_parents=(cp == "true"),
                    )

        return self._service.save(token, candidate_source_id, None, b"")

    # ----- response emission ---------------------------------------------

    def _send_json_response(self, conn, result, endpoint):
        try:
            raw = json.dumps(
                {"ok": True, "result": result},
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except BaseException:
            if endpoint == "save":
                self._safe_send_error(conn, 503, "unavailable", True, False)
            else:
                self._safe_send_error(conn, 503, "unavailable", False, True)
            return

        if len(raw) > MAX_JSON_BODY_BYTES:
            if endpoint == "save":
                self._safe_send_error(conn, 413, "too_large", True, False)
            else:
                self._safe_send_error(conn, 413, "too_large", False, False)
            return

        head = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(raw)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        self._safe_write(conn, head + raw)

    def _send_read_response(self, conn, res):
        data = getattr(res, "data", None)
        offset = getattr(res, "offset", None)
        observed_size = getattr(res, "observed_size", None)
        observed_mtime_ns = getattr(res, "observed_mtime_ns", None)
        eof_observed = getattr(res, "eof_observed", None)

        if type(data) is not bytes or len(data) > MAX_READ_BODY_BYTES:
            self._safe_send_error(conn, 503, "unavailable", False, True)
            return
        if type(offset) is not int or offset < 0:
            self._safe_send_error(conn, 503, "unavailable", False, True)
            return
        if type(observed_size) is not int or observed_size < 0:
            self._safe_send_error(conn, 503, "unavailable", False, True)
            return
        if type(observed_mtime_ns) is not int or observed_mtime_ns < 0:
            self._safe_send_error(conn, 503, "unavailable", False, True)
            return
        if type(eof_observed) is not bool:
            self._safe_send_error(conn, 503, "unavailable", False, True)
            return

        head = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/octet-stream\r\n"
            b"Content-Length: " + str(len(data)).encode("ascii") + b"\r\n"
            b"X-Drive-Offset: " + str(offset).encode("ascii") + b"\r\n"
            b"X-Drive-Observed-Size: " + str(observed_size).encode("ascii") + b"\r\n"
            b"X-Drive-Observed-Mtime-Ns: "
            + str(observed_mtime_ns).encode("ascii")
            + b"\r\n"
            b"X-Drive-EOF-Observed: "
            + (b"true" if eof_observed else b"false")
            + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        self._safe_write(conn, head + data)
