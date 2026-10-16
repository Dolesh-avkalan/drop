"""Base adapter + ONLY the D094 phase constants (so the module imports), with the
original monolithic _busy_reject left untouched: the oldfail configuration."""
path = "drive_tool/http_adapter.py"
s = open(path, encoding="utf-8").read()
old = '''BUSY_REJECT_BUDGET_SECONDS = 0.05
MAX_BUSY_READ_BYTES = 16384'''
new = '''BUSY_REJECT_BUDGET_SECONDS = 0.050
BUSY_PRE_READ_BUDGET_SECONDS = 0.010
BUSY_WRITE_RESERVE_SECONDS = 0.020
BUSY_POST_DRAIN_BUDGET_SECONDS = 0.020
MAX_BUSY_READ_BYTES = 16384'''
assert s.count(old) == 1
s = s.replace(old, new, 1)
s = s.replace('''    "BUSY_REJECT_BUDGET_SECONDS",
    "MAX_BUSY_READ_BYTES",''', '''    "BUSY_REJECT_BUDGET_SECONDS",
    "BUSY_PRE_READ_BUDGET_SECONDS",
    "BUSY_WRITE_RESERVE_SECONDS",
    "BUSY_POST_DRAIN_BUDGET_SECONDS",
    "MAX_BUSY_READ_BYTES",''', 1)
open(path, "w", encoding="utf-8").write(s)
print("constants-only base prepared (monolithic _busy_reject retained)")
