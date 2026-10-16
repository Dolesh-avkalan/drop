import sys

path = "drive_tool/http_adapter.py"
src = open(path, encoding="utf-8").read()
orig = src
applied = []


def sub(name, old, new, count=1):
    global src
    n = src.count(old)
    assert n == count, "hunk %s: expected %d occurrence(s), found %d" % (name, count, n)
    src = src.replace(old, new, count)
    applied.append(name)


# --- Hunk A: new lifecycle attributes -------------------------------------
sub("A-attrs",
"""        self._draining = False
        self._closed = False

        self._pool_lock = threading.Lock()
        self._pool_cond = threading.Condition(self._pool_lock)
        self._idle_slots = []
""",
"""        self._draining = False
        self._closed = False
        self._listener_closed = False

        self._pool_lock = threading.Lock()
        self._pool_cond = threading.Condition(self._pool_lock)
        self._idle_slots = []
        self._close_lock = threading.Lock()
""")

# --- Hunk B: pre-populate idle slots; workers before accept ---------------
sub("B-idle-slots",
"""            for _ in range(MAX_IN_FLIGHT_OPERATIONS):
                self._slots.append(_WorkerSlot())

            self._accept_thread = threading.Thread(
""",
"""            for _ in range(MAX_IN_FLIGHT_OPERATIONS):
                self._slots.append(_WorkerSlot())

            with self._pool_cond:
                self._idle_slots.extend(self._slots)

            self._accept_thread = threading.Thread(
""")

sub("B-start-order",
"""            self._accept_thread.start()
            for worker in self._workers:
                worker.start()
""",
"""            for worker in self._workers:
                worker.start()
            self._accept_thread.start()
""")

# --- Hunk C: serialized, once-only, handoff-closing close() ---------------
OLD_CLOSE = """        if self._closed:
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
"""
NEW_CLOSE = """        with self._close_lock:
            if self._closed:
                return True

            deadline = time.monotonic() + timeout_f

            with self._pool_cond:
                should_close_listener = not self._listener_closed
                self._listener_closed = True
                self._draining = True
                for slot in self._slots:
                    if slot.conn is not None:
                        try:
                            slot.conn.close()
                        except OSError:
                            pass
                        slot.conn = None
                self._pool_cond.notify_all()

            if should_close_listener:
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
"""
sub("C-close", OLD_CLOSE, NEW_CLOSE)

# --- Hunk D: incremental partial-header bounds ----------------------------
sub("D-phaseA-call",
"""        while True:
            idx = buf.find(b"\\r\\n\\r\\n")
            if idx >= 0:
                break
            if len(buf) > MAX_REQUEST_LINE_BYTES + MAX_HEADER_BLOCK_BYTES:
""",
"""        while True:
            idx = buf.find(b"\\r\\n\\r\\n")
            if idx >= 0:
                break
            self._check_partial_header_block(buf)
            if len(buf) > MAX_REQUEST_LINE_BYTES + MAX_HEADER_BLOCK_BYTES:
""")

sub("D-new-method",
"""    def _parse_request_line(self, line):
""",
"""    def _check_partial_header_block(self, buf):
        for i, byte in enumerate(buf):
            if byte == 0x0A:
                if i == 0 or buf[i - 1] != 0x0D:
                    raise _ReqErrorSignal(400, "invalid", False, False)
            elif byte == 0x0D:
                if i + 1 < len(buf) and buf[i + 1] != 0x0A:
                    raise _ReqErrorSignal(400, "invalid", False, False)

        first_crlf = buf.find(b"\\r\\n")
        if first_crlf < 0:
            end = len(buf)
            if end and buf[-1] == 0x0D:
                end -= 1
            for b in buf[:end]:
                if b < 0x20 or b > 0x7E:
                    raise _ReqErrorSignal(400, "invalid", False, False)
            if buf.endswith(b"\\r"):
                if len(buf) > MAX_REQUEST_LINE_BYTES - 1:
                    raise _ReqErrorSignal(400, "invalid", False, False)
            else:
                if len(buf) > MAX_REQUEST_LINE_BYTES - 2:
                    raise _ReqErrorSignal(400, "invalid", False, False)
            return

        if first_crlf + 2 > MAX_REQUEST_LINE_BYTES:
            raise _ReqErrorSignal(400, "invalid", False, False)
        target = self._parse_request_line(bytes(buf[:first_crlf]))
        self._parse_target(target)
        if len(buf) - (first_crlf + 2) > MAX_HEADER_BLOCK_BYTES:
            raise _ReqErrorSignal(400, "invalid", False, False)
        if buf.count(b"\\r\\n", first_crlf + 2, len(buf)) > MAX_HEADER_COUNT + 1:
            raise _ReqErrorSignal(400, "invalid", False, False)

    def _parse_request_line(self, line):
""")

# --- Hunk E: Content-Length normalisation / deferred size gate ------------
sub("E-content-length",
"""        if len(cl_raw) > _MAX_CONTENT_LENGTH_DIGITS:
            raise _ReqErrorSignal(413, "too_large", False, False)
        content_length = int(cl_raw)
""",
"""        cl_norm = cl_raw.lstrip(b"0") or b"0"
        if len(cl_norm) > _MAX_CONTENT_LENGTH_DIGITS:
            content_length = MAX_SAVE_BODY_BYTES + 1
        else:
            content_length = int(cl_norm)
""")

# --- Hunk F: drop the unreachable post-recv excess check ------------------
sub("F-read-body",
"""            body.extend(chunk)
            if len(body) > content_length:
                raise _ReqErrorSignal(400, "invalid", False, False)
        return bytes(body)
""",
"""            body.extend(chunk)
        return bytes(body)
""")

open(path, "w", encoding="utf-8").write(src)
print("applied hunks:", applied)
print("bytes: %d -> %d" % (len(orig), len(src)))
