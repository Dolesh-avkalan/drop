# dt06b-deepseek (deepseek)

- status: failed
- chat: (none)
- model: (not recorded)
- finished: 2026-10-16T12:42:10Z

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

could not read Dolesh-avkalan/browser-tool:browser_host/relay.py@main: HTTPError: HTTP Error 404: Not Found
