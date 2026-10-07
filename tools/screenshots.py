#!/usr/bin/env python3
"""Capture seven fresh application surfaces and publish an immutable non-Latest gallery."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import secrets
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

import ci_plan as ci
import dependency_archive as archive
import github_release as delivery
import process_tree
import gallery_browser
from build_capacity import compile_jobs

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ('fltk', 'rev', 'sdl', 'terminal', 'framebuffer', 'hosted-web', 'wasm')
TARGETS = ('fltk', 'rev', 'sdl', 'terminal', 'framebuffer', 'web')
PUBLIC = {*(name + '.png' for name in BACKENDS), 'BUILD.txt', 'screenshots.json', 'SHA256SUMS'}
MAX_IMAGE = 16 * 1024 * 1024
MAX_DISPLAY_LOG = 4 * 1024 * 1024


def command(argv, *, timeout=30, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, timeout=timeout, **kwargs)


def text(argv):
    return command(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


def image_info(path):
    width, height, colors = text(['identify', '-format', '%w %h %k', path]).split()
    return int(width), int(height), int(colors)


def png_size(path):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_IMAGE:
        raise ValueError('ordinary bounded PNG required')
    with path.open('rb') as stream:
        data = stream.read(24)
    if len(data) != 24 or data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
        raise ValueError('invalid PNG header')
    width, height = struct.unpack('>II', data[16:])
    if not 1 <= width <= 2048 or not 1 <= height <= 2048:
        raise ValueError('unsupported PNG dimensions')
    return width, height


def valid_dimensions(name, width, height):
    return (640 <= width <= 900 and 496 <= height <= 700) if name == 'terminal' else (width, height) == (640, 480)


@contextmanager
def process(argv, log_path, *, environment=None):
    """The private supervisor owns nested children before the application starts."""
    with log_path.open('xb') as log:
        child = process_tree.launch([str(x) for x in argv], log_path.parent, log, env=environment)
        try:
            yield child
        finally:
            try:
                child.terminate()
            finally:
                child.close()


def windows():
    result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--maxdepth', '1', '--name', '.'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
    if result.returncode not in (0, 1):
        raise RuntimeError('cannot inspect the declared native display')
    return set(result.stdout.split())


def capture_window(argv, name, directory):
    before = windows(); output = directory / (name + '.png')
    with process(argv, directory / (name + '.log'), environment=os.environ.copy()) as child:
        deadline = time.monotonic() + 30
        previous = None; since = time.monotonic()
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(name + ' exited before a complete capture')
            candidates = windows() - before
            if len(candidates) == 1:
                window = next(iter(candidates))
                command(['import', '-silent', '-window', window, '-strip', output],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                width, height, colors = image_info(output)
                fingerprint = archive.digest(output)
                if valid_dimensions(name, width, height) and colors >= 4:
                    if fingerprint != previous:
                        previous, since = fingerprint, time.monotonic()
                    elif time.monotonic() - since >= 1:
                        if child.poll() is not None:
                            raise RuntimeError(name + ' exited before capture completed')
                        return {'width': width, 'height': height, 'colors': colors, 'surface': 'native-window'}
                else:
                    previous = None
            time.sleep(.2)
        raise RuntimeError(name + ': no stable painted window at the declared viewport')


@contextmanager
def web_host(native, wasm):
    spec = importlib.util.spec_from_file_location('gallery_host', native / 'gui/web/serve.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with module.boundary.Host(('127.0.0.1', 0), native / 'gui/foundation-gui-web', wasm / 'gui') as host:
        thread = threading.Thread(target=host.serve_forever); thread.start()
        try:
            yield 'http://' + host.authority + '/'
        finally:
            host.shutdown(); thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError('browser host did not stop; retain all output ownership')


def capture_web(native, wasm, directory):
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    options = gallery_browser.chrome_options(directory / 'browser-profile')
    service = gallery_browser.chrome_service(directory / 'chromedriver.log')
    result = {}
    with web_host(native, wasm) as url, webdriver.Chrome(service=service, options=options) as browser:
        sandbox = gallery_browser.sandbox_status(browser)
        browser.set_page_load_timeout(30); browser.set_script_timeout(10)
        browser.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': '''
            window.galleryPending=0; const originalFetch=window.fetch;
            window.fetch=async (...args)=>{++window.galleryPending;
                try{return await originalFetch(...args);}finally{--window.galleryPending;}};
        '''})
        browser.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',
            {'width': 640, 'height': 512, 'deviceScaleFactor': 1, 'mobile': False})
        geometry = None
        for name, mode, status in (('hosted-web', 'hosted', 'Hosted C++'), ('wasm', 'wasm', 'Wasm')):
            browser.get(url + '?mode=' + mode)
            deadline = time.monotonic() + 30; previous = None; since = time.monotonic()
            while time.monotonic() < deadline:
                state = browser.execute_script('''
                    const stage=document.querySelector('#stage');
                    return {status:document.querySelector('#status').textContent,
                        ready:window.galleryPending===0 && document.fonts.status==='loaded' &&
                            stage.clientWidth===640 && stage.clientHeight===480 && !!stage.querySelector('.widget') &&
                            [...stage.querySelectorAll('img')].every(i=>i.complete && i.naturalWidth>0),
                        html:stage.innerHTML,
                        geometry:[...stage.querySelectorAll('.widget')].map(e=>({key:e.dataset.key,
                            box:[e.offsetLeft,e.offsetTop,e.offsetWidth,e.offsetHeight]}))};
                ''')
                if state['status'].startswith('Could not start:'):
                    raise RuntimeError(name + ': application startup failed')
                if state['ready'] and state['status'].startswith(status + ' ·'):
                    pixels = browser.find_element(By.ID, 'viewport').screenshot_as_png
                    fingerprint = hashlib.sha256(state['html'].encode() + pixels).digest()
                    if fingerprint != previous:
                        previous, since = fingerprint, time.monotonic()
                    elif time.monotonic() - since >= 1:
                        if geometry is not None and state['geometry'] != geometry:
                            raise RuntimeError('browser initial shared geometry differs between transports')
                        geometry = state['geometry']
                        (directory / (name + '.png')).write_bytes(pixels)
                        result[name] = {'width': 640, 'height': 480, 'surface': 'browser-viewport',
                                        'mode': mode, 'geometry': geometry}
                        break
                else:
                    previous = None
                time.sleep(.2)
            else:
                raise RuntimeError(name + ': initial browser view did not settle')
            # Drop the first session before creating the independent next transport.
            browser.get('about:blank')
        result['browser'] = {key: browser.capabilities.get(key) for key in ('browserName', 'browserVersion')}
        result['browser']['sandbox'] = sandbox
    return result


def surfaces(native, wasm, directory):
    if sys.platform != 'linux' or not os.environ.get('DISPLAY'):
        raise ValueError('initial-view capture requires Linux and its declared private display')
    if any(os.environ.get(k) != v for k, v in {'SDL_VIDEODRIVER': 'x11', 'REV_SCALE': '1',
                                             'LIBGL_ALWAYS_SOFTWARE': '1'}.items()):
        raise ValueError('declare native X11, scale one and software rendering explicitly')
    display = text(['xdpyinfo'])
    if 'resolution:    96x96 dots per inch' not in display:
        raise ValueError('the private capture display must use 96 DPI')
    for name in ('xdotool', 'import', 'identify', 'convert', 'xterm', 'chromedriver'):
        if not shutil.which(name):
            raise ValueError('missing screenshot prerequisite: ' + name)
    directory.mkdir(parents=True, exist_ok=False)
    command(['xdotool', 'mousemove', '1200', '850'])
    result = {}
    for name in ('fltk', 'rev', 'sdl'):
        result[name] = capture_window([native / 'gui' / ('foundation-gui-' + name)], name, directory)
    result['terminal'] = capture_window(['xterm', '-geometry', '80x31+0+0', '-fa', 'DejaVu Sans Mono',
        '-fs', '10', '+sb', '-xrm', 'XTerm*cursorBlink:false', '-e', native / 'gui/foundation-gui-terminal'],
        'terminal', directory)
    command([native / 'gui/foundation-gui-framebuffer', directory / 'framebuffer.ppm'])
    command(['convert', directory / 'framebuffer.ppm', '-strip', directory / 'framebuffer.png'])
    result['framebuffer'] = {'width': 640, 'height': 480, 'surface': 'application-framebuffer'}
    result.update(capture_web(native, wasm, directory))
    for name in BACKENDS:
        width, height, colors = image_info(directory / (name + '.png'))
        if not valid_dimensions(name, width, height) or colors < 4:
            raise ValueError('blank or wrongly sized actual capture: ' + name)
        result[name].update(width=width, height=height, colors=colors)
    delivery.coverage.write_new(directory / 'captures.json', result)


def collect(native_group, native_recipe, wasm_group, wasm_recipe, gui_group, work, output, jobs=2, origins=None, *,
            core_provider='rust', native_rust_group=None, native_rust_recipe=None,
            wasm_rust_group=None, wasm_rust_recipe=None, rust_origins=None):
    import sdk
    import windows_graphics
    ci.assert_host('linux-x86_64')
    work, output = Path(work).absolute(), Path(output).absolute()
    if jobs < 1 or work.exists() or output.exists() or work.is_symlink() or output.is_symlink():
        raise ValueError('new owned work/output directories and positive concurrency required')
    gui = ci.gui_group_module().verify(Path(gui_group))
    inputs = {'native': delivery.store.verify_group(native_group, native_recipe),
              'wasm': delivery.store.verify_group(wasm_group, wasm_recipe)}
    rust_groups = {'native': native_rust_group, 'wasm': wasm_rust_group}
    rust_recipes = {'native': native_rust_recipe, 'wasm': wasm_rust_recipe}
    rust_inputs = {name: ci.rust_selection(core_provider, rust_groups[name], rust_recipes[name])
                   for name in ('native', 'wasm')}
    if core_provider == 'cpp' and rust_origins is not None:
        raise ValueError('C++ selection must omit Rust SDK origins')
    if rust_origins is None:
        rust_origins = {name: {'origin': 'local', 'recipe': recipe} for name, recipe in rust_recipes.items()}
    if core_provider == 'rust' and (not isinstance(rust_origins, dict) or set(rust_origins) != {'native', 'wasm'}):
        raise ValueError('both Rust SDK acquisition origins are required')
    origins = origins or {name: {'origin': 'local', 'recipe': recipe} for name, recipe in
                          [('native', native_recipe), ('wasm', wasm_recipe)]}
    commit = ci.exact_commit(text(['git', '-C', ROOT, 'rev-parse', 'HEAD']))
    if text(['git', '-C', ROOT, 'status', '--porcelain', '--untracked-files=normal']):
        raise ValueError('capture requires a clean source commit')
    if os.environ.get('GITHUB_SHA', commit) != commit:
        raise ValueError('capture source differs from workflow revision')
    source = ci.module('source_identity').source_tree(ROOT)
    work.mkdir(parents=True)
    native_metadata = sdk.install(native_group, native_recipe, work / 'native-sdk', production=True)
    wasm_metadata = sdk.install(wasm_group, wasm_recipe, work / 'wasm-sdk', production=True)
    if (native_metadata['target']['system'] != 'Linux' or native_metadata['target']['processor'] != 'x86_64' or
            wasm_metadata['target']['system'] != 'Emscripten' or
            not {'terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web'} <= set(native_metadata.get('capabilities', []))):
        raise ValueError('capture requires the declared GUI-capable native and browser SDKs')
    rust_provenance = {}
    for name, backends in (('native', 'terminal,framebuffer,fltk,rev,sdl,hosted-web'), ('wasm', 'wasm')):
        provider_flags, identity = ci.install_rust_input(core_provider, rust_groups[name], rust_recipes[name],
                                                        work / (name + '-rust-sdk'), work / (name + '-sdk'))
        if core_provider == 'rust':
            rust_provenance[name] = {**identity, 'group_files': rust_inputs[name], 'origin': rust_origins[name]}
        windows_graphics.run_owned([sys.executable, str(ROOT / 'tools/build.py'), 'build', 'release', '--portable',
            '--sdk', str(work / (name + '-sdk')), '--gui-input-group', str(Path(gui_group).resolve()),
            '--gui-backends', backends, '--build-dir', str(work / name), '--jobs', str(jobs), *provider_flags],
            ROOT, work / (name + '-build.log'), timeout=3600)
    windows_graphics.run_owned([sys.executable, str(Path(__file__).resolve()), 'surfaces',
        '--native', str(work / 'native'), '--wasm', str(work / 'wasm'), '--output', str(work / 'captures')],
        ROOT, work / 'capture.log', environment=os.environ.copy(), timeout=300)
    if (ci.module('source_identity').source_tree(ROOT) != source or
            ci.gui_group_module().verify(Path(gui_group)) != gui or
            delivery.store.verify_group(native_group, native_recipe) != inputs['native'] or
            delivery.store.verify_group(wasm_group, wasm_recipe) != inputs['wasm'] or
            any(ci.rust_selection(core_provider, rust_groups[name], rust_recipes[name]) != rust_inputs[name]
                for name in ('native', 'wasm'))):
        raise ValueError('source or prepared capture inputs changed during execution')
    captures = delivery.coverage.load(work / 'captures/captures.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gallery-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'gallery'; stage.mkdir()
        for name in BACKENDS:
            shutil.copyfile(work / 'captures' / (name + '.png'), stage / (name + '.png'))
        binaries = {str(path.relative_to(work)): archive.digest(path) for path in
            [*(work / 'native/gui' / ('foundation-gui-' + name) for name in TARGETS),
             work / 'wasm/gui/gui_web_wasm.js', work / 'wasm/gui/gui_web_wasm.wasm']}
        manifest = {'schema_version': 2, 'kind': 'initial-view-gallery', 'source_commit': commit,
            'source_sha256': delivery.coverage.digest(source), 'run_id': os.environ.get('GITHUB_RUN_ID', 'local'),
            'attempt': int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')), 'state': 'fresh initial application',
            'logical_viewport': [640, 480], 'display_dpi': 96, 'display_scale': 1,
            'terminal': '80x31 cells; DejaVu Sans Mono 10pt; status row and terminal border retained',
            'host': ci.assert_host('linux-x86_64'), 'distribution': platform.freedesktop_os_release(),
            'recipes': {'native': native_recipe, 'wasm': wasm_recipe}, 'dependencies': inputs, 'origins': origins,
            'core_provider': core_provider, 'rust': rust_provenance,
            'gui_group': {**{key: gui[key] for key in ('revision', 'source_tree', 'upstream', 'license',
                           'redistributable', 'archive_sha256')},
                          'manifest_sha256': archive.digest(Path(gui_group) / 'manifest.json')},
            'binaries': binaries, 'captures': captures,
            'tools': {name: text([gallery_browser.chrome_options(work / 'unused-profile').binary_location if name == 'browser' else name,
                           '-version' if name == 'xterm' else '--version']).splitlines()[0]
                      for name in ('cmake', 'browser', 'chromedriver', 'xterm')},
            'images': {name + '.png': {'sha256': archive.digest(stage / (name + '.png')),
                                     'size': (stage / (name + '.png')).stat().st_size,
                                     'dimensions': list(png_size(stage / (name + '.png')))} for name in BACKENDS}}
        delivery.coverage.write_new(stage / 'screenshots.json', manifest)
        (stage / 'BUILD.txt').write_text('Initial application view for seven actual backends.\n'
            'Source: ' + commit + '\nRun: ' + manifest['run_id'] + '; attempt: ' + str(manifest['attempt']) + '\n'
            'Core provider: ' + core_provider + '\n'
            'Native: X11, 96 DPI, 640x480 client pixels, scale 1. Browser: 640x480 viewport.\n'
            'Terminal: 80x31 cells; status row and border retained. No content edits or image resampling.\n'
            'See screenshots.json for exact source, SDK inputs, binaries, runtime and image digests.\n'
            'These images do not establish release qualification or permission to redistribute dependencies.\n', encoding='utf-8')
        files = sorted(p.name for p in stage.iterdir())
        (stage / 'SHA256SUMS').write_text(''.join(archive.digest(stage / name) + '  ' + name + '\n' for name in files), encoding='ascii')
        verify_gallery(stage)
        stage.rename(output)
    return manifest


def input_selection(repository, native_recipe, wasm_recipe, source='base', retained_inputs=None):
    delivery.location(repository)
    recipes = {'native': native_recipe, 'wasm': wasm_recipe}
    if any(not isinstance(r, str) or not delivery.SHA.fullmatch(r) for r in recipes.values()):
        raise ValueError('both exact SDK recipes are required')
    if source == 'base':
        if retained_inputs is not None:
            raise ValueError('base source must not contain retained input requests')
        return recipes
    if source != 'retained' or not isinstance(retained_inputs, dict) or set(retained_inputs) != {'native', 'wasm'}:
        raise ValueError('retained source requires exactly two explicit SDK requests')
    for name, target in [('native', 'linux-x86_64'), ('wasm', 'browser-wasm32')]:
        ci.retained_sdk_request(retained_inputs[name], repository, target, 'all-gui', recipes[name])
    return recipes


def rust_input_selection(repository, core_provider='rust', native_recipe=None, wasm_recipe=None,
                         source='base', retained_inputs=None):
    if repository is not None:
        delivery.location(repository)
    if core_provider == 'cpp':
        if native_recipe is not None or wasm_recipe is not None or retained_inputs is not None or source != 'base':
            raise ValueError('C++ selection must omit Rust SDK acquisition inputs')
        return {}
    if core_provider != 'rust':
        raise ValueError('unknown core provider')
    recipes = {name: recipe if recipe is not None else ci.rust_recipe(target)
               for name, target, recipe in [('native', 'linux-x86_64', native_recipe),
                                           ('wasm', 'browser-wasm32', wasm_recipe)]}
    if any(not isinstance(recipe, str) or not delivery.SHA.fullmatch(recipe) for recipe in recipes.values()):
        raise ValueError('both exact Rust SDK recipes are required')
    if source == 'base':
        if retained_inputs is not None:
            raise ValueError('base Rust source must not contain retained input requests')
        return recipes
    if source != 'retained' or not isinstance(retained_inputs, dict) or set(retained_inputs) != {'native', 'wasm'}:
        raise ValueError('retained Rust source requires exactly two explicit SDK requests')
    for name, target in [('native', 'linux-x86_64'), ('wasm', 'browser-wasm32')]:
        ci.retained_rust_request(retained_inputs[name], repository, target, recipes[name])
    return recipes


def gui_input_selection(repository, value):
    """Bind an existing group and, for private storage, its exact successful producer."""
    delivery.location(repository)
    if (not isinstance(value, dict) or value.get('source') not in ('base', 'retained') or
            not isinstance(value.get('manifest_sha256'), str) or
            not delivery.SHA.fullmatch(value['manifest_sha256'])):
        raise ValueError('exact existing GUI input selector required')
    if value['source'] == 'base':
        if set(value) != {'source', 'manifest_sha256'}:
            raise ValueError('base GUI selector has unexpected fields')
        return value
    if set(value) != {'source', 'pointer', 'manifest_sha256'} or not isinstance(value['pointer'], dict):
        raise ValueError('retained GUI selector requires an exact transport pointer')
    p = value['pointer']; m = p.get('manifest')
    if (set(p) != {'schema_version', 'repository', 'run_id', 'attempt', 'source_commit', 'workflow',
                   'name', 'job_id', 'release_id', 'tag', 'manifest'} or
            type(p['schema_version']) is not int or p['schema_version'] != 1 or
            p['repository'] != repository or p['workflow'] != 'gui-inputs.yml' or
            any(type(p[k]) is not int or not 0 < p[k] < 2**63 for k in ('run_id', 'attempt', 'job_id', 'release_id')) or
            not isinstance(p['source_commit'], str) or not delivery.OID.fullmatch(p['source_commit']) or
            p['name'] != 'gui-inputs-' + str(p['attempt']) or
            p['tag'] != f"ci-{p['run_id']}-attempt-{p['attempt']}" or
            not isinstance(m, dict) or set(m) != {'id', 'name', 'size', 'sha256'} or
            type(m['id']) is not int or not 0 < m['id'] < 2**63 or
            type(m['size']) is not int or not 0 < m['size'] <= ci.module('ci_transport').MAX_MANIFEST or
            m['name'] != 'bundle-' + p['name'] + '.json' or
            not isinstance(m['sha256'], str) or not delivery.SHA.fullmatch(m['sha256'])):
        raise ValueError('retained GUI producer pointer differs from its exact contract')
    return value


def fetch_gui_input(repository, selector, output):
    selector = gui_input_selection(repository, selector)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('GUI input destination must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gallery-gui-', dir=output.parent) as temporary:
        stage = Path(temporary); group = stage / 'group'
        if selector['source'] == 'base':
            receipt = ci.fetch_gui_group(repository, selector['manifest_sha256'], group)
        else:
            p = selector['pointer']; payload = stage / 'payload'
            receipt = ci.module('ci_transport').fetch_bundle(repository, p['run_id'], p['attempt'],
                p['source_commit'], p['workflow'], p['name'], payload, job_id=p['job_id'],
                manifest_id=p['manifest']['id'], manifest_sha256=p['manifest']['sha256'])
            if receipt['pointer'] != p:
                raise ValueError('fetched GUI pointer differs from the complete selected identity')
            if {entry.name for entry in payload.iterdir()} != {'gui-group', 'gui-publication-plan.json'}:
                raise ValueError('retained GUI bundle must contain only its complete group and plan')
            plan_path = archive.checked_file(payload, 'gui-publication-plan.json')
            if plan_path.stat().st_size > 64 * 1024:
                raise ValueError('retained GUI plan exceeds supported limit')
            plan = delivery.coverage.load(plan_path)
            expected = {key: item for key, item in plan.items() if key != 'plan_sha256'}
            if (plan.get('plan_sha256') != delivery.coverage.digest(expected) or
                    plan.get('operation') != 'publish-gui-inputs' or plan.get('repository') != repository or
                    plan.get('source_commit') != p['source_commit'] or plan.get('execute') is not False or
                    plan.get('group_sha256') != selector['manifest_sha256']):
                raise ValueError('retained GUI plan does not bind the selected group and producer')
            group = payload / 'gui-group'
        manifest = ci.gui_group_module().verify(group)
        if archive.digest(group / 'manifest.json') != selector['manifest_sha256']:
            raise ValueError('GUI manifest differs from the selected group identity')
        if selector['source'] == 'retained':
            names = ci.gui_group_names(selector['manifest_sha256'])
            if (plan.get('files') != {remote: archive.digest(group / local) for local, remote in names.items()} or
                    plan.get('redistributable') is not manifest['redistributable']):
                raise ValueError('retained GUI plan file inventory or terms differs')
        group.rename(output)
    return {'selector': selector, 'receipt': receipt, 'publication_approved': False}


def prepare_inputs(repository, native_recipe, wasm_recipe, directory, source='base', retained_inputs=None, *, gui_input,
                   core_provider='rust', native_rust_recipe=None, wasm_rust_recipe=None,
                   rust_source='base', rust_retained_inputs=None):
    """Consume existing verified SDK and GUI groups; ordinary capture never fetches source upstream."""
    recipes = input_selection(repository, native_recipe, wasm_recipe, source, retained_inputs)
    rust_recipes = rust_input_selection(repository, core_provider, native_rust_recipe, wasm_rust_recipe,
                                       rust_source, rust_retained_inputs)
    gui_input_selection(repository, gui_input)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        raise ValueError('screenshot input directory must be new')
    directory.mkdir(parents=True)
    origins = {}
    for name, target in [('native', 'linux-x86_64'), ('wasm', 'browser-wasm32')]:
        if source == 'base':
            delivery.fetch_base(repository, recipes[name], directory / name)
            origins[name] = {'origin': 'base', 'recipe': recipes[name]}
        else:
            result = ci.retained_sdk(repository, retained_inputs[name], target, 'all-gui', recipes[name], directory / name)
            origins[name] = {key: result[key] for key in ('origin', 'recipe', 'qualification', 'publication_approved', 'request')}
    delivery.coverage.write_new(directory / 'origins.json', origins)
    if core_provider == 'rust':
        rust_origins = {}
        for name, target in [('native', 'linux-x86_64'), ('wasm', 'browser-wasm32')]:
            if rust_source == 'base':
                ci.fetch_rust_base(repository, rust_recipes[name], directory / (name + '-rust'))
                rust_origins[name] = {'origin': 'base', 'recipe': rust_recipes[name]}
            else:
                result = ci.retained_rust_sdk(repository, rust_retained_inputs[name], target, rust_recipes[name],
                                              directory / (name + '-rust'))
                rust_origins[name] = {key: result[key] for key in
                                     ('origin', 'recipe', 'qualification', 'publication_approved', 'request')}
        delivery.coverage.write_new(directory / 'rust-origins.json', rust_origins)
    gui_origin = fetch_gui_input(repository, gui_input, directory / 'gui')
    delivery.coverage.write_new(directory / 'gui-origin.json', gui_origin)


def hosted_command(native_recipe, wasm_recipe, jobs, *, uid=None, gid=None, core_provider='rust',
                   native_rust_recipe=None, wasm_rust_recipe=None):
    """Ordinary unprivileged Linux runtime; no container or host policy mutation."""
    for recipe in (native_recipe, wasm_recipe):
        if not delivery.SHA.fullmatch(recipe): raise ValueError('exact SDK recipe required')
    uid = os.getuid() if uid is None else uid; gid = os.getgid() if gid is None else gid
    if (type(uid) is not int or type(gid) is not int or not 0 < uid < 2**31 or
            not 0 < gid < 2**31 or type(jobs) is not int or jobs < 1):
        raise ValueError('non-root host account and positive concurrency required')
    recipes = rust_input_selection(None, core_provider, native_rust_recipe, wasm_rust_recipe)
    argv = [sys.executable, '-B', str(ROOT / 'tools/screenshots.py'), 'display-collect',
        '--native-group', 'build/screenshots-inputs/native', '--native-recipe', native_recipe,
        '--wasm-group', 'build/screenshots-inputs/wasm', '--wasm-recipe', wasm_recipe,
        '--gui-group', 'build/screenshots-inputs/gui', '--origins', 'build/screenshots-inputs/origins.json',
        '--work', 'build/screenshots-work', '--output', 'build/gallery', '--jobs', str(jobs),
        '--core-provider', core_provider]
    if core_provider == 'rust':
        argv += ['--native-rust-group', 'build/screenshots-inputs/native-rust', '--native-rust-recipe', recipes['native'],
                 '--wasm-rust-group', 'build/screenshots-inputs/wasm-rust', '--wasm-rust-recipe', recipes['wasm'],
                 '--rust-origins', 'build/screenshots-inputs/rust-origins.json']
    return argv


def capture_environment():
    # Compiler/application/browser children need runtime paths and provenance,
    # never the authenticated transport credential used to acquire inputs.
    names = ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'XDG_RUNTIME_DIR',
             'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')
    return {**{name: os.environ[name] for name in names if name in os.environ},
            'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}


def display_server(argv):
    # This internal Linux child execs in place: the parent's Popen identity and
    # readiness descriptor remain valid, and even a noisy server has bounded logs.
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_DISPLAY_LOG, MAX_DISPLAY_LOG))
    os.execvp('Xvfb', ['Xvfb', *argv])


def display_number(descriptor, child, timeout=20):
    """Read the server-selected display only after its bounded readiness notification."""
    deadline = time.monotonic() + timeout; data = b''
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError('private display exited before readiness')
        if not select.select([descriptor], [], [], min(.1, max(0, deadline - time.monotonic())))[0]:
            continue
        chunk = os.read(descriptor, 32)
        if not chunk:
            raise RuntimeError('private display closed its readiness pipe')
        data += chunk
        if len(data) > 6 or b'\n' in data:
            if not re.fullmatch(rb'(0|[1-9][0-9]{0,4})\n', data) or int(data) > 65535:
                raise RuntimeError('private display returned invalid readiness data')
            return ':' + data[:-1].decode('ascii')
    raise RuntimeError('private display readiness timed out')


def join_display(child, timeout=10):
    """Join this exact server before the enclosing supervised helper exits."""
    if child.poll() is None:
        child.terminate()
    try:
        child.wait(timeout=timeout)
        return 'joined'
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)
        return 'killed-and-joined'


@contextmanager
def private_display(directory, *, startup_timeout=20):
    directory = Path(directory).absolute(); directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    environment = capture_environment()
    environment.update(LIBGL_ALWAYS_SOFTWARE='1', SDL_VIDEODRIVER='x11', REV_SCALE='1', LC_ALL='C.UTF-8')
    receipt = {'schema_version': 1, 'status': 'failed', 'screen': [1280, 900, 24], 'dpi': 96,
               'maximum_log_bytes': MAX_DISPLAY_LOG,
               'cleanup': 'not-started'}
    child = None; reader = writer = None; original = None
    authority = directory / 'Xauthority'
    try:
        for name in ('Xvfb', 'xauth', 'xdpyinfo'):
            if not shutil.which(name): raise ValueError('missing private display prerequisite: ' + name)
        with authority.open('xb'):
            authority.chmod(0o600)
        cookie = secrets.token_hex(16)
        def authorize(display):
            # The server loads the cookie before its display number is known.
            # Add the actual client address after -displayfd chooses the number.
            try:
                command(['xauth', '-f', authority, 'add', display, 'MIT-MAGIC-COOKIE-1', cookie],
                        env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except subprocess.SubprocessError:
                raise RuntimeError('private display authorization setup failed') from None
        authorize(':0')
        reader, writer = os.pipe()
        with (directory / 'xvfb.log').open('xb') as log:
            try:
                child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), 'display-server',
                    '-displayfd', str(writer), '-auth', str(authority),
                    '-nolisten', 'tcp', '-screen', '0', '1280x900x24', '-dpi', '96'],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    pass_fds=(writer,), env=environment, cwd=directory)
                os.close(writer); writer = None
                receipt['pid'] = child.pid; receipt['cleanup'] = 'pending'
                display = display_number(reader, child, startup_timeout)
                authorize(display); environment.update(DISPLAY=display, XAUTHORITY=str(authority))
                result = command(['xdpyinfo'], env=environment, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, timeout=10).stdout
                if (not re.search(r'dimensions:\s+1280x900 pixels', result) or
                        not re.search(r'resolution:\s+96x96 dots per inch', result)):
                    raise RuntimeError('private display geometry or resolution differs')
                receipt['display'] = display; receipt['ready'] = True
                if child.poll() is not None: raise RuntimeError('private display exited before capture')
                yield environment
                if child.poll() is not None: raise RuntimeError('private display exited during capture')
                receipt['status'] = 'passed'
            except BaseException as error:
                original = error; receipt['error'] = str(error)
                raise
            finally:
                if child is not None:
                    try:
                        receipt['cleanup'] = join_display(child)
                        if (directory / 'xvfb.log').stat().st_size >= MAX_DISPLAY_LOG:
                            raise RuntimeError('private display log reached its byte limit')
                    except BaseException as error:
                        receipt.update(status='failed', cleanup_error=str(error))
                        if receipt['cleanup'] == 'pending': receipt['cleanup'] = 'uncertain'
                        if original is not None:
                            original.display_cleanup_error = str(error)
                        else:
                            raise
    finally:
        for descriptor in (reader, writer):
            if descriptor is not None: os.close(descriptor)
        if receipt['cleanup'] in ('joined', 'killed-and-joined', 'not-started') and authority.exists():
            authority.unlink()
        delivery.coverage.write_new(directory / 'display.json', receipt)


def display_collect(argv, directory):
    import windows_graphics
    with private_display(directory) as environment:
        windows_graphics.run_owned(argv, ROOT, Path(directory) / 'collector.log',
                                   environment=environment, timeout=5300)


def run_hosted(argv):
    import windows_graphics
    windows_graphics.run_owned(argv, ROOT, ROOT / 'build/screenshot-hosted.log',
        environment=capture_environment(), timeout=5400)


def verify_gallery(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or {p.name for p in directory.iterdir()} != PUBLIC:
        raise ValueError('complete exact screenshot gallery required')
    for name in PUBLIC:
        archive.checked_file(directory, name)
    for name, maximum in [('screenshots.json', 256 * 1024), ('BUILD.txt', 64 * 1024), ('SHA256SUMS', 4096)]:
        if (directory / name).stat().st_size > maximum:
            raise ValueError('gallery metadata exceeds supported limit')
    manifest = delivery.coverage.load(directory / 'screenshots.json')
    required = {'schema_version', 'kind', 'source_commit', 'source_sha256', 'run_id', 'attempt', 'state',
                'logical_viewport', 'display_dpi', 'display_scale', 'terminal', 'host', 'distribution',
                'recipes', 'dependencies', 'origins', 'gui_group', 'binaries', 'captures', 'tools', 'images'}
    version = manifest.get('schema_version')
    if version == 2:
        required |= {'core_provider', 'rust'}
    if (set(manifest) != required or type(version) is not int or version not in (1, 2) or
            manifest.get('kind') != 'initial-view-gallery' or
            manifest.get('state') != 'fresh initial application' or manifest.get('logical_viewport') != [640, 480] or
            manifest.get('display_dpi') != 96 or manifest.get('display_scale') != 1 or
            set(manifest.get('images', {})) != {name + '.png' for name in BACKENDS}):
        raise ValueError('gallery metadata does not describe all fresh actual surfaces')
    ci.exact_commit(manifest.get('source_commit'))
    if (not delivery.SHA.fullmatch(manifest['source_sha256']) or
            type(manifest['attempt']) is not int or manifest['attempt'] < 1 or
            not isinstance(manifest['run_id'], str) or not manifest['run_id'] or
            set(manifest['recipes']) != {'native', 'wasm'} or set(manifest['dependencies']) != {'native', 'wasm'} or
            manifest['host'].get('target') != 'linux-x86_64' or not manifest['distribution'] or
            not manifest['terminal'] or set(manifest['captures']) != {*BACKENDS, 'browser'} or
            set(manifest['tools']) != {'cmake', 'browser', 'chromedriver', 'xterm'} or
            any(not isinstance(v, str) or not v for v in manifest['tools'].values())):
        raise ValueError('incomplete source, host, input or capture provenance')
    sandbox = manifest['captures'].get('browser', {}).get('sandbox', {})
    if gallery_browser.parse_sandbox({'rows': sandbox.get('rows'), 'evaluation': sandbox.get('evaluation')}) != sandbox:
        raise ValueError('capture browser sandbox evidence differs')
    for name, recipe in manifest['recipes'].items():
        if (not delivery.SHA.fullmatch(recipe) or set(manifest['dependencies'][name]) != set(delivery.store.names(recipe)) or
                any(not delivery.SHA.fullmatch(v) for v in manifest['dependencies'][name].values())):
            raise ValueError('complete exact SDK triplet provenance required')
    if set(manifest['origins']) != {'native', 'wasm'}:
        raise ValueError('both SDK acquisition origins are required')
    for name, origin in manifest['origins'].items():
        if origin.get('origin') not in ('base', 'retained', 'local') or origin.get('recipe') != manifest['recipes'][name]:
            raise ValueError('SDK acquisition origin differs from selected input')
        if origin['origin'] == 'retained':
            request = origin.get('request', {})
            ci.retained_sdk_request(request, request.get('repository'), 'linux-x86_64' if name == 'native' else 'browser-wasm32',
                                    'all-gui', origin['recipe'])
            if origin.get('qualification') != 'unqualified' or origin.get('publication_approved') is not False:
                raise ValueError('retained byte reuse must not grant SDK publication eligibility')
    if version == 2:
        provider = manifest['core_provider']; rust = manifest['rust']
        if (not isinstance(provider, str) or provider not in ('cpp', 'rust') or not isinstance(rust, dict) or
                set(rust) != ({'native', 'wasm'} if provider == 'rust' else set())):
            raise ValueError('gallery requires the selected provider and both Rust target identities')
        fields = {'core_provider', 'rust_sdk_recipe_id', 'rust_compiler_version', 'rust_target',
                  'rust_sdk_manifest_sha256', 'rust_compiler_sha256', 'group_files', 'origin'}
        for name, item in rust.items():
            if not isinstance(item, dict):
                raise ValueError('complete target-matched Rust compiler and retained group provenance required')
            recipe = item.get('rust_sdk_recipe_id')
            if (set(item) != fields or item['core_provider'] != 'rust' or
                    not isinstance(recipe, str) or not delivery.SHA.fullmatch(recipe) or
                    item['rust_target'] != ('x86_64-unknown-linux-gnu' if name == 'native' else 'wasm32-unknown-emscripten') or
                    not isinstance(item['rust_compiler_version'], str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', item['rust_compiler_version']) or
                    any(not isinstance(item[key], str) or not delivery.SHA.fullmatch(item[key]) for key in
                        ('rust_sdk_manifest_sha256', 'rust_compiler_sha256')) or
                    not isinstance(item['group_files'], dict) or
                    set(item['group_files']) != set(ci.module('rust_sdk').group_names(recipe)) or
                    any(not isinstance(value, str) or not delivery.SHA.fullmatch(value) for value in item['group_files'].values())):
                raise ValueError('complete target-matched Rust compiler and retained group provenance required')
            origin = item['origin']
            if (not isinstance(origin, dict) or origin.get('origin') not in ('base', 'retained', 'local') or
                    origin.get('recipe') != recipe):
                raise ValueError('Rust acquisition origin differs from selected input')
            if origin['origin'] == 'retained':
                request = origin.get('request', {})
                ci.retained_rust_request(request, request.get('repository'),
                    'linux-x86_64' if name == 'native' else 'browser-wasm32', recipe)
                if origin.get('qualification') != 'unqualified' or origin.get('publication_approved') is not False:
                    raise ValueError('retained Rust reuse must not grant publication eligibility')
    gui = manifest['gui_group']
    if (set(gui) != {'revision', 'source_tree', 'upstream', 'license', 'redistributable', 'archive_sha256', 'manifest_sha256'} or
            not delivery.OID.fullmatch(gui['revision']) or not delivery.OID.fullmatch(gui['source_tree']) or
            not delivery.SHA.fullmatch(gui['archive_sha256']) or not delivery.SHA.fullmatch(gui['manifest_sha256']) or
            type(gui['redistributable']) is not bool):
        raise ValueError('complete reviewed GUI input provenance required')
    binaries = {*(f'native/gui/foundation-gui-{name}' for name in TARGETS),
                'wasm/gui/gui_web_wasm.js', 'wasm/gui/gui_web_wasm.wasm'}
    if set(manifest['binaries']) != binaries or any(not delivery.SHA.fullmatch(v) for v in manifest['binaries'].values()):
        raise ValueError('every actual native and browser build output must be identified')
    for name in BACKENDS:
        path = directory / (name + '.png'); dimensions = list(png_size(path))
        if (not valid_dimensions(name, *dimensions) or manifest['images'][path.name] !=
                {'sha256': archive.digest(path), 'size': path.stat().st_size, 'dimensions': dimensions}):
            raise ValueError('image bytes or viewport differ from gallery inventory')
        capture = manifest['captures'][name]
        surface = 'browser-viewport' if name in ('hosted-web', 'wasm') else 'application-framebuffer' if name == 'framebuffer' else 'native-window'
        if (capture.get('surface') != surface or [capture.get('width'), capture.get('height')] != dimensions or
                type(capture.get('colors')) is not int or capture['colors'] < 4):
            raise ValueError('actual surface or painted capture provenance differs')
    if (manifest['captures']['hosted-web'].get('mode') != 'hosted' or manifest['captures']['wasm'].get('mode') != 'wasm' or
            not manifest['captures']['hosted-web'].get('geometry') or
            manifest['captures']['hosted-web']['geometry'] != manifest['captures']['wasm'].get('geometry')):
        raise ValueError('independent browser captures require matching initial shared geometry')
    sums = ''.join(archive.digest(directory / name) + '  ' + name + '\n' for name in sorted(PUBLIC - {'SHA256SUMS'}))
    if (directory / 'SHA256SUMS').read_text(encoding='ascii') != sums:
        raise ValueError('gallery checksums differ')
    return manifest


def publish(repository, tag, directory, source_commit, *, execute=False, transport=None):
    delivery.location(repository, tag); ci.exact_commit(source_commit)
    if not tag.startswith('screenshots-'):
        raise ValueError('screenshot release requires its separate tag namespace')
    manifest = verify_gallery(directory)
    if manifest['source_commit'] != source_commit:
        raise ValueError('gallery source differs from release tag')
    directory = Path(directory)
    files = {name: archive.digest(directory / name) for name in sorted(PUBLIC)}
    result = delivery.plan('publish-screenshots', repository, tag=tag, source_commit=source_commit,
                           files=files, lifecycle='immutable prerelease; never Latest')
    if not execute:
        return result
    remote = delivery.Remote(repository, transport)
    def act():
        remote.visible()
        if remote.find(tag, False) is not None or remote.reference(tag, True) is not None:
            raise ValueError('gallery tag or release already exists; never overwrite')
        remote.change('/git/refs', body={'ref': 'refs/tags/' + tag, 'sha': source_commit})
        info = remote.info(remote.change('/releases', body={'tag_name': tag, 'target_commitish': source_commit,
            'name': tag, 'body': 'Fresh initial application views for seven actual backends. See BUILD.txt and screenshots.json.',
            'draft': True, 'prerelease': True, 'make_latest': 'false'}), tag)
        if not info['draft'] or not info['prerelease'] or info['name'] != tag or remote.reference(tag) != source_commit:
            raise ValueError('created gallery must be the exact private draft before uploading')
        remote.wait_find(tag, release_id=info['id'])
        for name in files:
            remote.upload(tag, directory / name)
        current = remote.find(tag); assets = remote.assets(current)
        if current['id'] != info['id'] or not current['draft'] or not current['prerelease'] or set(assets) != set(files):
            raise ValueError('gallery draft lifecycle or complete inventory differs')
        with tempfile.TemporaryDirectory(prefix='gallery-confirm-') as temporary:
            restored = Path(temporary)
            for name in files:
                remote.download(assets[name], restored / name, files[name])
            if verify_gallery(restored) != manifest or verify_gallery(directory) != manifest:
                raise ValueError('gallery changed during publication')
        remote.unchanged(tag, current, assets, source_commit)
        remote.change(f'/releases/{info["id"]}', method='PATCH',
                      body={'draft': False, 'prerelease': True, 'make_latest': 'false'})
        final = remote.find(tag)
        if (final['id'] != info['id'] or final['draft'] or not final['prerelease'] or
                remote.assets(final) != assets or remote.reference(tag) != source_commit):
            raise ValueError('gallery finalization could not be verified')
        remote.not_latest(final)
        return dict(result, execute=True, release_id=final['id'], assets=assets)
    return delivery.run_mutation(remote, act)


def main(argv=None):
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] == 'display-server':
        return display_server(raw_argv[1:])
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='operation', required=True)
    p = sub.add_parser('surfaces'); p.add_argument('--native', type=Path, required=True); p.add_argument('--wasm', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    for operation in ('collect', 'display-collect'):
        p = sub.add_parser(operation)
        for name in ('native-group', 'wasm-group', 'gui-group', 'work', 'output'):
            p.add_argument('--' + name, type=Path, required=True)
        for name in ('native-recipe', 'wasm-recipe'): p.add_argument('--' + name, required=True)
        p.add_argument('--jobs', type=int, default=2)
        p.add_argument('--origins', type=Path)
        p.add_argument('--core-provider', choices=('rust', 'cpp'), default='rust')
        for name in ('native-rust-group', 'wasm-rust-group', 'rust-origins'):
            p.add_argument('--' + name, type=Path)
        for name in ('native-rust-recipe', 'wasm-rust-recipe'):
            p.add_argument('--' + name)
    p = sub.add_parser('verify'); p.add_argument('directory', type=Path)
    p = sub.add_parser('hosted')
    p.add_argument('--repository', required=True); p.add_argument('--native-recipe', required=True)
    p.add_argument('--wasm-recipe', required=True); p.add_argument('--jobs', type=compile_jobs, default='auto')
    p.add_argument('--source', choices=('base', 'retained'), default='base')
    p.add_argument('--gui-input', required=True, help='exact existing GUI group selector as JSON')
    p.add_argument('--retained-inputs', help='exact version-2 native and wasm requests as one JSON object')
    p.add_argument('--core-provider', choices=('rust', 'cpp'), default='rust')
    p.add_argument('--native-rust-recipe', help='exact retained Rust recipe; default is the checked-in Linux recipe')
    p.add_argument('--wasm-rust-recipe', help='exact retained Rust recipe; default is the checked-in Wasm recipe')
    p.add_argument('--rust-source', choices=('base', 'retained'), default='base')
    p.add_argument('--rust-retained-inputs', help='exact native and wasm retained Rust requests as one JSON object')
    p = sub.add_parser('publish'); p.add_argument('directory', type=Path)
    p.add_argument('--repository', required=True); p.add_argument('--tag', required=True)
    p.add_argument('--source-commit', required=True); p.add_argument('--execute', action='store_true')
    p.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args(raw_argv)
    if args.operation == 'surfaces': return surfaces(args.native, args.wasm, args.output)
    if args.operation == 'display-collect':
        return display_collect([sys.executable, '-B', str(Path(__file__).resolve()), 'collect', *raw_argv[1:]],
                               ROOT / 'build/screenshots-display')
    if args.operation == 'collect':
        return collect(args.native_group, args.native_recipe, args.wasm_group, args.wasm_recipe,
                       args.gui_group, args.work, args.output, args.jobs,
                       delivery.coverage.load(args.origins) if args.origins else None,
                       core_provider=args.core_provider, native_rust_group=args.native_rust_group,
                       native_rust_recipe=args.native_rust_recipe, wasm_rust_group=args.wasm_rust_group,
                       wasm_rust_recipe=args.wasm_rust_recipe,
                       rust_origins=delivery.coverage.load(args.rust_origins) if args.rust_origins else None)
    if args.operation == 'verify': return verify_gallery(args.directory)
    if args.operation == 'hosted':
        gui_input = gui_input_selection(args.repository, delivery.parse(args.gui_input))
        retained = delivery.parse(args.retained_inputs) if args.retained_inputs else None
        rust_retained = delivery.parse(args.rust_retained_inputs) if args.rust_retained_inputs else None
        input_selection(args.repository, args.native_recipe, args.wasm_recipe, args.source, retained)
        rust_recipes = rust_input_selection(args.repository, args.core_provider, args.native_rust_recipe,
                                           args.wasm_rust_recipe, args.rust_source, rust_retained)
        argv = hosted_command(args.native_recipe, args.wasm_recipe, args.jobs, core_provider=args.core_provider,
                              native_rust_recipe=rust_recipes.get('native'), wasm_rust_recipe=rust_recipes.get('wasm'))
        gallery_browser.preflight(ROOT / 'build/browser-preflight')
        prepare_inputs(args.repository, args.native_recipe, args.wasm_recipe, ROOT / 'build/screenshots-inputs',
                       args.source, retained, gui_input=gui_input, core_provider=args.core_provider,
                       native_rust_recipe=rust_recipes.get('native'), wasm_rust_recipe=rust_recipes.get('wasm'),
                       rust_source=args.rust_source, rust_retained_inputs=rust_retained)
        run_hosted(argv)
        return verify_gallery(ROOT / 'build/gallery')
    result = publish(args.repository, args.tag, args.directory, args.source_commit, execute=args.execute)
    try:
        delivery.coverage.write_new(args.receipt, result)
    except BaseException as error:
        if args.execute: raise delivery.DeliveryError('gallery receipt failed after execution; reconcile remote state', True) from error
        raise
    return result


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({'ok': False, 'uncertain': bool(getattr(error, 'uncertain', False)), 'error': str(error)}), file=sys.stderr)
        raise SystemExit(1)
