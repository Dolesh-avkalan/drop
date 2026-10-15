"""D049 independent adversarial probes for drive_tool.service_policy.

Fresh probes written by the D049 reviewer. Synthetic tokens/roots only.
Pure in-memory; patches os/socket to prove no filesystem/network work.
Exits non-zero if any probe fails.
"""
from __future__ import annotations

import hashlib
import hmac
import sys
import traceback
from unittest import mock

from drive_tool.service_policy import (
    OPERATIONS,
    MAX_TRANSFER_BYTES,
    PolicyDeniedError,
    SourceGrant,
    AgentPolicy,
    PolicyTable,
)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))


def dig(tok):
    return hashlib.sha256(tok.encode("ascii")).digest()


def tok(i):
    s = "tok{:029d}".format(i)
    assert len(s) == 32
    return s


def grant(alias="main", root="/srv/data", ops=frozenset({"read", "find"}),
          r=MAX_TRANSFER_BYTES, w=MAX_TRANSFER_BYTES):
    return SourceGrant(alias=alias, root=root, operations=ops,
                       max_read_bytes=r, max_write_bytes=w)


def agent(aid="a", token=None, grants=None):
    if token is None:
        token = tok(0)
    if grants is None:
        grants = (grant(),)
    return AgentPolicy(agent_id=aid, token_sha256=dig(tok if False else token),
                       grants=grants)


def expect_denied(fn, *args):
    try:
        fn(*args)
    except PolicyDeniedError as e:
        return str(e) == "access denied", str(e)
    except BaseException as e:  # wrong exception type is a failure
        return False, f"raised {type(e).__name__}: {e}"
    return False, "no exception"


def expect_type(fn, exc=TypeError):
    try:
        fn()
    except exc:
        return True, ""
    except BaseException as e:
        return False, f"raised {type(e).__name__} not {exc.__name__}"
    return False, "no exception"


# ---- P1 real NUL / single backslash / dot / empty root components ----------
def p1_root_grammar():
    nul = "/x" + "\x00" + "y"
    bs1 = "/x" + "\\" + "y"          # ONE backslash char
    bs2 = "/x" + "\\\\" + "y"        # TWO backslash chars
    check("P1 real NUL root rejected", expect_type(lambda: grant(root=nul), ValueError)[0],
          repr(nul))
    check("P1 single-backslash root rejected", expect_type(lambda: grant(root=bs1), ValueError)[0],
          repr(bs1))
    check("P1 double-backslash root rejected", expect_type(lambda: grant(root=bs2), ValueError)[0],
          repr(bs2))
    for bad in ("/x/./y", "/x/../y", "/./x", "/../x", "/.", "/..",
                "/x//y", "/foo/", "//", ""):
        ok = expect_type(lambda b=bad: grant(root=b), ValueError)[0]
        check(f"P1 root component rejected {bad!r}", ok)
    check("P1 root '/' accepted", grant(root="/").root == "/")
    check("P1 root '/srv/data' accepted", grant(root="/srv/data").root == "/srv/data")
    check("P1 relative root rejected", expect_type(lambda: grant(root="rel/x"), ValueError)[0])
    check("P1 non-str root TypeError", expect_type(lambda: grant(root=b"/x"))[0])


# ---- P2 nonbool bounds / duplicate ids or digests -------------------------
def p2_bounds_and_dupes():
    for field in ("max_read_bytes", "max_write_bytes"):
        key = "r" if field == "max_read_bytes" else "w"
        for v in (True, False):
            ok = expect_type(lambda k=key, vv=v: grant(**{k: vv}))[0]
            check(f"P2 {field} bool {v} rejected (TypeError)", ok)
        for v in (0, -1, MAX_TRANSFER_BYTES + 1):
            ok = expect_type(lambda k=key, vv=v: grant(**{k: vv}), ValueError)[0]
            check(f"P2 {field} out-of-range {v} rejected (ValueError)", ok)
        for v in (1, MAX_TRANSFER_BYTES):
            ok = grant(**{key: v})
            check(f"P2 {field} boundary {v} accepted", getattr(ok, field) == v)
        for v in (1.0, "1", None):
            ok = expect_type(lambda k=key, vv=v: grant(**{k: vv}))[0]
            check(f"P2 {field} non-int {v!r} rejected (TypeError)", ok)
    # duplicate agent ids
    a1 = AgentPolicy("dup", dig(tok(0)), (grant(alias="g1"),))
    a2 = AgentPolicy("dup", dig(tok(1)), (grant(alias="g2"),))
    check("P2 duplicate agent_id rejected",
          expect_type(lambda: PolicyTable((a1, a2)), ValueError)[0])
    # duplicate token digest
    b1 = AgentPolicy("a1", dig(tok(0)), (grant(alias="g1"),))
    b2 = AgentPolicy("a2", dig(tok(0)), (grant(alias="g2"),))
    check("P2 duplicate token digest rejected",
          expect_type(lambda: PolicyTable((b1, b2)), ValueError)[0])
    # max agents / grants boundaries
    ok32 = tuple(AgentPolicy(f"a{i}", dig(tok(i)), (grant(alias="g"),)) for i in range(32))
    check("P2 32 agents accepted", len(PolicyTable(ok32)._agents) == 32)
    ok33 = tuple(AgentPolicy(f"a{i}", dig(tok(i)), (grant(alias="g"),)) for i in range(33))
    check("P2 33 agents rejected",
          expect_type(lambda: PolicyTable(ok33), ValueError)[0])
    g32 = tuple(grant(alias=f"g{i}") for i in range(32))
    check("P2 32 grants accepted", len(AgentPolicy("a", dig(tok(0)), g32).grants) == 32)
    g33 = tuple(grant(alias=f"g{i}") for i in range(33))
    check("P2 33 grants rejected",
          expect_type(lambda: AgentPolicy("a", dig(tok(0)), g33), ValueError)[0])
    # alias / agent_id grammar boundaries
    check("P2 alias 64 chars accepted", grant(alias="a" * 64).alias == "a" * 64)
    check("P2 alias 65 chars rejected",
          expect_type(lambda: grant(alias="a" * 65), ValueError)[0])
    check("P2 alias empty rejected", expect_type(lambda: grant(alias=""), ValueError)[0])
    check("P2 agent_id 65 chars rejected",
          expect_type(lambda: AgentPolicy("a" * 65, dig(tok(0)), (grant(),)), ValueError)[0])


# ---- P3 immutable tuple/frozenset registry --------------------------------
def p3_registry_immutability():
    t = PolicyTable((agent("a", tok(0)),))
    from types import MappingProxyType
    check("P3 _by_id is mappingproxy", isinstance(t._by_id, MappingProxyType),
          type(t._by_id).__name__)
    check("P3 _agents is tuple", isinstance(t._agents, tuple))
    check("P3 _digests is tuple", isinstance(t._digests, tuple))
    try:
        t._by_id["a"] = agent("evil", tok(9))
        check("P3 _by_id item assignment blocked", False, "assignment succeeded!")
    except TypeError:
        check("P3 _by_id item assignment blocked", True)
    g = grant()
    check("P3 grant.operations is frozenset", isinstance(g.operations, frozenset))
    check("P3 grant frozen (alias)", expect_type(lambda: setattr(g, "alias", "x"), AttributeError)[0])
    a = agent()
    check("P3 agent frozen (agent_id)", expect_type(lambda: setattr(a, "agent_id", "x"), AttributeError)[0])
    # caller-supplied mutable input cannot change permissions (copies made)
    src = {  # a plain dict passed as mapping is not accepted; use tuple
    }
    check("P3 agents list rejected", expect_type(lambda: PolicyTable([agent()]))[0])


# ---- P4 different agents same alias / different roots ---------------------
def p4_alias_isolation():
    ga = grant(alias="src", root="/a/root", ops=frozenset({"read"}))
    gb = grant(alias="src", root="/b/root", ops=frozenset({"read"}))
    ap_a = AgentPolicy("a", dig(tok(0)), (ga,))
    ap_b = AgentPolicy("b", dig(tok(1)), (gb,))
    t = PolicyTable((ap_a, ap_b))
    check("P4 agent a returns its own grant (identity)",
          t.authorize("a", "src", "read") is ga)
    check("P4 agent b returns its own grant (identity)",
          t.authorize("b", "src", "read") is gb)
    check("P4 roots differ", t.authorize("a", "src", "read").root !=
          t.authorize("b", "src", "read").root)
    # no cross-agent fallback: alias only on b, asked as a
    check("P4 no fallback a->b's alias",
          expect_denied(t.authorize, "a", "b-only", "read")[0])
    # a has alias 'src', b has alias 'other'; asking a for 'other' must deny
    gb2 = grant(alias="other", root="/b/root", ops=frozenset({"read"}))
    t2 = PolicyTable((AgentPolicy("a", dig(tok(0)), (ga,)),
                      AgentPolicy("b", dig(tok(1)), (gb2,))))
    check("P4 asking a for b-only alias denies", expect_denied(t2.authorize, "a", "other", "read")[0])
    check("P4 asking b for a-only alias denies", expect_denied(t2.authorize, "b", "src", "read")[0])


# ---- P5 readonly cannot save; caps don't grant ops ------------------------
def p5_caps_and_readonly():
    ro = grant(alias="ro", root="/x", ops=frozenset({"read", "find"}),
               r=MAX_TRANSFER_BYTES, w=MAX_TRANSFER_BYTES)
    t = PolicyTable((AgentPolicy("c", dig(tok(0)), (ro,)),))
    check("P5 readonly denies save", expect_denied(t.authorize, "c", "ro", "save")[0])
    check("P5 readonly denies list", expect_denied(t.authorize, "c", "ro", "list")[0])
    check("P5 readonly allows read", t.authorize("c", "ro", "read") is ro)
    wo = grant(alias="wo", root="/x", ops=frozenset({"save"}),
               r=MAX_TRANSFER_BYTES, w=MAX_TRANSFER_BYTES)
    t2 = PolicyTable((AgentPolicy("d", dig(tok(1)), (wo,)),))
    check("P5 write-only denies read", expect_denied(t2.authorize, "d", "wo", "read")[0])
    check("P5 write-only denies find", expect_denied(t2.authorize, "d", "wo", "find")[0])


# ---- P6 malformed / unhashable request fields deny uniformly --------------
def p6_malformed_uniform():
    t = PolicyTable((agent("a", tok(0)),))
    unhashable = [[], {}, set(), bytearray(b"x")]
    cases = []
    for u in unhashable:
        cases += [(u, "main", "read"), ("a", u, "read"), ("a", "main", u)]
    cases += [(None, "main", "read"), ("a", None, "read"), ("a", "main", None),
              (5, "main", "read"), ("a", 5, "read"), ("a", "main", 5),
              (b"a", "main", "read"), ("a", b"main", "read")]
    msgs = []
    allok = True
    for c in cases:
        ok, msg = expect_denied(t.authorize, *c)
        if not ok:
            allok = False
            check(f"P6 deny {c!r}", False, msg)
        msgs.append(msg)
    check("P6 all malformed/unhashable denied with fixed message",
          allok and all(m == "access denied" for m in msgs),
          f"{len(cases)} cases")


# ---- P7 exact returned object identity ------------------------------------
def p7_identity():
    ga = grant(alias="src", root="/a", ops=frozenset({"read"}))
    ap = AgentPolicy("a", dig(tok(0)), (ga,))
    t = PolicyTable((ap,))
    check("P7 authenticate returns exact AgentPolicy", t.authenticate(tok(0)) is ap)
    check("P7 authorize returns exact SourceGrant", t.authorize("a", "src", "read") is ga)


# ---- P8 visible ASCII token boundaries / lengths --------------------------
def p8_token_bounds():
    # accepted: cp 33 and 126 at min len 32; also max len 256
    tlo = "!" * 32
    thi = "~" * 32
    tmax = "A" * 256
    t = PolicyTable((
        AgentPolicy("lo", dig(tlo), (grant(alias="g"),)),
        AgentPolicy("hi", dig(thi), (grant(alias="g"),)),
        AgentPolicy("mx", dig(tmax), (grant(alias="g"),)),
    ))
    check("P8 cp33 len32 accepted", t.authenticate(tlo).agent_id == "lo")
    check("P8 cp126 len32 accepted", t.authenticate(thi).agent_id == "hi")
    check("P8 len256 accepted", t.authenticate(tmax).agent_id == "mx")
    # rejected lengths
    for bad in ("a" * 31, "a" * 257, "", "a" * 255):
        # 255 is a valid length only if it matches; use unknown 255 well-formed
        pass
    for bad in ("a" * 31, "a" * 257, ""):
        ok, msg = expect_denied(t.authenticate, bad)
        check(f"P8 length {len(bad)} rejected", ok, msg)
    # boundary codepoints just outside
    for bad in (" " + "a" * 31, "a" * 31 + "\x7f", "\x20" * 32, "\t" + "a" * 31,
                "a" * 31 + "\x1f", "ä" * 32, "\u00e9" * 32):
        ok, msg = expect_denied(t.authenticate, bad)
        check(f"P8 charset-outside {bad!r:.12} rejected", ok, msg)
    # wrong types
    for bad in (None, 5, b"x" * 32, bytearray(b"x" * 32), ["x" * 32], {"t": 1}):
        ok, msg = expect_denied(t.authenticate, bad)
        check(f"P8 non-str token {type(bad).__name__} rejected", ok, msg)


# ---- P9 all configured digest comparisons occur, no early return ----------
def p9_full_scan():
    N = 5
    toks = [tok(i) for i in range(N)]
    agents = tuple(AgentPolicy(f"a{i}", dig(t), (grant(alias="g"),))
                   for i, t in enumerate(toks))
    t = PolicyTable(agents)
    for target in (0, N - 1):
        calls = []
        real = hmac.compare_digest

        def spy(a, b):
            calls.append(1)
            return real(a, b)

        with mock.patch("hmac.compare_digest", side_effect=spy):
            got = t.authenticate(toks[target])
        check(f"P9 match@{target} compares all {N} digests (no early return)",
              len(calls) == N, f"calls={len(calls)}")
        check(f"P9 match@{target} returns exact agent", got is agents[target])
    # unknown token also compares all
    calls = []
    real = hmac.compare_digest

    def spy2(a, b):
        calls.append(1)
        return real(a, b)

    with mock.patch("hmac.compare_digest", side_effect=spy2):
        try:
            t.authenticate(tok(99))
        except PolicyDeniedError:
            pass
    check("P9 unknown token compares all digests", len(calls) == N, f"calls={len(calls)}")


# ---- P10 no secrets in repr/errors; no fs/network -------------------------
def p10_secrets_and_purity():
    secret = "SECRET-TOKEN-" + "z" * 30   # unknown, visible-ASCII, len 43
    g = grant(alias="src", root="/very/secret/root")
    ap = AgentPolicy("a", dig(tok(0)), (g,))
    t = PolicyTable((ap,))
    check("P10 secret token absent from agent repr", secret not in repr(ap))
    check("P10 digest absent from agent repr", repr(dig(secret)) not in repr(ap))
    check("P10 root absent from grant repr", "/very/secret/root" not in repr(g))
    check("P10 root absent from table repr", "/very/secret/root" not in repr(t))
    ok, msg = expect_denied(t.authenticate, secret)
    check("P10 denied message has no secret", ok and "SECRET" not in msg, msg)
    ok, msg = expect_denied(t.authorize, "a", "src", "delete")
    check("P10 authorize denied message fixed", ok, msg)
    # purity: patch fs/network and exercise build+use
    with mock.patch("os.stat", side_effect=AssertionError("fs")), \
         mock.patch("os.lstat", side_effect=AssertionError("fs")), \
         mock.patch("os.listdir", side_effect=AssertionError("fs")), \
         mock.patch("os.open", side_effect=AssertionError("fs")), \
         mock.patch("socket.socket", side_effect=AssertionError("net")), \
         mock.patch("socket.create_connection", side_effect=AssertionError("net")):
        s = tok(7)
        gg = grant()
        aa = AgentPolicy("z", dig(s), (gg,))
        tt = PolicyTable((aa,))
        r1 = tt.authenticate(s)
        r2 = tt.authorize("z", "main", "read")
        check("P10 build+use touches no fs/network",
              r1 is aa and r2 is gg)
    # token not retained on table attributes
    check("P10 raw token not in table attrs",
          all(secret not in repr(getattr(t, n)) for n in ("_agents", "_by_id", "_digests")))


# ---- P11 Mapping annotation nit: import works, name not bound -------------
def p11_mapping_nit():
    import drive_tool.service_policy as sp
    check("P11 module imports cleanly", True)
    check("P11 'Mapping' not imported into module namespace", not hasattr(sp, "Mapping"))


def main():
    for fn in (p1_root_grammar, p2_bounds_and_dupes, p3_registry_immutability,
               p4_alias_isolation, p5_caps_and_readonly, p6_malformed_uniform,
               p7_identity, p8_token_bounds, p9_full_scan,
               p10_secrets_and_purity, p11_mapping_nit):
        try:
            fn()
        except BaseException:
            check(f"{fn.__name__} crashed", False, traceback.format_exc().splitlines()[-1])
    total = len(RESULTS)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n=== PROBE SUMMARY: {total - len(failed)}/{total} passed ===")
    for name, ok, detail in failed:
        print(f"  FAIL: {name}  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
