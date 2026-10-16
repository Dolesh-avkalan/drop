"""Live check harness for drive_tool.serve (dt05b).

Runs the launcher as a child process of THIS foreground program (no shell
background jobs), performs the DriveClient list/read, then sends SIGTERM and
records the exit code. Two variants are run:

  LITERAL   - exactly as specified: token "secret123".
  COMPLIANT - the same procedure with a >=32-char token (see notes), to show
              whether the launcher itself works live.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time

REPO = "/scratch/work/drive-tool"
sys.path.insert(0, REPO)
PORT = 18765
TOKEN_LITERAL = "secret123"
TOKEN_COMPLIANT = "A" * 40  # 40 visible ASCII chars, satisfies the 32..256 rule

out_lines = []


def log(msg=""):
    print(msg)
    out_lines.append(msg)


def run_hash_token(token):
    """echo -n <token> | python3 -m drive_tool.serve --hash-token"""
    proc = subprocess.run(
        [sys.executable, "-m", "drive_tool.serve", "--hash-token"],
        input=token.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO,
    )
    return proc.returncode, proc.stdout.decode().strip(), proc.stderr.decode()


def wait_listening(proc, timeout=15.0):
    """Read the launcher's stderr until the listening line appears."""
    deadline = time.monotonic() + timeout
    buf = b""
    import select
    fd = proc.stderr.fileno()
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            buf += chunk
            if b"listening" in buf:
                return True, buf.decode(errors="replace")
        if proc.poll() is not None:
            break
    return False, buf.decode(errors="replace")


def start_server(cfg_path):
    return subprocess.Popen(
        [sys.executable, "-m", "drive_tool.serve", "--config", cfg_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO,
    )


def port_open(port, timeout=0.3):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def make_env(tag):
    tmp = tempfile.mkdtemp(prefix="dt05b-%s-" % tag)
    root = os.path.join(tmp, "root")
    os.mkdir(root)
    with open(os.path.join(root, "hello.txt"), "wb") as fh:
        fh.write(b"hello from live check")
    return tmp, root


def run_variant(label, token):
    log("")
    log("===== VARIANT: %s (token=%r, len=%d) =====" % (label, token, len(token)))
    tmp, root = make_env(label)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()

    # --- verify --hash-token ---
    rc, printed, herr = run_hash_token(token)
    log("--hash-token rc=%d printed=%s" % (rc, printed))
    log("sha256(%r)         = %s" % (token, digest))
    log("hash matches hashlib: %s" % (printed == digest))

    # --- config ---
    cfg = {
        "port": PORT,
        "agents": [
            {
                "agent_id": "alice",
                "token_sha256": printed,
                "grants": [
                    {
                        "alias": "work",
                        "root": root,
                        "operations": ["list", "find", "read", "save"],
                    }
                ],
            }
        ],
    }
    cfg_path = os.path.join(tmp, "cfg.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    os.chmod(cfg_path, 0o600)
    log("config written: %s (mode %o)" % (cfg_path, os.stat(cfg_path).st_mode & 0o777))

    # --- start server (child of this foreground program) ---
    proc = start_server(cfg_path)
    ready, srv_err = wait_listening(proc)
    log("launcher stderr: %s" % srv_err.strip())
    log("listening: %s ; port_open=%s" % (ready, port_open(PORT)))

    result = {"variant": label, "client_ok": False, "list": None, "read": None,
              "error": None, "returncode": None}

    # --- client list + read ---
    try:
        from drive_tool.service_client import DriveClient

        client = DriveClient(port=PORT, token=token)
        listing = client.list("work", "root")
        result["list"] = listing
        log("list('work','root') -> keys=%s items=%d"
            % (sorted(listing.keys()), len(listing.get("items", []))))
        reply = client.read("work", "p/hello.txt", offset=0, length=64)
        result["read"] = reply.data.decode(errors="replace")
        result["client_ok"] = True
        log("read('work','p/hello.txt') -> data=%r eof=%s"
            % (reply.data, reply.eof_observed))
    except Exception as exc:  # noqa: BLE001
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        log("CLIENT ERROR: %s: %s" % (type(exc).__name__, exc))

    # --- SIGTERM ---
    proc.send_signal(signal.SIGTERM)
    try:
        rc = proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = proc.wait()
    result["returncode"] = rc
    log("SIGTERM sent; process exit code = %d" % rc)
    return result


def main():
    log("drive_tool.serve live check")
    log("uid=%d user=%s" % (os.getuid(), os.environ.get("USER", "?")))
    log("repo=%s" % REPO)

    results = []
    results.append(run_variant("LITERAL", TOKEN_LITERAL))
    results.append(run_variant("COMPLIANT", TOKEN_COMPLIANT))

    log("")
    log("===== SUMMARY =====")
    for r in results:
        ok = r["client_ok"] and r["returncode"] == 0
        log("%-10s client_ok=%-5s exit=%s %s"
            % (r["variant"], r["client_ok"], r["returncode"],
               ("PASS" if ok else "FAIL")))
        if r["error"]:
            log("           error: %s" % r["error"])

    with open("/scratch/work/live.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(out_lines) + "\n")


if __name__ == "__main__":
    main()
