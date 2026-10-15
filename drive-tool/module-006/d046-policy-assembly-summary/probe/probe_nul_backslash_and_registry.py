"""D046 probe: exact NUL/backslash semantics and registry immutability.

Runs against the FINAL assembled candidate (drive_tool/service_policy.py).
Uses actual characters (a real NUL and a real single backslash), not
escaped textual stand-ins.
"""
from drive_tool import service_policy as sp

def try_root(label, value):
    try:
        sp.SourceGrant(alias='a', root=value, operations=frozenset({'read'}))
        return f"{label}: ACCEPTED"
    except Exception as e:
        return f"{label}: {type(e).__name__}: {e}"

print("=== root NUL/backslash semantics (actual characters) ===")
print(try_root("actual NUL  '/x'+NUL+'y'", '/x\x00y'))
print(try_root("single backslash  '/x\\\\y'", '/x\\y'))
print(try_root("two backslashes  '/x\\\\\\\\y'", '/x\\\\y'))
print(try_root("normal  '/srv/data'", '/srv/data'))
print(try_root("root '/'", '/'))
print(try_root("trailing slash  '/foo/'", '/foo/'))

print()
print("=== registry immutability ===")
g = sp.SourceGrant(alias='m', root='/srv/data', operations=frozenset({'read'}))
ap = sp.AgentPolicy(agent_id='a', token_sha256=b'x'*32, grants=(g,))
t = sp.PolicyTable((ap,))
print("type(_by_id):", type(t._by_id))
try:
    t._by_id['a'] = 'x'
    print("MUTABLE (bad)")
except TypeError as e:
    print("immutable OK:", type(e).__name__, e)
print("authorize still returns exact grant:", t.authorize('a','m','read') is g)
