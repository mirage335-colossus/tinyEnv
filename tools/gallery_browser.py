#!/usr/bin/env python3
"""Qualify an installed Linux browser without changing host security policy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import sys
import time
from urllib.parse import quote


class BrowserPrerequisiteError(ValueError):
    def __init__(self, message, *, details=None):
        super().__init__(message)
        self.details = details


def executable(names):
    """Select installed executables explicitly; never invoke a download manager."""
    for name in names:
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve(strict=True))
    raise BrowserPrerequisiteError('Missing installed executable: ' + ', '.join(names))


def browser_environment():
    """Only local browser prerequisites cross into untrusted child processes."""
    names = ('PATH', 'HOME', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL', 'LC_CTYPE',
             'TZ', 'DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR')
    result = {name: os.environ[name] for name in names if name in os.environ}
    result.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    return result


def chrome_options(profile):
    from selenium.webdriver import ChromeOptions
    profile = Path(profile).absolute()
    if profile.exists() or profile.is_symlink() or not profile.parent.is_dir():
        raise BrowserPrerequisiteError('A new owned browser profile path is required')
    options = ChromeOptions()
    # Ubuntu's installed Chrome has a distribution-supplied AppArmor policy.
    # Prefer it to an unrelated browser copy that lacks that host prerequisite.
    options.binary_location = executable(('google-chrome', 'google-chrome-stable', 'chromium'))
    for argument in ('--headless=new', '--disable-dev-shm-usage', '--force-device-scale-factor=1',
                     '--no-first-run', '--no-default-browser-check', '--lang=en-US',
                     '--user-data-dir=' + str(profile)):
        options.add_argument(argument)
    return options


def chrome_service(log_path):
    from selenium.webdriver.chrome.service import Service
    path = Path(log_path).absolute()
    driver = executable(('chromedriver',))
    # Reserve our file before the driver opens it; existing diagnostic bytes are
    # never silently replaced. The caller owns its enclosing output directory.
    with path.open('xb'):
        pass
    # Selenium 4.8.3 silently ignores log_output. This driver option is supported
    # by both that distribution release and current Selenium Service APIs.
    return Service(executable_path=driver, service_args=['--log-path=' + str(path)],
                   env=browser_environment())


def checked_arguments(arguments):
    forbidden = {'--no-sandbox', '--disable-setuid-sandbox', '--disable-namespace-sandbox',
                 '--disable-seccomp-filter-sandbox', '--disable-gpu-sandbox',
                 '--single-process', '--no-zygote'}
    if (not isinstance(arguments, list) or not arguments or len(arguments) > 256 or
            any(not isinstance(v, str) or len(v) > 8192 for v in arguments)):
        raise BrowserPrerequisiteError('Invalid actual browser command line')
    denied = sorted({v.split('=', 1)[0] for v in arguments} & forbidden)
    if denied:
        raise BrowserPrerequisiteError('Browser sandbox-disabling arguments: ' + ', '.join(denied))
    return arguments


def parse_sandbox(state):
    """Accept Chromium's old and current Linux diagnostic table layouts."""
    if (not isinstance(state, dict) or set(state) != {'rows', 'evaluation'} or
            not isinstance(state['rows'], list) or not 1 <= len(state['rows']) <= 32 or
            not isinstance(state['evaluation'], str) or len(state['evaluation']) > 256):
        raise BrowserPrerequisiteError('Missing or malformed Chromium sandbox diagnostics', details=state)
    rows = {}
    for pair in state['rows']:
        if (not isinstance(pair, list) or len(pair) != 2 or
                any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in pair)):
            raise BrowserPrerequisiteError('Malformed Chromium sandbox row', details=state)
        key, value = (' '.join(value.split()).casefold() for value in pair)
        if key in rows:
            raise BrowserPrerequisiteError('Duplicate Chromium sandbox row', details=state)
        rows[key] = value
    layer = rows.get('layer 1 sandbox')
    old_namespace, old_suid = rows.get('namespace sandbox'), rows.get('suid sandbox')
    if layer is None:
        if old_namespace not in ('yes', 'no') or old_suid not in ('yes', 'no'):
            raise BrowserPrerequisiteError('Unrecognized first sandbox layer', details=state)
        layer = 'namespace' if old_namespace == 'yes' else 'suid' if old_suid == 'yes' else 'none'
    elif ((old_namespace is not None and old_namespace != ('yes' if layer == 'namespace' else 'no')) or
          (old_suid is not None and old_suid != ('yes' if layer == 'suid' else 'no'))):
        raise BrowserPrerequisiteError('Conflicting first sandbox layer', details=state)
    required = ('pid namespaces', 'network namespaces', 'seccomp-bpf sandbox')
    if (layer not in ('namespace', 'suid') or any(rows.get(key) != 'yes' for key in required) or
            ' '.join(state['evaluation'].split()) != 'You are adequately sandboxed.'):
        raise BrowserPrerequisiteError('Chromium has no verified namespace and syscall sandbox', details=state)
    return {'first_layer': layer, 'pid_namespaces': True, 'network_namespaces': True,
            'seccomp_bpf': True, 'seccomp_tsync': rows.get('seccomp-bpf sandbox supports tsync') == 'yes',
            'rows': state['rows'], 'evaluation': state['evaluation']}


def sandbox_status(browser):
    checked_arguments(browser.execute_cdp_cmd('Browser.getBrowserCommandLine', {})['arguments'])
    browser.get('chrome://sandbox')
    deadline = time.monotonic() + 10
    while True:
        if browser.current_url.rstrip('/') != 'chrome://sandbox':
            raise BrowserPrerequisiteError('Browser did not open its own sandbox diagnostic page')
        state = browser.execute_script('''return {
            rows:[...document.querySelectorAll('#sandbox-status tr')].map(row=>
                [...row.querySelectorAll('td')].map(cell=>cell.textContent)),
            evaluation:document.querySelector('#evaluation')?.textContent || ''};''')
        if state.get('rows') and state.get('evaluation'):
            return parse_sandbox(state)
        if time.monotonic() >= deadline:
            raise BrowserPrerequisiteError('Chromium sandbox diagnostics did not load', details=state)
        time.sleep(.1)


def host_policy():
    paths = {'apparmor': '/proc/self/attr/current',
             'apparmor_restrict_unprivileged_userns': '/proc/sys/kernel/apparmor_restrict_unprivileged_userns',
             'unprivileged_userns_clone': '/proc/sys/kernel/unprivileged_userns_clone',
             'max_user_namespaces': '/proc/sys/user/max_user_namespaces'}
    result = {'system': platform.system(), 'release': platform.release(),
              'uid': os.geteuid() if hasattr(os, 'geteuid') else None}
    for key, path in paths.items():
        try:
            with open(path, encoding='utf-8') as stream:
                result[key] = stream.read(1024).strip()
        except OSError as error:
            result[key] = 'unavailable: ' + type(error).__name__
    return result


def render_probe(browser, output):
    html = '''<!doctype html><meta charset="utf-8"><title>Browser prerequisite</title>
    <style>html,body{margin:0}#viewport{position:relative;width:160px;height:96px}
    canvas{position:absolute;left:0;top:0}span{position:absolute;left:8px;top:8px;
    font:16px sans-serif;color:white}</style><div id="viewport"><canvas width="160"
    height="96"></canvas><span>Ready</span></div><script>
    let c=document.querySelector('canvas').getContext('2d');
    c.fillStyle='rgb(16,64,128)';c.fillRect(0,0,160,96);</script>'''
    browser.get('data:text/html;charset=utf-8,' + quote(html))
    state = browser.execute_async_script('''const done=arguments[arguments.length-1];
        document.fonts.ready.then(()=>{const c=document.querySelector('canvas');
            const b=document.querySelector('#viewport').getBoundingClientRect();
            done({size:[b.width,b.height],pixel:[...c.getContext('2d').getImageData(120,80,1,1).data],
                  text:document.querySelector('span').textContent,fonts:document.fonts.status});});''')
    if state != {'size': [160, 96], 'pixel': [16, 64, 128, 255], 'text': 'Ready', 'fonts': 'loaded'}:
        raise BrowserPrerequisiteError('Actual browser rendering prerequisite failed', details=state)
    image = browser.find_element('id', 'viewport').screenshot_as_png
    if (not isinstance(image, bytes) or not 24 <= len(image) <= 1024 * 1024 or
            image[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' or
            struct.unpack('>II', image[16:24]) != (160, 96)):
        raise BrowserPrerequisiteError('Browser did not capture the rendered viewport')
    with (output / 'render.png').open('xb') as stream:
        stream.write(image)
    return {**state, 'png_sha256': hashlib.sha256(image).hexdigest(), 'png_size': len(image)}


def versions(capabilities):
    browser = capabilities.get('browserVersion', '')
    driver = capabilities.get('chrome', {}).get('chromedriverVersion', '')
    if (capabilities.get('browserName') != 'chrome' or not isinstance(browser, str) or
            not isinstance(driver, str) or len(browser) > 128 or len(driver) > 512 or
            not re.match(r'^\d+\.', browser) or not re.match(r'^\d+\.', driver) or
            browser.split('.')[0] != driver.split('.')[0]):
        raise BrowserPrerequisiteError('Installed Chrome and ChromeDriver versions do not match')
    return {'browser': browser, 'driver': driver}


def _probe(output):
    receipt = {'schema_version': 1, 'status': 'failed', 'host_policy': host_policy()}
    try:
        if sys.platform != 'linux' or not hasattr(os, 'geteuid') or os.geteuid() == 0:
            raise BrowserPrerequisiteError('Browser preflight requires an unprivileged Linux account')
        from selenium import webdriver
        options = chrome_options(output / 'profile')
        service = chrome_service(output / 'chromedriver.log')
        receipt['executables'] = {'browser': options.binary_location, 'driver': service.path}
        try:
            with webdriver.Chrome(service=service, options=options) as browser:
                browser.set_page_load_timeout(25)
                browser.set_script_timeout(10)
                receipt['versions'] = versions(browser.capabilities)
                receipt['sandbox'] = sandbox_status(browser)
                receipt['render'] = render_probe(browser, output)
            receipt['status'] = 'passed'
        finally:
            service.stop()
    except Exception as error:
        receipt['status'] = 'failed'
        receipt['error'] = (type(error).__name__ + ': ' + str(error))[:4096]
        if isinstance(error, BrowserPrerequisiteError) and error.details is not None:
            details = json.dumps(error.details, ensure_ascii=True)
            receipt['details'] = details[:8192]
        raise
    finally:
        with (output / 'preflight.json').open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
            stream.write('\n')
    return receipt


def preflight(output_dir, timeout=90):
    """Own all browser descendants and bound prerequisite execution before builds."""
    import windows_graphics
    output = Path(output_dir).absolute()
    if type(timeout) not in (int, float) or not 1 <= timeout <= 120:
        raise ValueError('Browser preflight timeout must be between 1 and 120 seconds')
    if output.exists() or output.is_symlink():
        raise ValueError('Browser preflight output must be a new owned directory')
    output.mkdir(parents=True)
    windows_graphics.run_owned([sys.executable, '-B', str(Path(__file__).resolve()),
        '_probe', '--output', str(output)], output, output / 'console.log', timeout=timeout,
        max_bytes=2 * 1024 * 1024, environment=browser_environment())
    path = output / 'preflight.json'
    if path.stat().st_size > 64 * 1024:
        raise BrowserPrerequisiteError('Oversized browser preflight receipt')
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if receipt.get('schema_version') != 1 or receipt.get('status') != 'passed':
        raise BrowserPrerequisiteError('Browser prerequisite did not pass')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=['preflight', '_probe'], default='preflight')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = _probe(args.output) if args.action == '_probe' else preflight(args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
