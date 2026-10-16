# d087 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/37dd9260-a518-4948-bf70-2cb664d11a26
- model: deepseek (deepthink on, search off)
- finished: 2026-10-16T00:41:56Z

## Question

DeepSeek, minimal caller-deadline lock acquisition correction and deterministic regression per D087. Director explicit single-budget/no-unbounded-lock requirement; Gemini noted gap. Preserve onceonlyclose/FDownership, no auth/testcontract changes. Patch only, honest TESTS_NOT_RUN. No redesign/merge/deploy.

(input files: Dolesh-avkalan/drive-tool:tasks/d087-close-lock-budget.txt@9f5a28140f50b3a41b23127548490ba04a5462a8)

## Answer

```diff
--- a/drive_tool/http_adapter.py
+++ b/drive_tool/http_adapter.py
@@
     def close(self, *, timeout=DEFAULT_DRAIN_TIMEOUT_SECONDS):
         if type(timeout) is bool or not isinstance(timeout, (int, float)):
             raise ValueError("timeout must be a finite non-negative number")
         timeout_f = float(timeout)
         if not math.isfinite(timeout_f) or timeout_f < 0.0:
             raise ValueError("timeout must be a finite non-negative number")
 
-        with self._close_lock:
-            if self._closed:
-                return True
-
-            deadline = time.monotonic() + timeout_f
-
-            with self._pool_cond:
-                should_close_listener = not self._listener_closed
-                self._listener_closed = True
-                self._draining = True
-                for slot in self._slots:
-                    if slot.conn is not None:
-                        try:
-                            slot.conn.close()
-                        except OSError:
-                            pass
-                        slot.conn = None
-                self._pool_cond.notify_all()
-
-            if should_close_listener:
-                self._wake_listener()
-                if self._listener is not None:
-                    try:
-                        self._listener.close()
-                    except OSError:
-                        pass
-
-            remaining = max(0.0, deadline - time.monotonic())
-            try:
-                service_closed = self._service.close(timeout=remaining)
-            except BaseException:
-                service_closed = False
-
-            if self._accept_thread is not None:
-                remaining = max(0.0, deadline - time.monotonic())
-                try:
-                    self._accept_thread.join(timeout=remaining)
-                except BaseException:
-                    pass
-
-            for worker in self._workers:
-                remaining = max(0.0, deadline - time.monotonic())
-                try:
-                    worker.join(timeout=remaining)
-                except BaseException:
-                    pass
-
-            accept_done = self._accept_thread is None or not self._accept_thread.is_alive()
-            workers_done = all(not worker.is_alive() for worker in self._workers)
-
-            if service_closed and accept_done and workers_done:
-                self._closed = True
-                return True
-            return False
+        deadline = time.monotonic() + timeout_f
+        remaining = deadline - time.monotonic()
+        if remaining <= 0.0:
+            acquired = self._close_lock.acquire(blocking=False)
+        else:
+            acquired = self._close_lock.acquire(timeout=remaining)
+        if not acquired:
+            return False
+
+        try:
+            if self._closed:
+                return True
+
+            with self._pool_cond:
+                should_close_listener = not self._listener_closed
+                self._listener_closed = True
+                self._draining = True
+                for slot in self._slots:
+                    if slot.conn is not None:
+                        try:
+                            slot.conn.close()
+                        except OSError:
+                            pass
+                        slot.conn = None
+                self._pool_cond.notify_all()
+
+            if should_close_listener:
+                self._wake_listener()
+                if self._listener is not None:
+                    try:
+                        self._listener.close()
+                    except OSError:
+                        pass
+
+            remaining = max(0.0, deadline - time.monotonic())
+            try:
+                service_closed = self._service.close(timeout=remaining)
+            except BaseException:
+                service_closed = False
+
+            if self._accept_thread is not None:
+                remaining = max(0.0, deadline - time.monotonic())
+                try:
+                    self._accept_thread.join(timeout=remaining)
+                except BaseException:
+                    pass
+
+            for worker in self._workers:
+                remaining = max(0.0, deadline - time.monotonic())
+                try:
+                    worker.join(timeout=remaining)
+                except BaseException:
+                    pass
+
+            accept_done = self._accept_thread is None or not self._accept_thread.is_alive()
+            workers_done = all(not worker.is_alive() for worker in self._workers)
+
+            if service_closed and accept_done and workers_done:
+                self._closed = True
+                return True
+            return False
+        finally:
+            self._close_lock.release()
```

```diff
--- /dev/null
+++ b/tests/test_d087_close_lock_budget.py
@@ -0,0 +1,62 @@
+import threading
+import time
+
+from drive_tool.http_adapter import DriveHTTPAdapter
+
+
+class _BlockingService:
+    def __init__(self):
+        self.entered = threading.Event()
+        self.release = threading.Event()
+        self.close_calls = 0
+
+    def close(self, *, timeout):
+        self.close_calls += 1
+        self.entered.set()
+        self.release.wait(timeout=5.0)
+        return True
+
+
+def _bare_adapter(service):
+    adapter = DriveHTTPAdapter.__new__(DriveHTTPAdapter)
+    adapter._close_lock = threading.Lock()
+    adapter._closed = False
+    adapter._listener_closed = False
+    adapter._draining = False
+    adapter._pool_cond = threading.Condition()
+    adapter._slots = []
+    adapter._listener = None
+    adapter._accept_thread = None
+    adapter._workers = []
+    adapter._service = service
+    adapter._port = 0
+    return adapter
+
+
+def test_d087_second_close_honors_deadline_while_first_holds_lock():
+    service = _BlockingService()
+    adapter = _bare_adapter(service)
+
+    first_result = []
+    first = threading.Thread(
+        target=lambda: first_result.append(adapter.close(timeout=5.0)),
+        daemon=True,
+    )
+    first.start()
+
+    assert service.entered.wait(1.0), "first close did not reach service lease"
+
+    started = time.monotonic()
+    second_result = adapter.close(timeout=0.05)
+    elapsed = time.monotonic() - started
+
+    assert second_result is False
+    assert elapsed < 0.05 + 0.10, elapsed
+    assert service.close_calls == 1
+
+    service.release.set()
+    first.join(timeout=1.0)
+    assert not first.is_alive()
+    assert first_result == [True]
+    assert adapter._closed is True
+    assert service.close_calls == 1
```

TESTS_NOT_RUN: patch authored only; no production/test execution performed. No auth/testcontract changes. No redesign/merge/deploy.
