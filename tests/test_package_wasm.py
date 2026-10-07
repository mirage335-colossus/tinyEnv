import importlib.util
import base64
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('package_wasm', ROOT / 'tools/package_wasm.py')
package_wasm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_wasm)
sys.path.insert(0, str(ROOT / 'tests'))
from test_browser_bundle import fixture_blobs


class PackageWasmTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        for name in package_wasm.ASSETS:
            (self.assets / name).write_text('// local fixture\n')
        (self.assets / 'gui_web_wasm.wasm').write_bytes(b'\0asm\x01\0\0\0')
        (self.assets / 'wasm_worker.mjs').write_bytes((ROOT / 'gui/host/wasm_worker.mjs').read_bytes())
        for name, data in fixture_blobs().items():
            (self.assets / name).write_bytes(data)
        for name, dependencies in package_wasm.IMPORTS.items():
            if name not in package_wasm.browser_bundle.CHILD_MODULES:
                (self.assets / name).write_text(''.join("import './" + dependency + "';" for dependency in dependencies))
        package_wasm.browser_bundle.generate(self.assets, self.assets / package_wasm.browser_bundle.BUNDLE_NAME)
        (self.assets / 'index.html').write_text('<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/style.css"><div id="status"></div><script type="module" src="/boot.mjs"></script>')
        self.notice = self.root / 'LICENSE'
        self.notice.write_text('Example notice <safe> </script>')
        self.output = self.root / 'output'

    def make(self):
        return package_wasm.package(self.assets, self.output, [self.notice])

    def make_legacy(self, schema=1, source_root=None):
        blobs = {name: (self.assets / name).read_bytes() for name in package_wasm.LEGACY_ASSETS}
        blobs['boot.mjs'] = b"import './renderer.mjs';import './browser_lifecycle.mjs';import './browser_presenter.mjs';import './wasm_transport.mjs';"
        blobs['renderer.mjs'] = b"import './file_services.mjs';"
        notices = {'LICENSE': self.notice.read_bytes()}
        html = package_wasm.make_legacy_html(blobs, notices)
        manifest = dict(schema=schema, runtime='dedicated-worker', transport='ordered-local-messages',
                        network='disabled-by-csp', csp=package_wasm.LEGACY_CSP,
                        inputs={name: package_wasm.digest(data) for name, data in blobs.items()},
                        notices={name: package_wasm.digest(data) for name, data in notices.items()},
                        html_sha256=package_wasm.digest(html))
        if source_root is not None:
            from source_identity import source_tree
            manifest['source_tree_sha256'] = source_tree(source_root)['tree_sha256']
        self.output.mkdir(exist_ok=True)
        (self.output / package_wasm.HTML_NAME).write_bytes(html)
        (self.output / 'web-manifest.json').write_bytes((json.dumps(manifest) + '\n').encode())
        self.rewrite_checksums()
        return manifest

    def rewrite_checksums(self):
        (self.output / 'manifest.sha256').write_bytes(''.join(package_wasm.digest((self.output / name).read_bytes()) + '  ' + name + '\n'
                    for name in sorted((package_wasm.HTML_NAME, 'web-manifest.json'))).encode())

    def test_offline_inventory_notice_and_deterministic_output(self):
        expected = self.make()
        self.assertEqual(expected['schema'], 3)
        self.assertEqual(expected['renderer_modes'], ['standalone', 'isolated'])
        self.assertEqual(expected['child']['sandbox'], 'allow-scripts')
        self.assertNotIn('allow-same-origin', expected['child']['sandbox'])
        self.assertNotIn("'sha256-", expected['csp'])
        self.assertIn("'sha256-", expected['child']['csp'])
        html = (self.output / package_wasm.HTML_NAME).read_text()
        self.assertIn("connect-src &#x27;none&#x27;", html)
        self.assertNotIn('src="/boot.mjs"', html)
        self.assertIn('Example notice &lt;safe&gt; &lt;/script&gt;', html)
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        self.assertEqual(self.make(), expected)
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, before)
        self.assertEqual(package_wasm.verify(self.output), expected)

    def test_canonical_metadata_survives_windows_text_translation(self):
        # Exercise Windows text-mode translation on every test host. Binary
        # package output must still verify and remain byte-identical.
        write_text = Path.write_text
        def windows_text(path, data, *args, **kwargs):
            if kwargs.get('newline') is None:
                data = data.replace('\n', '\r\n')
            return write_text(path, data, *args, **kwargs)
        expected = self.make()
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        with patch.object(Path, 'write_text', windows_text):
            self.assertEqual(self.make(), expected)
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, before)
        for name in ('web-manifest.json', 'manifest.sha256'):
            self.assertNotIn(b'\r', before[name])
        self.assertEqual(package_wasm.verify(self.output), expected)

    def test_tampering_and_extra_files_fail(self):
        self.make()
        html = self.output / package_wasm.HTML_NAME
        html.write_bytes(html.read_bytes() + b'bad')
        with self.assertRaisesRegex(ValueError, 'manifest mismatch'):
            package_wasm.verify(self.output)
        self.make()
        (self.output / 'external.js').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            package_wasm.verify(self.output)
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.make()

    def test_missing_notice_or_asset_rejected(self):
        with self.assertRaisesRegex(ValueError, 'notice'):
            package_wasm.package(self.assets, self.output, [])
        (self.assets / 'wasm_worker.mjs').unlink()
        with self.assertRaisesRegex(ValueError, 'ordinary asset'):
            self.make()

    def test_module_and_html_contract_drift_rejected(self):
        (self.assets / 'boot.mjs').write_text("import './other.mjs'")
        with self.assertRaisesRegex(ValueError, 'dependency changed'):
            self.make()

    def test_nested_renderer_dependency_is_required_and_embedded(self):
        self.make()
        html = (self.output / package_wasm.HTML_NAME).read_text()
        self.assertIn('"renderer.mjs":["renderer_dom.mjs","browser_client.mjs","browser_services.mjs"]', html)
        self.assertIn('JSON.stringify(moduleURL(dependency))', html)
        self.assertIn("await import(moduleURL('boot.mjs'))", html)
        (self.assets / 'renderer.mjs').write_text('// missing dependency')
        with self.assertRaisesRegex(ValueError, 'renderer.mjs'):
            self.make()

    def test_legacy_schemas_preserve_original_inventory_and_policy(self):
        for schema in (1, 2):
            with self.subTest(schema=schema):
                source = self.root / 'legacy-source'
                source.mkdir(exist_ok=True)
                (source / 'main.cpp').write_text('int main(){}')
                manifest = self.make_legacy(schema, source if schema == 2 else None)
                self.assertEqual(package_wasm.verify(self.output), manifest)
                self.assertEqual(set(manifest['inputs']), set(package_wasm.LEGACY_ASSETS))
                self.assertNotIn('child', manifest)
                changed = dict(manifest, csp=package_wasm.CSP)
                (self.output / 'web-manifest.json').write_text(json.dumps(changed))
                self.rewrite_checksums()
                with self.assertRaisesRegex(ValueError, 'manifest mismatch'):
                    package_wasm.verify(self.output)

    def test_schema3_child_policy_and_canonical_document_bound(self):
        self.make()
        manifest_path = self.output / 'web-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        for field in ('protocol', 'sandbox', 'csp', 'script_sha256', 'script_csp_sha256', 'inputs'):
            with self.subTest(field=field):
                original = json.loads(json.dumps(manifest))
                original['child'][field] = {} if field == 'inputs' else 'changed'
                manifest_path.write_text(json.dumps(original))
                self.rewrite_checksums()
                with self.assertRaisesRegex(ValueError, 'child isolation'):
                    package_wasm.verify(self.output)
        self.make()
        html_path = self.output / package_wasm.HTML_NAME
        html_path.write_bytes(html_path.read_bytes().replace(b"await import(moduleURL('boot.mjs'))", b"globalThis.unreviewed=true;await import(moduleURL('boot.mjs'))"))
        manifest = json.loads(manifest_path.read_text())
        manifest['html_sha256'] = package_wasm.digest(html_path.read_bytes())
        manifest_path.write_text(json.dumps(manifest))
        self.rewrite_checksums()
        with self.assertRaisesRegex(ValueError, 'canonical'):
            package_wasm.verify(self.output)

    def test_generated_child_data_matches_exact_inputs(self):
        (self.assets / 'renderer_dom.mjs').write_bytes((self.assets / 'renderer_dom.mjs').read_bytes() + b'\n// changed supplier input\n')
        with self.assertRaisesRegex(ValueError, 'child bundle differs'):
            self.make()
        package_wasm.browser_bundle.generate(self.assets, self.assets / package_wasm.browser_bundle.BUNDLE_NAME)
        self.make()
        (self.assets / package_wasm.browser_bundle.BUNDLE_NAME).write_text('export const CHILD_SCRIPT="unreviewed";')
        with self.assertRaisesRegex(ValueError, 'child bundle differs'):
            self.make()

    def test_classic_offline_worker_keeps_original_input_and_unchanged_policy(self):
        original = (self.assets / 'wasm_worker.mjs').read_bytes()
        converted = package_wasm.classic_worker_source(original)
        self.assertNotIn('export function installWasmWorker', converted)
        self.assertIn('function installWasmWorker(scope,loadModule=url=>import(url))', converted)
        self.assertIn('installWasmWorker(globalThis)', converted)
        self.assertEqual(converted.encode(), b'"use strict";\n' + original.replace(b'export function installWasmWorker', b'function installWasmWorker', 1))
        manifest = self.make()
        self.assertEqual(manifest['inputs']['wasm_worker.mjs'], package_wasm.digest(original))
        self.assertEqual(manifest['csp'], package_wasm.CSP)
        self.assertNotIn('unsafe-eval', manifest['csp'].replace('wasm-unsafe-eval', ''))
        html = (self.output / package_wasm.HTML_NAME).read_text()
        self.assertIn("workerFactory:url=>new Worker(url,{type:'classic'})", html)
        payload = json.loads(re.search(r'<script type="application/json" id="foundation-assets">([^<]*)</script>', html)[1])
        self.assertEqual(base64.b64decode(payload['wasm_worker.mjs']), original)
        self.assertIn(base64.b64encode(converted.encode()).decode(), html)
        # HTTP composition still uses the existing module Worker default.
        self.assertIn("workerFactory=url=>new Worker(url,{type:'module'})", (ROOT / 'gui/host/wasm_transport.mjs').read_text())
        self.assertEqual(package_wasm.verify(self.output), manifest)
        legacy = self.make_legacy()
        legacy_html = (self.output / package_wasm.HTML_NAME).read_text()
        self.assertNotIn('workerFactory', legacy_html)
        self.assertIn("workerURL:local(text('wasm_worker.mjs'))", legacy_html)
        self.assertEqual(package_wasm.verify(self.output), legacy)

    def test_classic_worker_conversion_fails_closed_on_unexpected_module_syntax(self):
        original = (self.assets / 'wasm_worker.mjs').read_bytes()
        changes = (original.replace(b'export function installWasmWorker', b'export async function installWasmWorker'),
                   original + b"\nimport {unexpected} from './unexpected.mjs';",
                   original + b'\nexport const unexpected=1;',
                   original + b'\nconst unexpected=import.meta.url;',
                   original + b"\nconst unexpected=import('unexpected');",
                   original.replace(b'loadModule=url=>import(url)', b'loadModule=url=>import /* drift */ (url)'))
        for source in changes:
            with self.subTest(source=source[-90:]):
                (self.assets / 'wasm_worker.mjs').write_bytes(source)
                with self.assertRaisesRegex(ValueError, 'Worker module syntax'):
                    self.make()

    def test_unsafe_css_and_bad_wasm_rejected(self):
        (self.assets / 'style.css').write_text('</style><script>bad()</script>')
        with self.assertRaisesRegex(ValueError, 'style terminator'):
            self.make()
        (self.assets / 'style.css').write_text('')
        (self.assets / 'gui_web_wasm.wasm').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'Wasm module header'):
            self.make()

    def test_notices_and_embedded_inputs_bound_even_with_updated_outer_checksums(self):
        for key in ('notices', 'inputs'):
            with self.subTest(key=key):
                self.make()
                path = self.output / 'web-manifest.json'
                manifest = json.loads(path.read_text())
                name = 'LICENSE' if key == 'notices' else 'wasm_worker.mjs'
                manifest[key][name] = '0' * 64
                path.write_bytes(json.dumps(manifest).encode('utf-8'))
                (self.output / 'manifest.sha256').write_bytes(''.join(package_wasm.digest((self.output / name).read_bytes()) + '  ' + name + '\n'
                    for name in sorted((package_wasm.HTML_NAME, 'web-manifest.json'))).encode('utf-8'))
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    package_wasm.verify(self.output)

    def test_separate_module_directory_and_labeled_notices(self):
        modules = self.root / 'modules'; modules.mkdir()
        for name in ('gui_web_wasm.js', 'gui_web_wasm.wasm'):
            (self.assets / name).rename(modules / name)
        second = self.root / 'second'; second.mkdir(); (second / 'LICENSE').write_text('Second notice')
        manifest = package_wasm.package(self.assets, self.output,
            ['core=' + str(self.notice), 'toolchain=' + str(second / 'LICENSE')], modules)
        self.assertEqual(set(manifest['notices']), {'core', 'toolchain'})
        self.assertIn('Second notice', (self.output / package_wasm.HTML_NAME).read_text())
        with self.assertRaisesRegex(ValueError, 'Duplicate notice'):
            package_wasm.package(self.assets, self.output, [self.notice, second / 'LICENSE'], modules)

    def test_sdk_runtime_notices_require_exact_retained_hashes(self):
        sdk = self.root / 'sdk'; sdk.mkdir()
        names = ['LICENSE'] + list(package_wasm.WASM_RUNTIME_NOTICES)
        files = {}
        for name in names:
            path = sdk / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('notice ' + name)
            files[name] = package_wasm.digest(path.read_bytes())
        metadata = dict(target=dict(system='Emscripten'), licenses=['LICENSE'], files=files, recipe_id='a' * 64)
        (sdk / 'sdk.json').write_text(json.dumps(metadata))
        with patch.object(package_wasm, 'verify_sdk') as verify:
            manifest = package_wasm.package(self.assets, self.output, [self.notice], sdk=sdk)
            verify.assert_called_once_with(sdk.resolve(), release=True)
            self.assertEqual(len(manifest['notices']), 1 + len(names))
            self.assertEqual(manifest['sdk']['recipe_id'], 'a' * 64)
            (sdk / names[-1]).write_text('changed')
            with self.assertRaisesRegex(ValueError, 'runtime notice differs'):
                package_wasm.package(self.assets, self.output, [self.notice], sdk=sdk)

    def test_asset_budget_and_checksums_enforced(self):
        original = package_wasm.MAX_TOTAL
        try:
            package_wasm.MAX_TOTAL = 1
            with self.assertRaisesRegex(ValueError, 'size'):
                self.make()
        finally:
            package_wasm.MAX_TOTAL = original
        self.make()
        (self.output / 'manifest.sha256').write_text('')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            package_wasm.verify(self.output)


if __name__ == '__main__':
    unittest.main()
