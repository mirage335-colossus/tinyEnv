"""Local OpenRouter configuration and requests keep credentials off output channels."""
import contextlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request
import urllib.response


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('openrouter', ROOT / 'tools/openrouter.py')
router = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = router
spec.loader.exec_module(router)

KEY = 'test-local-openrouter-key'
MODEL = 'example/model'


class Response(io.BytesIO):
    def __init__(self, value):
        super().__init__(json.dumps(value).encode('utf-8'))
        self.headers = {}
        self.status = 200


class OpenRouterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='openrouter-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / '.env.openrouter'
        self.config = router.Config(api_key=KEY, model=MODEL)
        # Even an accidentally unmocked call must fail before network access.
        self.socket_patch = mock.patch('socket.create_connection', side_effect=AssertionError('unexpected network access'))
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)

    def write_config(self, text=None):
        self.path.write_text(text if text is not None else
                             'OPENROUTER_API_KEY=' + KEY + '\nOPENROUTER_MODEL=' + MODEL + '\n',
                             encoding='utf-8')
        self.path.chmod(0o600)
        return self.path

    def run_main(self, args, *, stdin='', environment=None):
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(router, 'CONFIG_PATH', self.path), \
             mock.patch.dict(os.environ, environment or {}, clear=True), \
             mock.patch.object(sys, 'stdin', io.StringIO(stdin)), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                result = router.main(args)
            except SystemExit as exited:
                result = exited.code
        return result, output.getvalue(), errors.getvalue()

    def request(self, value=None, *, error=None, method='GET', path='/key', payload=None, timeout=30):
        opener = mock.Mock()
        if error is not None:
            opener.open.side_effect = error
        else:
            opener.open.return_value = Response(value if value is not None else {'data': {}})
        with mock.patch.object(urllib.request, 'build_opener', return_value=opener) as build:
            result = router.request_json(self.config, method, path, payload, timeout=timeout)
        return result, opener, build

    def test_comments_quotes_and_shell_looking_values_are_literal(self):
        marker = self.root / 'must-not-exist'
        model = '$(touch ' + str(marker) + ')'
        self.write_config('# local settings\n\nOPENROUTER_API_KEY="' + KEY + '"\n'
                          "OPENROUTER_MODEL='" + model + "'\n")
        config = router.load_config(self.path, environ={})
        self.assertEqual(KEY, config.api_key)
        self.assertEqual(model, config.model)
        self.assertFalse(marker.exists())

    def test_environment_overrides_each_variable_independently(self):
        self.write_config()
        key_only = router.load_config(self.path, environ={'OPENROUTER_API_KEY': 'environment-key'})
        model_only = router.load_config(self.path, environ={'OPENROUTER_MODEL': 'provider/environment'})
        self.assertEqual(('environment-key', MODEL), (key_only.api_key, key_only.model))
        self.assertEqual((KEY, 'provider/environment'), (model_only.api_key, model_only.model))

    def test_empty_environment_override_does_not_restore_file_secret(self):
        self.write_config()
        config = router.load_config(self.path, environ={'OPENROUTER_API_KEY': ''})
        self.assertEqual('', config.api_key)
        self.assertEqual(MODEL, config.model)
        with mock.patch.object(router, 'request_json') as request:
            code, output, error = self.run_main(['check'], environment={'OPENROUTER_API_KEY': ''})
        self.assertNotEqual(0, code)
        request.assert_not_called()
        self.assertNotIn(KEY, output + error)

    def test_absent_file_allows_environment_only_configuration(self):
        config = router.load_config(self.path, environ={'OPENROUTER_API_KEY': KEY, 'OPENROUTER_MODEL': MODEL})
        self.assertEqual((KEY, MODEL), (config.api_key, config.model))
        empty = router.load_config(self.path, environ={})
        self.assertEqual(('', ''), (empty.api_key, empty.model))

    def test_invalid_config_never_echoes_values(self):
        for text in ('export OPENROUTER_API_KEY=' + KEY,
                     'UNKNOWN=' + KEY,
                     'OPENROUTER_API_KEY=' + KEY + '\nOPENROUTER_API_KEY=other',
                     'OPENROUTER_API_KEY="' + KEY,
                     'OPENROUTER_API_KEY=' + KEY + '\nmalformed ' + KEY):
            with self.subTest(text=text):
                self.write_config(text)
                with self.assertRaises(router.OpenRouterError) as raised:
                    router.load_config(self.path, environ={})
                self.assertNotIn(KEY, str(raised.exception))

    def test_header_unsafe_keys_fail_without_echoing_them(self):
        for key in (KEY + '\r\nInjected: value', KEY + '\tvalue', KEY + ' value', KEY + '\x00', KEY + '\u00e9'):
            with self.subTest(kind=repr(key[len(KEY):])):
                with self.assertRaises(router.OpenRouterError) as raised:
                    router.load_config(self.path, environ={'OPENROUTER_API_KEY': key})
                self.assertNotIn(KEY, str(raised.exception))

    def test_invalid_utf8_and_oversized_configuration_fail_safely(self):
        for value in (KEY.encode() + b'\xff', b'#' + KEY.encode() + b'x' * 65536):
            with self.subTest(size=len(value)):
                self.path.write_bytes(value)
                self.path.chmod(0o600)
                with self.assertRaises(router.OpenRouterError) as raised:
                    router.load_config(self.path, environ={})
                self.assertNotIn(KEY, str(raised.exception))

    def test_directory_cannot_be_loaded_as_configuration(self):
        self.path.mkdir()
        with self.assertRaises(router.OpenRouterError):
            router.load_config(self.path, environ={})

    def test_config_repr_never_contains_key_or_model(self):
        self.assertNotIn(KEY, repr(self.config))
        self.assertNotIn(MODEL, repr(self.config))

    def test_init_creates_empty_private_configuration(self):
        if os.name != 'posix':
            with self.assertRaises(router.OpenRouterError):
                router.init_config(self.path)
            self.assertFalse(self.path.exists())
            return
        result = router.init_config(self.path)
        self.assertEqual(self.path, result)
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))
        self.assertEqual(('', ''), (router.load_config(self.path, environ={}).api_key,
                                 router.load_config(self.path, environ={}).model))
        self.assertNotIn(KEY, self.path.read_text())

    def test_init_preserves_existing_configuration(self):
        self.write_config()
        original = self.path.read_bytes()
        with self.assertRaises(router.OpenRouterError) as raised:
            router.init_config(self.path)
        self.assertEqual(original, self.path.read_bytes())
        self.assertNotIn(KEY, str(raised.exception))

    def test_init_cannot_follow_or_replace_symlink(self):
        if os.name != 'posix':
            with self.assertRaises(router.OpenRouterError):
                router.init_config(self.path)
            return
        target = self.root / 'preserved'
        target.write_text('unrelated data')
        self.path.symlink_to(target)
        with self.assertRaises(router.OpenRouterError):
            router.init_config(self.path)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual('unrelated data', target.read_text())
        target.unlink()
        with self.assertRaises(router.OpenRouterError):
            router.init_config(self.path)
        self.assertTrue(self.path.is_symlink())
        self.assertFalse(target.exists())

    def test_posix_load_rejects_shared_permissions_and_symlinks(self):
        self.write_config()
        if os.name != 'posix':
            self.assertEqual(KEY, router.load_config(self.path, environ={}).api_key)
            return
        for permissions in (0o640, 0o604, 0o666):
            with self.subTest(permissions=permissions):
                self.path.chmod(permissions)
                with self.assertRaises(router.OpenRouterError) as raised:
                    router.load_config(self.path, environ={})
                self.assertNotIn(KEY, str(raised.exception))
        self.path.chmod(0o600)
        target = self.root / 'private'
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(router.OpenRouterError):
            router.load_config(self.path, environ={})

    def test_default_configuration_is_repository_relative_from_other_cwd(self):
        self.assertEqual(ROOT / '.env.openrouter', router.CONFIG_PATH)
        self.write_config()
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.object(router, 'CONFIG_PATH', self.path):
                config = router.load_config(environ={})
            self.assertEqual((KEY, MODEL), (config.api_key, config.model))
        finally:
            os.chdir(previous)

    def test_status_is_offline_and_reports_only_presence(self):
        self.write_config()
        with mock.patch.object(router, 'request_json') as request:
            code, output, error = self.run_main(['status'])
        self.assertEqual(0, code)
        self.assertEqual('API key: configured\nModel: configured\n', output)
        self.assertEqual('', error)
        request.assert_not_called()
        self.assertNotIn(KEY, output)
        self.assertNotIn(MODEL, output)

    def test_status_missing_key_has_failure_exit(self):
        code, output, error = self.run_main(['status'])
        self.assertNotEqual(0, code)
        self.assertEqual('API key: missing\nModel: missing\n', output)
        self.assertEqual('', error)

    def test_check_uses_only_authentication_endpoint_and_suppresses_account_data(self):
        self.write_config()
        with mock.patch.object(router, 'request_json', return_value={'data': {'label': KEY, 'limit': 10}}) as request:
            code, output, error = self.run_main(['check'])
        self.assertEqual(0, code)
        self.assertEqual('OpenRouter authentication succeeded.\n', output)
        self.assertEqual('', error)
        self.assertEqual(('GET', '/key'), request.call_args.args[1:3])
        self.assertEqual(KEY, request.call_args.args[0].api_key)
        self.assertNotIn(KEY, output)

    def test_check_rejects_malformed_success_payload(self):
        self.write_config()
        for value in ({}, {'data': None}, {'data': 'not an account object'}):
            with self.subTest(value=value), mock.patch.object(router, 'request_json', return_value=value):
                code, output, error = self.run_main(['check'])
            self.assertNotEqual(0, code)
            self.assertNotIn('authentication succeeded', output)
            self.assertNotIn(KEY, output + error)

    def test_chat_reads_stdin_and_sends_bounded_payload(self):
        self.write_config()
        response = {'choices': [{'message': {'content': 'A useful response.'}}]}
        with mock.patch.object(router, 'request_json', return_value=response) as request:
            code, output, error = self.run_main(['chat'], stdin='prompt from stdin\n')
        self.assertEqual(0, code)
        self.assertEqual('A useful response.\n', output)
        self.assertEqual('', error)
        self.assertEqual(('POST', '/chat/completions'), request.call_args.args[1:3])
        payload = request.call_args.args[3]
        self.assertEqual(MODEL, payload['model'])
        self.assertEqual(256, payload['max_tokens'])
        self.assertEqual([{'role': 'user', 'content': 'prompt from stdin\n'}], payload['messages'])
        self.assertNotIn(KEY, json.dumps(payload))

    def test_chat_model_override_and_explicit_limits_are_used(self):
        self.write_config()
        with mock.patch.object(router, 'request_json', return_value={'choices': [{'message': {'content': 'ok'}}]}) as request:
            code, output, error = self.run_main(
                ['chat', '--model', 'provider/override', '--max-tokens', '17', '--timeout', '9'], stdin='test')
        self.assertEqual(0, code)
        self.assertEqual('provider/override', request.call_args.args[3]['model'])
        self.assertEqual(17, request.call_args.args[3]['max_tokens'])
        self.assertEqual(9, request.call_args.kwargs['timeout'])

    def test_chat_missing_key_model_or_prompt_does_not_make_request(self):
        configurations = (('OPENROUTER_MODEL=' + MODEL, 'prompt'),
                          ('OPENROUTER_API_KEY=' + KEY, 'prompt'),
                          ('OPENROUTER_API_KEY=' + KEY + '\nOPENROUTER_MODEL=' + MODEL, ''))
        for text, prompt in configurations:
            with self.subTest(text=text, prompt=prompt):
                self.write_config(text)
                with mock.patch.object(router, 'request_json') as request:
                    code, output, error = self.run_main(['chat'], stdin=prompt)
                self.assertNotEqual(0, code)
                request.assert_not_called()
                self.assertNotIn(KEY, output + error)

    def test_chat_whitespace_and_oversized_prompt_do_not_make_request(self):
        self.write_config()
        for prompt in (' \n\t', 'x' * 65537):
            with self.subTest(size=len(prompt)), mock.patch.object(router, 'request_json') as request:
                code, output, error = self.run_main(['chat'], stdin=prompt)
            self.assertNotEqual(0, code)
            request.assert_not_called()

    def test_invalid_model_or_numeric_argument_does_not_make_request_or_echo_input(self):
        self.write_config()
        for args in (['chat', '--model', KEY], ['chat', '--max-tokens', '0'],
                     ['chat', '--max-tokens', '65537'], ['chat', '--timeout', '0'],
                     ['check', '--timeout', '121'], ['chat', '--timeout', KEY]):
            with self.subTest(args=args), mock.patch.object(router, 'request_json') as request:
                code, output, error = self.run_main(args, stdin='prompt')
            self.assertNotEqual(0, code)
            request.assert_not_called()
            self.assertNotIn(KEY, output + error)

    def test_chat_redacts_exact_credential_from_model_response(self):
        self.write_config()
        response = {'choices': [{'message': {'content': 'echo ' + KEY + ' / ' + KEY}}]}
        with mock.patch.object(router, 'request_json', return_value=response):
            code, output, error = self.run_main(['chat'], stdin='prompt')
        self.assertEqual(0, code)
        self.assertEqual('echo [REDACTED] / [REDACTED]\n', output)
        self.assertNotIn(KEY, output + error)

    def test_chat_malformed_response_is_a_safe_failure(self):
        self.write_config()
        for value in ({}, {'choices': []}, {'choices': [{'message': {'content': None}}]},
                      {'choices': [{'message': {'content': {'secret': KEY}}}]}):
            with self.subTest(value=value), mock.patch.object(router, 'request_json', return_value=value):
                code, output, error = self.run_main(['chat'], stdin='prompt')
            self.assertNotEqual(0, code)
            self.assertNotIn(KEY, output + error)

    def test_request_has_fixed_https_origin_authorization_and_timeout(self):
        value, opener, build = self.request({'data': {}}, timeout=11)
        self.assertEqual({'data': {}}, value)
        request = opener.open.call_args.args[0]
        self.assertEqual('https://openrouter.ai/api/v1/key', request.full_url)
        self.assertEqual('GET', request.get_method())
        self.assertEqual('Bearer ' + KEY, request.get_header('Authorization'))
        self.assertIsNone(request.data)
        self.assertEqual(11, opener.open.call_args.kwargs['timeout'])
        self.assertEqual(1, build.call_count)

    def test_request_posts_json_with_only_supplied_payload(self):
        payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'request'}], 'max_tokens': 17}
        value, opener, build = self.request({'choices': []}, method='POST', path='/chat/completions', payload=payload)
        request = opener.open.call_args.args[0]
        self.assertEqual('https://openrouter.ai/api/v1/chat/completions', request.full_url)
        self.assertEqual('POST', request.get_method())
        self.assertEqual(payload, json.loads(request.data.decode('utf-8')))
        self.assertEqual('application/json', request.get_header('Content-type'))
        self.assertNotIn(KEY, request.data.decode('utf-8'))

    def test_unsupported_destination_or_method_cannot_send_credentials(self):
        for method, path in (('GET', 'https://credential-sink.invalid/key'),
                             ('GET', '//credential-sink.invalid/key'), ('GET', '/other'),
                             ('POST', '/key'), ('GET', '/chat/completions')):
            with self.subTest(method=method, path=path), mock.patch.object(urllib.request, 'build_opener') as build:
                with self.assertRaises(router.OpenRouterError):
                    router.request_json(self.config, method, path)
            build.assert_not_called()

    def test_unsafe_request_timeouts_fail_before_transport(self):
        for timeout in (0, 121, float('nan'), float('inf'), '30'):
            with self.subTest(timeout=timeout), mock.patch.object(urllib.request, 'build_opener') as build:
                with self.assertRaises(router.OpenRouterError):
                    router.request_json(self.config, 'GET', '/key', timeout=timeout)
            build.assert_not_called()

    def test_redirect_cannot_forward_authorization_to_another_origin(self):
        calls = []

        class OfflineHTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, request):
                calls.append(request)
                response = urllib.response.addinfourl(
                    io.BytesIO(b''), {'Location': 'https://credential-sink.invalid/key'}, request.full_url, 302)
                response.msg = 'Found'
                return response

        original = urllib.request.build_opener
        with mock.patch.object(urllib.request, 'build_opener',
                               side_effect=lambda *handlers: original(*handlers, OfflineHTTPSHandler())):
            with self.assertRaises(router.OpenRouterError) as raised:
                router.request_json(self.config, 'GET', '/key')
        self.assertEqual(1, len(calls))
        self.assertEqual('https://openrouter.ai/api/v1/key', calls[0].full_url)
        self.assertNotIn(KEY, str(raised.exception))

    def test_network_http_and_timeout_errors_do_not_echo_details(self):
        failures = (urllib.error.URLError('network ' + KEY), TimeoutError('timeout ' + KEY),
                    http.client.BadStatusLine('remote protocol ' + KEY),
                    http.client.IncompleteRead(KEY.encode(), len(KEY) + 10),
                    urllib.error.HTTPError('https://host/' + KEY, 401, 'denied ' + KEY, {}, io.BytesIO(KEY.encode())))
        for failure in failures:
            with self.subTest(kind=type(failure).__name__):
                with self.assertRaises(router.OpenRouterError) as raised:
                    self.request(error=failure)
                self.assertNotIn(KEY, str(raised.exception))
                self.assertNotIn('https://host/', str(raised.exception))

    def test_invalid_response_json_is_rejected_without_body_output(self):
        opener = mock.Mock()
        opener.open.return_value = io.BytesIO(('invalid body ' + KEY).encode())
        with mock.patch.object(urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(router.OpenRouterError) as raised:
                router.request_json(self.config, 'GET', '/key')
        self.assertNotIn(KEY, str(raised.exception))

    def test_response_scalar_list_and_provider_error_fail_without_output(self):
        for response in (None, 17, KEY, [KEY], {'error': {'message': KEY}}):
            with self.subTest(kind=type(response).__name__):
                opener = mock.Mock()
                opener.open.return_value = Response(response)
                with mock.patch.object(urllib.request, 'build_opener', return_value=opener):
                    with self.assertRaises(router.OpenRouterError) as raised:
                        router.request_json(self.config, 'GET', '/key')
                self.assertNotIn(KEY, str(raised.exception))

    def test_oversized_response_is_bounded_and_rejected(self):
        response = io.BytesIO(KEY.encode() + b'x' * (1024 * 1024))
        bounded = mock.Mock(wraps=response.read)
        response.read = bounded
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(router.OpenRouterError) as raised:
                router.request_json(self.config, 'GET', '/key')
        bounded.assert_called_once_with(1024 * 1024 + 1)
        self.assertTrue(response.closed)
        self.assertNotIn(KEY, str(raised.exception))


if __name__ == '__main__':
    unittest.main()
