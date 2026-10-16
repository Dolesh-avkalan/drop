# dt07c-grok (grok)

- status: done
- chat: https://grok.com/c/8b1f7c3c-dc40-4461-9435-e74ee5ac9ca3?rid=cd279bb4-1ecb-4c3a-b0d4-51fa5beb3279
- model: expert (thinking: -)
- finished: 2026-10-16T12:57:55Z

## Question

Grok, I need you to add a shared file drive to our browser host. Attached: hostd.py (the host's API server), install.sh (its idempotent installer, runs as root on every deploy), and dt06-relay-drive.md which contains the new browser_host/drive.py wrapper (use it, do not change it).

browser_host/drive.py (the shared wrapper, used by relay.py and hostd.py):
- Settings from the environment: BH_DRIVE_PORT (default 8940), BH_DRIVE_TOKEN (no default), BH_DRIVE_TOOL (path of the drive-tool checkout, default /opt/drive-tool; add it to sys.path lazily before importing drive_tool.service_client). Source alias is the constant ALIAS = "projects".
- class DriveError(Exception); every DriveClientError or connection problem becomes DriveError(<code>) whose text never contains the token.
- enabled() -> bool: True when BH_DRIVE_TOKEN is set.
- parse_ref(ref) -> str or None: "drive:proj/notes/a.md" -> "proj/notes/a.md"; anything not starting with "drive:" -> None. Validate the path: relative, no leading "/", no "..", no empty parts, each part matches [A-Za-z0-9._ -]{1,128} and is not "." ; invalid -> DriveError("bad drive path").
- file_id(path) -> "root" for "" else "p/" + path.
- read_text(path, max_bytes=1048576) -> str: read with offset/length chunks until EOF or max_bytes, decode UTF-8 with errors="replace".
- save_text(path, text, overwrite=True) -> None: UTF-8 bytes, create_parents=True; over 1 MiB -> DriveError("too_large").
- list_dir(path="", limit=200) -> list of entries (as returned by the service); find(name, path="", limit=50) -> list of entries.
- append_line(path, line) -> None: read the file (missing file = empty), add line + "\n", save with overwrite.
- One DriveClient(port=..., token=..., timeout=10.0) per call.

1. install.sh (keep its style; idempotent; never print secrets):
- clone or update https://github.com/Dolesh-avkalan/drive-tool into /opt/drive-tool at ref ${BH_DRIVE_REF:-main} (git fetch + checkout, no local changes).
- data dir /var/lib/agent-drive/projects owned by bh:bh, mode 750.
- if BH_DRIVE_TOKEN is missing from $ENVF, append one generated like BH_TOKEN (python3 secrets.token_urlsafe(32)); then source $ENVF as the script already does.
- write /etc/drive-tool/config.json (dir 750 root:bh, file 640 root:bh — the launcher refuses group/other-writable files) with port 8940 and one agent "hub" whose token_sha256 is the sha256 hex of BH_DRIVE_TOKEN, one grant alias "projects" -> /var/lib/agent-drive/projects, operations list/find/read/save. Only rewrite it when the content changes.
- a unit bh-drive.service with the existing unit() helper and $COMMON: ExecStart=/usr/bin/python3 -m drive_tool.serve --config /etc/drive-tool/config.json, WorkingDirectory=/opt/drive-tool, Environment=PYTHONPATH=/opt/drive-tool. Add bh-drive to SERVICES (before bh-hostd) and to hostd's After=; pass BH_DRIVE_TOKEN to hostd (it already loads EnvironmentFile=$ENVF) and Environment=BH_DRIVE_TOOL=/opt/drive-tool.

2. hostd.py: a new endpoint POST /api/drive, same Bearer BH_TOKEN auth as /api/call. JSON body {"op": "list"|"find"|"read"|"save"|"append", "path": "...", plus "name" for find, "text" for save/append, optional "limit"}. Call the matching drive.py function and return {"ok": true, "result": ...} or {"ok": false, "error": "<DriveError text>"} with status 400/404/503 as fitting. Paths go through the same validation as parse_ref (without the "drive:" prefix). Body limit 1.2 MiB.

Reply with exactly two blocks, each starting with a line "FILE: <path>" then the complete file in a fenced block: browser_host/hostd.py (whole file), browser_host/install.sh (whole file). Change nothing else in them.

## Answer

FILE: browser_host/hostd.py

```python
"""Browser host: one persistent Brave, reachable by any agent three ways.

1. Direct HTTPS (Caddy -> this service /api/*, and raw MCP at /mcp).
2. Cloudflare quick tunnel -> this service (same /api/*, discovered via the bus).
3. Git/GitHub API bus: request files on branch `browser-bus`, answered by commits.

Standard library only. All three paths share one MCP session and one lock, so
the browser is driven by one call at a time.
"""
import base64
import hmac
import itertools
import json
import mimetypes
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from agent import Agent
from relay import Relay
import drive

ENV = os.environ.get
TOKEN = ENV("BH_TOKEN", "")
MCP_URL = ENV("BH_MCP_URL", "http://127.0.0.1:8931/mcp")
PORT = int(ENV("BH_PORT", "8800"))
FILES = Path(ENV("BH_FILES", "/var/lib/browserhost/files")).resolve()
PUBLIC_URL = ENV("BH_PUBLIC_URL", "").rstrip("/")
DOWNLOADS = Path(ENV("BH_DOWNLOADS", str(FILES / "downloads"))).resolve()
TUNNEL_METRICS = ENV("BH_TUNNEL_METRICS", "http://127.0.0.1:20241")
BUS_DIR = ENV("BH_BUS_DIR", "")
BUS_BRANCH = ENV("BH_BUS_BRANCH", "browser-bus")
DROP_DIR = ENV("BH_DROP_DIR", "")  # clone of the repo for relay `save_to:` answers
DROP_BRANCH = ENV("BH_DROP_BRANCH", "main")
BUS_INTERVAL = float(ENV("BH_BUS_INTERVAL", "5"))
CALL_TIMEOUT = float(ENV("BH_CALL_TIMEOUT", "180"))
AGENT_STATE = Path(ENV("BH_AGENT_STATE", str(FILES.parent / "agent.json")))
CHAT_PAGE = Path(__file__).with_name("chat.html")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
BUS_CLAIMS = FILES.parent / "bus-claimed"  # outside the repo: survives restarts, never pushed
DOWNLOAD_LOCK = threading.Lock()
GIT_LOCK = threading.Lock()  # git bus and task relay share the bus clone
DROP_LOCK = threading.Lock()
SHOT_SEQ = itertools.count()

def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)

class MCPError(RuntimeError):
    pass

class MCP:
    """Minimal Streamable-HTTP MCP client with transparent re-initialisation."""

    def __init__(self, url):
        self.url, self.session, self.serial = url, None, 0
        self.lock = threading.Lock()
        self.tools = []

    def _post(self, body, timeout):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["mcp-session-id"] = self.session
        req = urllib.request.Request(self.url, json.dumps(body).encode(), headers, method="POST")
        resp = urllib.request.urlopen(req, timeout=timeout)
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session = sid
        if "id" not in body:
            resp.read()
            return None
        ctype = resp.headers.get("Content-Type", "")
        try:
            if "text/event-stream" not in ctype:
                return json.loads(resp.read() or b"null")
            data = []
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    msg = json.loads("\n".join(data))
                    data = []
                    if isinstance(msg, dict) and msg.get("id") == body["id"]:
                        return msg
            raise MCPError("MCP stream ended without a response")
        finally:
            resp.close()

    def _rpc(self, method, params, timeout):
        self.serial += 1
        msg = self._post({"jsonrpc": "2.0", "id": self.serial, "method": method,
                          "params": params}, timeout)
        if not isinstance(msg, dict):
            raise MCPError("bad MCP response")
        if "error" in msg:
            raise MCPError(json.dumps(msg["error"])[:2000])
        return msg.get("result", {})

    def _connect(self):
        self.session = None
        try:
            self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "dolesh-browser-host", "version": "1"}}, 60)
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, 30)
            self.tools = self._rpc("tools/list", {}, 60).get("tools", [])
        except Exception:
            self.session = None  # half-finished handshake: retry next time
            raise

    def ensure(self):
        if not self.session:
            self._connect()

    def list_tools(self):
        if self.session and self.tools:  # cached: do not queue behind a long tool call
            return self.tools
        with self.lock:
            self.ensure()
            return self.tools

    def call(self, tool, args=None):
        with self.lock:
            for attempt in (1, 2):
                try:
                    self.ensure()
                    return self._rpc("tools/call", {"name": tool, "arguments": args or {}},
                                     CALL_TIMEOUT)
                except urllib.error.HTTPError as exc:
                    # 404/400 => session expired (MCP restarted). Reconnect once.
                    # The call was rejected before running, so a retry is safe.
                    if attempt == 1 and exc.code in (400, 404):
                        self.session = None
                        continue
                    raise
                except (urllib.error.URLError, ConnectionError) as exc:
                    if attempt == 1 and not isinstance(exc, urllib.error.HTTPError) \
                            and "refused" in str(exc).lower():
                        self.session = None
                        time.sleep(2)
                        continue
                    raise

mcp = MCP(MCP_URL)

def save_image(item, prefix):
    ext = {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(item.get("mimeType"), ".png")
    shots = FILES / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(item.get("data", ""))
    while True:
        path = shots / f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{next(SHOT_SEQ):05d}{ext}"
        try:
            with open(path, "xb") as f:
                f.write(data)
            return path
        except FileExistsError:
            continue

def inline_files(item):
    """Playwright MCP writes page snapshots to files over HTTP; inline them so a
    remote agent sees the page without a second request."""
    text = item.get("text") if item.get("type") == "text" else None
    if not text:
        return item
    for ref in re.findall(r"\[Snapshot\]\(([^)]+\.yml)\)", text):
        path = FILES / Path(ref).name
        if path.is_file():
            text = text.replace(f"[Snapshot]({ref})",
                                "\n```yaml\n" + path.read_text("utf-8", "replace") + "\n```")
    return {**item, "text": text}

# Arbitrary server-side code would turn the bearer token into a shell on this box;
# this service never calls it and refuses it from agents.
# Page JavaScript (browser_evaluate) stays available: it runs inside the page.
BLOCKED = {"browser_run_code_unsafe"}

HOST_TOOLS = [
    {"name": "browser_download",
     "description": "Download a file through the browser (keeps its cookies/login). Give `target` "
                    "(snapshot ref or selector of the link/button that starts the download) or `url`. "
                    "Saved under downloads/; fetch it with host_read_file or GET /api/files/<path>.",
     "inputSchema": {"type": "object", "properties": {
         "target": {"type": "string"}, "url": {"type": "string"},
         "timeout_ms": {"type": "integer", "description": "default 60000"}}}},
    {"name": "browser_upload",
     "description": "Upload files from the browser host into a page's file input: give `target` "
                    "(ref of the file input or its 'Choose file' button) and `paths` (host paths "
                    "like 'uploads/report.pdf' from host_list_files, or absolute paths under the "
                    "host files dir). Opens the file chooser and attaches the files in one step.",
     "inputSchema": {"type": "object", "properties": {
         "target": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}},
         "required": ["target", "paths"]}},
    {"name": "browser_wait_stable",
     "description": "Wait until the page stops changing, e.g. a chatbot finished streaming its "
                    "answer or a feed finished loading, then return a fresh snapshot. Use after "
                    "submitting a message to an AI chat.",
     "inputSchema": {"type": "object", "properties": {
         "stable_ms": {"type": "integer", "description": "how long the page must stay unchanged (default 3000)"},
         "timeout_ms": {"type": "integer", "description": "give up after this long (default 120000, max 300000)"}}}},
    {"name": "host_list_files",
     "description": "List files on the browser host: downloads, screenshots, page snapshots, uploads.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "host_read_file",
     "description": "Read a host file by its path from host_list_files. Text is returned as text, "
                    "images as images, other files as a download URL.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                     "required": ["path"]}},
]

def text_result(text, error=False):
    return {"content": [{"type": "text", "text": text}], "isError": error}

def host_path(rel):
    """Resolve a path under FILES. Callers pass decoded paths (HTTP handlers unquote)."""
    path = (FILES / str(rel)).resolve()
    if path != FILES and FILES not in path.parents:
        raise PermissionError("path escapes files dir")
    return path

def list_files():
    items = []
    for p in FILES.rglob("*"):
        try:  # Brave renames files mid-download; skip entries that vanish
            st = p.stat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(st.st_mode):
            items.append({"path": p.relative_to(FILES).as_posix(), "bytes": st.st_size,
                          "mtime": int(st.st_mtime)})
    return sorted(items, key=lambda i: -i["mtime"])

def file_url(rel):
    return f"{PUBLIC_URL}/api/files/{quote(rel)}" if PUBLIC_URL else f"/api/files/{quote(rel)}"

PARTIAL = (".crdownload",)  # Chromium's in-progress suffix

def _downloads():
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    out = {}
    for p in DOWNLOADS.iterdir():
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(st.st_mode):
            out[p.name] = st.st_size
    return out

def _download_result(names, note=None):
    rels = [f"{DOWNLOADS.relative_to(FILES).as_posix()}/{n}" for n in names]
    out = [{"path": r, "bytes": (FILES / r).stat().st_size, "url": file_url(r)} for r in rels]
    if note:
        for o in out:
            o["note"] = note
    return text_result(json.dumps(out))

# Fetch inside the page (keeps cookies) and save the blob: this downloads even PDFs the
# viewer would otherwise open. If the page may not fetch it (CORS), the host fetches it.
DOWNLOAD_JS = r"""async () => {
  const url = %s;
  try {
    const ctl = new AbortController(); setTimeout(() => ctl.abort(), 150000);
    const r = await fetch(url, {credentials: 'include', signal: ctl.signal});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const b = await r.blob();
    let name = (r.headers.get('content-disposition') || '').match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i);
    name = name ? decodeURIComponent(name[1])
                : decodeURIComponent(new URL(url, location.href).pathname.split('/').pop() || 'download');
    if (b.type === 'application/pdf' && !/\.pdf$/i.test(name)) name += '.pdf';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b); a.download = name;
    (document.body || document.documentElement).appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 60000);
    return 'blob ' + name;
  } catch (e) { return 'link ' + e; }
}"""

def browser_download(args, stop=None):
    """Brave saves every download into DOWNLOADS (profile pref, policy and symlink).
    Start the download with ordinary browser tools, then wait for the finished file."""
    target, url = args.get("target"), args.get("url")
    if isinstance(target, str) and re.match(r"https?://", target.strip()):
        url, target = target.strip(), None  # a URL passed as the element
    if url:
        if urlparse(str(url)).scheme not in ("http", "https"):
            return text_result("only http(s) URLs can be downloaded", True)
        target = None  # a real URL beats a guessed element
    if not (target or url):
        return text_result("give target or url", True)
    timeout = min(max(5000, int(args.get("timeout_ms") or 60000)), 600000) / 1000
    with DOWNLOAD_LOCK:  # one download at a time, so results cannot be mixed up
        before = _downloads()
        expected = None
        if target:
            res = mcp.call("browser_click", {"target": target, "element": "download link"})
            if res.get("isError"):
                return res
        else:
            res = mcp.call("browser_evaluate", {"function": DOWNLOAD_JS % json.dumps(url)})
            said = "".join(c.get("text", "") for c in res.get("content", []))
            m = None if res.get("isError") else re.search(r'"blob ([^"]+)"', said)
            if not m:  # CORS, odd page or evaluation error: the host fetches it instead
                return direct_download(url)
            expected = m.group(1)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if stop and stop():
                return text_result("Stopped by the user while waiting for the download.", True)
            time.sleep(0.5)
            now = _downloads()
            fresh = [n for n in now if n not in before]
            busy = [n for n in fresh if n.endswith(PARTIAL)]
            done = sorted(n for n in fresh if not n.endswith(PARTIAL))
            if expected:
                stem, ext = os.path.splitext(expected)
                matched = [n for n in done if n == expected or (n.startswith(stem) and n.endswith(ext))]
                done = matched or (done if len(done) == 1 else [])
            if done and not busy:
                return _download_result(done)
        return text_result("no finished download appeared before timeout; check host_list_files",
                           True)

def _unique_download_path(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or "download"
    stem, ext = os.path.splitext(name)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    for n in range(10000):
        cand = DOWNLOADS / (name if n == 0 else f"{stem} ({n}){ext}")
        try:
            return cand, open(cand, "xb")
        except FileExistsError:
            continue
    raise RuntimeError("no free file name")

def direct_download(url):
    """Server-side fetch (no browser cookies) for files the page may not fetch."""
    if urlparse(str(url)).scheme not in ("http", "https"):
        return text_result("only http(s) URLs can be downloaded", True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=120) as r:
        disp = r.headers.get("Content-Disposition") or ""
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disp, re.I)
        name = unquote(m.group(1) if m else (Path(urlparse(r.geturl()).path).name or "download"))
        if r.headers.get_content_type() == "application/pdf" and not name.lower().endswith(".pdf"):
            name += ".pdf"
        path, f = _unique_download_path(name)
        with f:  # streamed: large files never sit in memory
            shutil.copyfileobj(r, f, 1 << 20)
    return _download_result([path.name], "fetched by the host directly (no browser cookies)")

FINGERPRINT_JS = """() => {
  const t = document.body ? document.body.innerText : '';
  const label = el => ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' +
                       (el.getAttribute('title') || '')).toLowerCase();
  const busy = document.querySelectorAll('[aria-busy="true"]').length +
    [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null && /\\bstop\\b/.test(label(b))).length;
  return busy + '|' + t.length + '|' + t.slice(-300);
}"""

def _page_fingerprint():
    """(fingerprint, busy) of the page, or (None, 0) if it cannot be read right now."""
    res = mcp.call("browser_evaluate", {"function": FINGERPRINT_JS})
    if res.get("isError"):
        return None, 0
    text = "".join(c.get("text", "") for c in res.get("content", []))
    m = re.search(r"### Result\s*(.*?)(?:\n### |\Z)", text, re.S)  # ignore console/event noise
    fp = m.group(1) if m else text
    busy = re.match(r'\s*"?(\d+)\|', fp)
    return fp, int(busy.group(1)) if busy else 0

def browser_wait_stable(args, stop=None):
    stable = max(500, int(args.get("stable_ms") or 3000)) / 1000
    timeout = min(max(5000, int(args.get("timeout_ms") or 120000)), 300000) / 1000
    start = time.time()
    deadline = start + timeout
    time.sleep(1)  # let a just-submitted request start streaming
    last, since, changed, note = None, time.time(), False, None
    while time.time() < deadline:
        if stop and stop():
            note = "Stopped by the user while waiting."
            break
        fp, busy = _page_fingerprint()
        now = time.time()
        if fp is None:  # unreadable (dialog, navigation): not evidence of stability
            last, since = None, now
        elif fp != last:
            changed = changed or last is not None
            last, since = fp, now
        else:
            quiet = now - since
            # A reply that has not started yet looks "stable": unless something changed,
            # wait at least 8 s. A busy marker (Stop button, aria-busy) means "still going".
            if busy == 0 and quiet >= stable and (changed or now - start >= max(stable, 8)):
                note = "Page is stable."
                break
            if quiet >= max(4 * stable, 20):
                note = "Page text has not changed for a while (a busy marker is still shown)."
                break
        time.sleep(0.7)
    snap = mcp.call("browser_snapshot", {})
    snap["content"] = [{"type": "text", "text": note or "Timed out while the page was still "
                        "changing."}] + snap.get("content", [])
    return snap

TEXT_SUFFIXES = (".json", ".yml", ".yaml", ".log", ".md", ".csv", ".txt")

def browser_upload(args):
    paths = args.get("paths") or []
    if isinstance(paths, str):
        paths = [paths]
    real = []
    for p in paths:
        path = Path(str(p))
        path = path.resolve() if path.is_absolute() else host_path(str(p))
        if path != FILES and FILES not in path.parents:
            return text_result(f"{p}: only files under {FILES} can be uploaded", True)
        if not path.is_file():
            return text_result(f"{p}: no such file on the host (see host_list_files)", True)
        real.append(str(path))
    if not real or not args.get("target"):
        return text_result("give target (file input ref) and paths", True)
    opened = mcp.call("browser_click", {"target": args["target"], "element": "file chooser"})
    if opened.get("isError"):
        return opened
    return mcp.call("browser_file_upload", {"paths": real})

def host_read_file(args):
    path = host_path(args.get("path", ""))
    if not path.is_file():
        return text_result("not found", True)
    rel = path.relative_to(FILES).as_posix()
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    size = path.stat().st_size
    if ctype.startswith("image/") and size <= 8 << 20:
        return {"content": [{"type": "image", "data": base64.b64encode(path.read_bytes()).decode(),
                             "mimeType": ctype}], "isError": False}
    if ctype.startswith("text/") or path.suffix.lower() in TEXT_SUFFIXES:
        with open(path, "rb") as f:
            data = f.read(200_000)
        more = f"\n…[file continues: {size} bytes in total; download it from {file_url(rel)}]" \
            if size > len(data) else ""
        return text_result(data.decode("utf-8", "replace") + more)
    return text_result(json.dumps({"path": rel, "bytes": size, "mimeType": ctype,
                                   "url": file_url(rel)}))

def public_tools():
    return [t for t in mcp.list_tools() if t["name"] not in BLOCKED] + HOST_TOOLS

def call_tool(tool, args, stop=None):
    if not isinstance(args, dict):
        return text_result("arguments must be an object", True)
    if tool in BLOCKED:
        return text_result(f"{tool} is disabled on this host", True)
    if tool == "browser_download":
        return browser_download(args, stop)
    if tool == "browser_wait_stable":
        return browser_wait_stable(args, stop)
    if tool == "browser_upload":
        return browser_upload(args)
    if tool == "host_list_files":
        return text_result(json.dumps(list_files()))
    if tool == "host_read_file":
        return host_read_file(args)
    return mcp.call(tool, args)

def agent_call(tool, args, stop=None):
    """The agent sees page snapshots inline, like the /mcp and REST clients do."""
    res = dict(call_tool(tool, args, stop))
    res["content"] = [inline_files(c) for c in res.get("content", [])]
    return res

def run_calls(calls, images="inline"):
    """Run a list of {tool,args}; returns per-call results. Stops at the first failure
    to run a call (never retried: actions may not be idempotent)."""
    out = []
    for call in calls:
        tool, started = None, time.time()
        try:
            if not isinstance(call, dict):
                raise ValueError("each call must be an object {tool, args}")
            tool, args = call.get("tool"), call.get("args") or {}
            if not isinstance(tool, str):
                raise ValueError("each call needs a string 'tool'")
            res = call_tool(tool, args)
            content = []
            for item in res.get("content", []):
                if item.get("type") == "image" and images != "inline":
                    path = save_image(item, "shot")
                    rel = path.relative_to(FILES).as_posix()
                    content.append({"type": "image_file", "path": rel,
                                    "mimeType": item.get("mimeType"), "url": file_url(rel)})
                else:
                    content.append(inline_files(item))
            out.append({"tool": tool, "ok": not res.get("isError"), "content": content,
                        "ms": int((time.time()-started)*1000)})
        except Exception as exc:
            out.append({"tool": tool, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                        "ms": int((time.time()-started)*1000)})
            break
    return out

def tunnel_url():
    try:
        with urllib.request.urlopen(TUNNEL_METRICS + "/quicktunnel", timeout=3) as r:
            host = json.loads(r.read()).get("hostname")
            return f"https://{host}" if host else None
    except Exception:
        return None

def endpoints():
    return {"direct": PUBLIC_URL or None, "cloudflare": tunnel_url(),
            "git_branch": BUS_BRANCH if BUS_DIR else None,
            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

# ---------------------------------------------------------------- HTTP API

class Handler(BaseHTTPRequestHandler):
    server_version = "dolesh-browser-host/1"

    def log_message(self, fmt, *a):
        log(self.address_string(), fmt % a)

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, indent=None).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authed(self, query):
        given = self.headers.get("Authorization", "")
        given = given[7:] if given.startswith("Bearer ") else (query.get("token") or [""])[0]
        if TOKEN and hmac.compare_digest(given.encode(), TOKEN.encode()):
            return True
        self._send(401, {"error": "unauthorized"})
        return False

    def _body(self):
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            out = bytearray()
            while True:
                size = int((self.rfile.readline(65537).split(b";")[0].strip() or b"0"), 16)
                if size == 0:
                    while self.rfile.readline(65537) not in (b"\r\n", b"\n", b""):
                        pass  # trailers
                    return bytes(out)
                out += self.rfile.read(size)
                self.rfile.readline(65537)  # CRLF after each chunk
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _send_file(self, path):
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if ctype.startswith(("image/", "application/pdf")) and ctype != "image/svg+xml":
            self.send_header("Content-Disposition", "inline")
        else:  # downloaded HTML/SVG/etc. must not run scripts on this origin
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''" + quote(path.name))
            self.send_header("Content-Security-Policy", "sandbox")
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/health", "/api/health"):
            return self._send(200, {"ok": True})
        if u.path in ("/", "/chat"):  # static page; it asks for the token itself
            return self._send(200, CHAT_PAGE.read_bytes(), "text/html; charset=utf-8")
        if not self._authed(q):
            return
        if u.path == "/mcp":  # no server-initiated stream; clients fall back to POST
            return self._send(405, {"error": "use POST"})
        try:
            if u.path == "/api/tools":
                return self._send(200, {"tools": public_tools()})
            if u.path == "/api/chat/status":
                return self._send(200, agent.status())
            if u.path == "/api/chat/events":
                epoch = (q.get("epoch") or [""])[0]
                return self._send(200, agent.events_after(
                    int((q.get("after") or ["0"])[0]), int(epoch) if epoch.isdigit() else None))
            if u.path == "/api/endpoints":
                return self._send(200, endpoints())
            if u.path == "/api/screenshot":
                args = {"type": "png"}
                if q.get("full"):
                    args["fullPage"] = True
                res = mcp.call("browser_take_screenshot", args)
                for item in res.get("content", []):
                    if item.get("type") == "image":
                        return self._send(200, base64.b64decode(item["data"]),
                                          item.get("mimeType", "image/png"))
                return self._send(502, {"error": "no image returned", "result": res})
            if u.path == "/api/files":
                return self._send(200, {"files": list_files()})
            if u.path.startswith("/api/files/"):
                path = host_path(unquote(u.path[len("/api/files/"):]))
                if not path.is_file():
                    return self._send(404, {"error": "not found"})
                return self._send_file(path)
            return self._send(404, {"error": "not found"})
        except Exception as exc:
            return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _mcp(self):
        """Stateless Streamable-HTTP MCP server (JSON responses, no SSE), so it also
        works through proxies/tunnels that buffer event streams."""
        try:
            msg = json.loads(self._body() or b"null")
        except ValueError:
            return self._send(400, {"jsonrpc": "2.0", "id": None,
                                    "error": {"code": -32700, "message": "parse error"}})
        if not isinstance(msg, (dict, list)) or msg == []:
            return self._send(400, {"jsonrpc": "2.0", "id": None,
                                    "error": {"code": -32600, "message": "invalid request"}})
        batch = msg if isinstance(msg, list) else [msg]
        replies = [r for r in (self._rpc(m) for m in batch) if r is not None]
        if not replies:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        return self._send(200, replies if isinstance(msg, list) else replies[0])

    def _rpc(self, m):
        if not isinstance(m, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if "id" not in m:
            return None  # notification
        method, params, rid = m.get("method"), m.get("params") or {}, m["id"]
        if not isinstance(method, str):
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "missing method"}}
        if not isinstance(params, dict):
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "params must be an object"}}
        try:
            if method == "initialize":
                result = {"protocolVersion": params.get("protocolVersion", "2025-03-26"),
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "dolesh-browser-host", "version": "1"},
                          "instructions": "One persistent Brave browser. Use browser_snapshot to "
                          "read the page (refs for click/type), browser_take_screenshot to see it."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": public_tools()}
            elif method == "tools/call":
                result = agent_call(params.get("name"), params.get("arguments") or {})
            else:
                return {"jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32601, "message": f"unknown method {method}"}}
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as exc:
            if method == "tools/call":  # a tool failure is a tool result, not a protocol error
                return {"jsonrpc": "2.0", "id": rid, "result": text_result(
                    f"{type(exc).__name__}: {exc}", True)}
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}

    def do_PUT(self):
        u = urlparse(self.path)
        if not self._authed(parse_qs(u.query)):
            return
        if not u.path.startswith("/api/files/"):
            return self._send(404, {"error": "not found"})
        try:
            path = host_path(unquote(u.path[len("/api/files/"):]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self._body())
            return self._send(200, {"path": path.relative_to(FILES).as_posix(),
                                    "absolute": str(path)})
        except Exception as exc:
            return self._send(400, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authed(q):
            return
        if u.path == "/mcp":
            return self._mcp()
        if u.path.startswith("/api/chat"):
            try:
                body = json.loads(self._body() or b"{}")
            except ValueError:
                body = {}
            body = body if isinstance(body, dict) else {}
            action = u.path[len("/api/chat"):]
            if action in ("", "/send"):
                return self._send(200, agent.send(str(body.get("message") or "")))
            if action == "/stop":
                return self._send(200, agent.stop())
            if action == "/reset":
                return self._send(200, agent.reset())
            return self._send(404, {"error": "not found"})
        if u.path == "/api/drive":
            cl = int(self.headers.get("Content-Length") or 0)
            if cl > 1258291:  # 1.2 MiB
                return self._send(413, {"ok": False, "error": "body too large"})
            try:
                body = self._body()
                data = json.loads(body or b"{}")
            except ValueError:
                return self._send(400, {"ok": False, "error": "body must be JSON"})
            if not isinstance(data, dict):
                return self._send(400, {"ok": False, "error": "body must be a JSON object"})
            op = data.get("op")
            path = data.get("path", "")
            if not isinstance(path, str):
                return self._send(400, {"ok": False, "error": "path must be a string"})
            try:
                if path:
                    parts = path.split("/")
                    if path.startswith("/") or any(p == "" or p == "." or p == ".." for p in parts):
                        raise drive.DriveError("bad drive path")
                    part_re = re.compile(r"^[A-Za-z0-9._ -]{1,128}$")
                    for part in parts:
                        if not part_re.match(part):
                            raise drive.DriveError("bad drive path")
            except drive.DriveError as exc:
                return self._send(400, {"ok": False, "error": str(exc)})
            try:
                if op == "list":
                    limit = int(data.get("limit", 200))
                    result = drive.list_dir(path, limit=limit)
                elif op == "find":
                    name = data.get("name")
                    if not isinstance(name, str) or not name:
                        return self._send(400, {"ok": False, "error": "name required for find"})
                    limit = int(data.get("limit", 50))
                    result = drive.find(name, path, limit=limit)
                elif op == "read":
                    result = drive.read_text(path)
                elif op == "save":
                    text = data.get("text")
                    if not isinstance(text, str):
                        return self._send(400, {"ok": False, "error": "text required for save"})
                    drive.save_text(path, text)
                    result = None
                elif op == "append":
                    text = data.get("text")
                    if not isinstance(text, str):
                        return self._send(400, {"ok": False, "error": "text required for append"})
                    drive.append_line(path, text)
                    result = None
                else:
                    return self._send(400, {"ok": False, "error": "unknown op"})
                return self._send(200, {"ok": True, "result": result})
            except drive.DriveError as exc:
                if exc.code == "not_found":
                    return self._send(404, {"ok": False, "error": str(exc)})
                if exc.code in ("unavailable", "drive client unavailable", "drive disabled",
                                "bad drive port"):
                    return self._send(503, {"ok": False, "error": str(exc)})
                return self._send(400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                return self._send(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        if u.path != "/api/call":
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self._body() or b"{}")
        except ValueError:
            return self._send(400, {"error": "body must be JSON"})
        if not isinstance(body, dict):
            return self._send(400, {"error": "body must be a JSON object"})
        calls = body.get("calls") or ([{"tool": body.get("tool"), "args": body.get("args")}]
                                      if body.get("tool") else [])
        if not calls or not isinstance(calls, list):
            return self._send(400, {"error": "give {tool,args} or {calls:[...]}"})
        images = (q.get("images") or [body.get("images", "inline")])[0]
        return self._send(200, {"results": run_calls(calls, images)})

# ---------------------------------------------------------------- git bus

def git(*args, check=True, repo=None):
    return subprocess.run(["git", "-C", repo or BUS_DIR, *args], check=check, text=True,
                          capture_output=True, timeout=120)

def bus_sync():
    """Rebase local answers onto the remote; never leave the clone mid-rebase."""
    if git("pull", "-q", "--rebase", "origin", BUS_BRANCH, check=False).returncode != 0:
        git("rebase", "--abort", check=False)
        return False
    return True

def bus_push(message):
    """Commit local changes and push until the remote has them. Returns success."""
    git("add", "-A")
    if git("status", "--porcelain").stdout.strip():
        git("commit", "-q", "-m", message)
    ahead = git("rev-list", "--count", f"origin/{BUS_BRANCH}..HEAD", check=False)
    if ahead.returncode == 0 and ahead.stdout.strip() == "0":
        return True
    for _ in range(5):
        if git("push", "-q", "origin", f"HEAD:{BUS_BRANCH}", check=False).returncode == 0:
            return True
        bus_sync()
    log("bus: push failed after retries; will retry next cycle")
    return False

def drop_save(rel, content, message):
    """Commit one answer file into the drop repo and push it. Returns (ok, where)."""
    if not DROP_DIR or not Path(DROP_DIR, ".git").exists():
        return False, "no drop repo on this host"
    root = Path(DROP_DIR).resolve()
    path = (root / rel).resolve()
    if root not in path.parents or ".git" in path.relative_to(root).parts:
        return False, f"refused path {rel!r}"
    with DROP_LOCK:
        # An empty repo has no remote branch yet: a failed pull is fine then.
        pulled = git("pull", "-q", "--rebase", "origin", DROP_BRANCH, check=False, repo=DROP_DIR)
        if pulled.returncode:
            git("rebase", "--abort", check=False, repo=DROP_DIR)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):  # files the agent saved
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        git("add", "--", str(path), repo=DROP_DIR)
        git("commit", "-q", "-m", message, check=False, repo=DROP_DIR)
        for _ in range(5):
            if git("push", "-q", "origin", f"HEAD:{DROP_BRANCH}", check=False,
                   repo=DROP_DIR).returncode == 0:
                return True, f"{DROP_BRANCH}:{path.relative_to(root).as_posix()}"
            git("pull", "-q", "--rebase", "origin", DROP_BRANCH, check=False, repo=DROP_DIR)
    return False, "push to the drop repo failed"

def drop_check(rel, since):
    """Did a commit after `since` (epoch s) put `rel` into the drop repo's remote branch?
    Used to check an agent's own push instead of trusting its reply."""
    if not DROP_DIR or not Path(DROP_DIR, ".git").exists():
        return False, "no drop repo on this host"
    with DROP_LOCK:
        git("fetch", "-q", "origin", DROP_BRANCH, check=False, repo=DROP_DIR)
        log_ = git("log", "-1", "--format=%H %ct", f"origin/{DROP_BRANCH}", "--", rel,
                   check=False, repo=DROP_DIR).stdout.split()
        if not log_ or int(log_[1]) < since - 120:  # small allowance for clock skew
            return False, f"no new commit of {rel}"
        # Keep the local clone in step so the box's own saves rebase cleanly on top.
        if git("pull", "-q", "--rebase", "origin", DROP_BRANCH, check=False,
               repo=DROP_DIR).returncode:
            git("rebase", "--abort", check=False, repo=DROP_DIR)
        return True, f"commit {log_[0][:7]} has {rel}"

def read_repo_file(repo, path, branch="main"):
    """Text of a file for a relay `read:` header: from the drop clone when it is the drop
    repo (private repos work), otherwise from GitHub's public raw URL."""
    if repo.lower() == drop_repo().lower():
        with DROP_LOCK:
            git("fetch", "-q", "origin", branch, check=False, repo=DROP_DIR)
            res = git("show", f"FETCH_HEAD:{path}", check=False, repo=DROP_DIR)
        if res.returncode:
            raise FileNotFoundError(res.stderr.strip()[:200] or path)
        return res.stdout
    if branch == "main" and repo.lower() == own_repo().lower():
        # This (private) repo's main is what the box runs: read the deployed checkout's file
        # (plain read: hostd's user may not own the checkout, and git refuses that).
        code = Path(__file__).resolve().parents[1]
        target = (code / path).resolve()
        if code not in target.parents or ".git" in target.relative_to(code).parts:
            raise FileNotFoundError(path)
        return target.read_text("utf-8", "replace")[:5_000_000]
    url = f"https://raw.githubusercontent.com/{quote(repo)}/{quote(branch)}/{quote(path)}"
    with urllib.request.urlopen(url, timeout=60) as r:  # public repos only
        return r.read(5_000_000).decode("utf-8", "replace")

def own_repo():
    """'owner/name' of this host's own code repo (browser-tool), from its checkout."""
    try:
        config = (Path(__file__).resolve().parents[1] / ".git" / "config").read_text()
    except OSError:
        return ""
    m = re.search(r"url\s*=\s*\S*github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?\s*$", config, re.M)
    return m.group(1) if m else ""

def drop_repo():
    """'owner/name' of the drop repo, from its clone's remote URL."""
    if not DROP_DIR or not Path(DROP_DIR, ".git").exists():
        return ""
    url = git("remote", "get-url", "origin", check=False, repo=DROP_DIR).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""

def bus_answer(root, rid, req):
    """Run one request and write its response. A claim marker outside the repo makes
    sure a request interrupted by a restart is reported, never blindly re-run."""
    claim = BUS_CLAIMS / rid
    resp = root / "responses" / f"{rid}.json"
    if claim.exists():
        results = [{"ok": False, "error": "interrupted: the host restarted while this request "
                    "was running; some calls may have run. Not re-run automatically."}]
    else:
        BUS_CLAIMS.mkdir(parents=True, exist_ok=True)
        claim.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        try:
            body = json.loads(req.read_text(encoding="utf-8"))
            if not isinstance(body, dict):
                raise ValueError("request must be a JSON object")
            calls = body.get("calls") or [{"tool": body.get("tool"), "args": body.get("args")}]
            results = run_calls(calls if isinstance(calls, list) else [calls], images="files")
        except Exception as exc:
            results = [{"ok": False, "error": f"bad request: {exc}"}]
    n = 0
    for r in results:  # copy images next to the response so git carries them
        for c in r.get("content", []):
            if c.get("type") == "image_file":
                n += 1
                try:
                    dst = root / "responses" / f"{rid}-{n}{Path(c['path']).suffix}"
                    shutil.copyfile(FILES / c["path"], dst)
                    c["bus_path"] = dst.relative_to(root).as_posix()
                except Exception as exc:
                    c["bus_error"] = f"{type(exc).__name__}: {exc}"
    resp.write_text(json.dumps({"id": rid, "results": results,
                                "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                               indent=1), encoding="utf-8")

def bus_loop():
    root = Path(BUS_DIR)
    last_endpoint, last_endpoint_at = None, 0
    while True:
        GIT_LOCK.acquire()
        try:
            bus_sync()
            (root / "requests").mkdir(exist_ok=True)
            (root / "responses").mkdir(exist_ok=True)
            for req in sorted((root / "requests").glob("*.json"),
                              key=lambda p: (p.stat().st_mtime, p.name)):
                rid = req.stem
                if (root / "responses" / f"{rid}.json").exists() or not SAFE_ID.match(rid):
                    continue
                try:
                    bus_answer(root, rid, req)
                except Exception as exc:  # always leave an answer so it is not re-run
                    (root / "responses" / f"{rid}.json").write_text(json.dumps(
                        {"id": rid, "results": [{"ok": False, "error": f"{type(exc).__name__}: {exc}"}]}),
                        encoding="utf-8")
                bus_push(f"browser-bus: answer {rid}")
            ep = endpoints()
            key = (ep["direct"], ep["cloudflare"])
            if key != last_endpoint or time.time() - last_endpoint_at > 1800:
                (root / "endpoint.json").write_text(json.dumps(ep, indent=1), encoding="utf-8")
                if bus_push("browser-bus: endpoint heartbeat"):
                    last_endpoint, last_endpoint_at = key, time.time()
            else:
                bus_push("browser-bus: retry")  # pushes only if earlier answers are unpushed
        except Exception:
            log("bus error:", traceback.format_exc(limit=3))
        finally:
            GIT_LOCK.release()
        time.sleep(BUS_INTERVAL)

agent = Agent(agent_call, public_tools,
              lambda item: save_image(item, "agent").relative_to(FILES).as_posix(),
              AGENT_STATE, log)

# Relay lanes: "1=gemini;2=deepseek;3=grok" -> lane 1 (Playwright MCP on port 8932) runs Gemini
# tasks, lane 2 (8933) DeepSeek, lane 3 (8934) Grok, while lane 0 (the main MCP) runs the rest.
# Each lane drives the same Brave (one login) through its own MCP server, so it has its own
# current tab, opens each task in its own window, and has its own repair agent.
LANES = ENV("BH_LANES", "1=gemini;2=deepseek;3=grok")

def parse_lanes(value):
    """'1=gemini;2=deepseek,duckai' -> {1: {'gemini'}, 2: {'deepseek', 'duckai'}}."""
    lanes = {}
    for part in filter(None, (x.strip() for x in (value or "").split(";"))):
        num, _, agents = part.partition("=")
        if num.strip().isdigit() and int(num) > 0:
            names = {a.strip().lower() for a in agents.split(",") if a.strip()}
            if names:
                lanes[int(num)] = names
    return lanes

def lane_agent(num, wait=120):
    """An Agent on lane `num`'s own MCP server, or None if that server does not answer."""
    lane_mcp = MCP(f"http://127.0.0.1:{8931 + num}/mcp")
    end = time.time() + wait  # lane servers start alongside hostd: give them time
    while True:
        try:
            lane_mcp.list_tools()
            break
        except Exception as exc:
            if time.time() >= end:
                log(f"relay lane {num}: MCP on port {8931 + num} unavailable ({exc}); "
                    "its agents run in lane 0")
                return None
            time.sleep(3)

    def lane_call(tool, args, stop=None):
        if not isinstance(args, dict):
            return text_result("arguments must be an object", True)
        if tool in BLOCKED:
            return text_result(f"{tool} is disabled on this host", True)
        res = dict(lane_mcp.call(tool, args))
        res["content"] = [inline_files(c) for c in res.get("content", [])]
        return res
    return Agent(lane_call, lambda: [t for t in lane_mcp.list_tools() if t["name"] not in BLOCKED],
                 lambda item: save_image(item, f"lane{num}").relative_to(FILES).as_posix(),
                 AGENT_STATE.with_name(f"agent-lane{num}.json"), log)

def main():
    FILES.mkdir(parents=True, exist_ok=True)
    if not TOKEN:
        raise SystemExit("BH_TOKEN is required")
    if BUS_DIR and Path(BUS_DIR, ".git").exists():
        threading.Thread(target=bus_loop, daemon=True).start()
        common = dict(drop_check=drop_check, drop_repo=drop_repo(), downloads=DOWNLOADS,
                      read_file=read_repo_file, attach_dir=FILES / "attach")
        lanes, tab_lock = [], threading.Lock()  # tab-list changes: one lane at a time
        for num, names in sorted(parse_lanes(LANES).items()):
            lane = lane_agent(num)
            if lane:
                lanes.append(Relay(lane, BUS_DIR, GIT_LOCK, bus_sync, bus_push, log, drop_save,
                                   agents=names, lane=num, new_window=True, shared_browser=True,
                                   tab_lock=tab_lock, **common))
        claimed = set().union(*(r.agents for r in lanes)) if lanes else set()
        relays = [Relay(agent, BUS_DIR, GIT_LOCK, bus_sync, bus_push, log, drop_save,
                        exclude=claimed, shared_browser=bool(lanes), new_window=bool(lanes),
                        tab_lock=tab_lock, **common)] + lanes
        busy = lambda: any(r.busy for r in relays)  # noqa: E731
        for r in relays:
            r.agent.browser_busy = busy
            threading.Thread(target=r.loop, daemon=True).start()
        log("git bus and task relay on branch", BUS_BRANCH, "lanes:",
            ", ".join(f"{r.lane}={','.join(sorted(r.agents)) if r.agents else 'rest'}"
                      for r in relays))
    else:
        log("git bus disabled (no BH_BUS_DIR clone)")
    log(f"browser host listening on 127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
```

FILE: browser_host/install.sh

```bash
#!/usr/bin/env bash
# Idempotent installer for the browser host on Ubuntu. Run as root from the repo
# checkout (e.g. /opt/browser-tool). Re-run by bh-update.timer on every new commit.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
exec 9>/run/bh-install.lock
flock 9

# Owner-requested cache/log cleanup, once per host; never touches browser data.
bash "$(dirname "$0")/cleanup.sh"
bash "$(dirname "$0")/disk-cleanup.sh" || true

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
BRANCH=$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)
# Settings (env > /etc/browserhost.conf > defaults from this checkout); nothing is
# hardcoded, so the same files install on any Ubuntu box, PC VM or VPS.
CONF=/etc/browserhost.conf
ENV_REPO=${BH_REPO:-} ENV_BRANCH=${BH_BUS_BRANCH:-} ENV_KEY=${BH_DEPLOY_KEY:-}
ENV_DROP_REPO=${BH_DROP_REPO:-} ENV_DROP_KEY=${BH_DROP_KEY:-}
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"
# Explicit environment wins over the saved file (needed to move a host to a new repo).
REMOTE=${ENV_REPO:-${BH_REPO:-$(git -C "$REPO_DIR" remote get-url origin)}}
BUS_BRANCH=${ENV_BRANCH:-${BH_BUS_BRANCH:-browser-bus}}
DEPLOY_KEY=${ENV_KEY:-${BH_DEPLOY_KEY:-/root/.ssh/bh_deploy}}
# Optional repo where relay answers with `save_to:` are committed (its own deploy key).
DROP_REPO=${ENV_DROP_REPO:-${BH_DROP_REPO:-}}
DROP_KEY=${ENV_DROP_KEY:-${BH_DROP_KEY:-/root/.ssh/drop_deploy}}
HOME_DIR=/var/lib/browserhost
FILES=$HOME_DIR/files
ENVF=/etc/browserhost.env
MCP_VERSION=0.0.83
STAMP=$HOME_DIR/.installed-packages-v1
CHANGED_UNITS=()

log() { echo "[browser-host] $*"; }
printf 'BH_REPO=%s\nBH_BUS_BRANCH=%s\nBH_DEPLOY_KEY=%s\nBH_DROP_REPO=%s\nBH_DROP_KEY=%s\n' \
  "$REMOTE" "$BUS_BRANCH" "$DEPLOY_KEY" "$DROP_REPO" "$DROP_KEY" > "$CONF"

# ---------------------------------------------------------------- packages (once)
if [ ! -f "$STAMP" ]; then
  log "installing packages (first run takes a few minutes)"
  if ! swapon --show | grep -q .; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
  apt-get update -qq
  apt-get install -y -qq curl gnupg ca-certificates git jq python3 xvfb fluxbox x11vnc \
    novnc websockify fonts-liberation fonts-noto-color-emoji fonts-noto-cjk >/dev/null
  # Brave
  curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg \
    https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" \
    > /etc/apt/sources.list.d/brave-browser-release.list
  # Caddy
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  # Node 22
  if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
  fi
  apt-get update -qq
  apt-get install -y -qq brave-browser caddy nodejs >/dev/null
  # cloudflared
  ARCH=$(dpkg --print-architecture)
  curl -fsSLo /tmp/cloudflared.deb \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARCH.deb"
  dpkg -i /tmp/cloudflared.deb >/dev/null && rm -f /tmp/cloudflared.deb
  mkdir -p "$HOME_DIR"
  touch "$STAMP"
fi

# Ubuntu's own nodejs package (e.g. 26.04) ships npm separately.
command -v npm >/dev/null || apt-get install -y -qq npm >/dev/null

# ---------------------------------------------------------------- user, dirs, secrets
id bh >/dev/null 2>&1 || useradd --system --home-dir "$HOME_DIR" --shell /usr/sbin/nologin bh
mkdir -p "$FILES/downloads" "$FILES/uploads" "$HOME_DIR/profile/Default" "$HOME_DIR/.ssh" /opt/browserhost/mcp

if [ ! -f "$ENVF" ]; then
  PUBLIC_IP=$(curl -fsS -H Metadata-Flavor:Google \
      http://169.254.169.254/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip 2>/dev/null \
    || curl -fsS https://api.ipify.org)
  cat > "$ENVF" <<EOF
BH_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(30))')
BH_VNC_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(4))')
BH_HOST=${BH_HOST:-${PUBLIC_IP//./-}.sslip.io}
EOF
  chmod 600 "$ENVF"
fi
# Sarvam key for the optional built-in agent. Stored only in the root-only env file,
# never printed. Source: SARVAM_API_KEY in the installer's environment; otherwise a
# `credentials.md` on the repo's main branch, if one exists (Dolesh's dev setup).
if [ -n "${SARVAM_API_KEY:-}" ]; then
  sed -i '/^SARVAM_API_KEY=/d' "$ENVF"; echo "SARVAM_API_KEY=$SARVAM_API_KEY" >> "$ENVF"
fi
if ! grep -q '^SARVAM_API_KEY=.' "$ENVF"; then
  GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o StrictHostKeyChecking=accept-new" \
    git -C "$REPO_DIR" fetch -q origin main || true
  KEYLINE=$(git -C "$REPO_DIR" show origin/main:credentials.md 2>/dev/null \
    | grep -m1 -o 'SARVAM_API_KEY=[^[:space:]`"'"'"']*' || true)
  if [ -n "${KEYLINE#SARVAM_API_KEY=}" ]; then
    sed -i '/^SARVAM_API_KEY=/d' "$ENVF"; echo "$KEYLINE" >> "$ENVF"; log "Sarvam key configured"
  else
    log "No Sarvam key: the browser tools work; the chat agent needs SARVAM_API_KEY in $ENVF"
  fi
fi
# shellcheck disable=SC1090
. "$ENVF"
if [ ! -f "$HOME_DIR/vnc.pass" ]; then
  x11vnc -storepasswd "$BH_VNC_PASSWORD" "$HOME_DIR/vnc.pass" >/dev/null
fi

# Brave profile: every download lands in the host files dir, never prompts.
PREFS=$HOME_DIR/profile/Default/Preferences
if [ ! -f "$PREFS" ]; then
  cat > "$PREFS" <<EOF
{"download":{"default_directory":"$FILES/downloads","prompt_for_download":false,"directory_upgrade":true},
 "savefile":{"default_directory":"$FILES/downloads"},
 "browser":{"has_seen_welcome_page":true},
 "brave":{"rewards":{"enabled":false},"p3a":{"enabled":false},"stats":{"reporting_enabled":false}}}
EOF
fi

# Managed policy (applies even to an existing profile): PDFs download instead of
# opening in the viewer, always into the served downloads dir, never prompting.
POLICY="{\"AlwaysOpenPdfExternally\": true, \"DownloadDirectory\": \"$FILES/downloads\", \"PromptForDownloadLocation\": false}"
for d in /etc/brave/policies/managed /etc/opt/brave/policies/managed /etc/opt/brave.com/brave/policies/managed; do
  mkdir -p "$d"
  if [ "$(cat "$d/browser-host.json" 2>/dev/null)" != "$POLICY" ]; then
    printf '%s\n' "$POLICY" > "$d/browser-host.json"; BRAVE_POLICY_CHANGED=1
  fi
done

# Brave may ignore the profile pref and use ~/Downloads; make both the same dir.
if [ -d "$HOME_DIR/Downloads" ] && [ ! -L "$HOME_DIR/Downloads" ]; then
  mv "$HOME_DIR/Downloads"/* "$FILES/downloads/" 2>/dev/null || true
  rmdir "$HOME_DIR/Downloads" 2>/dev/null || rm -rf "$HOME_DIR/Downloads"
fi
ln -sfn "$FILES/downloads" "$HOME_DIR/Downloads"

cp "$DEPLOY_KEY" "$HOME_DIR/.ssh/deploy"
chmod 700 "$HOME_DIR/.ssh"; chmod 600 "$HOME_DIR/.ssh/deploy"

# Playwright MCP (local only; the host service is the public door)
if [ ! -f /opt/browserhost/mcp/node_modules/@playwright/mcp/package.json ] || \
   [ "$(jq -r .version /opt/browserhost/mcp/node_modules/@playwright/mcp/package.json)" != "$MCP_VERSION" ]; then
  log "installing @playwright/mcp@$MCP_VERSION"
  npm install --silent --prefix /opt/browserhost/mcp "@playwright/mcp@$MCP_VERSION" >/dev/null
fi

# Git bus working copy (branch browser-bus), owned by bh
BUS=$HOME_DIR/bus
GSSH="ssh -i $HOME_DIR/.ssh/deploy -o StrictHostKeyChecking=accept-new"
chown -R bh:bh "$HOME_DIR"
if [ ! -d "$BUS/.git" ]; then
  log "preparing git bus"
  if sudo -u bh env GIT_SSH_COMMAND="$GSSH" git ls-remote --exit-code "$REMOTE" "$BUS_BRANCH" >/dev/null 2>&1; then
    sudo -u bh env GIT_SSH_COMMAND="$GSSH" git clone -q -b "$BUS_BRANCH" --single-branch "$REMOTE" "$BUS"
  else
    sudo -u bh bash -c "set -e; mkdir -p '$BUS' && cd '$BUS' && git init -q && git checkout -q --orphan '$BUS_BRANCH'
      cp '$REPO_DIR/browser_host/BUS.md' README.md && mkdir -p requests responses && touch requests/.keep responses/.keep
      git add -A && git -c user.name=browser-host -c user.email=browser-host@localhost commit -q -m 'browser-bus: init'
      git remote add origin '$REMOTE' && GIT_SSH_COMMAND='$GSSH' git push -q -u origin '$BUS_BRANCH'"
  fi
fi
sudo -u bh git -C "$BUS" config user.name browser-host
sudo -u bh git -C "$BUS" config user.email browser-host@localhost
sudo -u bh git -C "$BUS" config core.sshCommand "$GSSH"

# Drop repo working copy (optional): relay answers with `save_to:` are committed here.
DROP=$HOME_DIR/drop
DROP_ENV=""
if [ -n "$DROP_REPO" ] && [ -f "$DROP_KEY" ]; then
  install -o bh -g bh -m 600 "$DROP_KEY" "$HOME_DIR/.ssh/drop"
  DSSH="ssh -i $HOME_DIR/.ssh/drop -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
  if [ ! -d "$DROP/.git" ]; then
    log "cloning drop repo $DROP_REPO"
    sudo -u bh env GIT_SSH_COMMAND="$DSSH" git clone -q "$DROP_REPO" "$DROP" \
      || log "drop repo clone failed: is $DROP_KEY.pub a deploy key with write access?"
  fi
  if [ -d "$DROP/.git" ]; then
    sudo -u bh git -C "$DROP" config core.sshCommand "$DSSH"
    sudo -u bh git -C "$DROP" config user.name browser-host
    sudo -u bh git -C "$DROP" config user.email browser-host@localhost
    DROP_ENV="Environment=BH_DROP_DIR=$DROP"
  fi
else
  log "no drop repo (BH_DROP_REPO + $DROP_KEY): save_to answers go to the bus branch"
fi

# ---------------------------------------------------------------- drive tool
DRIVE_TOOL=/opt/drive-tool
DRIVE_REF=${BH_DRIVE_REF:-main}
if [ ! -d "$DRIVE_TOOL/.git" ]; then
  log "cloning drive-tool"
  git clone -q --branch "$DRIVE_REF" https://github.com/Dolesh-avkalan/drive-tool "$DRIVE_TOOL" \
    || git clone -q https://github.com/Dolesh-avkalan/drive-tool "$DRIVE_TOOL"
fi
git -C "$DRIVE_TOOL" fetch -q origin "$DRIVE_REF"
git -C "$DRIVE_TOOL" checkout -q "$DRIVE_REF" || true
git -C "$DRIVE_TOOL" reset --hard "origin/$DRIVE_REF" 2>/dev/null || git -C "$DRIVE_TOOL" checkout -q "$DRIVE_REF"
mkdir -p /var/lib/agent-drive/projects
chown bh:bh /var/lib/agent-drive /var/lib/agent-drive/projects
chmod 750 /var/lib/agent-drive/projects
if ! grep -q '^BH_DRIVE_TOKEN=.' "$ENVF"; then
  echo "BH_DRIVE_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> "$ENVF"
  log "generated BH_DRIVE_TOKEN"
fi
# shellcheck disable=SC1090
. "$ENVF"
mkdir -p /etc/drive-tool
chown root:bh /etc/drive-tool
chmod 750 /etc/drive-tool
HASH=$(echo -n "$BH_DRIVE_TOKEN" | sha256sum | awk '{print $1}')
CONFIG='{"port":8940,"agents":{"hub":{"token_sha256":"'"$HASH"'","grants":[{"alias":"projects","path":"/var/lib/agent-drive/projects","operations":["list","find","read","save"]}]}}}'
if [ "$(cat /etc/drive-tool/config.json 2>/dev/null)" != "$CONFIG" ]; then
  printf '%s\n' "$CONFIG" > /etc/drive-tool/config.json
  chown root:bh /etc/drive-tool/config.json
  chmod 640 /etc/drive-tool/config.json
fi

# ---------------------------------------------------------------- systemd units
unit() {  # unit NAME CONTENT ; records whether it changed
  local path=/etc/systemd/system/$1
  if [ ! -f "$path" ] || [ "$(cat "$path")" != "$2" ]; then
    printf '%s\n' "$2" > "$path"; CHANGED_UNITS+=("$1")
  fi
}
COMMON="User=bh
Group=bh
Restart=always
RestartSec=3
Environment=DISPLAY=:99
Environment=HOME=$HOME_DIR"

unit bh-xvfb.service "[Unit]
Description=Browser host virtual display
[Service]
$COMMON
ExecStart=/usr/bin/Xvfb :99 -screen 0 1440x900x24 -nolisten tcp
[Install]
WantedBy=multi-user.target"

unit bh-wm.service "[Unit]
Description=Browser host window manager
After=bh-xvfb.service
Requires=bh-xvfb.service
[Service]
$COMMON
ExecStart=/usr/bin/fluxbox
[Install]
WantedBy=multi-user.target"

unit bh-brave.service "[Unit]
Description=Persistent Brave for the browser host
After=bh-wm.service
Requires=bh-xvfb.service
[Service]
$COMMON
ExecStart=/usr/bin/brave-browser --user-data-dir=$HOME_DIR/profile --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --no-first-run --no-default-browser-check --password-store=basic --disable-dev-shm-usage --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows --start-maximized --window-position=0,0 --window-size=1440,900 about:blank
[Install]
WantedBy=multi-user.target"

unit bh-vnc.service "[Unit]
Description=Browser host VNC (local only)
After=bh-xvfb.service
Requires=bh-xvfb.service
[Service]
$COMMON
ExecStart=/usr/bin/x11vnc -display :99 -forever -shared -localhost -rfbport 5900 -rfbauth $HOME_DIR/vnc.pass -quiet
[Install]
WantedBy=multi-user.target"

unit bh-novnc.service "[Unit]
Description=Browser host noVNC web viewer (local only, served via Caddy)
After=bh-vnc.service
[Service]
$COMMON
ExecStart=/usr/bin/websockify --web /usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900
[Install]
WantedBy=multi-user.target"

unit bh-mcp.service "[Unit]
Description=Playwright MCP attached to Brave (local only)
After=bh-brave.service
[Service]
$COMMON
WorkingDirectory=$FILES
ExecStartPre=/usr/bin/curl -fsS -o /dev/null --retry 60 --retry-connrefused --retry-delay 1 http://127.0.0.1:9222/json/version
ExecStart=/usr/bin/node /opt/browserhost/mcp/node_modules/@playwright/mcp/cli.js --cdp-endpoint http://127.0.0.1:9222 --port 8931 --host 127.0.0.1 --allowed-hosts * --caps vision,pdf --timeout-action 30000 --output-dir $FILES --image-responses allow
[Install]
WantedBy=multi-user.target"

# Lanes: more Playwright MCP servers on the same Brave (one login), each with its own
# current tab, so the relay can drive Gemini, DeepSeek and Sarvam at the same time.
for LANE in 1 2 3; do
unit bh-mcp-l$LANE.service "[Unit]
Description=Playwright MCP lane $LANE attached to Brave (local only)
After=bh-brave.service
[Service]
$COMMON
WorkingDirectory=$FILES
ExecStartPre=/usr/bin/curl -fsS -o /dev/null --retry 60 --retry-connrefused --retry-delay 1 http://127.0.0.1:9222/json/version
ExecStart=/usr/bin/node /opt/browserhost/mcp/node_modules/@playwright/mcp/cli.js --cdp-endpoint http://127.0.0.1:9222 --port $((8931 + LANE)) --host 127.0.0.1 --allowed-hosts * --caps vision,pdf --timeout-action 30000 --output-dir $FILES --image-responses allow
[Install]
WantedBy=multi-user.target"
done

unit bh-drive.service "[Unit]
Description=Agent drive service
After=network.target
[Service]
$COMMON
WorkingDirectory=/opt/drive-tool
Environment=PYTHONPATH=/opt/drive-tool
ExecStart=/usr/bin/python3 -m drive_tool.serve --config /etc/drive-tool/config.json
[Install]
WantedBy=multi-user.target"

unit bh-hostd.service "[Unit]
Description=Browser host API + MCP endpoint + git bus
After=bh-mcp.service bh-mcp-l1.service bh-mcp-l2.service bh-mcp-l3.service bh-drive.service
[Service]
$COMMON
EnvironmentFile=$ENVF
Environment=BH_FILES=$FILES
Environment=BH_PUBLIC_URL=https://$BH_HOST
Environment=BH_BUS_DIR=$BUS
Environment=BH_BUS_BRANCH=$BUS_BRANCH
Environment=BH_DRIVE_TOOL=/opt/drive-tool
$DROP_ENV
ExecStart=/usr/bin/python3 $REPO_DIR/browser_host/hostd.py
[Install]
WantedBy=multi-user.target"

unit bh-tunnel.service "[Unit]
Description=Cloudflare quick tunnel to the browser host API (fallback path)
After=bh-hostd.service
[Service]
$COMMON
ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate --metrics 127.0.0.1:20241 --url http://127.0.0.1:8800
[Install]
WantedBy=multi-user.target"

# SSH over HTTPS for agents that can reach port 443 but not 22: Caddy passes /ssh to this
# websocket bridge, which forwards to the box's own sshd. Login is by key only (below).
unit bh-sshws.service "[Unit]
Description=Browser host SSH-over-websocket bridge (local only, served via Caddy /ssh)
[Service]
$COMMON
ExecStart=/usr/bin/websockify 127.0.0.1:6081 127.0.0.1:22
[Install]
WantedBy=multi-user.target"

unit bh-update.service "[Unit]
Description=Pull browser host code and reinstall when it changes
[Service]
Type=oneshot
Environment=\"GIT_SSH_COMMAND=ssh -i $DEPLOY_KEY -o StrictHostKeyChecking=accept-new\"
ExecStart=/bin/bash $REPO_DIR/browser_host/update.sh"

unit bh-update.timer "[Unit]
Description=Check for browser host updates every minute
[Timer]
OnActiveSec=30s
OnBootSec=1min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target"

# ---------------------------------------------------------------- director SSH login
# User `director`: key-only (no password is ever set), passwordless sudo. Keys come from
# browser_host/director_keys.pub; removing every key there turns the login off.
KEYS=$(grep -E '^(ssh-|ecdsa-|sk-)' "$REPO_DIR/browser_host/director_keys.pub" 2>/dev/null || true)
if [ -n "$KEYS" ]; then
  id director >/dev/null 2>&1 || useradd --create-home --shell /bin/bash director
  install -d -m 700 -o director -g director /home/director/.ssh
  printf '%s\n' "$KEYS" > /home/director/.ssh/authorized_keys
  chown director:director /home/director/.ssh/authorized_keys
  chmod 600 /home/director/.ssh/authorized_keys
  echo 'director ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/bh-director
  chmod 440 /etc/sudoers.d/bh-director
else
  rm -f /home/director/.ssh/authorized_keys /etc/sudoers.d/bh-director
fi

# ---------------------------------------------------------------- Caddy
CADDY="$BH_HOST {
	encode gzip
	handle /ssh {
		reverse_proxy 127.0.0.1:6081
	}
	handle_path /view/* {
		reverse_proxy 127.0.0.1:6080
	}
	handle {
		reverse_proxy 127.0.0.1:8800 {
			flush_interval -1
		}
	}
}"
if [ "$(cat /etc/caddy/Caddyfile 2>/dev/null)" != "$CADDY" ]; then
  printf '%s\n' "$CADDY" > /etc/caddy/Caddyfile
  systemctl reload caddy 2>/dev/null || systemctl restart caddy || log "caddy failed to start"
fi

systemctl daemon-reload
SERVICES="bh-xvfb bh-wm bh-brave bh-vnc bh-novnc bh-mcp bh-mcp-l1 bh-mcp-l2 bh-mcp-l3 bh-drive bh-hostd bh-tunnel bh-sshws"
# From here on a failing service must not abort: report.sh publishes its journal.
set +e
systemctl enable -q $SERVICES bh-update.timer caddy
for u in "${CHANGED_UNITS[@]}"; do
  case $u in *.timer|bh-update.service) ;; *) systemctl restart "$u" ;; esac
done
systemctl start $SERVICES bh-update.timer
[ -n "${BRAVE_POLICY_CHANGED:-}" ] && systemctl restart bh-brave bh-mcp bh-mcp-l1 bh-mcp-l2 bh-mcp-l3   # policies load at browser start
# A restarted Brave drops every MCP server's CDP connection: reconnect them all.
case " ${CHANGED_UNITS[*]} " in *" bh-brave.service "*) systemctl restart bh-mcp bh-mcp-l1 bh-mcp-l2 bh-mcp-l3 ;; esac
systemctl restart bh-hostd   # always pick up new code

# ---------------------------------------------------------------- report
sleep 8
TUNNEL=$(curl -fsS http://127.0.0.1:20241/quicktunnel 2>/dev/null | jq -r '.hostname // empty' || true)
echo
echo "================ BROWSER HOST READY ================"
for s in $SERVICES caddy; do printf '  %-10s %s\n' "$s" "$(systemctl is-active $s)"; done
echo "  MCP (any agent):   https://$BH_HOST/mcp"
echo "  REST API:          https://$BH_HOST/api/call"
[ -n "$TUNNEL" ] && echo "  Cloudflare backup: https://$TUNNEL  (same /mcp and /api paths; URL changes on restart)"
echo "  Git fallback:      branch $BUS_BRANCH of $REMOTE (README there)"
echo "  Auth header:       Authorization: Bearer $BH_TOKEN"
echo "  WATCH THE BROWSER: https://$BH_HOST/view/vnc.html?path=view/websockify&autoconnect=1&resize=scale"
echo "  Viewer password:   $BH_VNC_PASSWORD"
echo "===================================================="
bash "$REPO_DIR/browser_host/report.sh" install || true
```
