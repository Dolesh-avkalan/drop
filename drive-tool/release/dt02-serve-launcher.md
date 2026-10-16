# dt02-deepseek (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/62243d07-c2a7-4817-9789-6d35349741b7
- model: deepseek (deepthink off, search off)
- finished: 2026-10-16T12:26:01Z

## Question

DeepSeek, I need you to implement a small launcher for drive-tool (Python 3.11+, standard library only). The attached files are the existing policy model (service_policy.py), the HTTP adapter (http_adapter.py: DriveHTTPAdapter(policies, port=...), .port, .close(timeout=5.0) returns bool) and the agent client (service_client.py: DriveClient(port=..., token=...)). Do not change them.

Write two new files.

1. drive_tool/serve.py
- Config is a JSON file: {"port": int 0..65535, "agents": [{"agent_id": str, "token_sha256": "<64 lowercase hex>", "grants": [{"alias": str, "root": "/abs/dir", "operations": ["list","find","read","save"], "max_read_bytes": int optional, "max_write_bytes": int optional}]}]}
- load_config(path) -> (port, tuple[AgentPolicy, ...]). Strict: reject duplicate JSON keys, unknown keys, wrong types (bool is not int), bad hex/length, empty agents, duplicate agent_id, duplicate token hash. Build SourceGrant/AgentPolicy from service_policy (operations as frozenset, token_sha256 as bytes) and let their own checks run. Every root must be an existing directory. Refuse a config file larger than 1 MiB or writable by group/others (mode & 0o022). Raise ConfigError(message); messages never contain token hashes.
- hash_token(token: str) -> lowercase sha256 hex of the UTF-8 token.
- run(config_path, *, ready=None, stop=None) -> int: load config, start DriveHTTPAdapter(policies, port=port), call ready(adapter.port) if given, wait until stop (a threading.Event) is set, then adapter.close(timeout=5.0); return 0 if close() returned True, else 1.
- main(argv=None) -> int: "python3 -m drive_tool.serve --config PATH" runs with SIGTERM/SIGINT setting the stop event and prints one line to stderr: "drive-tool listening on 127.0.0.1:<port> (<n> agents)". "python3 -m drive_tool.serve --hash-token" reads one line from stdin and prints its hash. ConfigError -> print "config error: <message>" to stderr, return 2. End with: if __name__ == "__main__": raise SystemExit(main())

2. tests/test_serve.py (unittest, temp dirs only, no network beyond 127.0.0.1)
- each rejection rule above has a test; a valid config loads; hash_token matches hashlib.
- end to end: temp root with a file, config with port 0, run() in a thread with ready/stop, then DriveClient lists, saves and reads back a file using the plain token, then stop is set and run() returns 0 and the thread ends.

Reply with exactly two blocks, each starting with a line "FILE: <path>" followed by the complete file in a ```python fence. No other files. Keep it small and plain; no frameworks, no extra features.

## Answer

FILE: drive_tool/serve.py

```python
"""Launcher for the drive-tool loopback HTTP service (standard library only).

Reads a strict JSON config file, builds the frozen policy objects from
``service_policy``, starts a :class:`DriveHTTPAdapter` on loopback, and waits
for a stop event. No filesystem access beyond config stat/read and the
``os.path.isdir`` root checks; no network beyond the adapter itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import threading

from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_policy import AgentPolicy, SourceGrant

__all__ = ["ConfigError", "load_config", "hash_token", "run", "main"]

_MAX_CONFIG_BYTES = 1024 * 1024
_OPERATIONS = frozenset({"list", "find", "read", "save"})
_HEX_DIGITS = frozenset("0123456789abcdef")

_TOP_KEYS = frozenset({"port", "agents"})
_AGENT_KEYS = frozenset({"agent_id", "token_sha256", "grants"})
_GRANT_REQUIRED_KEYS = frozenset({"alias", "root", "operations"})
_GRANT_OPTIONAL_KEYS = frozenset({"max_read_bytes", "max_write_bytes"})
_GRANT_KEYS = _GRANT_REQUIRED_KEYS | _GRANT_OPTIONAL_KEYS

class ConfigError(Exception):
    """Raised for any config load / validation failure."""

    __slots__ = ()

def _no_dup_keys(pairs):
    seen = set()
    out = {}
    for key, value in pairs:
        if key in seen:
            raise ConfigError("duplicate JSON key")
        seen.add(key)
        out[key] = value
    return out

def _no_nan_inf(value):
    raise ConfigError("non-finite JSON constant")

def _load_json(path):
    try:
        size = os.path.getsize(path)
    except OSError:
        raise ConfigError("cannot stat config file") from None
    if size > _MAX_CONFIG_BYTES:
        raise ConfigError("config file too large")
    try:
        mode = os.stat(path).st_mode
    except OSError:
        raise ConfigError("cannot stat config file") from None
    if mode & 0o022:
        raise ConfigError("config file must not be group/other writable")
    try:
        with open(path, "rb") as fh:
            raw = fh.read(_MAX_CONFIG_BYTES + 1)
    except OSError:
        raise ConfigError("cannot read config file") from None
    if len(raw) > _MAX_CONFIG_BYTES:
        raise ConfigError("config file too large")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ConfigError("config file must be valid UTF-8") from None
    try:
        return json.loads(
            text, object_pairs_hook=_no_dup_keys, parse_constant=_no_nan_inf
        )
    except ConfigError:
        raise
    except ValueError:
        raise ConfigError("config file is not valid JSON") from None

def _require_mapping(value, what):
    if not isinstance(value, dict):
        raise ConfigError("%s must be an object" % (what,))
    return value

def _require_keys(obj, required, allowed, what):
    keys = set(obj.keys())
    if not required.issubset(keys):
        raise ConfigError("%s is missing required keys" % (what,))
    if not keys.issubset(allowed):
        raise ConfigError("%s has unknown keys" % (what,))

def _parse_port(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("port must be an int")
    if value < 0 or value > 65535:
        raise ConfigError("port must be in 0..65535")
    return value

def _parse_token_sha256(value):
    if not isinstance(value, str):
        raise ConfigError("token_sha256 must be a string")
    if len(value) != 64:
        raise ConfigError("token_sha256 must be 64 lowercase hex characters")
    for ch in value:
        if ch not in _HEX_DIGITS:
            raise ConfigError("token_sha256 must be 64 lowercase hex characters")
    return bytes.fromhex(value)

def _parse_operations(value):
    if not isinstance(value, list):
        raise ConfigError("operations must be an array")
    if not value:
        raise ConfigError("operations must be non-empty")
    for op in value:
        if not isinstance(op, str):
            raise ConfigError("operations members must be strings")
        if op not in _OPERATIONS:
            raise ConfigError("operations contains an unsupported operation")
    return frozenset(value)

def _parse_cap(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("%s must be an int" % (name,))
    return value

def _parse_grant(value, index):
    what = "agents[%d].grants[%d]" % (index[0], index[1])
    _require_mapping(value, what)
    _require_keys(value, _GRANT_REQUIRED_KEYS, _GRANT_KEYS, what)

    alias = value["alias"]
    root = value["root"]
    operations = _parse_operations(value["operations"])
    max_read_bytes = _parse_cap(value.get("max_read_bytes"), "max_read_bytes")
    max_write_bytes = _parse_cap(value.get("max_write_bytes"), "max_write_bytes")

    if not isinstance(alias, str):
        raise ConfigError("%s.alias must be a string" % (what,))
    if not isinstance(root, str):
        raise ConfigError("%s.root must be a string" % (what,))

    kwargs = {}
    if max_read_bytes is not None:
        kwargs["max_read_bytes"] = max_read_bytes
    if max_write_bytes is not None:
        kwargs["max_write_bytes"] = max_write_bytes

    try:
        grant = SourceGrant(
            alias=alias, root=root, operations=operations, **kwargs
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError("%s is invalid: %s" % (what, exc)) from None

    if not os.path.isdir(grant.root):
        raise ConfigError("%s.root must be an existing directory" % (what,))
    return grant

def _parse_agent(value, index):
    what = "agents[%d]" % (index,)
    _require_mapping(value, what)
    _require_keys(value, _AGENT_KEYS, _AGENT_KEYS, what)

    agent_id = value["agent_id"]
    token_sha256 = _parse_token_sha256(value["token_sha256"])
    grants_raw = value["grants"]

    if not isinstance(agent_id, str):
        raise ConfigError("%s.agent_id must be a string" % (what,))
    if not isinstance(grants_raw, list):
        raise ConfigError("%s.grants must be an array" % (what,))
    if not grants_raw:
        raise ConfigError("%s.grants must be non-empty" % (what,))

    grants = tuple(
        _parse_grant(grant, (index, i)) for i, grant in enumerate(grants_raw)
    )

    try:
        return AgentPolicy(
            agent_id=agent_id, token_sha256=token_sha256, grants=grants
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError("%s is invalid: %s" % (what, exc)) from None

def load_config(path):
    """Load and validate the config file, returning ``(port, agents)``."""

    data = _load_json(path)
    _require_mapping(data, "config")
    _require_keys(data, _TOP_KEYS, _TOP_KEYS, "config")

    port = _parse_port(data["port"])
    agents_raw = data["agents"]
    if not isinstance(agents_raw, list):
        raise ConfigError("agents must be an array")
    if not agents_raw:
        raise ConfigError("agents must be non-empty")

    agents = tuple(
        _parse_agent(agent, i) for i, agent in enumerate(agents_raw)
    )

    seen_ids = set()
    seen_digests = set()
    for agent in agents:
        if agent.agent_id in seen_ids:
            raise ConfigError("duplicate agent_id")
        seen_ids.add(agent.agent_id)
        if agent.token_sha256 in seen_digests:
            raise ConfigError("duplicate token_sha256")
        seen_digests.add(agent.token_sha256)

    return port, agents

def hash_token(token):
    """Return the lowercase hex SHA-256 of a UTF-8 encoded token."""

    if not isinstance(token, str):
        raise TypeError("token must be a str")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def run(config_path, *, ready=None, stop=None):
    """Load config, start the adapter, wait for ``stop``, then close."""

    port, agents = load_config(config_path)
    adapter = DriveHTTPAdapter(agents, port=port)
    try:
        if ready is not None:
            ready(adapter.port)
        if stop is not None:
            stop.wait()
        closed = adapter.close(timeout=5.0)
        return 0 if closed else 1
    finally:
        try:
            adapter.close(timeout=5.0)
        except Exception:
            pass

def _do_hash_token():
    line = sys.stdin.readline()
    if line == "":
        line = ""
    if line.endswith("\n"):
        line = line[:-1]
    if line.endswith("\r"):
        line = line[:-1]
    sys.stdout.write(hash_token(line) + "\n")
    sys.stdout.flush()
    return 0

def main(argv=None):
    parser = argparse.ArgumentParser(prog="drive_tool.serve", add_help=True)
    parser.add_argument("--config", dest="config", default=None)
    parser.add_argument("--hash-token", dest="hash_token", action="store_true")
    args = parser.parse_args(argv)

    if args.hash_token:
        return _do_hash_token()

    if args.config is None:
        sys.stderr.write("config error: --config is required\n")
        return 2

    try:
        port, agents = load_config(args.config)
    except ConfigError as exc:
        sys.stderr.write("config error: %s\n" % (exc,))
        return 2

    stop = threading.Event()

    def _handle_signal(signum, frame):
        stop.set()

    old_term = signal.signal(signal.SIGTERM, _handle_signal)
    old_int = signal.signal(signal.SIGINT, _handle_signal)
    try:
        adapter = DriveHTTPAdapter(agents, port=port)
        try:
            sys.stderr.write(
                "drive-tool listening on 127.0.0.1:%d (%d agents)\n"
                % (adapter.port, len(agents))
            )
            sys.stderr.flush()
            stop.wait()
            closed = adapter.close(timeout=5.0)
            return 0 if closed else 1
        finally:
            try:
                adapter.close(timeout=5.0)
            except Exception:
                pass
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)

if __name__ == "__main__":
    raise SystemExit(main())
```

FILE: tests/test_serve.py

```python
"""Tests for drive_tool.serve: config validation and end-to-end run."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drive_tool.serve import ConfigError, hash_token, load_config, run
from drive_tool.service_client import DriveClient

_TOKEN = "A" * 40  # visible ASCII, length 40

def _valid_grant(root):
    return {
        "alias": "work",
        "root": root,
        "operations": ["list", "find", "read", "save"],
    }

def _valid_config(root, port=0):
    return {
        "port": port,
        "agents": [
            {
                "agent_id": "alice",
                "token_sha256": hash_token(_TOKEN),
                "grants": [_valid_grant(root)],
            }
        ],
    }

class ServeConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "root")
        os.mkdir(self.root)

    def _write(self, data, name="config.json", mode=0o600):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            if isinstance(data, str):
                fh.write(data)
            else:
                json.dump(data, fh)
        os.chmod(path, mode)
        return path

    def test_valid_config_loads(self):
        path = self._write(_valid_config(self.root))
        port, agents = load_config(path)
        self.assertEqual(port, 0)
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].agent_id, "alice")
        self.assertEqual(
            agents[0].token_sha256, hashlib.sha256(_TOKEN.encode()).digest()
        )
        self.assertEqual(len(agents[0].grants), 1)
        self.assertEqual(agents[0].grants[0].alias, "work")
        self.assertEqual(agents[0].grants[0].operations, frozenset(
            {"list", "find", "read", "save"}
        ))

    def test_hash_token_matches_hashlib(self):
        self.assertEqual(
            hash_token("hello"), hashlib.sha256(b"hello").hexdigest()
        )

    def test_duplicate_json_keys_rejected(self):
        path = self._write('{"port":0,"port":0,"agents":[]}')
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_unknown_top_level_key_rejected(self):
        cfg = _valid_config(self.root)
        cfg["extra"] = 1
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_unknown_agent_key_rejected(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["extra"] = 1
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_unknown_grant_key_rejected(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["grants"][0]["extra"] = 1
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_port_bool_rejected(self):
        cfg = _valid_config(self.root)
        cfg["port"] = True
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_port_out_of_range_rejected(self):
        cfg = _valid_config(self.root)
        cfg["port"] = 70000
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_bad_hex_rejected(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["token_sha256"] = "Z" * 64
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_bad_hex_length_rejected(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["token_sha256"] = "a" * 63
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_uppercase_hex_rejected(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["token_sha256"] = "A" * 64
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_empty_agents_rejected(self):
        cfg = {"port": 0, "agents": []}
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_duplicate_agent_id_rejected(self):
        cfg = _valid_config(self.root)
        second = {
            "agent_id": "alice",
            "token_sha256": hash_token("B" * 40),
            "grants": [_valid_grant(self.root)],
        }
        cfg["agents"].append(second)
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_duplicate_token_hash_rejected(self):
        cfg = _valid_config(self.root)
        second = {
            "agent_id": "bob",
            "token_sha256": hash_token(_TOKEN),
            "grants": [_valid_grant(self.root)],
        }
        cfg["agents"].append(second)
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_missing_root_rejected(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["grants"][0]["root"] = os.path.join(
            self.tmp.name, "nope"
        )
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_relative_root_rejected(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["grants"][0]["root"] = "relative/dir"
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_bad_operation_rejected(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["grants"][0]["operations"] = ["delete"]
        with self.assertRaises(ConfigError):
            load_config(self._write(cfg))

    def test_writable_config_rejected(self):
        path = self._write(_valid_config(self.root), mode=0o666)
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_oversized_config_rejected(self):
        path = os.path.join(self.tmp.name, "big.json")
        with open(path, "wb") as fh:
            fh.write(b" " * (1024 * 1024 + 1))
        os.chmod(path, 0o600)
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_error_message_never_contains_token_hash(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["token_sha256"] = "Z" * 64
        path = self._write(cfg)
        with self.assertRaises(ConfigError) as ctx:
            load_config(path)
        self.assertNotIn("Z" * 64, str(ctx.exception))

    def test_optional_caps_accepted(self):
        cfg = _valid_config(self.root)
        cfg["agents"][0]["grants"][0]["max_read_bytes"] = 4096
        cfg["agents"][0]["grants"][0]["max_write_bytes"] = 8192
        port, agents = load_config(self._write(cfg))
        grant = agents[0].grants[0]
        self.assertEqual(grant.max_read_bytes, 4096)
        self.assertEqual(grant.max_write_bytes, 8192)

class ServeEndToEndTests(unittest.TestCase):
    def test_run_end_to_end(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = os.path.join(tmp.name, "root")
        os.mkdir(root)
        with open(os.path.join(root, "hello.txt"), "wb") as fh:
            fh.write(b"hello world")

        cfg = _valid_config(root, port=0)
        path = os.path.join(tmp.name, "config.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        os.chmod(path, 0o600)

        ready = threading.Event()
        stop = threading.Event()
        result = {}
        port_holder = {}

        def _ready(p):
            port_holder["port"] = p
            ready.set()

        def _run():
            result["rc"] = run(path, ready=_ready, stop=stop)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        self.assertTrue(ready.wait(timeout=10.0), "adapter never became ready")
        port = port_holder["port"]
        self.assertGreater(port, 0)

        client = DriveClient(port=port, token=_TOKEN, timeout=5.0)

        listing = client.list("work", "root")
        self.assertIn("entries", listing)

        client.save("work", "p/notes.txt", b"new content", overwrite=False)

        reply = client.read("work", "p/notes.txt", offset=0, length=64)
        self.assertEqual(reply.data, b"new content")
        self.assertEqual(reply.offset, 0)
        self.assertTrue(reply.eof_observed)

        stop.set()
        thread.join(timeout=10.0)
        self.assertFalse(thread.is_alive(), "run() thread did not end")
        self.assertEqual(result["rc"], 0)

if __name__ == "__main__":
    unittest.main()
```
