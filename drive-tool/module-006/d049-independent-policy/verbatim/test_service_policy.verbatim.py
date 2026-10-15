"""D045 tests for drive_tool.service_policy.

Pure unittest, stdlib only, synthetic tokens and roots. No filesystem
or network access is expected or performed by the module under test.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import socket
import unittest
from unittest import mock

from drive_tool.service_policy import (
    OPERATIONS,
    MAX_TRANSFER_BYTES,
    PolicyDeniedError,
    SourceGrant,
    AgentPolicy,
    PolicyTable,
)

def make_token(i: int) -> str:
    """Distinct 32-char visible-ASCII token for index ``i``."""
    s = 'tok{:029d}'.format(i)
    assert len(s) == 32
    return s

def digest(token: str) -> bytes:
    return hashlib.sha256(token.encode('ascii')).digest()

def make_grant(alias: str = 'main',
               root: str = '/srv/data',
               ops: frozenset = frozenset({'read', 'find'}),
               r: int = MAX_TRANSFER_BYTES,
               w: int = MAX_TRANSFER_BYTES) -> SourceGrant:
    return SourceGrant(alias=alias, root=root, operations=ops,
                       max_read_bytes=r, max_write_bytes=w)

def make_agent(agent_id: str = 'a',
               token: str | None = None,
               grants: tuple | None = None) -> AgentPolicy:
    if token is None:
        token = make_token(0)
    if grants is None:
        grants = (make_grant(),)
    return AgentPolicy(agent_id=agent_id, token_sha256=digest(token),
                       grants=grants)

class ConstantsTests(unittest.TestCase):
    def test_operations_exact(self):
        self.assertEqual(OPERATIONS,
                         frozenset({'find', 'list', 'read', 'save'}))

    def test_max_transfer_bytes(self):
        self.assertEqual(MAX_TRANSFER_BYTES, 1048576)

    def test_denied_message_fixed(self):
        self.assertEqual(str(PolicyDeniedError()), 'access denied')
        self.assertEqual(str(PolicyDeniedError('ignored')), 'access denied')

class SourceGrantTests(unittest.TestCase):
    def test_valid_grant(self):
        g = make_grant()
        self.assertEqual(g.alias, 'main')
        self.assertEqual(g.root, '/srv/data')
        self.assertEqual(g.operations, frozenset({'read', 'find'}))
        self.assertEqual(g.max_read_bytes, MAX_TRANSFER_BYTES)
        self.assertEqual(g.max_write_bytes, MAX_TRANSFER_BYTES)

    def test_root_slash_accepted(self):
        self.assertEqual(make_grant(root='/').root, '/')

    def test_alias_type_errors(self):
        for bad in (b'main', 5, None, ['main']):
            with self.assertRaises(TypeError):
                SourceGrant(alias=bad, root='/x',
                            operations=frozenset({'read'}))

    def test_alias_value_errors(self):
        for bad in ('', 'a' * 65, 'has space', 'has/slash', 'a.b', 'ünïcode',
                    'a\nb'):
            with self.assertRaises(ValueError):
                SourceGrant(alias=bad, root='/x',
                            operations=frozenset({'read'}))

    def test_root_type_errors(self):
        with self.assertRaises(TypeError):
            SourceGrant(alias='a', root=b'/x',
                        operations=frozenset({'read'}))

    def test_root_relative_rejected(self):
        with self.assertRaises(ValueError):
            SourceGrant(alias='a', root='rel/x',
                        operations=frozenset({'read'}))

    def test_root_empty_rejected(self):
        with self.assertRaises(ValueError):
            SourceGrant(alias='a', root='',
                        operations=frozenset({'read'}))

    def test_root_nul_rejected(self):
        with self.assertRaises(ValueError):
            SourceGrant(alias='a', root='/x\x00y',
                        operations=frozenset({'read'}))

    def test_root_backslash_rejected(self):
        with self.assertRaises(ValueError):
            SourceGrant(alias='a', root='/x\\y',
                        operations=frozenset({'read'}))

    def test_root_dot_components_rejected(self):
        for bad in ('/x/./y', '/x/../y', '/./x', '/../x', '/.', '/..'):
            with self.assertRaises(ValueError):
                SourceGrant(alias='a', root=bad,
                            operations=frozenset({'read'}))

    def test_root_empty_components_rejected(self):
        for bad in ('/x//y', '/foo/', '//'):
            with self.assertRaises(ValueError):
                SourceGrant(alias='a', root=bad,
                            operations=frozenset({'read'}))

    def test_operations_must_be_frozenset(self):
        for bad in ({'read'}, ['read'], 'read', None, 5, (('read',),)):
            with self.assertRaises(TypeError):
                SourceGrant(alias='a', root='/x', operations=bad)

    def test_operations_empty_rejected(self):
        with self.assertRaises(ValueError):
            SourceGrant(alias='a', root='/x', operations=frozenset())

    def test_operations_unknown_rejected(self):
        with self.assertRaises(ValueError):
            SourceGrant(alias='a', root='/x',
                        operations=frozenset({'read', 'bogus'}))

    def test_operations_nonstring_members_rejected(self):
        with self.assertRaises(TypeError):
            SourceGrant(alias='a', root='/x', operations=frozenset({1}))

    def test_cap_bool_rejected(self):
        for field in ('max_read_bytes', 'max_write_bytes'):
            with self.assertRaises(TypeError):
                SourceGrant(alias='a', root='/x',
                            operations=frozenset({'read'}),
                            **{field: True})

    def test_cap_zero_rejected(self):
        for field in ('max_read_bytes', 'max_write_bytes'):
            with self.assertRaises(ValueError):
                SourceGrant(alias='a', root='/x',
                            operations=frozenset({'read'}),
                            **{field: 0})

    def test_cap_too_large_rejected(self):
        for field in ('max_read_bytes', 'max_write_bytes'):
            with self.assertRaises(ValueError):
                SourceGrant(alias='a', root='/x',
                            operations=frozenset({'read'}),
                            **{field: MAX_TRANSFER_BYTES + 1})

    def test_cap_minimum_accepted(self):
        g = SourceGrant(alias='a', root='/x',
                        operations=frozenset({'read'}),
                        max_read_bytes=1, max_write_bytes=1)
        self.assertEqual(g.max_read_bytes, 1)
        self.assertEqual(g.max_write_bytes, 1)

class AgentPolicyTests(unittest.TestCase):
    def test_valid_agent(self):
        ap = make_agent()
        self.assertEqual(ap.agent_id, 'a')
        self.assertIsInstance(ap.token_sha256, bytes)
        self.assertEqual(len(ap.token_sha256), 32)

    def test_agent_id_type_error(self):
        with self.assertRaises(TypeError):
            AgentPolicy(agent_id=5, token_sha256=b'x' * 32,
                        grants=(make_grant(),))

    def test_agent_id_value_error(self):
        for bad in ('', 'has space', 'a' * 65, 'a/b'):
            with self.assertRaises(ValueError):
                AgentPolicy(agent_id=bad, token_sha256=b'x' * 32,
                            grants=(make_grant(),))

    def test_token_bytearray_rejected(self):
        with self.assertRaises(TypeError):
            AgentPolicy(agent_id='a', token_sha256=bytearray(b'x' * 32),
                        grants=(make_grant(),))

    def test_token_memoryview_rejected(self):
        with self.assertRaises(TypeError):
            AgentPolicy(agent_id='a', token_sha256=memoryview(b'x' * 32),
                        grants=(make_grant(),))

    def test_token_wrong_length_rejected(self):
        for n in (0, 1, 31, 33, 64):
            with self.assertRaises(ValueError):
                AgentPolicy(agent_id='a', token_sha256=b'x' * n,
                            grants=(make_grant(),))

    def test_grants_type_error(self):
        with self.assertRaises(TypeError):
            AgentPolicy(agent_id='a', token_sha256=b'x' * 32,
                        grants=[make_grant()])

    def test_grants_empty_rejected(self):
        with self.assertRaises(ValueError):
            AgentPolicy(agent_id='a', token_sha256=b'x' * 32, grants=())

    def test_grants_too_many_rejected(self):
        gs = tuple(make_grant(alias=f'g{i}') for i in range(33))
        with self.assertRaises(ValueError):
            AgentPolicy(agent_id='a', token_sha256=b'x' * 32, grants=gs)

    def test_grants_duplicate_alias_rejected(self):
        g1 = make_grant(alias='dup')
        g2 = make_grant(alias='dup', root='/other')
        with self.assertRaises(ValueError):
            AgentPolicy(agent_id='a', token_sha256=b'x' * 32,
                        grants=(g1, g2))

    def test_grants_wrong_type_rejected(self):
        with self.assertRaises(TypeError):
            AgentPolicy(agent_id='a', token_sha256=b'x' * 32,
                        grants=('not-a-grant',))

class PolicyTableConstructionTests(unittest.TestCase):
    def test_agents_must_be_tuple(self):
        with self.assertRaises(TypeError):
            PolicyTable([make_agent()])

    def test_empty_agents_rejected(self):
        with self.assertRaises(ValueError):
            PolicyTable(())

    def test_too_many_agents_rejected(self):
        agents = tuple(make_agent(agent_id=f'a{i}', token=make_token(i))
                       for i in range(33))
        with self.assertRaises(ValueError):
            PolicyTable(agents)

    def test_duplicate_agent_id_rejected(self):
        a1 = make_agent(agent_id='dup', token=make_token(0))
        a2 = make_agent(agent_id='dup', token=make_token(1))
        with self.assertRaises(ValueError):
            PolicyTable((a1, a2))

    def test_duplicate_token_digest_rejected(self):
        tok = make_token(0)
        a1 = AgentPolicy(agent_id='a1', token_sha256=digest(tok),
                         grants=(make_grant(alias='g1'),))
        a2 = AgentPolicy(agent_id='a2', token_sha256=digest(tok),
                         grants=(make_grant(alias='g2'),))
        with self.assertRaises(ValueError):
            PolicyTable((a1, a2))

    def test_wrong_entry_type_rejected(self):
        with self.assertRaises(TypeError):
            PolicyTable(('nope',))

class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.tokens = [make_token(i) for i in range(5)]
        self.agents = tuple(
            AgentPolicy(agent_id=f'a{i}', token_sha256=digest(t),
                        grants=(make_grant(alias=f'g{i}'),))
            for i, t in enumerate(self.tokens)
        )
        self.table = PolicyTable(self.agents)

    def test_valid_token_returns_exact_agent(self):
        for i, tok in enumerate(self.tokens):
            self.assertIs(self.table.authenticate(tok), self.agents[i])

    def test_invalid_tokens_indistinguishable(self):
        cases = [
            make_token(99),           # unknown but well-formed
            self.tokens[0][:-1],      # too short
            self.tokens[0] + 'X',     # wrong but valid length
            'x' * 31,                 # below minimum
            'x' * 257,                # above maximum
            ' ' + 'a' * 31,           # space not visible
            'a' * 31 + '\n',          # newline not visible
            'a' * 31 + '\x7f',        # DEL not visible
            'ä' * 32,                 # non-ASCII
            None, 5, b'bytes', [1],   # wrong types
        ]
        for bad in cases:
            with self.assertRaises(PolicyDeniedError) as ctx:
                self.table.authenticate(bad)
            self.assertEqual(str(ctx.exception), 'access denied')

    def test_visible_ascii_bounds_accepted(self):
        # '!' (33) and '~' (126) are visible; length 32 is minimum.
        self.table.authenticate('!' * 32)  # unknown -> denied
        # (we only assert it did not raise for charset; unknown token still denies)

    def test_compares_all_digests_no_early_return(self):
        calls: list = []
        real = hmac.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return real(a, b)

        with mock.patch('hmac.compare_digest', side_effect=spy):
            result = self.table.authenticate(self.tokens[2])
        self.assertIs(result, self.agents[2])
        self.assertEqual(len(calls), len(self.agents))

    def test_authenticate_does_not_leak_input_in_message(self):
        bad = 'SECRET-TOKEN-' + 'a' * 30  # 43 chars, visible, unknown
        with self.assertRaises(PolicyDeniedError) as ctx:
            self.table.authenticate(bad)
        self.assertNotIn('SECRET', str(ctx.exception))
        self.assertEqual(str(ctx.exception), 'access denied')

    def test_repr_redacts_digest_and_root(self):
        tok = self.tokens[0]
        agent = self.agents[0]
        table = self.table
        self.assertNotIn(tok, repr(agent))
        self.assertNotIn(repr(digest(tok)), repr(agent))
        self.assertNotIn('/srv/data', repr(agent))
        # SourceGrant hides root.
        self.assertNotIn('/srv/data', repr(agent.grants[0]))
        self.assertNotIn('/srv/data', repr(table))
        self.assertNotIn(tok, repr(table))

    def test_no_raw_token_stored_on_agent(self):
        tok = self.tokens[0]
        agent = self.agents[0]
        for value in vars(agent).values():
            self.assertNotEqual(value, tok)

    def test_no_raw_token_stored_on_table(self):
        tok = self.tokens[0]
        table = self.table
        for name in ('_agents', '_by_id', '_digests'):
            obj = getattr(table, name)
            self.assertNotIn(tok, repr(obj))

class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tok_a = make_token(0)
        self.tok_b = make_token(1)
        self.ga_read = make_grant(alias='src', root='/a/root',
                                  ops=frozenset({'read', 'find'}))
        self.ga_save = make_grant(alias='write', root='/a/write',
                                  ops=frozenset({'save', 'list'}))
        self.gb_read = make_grant(alias='src', root='/b/root',
                                  ops=frozenset({'read'}))
        self.ap_a = AgentPolicy(agent_id='a', token_sha256=digest(self.tok_a),
                                grants=(self.ga_read, self.ga_save))
        self.ap_b = AgentPolicy(agent_id='b', token_sha256=digest(self.tok_b),
                                grants=(self.gb_read,))
        self.table = PolicyTable((self.ap_a, self.ap_b))

    def test_allowed_returns_exact_object(self):
        self.assertIs(self.table.authorize('a', 'src', 'read'), self.ga_read)
        self.assertIs(self.table.authorize('a', 'write', 'save'), self.ga_save)
        self.assertIs(self.table.authorize('b', 'src', 'read'), self.gb_read)

    def test_same_alias_across_agents_isolated(self):
        ga = self.table.authorize('a', 'src', 'read')
        gb = self.table.authorize('b', 'src', 'read')
        self.assertIs(ga, self.ga_read)
        self.assertIs(gb, self.gb_read)
        self.assertNotEqual(ga.root, gb.root)

    def test_read_only_denies_save(self):
        with self.assertRaises(PolicyDeniedError):
            self.table.authorize('a', 'src', 'save')

    def test_save_only_denies_read(self):
        with self.assertRaises(PolicyDeniedError):
            self.table.authorize('a', 'write', 'read')

    def test_alias_not_granted_denied(self):
        with self.assertRaises(PolicyDeniedError):
            self.table.authorize('a', 'missing', 'read')

    def test_unknown_agent_denied(self):
        with self.assertRaises(PolicyDeniedError):
            self.table.authorize('zzz', 'src', 'read')

    def test_unknown_operation_denied(self):
        with self.assertRaises(PolicyDeniedError):
            self.table.authorize('a', 'src', 'delete')

    def test_caps_do_not_grant_absent_operations(self):
        g = make_grant(alias='r', root='/x', ops=frozenset({'read'}),
                       r=MAX_TRANSFER_BYTES, w=MAX_TRANSFER_BYTES)
        ap = AgentPolicy(agent_id='c', token_sha256=digest(make_token(2)),
                         grants=(g,))
        t = PolicyTable((ap,))
        with self.assertRaises(PolicyDeniedError):
            t.authorize('c', 'r', 'save')
        with self.assertRaises(PolicyDeniedError):
            t.authorize('c', 'r', 'list')

    def test_wrong_type_and_unhashable_denied(self):
        cases = [
            (None, 'src', 'read'),
            ('a', None, 'read'),
            ('a', 'src', None),
            (5, 'src', 'read'),
            ('a', 5, 'read'),
            ('a', 'src', 5),
            ([], 'src', 'read'),
            ('a', [], 'read'),
            ('a', 'src', []),
            ({}, 'src', 'read'),
            ('a', {}, 'read'),
            ('a', 'src', {}),
        ]
        for args in cases:
            with self.assertRaises(PolicyDeniedError) as ctx:
                self.table.authorize(*args)
            self.assertEqual(str(ctx.exception), 'access denied')

    def test_denied_message_identical_across_reasons(self):
        messages = []
        for args in (
            ('a', 'src', 'save'),
            ('a', 'missing', 'read'),
            ('unknown', 'src', 'read'),
            ('a', 'src', 'bogus'),
            (None, None, None),
        ):
            with self.assertRaises(PolicyDeniedError) as ctx:
                self.table.authorize(*args)
            messages.append(str(ctx.exception))
        self.assertTrue(all(m == 'access denied' for m in messages))

class PurityTests(unittest.TestCase):
    def test_build_and_use_do_not_touch_fs_or_network(self):
        with mock.patch('os.stat', side_effect=AssertionError('fs')), \
             mock.patch('os.lstat', side_effect=AssertionError('fs')), \
             mock.patch('os.listdir', side_effect=AssertionError('fs')), \
             mock.patch('os.open', side_effect=AssertionError('fs')), \
             mock.patch('socket.socket', side_effect=AssertionError('net')), \
             mock.patch('socket.create_connection',
                        side_effect=AssertionError('net')):
            tok = make_token(0)
            g = make_grant()
            ap = AgentPolicy(agent_id='a', token_sha256=digest(tok),
                             grants=(g,))
            t = PolicyTable((ap,))
            self.assertIs(t.authenticate(tok), ap)
            self.assertIs(t.authorize('a', 'main', 'read'), g)
            with self.assertRaises(PolicyDeniedError):
                t.authenticate('bogus')

class FrozenDataclassTests(unittest.TestCase):
    def test_source_grant_frozen(self):
        g = make_grant()
        with self.assertRaises(AttributeError):
            g.alias = 'other'  # type: ignore[misc]

    def test_agent_policy_frozen(self):
        ap = make_agent()
        with self.assertRaises(AttributeError):
            ap.agent_id = 'b'  # type: ignore[misc]

    def test_source_grant_operations_is_frozenset(self):
        g = make_grant()
        self.assertIsInstance(g.operations, frozenset)

    def test_agent_policy_grants_is_tuple(self):
        ap = make_agent()
        self.assertIsInstance(ap.grants, tuple)

if __name__ == '__main__':  # pragma: no cover
    unittest.main()
