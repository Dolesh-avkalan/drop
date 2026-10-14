#!/usr/bin/env python3
"""Raw-kernel open probe behind MODULE-003-REVIEW-FIXES.md section 3.

Uses the exact component flags the revised adapter uses (no O_DIRECTORY) and
reports real kernel behaviour. Nothing is simulated.
"""
import errno, os, shutil, stat, tempfile

FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)

def probe():
    base = tempfile.mkdtemp(prefix="raw_probe_")
    try:
        d = os.path.join(base, "d"); os.mkdir(d)
        link = os.path.join(base, "link"); os.symlink(d, link)
        broken = os.path.join(base, "broken"); os.symlink(os.path.join(base, "nope"), broken)
        def attempt(path):
            try:
                fd = os.open(path, FLAGS)
            except OSError as e:
                return f"raised {errno.errorcode.get(e.errno, e.errno)}"
            try:
                return f"opened, mode={oct(os.fstat(fd).st_mode)}"
            finally:
                os.close(fd)
        print(f"flags O_NOFOLLOW={bool(FLAGS & os.O_NOFOLLOW)} O_DIRECTORY={bool(FLAGS & os.O_DIRECTORY)}")
        print(f"symlink_to_dir : {attempt(link)}")
        print(f"broken_symlink : {attempt(broken)}")
        print(f"real_dir       : {attempt(d)}")
        print(f"root_slash     : {attempt('/')}")
        fifo = os.path.join(base, "fifo"); os.mkfifo(fifo)
        print(f"fifo           : {attempt(fifo)}")
        rf = os.path.join(base, "f.txt"); open(rf, "wb").write(b"x")
        print(f"regular_file   : {attempt(rf)}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

if __name__ == "__main__":
    probe()
