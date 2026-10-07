#!/usr/bin/env python3
"""Package the generated, patched browser assets as one offline HTML application."""
import argparse
import base64
import hashlib
from html import escape
import json
from pathlib import Path
import re
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from package_notices import WASM_RUNTIME_NOTICES, notice_files
from sdk_manifest import verify_sdk
import browser_bundle

LEGACY_ASSETS = ('boot.mjs', 'renderer.mjs', 'browser_lifecycle.mjs', 'wasm_transport.mjs',
          'wasm_worker.mjs', 'browser_presenter.mjs', 'file_services.mjs', 'style.css', 'index.html', 'gui_web_wasm.js', 'gui_web_wasm.wasm')
MAX_ASSET = 64 * 1024 * 1024
MAX_TOTAL = 96 * 1024 * 1024
HTML_NAME = 'software-foundation-wasm.html'
LEGACY_CSP = ("default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval' blob:; "
       "worker-src blob:; connect-src 'none'; style-src 'unsafe-inline'; "
       "img-src data: blob:; object-src 'none'; base-uri 'none'; form-action 'none'")
# Static module imports are rewritten only at these exact reviewed dependency edges.
LEGACY_IMPORTS = {'boot.mjs': ('renderer.mjs', 'browser_lifecycle.mjs', 'browser_presenter.mjs', 'wasm_transport.mjs'),
           'renderer.mjs': ('file_services.mjs',)}

# Schemas 1/2 retain their original inventory and policy. The schema-3 document
# adds an isolated renderer composition while preserving the standalone entry.
ASSETS = LEGACY_ASSETS + ('browser_limits.mjs', 'browser_client.mjs', 'browser_services.mjs', 'browser_composition.mjs',
                         'renderer_dom.mjs', 'renderer_channel.mjs', 'renderer_frame.mjs',
                         'browser_embedding.mjs', browser_bundle.BUNDLE_NAME)
CSP = LEGACY_CSP + "; frame-src 'self' blob:"
IMPORTS = {
    'boot.mjs': ('browser_embedding.mjs', 'browser_services.mjs', 'browser_composition.mjs', 'renderer.mjs', 'browser_lifecycle.mjs',
                 'browser_presenter.mjs', 'wasm_transport.mjs'),
    'renderer.mjs': ('renderer_dom.mjs', 'browser_client.mjs', 'browser_services.mjs'),
    'browser_client.mjs': ('browser_limits.mjs', 'browser_limits.mjs'),
    'browser_services.mjs': ('file_services.mjs',),
    'browser_embedding.mjs': ('browser_client.mjs', 'browser_services.mjs', 'browser_lifecycle.mjs',
                             'renderer_channel.mjs', 'browser_limits.mjs', browser_bundle.BUNDLE_NAME),
    **browser_bundle.CHILD_GRAPH,
}


def child_metadata(blobs):
    metadata = browser_bundle.assemble({name: blobs[name] for name in browser_bundle.CHILD_MODULES + ('style.css',)})
    if blobs[browser_bundle.BUNDLE_NAME] != browser_bundle.module_bytes(metadata):
        raise ValueError('Generated child bundle differs from reviewed renderer inputs')
    return {'protocol': metadata['CHILD_PROTOCOL'], 'sandbox': metadata['CHILD_SANDBOX'],
            'csp': metadata['CHILD_CSP'], 'script_sha256': digest(metadata['CHILD_SCRIPT'].encode('utf-8')),
            'script_csp_sha256': metadata['CHILD_SCRIPT_SHA256'], 'inputs': metadata['CHILD_INPUTS']}


def classic_worker_source(data):
    """Adapt only the reviewed self-installing Worker entry for local files.

    Chromium rejects a module Blob Worker created by a file document before its
    entry point runs. A classic entry retains the existing Worker-owned dynamic
    factory import. No general module transform or runtime fallback is allowed.
    """
    source = data.decode('utf-8')
    declaration = 'export function installWasmWorker(scope,loadModule=url=>import(url))'
    if (source.count(declaration) != 1 or len(re.findall(r'\bexport\b', source)) != 1 or
            len(re.findall(r'\bimport\b', source)) != 1):
        raise ValueError('Unexpected embedded Worker module syntax')
    declaration_offset = source.index(declaration)
    import_offset = declaration_offset + declaration.index('import(url)')
    if browser_bundle._keywords(source) != [(declaration_offset, 'export'), (import_offset, 'import')]:
        raise ValueError('Unexpected embedded Worker module syntax')
    # Modules are implicitly strict. Preserve that semantic mode in the classic
    # entry instead of relying on the current body to avoid sloppy behavior.
    return '"use strict";\n' + source[:declaration_offset] + source[declaration_offset:].replace('export ', '', 1)


def make_html(blobs, notices):
    if set(blobs) != set(ASSETS) or sum(map(len, blobs.values())) > MAX_TOTAL:
        raise ValueError('Invalid browser asset inventory or size')
    if not blobs['gui_web_wasm.wasm'].startswith(b'\0asm\x01\0\0\0'):
        raise ValueError('Invalid Wasm module header')
    for name in ASSETS:
        if name.endswith(('.mjs', '.js', '.css', '.html')):
            blobs[name].decode('utf-8')
    child_metadata(blobs)
    worker_source = classic_worker_source(blobs['wasm_worker.mjs'])
    for module, dependencies in IMPORTS.items():
        source = blobs[module].decode('utf-8')
        discovered = re.findall(r"['\"]\./([A-Za-z0-9_.-]+\.mjs)['\"]", source)
        if sorted(discovered) != sorted(dependencies):
            raise ValueError('Generated module dependency changed: ' + module)
    shell = blobs['index.html'].decode('utf-8')
    style_link = '<link rel="stylesheet" href="/style.css">'
    script_link = '<script type="module" src="/boot.mjs"></script>'
    if shell.count(style_link) != 1 or shell.count(script_link) != 1 or shell.count('<meta charset="utf-8">') != 1:
        raise ValueError('Generated HTML entry point changed')
    if len(re.findall(r'<script\b', shell, re.I)) != 1:
        raise ValueError('Generated HTML has an unexpected script entry point')
    style = blobs['style.css'].decode('utf-8')
    if '</style' in style.lower():
        raise ValueError('Unsafe style terminator')
    # Include original shell/style bytes too, so verification can regenerate and
    # compare the complete canonical document instead of trusting outer hashes.
    payload = {name: base64.b64encode(data).decode('ascii') for name, data in sorted(blobs.items())}
    bootstrap = '''
const assets=JSON.parse(document.querySelector('#foundation-assets').textContent);
const bytes=name=>Uint8Array.from(atob(assets[name]),c=>c.charCodeAt(0));
const text=name=>new TextDecoder('utf-8',{fatal:true}).decode(bytes(name));
const urls=[];
const local=source=>{const url=URL.createObjectURL(new Blob([source],{type:'text/javascript'}));urls.push(url);return url;};
try{
  const dependencies=DEPENDENCY_GRAPH;
  const modules=new Map();
  const moduleURL=name=>{
    if(modules.has(name))return modules.get(name);
    let source=text(name);
    for(const dependency of dependencies[name]||[]){
      const target=JSON.stringify(moduleURL(dependency));
      source=source.replace("'./"+dependency+"'",target).replace('"./'+dependency+'"',target);
    }
    const url=local(source);modules.set(name,url);return url;
  };
  const workerSource=new TextDecoder('utf-8',{fatal:true}).decode(Uint8Array.from(atob(CLASSIC_WORKER_SOURCE),c=>c.charCodeAt(0)));
  globalThis.foundationWasmAssets={workerURL:local(workerSource),workerFactory:url=>new Worker(url,{type:'classic'}),moduleURL:'embedded',
    factorySource:text('gui_web_wasm.js'),wasmBinary:bytes('gui_web_wasm.wasm')};
  await import(moduleURL('boot.mjs'));
}catch(error){document.querySelector('#status').textContent='Could not start: '+error.message;}
finally{delete globalThis.foundationWasmAssets;for(const url of urls)URL.revokeObjectURL(url);}
'''.replace('DEPENDENCY_GRAPH', json.dumps(IMPORTS, separators=(',', ':'))).replace(
        'CLASSIC_WORKER_SOURCE', json.dumps(base64.b64encode(worker_source.encode('utf-8')).decode('ascii')))
    content = ('<script type="application/json" id="foundation-assets">' + json.dumps(payload, separators=(',', ':')) + '</script>' +
               '<script type="application/json" id="foundation-notices">' +
               json.dumps({name: base64.b64encode(data).decode('ascii') for name, data in sorted(notices.items())}, separators=(',', ':')) + '</script>' +
               '<details id="foundation-notices-text"><summary>Software licenses and notices</summary><pre>' +
               escape('\n\n'.join(name + '\n' + data.decode('utf-8') for name, data in sorted(notices.items()))) +
               '</pre></details><script type="module">' + bootstrap + '</script>')
    return (shell.replace('<meta charset="utf-8">', '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + escape(CSP, quote=True) + '">')
            .replace(style_link, '<style>' + style + '</style>').replace(script_link, content)).encode('utf-8')


def read_file(path, limit=MAX_ASSET):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected ordinary asset: ' + str(path))
    if path.stat().st_size > limit:
        raise ValueError('Asset exceeds limit: ' + str(path))
    return path.read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def make_legacy_html(blobs, notices):
    if set(blobs) != set(LEGACY_ASSETS) or sum(map(len, blobs.values())) > MAX_TOTAL:
        raise ValueError('Invalid browser asset inventory or size')
    if not blobs['gui_web_wasm.wasm'].startswith(b'\0asm\x01\0\0\0'):
        raise ValueError('Invalid Wasm module header')
    for name in LEGACY_ASSETS:
        if name.endswith(('.mjs', '.js', '.css', '.html')):
            blobs[name].decode('utf-8')
    for module, dependencies in LEGACY_IMPORTS.items():
        source = blobs[module].decode('utf-8')
        for name in dependencies:
            if source.count("'./" + name + "'") != 1:
                raise ValueError('Generated module dependency changed: ' + module + ' -> ' + name)
    shell = blobs['index.html'].decode('utf-8')
    style_link = '<link rel="stylesheet" href="/style.css">'
    script_link = '<script type="module" src="/boot.mjs"></script>'
    if shell.count(style_link) != 1 or shell.count(script_link) != 1 or shell.count('<meta charset="utf-8">') != 1:
        raise ValueError('Generated HTML entry point changed')
    style = blobs['style.css'].decode('utf-8')
    if '</style' in style.lower():
        raise ValueError('Unsafe style terminator')
    payload = {name: base64.b64encode(data).decode('ascii') for name, data in blobs.items()
               if name not in ('index.html', 'style.css')}
    bootstrap = '''
const assets=JSON.parse(document.querySelector('#foundation-assets').textContent);
const bytes=name=>Uint8Array.from(atob(assets[name]),c=>c.charCodeAt(0));
const text=name=>new TextDecoder('utf-8',{fatal:true}).decode(bytes(name));
const urls=[];
const local=source=>{const url=URL.createObjectURL(new Blob([source],{type:'text/javascript'}));urls.push(url);return url;};
try{
  const dependencies=DEPENDENCY_GRAPH;
  const modules=new Map();
  const moduleURL=name=>{
    if(modules.has(name))return modules.get(name);
    let source=text(name);
    for(const dependency of dependencies[name]||[])
      source=source.replace("'./"+dependency+"'",JSON.stringify(moduleURL(dependency)));
    const url=local(source);modules.set(name,url);return url;
  };
  globalThis.foundationWasmAssets={workerURL:local(text('wasm_worker.mjs')),moduleURL:'embedded',
    factorySource:text('gui_web_wasm.js'),wasmBinary:bytes('gui_web_wasm.wasm')};
  await import(moduleURL('boot.mjs'));
}catch(error){document.querySelector('#status').textContent='Could not start: '+error.message;}
finally{delete globalThis.foundationWasmAssets;for(const url of urls)URL.revokeObjectURL(url);}
'''
    bootstrap = bootstrap.replace('DEPENDENCY_GRAPH', json.dumps(LEGACY_IMPORTS, separators=(',', ':')))
    content = ('<script type="application/json" id="foundation-assets">' +
               json.dumps(payload, separators=(',', ':')) + '</script>' +
               '<script type="application/json" id="foundation-notices">' +
               json.dumps({name: base64.b64encode(data).decode('ascii') for name, data in sorted(notices.items())}, separators=(',', ':')) + '</script>' +
               '<details id="foundation-notices-text"><summary>Software licenses and notices</summary><pre>' +
               escape('\n\n'.join(name + '\n' + data.decode('utf-8') for name, data in sorted(notices.items()))) +
               '</pre></details><script type="module">' + bootstrap + '</script>')
    return (shell.replace('<meta charset="utf-8">', '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + escape(LEGACY_CSP, quote=True) + '">')
            .replace(style_link, '<style>' + style + '</style>').replace(script_link, content)).encode('utf-8')


def sdk_notices(root):
    root = Path(root).resolve(strict=True)
    verify_sdk(root, release=True)
    manifest = json.loads(read_file(root / 'sdk.json'))
    if manifest['target']['system'] != 'Emscripten':
        raise ValueError('Offline Wasm package requires an Emscripten SDK')
    inputs = []
    for relative in manifest['licenses']:
        tree = root / relative
        if root not in tree.resolve(strict=True).parents:
            raise ValueError('SDK notice escapes retained root')
        inputs.extend(notice_files(tree))
    inputs.extend(root / name for name in WASM_RUNTIME_NOTICES)
    paths = sorted(set(inputs))
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if manifest['files'].get(relative) != digest(read_file(path)):
            raise ValueError('SDK runtime notice differs from retained inventory: ' + relative)
    return ['sdk-' + str(index) + '=' + str(path) for index, path in enumerate(paths)], {
        'manifest_sha256': digest(read_file(root / 'sdk.json')), 'recipe_id': manifest['recipe_id']}


def package(assets, output, notice_paths, module_dir=None, sdk=None, source_root=None):
    assets, output = Path(assets), Path(output)
    if not notice_paths:
        raise ValueError('At least one applicable license notice is required')
    notice_paths = list(notice_paths)
    sdk_identity = None
    if sdk is not None:
        extra, sdk_identity = sdk_notices(sdk)
        notice_paths.extend(extra)
    notices = {}
    for item in notice_paths:
        label, raw = str(item).split('=', 1) if '=' in str(item) else (Path(item).name, str(item))
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', label) or label in ('.', '..'):
            raise ValueError('Invalid notice label')
        if label in notices:
            raise ValueError('Duplicate notice label: ' + label)
        notices[label] = read_file(Path(raw))
    if sum(map(len, notices.values())) > 4 * 1024 * 1024:
        raise ValueError('Notices exceed limit')
    blobs = {name: read_file((Path(module_dir) if module_dir and name.startswith('gui_web_wasm.') else assets) / name) for name in ASSETS}
    html = make_html(blobs, notices)
    manifest = {'schema': 3, 'runtime': 'dedicated-worker', 'transport': 'ordered-local-messages',
                'network': 'disabled-by-csp', 'csp': CSP,
                'renderer_modes': ['standalone', 'isolated'], 'child': child_metadata(blobs),
                'inputs': {name: digest(data) for name, data in sorted(blobs.items())},
                'notices': {name: digest(data) for name, data in sorted(notices.items())},
                'html_sha256': digest(html)}
    if source_root is not None:
        from source_identity import source_tree
        manifest['source_tree_sha256'] = source_tree(source_root)['tree_sha256']
    if sdk_identity is not None:
        manifest['sdk'] = sdk_identity
    if output.is_symlink():
        raise ValueError('Output must be an ordinary directory')
    output.mkdir(parents=True, exist_ok=True)
    expected = {HTML_NAME, 'web-manifest.json', 'manifest.sha256'}
    if any(p.name not in expected or not p.is_file() or p.is_symlink() for p in output.iterdir()):
        raise ValueError('Output contains unexpected entries')
    (output / HTML_NAME).write_bytes(html)
    # These files have byte identities; host text-mode newline translation must
    # not change either the metadata or the portable checksum grammar.
    (output / 'web-manifest.json').write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode('utf-8'))
    (output / 'manifest.sha256').write_bytes(''.join(digest(read_file(output / name, 256 * 1024 * 1024)) + '  ' + name + '\n'
                                                for name in sorted(expected - {'manifest.sha256'})).encode('utf-8'))
    verify(output)
    return manifest


def verify(output):
    output = Path(output)
    if output.is_symlink() or set(p.name for p in output.iterdir()) != {HTML_NAME, 'web-manifest.json', 'manifest.sha256'}:
        raise ValueError('Incomplete or unexpected package inventory')
    manifest = json.loads(read_file(output / 'web-manifest.json'))
    schema = manifest.get('schema')
    if type(schema) is not int or schema not in (1, 2, 3):
        raise ValueError('Package manifest mismatch')
    if schema in (1, 2):
        return verify_legacy(output)
    html = read_file(output / HTML_NAME, 256 * 1024 * 1024)
    if manifest.get('csp') != CSP or manifest.get('html_sha256') != digest(html):
        raise ValueError('Package manifest mismatch')
    source_identity = manifest.get('source_tree_sha256')
    if 'source_tree_sha256' in manifest and (not isinstance(source_identity, str) or not re.fullmatch(r'[0-9a-f]{64}', source_identity)):
        raise ValueError('Package source identity missing or invalid')
    expected = ''.join(digest(read_file(output / name, 256 * 1024 * 1024)) + '  ' + name + '\n'
                       for name in sorted((HTML_NAME, 'web-manifest.json')))
    if read_file(output / 'manifest.sha256').decode('utf-8') != expected:
        raise ValueError('Package checksum mismatch')
    text = html.decode('utf-8')
    if re.search(r'<script\b[^>]*\bsrc\s*=', text, re.I):
        raise ValueError('Package has an external entry point')
    payloads = re.findall(r'<script type="application/json" id="foundation-assets">([^<]*)</script>', text)
    if len(payloads) != 1:
        raise ValueError('Missing embedded asset inventory')
    payload = json.loads(payloads[0])
    if not isinstance(payload, dict) or set(payload) != set(ASSETS) or set(manifest.get('inputs', {})) != set(ASSETS):
        raise ValueError('Embedded asset inventory mismatch')
    blobs = {}
    for name, encoded in payload.items():
        if not isinstance(encoded, str):
            raise ValueError('Invalid embedded asset encoding')
        blobs[name] = base64.b64decode(encoded, validate=True)
        if len(blobs[name]) > MAX_ASSET or digest(blobs[name]) != manifest['inputs'][name]:
            raise ValueError('Embedded asset digest mismatch: ' + name)
    notice_payloads = re.findall(r'<script type="application/json" id="foundation-notices">([^<]*)</script>', text)
    if len(notice_payloads) != 1:
        raise ValueError('Missing embedded notices')
    encoded_notices = json.loads(notice_payloads[0])
    if not isinstance(encoded_notices, dict) or not encoded_notices or set(encoded_notices) != set(manifest.get('notices', {})):
        raise ValueError('Embedded notice inventory mismatch')
    notices = {}
    for name, encoded in encoded_notices.items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..') or not isinstance(encoded, str):
            raise ValueError('Invalid embedded notice label or encoding')
        notices[name] = base64.b64decode(encoded, validate=True)
        if digest(notices[name]) != manifest['notices'][name]:
            raise ValueError('Embedded notice digest mismatch')
    if sum(map(len, notices.values())) > 4 * 1024 * 1024:
        raise ValueError('Embedded notices exceed limit')
    if (manifest.get('runtime') != 'dedicated-worker' or manifest.get('transport') != 'ordered-local-messages' or
            manifest.get('network') != 'disabled-by-csp' or manifest.get('renderer_modes') != ['standalone', 'isolated']):
        raise ValueError('Package runtime/renderer metadata mismatch')
    if manifest.get('child') != child_metadata(blobs):
        raise ValueError('Package child isolation metadata mismatch')
    if html != make_html(blobs, notices):
        raise ValueError('Package document differs from canonical embedded inputs')
    return manifest


def verify_legacy(output):
    output = Path(output)
    if output.is_symlink() or set(p.name for p in output.iterdir()) != {HTML_NAME, 'web-manifest.json', 'manifest.sha256'}:
        raise ValueError('Incomplete or unexpected package inventory')
    html = read_file(output / HTML_NAME, 256 * 1024 * 1024)
    manifest = json.loads(read_file(output / 'web-manifest.json'))
    if manifest.get('schema') not in (1, 2) or manifest.get('csp') != LEGACY_CSP or manifest.get('html_sha256') != digest(html):
        raise ValueError('Package manifest mismatch')
    if manifest['schema'] == 2 and not re.fullmatch(r'[0-9a-f]{64}', manifest.get('source_tree_sha256', '')):
        raise ValueError('Package source identity missing or invalid')
    expected = ''.join(digest(read_file(output / name, 256 * 1024 * 1024)) + '  ' + name + '\n' for name in sorted((HTML_NAME, 'web-manifest.json')))
    if read_file(output / 'manifest.sha256').decode('utf-8') != expected:
        raise ValueError('Package checksum mismatch')
    text = html.decode('utf-8')
    if escape(LEGACY_CSP, quote=True) not in text or re.search(r'<script\b[^>]*\bsrc\s*=', text, re.I):
        raise ValueError('Package has an external entry point')
    payloads = re.findall(r'<script type="application/json" id="foundation-assets">([^<]*)</script>', text)
    if len(payloads) != 1:
        raise ValueError('Missing embedded asset inventory')
    payload = json.loads(payloads[0])
    expected_names = set(LEGACY_ASSETS) - {'index.html', 'style.css'}
    if set(payload) != expected_names or set(manifest.get('inputs', {})) != set(LEGACY_ASSETS):
        raise ValueError('Embedded asset inventory mismatch')
    for name, encoded in payload.items():
        data = base64.b64decode(encoded, validate=True)
        if len(data) > MAX_ASSET or digest(data) != manifest['inputs'][name]:
            raise ValueError('Embedded asset digest mismatch: ' + name)
    styles = re.findall(r'<style>(.*?)</style>', text, re.S)
    if len(styles) != 1 or digest(styles[0].encode('utf-8')) != manifest['inputs']['style.css']:
        raise ValueError('Embedded style digest mismatch')
    notice_payloads = re.findall(r'<script type="application/json" id="foundation-notices">([^<]*)</script>', text)
    if len(notice_payloads) != 1:
        raise ValueError('Missing embedded notices')
    encoded_notices = json.loads(notice_payloads[0])
    if not isinstance(encoded_notices, dict) or not encoded_notices or set(encoded_notices) != set(manifest.get('notices', {})):
        raise ValueError('Embedded notice inventory mismatch')
    notices = {}
    for name, encoded in encoded_notices.items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
            raise ValueError('Invalid embedded notice label')
        notices[name] = base64.b64decode(encoded, validate=True)
        if digest(notices[name]) != manifest['notices'][name]:
            raise ValueError('Embedded notice digest mismatch')
    if sum(map(len, notices.values())) > 4 * 1024 * 1024:
        raise ValueError('Embedded notices exceed limit')
    visible_notices = ('<details id="foundation-notices-text"><summary>Software licenses and notices</summary><pre>' +
                       escape('\n\n'.join(name + '\n' + data.decode('utf-8') for name, data in sorted(notices.items()))) + '</pre></details>')
    if text.count(visible_notices) != 1:
        raise ValueError('Visible notice content differs')
    if not manifest.get('notices') or manifest.get('runtime') != 'dedicated-worker' or manifest.get('transport') != 'ordered-local-messages' or manifest.get('network') != 'disabled-by-csp':
        raise ValueError('Package runtime/notice metadata mismatch')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--notice', action='append', default=[], help='Applicable notice path or unique-label=path')
    parser.add_argument('--module-dir', type=Path, help='Directory containing compiled gui_web_wasm.js/.wasm')
    parser.add_argument('--sdk', type=Path, help='Verified retained Emscripten SDK including complete runtime notices')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--source-root', type=Path, help='Bind the package to the complete application source tree')
    args = parser.parse_args(argv)
    if args.verify:
        verify(args.output)
    elif args.assets:
        package(args.assets, args.output, args.notice, args.module_dir, args.sdk, args.source_root)
    else:
        parser.error('--assets is required for packaging')


if __name__ == '__main__':
    main()
