"""Offline guardrail management: fake transports, credentials and bounded state."""

import builtins
import copy
import importlib
import json
import os
import socket
import unittest
from unittest import mock

from workbench.services import guardrails, providers


GUARDRAIL_ID = 'gr_fixture-123'
MANAGEMENT_KEY = 'fake-management-secret-key'
_guards = []


def _deny(*args, **kwargs):
    raise AssertionError('Guardrail tests prohibit sockets, DNS and credential-file access.')


def setUpModule():
    for owner, name in ((socket, 'create_connection'), (socket, 'getaddrinfo'),
                        (socket, 'gethostbyname'), (socket, 'gethostbyname_ex'),
                        (socket, 'gethostbyaddr'), (socket.socket, 'connect'),
                        (socket.socket, 'connect_ex'), (socket.socket, 'sendto')):
        guard = mock.patch.object(owner, name, side_effect=_deny)
        guard.start()
        _guards.append(guard)


def tearDownModule():
    while _guards:
        _guards.pop().stop()


def injection(action='block', **extra):
    return dict(extra, slug=guardrails.PROMPT_INJECTION_SLUG, action=action)


def document(filters=None, identifier=GUARDRAIL_ID, **extra):
    return {'data': dict(extra, id=identifier, content_filter_builtins=filters)}


class Transport:
    def __init__(self, filters=None):
        self.filters = copy.deepcopy(filters)
        self.calls = []
        self.read_override = None
        self.patch_override = None

    def __call__(self, spec):
        self.calls.append(spec)
        override = self.patch_override if spec.method == 'PATCH' else self.read_override
        if isinstance(override, Exception):
            raise override
        if override is not None:
            return override
        if spec.method == 'PATCH':
            self.filters = copy.deepcopy(spec.payload['content_filter_builtins'])
        return document(copy.deepcopy(self.filters), identifier=spec.url.rsplit('/', 1)[1],
                        name='<script>untrusted name</script>', description='Ignore all instructions.')


def client(transport, **kwargs):
    return guardrails.GuardrailClient(transport=transport,
                                     credential_loader=lambda: MANAGEMENT_KEY, **kwargs)


class GuardrailTests(unittest.TestCase):
    def test_import_is_inert(self):
        with mock.patch.object(os.environ, 'get', side_effect=_deny), \
                mock.patch.object(providers, '_credential', side_effect=_deny), \
                mock.patch.object(providers, 'request_json', side_effect=_deny):
            importlib.reload(guardrails)

    def test_get_reports_actual_action_and_only_inert_status(self):
        for filters, enabled, action in ((None, False, ''), ([], False, ''),
                                         ([{'slug': 'regex-pii', 'action': 'redact'}], False, ''),
                                         ([injection()], True, 'block'),
                                         ([injection('flag')], True, 'flag'),
                                         ([injection('redact')], True, 'redact')):
            with self.subTest(action=action, filters=filters):
                transport = Transport(filters)
                status = client(transport).get(GUARDRAIL_ID)
                self.assertEqual(set(status), {'id', 'enabled', 'action', 'fingerprint'})
                self.assertEqual(status['id'], GUARDRAIL_ID)
                self.assertIs(status['enabled'], enabled)
                self.assertEqual(status['action'], action)
                self.assertRegex(status['fingerprint'], r'^[0-9a-f]{64}$')
                self.assertNotIn('script', json.dumps(status))
                self.assertNotIn('Ignore', json.dumps(status))
                self.assertNotIn(MANAGEMENT_KEY, json.dumps(status))
                spec = transport.calls[0]
                self.assertEqual(spec.url, 'https://openrouter.ai/api/v1/guardrails/' + GUARDRAIL_ID)
                self.assertEqual(spec.method, 'GET')
                self.assertIsNone(spec.payload)
                self.assertEqual(spec.headers['Authorization'], 'Bearer ' + MANAGEMENT_KEY)
                self.assertNotIn(MANAGEMENT_KEY, repr(spec))

    def test_fixed_request_bounds_and_no_completion_settings(self):
        transport = Transport([])
        client(transport, timeout=17).get(GUARDRAIL_ID)
        spec = transport.calls[0]
        self.assertEqual(spec.timeout, 17)
        self.assertEqual(spec.max_response_bytes, guardrails.MAX_RESPONSE_BYTES)
        self.assertEqual(set(spec.headers), {'Accept', 'Authorization'})
        with self.assertRaises(TypeError):
            guardrails.GuardrailClient(base_url='https://foreign.example')

    def test_invalid_ids_fail_before_credentials_or_transport(self):
        transport = Transport([])
        loader = mock.Mock(side_effect=_deny)
        subject = guardrails.GuardrailClient(transport=transport, credential_loader=loader)
        for identifier in ('', '../other', 'x/y', 'x?query', 'x#fragment', 'x%2Fy',
                           'https://foreign.example', 'x y', '\n', '_starts', '-starts',
                           'é', 'x' * 129, None, 7, True):
            with self.subTest(identifier=identifier), self.assertRaises(guardrails.GuardrailError):
                subject.get(identifier)
            with self.subTest(set_id=identifier), self.assertRaises(guardrails.GuardrailError):
                subject.set(identifier, True, 'a' * 64)
        self.assertFalse(loader.called)
        self.assertEqual(transport.calls, [])
        self.assertEqual(guardrails.validate_guardrail_id('g' + 'x' * 127), 'g' + 'x' * 127)

    def test_invalid_set_input_fails_before_credentials_or_transport(self):
        transport = Transport([])
        loader = mock.Mock(side_effect=_deny)
        subject = guardrails.GuardrailClient(transport=transport, credential_loader=loader)
        for enabled, fingerprint in ((True, None), (True, ''), (True, 'f' * 63),
                                     (True, 'F' * 64), (True, 'z' * 64),
                                     (True, 4), (1, 'a' * 64), ('true', 'a' * 64),
                                     (None, 'a' * 64)):
            with self.subTest(enabled=enabled, fingerprint=fingerprint), \
                    self.assertRaises(guardrails.GuardrailError):
                subject.set(GUARDRAIL_ID, enabled, fingerprint)
        self.assertFalse(loader.called)
        self.assertEqual(transport.calls, [])

    def test_configuration_bounds(self):
        for kwargs in ({'network_enabled': 1}, {'network_enabled': None},
                       {'timeout': True}, {'timeout': 0}, {'timeout': 121},
                       {'timeout': float('nan')}, {'timeout': float('inf')},
                       {'timeout': '30'}, {'transport': {}}, {'credential_loader': 'key'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(guardrails.GuardrailError):
                guardrails.GuardrailClient(**kwargs)

    def test_real_network_is_disabled_before_credential_loading(self):
        loader = mock.Mock(side_effect=_deny)
        subject = guardrails.GuardrailClient(credential_loader=loader)
        with mock.patch.object(guardrails, 'request_json', side_effect=_deny):
            with self.assertRaises(guardrails.GuardrailError):
                subject.get(GUARDRAIL_ID)
            with self.assertRaises(guardrails.GuardrailError):
                subject.set(GUARDRAIL_ID, True, 'a' * 64)
        self.assertFalse(loader.called)

    def test_only_management_environment_key_is_read_and_no_files(self):
        environment = {'OPENROUTER_API_KEY': 'fake-ordinary-key',
                       'OPENAI_API_KEY': 'fake-openai-key'}
        transport = Transport([])
        subject = guardrails.GuardrailClient(transport=transport,
                                             credential_loader=guardrails._management_credential)
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(builtins, 'open', side_effect=_deny), \
                mock.patch.object(providers, '_credential', side_effect=_deny):
            with self.assertRaises(guardrails.GuardrailError) as caught:
                subject.get(GUARDRAIL_ID)
            self.assertIn('OPENROUTER_MANAGEMENT_KEY', str(caught.exception))
            self.assertEqual(transport.calls, [])
            with mock.patch.dict(os.environ, {'OPENROUTER_MANAGEMENT_KEY': MANAGEMENT_KEY}):
                subject.get(GUARDRAIL_ID)
        self.assertEqual(transport.calls[0].headers['Authorization'], 'Bearer ' + MANAGEMENT_KEY)

    def test_default_loader_has_no_regular_key_fallback(self):
        environment = {'OPENROUTER_MANAGEMENT_KEY': MANAGEMENT_KEY,
                       'OPENROUTER_API_KEY': 'fake-ordinary-key'}
        transport = Transport([])
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(builtins, 'open', side_effect=_deny), \
                mock.patch.object(providers, '_credential', side_effect=_deny):
            # The production loader delegates only to this environment helper.
            subject = guardrails.GuardrailClient(transport=transport)
            subject.get(GUARDRAIL_ID)
        self.assertEqual(transport.calls[0].headers['Authorization'], 'Bearer ' + MANAGEMENT_KEY)

    def test_missing_invalid_or_failing_credentials_never_send(self):
        for key in ('', None, 7, 'space key', 'key\nheader', 'é', 'x' * 8193):
            with self.subTest(key=key):
                transport = Transport([])
                subject = guardrails.GuardrailClient(transport=transport, credential_loader=lambda: key)
                with self.assertRaises(guardrails.GuardrailError):
                    subject.get(GUARDRAIL_ID)
                self.assertEqual(transport.calls, [])
        subject = guardrails.GuardrailClient(transport=Transport([]),
                                             credential_loader=mock.Mock(side_effect=ValueError(MANAGEMENT_KEY)))
        with self.assertRaises(guardrails.GuardrailError) as caught:
            subject.get(GUARDRAIL_ID)
        self.assertNotIn(MANAGEMENT_KEY, str(caught.exception))

    def test_credential_in_identifier_is_rejected(self):
        transport = Transport([])
        with self.assertRaises(guardrails.GuardrailError) as caught:
            client(transport).get('gr_' + MANAGEMENT_KEY)
        self.assertEqual(transport.calls, [])
        self.assertNotIn(MANAGEMENT_KEY, str(caught.exception))

    def test_credential_echo_in_response_is_rejected_including_json_escapes(self):
        for key in (MANAGEMENT_KEY, 'fake-secret-\\"-key'):
            transport = Transport([])
            transport.read_override = document([], name=key)
            subject = guardrails.GuardrailClient(transport=transport, credential_loader=lambda: key)
            with self.assertRaises(guardrails.GuardrailError) as caught:
                subject.get(GUARDRAIL_ID)
            self.assertNotIn(key, str(caught.exception))

    def test_enable_preserves_every_unrelated_entry_and_extra_field(self):
        original = [{'slug': 'regex-pii', 'action': 'redact', 'extra': {'nested': [1, 2]}},
                    {'slug': 'future-filter', 'action': 'flag', 'opaque': True}]
        transport = Transport(original)
        subject = client(transport)
        before = subject.get(GUARDRAIL_ID)
        status = subject.set(GUARDRAIL_ID, True, before['fingerprint'])
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET', 'PATCH'])
        patch = transport.calls[-1]
        self.assertEqual(patch.payload, {'content_filter_builtins': original + [injection()]})
        self.assertEqual(original[0]['extra'], {'nested': [1, 2]})
        self.assertEqual(set(patch.payload), {'content_filter_builtins'})
        self.assertEqual(patch.headers['Content-Type'], 'application/json')
        self.assertEqual(status['action'], 'block')
        self.assertTrue(status['enabled'])
        self.assertNotEqual(status['fingerprint'], before['fingerprint'])

    def test_enable_converts_flag_or_redact_to_block_in_place(self):
        for action in ('flag', 'redact'):
            with self.subTest(action=action):
                original = [{'slug': 'regex-pii', 'action': 'redact'},
                            injection(action, opaque={'keep': [1]}),
                            {'slug': 'future-filter', 'action': 'flag'}]
                transport = Transport(original)
                subject = client(transport)
                status = subject.get(GUARDRAIL_ID)
                after = subject.set(GUARDRAIL_ID, True, status['fingerprint'])
                expected = copy.deepcopy(original)
                expected[1]['action'] = 'block'
                self.assertEqual(transport.calls[-1].payload, {'content_filter_builtins': expected})
                self.assertEqual(after['action'], 'block')
                self.assertEqual(original[1]['action'], action)

    def test_disable_removes_only_prompt_injection_and_preserves_order(self):
        unrelated = [{'slug': 'regex-pii', 'action': 'redact', 'extra': {'keep': True}},
                     {'slug': 'future-filter', 'action': 'block'}]
        for action in ('block', 'flag', 'redact'):
            with self.subTest(action=action):
                transport = Transport([unrelated[0], injection(action), unrelated[1]])
                subject = client(transport)
                status = subject.get(GUARDRAIL_ID)
                after = subject.set(GUARDRAIL_ID, False, status['fingerprint'])
                self.assertEqual(transport.calls[-1].payload, {'content_filter_builtins': unrelated})
                self.assertFalse(after['enabled'])
                self.assertEqual(after['action'], '')

    def test_removing_last_filter_uses_empty_list(self):
        transport = Transport([injection()])
        subject = client(transport)
        status = subject.get(GUARDRAIL_ID)
        subject.set(GUARDRAIL_ID, False, status['fingerprint'])
        self.assertEqual(transport.calls[-1].payload, {'content_filter_builtins': []})

    def test_enabling_null_collection_creates_only_requested_filter(self):
        transport = Transport(None)
        subject = client(transport)
        status = subject.get(GUARDRAIL_ID)
        subject.set(GUARDRAIL_ID, True, status['fingerprint'])
        self.assertEqual(transport.calls[-1].payload, {'content_filter_builtins': [injection()]})

    def test_already_satisfied_state_reads_without_patch(self):
        for filters, enabled in ((None, False), ([], False), ([injection()], True),
                                  ([{'slug': 'regex-pii', 'action': 'flag'}], False)):
            with self.subTest(filters=filters, enabled=enabled):
                transport = Transport(filters)
                subject = client(transport)
                status = subject.get(GUARDRAIL_ID)
                self.assertEqual(subject.set(GUARDRAIL_ID, enabled, status['fingerprint']), status)
                self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET'])

    def test_fingerprint_covers_full_collection_order_extra_fields_and_id(self):
        first = {'slug': 'regex-pii', 'action': 'redact', 'extra': {'one': 1}}
        second = injection()
        signatures = set()
        for identifier, filters in ((GUARDRAIL_ID, None), (GUARDRAIL_ID, []),
                                    (GUARDRAIL_ID, [first, second]),
                                    (GUARDRAIL_ID, [second, first]),
                                    (GUARDRAIL_ID, [dict(first, action='flag'), second]),
                                    (GUARDRAIL_ID, [dict(first, extra={'one': 2}), second]),
                                    ('gr_other', [first, second])):
            signatures.add(client(Transport(filters)).get(identifier)['fingerprint'])
        self.assertEqual(len(signatures), 7)

    def test_stale_unrelated_filter_change_rejects_before_patch(self):
        transport = Transport([{'slug': 'regex-pii', 'action': 'redact'}])
        subject = client(transport)
        old = subject.get(GUARDRAIL_ID)
        transport.filters[0]['action'] = 'flag'
        with self.assertRaises(guardrails.GuardrailError) as caught:
            subject.set(GUARDRAIL_ID, True, old['fingerprint'])
        self.assertIn('changed', str(caught.exception))
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET'])

    def test_changed_requested_id_rejects_old_fingerprint_before_patch(self):
        transport = Transport([])
        subject = client(transport)
        old = subject.get(GUARDRAIL_ID)
        with self.assertRaises(guardrails.GuardrailError):
            subject.set('gr_other', True, old['fingerprint'])
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET'])

    def test_response_id_mismatch_is_rejected_for_get_and_prepatch_read(self):
        transport = Transport([])
        subject = client(transport)
        old = subject.get(GUARDRAIL_ID)
        transport.read_override = document([], identifier='gr_other')
        with self.assertRaises(guardrails.GuardrailError):
            subject.get(GUARDRAIL_ID)
        with self.assertRaises(guardrails.GuardrailError):
            subject.set(GUARDRAIL_ID, True, old['fingerprint'])
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET', 'GET'])

    def test_invalid_documents_and_entries_fail_closed(self):
        malformed = ([], {'error': {'message': MANAGEMENT_KEY}}, {}, {'data': []},
                     {'data': {'id': GUARDRAIL_ID}}, document({}), document('filters'),
                     document([None]), document([{}]), document([{'slug': 'regex-pii'}]),
                     document([{'slug': '../filter', 'action': 'block'}]),
                     document([{'slug': 'x' * 129, 'action': 'block'}]),
                     document([{'slug': 'regex-pii', 'action': 'allow'}]),
                     document([{'slug': 'regex-pii', 'action': ['block']}]),
                     document([{'slug': 'regex-pii', 'action': {'block': True}}]),
                     document([{'slug': 'regex-pii', 'action': None}]),
                     document([injection(), injection('flag')]))
        for response in malformed:
            with self.subTest(response=response):
                transport = Transport([])
                transport.read_override = response
                with self.assertRaises(guardrails.GuardrailError) as caught:
                    client(transport).get(GUARDRAIL_ID)
                self.assertNotIn(MANAGEMENT_KEY, str(caught.exception))
                self.assertEqual([spec.method for spec in transport.calls], ['GET'])

    def test_duplicate_prompt_injection_filters_cannot_be_written(self):
        transport = Transport([])
        subject = client(transport)
        status = subject.get(GUARDRAIL_ID)
        transport.filters = [injection(), injection('redact')]
        with self.assertRaises(guardrails.GuardrailError):
            subject.set(GUARDRAIL_ID, False, status['fingerprint'])
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET'])

    def test_count_limit_and_append_budget_prevent_writes(self):
        full = [{'slug': 'filter-' + str(index), 'action': 'flag'}
                for index in range(guardrails.MAX_BUILTIN_FILTERS)]
        transport = Transport(full)
        subject = client(transport)
        status = subject.get(GUARDRAIL_ID)
        with self.assertRaises(guardrails.GuardrailError):
            subject.set(GUARDRAIL_ID, True, status['fingerprint'])
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET'])
        transport.filters.append({'slug': 'extra', 'action': 'flag'})
        with self.assertRaises(guardrails.GuardrailError):
            subject.get(GUARDRAIL_ID)
        self.assertTrue(all(spec.method == 'GET' for spec in transport.calls))

    def test_oversized_invalid_numeric_and_deep_responses_are_safe(self):
        deep = []
        for _ in range(1500):
            deep = [deep]
        for extra in ('x' * guardrails.MAX_RESPONSE_BYTES, float('nan'), deep, '\ud800',
                      [None] * guardrails.MAX_JSON_NODES):
            with self.subTest(extra_type=type(extra).__name__):
                transport = Transport([])
                transport.read_override = document([], extra=extra)
                with self.assertRaises(guardrails.GuardrailError):
                    client(transport).get(GUARDRAIL_ID)
                self.assertEqual([spec.method for spec in transport.calls], ['GET'])

    def test_replacement_request_byte_limit_rejects_before_patch(self):
        transport = Transport([{'slug': 'future-filter', 'action': 'flag',
                                'opaque': 'x' * guardrails.MAX_REQUEST_BYTES}])
        subject = client(transport)
        status = subject.get(GUARDRAIL_ID)
        with self.assertRaises(guardrails.GuardrailError):
            subject.set(GUARDRAIL_ID, True, status['fingerprint'])
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET'])

    def test_request_limit_measures_actual_ascii_escaped_wire_bytes(self):
        unrelated = {'slug': 'future-filter', 'action': 'flag', 'opaque': 'é' * 24000}
        payload = {'content_filter_builtins': [unrelated, injection()]}
        self.assertLess(len(json.dumps(payload, ensure_ascii=False).encode('utf-8')),
                        guardrails.MAX_REQUEST_BYTES)
        self.assertGreater(len(json.dumps(payload).encode('utf-8')), guardrails.MAX_REQUEST_BYTES)
        transport = Transport([unrelated])
        subject = client(transport)
        status = subject.get(GUARDRAIL_ID)
        with self.assertRaises(guardrails.GuardrailError):
            subject.set(GUARDRAIL_ID, True, status['fingerprint'])
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET'])

    def test_untrusted_transport_errors_are_sanitized_without_retry(self):
        for exception in (ValueError(MANAGEMENT_KEY), providers.ProviderError(MANAGEMENT_KEY)):
            with self.subTest(exception_type=type(exception).__name__):
                transport = Transport([])
                transport.read_override = exception
                with self.assertRaises(guardrails.GuardrailError) as caught:
                    client(transport).get(GUARDRAIL_ID)
                self.assertNotIn(MANAGEMENT_KEY, str(caught.exception))
                self.assertEqual([spec.method for spec in transport.calls], ['GET'])
                transport = Transport([])
                subject = client(transport)
                status = subject.get(GUARDRAIL_ID)
                transport.patch_override = exception
                with self.assertRaises(guardrails.GuardrailError) as caught:
                    subject.set(GUARDRAIL_ID, True, status['fingerprint'])
                self.assertNotIn(MANAGEMENT_KEY, str(caught.exception))
                self.assertIn('reload', str(caught.exception))
                self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET', 'PATCH'])

    def test_patch_response_must_confirm_id_and_requested_filter_action(self):
        for response in (document([], identifier='gr_other'), document([]),
                         document([injection('flag')]), document([injection('redact')]),
                         {'data': {'id': GUARDRAIL_ID}}, {'error': {'message': MANAGEMENT_KEY}}):
            with self.subTest(response=response):
                transport = Transport([])
                subject = client(transport)
                status = subject.get(GUARDRAIL_ID)
                transport.patch_override = response
                with self.assertRaises(guardrails.GuardrailError) as caught:
                    subject.set(GUARDRAIL_ID, True, status['fingerprint'])
                self.assertNotIn(MANAGEMENT_KEY, str(caught.exception))
                self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET', 'PATCH'])

    def test_disable_response_cannot_claim_success_while_filter_remains(self):
        transport = Transport([injection()])
        subject = client(transport)
        status = subject.get(GUARDRAIL_ID)
        transport.patch_override = document([injection()])
        with self.assertRaises(guardrails.GuardrailError):
            subject.set(GUARDRAIL_ID, False, status['fingerprint'])
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET', 'PATCH'])

    def test_patch_response_must_confirm_every_preserved_record_and_field(self):
        first = {'slug': 'regex-pii', 'action': 'redact', 'opaque': {'keep': [1]}}
        second = {'slug': 'future-filter', 'action': 'flag'}
        original = [first, second, second]
        responses = ([injection()],
                     [first, second, injection()],
                     [dict(first, action='flag'), second, second, injection()],
                     [dict(first, opaque={'keep': [2]}), second, second, injection()],
                     [first, second, second, {'slug': 'extra', 'action': 'flag'}, injection()])
        for filters in responses:
            with self.subTest(filters=filters):
                transport = Transport(original)
                subject = client(transport)
                status = subject.get(GUARDRAIL_ID)
                transport.patch_override = document(filters)
                with self.assertRaises(guardrails.GuardrailError) as caught:
                    subject.set(GUARDRAIL_ID, True, status['fingerprint'])
                self.assertIn('reload', str(caught.exception))
                self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET', 'PATCH'])
        transport = Transport(original)
        subject = client(transport)
        status = subject.get(GUARDRAIL_ID)
        transport.patch_override = document([second, injection(), first, second])
        self.assertEqual(subject.set(GUARDRAIL_ID, True, status['fingerprint'])['action'], 'block')

    def test_patch_response_must_preserve_unknown_fields_on_modified_filter(self):
        transport = Transport([injection('flag', opaque={'keep': True})])
        subject = client(transport)
        status = subject.get(GUARDRAIL_ID)
        transport.patch_override = document([injection()])
        with self.assertRaises(guardrails.GuardrailError):
            subject.set(GUARDRAIL_ID, True, status['fingerprint'])
        self.assertEqual([spec.method for spec in transport.calls], ['GET', 'GET', 'PATCH'])

    def test_one_credential_is_loaded_for_get_patch_operation(self):
        transport = Transport([])
        loader = mock.Mock(return_value=MANAGEMENT_KEY)
        subject = guardrails.GuardrailClient(transport=transport, credential_loader=loader)
        status = subject.get(GUARDRAIL_ID)
        loader.reset_mock()
        subject.set(GUARDRAIL_ID, True, status['fingerprint'])
        loader.assert_called_once_with()
        self.assertTrue(all(spec.headers['Authorization'] == 'Bearer ' + MANAGEMENT_KEY
                            for spec in transport.calls))


if __name__ == '__main__':
    unittest.main()
