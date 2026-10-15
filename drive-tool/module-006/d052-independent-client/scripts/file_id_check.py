"""D052 finding #2 check: does the client enforce the director's file_id rule?

Director interpretation (d052 brief): every non-root file_id MUST start with
"p/" and be canonical relative POSIX after the prefix; root allowed only for
list/find. This script shows which file_ids the client accepts (reaches the
network) versus rejects (ValueError/TypeError before network).
"""
import sys, os
sys.path.insert(0, os.environ.get("D052_TREE", "/scratch/work/candidate"))
from drive_tool.service_client import DriveClient, DriveClientError

class Probe(DriveClient):
    def _open(self):
        raise RuntimeError("REACHED_NETWORK")  # reached => validation passed

c = Probe(port=1, token="x" * 40)

def check(label, fn):
    try:
        fn()
        print(f"{label:38s} -> accepted (no error)")
    except (TypeError, ValueError) as e:
        print(f"{label:38s} -> REJECTED pre-network ({type(e).__name__})")
    except DriveClientError:
        print(f"{label:38s} -> ACCEPTED (reached network; wrapped)")

print("== read (non-root required) ==")
for fid in ["p/a.txt", "p/dir/f.txt", "a.txt", "docs/x", "p", "p/", "/abs", "p/../x", "p/./x", "root", "p\\x"]:
    check(f"read file_id={fid!r}", lambda fid=fid: c.read("src", fid))
print("== save (non-root required) ==")
for fid in ["a.txt", "p/a.txt", "root"]:
    check(f"save file_id={fid!r}", lambda fid=fid: c.save("src", fid, b"x"))
print("== list (root allowed) ==")
for fid in ["root", "a.txt", "p/a.txt"]:
    check(f"list file_id={fid!r}", lambda fid=fid: c.list("src", fid))
print()
print("EXPECTED under director rule: non-root ids not starting 'p/' (a.txt, docs/x, p) -> REJECTED pre-network.")
