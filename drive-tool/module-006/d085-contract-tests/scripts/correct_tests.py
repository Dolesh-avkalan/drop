path = "tests/test_http_adapter.py"
src = open(path, encoding="utf-8").read()
done = []


def sub(name, old, new, count=1):
    global src
    n = src.count(old)
    assert n == count, "hunk %s: expected %d, found %d" % (name, count, n)
    src = src.replace(old, new, count)
    done.append(name)


# 1. Framing: per-case contract status (huge CL -> 413, duplicate save key -> 403)
sub("framing", '''class FramingRejectionTests(_Base):
    def test_all_framing_cases_rejected_400_invalid(self):
        a = self.make()
        for name, raw in _framing_cases().items():
            with self.subTest(case=name):
                status, code, unc, retry = _err(_exchange(a.port, raw))
                self.assertEqual(status, 400, name)
                self.assertEqual(code, "invalid", name)
                self.assertFalse(unc, name)
                self.assertFalse(retry, name)
''', '''class FramingRejectionTests(_Base):
    # Adopted contract: a malformed frame is 400 invalid, except (a) a huge but
    # syntactically valid Content-Length, which reaches the Step 8 wire cap and
    # is 413 too_large, and (b) a duplicate save source_id, whose source is
    # ambiguous and therefore denied 403.  Everything else stays 400 invalid.
    _CONTRACT_STATUS = {
        "huge_digit_content_length": (413, "too_large"),
        "save_duplicate_key": (403, "denied"),
    }

    def test_framing_cases_rejected_per_contract(self):
        a = self.make()
        for name, raw in _framing_cases().items():
            with self.subTest(case=name):
                expected = self._CONTRACT_STATUS.get(name, (400, "invalid"))
                status, code, unc, retry = _err(_exchange(a.port, raw))
                self.assertEqual(status, expected[0], name)
                self.assertEqual(code, expected[1], name)
                self.assertFalse(unc, name)
                self.assertFalse(retry, name)
''')

# 2. Payload cases: 403 when the source_id is unextractable, 400 when it is
#    extractable and the remaining schema is bad.
sub("payload", '''class PayloadParsingTests(_Base):
    def test_payload_cases_rejected_400_invalid(self):
        a = self.make()
        for name, body in _payload_cases().items():
            with self.subTest(case=name):
                raw = _frame("/v1/list", _hdrs(_MAIN_TOKEN, body=body), body)
                status, code, _u, _r = _err(_exchange(a.port, raw))
                self.assertEqual((status, code), (400, "invalid"), name)
    def test_deeply_nested_json_does_not_kill_worker(self):
        a = self.make()
        body = b"[" * 5000 + b"]" * 5000
        raw = _frame("/v1/list", _hdrs(_MAIN_TOKEN, body=body), body)
        self.assertEqual(_parse(_exchange(a.port, raw))[0], 400)
        ok = self.client(a, _MAIN_TOKEN).list("main", limit=5)
        self.assertIn("items", ok)
''', '''# Payload cases whose source_id cannot be extracted at all: the frozen backend
# authorizes (token, source_id, operation), so the adapter delegates with
# source_id=None and the request is uniformly 403 denied.
_UNEXTRACTABLE_SOURCE_CASES = (
    "duplicate_keys", "nan", "infinity", "bom", "invalid_utf8", "non_object",
)
# Payload cases with an extractable, authorized source_id but a bad remaining
# schema: those are 400 invalid before any binding lease.
_EXTRACTABLE_BAD_SCHEMA_CASES = ("extra_key", "missing_key")


@unittest.skipUnless(_ADAPTER_AVAILABLE, _SKIP_REASON)
class PayloadParsingTests(_Base):
    def test_payload_cases_rejected_per_contract(self):
        a = self.make()
        for name, body in _payload_cases().items():
            with self.subTest(case=name):
                if name in _UNEXTRACTABLE_SOURCE_CASES:
                    expected = (403, "denied")
                elif name in _EXTRACTABLE_BAD_SCHEMA_CASES:
                    expected = (400, "invalid")
                else:  # pragma: no cover - guard against an unclassified case
                    self.fail("unclassified payload case %r" % (name,))
                raw = _frame("/v1/list", _hdrs(_MAIN_TOKEN, body=body), body)
                status, code, _u, _r = _err(_exchange(a.port, raw))
                self.assertEqual((status, code), expected, name)
    def test_deeply_nested_json_does_not_kill_worker(self):
        a = self.make()
        body = b"[" * 5000 + b"]" * 5000
        raw = _frame("/v1/list", _hdrs(_MAIN_TOKEN, body=body), body)
        # The body never yields an extractable source_id, so it is denied 403
        # rather than parsed into an invalid request.
        status, code, _u, _r = _err(_exchange(a.port, raw))
        self.assertEqual((status, code), (403, "denied"))
        ok = self.client(a, _MAIN_TOKEN).list("main", limit=5)
        self.assertIn("items", ok)
''')

# 3. Auth-first: unextractable source is denied for every token state.
sub("authfirst", '''    def test_valid_token_valid_source_bad_payload_invalid_before_lease(self):
        body = b"{bad"
        raw = _frame("/v1/list", _hdrs(_MAIN_TOKEN, body=body), body)
        status, code, unc, retry = self._send(raw)
        self.assertEqual((status, code), (400, "invalid"))
        self.assertFalse(unc)
        self.assertFalse(retry)
        self.assertEqual(self.s.calls, [("list", None)])
        self.assertEqual(self.s.leases, 0)
''', '''    def test_unextractable_source_denied_uniformly_across_token_states(self):
        body = b"{bad"
        raw = _frame("/v1/list", _hdrs(_MAIN_TOKEN, body=body), body)
        status, code, unc, retry = self._send(raw)
        self.assertEqual((status, code), (403, "denied"))
        self.assertFalse(unc)
        self.assertFalse(retry)
        self.assertEqual(self.s.calls, [("list", None)])
        self.assertEqual(self.s.leases, 0)
        # Paired: an unknown token and an unauthorized known token receive the
        # same uniform denial, and no binding lease is ever acquired.
        for token in (_UNKNOWN_TOKEN, _OTHER_TOKEN):
            with self.subTest(token=token[:12]):
                raw = _frame("/v1/list", _hdrs(token, body=body), body)
                self.assertEqual(self._send(raw)[:2], (403, "denied"))
        self.assertEqual(self.s.leases, 0)
''')

# 4. New paired capability-boundary / lexical-vs-service-auth coverage.
sub("boundary", '''@unittest.skipUnless(_ADAPTER_AVAILABLE, _SKIP_REASON)
class AliasIsolationTests(_Base):
''', '''@unittest.skipUnless(_ADAPTER_AVAILABLE, _SKIP_REASON)
class CapabilityBoundaryTests(_Base):
    """Adopted capability boundary (director clarification over D083).

    Lexical vs service authentication.  Step 7 of ``_check_headers`` is a purely
    lexical Authorization *framing* check: scheme ``Bearer ``, token length
    32..256 and printable bytes.  It cannot authenticate a token, because the
    frozen backend resolves capability as ``(token, source_id, operation)`` and
    exposes no token-only method.  A lexically valid but unknown token therefore
    passes Step 7 and can still receive a pre-body 413 from the wire cap.  A
    missing, unextractable or non-string ``source_id`` reaches the service as
    ``source_id=None`` and is uniformly 403 denied for known, unknown and
    unauthorized tokens alike.  An extractable, *authorized* source with bad
    remaining schema is 400 invalid; an extractable but *unauthorized* source is
    403 denied.
    """

    def test_unextractable_source_denied_for_every_token_state(self):
        a = self.make()
        body = b"{bad"
        for token in (_MAIN_TOKEN, _UNKNOWN_TOKEN, _OTHER_TOKEN, _READONLY_TOKEN):
            with self.subTest(token=token[:12]):
                raw = _frame("/v1/list", _hdrs(token, body=body), body)
                status, code, unc, retry = _err(_exchange(a.port, raw))
                self.assertEqual((status, code), (403, "denied"))
                self.assertFalse(unc)
                self.assertFalse(retry)

    def test_extractable_authorized_source_bad_schema_is_invalid(self):
        a = self.make()
        body = _jb({"source_id": "main", "file_id": "root", "limit": 5})
        raw = _frame("/v1/list", _hdrs(_MAIN_TOKEN, body=body), body)
        status, code, unc, retry = _err(_exchange(a.port, raw))
        self.assertEqual((status, code), (400, "invalid"))
        self.assertFalse(unc)
        self.assertFalse(retry)

    def test_extractable_unauthorized_source_is_denied(self):
        a = self.make()
        body = _jb({"source_id": "other", "file_id": "root", "limit": 5})
        raw = _frame("/v1/list", _hdrs(_MAIN_TOKEN, body=body), body)
        self.assertEqual(_err(_exchange(a.port, raw))[:2], (403, "denied"))

    def test_duplicate_json_key_ambiguous_source_is_denied(self):
        a = self.make()
        body = (b\'{"source_id":"main","source_id":"main","file_id":"root",\'
                b\'"limit":5,"offset":0}\')
        raw = _frame("/v1/list", _hdrs(_MAIN_TOKEN, body=body), body)
        self.assertEqual(_err(_exchange(a.port, raw))[:2], (403, "denied"))

    def test_leading_zero_content_length_accepted_and_normalised(self):
        a = self.make()
        body = _jb(_LIST_PAYLOAD)
        raw = _frame("/v1/list",
                     _hdrs(_MAIN_TOKEN, body=body,
                           cl="00000000" + str(len(body))), body)
        status, code, unc, retry = _err(_exchange(a.port, raw))
        self.assertNotEqual(status, 413)
        self.assertFalse(unc)
        self.assertFalse(retry)

    def test_huge_content_length_is_413_only_after_the_lexical_auth_gate(self):
        a = self.make()
        body = _jb(_LIST_PAYLOAD)
        base = [b"Host: 127.0.0.1", b"Content-Type: application/json"]
        huge = [b"Content-Length: " + b"9" * 5000]
        bearer = lambda t: [b"Authorization: Bearer " + t.encode()]  # noqa: E731

        # Known token: lexical gate passes, the Step 8 wire cap applies.
        raw = _frame("/v1/list", base + bearer(_MAIN_TOKEN) + huge, body)
        status, code, unc, retry = _err(_exchange(a.port, raw))
        self.assertEqual((status, code), (413, "too_large"))
        self.assertFalse(unc)
        self.assertFalse(retry)

        # Lexically valid but UNKNOWN token: it cannot be authenticated without
        # a source_id and body, so it still passes the lexical gate and the wire
        # cap applies (413, not 403).
        raw = _frame("/v1/list", base + bearer(_UNKNOWN_TOKEN) + huge, body)
        self.assertEqual(_err(_exchange(a.port, raw))[:2], (413, "too_large"))

        # Lexically INVALID token: the lexical gate rejects before the cap.
        raw = _frame("/v1/list", base + [b"Authorization: Bearer short"] + huge, body)
        self.assertEqual(_err(_exchange(a.port, raw))[:2], (403, "denied"))

        # No Authorization at all: same, rejected before the cap.
        raw = _frame("/v1/list", base + huge, body)
        self.assertEqual(_err(_exchange(a.port, raw))[:2], (403, "denied"))


@unittest.skipUnless(_ADAPTER_AVAILABLE, _SKIP_REASON)
class AliasIsolationTests(_Base):
''')

open(path, "w", encoding="utf-8").write(src)
print("applied:", done)
