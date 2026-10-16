path = "drive_tool/http_adapter.py"
src = open(path, encoding="utf-8").read()
done = []

def sub(name, old, new, count=1):
    global src
    n = src.count(old)
    assert n == count, "hunk %s: expected %d, found %d" % (name, count, n)
    src = src.replace(old, new, count)
    done.append(name)

# 1. __all__ additions
sub("all", '''    "BUSY_REJECT_BUDGET_SECONDS",
    "MAX_BUSY_READ_BYTES",''', '''    "BUSY_REJECT_BUDGET_SECONDS",
    "BUSY_PRE_READ_BUDGET_SECONDS",
    "BUSY_WRITE_RESERVE_SECONDS",
    "BUSY_POST_DRAIN_BUDGET_SECONDS",
    "MAX_BUSY_READ_BYTES",''')

# 2. precise constants
sub("constants", '''BUSY_REJECT_BUDGET_SECONDS = 0.05
MAX_BUSY_READ_BYTES = 16384''', '''BUSY_REJECT_BUDGET_SECONDS = 0.050
BUSY_PRE_READ_BUDGET_SECONDS = 0.010
BUSY_WRITE_RESERVE_SECONDS = 0.020
BUSY_POST_DRAIN_BUDGET_SECONDS = 0.020
MAX_BUSY_READ_BYTES = 16384''')

# 3. phased _busy_reject
sub("busy_reject", '''    def _busy_reject(self, conn):
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

        body = (''', '''    def _busy_reject(self, conn):
        now = time.monotonic()
        busy_deadline = now + BUSY_REJECT_BUDGET_SECONDS
        total_read = 0

        # Phase 1: bounded pre-read. Must not consume the reserved write slice.
        pre_read_deadline = min(
            now + BUSY_PRE_READ_BUDGET_SECONDS,
            busy_deadline - BUSY_WRITE_RESERVE_SECONDS,
        )
        remaining = pre_read_deadline - time.monotonic()
        if remaining > 0:
            try:
                conn.settimeout(remaining)
                chunk = conn.recv(MAX_BUSY_READ_BYTES)
                if chunk:
                    total_read += len(chunk)
            except (socket.timeout, OSError, ValueError):
                pass

        # Phase 2: reserved write window inside the same 50ms outer ceiling.
        body = (''')

sub("drain", '''        while total_read < MAX_BUSY_READ_BYTES:
            remaining = busy_deadline - time.monotonic()
            if remaining <= 0:
                break''', '''        # Phase 3: bounded post-write drain; never exceeds 16 KiB or outer deadline.
        drain_deadline = min(
            busy_deadline,
            time.monotonic() + BUSY_POST_DRAIN_BUDGET_SECONDS,
        )
        while total_read < MAX_BUSY_READ_BYTES:
            remaining = drain_deadline - time.monotonic()
            if remaining <= 0:
                break''')

open(path, "w", encoding="utf-8").write(src)
print("applied:", done)
