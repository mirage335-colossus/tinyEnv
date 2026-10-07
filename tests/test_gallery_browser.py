"""Host browser prerequisites, version compatibility and failed-probe receipts."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import gallery_browser as B
import windows_graphics


def status(new=True, layer='Namespace'):
    rows = ([['Layer 1 Sandbox', layer]] if new else
            [['SUID sandbox', 'No'], ['Namespace sandbox', 'Yes']])
    return {'rows': rows + [['PID namespaces', 'Yes'], ['Network namespaces', 'Yes'],
            ['Seccomp-BPF sandbox', 'Yes'], ['Seccomp-BPF sandbox supports TSYNC', 'Yes']],
            'evaluation': 'You are adequately sandboxed.'}


class Options:
    def __init__(self): self.arguments = []; self.binary_location = None
    def add_argument(self, value): self.arguments.append(value)


class OldService:
    """The 4.8.3 public signature, without silently accepted irrelevant keywords."""
    def __init__(self, executable_path, port=0, service_args=None, log_path=None, env=None):
        self.path, self.service_args = executable_path, service_args
        self.stopped = False
    def stop(self): self.stopped = True


def selenium_modules(service=OldService):
    return {'selenium': types.SimpleNamespace(webdriver=types.SimpleNamespace()),
            'selenium.webdriver': types.SimpleNamespace(ChromeOptions=Options),
            'selenium.webdriver.chrome.service': types.SimpleNamespace(Service=service)}


class Browser:
    capabilities = {'browserName': 'chrome', 'browserVersion': '154.0.1.2',
                    'chrome': {'chromedriverVersion': '154.0.1.3 (fixture)'}}
    current_url = 'chrome://sandbox/'
    def __init__(self):
        self.closed = False
        self.state = status()
    def __enter__(self): return self
    def __exit__(self, *_): self.closed = True
    def set_page_load_timeout(self, value): self.page_timeout = value
    def set_script_timeout(self, value): self.script_timeout = value
    def execute_cdp_cmd(self, name, args):
        return {'arguments': ['/usr/bin/google-chrome', '--enable-automation']}
    def get(self, url): self.current_url = url
    def execute_script(self, _): return self.state
    def execute_async_script(self, _):
        return {'size': [160, 96], 'pixel': [16, 64, 128, 255], 'text': 'Ready', 'fonts': 'loaded'}
    def find_element(self, *args):
        return types.SimpleNamespace(screenshot_as_png=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' +
                                     struct.pack('>II', 160, 96))


class GalleryBrowserTests(unittest.TestCase):
    def test_old_and_current_sandbox_tables(self):
        for new in (False, True):
            with self.subTest(new=new):
                result = B.parse_sandbox(status(new))
                self.assertEqual(result['first_layer'], 'namespace')
                self.assertTrue(result['pid_namespaces'] and result['network_namespaces'] and result['seccomp_bpf'])
        self.assertEqual(B.parse_sandbox(status(layer='SUID'))['first_layer'], 'suid')

    def test_status_label_spacing_and_case_do_not_change_meaning(self):
        value = status()
        value['rows'] = [[label.upper() + '  ', '\n' + answer.lower()] for label, answer in value['rows']]
        self.assertEqual(B.parse_sandbox(value)['first_layer'], 'namespace')

    def test_disabled_missing_and_malformed_protections_fail(self):
        for index in range(4):
            for change in ('No', 'Unknown', '', None):
                with self.subTest(index=index, change=change):
                    value = status(); value['rows'][index][1] = change
                    with self.assertRaises(B.BrowserPrerequisiteError): B.parse_sandbox(value)
            value = status(); del value['rows'][index]
            with self.assertRaises(B.BrowserPrerequisiteError): B.parse_sandbox(value)

    def test_negative_evaluation_duplicate_and_conflicting_rows_fail(self):
        invalid = [status(), status(), status()]
        invalid[0]['evaluation'] = 'You are NOT adequately sandboxed.'
        invalid[1]['rows'].append(['PID namespaces', 'No'])
        invalid[2]['rows'].append(['Namespace sandbox', 'No'])
        for value in invalid:
            with self.assertRaises(B.BrowserPrerequisiteError): B.parse_sandbox(value)

    def test_no_namespace_or_setuid_layer_fails(self):
        value = status(False); value['rows'][1][1] = 'No'
        with self.assertRaises(B.BrowserPrerequisiteError): B.parse_sandbox(value)
        with self.assertRaises(B.BrowserPrerequisiteError): B.parse_sandbox(status(layer='None'))

    def test_optional_tsync_is_recorded_without_inventing_support(self):
        value = status(); value['rows'][-1][1] = 'No'
        self.assertFalse(B.parse_sandbox(value)['seccomp_tsync'])
        value['rows'].pop()
        self.assertFalse(B.parse_sandbox(value)['seccomp_tsync'])

    def test_actual_unsafe_arguments_are_rejected(self):
        for option in ('--no-sandbox', '--disable-setuid-sandbox', '--disable-namespace-sandbox',
                       '--disable-seccomp-filter-sandbox', '--disable-gpu-sandbox', '--single-process', '--no-zygote'):
            for suffix in ('', '=true'):
                with self.assertRaises(B.BrowserPrerequisiteError):
                    B.checked_arguments(['/browser', option + suffix])
        self.assertEqual(B.checked_arguments(['/browser', '--headless=new']), ['/browser', '--headless=new'])

    def test_authentication_and_loader_environment_never_reaches_browser(self):
        supplied = {'PATH': '/bin', 'HOME': '/home/fixture', 'LANG': 'C.UTF-8',
                    'GH_TOKEN': 'private', 'GITHUB_TOKEN': 'private',
                    'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'private', 'ACTIONS_ID_TOKEN_REQUEST_URL': 'private',
                    'LD_PRELOAD': '/foreign', 'PYTHONPATH': '/foreign', 'CHROMIUM_FLAGS': '--no-sandbox'}
        with mock.patch.dict(B.os.environ, supplied, clear=True):
            value = B.browser_environment()
        self.assertEqual(value, {'PATH': '/bin', 'HOME': '/home/fixture', 'LANG': 'C.UTF-8',
                                'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'})

    def test_driver_factory_supports_old_and_current_service_signatures(self):
        class NewService:
            def __init__(self, executable_path=None, port=0, service_args=None, log_output=None, env=None, **kwargs):
                self.path, self.service_args = executable_path, service_args
        with tempfile.TemporaryDirectory() as tmp:
            for index, factory in enumerate((OldService, NewService)):
                path = Path(tmp) / str(index)
                with mock.patch.dict(sys.modules, selenium_modules(factory)), mock.patch.object(B, 'executable', return_value='/driver'):
                    service = B.chrome_service(path)
                self.assertEqual(service.service_args, ['--log-path=' + str(path)])
                self.assertTrue(path.is_file())

    def test_driver_factory_refuses_existing_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'driver.log'; path.write_text('keep')
            with mock.patch.dict(sys.modules, selenium_modules()), mock.patch.object(B, 'executable', return_value='/driver'):
                with self.assertRaises(FileExistsError): B.chrome_service(path)
            self.assertEqual(path.read_text(), 'keep')

    def test_options_keep_sandbox_and_fresh_profile(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, selenium_modules()), \
                mock.patch.object(B, 'executable', return_value='/chrome'):
            profile = Path(tmp) / 'profile'
            options = B.chrome_options(profile)
            self.assertEqual(options.binary_location, '/chrome')
            B.checked_arguments(['/chrome', *options.arguments])
            self.assertIn('--user-data-dir=' + str(profile), options.arguments)
            profile.mkdir()
            with self.assertRaises(B.BrowserPrerequisiteError): B.chrome_options(profile)

    def test_discovery_does_not_download_when_executable_absent(self):
        with mock.patch.object(B.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(B.BrowserPrerequisiteError, 'Missing installed'):
                B.executable(('google-chrome', 'chromium'))

    def test_version_mismatch_fails_before_rendering(self):
        self.assertEqual(B.versions(Browser.capabilities)['browser'], '154.0.1.2')
        value = copy.deepcopy(Browser.capabilities)
        value['chrome']['chromedriverVersion'] = '153.0.0.0'
        with self.assertRaises(B.BrowserPrerequisiteError): B.versions(value)

    def test_sandbox_reads_actual_page_and_rejects_redirect(self):
        browser = Browser()
        self.assertEqual(B.sandbox_status(browser)['first_layer'], 'namespace')
        with mock.patch.object(browser, 'get', side_effect=lambda _: setattr(browser, 'current_url', 'https://example.invalid')):
            with self.assertRaisesRegex(B.BrowserPrerequisiteError, 'own sandbox'): B.sandbox_status(browser)

    def test_blank_or_wrong_render_fails(self):
        browser = Browser()
        with tempfile.TemporaryDirectory() as tmp:
            browser.execute_async_script = lambda _: {'size': [0, 0]}
            with self.assertRaises(B.BrowserPrerequisiteError): B.render_probe(browser, Path(tmp))
            self.assertFalse((Path(tmp) / 'render.png').exists())

    def test_success_receipt_follows_browser_and_service_cleanup(self):
        browser, service = Browser(), OldService('/driver')
        modules = selenium_modules(); modules['selenium'].webdriver.Chrome = mock.Mock(return_value=browser)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, modules), \
                mock.patch.object(B.sys, 'platform', 'linux'), mock.patch.object(B.os, 'geteuid', return_value=1000, create=True), \
                mock.patch.object(B, 'chrome_options', return_value=types.SimpleNamespace(binary_location='/chrome')), \
                mock.patch.object(B, 'chrome_service', return_value=service):
            result = B._probe(Path(tmp))
            self.assertTrue(browser.closed and service.stopped)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(json.loads((Path(tmp) / 'preflight.json').read_text()), result)

    def test_failed_sandbox_keeps_evidence_and_closes_browser(self):
        browser, service = Browser(), OldService('/driver')
        browser.state['rows'][3][1] = 'No'
        modules = selenium_modules(); modules['selenium'].webdriver.Chrome = mock.Mock(return_value=browser)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, modules), \
                mock.patch.object(B.sys, 'platform', 'linux'), mock.patch.object(B.os, 'geteuid', return_value=1000, create=True), \
                mock.patch.object(B, 'chrome_options', return_value=types.SimpleNamespace(binary_location='/chrome')), \
                mock.patch.object(B, 'chrome_service', return_value=service):
            with self.assertRaises(B.BrowserPrerequisiteError): B._probe(Path(tmp))
            self.assertTrue(browser.closed and service.stopped)
            result = json.loads((Path(tmp) / 'preflight.json').read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertIn('No', result['details'])

    def test_service_cleanup_failure_cannot_leave_passed_receipt(self):
        browser, service = Browser(), OldService('/driver')
        service.stop = mock.Mock(side_effect=RuntimeError('service cleanup failed'))
        modules = selenium_modules(); modules['selenium'].webdriver.Chrome = mock.Mock(return_value=browser)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, modules), \
                mock.patch.object(B.sys, 'platform', 'linux'), mock.patch.object(B.os, 'geteuid', return_value=1000, create=True), \
                mock.patch.object(B, 'chrome_options', return_value=types.SimpleNamespace(binary_location='/chrome')), \
                mock.patch.object(B, 'chrome_service', return_value=service):
            with self.assertRaisesRegex(RuntimeError, 'cleanup'): B._probe(Path(tmp))
            self.assertEqual(json.loads((Path(tmp) / 'preflight.json').read_text())['status'], 'failed')

    def test_root_account_is_a_failed_prerequisite(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(B.sys, 'platform', 'linux'), \
                mock.patch.object(B.os, 'geteuid', return_value=0, create=True):
            with self.assertRaisesRegex(B.BrowserPrerequisiteError, 'unprivileged'): B._probe(Path(tmp))
            self.assertEqual(json.loads((Path(tmp) / 'preflight.json').read_text())['status'], 'failed')

    def test_public_preflight_uses_bounded_process_owner_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'probe'
            def run(argv, cwd, log, **kwargs):
                self.assertEqual(kwargs['timeout'], 90)
                self.assertEqual(kwargs['max_bytes'], 2 * 1024 * 1024)
                self.assertEqual(kwargs['environment'], B.browser_environment())
                self.assertNotIn('GH_TOKEN', kwargs['environment'])
                self.assertEqual(argv[-1], str(output))
                (cwd / 'preflight.json').write_text(json.dumps({'schema_version': 1, 'status': 'passed'}))
            with mock.patch.object(windows_graphics, 'run_owned', side_effect=run):
                self.assertEqual(B.preflight(output)['status'], 'passed')
                with self.assertRaisesRegex(ValueError, 'new owned'): B.preflight(output)
            failure = Path(tmp) / 'failed'
            with mock.patch.object(windows_graphics, 'run_owned', side_effect=RuntimeError('bounded child failure')):
                with self.assertRaisesRegex(RuntimeError, 'bounded child'): B.preflight(failure)
            self.assertTrue(failure.is_dir())


if __name__ == '__main__':
    unittest.main()
