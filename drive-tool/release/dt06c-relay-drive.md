# dt06c-deepseek (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/6f4eb27d-41bc-4b95-aa8b-4419bc8b0459
- model: deepseek (deepthink on, search off)
- finished: 2026-10-16T12:50:21Z

## Question

DeepSeek, I need you to connect our task relay (attached relay.py, from the browser-tool repo) to a shared file drive, so AI agents can keep project memory in files instead of in their context. The drive is a local service; its Python client is the attached service_client.py (DriveClient: list/find/read/save with source_id, file_id "root" or "p/<path>"). Python 3.11+, standard library only.

Write:

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

Changes to browser_host/relay.py (keep everything else exactly as it is):
- read: and attach: accept refs of the form drive:<path> next to the existing owner/repo:path refs. Drive refs are always fetched by the box with drive.read_text (also for agents that push, like Sarvam: they cannot reach the drive), pasted or attached exactly like GitHub files are today. A drive ref when drive.enabled() is False, or a read error, fails the task before anything is sent, with a clear message.
- save_to: drive:<path> saves the answer into the drive with drive.save_text instead of the drop repo; pushers are not asked to push for a drive save_to. If the save fails, the answer stays in the bus result (as with the drop repo today) and the result says the drive save failed.
- After a task whose save_to is a drive path, append one line to "<first part of the path>/history/<YYYY-MM>.md": "- <UTC time ISO, seconds> <task id> <agent> <status> -> <path>". A failure here is noted in the result, never fails the task.

tests/test_drive.py (unittest): parse_ref accepts and rejects the right paths; read_text/save_text/append_line against a fake client (patch the client factory); relay: a drive read: ref is pasted, a drive save_to is saved and a history line appended, drive disabled -> task fails before sending. Keep it small.

Reply with exactly three blocks, each starting with a line "FILE: <path>" followed by the complete file in a ```python fence: browser_host/drive.py, browser_host/relay.py (the whole file), tests/test_drive.py.

## Answer

FILE: browser_host/drive.py

```python
"""Shared wrapper around the Drive service client, used by the relay and hostd.

Settings come from the environment:

    BH_DRIVE_PORT   port of the loopback drive service (default 8940)
    BH_DRIVE_TOKEN  bearer token; unset means the drive is disabled
    BH_DRIVE_TOOL   path of the drive-tool checkout (default /opt/drive-tool);
                    added to sys.path lazily before importing
                    drive_tool.service_client

The source alias used for every call is the constant ALIAS ("projects").
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, List

ALIAS = "projects"

DEFAULT_PORT = 8940
DEFAULT_TOOL = "/opt/drive-tool"
_TIMEOUT = 10.0

_MAX_BYTES = 1048576
_CHUNK = 262144

_PART_RE = re.compile(r"^[A-Za-z0-9._ -]{1,128}$")

class DriveError(Exception):
    """A drive call failed. ``code`` is a short, safe reason; ``str`` never
    contains the bearer token."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def _port() -> int:
    raw = (os.environ.get("BH_DRIVE_PORT") or "").strip() or str(DEFAULT_PORT)
    try:
        port = int(raw)
    except ValueError:
        raise DriveError("bad drive port") from None
    if not (1 <= port <= 65535):
        raise DriveError("bad drive port")
    return port

def _token() -> str:
    return os.environ.get("BH_DRIVE_TOKEN") or ""

def _tool_path() -> str:
    return (os.environ.get("BH_DRIVE_TOOL") or "").strip() or DEFAULT_TOOL

def enabled() -> bool:
    return bool(_token())

def _client():
    """Create one DriveClient for a single call."""
    if not enabled():
        raise DriveError("drive disabled")
    tool = _tool_path()
    if tool and tool not in sys.path:
        sys.path.insert(0, tool)
    try:
        from drive_tool.service_client import DriveClient
    except Exception:  # noqa: BLE001
        raise DriveError("drive client unavailable") from None
    return DriveClient(port=_port(), token=_token(), timeout=_TIMEOUT)

def _call(fn):
    """Run ``fn(client)``; map every client failure to DriveError(code)."""
    client = _client()
    try:
        return fn(client)
    except DriveError:
        raise
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code:
            raise DriveError(code) from None
        raise DriveError("unavailable") from None

def parse_ref(ref: str) -> str | None:
    """'drive:proj/notes/a.md' -> 'proj/notes/a.md'; None for non-drive refs.

    Raises DriveError("bad drive path") for a drive ref whose path is not a
    safe relative POSIX path.
    """
    if not isinstance(ref, str):
        raise DriveError("bad drive path")
    if not ref.startswith("drive:"):
        return None
    path = ref[len("drive:"):]
    if path == "" or path.startswith("/"):
        raise DriveError("bad drive path")
    parts = path.split("/")
    if any(p == "" or p == "." or p == ".." for p in parts):
        raise DriveError("bad drive path")
    for part in parts:
        if not _PART_RE.match(part):
            raise DriveError("bad drive path")
    return path

def file_id(path: str) -> str:
    return "root" if path == "" else "p/" + path

def read_text(path: str, max_bytes: int = _MAX_BYTES) -> str:
    """Read up to ``max_bytes`` of a drive file, decoded as UTF-8."""
    def run(client):
        chunks: List[bytes] = []
        total = 0
        offset = 0
        while total < max_bytes:
            want = min(_CHUNK, max_bytes - total)
            if want <= 0:
                break
            reply = client.read(ALIAS, file_id(path), offset=offset, length=want)
            chunks.append(reply.data)
            total += len(reply.data)
            if reply.eof_observed or not reply.data:
                break
            offset += len(reply.data)
        return b"".join(chunks)[:max_bytes].decode("utf-8", errors="replace")
    return _call(run)

def save_text(path: str, text: str, overwrite: bool = True) -> None:
    """Save ``text`` as UTF-8, creating parent folders."""
    data = text.encode("utf-8")
    if len(data) > _MAX_BYTES:
        raise DriveError("too_large")

    def run(client):
        client.save(ALIAS, file_id(path), data, overwrite=overwrite,
                    create_parents=True)
    _call(run)

def list_dir(path: str = "", limit: int = 200) -> List[Any]:
    def run(client):
        result = client.list(ALIAS, file_id(path), limit=limit)
        if isinstance(result, dict):
            return result.get("entries", [])
        return result
    return _call(run)

def find(name: str, path: str = "", limit: int = 50) -> List[Any]:
    def run(client):
        result = client.find(ALIAS, file_id(path), name_contains=name, limit=limit)
        if isinstance(result, dict):
            return result.get("entries", [])
        return result
    return _call(run)

def append_line(path: str, line: str) -> None:
    """Append ``line`` plus a newline; a missing file counts as empty."""
    try:
        text = read_text(path)
    except DriveError as exc:
        if exc.code == "not_found":
            text = ""
        else:
            raise
    save_text(path, text + line + "\n", overwrite=True)
```

FILE: browser_host/relay.py

```python
"""Task relay: a director writes a scoped task into the repo; the browser agent hands
it to a heavyweight AI agent's website (ChatGPT, Claude, Gemini, ...), waits for the
work to finish, and commits the result back.

Repo layout on branch `browser-bus`:
  tasks/<id>.md          the task (header lines, then `---`, then the task text)
  tasks/<id>.result.md   written by the relay: status, the agent's final answer, evidence

Task header (one `key: value` per line, all optional except agent):
  agent: chatgpt | claude | gemini | deepseek | sarvam | grok | duckai   (allowlist; nothing else runs)
  done_when: what counts as finished (the relay waits for this)
  ping: https://...       POSTed {"id","status","result"} when the result is committed
  chat: new | <chat URL> | <chat id>   (default new; an existing chat continues that thread)
  read: owner/repo:path[@branch], ...  (input files: an agent that pushes reads them from
                          GitHub itself; for the others the box pastes them into the task)
  save_to: folder/name.md (also commit the answer there in the drop repo; without a drop
                          repo on the host it goes to drop/<save_to> on the bus branch)
  model: 3.1 Pro          (gemini, grok: pick this model in the site's picker (grok: auto,
                          fast, expert, build, heavy); default: leave as is)
  effort: low | medium | high   (gemini: thinking level; default: leave as is)
  deepthink: on | off     (deepseek switches; each defaults to off so runs repeat)
  search: on | off
  mode: scripted | agent  (default: scripted where the site has a recipe, else agent)
  timeout_min: 30         (scripted: how long to wait for the reply)
  chaos: popup | wrong_page   (TEST ONLY: break the page on purpose to prove a repair)
  attach: owner/repo:path[@branch], ...  (input files uploaded INTO the chat as attachments
                          (Gemini, DeepSeek, Grok), so the chat shows them as files; if the upload
                          fails they are pasted in instead. Agents that push read them from
                          GitHub themselves, as with read:. Text files only.)
  collect: d119           (recover: send nothing; reopen task d119's chat (its CHAT_URL) and save
                          its last reply once finished, e.g. after a timeout. A task cut off by
                          a host restart does this by itself on its re-run.)
  after: d025, d026       (chains: run only once these tasks have results with status done;
                          if one ended otherwise, this task is closed as blocked, and so on
                          down the chain, without running)
  expect: STATUS: GENERATED | FILE: a.py   (checks: every `|`-separated text must appear
                          in the answer, else the task ends `failed` (answer kept), which
                          stops the tasks that come `after` it)

Chains: queue a whole pipeline at once (design -> code -> assemble -> review) with
`after:` and `expect:`; each step starts as soon as the one before it passes its checks,
with no director in between. Put `ping:` on the last step (or every step) to hear back.

Tasks run one at a time. Sites with a recipe in scripted.py (gemini, sarvam, deepseek, grok)
run as coded steps:
no model on the normal path; the Sarvam agent is called only to repair a failed step,
with a few actions, and the code re-checks its work. Other sites, or `mode: agent`,
run the whole task through the Sarvam browser agent, as the chat page does.

Started by hostd.main() with the bus clone's git lock; Relay.loop() refuses to run while
ENABLED is False.
"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path

import drive
import scripted

SITES = {
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/new",
    "gemini": "https://gemini.google.com/app",
    "deepseek": "https://chat.deepseek.com/",
    "sarvam": "https://indus.sarvam.ai/",
    "grok": "https://grok.com/",
    "duckai": "https://duck.ai/",
}
ENABLED = True  # enabled by owner decision (2026-10-05), allowlisted sites only
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
MAX_ATTEMPTS = 2  # a task that crashes or is cut off by a restart runs at most twice
ASSIST_STEPS = 8  # model steps allowed for one repair
# Seconds between tasks that use a site: back-to-back messages got Gemini throttling the
# account (errors after ~30 messages in an hour, 2026-10-14). 0 turns it off.
GAP = int(os.environ.get("BH_RELAY_GAP", "90"))
# Agents with a sandbox and a GitHub connection commit their own answer and files to the
# drop repo; the relay then checks the repo and saves the answer itself if nothing came.
# Everyone else (Gemini, DeepSeek, duck.ai) cannot push: the relay always saves for them.
PUSHERS = {"sarvam"}
# Failures caused by the browser, not the site or the task: worth one automatic re-run.
BROWSER_GONE = re.compile(r"ECONNREFUSED|has been closed|disappeared|our tab is gone|"
                          r"no longer on its own tab|could not list the tabs|could not open a tab|"
                          r"selected tab shows")

class BrowserGone(Exception):
    """The browser went away under a task; run_guarded re-runs it once."""
PUSH_WAIT = 120  # s to wait for an agent's push to show up in the drop repo

READ_REF = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+):([A-Za-z0-9_./ -]+?)"
                      r"(?:@([A-Za-z0-9_./-]+))?$")

def read_refs(value):
    """'o/r:a.md, drive:proj/b.md' -> refs; ValueError on a bad one.

    A ref is ('github', repo, path, branch) or ('drive', path).
    """
    refs = []
    for part in filter(None, (x.strip() for x in (value or "").split(","))):
        if part.startswith("drive:"):
            try:
                path = drive.parse_ref(part)
            except drive.DriveError as exc:
                raise ValueError(f"read: {part!r}: {exc}") from None
            if path is None:
                raise ValueError(f"read: {part!r} is not a drive ref")
            refs.append(("drive", path))
            continue
        m = READ_REF.match(part)
        if not m or ".." in m.group(2).split("/") or m.group(2).startswith("/"):
            raise ValueError(f"read: {part!r} is not owner/repo:path[@branch]")
        refs.append(("github", m.group(1), m.group(2), m.group(3) or "main"))
    return refs

def ref_label(ref):
    """A human-readable label for a read/attach ref."""
    if ref[0] == "drive":
        return f"drive:{ref[1]}"
    return f"{ref[1]}:{ref[2]}@{ref[3]}"

def read_instruction(refs):
    lines = "\n".join(f"- repository {r}, branch {b}, file `{p}`"
                      for _, r, p, b in refs)
    return f"""

---
Input files: read these yourself from GitHub before you start (they are part of the task):
{lines}"""

def pasted_files(files):
    out = []
    for ref, text in files:
        if ref[0] == "drive":
            head = f"File `{ref[1]}` (shared drive)"
        else:
            _, r, p, b = ref
            head = f"File `{p}` (repository {r}, branch {b})"
        out.append(f"""

---
{head}:
```

{text}

```""")
    return "".join(out)

def push_instruction(tid, repo, save_to):
    folder = save_to[:-3] if save_to.endswith(".md") else save_to + ".files"
    return f"""

---
Relay instructions (from the automation that sent this task):
When you have completely finished, save your work yourself to the GitHub repository
{repo}, branch main:
- your complete final answer, as Markdown, in `{save_to}`
- any files you created, in the folder `{folder}/` (keep their names)
Commit with the message "relay: {tid}", then reply with the commit URL. If you cannot push,
say exactly why."""
SAVE_PART = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. -]{0,99}$")

def save_path(value):
    """A safe relative path for save_to (no '..', no dot-files, no absolute paths)."""
    parts = value.strip().split("/")
    if value and len(parts) <= 8 and all(SAVE_PART.match(p) for p in parts):
        return "/".join(parts)
    return None

def chat_url(agent, chat):
    """The existing chat to continue, None for a new chat; refuses other sites."""
    chat = (chat or "").strip()
    if chat.lower() in ("", "new"):
        return None
    if agent in scripted.RECIPES:
        return scripted.chat_target(scripted.RECIPES[agent], chat)
    host = SITES[agent].split("/")[2]
    if re.match(rf"^https://{re.escape(host)}/\S*$", chat):
        return chat
    raise scripted.Failed(f"chat must be 'new' or a URL on {host}, not {chat!r}")

def repair_prompt(site, step, problem):
    return f"""Relay repair on {site['name']} ({site['url']}). A script is doing this task and
one of its checks failed. Fix only this, in the CURRENT tab, with as few actions as possible.

Step: {step}
Problem: {problem}

Allowed: take a snapshot, close popups/dialogs/banners (Escape or their close button), accept
a consent or intro screen, scroll, click "New chat". Not allowed: typing or sending any
message, opening other sites or tabs, logging in. The script re-checks the page afterwards.
Reply with one line: FIXED, or BLOCKED: <what the page says> if a person must act (login,
captcha, usage limit)."""

def task_status(result_text):
    """The `status:` line of a result file ('done', 'failed', ...), or '' if none."""
    m = re.search(r"^status:[ \t]*(\S+)", result_text or "", re.M)
    return m.group(1).lower() if m else ""

def after_ids(value):
    """'d025, d026' -> ['d025', 'd026']; ValueError on an id that is not safe."""
    ids = [x.strip() for x in (value or "").split(",") if x.strip()]
    for tid in ids:
        if not SAFE_ID.match(tid):
            raise ValueError(f"after: {tid!r} is not a task id")
    return ids

def expect_texts(value):
    """'STATUS: GENERATED | FILE: a.py' -> ['STATUS: GENERATED', 'FILE: a.py']."""
    return [x.strip() for x in (value or "").split("|") if x.strip()]

def missing_expected(meta, reply):
    """The `expect:` texts that are not in the answer."""
    answer = reply.split("ANSWER:", 1)[1] if "ANSWER:" in reply else reply
    return [t for t in expect_texts(meta.get("expect")) if t not in answer]

def parse_task(text):
    head, sep, body = text.partition("\n---")
    if not sep:
        return {}, text.strip()
    meta = {}
    for line in head.splitlines():
        k, colon, v = line.partition(":")
        if colon and k.strip():
            meta[k.strip().lower()] = v.strip()
    return meta, body.lstrip("-\n").strip()

def instruction(tid, meta, task):
    agent = meta.get("agent", "").lower()
    site = SITES[agent]
    done = meta.get("done_when") or "the agent says it has finished and gives its final answer"
    chat = chat_url(agent, meta.get("chat"))
    opening = (f"Open this existing {agent} chat: {chat} and continue it (do NOT start a new "
               "chat)." if chat else
               f"Open {site} ({agent}). Start a NEW chat (do not reuse an old one).")
    if meta.get("model") or meta.get("effort"):
        opening += (f" Before sending, set the site's model picker to model "
                    f"'{meta.get('model') or 'unchanged'}' and thinking level "
                    f"'{meta.get('effort') or 'unchanged'}'.")
    return f"""Relay task {tid}. You are only the messenger between the director and another AI agent.

1. {opening} Get past intro screens.
   If it requires login, a captcha or a paid plan, stop and reply starting with "BLOCKED:"
   and quote what the page says.
2. Paste the TASK below exactly as written (one message) and submit it.
3. Wait until the agent has really finished: done when {done}. Long work can take many
   minutes: keep calling browser_wait_stable. If the agent asks a question, answer only from
   the TASK text; if the TASK does not answer it, reply "Use your best judgement and continue."
4. When it is done, copy the agent's final answer VERBATIM with browser_evaluate (the text
   of its last message, not your summary) and take one screenshot.
5. Your final reply must be exactly:
   STATUS: done | blocked | failed
   CHAT_URL: <the chat page URL>
   ANSWER:
   <the agent's final answer, verbatim>

TASK:
{task}"""

class Relay:
    def __init__(self, agent, bus_dir, git_lock, bus_sync, bus_push, log, drop_save=None,
                 claims_dir=None, drop_check=None, drop_repo="", downloads=None,
                 read_file=None, agents=None, exclude=(), lane=0, new_window=False,
                 shared_browser=False, tab_lock=None, attach_dir=None):
        self.agent, self.root, self.log = agent, Path(bus_dir), log
        # Lanes: each Relay runs only its own agents' tasks (agents=None: all but exclude),
        # on its own browser connection, so lanes for different sites run at the same time.
        self.agents, self.exclude, self.lane = agents, set(exclude), lane
        self.new_window = new_window  # open each task in its own window (fully rendered)
        self.shared_browser = shared_browser  # other lanes use this browser: never wipe tabs
        self.busy = False
        self.tab_lock = tab_lock  # shared by all lanes: tab-list changes one lane at a time
        self.attach_dir = attach_dir  # where `attach:` files are put for the browser to upload
        self.attach_paths, self.attach_fallback = [], ""
        # Attempt counts live outside the repo: they survive restarts and are never pushed.
        self.claims = Path(claims_dir or Path(bus_dir).parent / "relay-claims")
        self.rerun, self.question = False, None
        self.gap, self.last_use, self.paced = GAP, 0.0, 0
        self.bus_sync, self.bus_push = bus_sync, bus_push
        self.drop_save = drop_save  # (path, content, message) -> (ok, where); None: bus
        self.drop_check = drop_check  # (path, since) -> (ok, commit): did it land in drop?
        self.drop_repo, self.downloads = drop_repo, downloads
        self.read_file = read_file  # (repo, path, branch) -> text, for agents that cannot
        self.lock = git_lock  # the bus clone is shared with the git bus thread

    def pending(self):
        tasks = self.root / "tasks"
        if not tasks.is_dir():
            return []
        out = []
        for p in sorted(tasks.glob("*.md")):
            tid = p.stem
            if tid.endswith(".result") or not SAFE_ID.match(tid):
                continue
            if (tasks / f"{tid}.result.md").exists():
                continue
            if self.agents is not None or self.exclude:
                try:
                    agent = parse_task(p.read_text(encoding="utf-8"))[0].get("agent", "").lower()
                except OSError:
                    continue
                if (agent not in self.agents) if self.agents is not None else (agent in self.exclude):
                    continue  # another lane's task
            out.append(p)
        return out

    def dependency_state(self, path, seen=None):
        """('ready', '') | ('wait', 'd025') | ('blocked', why) | ('failed', why) for a
        pending task, from its `after:` header and the dependencies' result files."""
        tasks = self.root / "tasks"
        meta, _ = parse_task(path.read_text(encoding="utf-8"))
        try:
            deps = after_ids(meta.get("after"))
        except ValueError as exc:
            return "failed", str(exc)
        seen = (seen or set()) | {path.stem}
        for dep in deps:
            if dep in seen:
                return "failed", f"dependency cycle through {dep}"
            result = tasks / f"{dep}.result.md"
            if result.exists():
                status = task_status(result.read_text(encoding="utf-8"))
                if status != "done":
                    return "blocked", f"dependency {dep} ended {status or 'without a status'}"
                continue
            dep_task = tasks / f"{dep}.md"
            if not dep_task.exists():
                return "failed", f"dependency {dep} does not exist (no task, no result)"
            state, why = self.dependency_state(dep_task, seen)
            if state == "failed" and why.startswith("dependency cycle"):
                return state, why
            return "wait", dep
        return "ready", ""

    def _wait_idle(self, timeout=None):
        start = time.time()
        while self.agent.running:
            if timeout and time.time() - start > timeout:
                return False
            time.sleep(5)
        return True

    def pace(self):
        """Wait out the pause after the previous task that used a site."""
        wait = self.last_use + self.gap - time.time()
        self.paced = max(0, int(round(wait)))
        if wait > 0:
            self.log(f"relay: pausing {self.paced} s between tasks")
            time.sleep(wait)

    def run_guarded(self, path):
        """run_one with an attempt count: a crash or a restart mid-task gets one re-run,
        then the task is closed as failed instead of being retried forever."""
        tid = path.stem
        claim = self.claims / tid
        try:
            prior = json.loads(claim.read_text("utf-8"))
        except (OSError, ValueError):
            prior = {"attempts": 0, "error": ""}
        meta, _ = parse_task(path.read_text(encoding="utf-8"))
        if prior["attempts"] >= MAX_ATTEMPTS:
            self.claims.mkdir(parents=True, exist_ok=True)
            claim.unlink(missing_ok=True)
            return self.finish(tid, meta, "failed", "FAILED: the task did not finish in "
                               f"{MAX_ATTEMPTS} attempts (crash or host restart). Last error: "
                               f"{prior['error'] or 'none recorded (cut off by a restart)'}", "")
        self.claims.mkdir(parents=True, exist_ok=True)
        # The chat URL is kept across attempts: a re-run collects from that chat instead of
        # asking again (a restart mid-task used to leave the old chat working, plus a new one).
        self.claim_path = claim
        self.claim_state = {"attempts": prior["attempts"] + 1, "error": "",
                            "chat": prior.get("chat", "")}
        claim.write_text(json.dumps(self.claim_state), "utf-8")
        self.rerun = prior["attempts"] > 0
        self.resume_chat = prior.get("chat", "") if self.rerun else ""
        self.busy = True
        try:
            status = self.run_one(path)
        except Exception as exc:
            self.log(f"relay: task {tid} crashed:", exc)
            self.claim_state["error"] = f"{type(exc).__name__}: {exc}"
            claim.write_text(json.dumps(self.claim_state), "utf-8")
            return "crashed"
        finally:
            self.busy = False
        claim.unlink(missing_ok=True)
        return status

    def _fetch_ref(self, ref):
        """Read one read:/attach: ref. Drive refs go through drive.read_text."""
        if ref[0] == "drive":
            return drive.read_text(ref[1])
        return self.read_file(ref[1], ref[2], ref[3])

    def run_one(self, path):
        tid = path.stem
        meta, task = parse_task(path.read_text(encoding="utf-8"))
        self.question = task  # the answer file shows the task as written, not pasted inputs
        agent = meta.get("agent", "").lower()
        if agent not in SITES:  # allowlist: only these sites, no free URLs
            return self.finish(tid, meta, "failed",
                               f"agent '{agent}' is not on the allowlist {sorted(SITES)}", "")
        save_to_raw = (meta.get("save_to") or "").strip()
        if save_to_raw.startswith("drive:"):
            try:
                drive.parse_ref(save_to_raw)
            except drive.DriveError as exc:
                return self.finish(tid, meta, "failed",
                                   f"save_to {save_to_raw!r}: {exc}", "")
            if not drive.enabled():
                return self.finish(tid, meta, "failed",
                                   "save_to: drive is not configured "
                                   "(BH_DRIVE_TOKEN is not set)", "")
        elif save_to_raw and not save_path(save_to_raw):
            return self.finish(tid, meta, "failed", f"save_to {save_to_raw!r} is not a "
                               "safe relative path (letters, digits, _ . - space, folders)", "")
        try:
            chat_url(agent, meta.get("chat"))
        except scripted.Failed as exc:
            return self.finish(tid, meta, "failed", str(exc), "")
        if meta.get("collect"):
            why = self.collect_problem(agent, meta["collect"].strip())
            if why:
                return self.finish(tid, meta, "failed", f"collect: {why}", "")
        try:
            refs = read_refs(meta.get("read"))
        except ValueError as exc:
            return self.finish(tid, meta, "failed", str(exc), "")
        if any(r[0] == "drive" for r in refs) and not drive.enabled():
            return self.finish(tid, meta, "failed",
                               "read: drive is not configured (BH_DRIVE_TOKEN is not set)", "")
        if refs:
            if agent in PUSHERS:  # the agent reads GitHub itself; the box fetches drive
                self_read = [r for r in refs if r[0] == "github"]
                box_read = [r for r in refs if r[0] == "drive"]
            else:
                self_read, box_read = [], list(refs)
            if self_read:
                task = task + read_instruction(self_read)
            if box_read:
                files = []
                for ref in box_read:
                    try:
                        files.append((ref, self._fetch_ref(ref)))
                    except drive.DriveError as exc:
                        return self.finish(tid, meta, "failed",
                                           f"could not read {ref_label(ref)}: {exc}", "", task)
                    except Exception as exc:
                        return self.finish(tid, meta, "failed",
                                           f"could not read {ref_label(ref)}: "
                                           f"{type(exc).__name__}: {exc}", "", task)
                task = task + pasted_files(files)
        self.attach_paths, self.attach_fallback = [], ""
        try:
            attach = read_refs(meta.get("attach"))
        except ValueError as exc:
            return self.finish(tid, meta, "failed", str(exc).replace("read:", "attach:"), "")
        if any(r[0] == "drive" for r in attach) and not drive.enabled():
            return self.finish(tid, meta, "failed",
                               "attach: drive is not configured (BH_DRIVE_TOKEN is not set)", "")
        site = scripted.RECIPES.get(agent, {})
        if attach and agent in PUSHERS:  # agents that push read their GitHub inputs themselves
            self_read = [r for r in attach if r[0] == "github"]
            attach = [r for r in attach if r[0] == "drive"]
            if self_read:
                task = task + read_instruction(self_read)
        if attach and (not site.get("attach") or meta.get("mode", "").lower() == "agent"):
            files = []  # no attach control here: paste them, as with read:
            for ref in attach:
                try:
                    files.append((ref, self._fetch_ref(ref)))
                except drive.DriveError as exc:
                    return self.finish(tid, meta, "failed",
                                       f"could not read {ref_label(ref)}: {exc}", "", task)
                except Exception as exc:
                    return self.finish(tid, meta, "failed",
                                       f"could not read {ref_label(ref)}: "
                                       f"{type(exc).__name__}: {exc}", "", task)
            task, attach = task + pasted_files(files), []
        if attach:  # the box fetches them; the coded steps upload them before sending
            files = []
            folder = Path(self.attach_dir or (self.root.parent / "attach")) / tid
            folder.mkdir(parents=True, exist_ok=True)
            for ref in attach:
                try:
                    text = self._fetch_ref(ref)
                except drive.DriveError as exc:
                    return self.finish(tid, meta, "failed",
                                       f"could not read {ref_label(ref)}: {exc}", "", task)
                except Exception as exc:
                    return self.finish(tid, meta, "failed",
                                       f"could not read {ref_label(ref)}: "
                                       f"{type(exc).__name__}: {exc}", "", task)
                name = ref[1] if ref[0] == "drive" else ref[2]
                local = folder / (save_path(Path(name).name) or "file.txt")
                local.write_text(text, encoding="utf-8")
                files.append((ref, text))
                self.attach_paths.append(str(local))
            self.attach_fallback = task + pasted_files(files)
            task = task + "\n\n(Attached: " + ", ".join(Path(p).name for p in self.attach_paths) \
                + ". Read the attached files before answering.)"
        chaos = meta.get("chaos", "").strip().lower()
        if chaos and chaos not in scripted.CHAOS:
            return self.finish(tid, meta, "failed", f"chaos must be one of "
                               f"{', '.join(scripted.CHAOS)}, not {meta['chaos']!r}", "")
        effort = meta.get("effort", "").strip().lower()
        if effort and effort not in scripted.EFFORTS:
            return self.finish(tid, meta, "failed", f"effort must be one of "
                               f"{', '.join(scripted.EFFORTS)}, not {meta['effort']!r}", "")
        site = scripted.RECIPES.get(agent, {})
        try:
            for name in site.get("toggles", {}):
                if meta.get(name):
                    scripted.toggle_value(name, meta[name])
        except scripted.Failed as exc:
            return self.finish(tid, meta, "failed", str(exc), "")
        mode = meta.get("mode", "").lower()
        self.pace()  # only tasks that reach the site wait; rejected ones above did not
        if agent in scripted.RECIPES and mode != "agent":
            return self.run_scripted(tid, meta, task, scripted.RECIPES[agent])
        self._wait_idle()
        # each relay task starts from a clean conversation (and browser, unless lanes share it)
        self.agent.reset(fresh_browser=not self.shared_browser)
        start_event = len(self.agent.events)
        started = time.time()
        try:
            self.agent.send(instruction(tid, meta, task))
            time.sleep(2)
            self._wait_idle()
        finally:
            self.last_use = time.time()
        events = self.agent.events[start_event:]
        replies = [e.get("text", "") for e in events if e.get("type") == "reply"]
        reply = replies[-1] if replies else ""
        m = re.search(r"STATUS:\s*(done|blocked|failed)", reply, re.I)
        status = m.group(1).lower() if m else ("blocked" if "BLOCKED:" in reply else "unclear")
        shots = [i for e in events for i in (e.get("images") or [])]
        evidence = (f"- relay run: {int(time.time() - started)} s, {len(events)} agent events\n"
                    + (f"- paused {self.paced} s first (pause between tasks)\n"
                       if self.paced else "")
                    + "".join(f"- screenshot: {s}\n" for s in shots))
        return self.finish(tid, meta, status, reply or "(no reply from the browser agent)", evidence,
                           task)

    def assist(self, site, step, problem, check=None, timeout=600):
        """Hand one failed step to the Sarvam agent: step-limited, tabs kept, and stopped
        as soon as the script's own check passes (left alone, it keeps clicking)."""
        self._wait_idle()
        self.agent.reset(fresh_browser=False)
        start = len(self.agent.events)
        self.agent.step_limit = ASSIST_STEPS
        self.agent.tab_guard = self.shared_browser  # no tab opening/closing beside other lanes
        fixed = False
        try:
            self.agent.send(repair_prompt(site, step, problem), force=True)
            end = time.time() + timeout
            while self.agent.running and time.time() < end:
                time.sleep(3)
                try:
                    fixed = bool(check and check())
                except Exception:
                    fixed = False
                if fixed:
                    break
            if self.agent.running:
                self.agent.stop()
                self._wait_idle(timeout=200)
        finally:
            self.agent.step_limit = 0
            self.agent.tab_guard = False
        if fixed:
            return "FIXED (the script's check passed; the model was stopped)"
        replies = [e.get("text", "") for e in self.agent.events[start:] if e.get("type") == "reply"]
        return replies[-1] if replies else ""

    def run_scripted(self, tid, meta, task, site):
        self._wait_idle()
        self.agent.reserved_by = f"relay task {tid}"  # chat sends would reset our tabs
        try:
            return self._run_scripted(tid, meta, task, site)
        finally:
            self.agent.reserved_by = ""
            self.last_use = time.time()

    def _run_scripted(self, tid, meta, task, site):
        try:
            timeout = max(1, min(int(meta.get("timeout_min") or 30), 240)) * 60
        except ValueError:
            timeout = 1800
        started = time.time()
        def assist(step, problem, check):
            return self.assist(site, step, problem, check)
        chat = scripted.ScriptedChat(self.agent.call_tool, self.agent.save_image, assist,
                                     self.log)
        chat.new_window, chat.tab_lock = self.new_window, self.tab_lock
        raw_save = (meta.get("save_to") or "").strip()
        drive_save = raw_save.startswith("drive:")
        save_to = None if drive_save else save_path(raw_save)
        resume = getattr(self, "resume_chat", "")
        collect = resume or (self.collect_url(meta["collect"].strip()) if meta.get("collect") else "")
        pushes = bool(site["name"] in PUSHERS and save_to and self.drop_repo
                      and self.drop_check) and not collect
        sent = task + push_instruction(tid, self.drop_repo, save_to) if pushes else task
        keep = bool((save_to or drive_save) and site.get("file_card"))
        options = {k: meta[k] for k in site.get("toggles", {}) if meta.get(k)}

        def on_sent(url):  # remembered for a re-run after a restart
            state = getattr(self, "claim_state", None)
            if state is not None:
                state["chat"] = url
                self.claim_path.write_text(json.dumps(state), "utf-8")
        if collect:
            out = chat.run(site, "", timeout, collect, keep_open=keep, collect=True)
        else:
            out = chat.run(site, sent, timeout, meta.get("chat"), meta.get("model"),
                           meta.get("effort"), keep_open=keep, chaos=meta.get("chaos", ""),
                           options=options, on_sent=on_sent, attachments=self.attach_paths,
                           fallback_text=self.attach_fallback)
        if (out["status"] == "failed" and BROWSER_GONE.search(out["answer"])
                and not getattr(self, "rerun", False)):
            # The browser went away under the task (crash, restart, a tab-list glitch): one
            # re-run, which collects from the same chat if the question was already sent.
            raise BrowserGone(out["answer"][:300])
        self.pushed_by_agent, self.files = None, []
        if pushes and out["status"] == "done":
            self.pushed_by_agent = self.wait_push(save_to, started, chat)
        if keep and out["status"] == "done":
            if not self.pushed_by_agent:  # not pushed: the box keeps the agent's files
                self.files = chat.download_files(site, self.downloads)
            chat.close_tab(chat.url)
        model = (f"MODEL: {out['model']} (thinking: {out['effort'] or '-'})\n"
                 if out.get("model") else
                 f"MODEL: {site['name']} ({out['options']})\n" if out.get("options") else "")
        reply = (f"STATUS: {out['status']}\nCHAT_URL: {out['chat_url']}\n{model}ANSWER:\n"
                 f"{out['answer']}")
        evidence = (f"- relay run: {int(time.time() - started)} s, mode scripted, lane {self.lane}, "
                    f"model repairs: {out['assists']}\n"
                    + ("- re-run after an earlier attempt was cut off or crashed\n"
                       if self.rerun else "")
                    + (f"- collected the reply from the existing chat {collect} (nothing sent "
                       + ("again: re-run after a restart" if resume else f"by collect: {meta.get('collect')}")
                       + ")\n" if collect else "")
                    + (f"- paused {self.paced} s first (pause between tasks)\n"
                       if self.paced else "")
                    + "".join(f"- screenshot: {s}\n" for s in out["shots"])
                    + "\nSteps:\n" + "".join(f"- {s}\n" for s in out["steps"]))
        if out["status"] == "done" and out["answer"].rstrip().endswith("?"):
            evidence += ("\nNote: the reply ends with a question; the agent may be waiting "
                         "for input rather than finished.\n")
        if meta.get("done_when"):
            evidence += f"\ndone_when (not checked by the scripted relay): {meta['done_when']}\n"
        if self.pushed_by_agent:
            evidence += (f"\n- {site['name']} pushed the answer to the drop repo itself; checked: "
                         f"{self.pushed_by_agent}\n")
        elif pushes and out["status"] == "done":
            evidence += (f"\n- {site['name']} did not push to the drop repo within {PUSH_WAIT} s; "
                         "the box saved the answer and files instead\n")
        return self.finish(tid, meta, out["status"], reply, evidence, task,
                           skip_answer=bool(self.pushed_by_agent), files=self.files)

    def collect_url(self, ref):
        """The CHAT_URL recorded in task `ref`'s result, or ''."""
        p = self.root / "tasks" / f"{ref}.result.md"
        m = re.search(r"^CHAT_URL:[ \t]*(\S+)", p.read_text(encoding="utf-8"), re.M) \
            if SAFE_ID.match(ref) and p.exists() else None
        return m.group(1) if m else ""

    def collect_problem(self, agent, ref):
        if agent not in scripted.RECIPES:
            return f"agent {agent!r} has no coded steps to collect with"
        if not SAFE_ID.match(ref):
            return f"{ref!r} is not a task id"
        url = self.collect_url(ref)
        if not url:
            return f"task {ref} has no result with a CHAT_URL to collect from"
        try:
            scripted.chat_target(scripted.RECIPES[agent], url)
        except scripted.Failed:
            return f"task {ref}'s chat {url} is not a {agent} chat"
        return ""

    def wait_push(self, save_to, since, chat):
        """Poll the drop repo for the agent's commit of save_to; never trust its reply."""
        end = time.time() + PUSH_WAIT
        while True:
            try:
                ok, info = self.drop_check(save_to, since)
            except Exception as exc:
                ok, info = False, f"{type(exc).__name__}: {exc}"
            if ok:
                chat.note(f"agent push found in the drop repo: {info}")
                return info
            if time.time() >= end:
                chat.note(f"agent push not found in the drop repo ({info})")
                return None
            time.sleep(10)

    @staticmethod
    def answer_file(tid, meta, status, reply, task, finished):
        chat = re.search(r"^CHAT_URL:[ \t]*(\S*)", reply, re.M)
        model = re.search(r"^MODEL:[ \t]*(.+)$", reply.split("ANSWER:", 1)[0], re.M)
        answer = reply.split("ANSWER:", 1)[1].strip() if "ANSWER:" in reply else reply.strip()
        return (f"# {tid} ({meta.get('agent', '')})\n\n- status: {status}\n"
                f"- chat: {chat.group(1) if chat and chat.group(1) else '(none)'}\n"
                f"- model: {model.group(1).strip() if model else '(not recorded)'}\n"
                f"- finished: {finished}\n\n## Question\n\n{task}\n\n## Answer\n\n{answer}\n")

    def save(self, rel, content, message):
        try:
            return (self.drop_save(rel, content, message) if self.drop_save
                    else (False, "no drop repo on this host"))
        except Exception as exc:  # the answer must still be recorded, never re-asked
            return False, f"drop repo error: {type(exc).__name__}: {exc}"

    def _append_drive_history(self, tid, meta, status, drive_path, finished):
        first = drive_path.split("/", 1)[0]
        month = time.strftime("%Y-%m", time.gmtime())
        hist = f"{first}/history/{month}.md"
        line = f"- {finished} {tid} {meta.get('agent', '')} {status} -> {drive_path}"
        try:
            drive.append_line(hist, line)
            return f"\n- drive history line appended to drive:{hist}\n"
        except Exception as exc:
            return f"\n- drive history line NOT appended ({type(exc).__name__}: {exc})\n"

    def finish(self, tid, meta, status, reply, evidence, task="", skip_answer=False, files=()):
        finished = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        if status == "done" and meta.get("expect"):
            missing = missing_expected(meta, reply)
            if missing:  # the answer is kept; the chain after this task stops
                status = "failed"
                evidence += ("\nexpect: check FAILED, not in the answer: "
                             + "; ".join(repr(t) for t in missing) + "\n")
            else:
                evidence += f"\nexpect: check passed ({len(expect_texts(meta['expect']))} texts)\n"
        raw_save = (meta.get("save_to") or "").strip()
        drive_save = raw_save.startswith("drive:")
        save_to = None if drive_save else save_path(raw_save)
        drive_path = None
        if drive_save:
            try:
                drive_path = drive.parse_ref(raw_save)
            except drive.DriveError:
                drive_path = None
        on_bus = []
        content = None
        if (save_to or drive_path) and not skip_answer:
            question = self.question if self.question is not None else task
            if meta.get("read"):
                question += f"\n\n(input files: {meta['read']})"
            content = self.answer_file(tid, meta, status, reply, question, finished)
        if drive_path:
            if content is not None and drive.enabled():
                try:
                    drive.save_text(drive_path, content, overwrite=True)
                    evidence += f"\n- answer saved to the drive: drive:{drive_path}\n"
                except drive.DriveError as exc:
                    on_bus.append((f"drop/{drive_path}", content))
                    evidence += (f"\n- drive save FAILED ({exc}); answer kept at "
                                 f"drop/{drive_path} on the bus branch\n")
            elif content is not None:
                on_bus.append((f"drop/{drive_path}", content))
                evidence += (f"\n- drive save skipped (drive not configured); answer kept at "
                             f"drop/{drive_path} on the bus branch\n")
            if drive.enabled():
                evidence += self._append_drive_history(tid, meta, status, drive_path, finished)
        elif save_to and content is not None:
            ok, where = self.save(save_to, content, f"relay: {tid} ({status})")
            if ok:
                evidence += f"\n- answer saved to the drop repo: {where}\n"
            else:
                on_bus.append((f"drop/{save_to}", content))
                evidence += f"\n- answer saved to drop/{save_to} on the bus branch ({where})\n"
        base = drive_path if drive_path else save_to
        folder = (base[:-3] if base.endswith(".md") else base + ".files") if base else ""
        for name, path in files:
            safe = save_path(name.replace("/", "_"))
            if not (path and safe):
                evidence += f"- file {name!r}: not saved (no download)\n"
                continue
            data = path.read_bytes()
            ok, where = self.save(f"{folder}/{safe}", data, f"relay: {tid} file {safe}")
            if ok:
                evidence += f"- file saved to the drop repo: {where}\n"
            else:
                on_bus.append((f"drop/{folder}/{safe}", data))
                evidence += f"- file saved to drop/{folder}/{safe} on the bus branch ({where})\n"
        result = (f"# Result for task {tid}\n\nstatus: {status}\nagent: {meta.get('agent', '')}\n"
                  f"finished: {finished}\n\n"
                  f"## Browser agent report\n\n{reply}\n\n## Evidence\n\n{evidence}")
        with self.lock:
            self.bus_sync()
            for rel, data in on_bus:
                path = self.root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(data, bytes):
                    path.write_bytes(data)
                else:
                    path.write_text(data, encoding="utf-8")
            (self.root / "tasks" / f"{tid}.result.md").write_text(result, encoding="utf-8")
            pushed = self.bus_push(f"relay: result for {tid} ({status})")
        ping = meta.get("ping")
        if ping and ping.startswith("https://"):
            try:
                req = urllib.request.Request(ping, json.dumps({
                    "id": tid, "status": status, "result": f"tasks/{tid}.result.md",
                    "pushed": pushed}).encode(), {"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=20).read()
            except Exception as exc:
                self.log("relay ping failed:", exc)
        self.log(f"relay: task {tid} -> {status}")
        return status

    def run_ready(self):
        """One pass over the queue in name order: run tasks whose `after:` chain is done,
        close those whose chain failed, leave the rest for a later pass."""
        for path in self.pending():
            if (self.root / "tasks" / f"{path.stem}.result.md").exists():
                continue  # closed earlier in this pass (a blocked chain)
            state, why = self.dependency_state(path)
            if state == "wait":
                continue
            if state in ("blocked", "failed"):
                meta, _ = parse_task(path.read_text(encoding="utf-8"))
                self.finish(path.stem, meta, state, f"{state.upper()}: not run: {why}",
                            "- not run: its `after:` chain did not complete\n")
                continue
            self.run_guarded(path)

    def loop(self, interval=15):
        if not ENABLED:
            self.log("relay: inactive (ENABLED is False); not starting")
            return
        while True:
            try:
                with self.lock:
                    self.bus_sync()
                self.run_ready()
            except Exception as exc:
                self.log(f"relay lane {self.lane} error:", exc)
            time.sleep(interval)
```

FILE: tests/test_drive.py
```python
"""Tests for browser_host/drive.py and the relay's drive integration."""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "browser_host"))

import drive  # noqa: E402
import relay  # noqa: E402

class FakeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

class FakeReply:
    def __init__(self, data, offset, size, eof):
        self.data = data
        self.offset = offset
        self.observed_size = size
        self.observed_mtime_ns = 0
        self.eof_observed = eof

class FakeClient:
    def __init__(self):
        self.files = {}
        self.ops = []

    def list(self, source_id, file_id="root", limit=20, offset=0, name_contains=None):
        self.ops.append(("list", file_id))
        return {"entries": [{"name": k} for k in sorted(self.files)]}

    def find(self, source_id, file_id="root", name_contains="", limit=20,
             max_entries=2000, max_depth=4):
        self.ops.append(("find", file_id, name_contains))
        return {"entries": [{"name": k} for k in sorted(self.files) if name_contains in k]}

    def read(self, source_id, file_id, offset=0, length=262144):
        self.ops.append(("read", file_id, offset, length))
        path = file_id[2:] if file_id.startswith("p/") else ""
        data = self.files.get(path)
        if data is None:
            raise FakeError("not_found")
        chunk = data[offset:offset + length]
        eof = offset + len(chunk) >= len(data)
        return FakeReply(chunk, offset, len(data), eof)

    def save(self, source_id, file_id, data, overwrite=False, create_parents=True):
        self.ops.append(("save", file_id, len(data), overwrite))
        path = file_id[2:]
        if path in self.files and not overwrite:
            raise FakeError("exists")
        self.files[path] = data
        return {"file_id": file_id, "size": len(data)}

class ParseRefTests(unittest.TestCase):
    def test_accepts(self):
        self.assertEqual(drive.parse_ref("drive:proj/notes/a.md"), "proj/notes/a.md")
        self.assertEqual(drive.parse_ref("drive:a"), "a")
        self.assertEqual(drive.parse_ref("drive:a/b/c-d_e.f"), "a/b/c-d_e.f")

    def test_non_drive_is_none(self):
        self.assertIsNone(drive.parse_ref("owner/repo:path"))
        self.assertIsNone(drive.parse_ref("https://example.com/x"))

    def test_rejects_bad_paths(self):
        for bad in ["drive:/abs", "drive:..", "drive:a/../b", "drive:a//b",
                    "drive:.", "drive:a/.", "drive:a/$bad", "drive:"]:
            with self.assertRaises(drive.DriveError):
                drive.parse_ref(bad)

class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.patcher = mock.patch.object(drive, "_client", lambda: self.client)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        os.environ["BH_DRIVE_TOKEN"] = "x" * 32
        self.addCleanup(os.environ.pop, "BH_DRIVE_TOKEN", None)

    def test_save_and_read(self):
        drive.save_text("proj/a.md", "hello")
        self.assertEqual(drive.read_text("proj/a.md"), "hello")

    def test_read_chunks(self):
        self.client.files["big"] = b"a" * 300000
        self.assertEqual(drive.read_text("big"), "a" * 300000)

    def test_read_missing(self):
        with self.assertRaises(drive.DriveError) as ctx:
            drive.read_text("nope")
        self.assertEqual(ctx.exception.code, "not_found")

    def test_append_line(self):
        drive.append_line("log/x.md", "one")
        drive.append_line("log/x.md", "two")
        self.assertEqual(drive.read_text("log/x.md"), "one\ntwo\n")

    def test_save_too_large(self):
        with self.assertRaises(drive.DriveError) as ctx:
            drive.save_text("x", "a" * (1048576 + 1))
        self.assertEqual(ctx.exception.code, "too_large")

class FakeAgent:
    def __init__(self, answer="STATUS: done\nCHAT_URL: https://chatgpt.com/c/1\nANSWER:\ndone"):
        self.running = False
        self.events = []
        self.answer = answer
        self.sent = []
        self.step_limit = 0
        self.tab_guard = False
        self.reserved_by = ""

    def reset(self, fresh_browser=True):
        pass

    def send(self, text, force=False):
        self.sent.append(text)
        self.events.append({"type": "reply", "text": self.answer})

    def call_tool(self, *a, **k):
        return {}

    def save_image(self, *a, **k):
        return None

    def stop(self):
        self.running = False

def make_relay(tmpdir, agent=None):
    bus = Path(tmpdir) / "bus"
    (bus / "tasks").mkdir(parents=True, exist_ok=True)
    agent = agent or FakeAgent()
    r = relay.Relay(
        agent=agent,
        bus_dir=bus,
        git_lock=threading.Lock(),
        bus_sync=lambda: None,
        bus_push=lambda msg: False,
        log=lambda *a, **k: None,
        claims_dir=Path(tmpdir) / "claims",
        read_file=lambda repo, path, branch: f"github:{repo}:{path}",
        shared_browser=True,
    )
    r.gap = 0
    return r, agent, bus

class RelayDriveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ.pop("BH_DRIVE_TOKEN", None)

    def test_drive_disabled_read_fails_before_sending(self):
        r, agent, bus = make_relay(self.tmp.name)
        (bus / "tasks" / "d1.md").write_text(
            "agent: chatgpt\nread: drive:proj/a.md\n---\nDo it.\n")
        status = r.run_one(bus / "tasks" / "d1.md")
        self.assertEqual(status, "failed")
        self.assertEqual(agent.sent, [])
        result = (bus / "tasks" / "d1.result.md").read_text(encoding="utf-8")
        self.assertIn("drive is not configured", result)

    def test_drive_read_is_pasted(self):
        client = FakeClient()
        client.files["proj/a.md"] = b"# Notes\nremember this"
        os.environ["BH_DRIVE_TOKEN"] = "x" * 32
        self.addCleanup(os.environ.pop, "BH_DRIVE_TOKEN", None)
        with mock.patch.object(drive, "_client", lambda: client), mock.patch("time.sleep"):
            r, agent, bus = make_relay(self.tmp.name)
            (bus / "tasks" / "d2.md").write_text(
                "agent: chatgpt\nread: drive:proj/a.md\n---\nDo it.\n")
            status = r.run_one(bus / "tasks" / "d2.md")
        self.assertEqual(status, "done")
        sent = agent.sent[0]
        self.assertIn("remember this", sent)
        self.assertIn("proj/a.md", sent)

    def test_drive_save_to_and_history(self):
        client = FakeClient()
        os.environ["BH_DRIVE_TOKEN"] = "x" * 32
        self.addCleanup(os.environ.pop, "BH_DRIVE_TOKEN", None)
        with mock.patch.object(drive, "_client", lambda: client), mock.patch("time.sleep"):
            r, agent, bus = make_relay(self.tmp.name)
            (bus / "tasks" / "d3.md").write_text(
                "agent: chatgpt\nsave_to: drive:proj/out/a.md\n---\nDo it.\n")
            status = r.run_one(bus / "tasks" / "d3.md")
        self.assertEqual(status, "done")
        self.assertIn("proj/out/a.md", client.files)
        answer = client.files["proj/out/a.md"].decode("utf-8")
        self.assertIn("## Answer", answer)
        month = time.strftime("%Y-%m", time.gmtime())
        hist = f"proj/history/{month}.md"
        self.assertIn(hist, client.files)
        line = client.files[hist].decode("utf-8")
        self.assertIn("d3", line)
        self.assertIn("chatgpt", line)
        self.assertIn("done", line)
        self.assertIn("proj/out/a.md", line)

if __name__ == "__main__":
    unittest.main()
```
```
