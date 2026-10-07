"""Initial-view and immutable gallery failure checks without a graphical service."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import screenshots as S
from test_github_release import FakeGitHub


def png(width, height):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    pixels = b''.join(b'\0' + bytes([row % 256, 50, 100]) * width for row in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def gallery(path):
    path.mkdir()
    value = {'schema_version': 1, 'kind': 'initial-view-gallery', 'source_commit': 'a' * 40,
             'state': 'fresh initial application', 'logical_viewport': [640, 480],
             'display_dpi': 96, 'display_scale': 1, 'images': {}, 'source_sha256': 'a' * 64,
             'run_id': '123', 'attempt': 1, 'terminal': 'fixture cells', 'host': {'target': 'linux-x86_64'},
             'distribution': {'ID': 'fixture'}, 'recipes': {'native': 'b' * 64, 'wasm': 'c' * 64},
             'origins': {name: {'origin': 'local', 'recipe': recipe} for name, recipe in
                         [('native', 'b' * 64), ('wasm', 'c' * 64)]},
             'dependencies': {name: {p: 'a' * 64 for p in S.delivery.store.names(recipe)}
                              for name, recipe in [('native', 'b' * 64), ('wasm', 'c' * 64)]},
             'gui_group': {'revision': 'a' * 40, 'source_tree': 'b' * 40, 'upstream': 'fixture',
                           'license': 'fixture', 'redistributable': False, 'archive_sha256': 'a' * 64,
                           'manifest_sha256': 'b' * 64},
             'binaries': {name: 'd' * 64 for name in {*(f'native/gui/foundation-gui-{n}' for n in S.TARGETS),
                          'wasm/gui/gui_web_wasm.js', 'wasm/gui/gui_web_wasm.wasm'}},
             'captures': {'browser': {'browserName': 'fixture', 'browserVersion': '1'}},
             'tools': {name: 'fixture version 1' for name in ('cmake', 'browser', 'chromedriver', 'xterm')}}
    value['captures']['browser']['sandbox'] = S.gallery_browser.parse_sandbox({
        'rows': [['Layer 1 Sandbox', 'Namespace'], ['PID namespaces', 'Yes'],
                 ['Network namespaces', 'Yes'], ['Seccomp-BPF sandbox', 'Yes']],
        'evaluation': 'You are adequately sandboxed.'})
    for name in S.BACKENDS:
        dimensions = [644, 500] if name == 'terminal' else [640, 480]
        p = path / (name + '.png'); p.write_bytes(png(*dimensions))
        value['images'][p.name] = {'sha256': S.archive.digest(p), 'size': p.stat().st_size, 'dimensions': dimensions}
        value['captures'][name] = {'width': dimensions[0], 'height': dimensions[1], 'colors': 20,
            'surface': 'browser-viewport' if name in ('hosted-web', 'wasm') else
                       'application-framebuffer' if name == 'framebuffer' else 'native-window'}
    for name, mode in [('hosted-web', 'hosted'), ('wasm', 'wasm')]:
        value['captures'][name].update(mode=mode, geometry=[{'key': 'generic', 'box': [0, 0, 20, 20]}])
    (path / 'screenshots.json').write_bytes(S.archive.encoded(value))
    (path / 'BUILD.txt').write_text('Fixture provenance\n', encoding='utf-8')
    seal(path)
    return value


def seal(path):
    (path / 'SHA256SUMS').write_text(''.join(S.archive.digest(path / name) + '  ' + name + '\n'
        for name in sorted(S.PUBLIC - {'SHA256SUMS'})), encoding='ascii')


class Clock:
    value = 0
    def monotonic(self): return self.value
    def sleep(self, amount): self.value += amount


@contextmanager
def running(*args, **kwargs):
    child = mock.Mock(); child.poll.return_value = None
    yield child


class ScreenshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.directory = self.root / 'gallery'

    def test_all_seven_distinct_inventory_entries_and_source_are_required(self):
        expected = gallery(self.directory)
        self.assertEqual(S.verify_gallery(self.directory), expected)
        for name in S.BACKENDS:
            file = self.directory / (name + '.png'); data = file.read_bytes(); file.unlink()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'complete exact'):
                S.verify_gallery(self.directory)
            file.write_bytes(data)
        expected['source_commit'] = 'main'
        (self.directory / 'screenshots.json').write_bytes(S.archive.encoded(expected)); seal(self.directory)
        with self.assertRaisesRegex(ValueError, 'complete source commit'):
            S.verify_gallery(self.directory)

    def test_changed_image_and_unexpected_binary_block_publication(self):
        gallery(self.directory)
        (self.directory / 'fltk.png').write_bytes(png(640, 480) + b'changed')
        with self.assertRaisesRegex(ValueError, 'image bytes'):
            S.verify_gallery(self.directory)
        (self.directory / 'application.exe').write_bytes(b'not publishable here')
        with self.assertRaisesRegex(ValueError, 'complete exact'):
            S.verify_gallery(self.directory)

    def test_png_dimensions_and_metadata_reject_resized_viewports(self):
        value = gallery(self.directory)
        p = self.directory / 'sdl.png'; p.write_bytes(png(320, 240))
        value['images'][p.name] = {'sha256': S.archive.digest(p), 'size': p.stat().st_size, 'dimensions': [320, 240]}
        (self.directory / 'screenshots.json').write_bytes(S.archive.encoded(value)); seal(self.directory)
        with self.assertRaisesRegex(ValueError, 'viewport'):
            S.verify_gallery(self.directory)

    def test_missing_actual_capture_and_dependency_provenance_is_rejected(self):
        value = gallery(self.directory)
        for field in ('binaries', 'captures', 'dependencies', 'gui_group'):
            changed = copy.deepcopy(value); changed[field] = {}
            (self.directory / 'screenshots.json').write_bytes(S.archive.encoded(changed)); seal(self.directory)
            with self.subTest(field=field), self.assertRaises(ValueError):
                S.verify_gallery(self.directory)

    def test_capture_crash_is_not_an_image(self):
        child = mock.Mock(); child.poll.return_value = 7
        @contextmanager
        def dead(*args, **kwargs): yield child
        with mock.patch.object(S, 'windows', return_value=set()), mock.patch.object(S, 'process', dead):
            with self.assertRaisesRegex(RuntimeError, 'exited before'):
                S.capture_window(['unused'], 'fltk', self.root)
        self.assertFalse((self.root / 'fltk.png').exists())

    def test_blank_stable_window_does_not_pass(self):
        clock = Clock()
        def capture(*args, **kwargs): (self.root / 'fltk.png').write_bytes(b'blank')
        with mock.patch.object(S, 'windows', side_effect=lambda: {'old', 'new'} if clock.value else {'old'}), \
             mock.patch.object(S, 'process', running), mock.patch.object(S, 'command', side_effect=capture), \
             mock.patch.object(S, 'image_info', return_value=(640, 480, 1)), \
             mock.patch.object(S.time, 'monotonic', clock.monotonic), mock.patch.object(S.time, 'sleep', clock.sleep):
            with self.assertRaisesRegex(RuntimeError, 'stable painted'):
                S.capture_window(['unused'], 'fltk', self.root)
        self.assertGreaterEqual(clock.value, 30)

    def test_discovery_ignores_preexisting_and_ambiguous_windows(self):
        clock = Clock(); sightings = iter(({'old'}, {'old', 'one', 'two'})); commands = []
        def capture(argv, **kwargs):
            commands.append(argv); (self.root / 'sdl.png').write_bytes(b'actual capture')
        with mock.patch.object(S, 'windows', side_effect=lambda: next(sightings, {'old', 'new'})), \
             mock.patch.object(S, 'process', running), mock.patch.object(S, 'command', side_effect=capture), \
             mock.patch.object(S, 'image_info', return_value=(640, 480, 20)), \
             mock.patch.object(S.time, 'monotonic', clock.monotonic), mock.patch.object(S.time, 'sleep', clock.sleep):
            receipt = S.capture_window(['unused'], 'sdl', self.root)
        self.assertEqual(receipt['surface'], 'native-window')
        self.assertTrue(commands)
        self.assertEqual({argv[argv.index('-window') + 1] for argv in commands}, {'new'})

    def test_display_inspection_error_is_not_empty_display(self):
        result = mock.Mock(returncode=2, stdout='', stderr='private diagnostic')
        with mock.patch.object(S.subprocess, 'run', return_value=result), self.assertRaisesRegex(RuntimeError, 'native display'):
            S.windows()

    def test_owned_process_is_stopped_even_when_capture_raises(self):
        child = mock.Mock()
        with mock.patch.object(S.process_tree, 'launch', return_value=child):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                with S.process(['command'], self.root / 'log'):
                    raise RuntimeError('injected')
        child.terminate.assert_called_once(); child.close.assert_called_once()

    def test_plan_is_network_free_and_source_bound(self):
        gallery(self.directory); remote = FakeGitHub()
        result = S.publish('example/project', 'screenshots-1', self.directory, 'a' * 40, transport=remote)
        self.assertFalse(result['execute']); self.assertEqual(remote.calls, [])
        with self.assertRaisesRegex(ValueError, 'source differs'):
            S.publish('example/project', 'screenshots-1', self.directory, 'b' * 40, transport=remote)
        with self.assertRaisesRegex(ValueError, 'separate tag namespace'):
            S.publish('example/project', 'v1', self.directory, 'a' * 40, transport=remote)

    def test_publication_verifies_complete_bytes_and_never_latest(self):
        gallery(self.directory); remote = FakeGitHub()
        result = S.publish('example/project', 'screenshots-1', self.directory, 'a' * 40, execute=True, transport=remote)
        self.assertTrue(result['execute']); self.assertIsNone(remote.latest)
        release = remote.releases[0]
        self.assertFalse(release['draft']); self.assertTrue(release['prerelease'])
        self.assertEqual({x['name'] for x in release['assets']}, S.PUBLIC)
        self.assertEqual(len([x for x in remote.calls if x[0] == 'download']), len(S.PUBLIC))
        before = copy.deepcopy(remote.mutations)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            S.publish('example/project', 'screenshots-1', self.directory, 'a' * 40, execute=True, transport=remote)
        self.assertEqual(remote.mutations, before)

    def test_incomplete_upload_is_uncertain_and_never_finalizes(self):
        gallery(self.directory); remote = FakeGitHub(); remote.fail_upload = 'fltk.png'
        with self.assertRaises(S.delivery.DeliveryError) as caught:
            S.publish('example/project', 'screenshots-1', self.directory, 'a' * 40, execute=True, transport=remote)
        self.assertTrue(caught.exception.uncertain)
        self.assertTrue(remote.releases[0]['draft']); self.assertIsNone(remote.latest)

    def test_same_byte_asset_replacement_during_verification_fails(self):
        gallery(self.directory); remote = FakeGitHub()
        remote.change_download = lambda: remote.replace_asset('fltk.png')
        with self.assertRaises(S.delivery.DeliveryError) as caught:
            S.publish('example/project', 'screenshots-1', self.directory, 'a' * 40, execute=True, transport=remote)
        self.assertTrue(caught.exception.uncertain); self.assertTrue(remote.releases[0]['draft'])

    def test_hosted_capture_uses_unprivileged_host_and_explicit_runtime_only(self):
        with mock.patch.dict(os.environ, {'GH_TOKEN': 'do-not-copy', 'GITHUB_RUN_ID': '4',
                                         'GITHUB_TOKEN': 'private', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'private'}):
            argv = S.hosted_command('a' * 64, 'b' * 64, 2, uid=1001, gid=1001)
            environment = S.capture_environment()
        self.assertEqual(argv[0], sys.executable); self.assertIn('display-collect', argv)
        self.assertNotIn('xvfb-run', argv); self.assertNotIn('docker', argv)
        self.assertNotIn('GH_TOKEN', environment); self.assertNotIn('GITHUB_TOKEN', environment)
        self.assertNotIn('ACTIONS_ID_TOKEN_REQUEST_TOKEN', environment)
        self.assertEqual(environment['GITHUB_RUN_ID'], '4')
        with self.assertRaisesRegex(ValueError, 'non-root'):
            S.hosted_command('a' * 64, 'b' * 64, 2, uid=0, gid=1001)

    def test_hosted_auto_compiles_with_available_capacity_and_keeps_explicit_override(self):
        with mock.patch.object(S, 'compile_jobs', side_effect=lambda value: 16 if value == 'auto' else int(value)), \
             mock.patch.object(S, 'hosted_command', return_value=['capture']) as command, \
             mock.patch.object(S.gallery_browser, 'preflight', side_effect=ValueError('stop before acquisition')):
            for jobs, expected in (('auto', 16), ('3', 3)):
                with self.assertRaisesRegex(ValueError, 'stop before acquisition'):
                    S.main(['hosted', '--repository', 'example/project', '--native-recipe', 'a'*64,
                            '--wasm-recipe', 'b'*64, '--jobs', jobs, '--gui-input',
                            json.dumps({'source': 'base', 'manifest_sha256': 'c'*64})])
                self.assertEqual(command.call_args.args[2], expected)
        argv = S.hosted_command('a'*64, 'b'*64, 16, uid=1001, gid=1001)
        self.assertEqual(argv[argv.index('--jobs') + 1], '16')
        for invalid in (0, -1, True):
            with self.assertRaisesRegex(ValueError, 'positive'):
                S.hosted_command('a'*64, 'b'*64, invalid, uid=1001, gid=1001)

    def test_retained_mode_requires_both_exact_requests_without_base_fallback(self):
        requests = {name: {'schema_version': 2, 'repository': 'example/project', 'target': target,
            'profile': 'all-gui', 'recipe_id': recipe, 'workflow': 'sdk-import.yml', 'run_id': 123,
            'attempt': 1, 'job_id': 456, 'source_commit': 'a' * 40,
            'group': {'manifest_id': 11, 'manifest_sha256': 'b' * 64},
            'proof': {'manifest_id': 12, 'manifest_sha256': 'c' * 64}}
            for name, target, recipe in [('native', 'linux-x86_64', 'b' * 64), ('wasm', 'browser-wasm32', 'c' * 64)]}
        self.assertEqual(S.input_selection('example/project', 'b' * 64, 'c' * 64, 'retained', requests),
                         {'native': 'b' * 64, 'wasm': 'c' * 64})
        for selected in (None, {}, {'native': requests['native']}, {**requests, 'unexpected': {}},
                         {**requests, 'wasm': {**requests['wasm'], 'recipe_id': 'd' * 64}}):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                S.input_selection('example/project', 'b' * 64, 'c' * 64, 'retained', selected)
        with self.assertRaisesRegex(ValueError, 'must not contain'):
            S.input_selection('example/project', 'b' * 64, 'c' * 64, 'base', requests)
        with mock.patch.object(S.ci, 'retained_sdk', side_effect=ValueError('missing retained input')), \
             mock.patch.object(S.delivery, 'fetch_base') as base:
            with self.assertRaisesRegex(ValueError, 'missing retained input'):
                S.prepare_inputs('example/project', 'b' * 64, 'c' * 64, self.root / 'inputs', 'retained', requests,
                                 gui_input={'source': 'base', 'manifest_sha256': 'd'*64}, core_provider='cpp')
        base.assert_not_called()

    def test_hosted_defaults_bind_both_rust_recipes_and_explicit_cpp_omits_them(self):
        argv = S.hosted_command('a'*64, 'b'*64, 2, uid=1001, gid=1001)
        self.assertEqual(argv[argv.index('--core-provider') + 1], 'rust')
        for name, target in [('native', 'linux-x86_64'), ('wasm', 'browser-wasm32')]:
            self.assertEqual(argv[argv.index('--'+name+'-rust-recipe') + 1], S.ci.rust_recipe(target))
            self.assertEqual(argv[argv.index('--'+name+'-rust-group') + 1], 'build/screenshots-inputs/'+name+'-rust')
        cpp = S.hosted_command('a'*64, 'b'*64, 2, uid=1001, gid=1001, core_provider='cpp')
        self.assertEqual(cpp[cpp.index('--core-provider') + 1], 'cpp')
        self.assertNotIn('--native-rust-group', cpp); self.assertNotIn('--rust-origins', cpp)
        with self.assertRaisesRegex(ValueError, 'must omit'):
            S.hosted_command('a'*64, 'b'*64, 2, uid=1001, gid=1001,
                             core_provider='cpp', native_rust_recipe='c'*64)

    def test_default_collection_requires_complete_rust_inputs_before_output_or_build(self):
        import windows_graphics
        with mock.patch.object(S.ci, 'assert_host'), \
             mock.patch.object(S.ci, 'gui_group_module') as gui, \
             mock.patch.object(S.delivery.store, 'verify_group', return_value={}), \
             mock.patch.object(windows_graphics, 'run_owned') as run:
            gui.return_value.verify.return_value = {}
            with self.assertRaisesRegex(ValueError, 'exact retained SDK group'):
                S.collect('native', 'a'*64, 'wasm', 'b'*64, 'gui', self.root/'work', self.root/'output')
        run.assert_not_called(); self.assertFalse((self.root/'work').exists())

    def test_collection_installs_each_rust_target_with_its_matching_cpp_sdk(self):
        import sdk
        import windows_graphics
        work = self.root/'work'; commands = []
        def installed(provider, group, recipe, output, cpp_sdk):
            self.assertEqual(provider, 'rust')
            name = 'native' if group == 'native-rust' else 'wasm'
            self.assertEqual(output, work/(name+'-rust-sdk'))
            self.assertEqual(cpp_sdk, work/(name+'-sdk'))
            return ['--core-provider', 'rust', '--rust-sdk', str(output)], {'core_provider': 'rust'}
        def run(argv, *args, **kwargs):
            commands.append(argv)
            if len(commands) == 3: raise ValueError('stop before surfaces')
        with mock.patch.dict(S.os.environ, {'GITHUB_SHA': 'a'*40}), \
             mock.patch.object(S.ci, 'assert_host'), \
             mock.patch.object(S.ci, 'gui_group_module') as gui, \
             mock.patch.object(S.delivery.store, 'verify_group', return_value={}), \
             mock.patch.object(S.ci, 'rust_selection', return_value={}), \
             mock.patch.object(S.ci, 'install_rust_input', side_effect=installed) as install, \
             mock.patch.object(S, 'text', side_effect=['a'*40, '']), \
             mock.patch.object(S.ci, 'module') as module, \
             mock.patch.object(sdk, 'install', side_effect=[
                 {'target': {'system': 'Linux', 'processor': 'x86_64'},
                  'capabilities': ['terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web']},
                 {'target': {'system': 'Emscripten'}}]), \
             mock.patch.object(windows_graphics, 'run_owned', side_effect=run):
            gui.return_value.verify.return_value = {}; module.return_value.source_tree.return_value = {}
            with self.assertRaisesRegex(ValueError, 'stop before surfaces'):
                S.collect('native', 'a'*64, 'wasm', 'b'*64, 'gui', work, self.root/'output',
                          native_rust_group='native-rust', native_rust_recipe='c'*64,
                          wasm_rust_group='wasm-rust', wasm_rust_recipe='d'*64)
        self.assertEqual(install.call_count, 2)
        for index, name in enumerate(('native', 'wasm')):
            self.assertEqual(commands[index][commands[index].index('--core-provider')+1], 'rust')
            self.assertEqual(commands[index][commands[index].index('--rust-sdk')+1], str(work/(name+'-rust-sdk')))

    def test_rust_gallery_retains_both_compilers_and_historical_cpp_schema(self):
        value = gallery(self.directory)
        self.assertEqual(S.verify_gallery(self.directory), value)
        value.update(schema_version=2, core_provider='rust', rust={})
        for name, recipe, target in [('native', 'd'*64, 'x86_64-unknown-linux-gnu'),
                                     ('wasm', 'e'*64, 'wasm32-unknown-emscripten')]:
            value['rust'][name] = {'core_provider': 'rust', 'rust_sdk_recipe_id': recipe,
                'rust_compiler_version': '1.63.0', 'rust_target': target,
                'rust_sdk_manifest_sha256': 'f'*64, 'rust_compiler_sha256': 'a'*64,
                'group_files': {p: 'b'*64 for p in S.ci.module('rust_sdk').group_names(recipe)},
                'origin': {'origin': 'local', 'recipe': recipe}}
        (self.directory/'screenshots.json').write_bytes(S.archive.encoded(value)); seal(self.directory)
        self.assertEqual(S.verify_gallery(self.directory), value)
        for field, changed in [('rust', {}), ('core_provider', 'cpp')]:
            invalid = copy.deepcopy(value); invalid[field] = changed
            (self.directory/'screenshots.json').write_bytes(S.archive.encoded(invalid)); seal(self.directory)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'selected provider'):
                S.verify_gallery(self.directory)
        for field, changed in [('rust_target', 'x86_64-unknown-linux-gnu'),
                               ('group_files', {}), ('rust_compiler_sha256', 'latest')]:
            invalid = copy.deepcopy(value); invalid['rust']['wasm'][field] = changed
            (self.directory/'screenshots.json').write_bytes(S.archive.encoded(invalid)); seal(self.directory)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'target-matched Rust'):
                S.verify_gallery(self.directory)

    def test_missing_retained_rust_never_selects_base_or_cpp(self):
        requests = {name: {'request': name} for name in ('native', 'wasm')}
        with mock.patch.object(S.ci, 'retained_rust_request') as check, \
             mock.patch.object(S.ci, 'retained_rust_sdk', side_effect=ValueError('missing retained Rust')), \
             mock.patch.object(S.ci, 'fetch_rust_base') as base, \
             mock.patch.object(S.delivery, 'fetch_base'), \
             mock.patch.object(S, 'fetch_gui_input') as gui:
            with self.assertRaisesRegex(ValueError, 'missing retained Rust'):
                S.prepare_inputs('example/project', 'a'*64, 'b'*64, self.root/'inputs',
                    gui_input={'source': 'base', 'manifest_sha256': 'c'*64},
                    native_rust_recipe='d'*64, wasm_rust_recipe='e'*64,
                    rust_source='retained', rust_retained_inputs=requests)
        self.assertEqual(check.call_count, 2); base.assert_not_called(); gui.assert_not_called()

    def test_retained_rust_selection_requires_both_target_bound_requests(self):
        requests = {name: {'schema_version': 1, 'repository': 'example/project', 'target': target,
            'recipe_id': recipe, 'workflow': 'sdk-maintenance.yml', 'run_id': 123,
            'attempt': 1, 'job_id': 456, 'source_commit': 'a'*40,
            'group': {'manifest_id': 11 if name == 'native' else 12, 'manifest_sha256': 'f'*64}}
            for name, target, recipe in [('native', 'linux-x86_64', 'd'*64),
                                         ('wasm', 'browser-wasm32', 'e'*64)]}
        self.assertEqual(S.rust_input_selection('example/project', 'rust', 'd'*64, 'e'*64,
                         'retained', requests), {'native': 'd'*64, 'wasm': 'e'*64})
        for selected in (None, {}, {'native': requests['native']}, {**requests, 'extra': {}},
                         {**requests, 'wasm': requests['native']}):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                S.rust_input_selection('example/project', 'rust', 'd'*64, 'e'*64, 'retained', selected)
        with self.assertRaisesRegex(ValueError, 'must not contain'):
            S.rust_input_selection('example/project', 'rust', 'd'*64, 'e'*64, 'base', requests)
        with self.assertRaisesRegex(ValueError, 'must omit'):
            S.rust_input_selection('example/project', 'cpp', source='retained', retained_inputs=requests)

    def test_host_capture_uses_owned_process_tree_and_sanitized_environment(self):
        import windows_graphics
        with mock.patch.object(windows_graphics, 'run_owned') as run, \
             mock.patch.dict(os.environ, {'GH_TOKEN': 'private'}):
            S.run_hosted(['xvfb-run', 'collector'])
        args, kwargs = run.call_args
        self.assertEqual(args[0], ['xvfb-run', 'collector'])
        self.assertEqual(args[2], S.ROOT / 'build/screenshot-hosted.log')
        self.assertNotIn('GH_TOKEN', kwargs['environment']); self.assertEqual(kwargs['timeout'], 5400)

    def test_browser_preflight_failure_prevents_input_acquisition_and_build(self):
        with mock.patch.object(S, 'hosted_command', return_value=['capture']), \
             mock.patch.object(S.gallery_browser, 'preflight', side_effect=ValueError('sandbox unavailable')), \
             mock.patch.object(S, 'prepare_inputs') as inputs, mock.patch.object(S, 'run_hosted') as build:
            with self.assertRaisesRegex(ValueError, 'sandbox unavailable'):
                S.main(['hosted', '--repository', 'example/project', '--native-recipe', 'a'*64,
                        '--wasm-recipe', 'b'*64, '--gui-input',
                        json.dumps({'source': 'base', 'manifest_sha256': 'c'*64})])
        inputs.assert_not_called(); build.assert_not_called()


    def gui_selector(self):
        return {'source': 'retained', 'manifest_sha256': 'd'*64,
            'pointer': {'schema_version': 1, 'repository': 'example/project', 'run_id': 123, 'attempt': 2,
                'source_commit': 'a'*40, 'workflow': 'gui-inputs.yml', 'name': 'gui-inputs-2',
                'job_id': 456, 'release_id': 789, 'tag': 'ci-123-attempt-2',
                'manifest': {'id': 9, 'name': 'bundle-gui-inputs-2.json', 'size': 500, 'sha256': 'b'*64}}}

    def test_gui_selector_requires_every_exact_binding_before_preflight(self):
        good = self.gui_selector()
        self.assertEqual(S.gui_input_selection('example/project', good), good)
        bad = [None, {}, {**good, 'extra': 1}, {**good, 'manifest_sha256': 'main'},
               {'source': 'base', 'manifest_sha256': 'd'*64, 'pointer': good['pointer']}]
        for field, value in [('schema_version', True), ('repository', 'other/project'),
                             ('workflow', 'sdk-maintenance.yml'), ('source_commit', 'main'),
                             ('run_id', True), ('attempt', 0), ('release_id', -1), ('job_id', '456'),
                             ('tag', 'latest'), ('name', 'gui-inputs-1')]:
            item = copy.deepcopy(good); item['pointer'][field] = value; bad.append(item)
        for field, value in [('id', True), ('size', 0), ('sha256', 'main'), ('name', 'other.json')]:
            item = copy.deepcopy(good); item['pointer']['manifest'][field] = value; bad.append(item)
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError):
                S.gui_input_selection('example/project', item)
        with mock.patch.object(S.gallery_browser, 'preflight') as probe, \
             mock.patch.object(S, 'prepare_inputs') as acquire:
            with self.assertRaises(ValueError):
                S.main(['hosted', '--repository', 'example/project', '--native-recipe', 'a'*64,
                        '--wasm-recipe', 'b'*64, '--gui-input', '{}'])
        probe.assert_not_called(); acquire.assert_not_called()

    def retained_gui_fixture(self, mutate=None):
        selector = self.gui_selector()
        manifest_bytes = b'{"fixture":true}\n'
        selector['manifest_sha256'] = S.hashlib.sha256(manifest_bytes).hexdigest()
        verifier = mock.Mock(); verifier.verify.return_value = {'redistributable': False}
        def fetch(repository, run, attempt, commit, workflow, name, output, **kwargs):
            self.assertEqual((repository, run, attempt, commit, workflow, name),
                ('example/project', 123, 2, 'a'*40, 'gui-inputs.yml', 'gui-inputs-2'))
            self.assertEqual(kwargs, {'job_id': 456, 'manifest_id': 9, 'manifest_sha256': 'b'*64})
            output.mkdir(); group = output/'gui-group'; group.mkdir()
            (group/'manifest.json').write_bytes(manifest_bytes)
            (group/'gui-inputs.tar.gz').write_bytes(b'fixture archive')
            (group/'SHA256SUMS').write_bytes(b'fixture checksums')
            files = {remote: S.archive.digest(group/local) for local, remote in
                     S.ci.gui_group_names(selector['manifest_sha256']).items()}
            plan = S.delivery.plan('publish-gui-inputs', repository, source_commit=commit,
                group_sha256=selector['manifest_sha256'], files=files, redistributable=False)
            S.delivery.coverage.write_new(output/'gui-publication-plan.json', plan)
            receipt = {'pointer': copy.deepcopy(selector['pointer'])}
            if mutate: mutate(output, receipt)
            return receipt
        return selector, verifier, fetch

    def test_retained_gui_fetch_verifies_full_pointer_plan_and_current_group(self):
        selector, verifier, fetch = self.retained_gui_fixture()
        transport = S.ci.module('ci_transport')
        with mock.patch.object(S.ci, 'module', return_value=transport), \
             mock.patch.object(transport, 'fetch_bundle', side_effect=fetch), \
             mock.patch.object(S.ci, 'gui_group_module', return_value=verifier), \
             mock.patch.object(S, 'command') as commands, mock.patch.object(S.ci, 'fetch_gui_group') as base:
            value = S.fetch_gui_input('example/project', selector, self.root/'input')
        self.assertFalse(value['publication_approved']); self.assertEqual(value['selector'], selector)
        self.assertEqual({p.name for p in (self.root/'input').iterdir()},
                         {'manifest.json', 'gui-inputs.tar.gz', 'SHA256SUMS'})
        verifier.verify.assert_called_once(); commands.assert_not_called(); base.assert_not_called()

    def test_retained_gui_mismatch_never_installs_or_falls_back(self):
        def change_plan(path, key, value):
            file = path/'gui-publication-plan.json'; plan = json.loads(file.read_text()); plan[key] = value
            plan['plan_sha256'] = S.delivery.coverage.digest({k:v for k,v in plan.items() if k != 'plan_sha256'})
            file.write_bytes(S.archive.encoded(plan))
        changes = [lambda p,r: r['pointer'].update(release_id=999),
            lambda p,r: r['pointer']['manifest'].update(size=501),
            lambda p,r: (p/'unexpected').write_bytes(b'x'),
            lambda p,r: (p/'gui-group/manifest.json').write_bytes(b'changed'),
            lambda p,r: change_plan(p, 'source_commit', 'f'*40),
            lambda p,r: change_plan(p, 'group_sha256', 'f'*64),
            lambda p,r: change_plan(p, 'files', {}),
            lambda p,r: change_plan(p, 'redistributable', True),
            lambda p,r: change_plan(p, 'execute', True)]
        transport = S.ci.module('ci_transport')
        for index, mutation in enumerate(changes):
            selector, verifier, fetch = self.retained_gui_fixture(mutation)
            destination = self.root/str(index)
            with self.subTest(index=index), mock.patch.object(S.ci, 'module', return_value=transport), \
                 mock.patch.object(transport, 'fetch_bundle', side_effect=fetch), \
                 mock.patch.object(S.ci, 'gui_group_module', return_value=verifier), \
                 mock.patch.object(S.ci, 'fetch_gui_group') as base:
                with self.assertRaises(ValueError): S.fetch_gui_input('example/project', selector, destination)
                self.assertFalse(destination.exists()); base.assert_not_called()

    def test_failed_gui_producer_or_current_patch_mismatch_has_no_fallback(self):
        transport = S.ci.module('ci_transport')
        for failure in ('producer', 'current-patches'):
            selector, verifier, fetch = self.retained_gui_fixture()
            if failure == 'current-patches': verifier.verify.side_effect = ValueError('current integration differs')
            else: fetch = mock.Mock(side_effect=ValueError('producer did not succeed'))
            with self.subTest(failure=failure), mock.patch.object(S.ci, 'module', return_value=transport), \
                 mock.patch.object(transport, 'fetch_bundle', side_effect=fetch), \
                 mock.patch.object(S.ci, 'gui_group_module', return_value=verifier), \
                 mock.patch.object(S.ci, 'fetch_gui_group') as base:
                with self.assertRaises(ValueError): S.fetch_gui_input('example/project', selector, self.root/failure)
                self.assertFalse((self.root/failure).exists()); base.assert_not_called()

    def test_base_gui_requires_selected_manifest_and_verifies_current_group(self):
        content = b'fixture'; identity = S.hashlib.sha256(content).hexdigest()
        selector = {'source': 'base', 'manifest_sha256': identity}
        def base(repository, selected, output):
            self.assertEqual((repository, selected), ('example/project', identity))
            output.mkdir(); (output/'manifest.json').write_bytes(content)
            return {'fetched': True}
        verifier = mock.Mock(); verifier.verify.return_value = {'redistributable': False}
        with mock.patch.object(S.ci, 'fetch_gui_group', side_effect=base), \
             mock.patch.object(S.ci, 'gui_group_module', return_value=verifier), \
             mock.patch.object(S, 'command') as upstream:
            S.fetch_gui_input('example/project', selector, self.root/'base')
        verifier.verify.assert_called_once(); upstream.assert_not_called()

    @contextmanager
    def display_fixture(self, *, ready=b'77\n', wait_error=None):
        child = mock.Mock(pid=1234); child.poll.return_value = None
        events = []
        def wait(**kwargs):
            events.append('wait')
            if wait_error: raise wait_error
            child.poll.return_value = 0
            return 0
        child.wait.side_effect = wait
        child.terminate.side_effect = lambda: events.append('terminate')
        child.kill.side_effect = lambda: events.append('kill')
        def start(argv, **kwargs):
            self.assertIn('-auth', argv); self.assertIn('-nolisten', argv)
            self.assertNotIn('-ac', argv); self.assertNotIn('GH_TOKEN', kwargs['env'])
            self.assertEqual(kwargs['pass_fds'], (int(argv[argv.index('-displayfd')+1]),))
            if ready is not None: os.write(kwargs['pass_fds'][0], ready)
            events.append('start')
            return child
        def command(argv, **kwargs):
            if argv[0] == 'xdpyinfo':
                self.assertEqual(kwargs['env']['DISPLAY'], ':77')
                self.assertTrue(Path(kwargs['env']['XAUTHORITY']).is_file())
                return mock.Mock(stdout='dimensions: 1280x900 pixels\nresolution: 96x96 dots per inch')
            self.assertEqual(argv[0], 'xauth'); events.append('authorize')
        with mock.patch.object(S.shutil, 'which', side_effect=lambda x:'/usr/bin/'+x), \
             mock.patch.object(S.subprocess, 'Popen', side_effect=start), \
             mock.patch.object(S, 'command', side_effect=command), \
             mock.patch.object(S.select, 'select', side_effect=lambda reads,*args: (reads,[],[])), \
             mock.patch.dict(os.environ, {'GH_TOKEN':'private'}):
            yield child, events

    def test_private_display_is_authenticated_ready_and_joined_before_return(self):
        output = self.root/'display'
        with self.display_fixture() as (child, events):
            with S.private_display(output) as environment:
                self.assertEqual(environment['DISPLAY'], ':77')
                self.assertEqual(environment['SDL_VIDEODRIVER'], 'x11')
                self.assertNotIn('GH_TOKEN', environment); events.append('capture')
        self.assertEqual(events, ['authorize','start','authorize','capture','terminate','wait'])
        self.assertEqual(json.loads((output/'display.json').read_text())['cleanup'], 'joined')
        self.assertEqual(json.loads((output/'display.json').read_text())['status'], 'passed')
        self.assertFalse((output/'Xauthority').exists()); child.kill.assert_not_called()

    def test_collector_failure_is_preserved_and_display_is_joined(self):
        output = self.root/'display'
        with self.display_fixture() as (child, events):
            with self.assertRaisesRegex(ValueError, 'collector failure'):
                with S.private_display(output): raise ValueError('collector failure')
        receipt = json.loads((output/'display.json').read_text())
        self.assertEqual(receipt['status'], 'failed'); self.assertEqual(receipt['cleanup'], 'joined')
        self.assertEqual(events[-2:], ['terminate','wait']); child.wait.assert_called_once()

    def test_display_eof_and_malformed_readiness_prevent_collection(self):
        for index, data in enumerate((None, b'not-a-display\n', b'1\n2\n', b'65536\n')):
            with self.subTest(data=data), self.display_fixture(ready=data) as (child, events):
                with self.assertRaisesRegex(RuntimeError, 'readiness'):
                    with S.private_display(self.root/str(index)): self.fail('collector must not run')
                child.wait.assert_called_once()

    def test_display_readiness_timeout_is_bounded(self):
        clock = Clock(); child = mock.Mock(); child.poll.return_value = None
        def never(*args): clock.sleep(.1); return [],[],[]
        with mock.patch.object(S.time, 'monotonic', clock.monotonic), \
             mock.patch.object(S.select, 'select', side_effect=never):
            with self.assertRaisesRegex(RuntimeError, 'timed out'): S.display_number(123, child, .3)
        self.assertLess(clock.value, .5)

    def test_unexpected_display_exit_fails_even_after_successful_capture(self):
        with self.display_fixture() as (child, events):
            with self.assertRaisesRegex(RuntimeError, 'during capture'):
                with S.private_display(self.root/'display'): child.poll.return_value = 2
        receipt = json.loads((self.root/'display/display.json').read_text())
        self.assertEqual(receipt['status'], 'failed'); child.wait.assert_called_once()

    def test_display_timeout_kills_and_joins_exact_child(self):
        child = mock.Mock(); child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('Xvfb',10),0]
        self.assertEqual(S.join_display(child), 'killed-and-joined')
        child.terminate.assert_called_once(); child.kill.assert_called_once()
        self.assertEqual(child.wait.call_args_list, [mock.call(timeout=10),mock.call(timeout=5)])

    def test_collector_error_survives_uncertain_display_cleanup(self):
        with self.display_fixture(wait_error=RuntimeError('join failed')):
            with self.assertRaisesRegex(ValueError, 'collector failure') as caught:
                with S.private_display(self.root/'display'): raise ValueError('collector failure')
        self.assertEqual(caught.exception.display_cleanup_error, 'join failed')
        receipt = json.loads((self.root/'display/display.json').read_text())
        self.assertEqual(receipt['cleanup'], 'uncertain'); self.assertEqual(receipt['status'], 'failed')
        self.assertTrue((self.root/'display/Xauthority').exists())

    def test_process_close_runs_even_when_terminate_fails(self):
        child = mock.Mock(); child.terminate.side_effect = RuntimeError('stop failed')
        with mock.patch.object(S.process_tree, 'launch', return_value=child), self.assertRaisesRegex(RuntimeError, 'stop failed'):
            with S.process(['command'], self.root/'log'): pass
        child.close.assert_called_once()

    def test_server_file_size_limit_is_applied_before_exec(self):
        resource = mock.Mock(RLIMIT_FSIZE=1); events = []
        resource.setrlimit.side_effect = lambda *args: events.append(('limit',args))
        with mock.patch.dict(sys.modules, {'resource':resource}), \
             mock.patch.object(S.os, 'execvp', side_effect=lambda *args: events.append(('exec',args))):
            S.display_server(['-displayfd','7'])
        self.assertEqual(events, [('limit',(1,(S.MAX_DISPLAY_LOG,S.MAX_DISPLAY_LOG))),
                                  ('exec',('Xvfb',['Xvfb','-displayfd','7']))])

    def test_display_log_limit_fails_after_join_without_unbounded_diagnostics(self):
        with self.display_fixture(), mock.patch.object(S, 'MAX_DISPLAY_LOG', 8):
            with self.assertRaisesRegex(RuntimeError, 'byte limit'):
                with S.private_display(self.root/'display'):
                    (self.root/'display/xvfb.log').write_bytes(b'12345678')
        receipt = json.loads((self.root/'display/display.json').read_text())
        self.assertEqual(receipt['status'], 'failed'); self.assertEqual(receipt['cleanup'], 'joined')
        self.assertFalse((self.root/'display/Xauthority').exists())

    def test_display_collector_retains_nested_process_supervision(self):
        import windows_graphics
        @contextmanager
        def display(path): yield {'DISPLAY': ':77', 'XAUTHORITY': 'private'}
        with mock.patch.object(S, 'private_display', display), mock.patch.object(windows_graphics, 'run_owned') as run:
            S.display_collect(['collector'], self.root)
        args, kwargs = run.call_args
        self.assertEqual(args, (['collector'], S.ROOT, self.root/'collector.log'))
        self.assertEqual(kwargs['environment'], {'DISPLAY': ':77', 'XAUTHORITY': 'private'})
        self.assertEqual(kwargs['timeout'], 5300)


if __name__ == '__main__': unittest.main()
