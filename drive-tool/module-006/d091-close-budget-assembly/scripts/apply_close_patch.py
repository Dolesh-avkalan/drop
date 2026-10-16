path = "drive_tool/http_adapter.py"
src = open(path, encoding="utf-8").read()

START = "    def close(self, *, timeout=DEFAULT_DRAIN_TIMEOUT_SECONDS):\n"
END = "    def _wake_listener(self):\n"

NEW_CLOSE = '''    def close(self, *, timeout=DEFAULT_DRAIN_TIMEOUT_SECONDS):
        if type(timeout) is bool or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a finite non-negative number")
        timeout_f = float(timeout)
        if not math.isfinite(timeout_f) or timeout_f < 0.0:
            raise ValueError("timeout must be a finite non-negative number")

        deadline = time.monotonic() + timeout_f
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            acquired = self._close_lock.acquire(blocking=False)
        else:
            acquired = self._close_lock.acquire(timeout=remaining)
        if not acquired:
            return False

        try:
            if self._closed:
                return True

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
        finally:
            self._close_lock.release()

'''

i = src.index(START)
j = src.index(END, i)
old = src[i:j]
assert "with self._close_lock:" in old and "return False\n" in old, "unexpected old close()"
assert "finally:" not in old
src = src[:i] + NEW_CLOSE + src[j:]
open(path, "w", encoding="utf-8").write(src)
print("close() replaced; %d -> %d chars" % (len(src) - len(NEW_CLOSE) + len(old), len(src)))
