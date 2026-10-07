"""The child assembler accepts only the reviewed module closure and syntax."""
import base64
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import browser_bundle as bundle


def fixture_blobs():
    result = {}
    for name in bundle.CHILD_MODULES:
        imports = ''.join("import {" + bundle.CHILD_EXPORTS[dependency][0] + " as input" + str(index) + "} from './" + dependency + "';\n"
                          for index, dependency in enumerate(bundle.CHILD_GRAPH[name]))
        exports = ''.join('export const ' + export + '=' + str(index) + ';\n'
                          for index, export in enumerate(bundle.CHILD_EXPORTS[name]))
        result[name] = (imports + 'const local=1;\n' + exports).encode('utf-8')
    result['style.css'] = b'body{color:black}\n'
    return result


class BrowserBundleTests(unittest.TestCase):
    def test_deterministic_pure_data_exact_hash_and_lexical_scopes(self):
        blobs = fixture_blobs()
        expected = bundle.assemble(blobs)
        self.assertEqual(bundle.assemble(blobs), expected)
        script = expected['CHILD_SCRIPT']
        hash_value = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        self.assertEqual(expected['CHILD_SCRIPT_SHA256'], hash_value)
        self.assertIn("script-src 'sha256-" + hash_value + "'", expected['CHILD_CSP'])
        self.assertEqual(expected['CHILD_SANDBOX'], 'allow-scripts')
        self.assertNotIn('blob:', expected['CHILD_CSP'])
        self.assertEqual(bundle.parse_module(bundle.module_bytes(expected)), expected)
        if shutil.which('node'):
            completed = subprocess.run(['node', '--input-type=commonjs', '-e', script + '\nif(typeof local!=="undefined")throw Error("Scope escaped");'],
                                       capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_unexpected_module_syntax_and_graph_rejected(self):
        cases = ["import './browser_limits.mjs';", "import x from './browser_limits.mjs';",
                 "import {MAX_OPERATION_BYTES} from './unknown.mjs';", "import('./browser_limits.mjs');",
                 "const value=`hidden ${import('./browser_limits.mjs')}`;",
                 "const value=/\\/\\//;import('./browser_limits.mjs');",
                 "let x=1;x++ / import('unexpected') / 2;",
                 "let x=1;x-- / import /* comment */ ('unexpected') / 2;",
                 "let α=1;α / import('unexpected') / 2;",
                 "export {createHostChannel};", "export {createHostChannel} from './renderer_channel.mjs';",
                 "export const unexpected=1;"]
        for addition in cases:
            with self.subTest(addition=addition):
                blobs = fixture_blobs()
                blobs['renderer_frame.mjs'] += addition.encode()
                with self.assertRaises(ValueError):
                    bundle.assemble(blobs)
        blobs = fixture_blobs()
        blobs['renderer_frame.mjs'] = blobs['renderer_frame.mjs'].replace(b"from './renderer_dom.mjs'", b"from './browser_presenter.mjs'")
        with self.assertRaises(ValueError):
            bundle.assemble(blobs)
        graph = dict(bundle.CHILD_GRAPH)
        graph['browser_limits.mjs'] = ('renderer_frame.mjs',)
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            bundle.assemble(fixture_blobs(), graph=graph)
        blobs = fixture_blobs()
        blobs['browser_limits.mjs'] = blobs['browser_limits.mjs'].replace(b'export const MAX_OPERATION_BYTES=0;', b'export const MAX_OPERATION_BYTES=0,unexpected=1;')
        with self.assertRaisesRegex(ValueError, 'multiple'):
            bundle.assemble(blobs)

    def test_comments_and_plain_string_keywords_are_data(self):
        blobs = fixture_blobs()
        blobs['renderer_frame.mjs'] += b'// import ignored\n/* export ignored */\nconst words="import export";const template=`import export`;'
        bundle.assemble(blobs)

    def test_windows_source_newlines_keep_html_canonical_script_hash(self):
        blobs = fixture_blobs()
        expected = bundle.assemble(blobs)
        windows = {name: data.replace(b'\n', b'\r\n') for name, data in blobs.items()}
        actual = bundle.assemble(windows)
        self.assertEqual(actual['CHILD_SCRIPT'], expected['CHILD_SCRIPT'])
        self.assertEqual(actual['CHILD_SCRIPT_SHA256'], expected['CHILD_SCRIPT_SHA256'])
        self.assertNotEqual(actual['CHILD_INPUTS'], expected['CHILD_INPUTS'])

    def test_unsafe_terminators_encoding_and_inventory_rejected(self):
        for addition in (b'// </ScRiPt>', b'// <!--', b'// -->', b'\0', b'\xff'):
            with self.subTest(addition=addition):
                blobs = fixture_blobs()
                blobs['renderer_dom.mjs'] += addition
                with self.assertRaises((ValueError, UnicodeError)):
                    bundle.assemble(blobs)
        for css in (b'</style>', b'</script>', b'\0'):
            blobs = fixture_blobs()
            blobs['style.css'] = css
            with self.assertRaises(ValueError):
                bundle.assemble(blobs)
        blobs = fixture_blobs()
        blobs['extra.mjs'] = b''
        with self.assertRaisesRegex(ValueError, 'inventory'):
            bundle.assemble(blobs)

    def test_generator_preserves_unchanged_output_and_rejects_metadata_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, data in fixture_blobs().items():
                (root / name).write_bytes(data)
            output = root / bundle.BUNDLE_NAME
            first = bundle.generate(root, output)
            stat = output.stat()
            self.assertEqual(bundle.generate(root, output), first)
            self.assertEqual(output.stat().st_mtime_ns, stat.st_mtime_ns)
            for old, new in ((b'allow-scripts', b'allow-scripts allow-same-origin'),
                             (b'foundation-renderer-v1', b'foundation-renderer-v2'),
                             (b'Generated renderer data', b'Edited renderer data')):
                with self.subTest(old=old):
                    with self.assertRaises(ValueError):
                        bundle.parse_module(first.replace(old, new))


if __name__ == '__main__':
    unittest.main()
