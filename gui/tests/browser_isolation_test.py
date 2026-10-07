#!/usr/bin/env python3
"""Qualify the production opaque renderer boundary in an actual browser.

The hostile module is assembled with the production graph and its correct hash.
Its claims establish only that probes ran; independent parent and HTTP canaries
establish denied effects. Own-frame navigation is recorded as an allowed request.
"""
import argparse
import base64
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

from browser_test import Browser, ChromiumBrowser, browser_workspace, PROCESS_TREE_PATH

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / 'tools/browser_bundle.py'
ATTACK = Path(__file__).with_name('browser_isolation_attack.mjs')
ASSETS = ('browser_embedding.mjs', 'browser_client.mjs', 'browser_services.mjs',
          'browser_lifecycle.mjs', 'browser_limits.mjs', 'browser_presenter.mjs',
          'renderer_channel.mjs', 'renderer_dom.mjs', 'renderer_frame.mjs',
          'renderer_child_bundle.mjs', 'file_services.mjs', 'style.css')
PROTOCOL_CASES = ('initial-navigation', 'wrong-nonce', 'extra-ports', 'duplicate-ready', 'duplicate-bound',
                  'duplicate-request', 'oversized-request', 'stale-message-generation',
                  'stale-key-generation', 'queue-bounds', 'forbidden-service',
                  'forbidden-file', 'forbidden-poll', 'forbidden-resize',
                  'forbidden-close', 'forbidden-transport')
PROBES = ('parent-dom', 'parent-global', 'parent-token', 'parent-storage', 'parent-cookie',
          'child-local-storage', 'child-session-storage', 'child-cookie', 'child-indexed-db',
          'fetch', 'xhr', 'websocket', 'image', 'script', 'stylesheet', 'css-image',
          'css-font', 'worker', 'nested-frame', 'object', 'form', 'popup',
          'parent-navigation', 'download', 'clipboard', 'file-picker')
SERVICE_CASES = ('provider-replacement', 'provider-dispose', 'provider-pagehide',
                 'file-read-replacement', 'file-read-dispose', 'file-read-pagehide',
                 'file-import-replacement', 'file-import-dispose',
                 'download-revocation', 'download-valid-cleanup')
INFRASTRUCTURE_CASES = ('concurrent-frontends',)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bundle_metadata(path):
    source = Path(path).read_text(encoding='utf-8')
    result = {}
    for name in ('CHILD_SCRIPT', 'CHILD_SCRIPT_SHA256', 'CHILD_CSP', 'CHILD_SANDBOX',
                 'CHILD_PROTOCOL', 'CHILD_STYLE', 'CHILD_INPUTS'):
        match = re.search(r'^export const ' + name + r'=(.*);$', source, re.MULTILINE)
        if not match:
            raise ValueError('Missing generated child metadata: ' + name)
        result[name] = json.loads(match[1])
    calculated = base64.b64encode(hashlib.sha256(result['CHILD_SCRIPT'].encode()).digest()).decode()
    if calculated != result['CHILD_SCRIPT_SHA256']:
        raise ValueError('Child script hash does not match its actual bytes')
    if result['CHILD_SANDBOX'] != 'allow-scripts' or result['CHILD_PROTOCOL'] != 'foundation-renderer-v1':
        raise ValueError('Unexpected production child policy')
    if "'sha256-" + calculated + "'" not in result['CHILD_CSP']:
        raise ValueError('Child CSP does not admit the actual exact script')
    return result


HARNESS = r'''
import {createEmbeddedFrontend} from './browser_embedding.mjs';
import {executeService} from './browser_services.mjs';
import {CHILD_SCRIPT_SHA256,CHILD_CSP,CHILD_SANDBOX,CHILD_PROTOCOL} from './renderer_child_bundle.mjs';
const scenario=SCENARIO,marker=MARKER,canaryURL=CANARY;
const canary='parent-'+marker,secret='transport-'+marker;
globalThis.foundationSecurityCanary=canary;
globalThis.foundationTransportToken=secret;
document.querySelector('#foundation-security-canary').textContent=canary;
localStorage.setItem('foundation-security-canary',canary);
document.cookie='foundation-security-canary='+encodeURIComponent(canary)+'; SameSite=Strict';
let frontend,secondFrontend,secondReady=false,secondReleases=0,sourceWindow,service=null,releaseRead=null,releaseProvider=null,releaseImport=null,releaseQueue=null;
let witness=0,ack='0',ready=false,closed=false,releases=0,report=null,siblingReport=null,siblingBeforeReady=null;
const dispatched=[],statuses=[],providerSignals=[],createdURLs=[],revokedURLs=[],clickedURLs=[];
const font={size:14,bold:false,tone:0};
const snapshot=()=>({revision:ack,title:'Isolation fixture',palette:{},width:640,height:480,scale:1,
 pages:[],activePage:'',widgets:[{key:{id:'attack.witness',generation:'1'},kind:2,
 bounds:[0,0,160,40],clip:[0,0,160,40],visible:true,enabled:true,inModal:true,
 label:'Witness',text:'',font,help:'',accessibleName:'Witness',scroll:null}],
 measurements:[],keyBindings:[],focus:null,popup:null,closed:false});
const state=(sequence=ack,transfer)=>({epoch:'trusted-'+marker,ack:String(sequence),snapshot:snapshot(),service,
 error:'',...(transfer?{transfer}:{}),tokenCanary:secret});
const prompt=(title='Original provider')=>({id:'same-service',kind:2,title,value:'original',byteLimit:'65536'});
const exporting=()=>({id:'same-service',kind:6,title:'Original export',value:'',byteLimit:'65536',byteSize:'3',chunked:true});
const importing=()=>({id:'same-service',kind:5,title:'Replacement import',value:'',byteLimit:'65536',chunked:true});
if(scenario.startsWith('provider-'))service=prompt();
if(scenario.startsWith('file-read-'))service=exporting();
if(scenario.startsWith('file-import-'))service=importing();
if(scenario.startsWith('download-'))service={...exporting(),chunked:false,value:'abc'};
const originalClick=HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click=function(){clickedURLs.push(this.href);return originalClick.call(this);};
const serviceHost={document,Blob,AbortController,setTimeout:globalThis.setTimeout.bind(globalThis),
 URL:{createObjectURL(blob){const url=URL.createObjectURL(blob);createdURLs.push(url);
   if(scenario==='download-revocation')frontend.close();return url;},
 revokeObjectURL(url){revokedURLs.push(url);URL.revokeObjectURL(url);}},
 executeService(request,host){
   providerSignals.push({title:request.title,signal:host.signal,descriptorFrozen:Object.isFrozen(request)});
   if(scenario.startsWith('provider-')){
     if(request.title==='Replacement provider')return new Promise(()=>{});
     return new Promise(resolve=>{releaseProvider=()=>resolve({type:'service',id:request.id,status:'success',value:'LATE',error:''});});
   }
   return executeService(request,host);
 }};
const exchange=async envelope=>{
 const operation=JSON.parse(JSON.stringify(envelope.operation));
 if(!['poll','resize'].includes(operation.type))dispatched.push(operation);
 if(operation.type==='activate'){
   if(scenario==='queue-bounds'&&witness===1){await new Promise(resolve=>releaseQueue=resolve);service=prompt('Late queue service');}
   witness+=1;
 }
 if(operation.type==='fileRead'){
   await new Promise(resolve=>releaseRead=resolve);
   if(scenario==='file-read-replacement')service=importing();
   ack=envelope.seq;
   return state(ack,{id:'same-service',offset:'0',total:'3',hex:'616263'});
 }
 if(['service','fileFinish'].includes(operation.type))service=null;
 ack=envelope.seq;return state();
};
addEventListener('message',event=>{
 if(event.data?.protocol!=='foundation-test-attack-report-v1')return;
 if(event.source===sourceWindow&&event.data.report?.marker===marker){
  report=event.data.report;
  if(typeof report.receipt==='string')event.source.postMessage({protocol:'foundation-test-attack-report-ack-v1',marker,receipt:report.receipt},'*');
 }
 if(event.data.report?.scenario==='sibling'&&event.data.report.marker===marker+'-sibling'){
  siblingReport=event.data.report;if(siblingBeforeReady===null)siblingBeforeReady=!ready;
 }
});
frontend=createEmbeddedFrontend({mount:document.querySelector('#mount'),initialState:state(),exchange,
 release(){releases+=1;closed=true;},status(message,failed){statuses.push({message,failed:!!failed});},
 serviceHost,startupTimeout:1500,pollingInterval:25});
sourceWindow=frontend.frame.contentWindow;
const framePolicy={sandbox:frontend.frame.getAttribute('sandbox'),srcdoc:!!frontend.frame.srcdoc,
 csp:CHILD_CSP,hash:CHILD_SCRIPT_SHA256,protocol:CHILD_PROTOCOL};
frontend.ready.then(()=>{ready=true;},error=>{statuses.push({message:error.message,startup:true});});
if(scenario==='concurrent-frontends'){
 const mount=document.createElement('div');mount.style.cssText='width:640px;height:480px';document.body.append(mount);
 secondFrontend=createEmbeddedFrontend({mount,initialState:{...state(),epoch:'second-'+marker},
  exchange:async envelope=>({...state(envelope.seq),epoch:'second-'+marker}),
  release(){secondReleases+=1;},status(message){statuses.push({message,second:true});},startupTimeout:1500});
 secondFrontend.ready.then(()=>secondReady=true,error=>statuses.push({message:error.message,second:true}));
}
if(scenario==='sibling'){
 const generation=/name="foundation-channel" content="([^"]+)"/.exec(frontend.frame.srcdoc)[1];
 const frame=document.createElement('iframe');frame.sandbox='allow-scripts';
 frame.srcdoc='<!doctype html><meta name="foundation-channel" content="'+generation+'"><script>'+SIBLING_SOURCE+'<'+ '/script>';
 document.body.append(frame);
}
const initialURL=location.href;
const read=()=>({scenario,marker,ready,secondReady,secondReleases,secondFramePresent:!!secondFrontend?.frame.isConnected,
 secondSandbox:secondFrontend?.frame.getAttribute('sandbox'),closed,releases,report,siblingReport,siblingBeforeReady,witness,ack,
 dispatched,statuses,framePolicy,framePresent:frontend.frame.isConnected,
 dom:document.querySelector('#foundation-security-canary')?.textContent,
 global:foundationSecurityCanary,token:foundationTransportToken,
 storage:localStorage.getItem('foundation-security-canary'),cookie:document.cookie,
 initialURL,currentURL:location.href,windowCount:globalThis.length,
 parentModuleMarker:document.documentElement.getAttribute('data-foundation-attack-dom-module'),
 parentFrameMarker:document.documentElement.getAttribute('data-foundation-attack-module'),
 providers:providerSignals.map(item=>({title:item.title,aborted:item.signal.aborted,descriptorFrozen:item.descriptorFrozen})),
 createdURLs,revokedURLs,clickedURLs,dialogs:document.querySelectorAll('dialog[open]').length});
globalThis.foundationIsolationFixture={read,close(){frontend.close();secondFrontend?.close();},pagehide(){dispatchEvent(new PageTransitionEvent('pagehide',{persisted:false}));},
 replaceProvider(){service={...prompt('Replacement provider'),value:'changed'};},
 replaceImport(){service={...importing(),title:'Replacement changed import'};},
 finishRead(){releaseRead?.();},finishProvider(){releaseProvider?.();},finishQueue(){releaseQueue?.();},
 beginImport(){
  const input=document.querySelector('dialog input[type=file]');
  const file=new File(['abc'],'selected.txt',{type:'text/plain'});
  Object.defineProperty(file,'slice',{value:()=>({arrayBuffer:()=>new Promise(resolve=>releaseImport=()=>resolve(new TextEncoder().encode('abc').buffer))})});
  const transfer=new DataTransfer();transfer.items.add(file);input.files=transfer.files;
  input.closest('form').requestSubmit();
 },finishImport(){releaseImport?.();},
 clickDownload(){document.querySelector('dialog form').requestSubmit();},
 addSibling(source){const frame=document.createElement('iframe');frame.sandbox='allow-scripts';frame.srcdoc='<!doctype html><script>'+source+'<'+ '/script>';document.body.append(frame);return frame;},
 generation(){return /name="foundation-channel" content="([^"]+)"/.exec(frontend.frame.srcdoc)?.[1];},
 async control(){const url=new URL(canaryURL);url.searchParams.set('marker',marker);url.searchParams.set('kind','positive-control');await fetch(url);document.documentElement.setAttribute('data-fixture-control-done','true');return true;},
 downloadControl(){const url=URL.createObjectURL(new Blob(['trusted download positive control'],{type:'text/plain'}));
  const link=document.createElement('a');link.href=url;link.download='control-'+marker+'.txt';document.body.append(link);originalClick.call(link);link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
};
'''


class CanaryServer(http.server.ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, root):
        super().__init__(('127.0.0.1', 0), CanaryHandler)
        self.root = root
        self.events = []
        self.events_lock = threading.Lock()

    @property
    def origin(self):
        return 'http://127.0.0.1:' + str(self.server_address[1])

    def hits(self, marker):
        with self.events_lock:
            return [event.copy() for event in self.events if event['marker'] == marker]


class CanaryHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length > 1024 * 1024:
            self.send_error(413)
            return
        self.rfile.read(length)
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == '/canary':
            query = urllib.parse.parse_qs(parsed.query)
            with self.server.events_lock:
                self.server.events.append({'marker': query.get('marker', [''])[0],
                    'kind': query.get('kind', [''])[0], 'method': self.command,
                    'path': self.path, 'time_monotonic': time.monotonic()})
            data = b'<!doctype html><title>Navigation canary</title><p>Observed request</p>'
            content_type = 'text/html'
        else:
            relative = Path(urllib.parse.unquote(parsed.path).lstrip('/'))
            path = self.server.root / relative
            if not relative.parts or '..' in relative.parts or path.is_symlink() or not path.is_file():
                self.send_error(404)
                return
            data = path.read_bytes()
            content_type = 'text/javascript' if path.suffix == '.mjs' else 'text/html' if path.suffix == '.html' else 'text/css'
        self.send_response(200)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)


def node_source(node, name, options):
    source = 'import {' + name + '} from ' + json.dumps(ATTACK.resolve().as_uri()) + ';process.stdout.write(' + name + '(JSON.parse(process.argv[1])));'
    return subprocess.run([node, '--input-type=module', '-e', source, json.dumps(options)],
                          check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=15, cwd=ROOT).stdout


def prepare_case(args, directory, name, origin, generator):
    directory.mkdir()
    for asset in ASSETS:
        shutil.copyfile(args.assets / asset, directory / asset)
    marker = 'actual-' + name
    malicious = name in ('authority', 'own-navigation', 'sibling', *PROTOCOL_CASES)
    if malicious:
        scenario = name
        source = node_source(args.node, 'maliciousRendererSource',
            {'canaryURL': origin + '/canary', 'marker': marker, 'scenario': scenario})
        (directory / 'renderer_frame.mjs').write_text(source, encoding='utf-8')
        with (directory / 'renderer_dom.mjs').open('a', encoding='utf-8') as stream:
            stream.write('\n// Test-only hostile module top-level effect.\n'
                'document.documentElement.setAttribute("data-foundation-attack-dom-module",' + json.dumps(marker) + ');\n'
                'globalThis.foundationSecurityCanary=' + json.dumps(marker) + ';\n'
                'try{parent.document.querySelector("#foundation-security-canary").textContent=' + json.dumps(marker) + ';}catch{}\n')
        generator.generate(directory, directory / 'renderer_child_bundle.mjs')
    metadata = bundle_metadata(directory / 'renderer_child_bundle.mjs')
    sibling_source = node_source(args.node, 'siblingAttackSource', {'generation':'from-meta','marker':marker+'-sibling'}) if name == 'sibling' else ''
    harness = (HARNESS.replace('SCENARIO', json.dumps(name)).replace('MARKER', json.dumps(marker))
               .replace('CANARY', json.dumps(origin + '/canary')).replace('SIBLING_SOURCE',json.dumps(sibling_source)))
    (directory / 'harness.mjs').write_text(harness, encoding='utf-8')
    sibling_hash = " 'sha256-"+base64.b64encode(hashlib.sha256(sibling_source.encode()).digest()).decode()+"'" if sibling_source else ''
    policy = ("default-src 'none'; script-src 'self' 'sha256-" + metadata['CHILD_SCRIPT_SHA256'] + "'"+sibling_hash+"; "
              "connect-src 'self'; frame-src 'self'; style-src 'unsafe-inline'; img-src data:; object-src 'none'; base-uri 'none'; form-action 'none'")
    from html import escape
    html = ('<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + escape(policy, quote=True) + '">'
            '<title>Isolation qualification</title></head><body><p id="foundation-security-canary"></p>'
            '<div id="mount" style="width:640px;height:480px"></div><script type="module" src="./harness.mjs"></script></body></html>')
    (directory / 'index.html').write_text(html, encoding='utf-8')
    return marker, metadata, policy


def read(browser):
    browser.root()
    return browser.script('return globalThis.foundationIsolationFixture?.read();')


def wait_for(browser, expression):
    browser.root()
    browser.wait('return Boolean(globalThis.foundationIsolationFixture && (' + expression + '));')


def run_command(browser, command):
    browser.root()
    browser.script('globalThis.foundationIsolationFixture.' + command + ';')


def stable_canaries(observed, marker, initial_url):
    expected = 'parent-' + marker
    for field in ('dom', 'global', 'storage'):
        if observed[field] != expected:
            raise AssertionError('Hostile renderer changed parent ' + field)
    if observed['token'] != 'transport-' + marker or observed['cookie'] != 'foundation-security-canary=' + expected:
        raise AssertionError('Hostile renderer changed parent cookie/token canary')
    if observed['currentURL'] != initial_url or observed['parentModuleMarker'] or observed['parentFrameMarker']:
        raise AssertionError('Hostile renderer evaluated or navigated in parent document')
    if observed['framePolicy']['sandbox'] != 'allow-scripts' or not observed['framePolicy']['srcdoc']:
        raise AssertionError('Actual production iframe policy differs')


def qualify_attack(browser, server, name, marker, url):
    wait_for(browser, 'foundationIsolationFixture.read().report?.payloadRan')
    if name in ('initial-navigation', 'wrong-nonce', 'extra-ports', 'duplicate-bound'):
        wait_for(browser, '!foundationIsolationFixture.read().framePresent')
    else:
        wait_for(browser, 'foundationIsolationFixture.read().report?.witnessAccepted')
        if name not in ('authority', 'sibling', 'duplicate-ready', 'stale-key-generation'):
            wait_for(browser, '!foundationIsolationFixture.read().framePresent')
    if name in ('authority', 'sibling', 'duplicate-ready', 'stale-key-generation'):
        wait_for(browser, 'foundationIsolationFixture.read().report?.complete')
    observed = read(browser)
    report = observed['report']
    if not report['moduleRan'] or not report['rendererDOMModuleRan'] or not report['payloadRan']:
        raise AssertionError('Hostile top-level module and payload execution were not both observed')
    if report.get('error'):
        raise AssertionError('Hostile probe setup failed: ' + report['error'])
    if name=='duplicate-bound' and not report['witnessAccepted']:
        raise AssertionError('Duplicate-bound rejection lacked an acknowledged benign witness')
    stable_canaries(observed, marker, url)
    expected = 0 if name in ('initial-navigation', 'wrong-nonce', 'extra-ports') else 1
    if len(observed['dispatched']) != expected + (1 if name == 'queue-bounds' else 0):
        raise AssertionError('Hostile protocol changed trusted operation dispatch: ' + str(observed['dispatched']))
    if any(operation['type'] != 'activate' for operation in observed['dispatched']):
        raise AssertionError('Hostile child acquired a service/transport capability')
    if observed['createdURLs'] or observed['clickedURLs'] or observed['providers'] or observed['dialogs']:
        raise AssertionError('Hostile child caused a privileged parent effect')
    if name == 'stale-key-generation':
        wait_for(browser, 'foundationIsolationFixture.read().report?.results.some(result=>result.id==="2"&&!result.ok)')
        observed = read(browser)
        if not observed['framePresent'] or observed['witness'] != 1:
            raise AssertionError('Stale ordinary intent was not rejected without losing the live channel')
    if name == 'authority' or name == 'sibling':
        attempted = {probe['name'] for probe in report['attempts'] if probe['attempted']}
        if not set(PROBES).issubset(attempted):
            raise AssertionError('Authority probes omitted: ' + str(set(PROBES) - attempted))
        if observed['windowCount'] != (2 if name == 'sibling' else 1):
            raise AssertionError('Hostile renderer changed parent window/frame canary')
    if name == 'queue-bounds':
        if not any('queue' in item['message'].lower() for item in observed['statuses']):
            raise AssertionError('Bounded queue rejection did not report a useful host error')
        run_command(browser, 'finishQueue()')
        # The operation first dispatched while authorized can finish. Revocation must
        # prevent every subsequent queued dispatch and parent state acceptance.
        browser.wait('return foundationIsolationFixture.read().witness===2;')
        later = read(browser)
        if len(later['dispatched']) != 2 or later['framePresent'] or later['releases'] != 1 or later['providers'] or later['dialogs']:
            raise AssertionError('Queue work continued after channel revocation')
        observed = later
    if name in ('own-navigation','initial-navigation'):
        hits = server.hits(marker)
        if not any(event['kind'] == name for event in hits):
            raise AssertionError('Allowed self-navigation positive observation was missing')
        if observed['framePresent'] or observed['releases'] != 1:
            raise AssertionError('Renderer self-navigation did not revoke its production channel')
    elif server.hits(marker):
        raise AssertionError('Child resource or authority probe reached the canary server: ' + str(server.hits(marker)))
    if observed['framePresent']:
        run_command(browser, 'close()')
    wait_for(browser, 'foundationIsolationFixture.read().releases===1')
    observed['network_events'] = server.hits(marker)
    return observed


def qualify_service(browser, name, marker, url):
    wait_for(browser, 'foundationIsolationFixture.read().ready')
    wait_for(browser, 'foundationIsolationFixture.read().providers.length===1')
    if name.startswith('provider-'):
        if name.endswith('replacement'):
            run_command(browser, 'replaceProvider()')
            wait_for(browser, 'foundationIsolationFixture.read().providers.length===2')
        elif name.endswith('dispose'):
            run_command(browser, 'close()')
        else:
            run_command(browser, 'pagehide()')
        run_command(browser, 'finishProvider()')
    elif name.startswith('file-read-'):
        wait_for(browser, 'foundationIsolationFixture.read().dispatched.some(x=>x.type==="fileRead")')
        if name.endswith('dispose'):
            run_command(browser, 'close()')
        elif name.endswith('pagehide'):
            run_command(browser, 'pagehide()')
        run_command(browser, 'finishRead()')
        if name.endswith('replacement'):
            wait_for(browser, 'foundationIsolationFixture.read().providers.length===2')
    elif name.startswith('file-import-'):
        wait_for(browser, 'foundationIsolationFixture.read().dialogs===1')
        run_command(browser, 'beginImport()')
        wait_for(browser, 'foundationIsolationFixture.read().dispatched.some(x=>x.type==="fileBegin")')
        if name.endswith('replacement'):
            run_command(browser, 'replaceImport()')
            wait_for(browser, 'foundationIsolationFixture.read().providers.length===2')
        else:
            run_command(browser, 'close()')
        run_command(browser, 'finishImport()')
    else:
        wait_for(browser, 'foundationIsolationFixture.read().dialogs===1')
        run_command(browser, 'clickDownload()')
        if name == 'download-valid-cleanup':
            wait_for(browser, 'foundationIsolationFixture.read().clickedURLs.length===1')
            run_command(browser, 'close()')
    # Wait for an independently observable abort, then drain actual browser
    # turns so deliberately late await completions have a chance to misbehave.
    wait_for(browser, 'foundationIsolationFixture.read().providers[0].aborted')
    browser.script('document.documentElement.removeAttribute("data-fixture-late-turn");setTimeout(()=>{document.documentElement.setAttribute("data-fixture-late-turn","true");},150);')
    browser.wait('return document.documentElement.hasAttribute("data-fixture-late-turn");')
    observed = read(browser)
    stable_canaries(observed, marker, url)
    if not observed['providers'][0]['descriptorFrozen']:
        raise AssertionError('Trusted provider received a mutable service descriptor')
    forbidden = [operation for operation in observed['dispatched'] if operation['type'] in ('service', 'fileFinish', 'fileChunk')]
    if name == 'download-valid-cleanup':
        if len(observed['createdURLs']) != 1 or observed['clickedURLs'] != observed['createdURLs'] or observed['revokedURLs'] != observed['createdURLs']:
            raise AssertionError('Valid download offering/owned URL cleanup failed')
        if len(forbidden) != 1 or forbidden[0]['type'] != 'service':
            raise AssertionError('Valid download completion was not acknowledged exactly once')
    elif name == 'download-revocation':
        if len(observed['createdURLs']) != 1 or observed['revokedURLs'] != observed['createdURLs'] or observed['clickedURLs'] or forbidden:
            raise AssertionError('Withdrawn export created a late click/completion or leaked its URL')
    elif forbidden or observed['createdURLs'] or observed['clickedURLs']:
        raise AssertionError('Revoked service produced a late file/application/window effect')
    run_command(browser, 'close()')
    wait_for(browser, 'foundationIsolationFixture.read().releases===1')
    if read(browser)['dialogs']:
        raise AssertionError('Disposed embedded frontend left a service dialog')
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--node', default='node')
    parser.add_argument('--browser', choices=('firefox', 'chromium'), default='firefox')
    parser.add_argument('--firefox', default='firefox')
    parser.add_argument('--browser-executable')
    parser.add_argument('--driver', default='chromedriver')
    parser.add_argument('--browser-argument', action='append', default=[])
    parser.add_argument('--case', action='append', choices=('authority', 'sibling', 'own-navigation', *PROTOCOL_CASES, *SERVICE_CASES,*INFRASTRUCTURE_CASES))
    args = parser.parse_args()
    if args.browser == 'chromium' and not args.browser_executable:
        parser.error('Chromium requires --browser-executable')
    args.assets = args.assets.resolve(strict=True)
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    source_inputs = [Path(__file__), Path(__file__).with_name('browser_test.py'), ATTACK, GENERATOR,
                     ROOT / 'tools/package_wasm.py', PROCESS_TREE_PATH, *(args.assets / asset for asset in ASSETS)]
    identify = lambda: {str(path.resolve()): digest(path) for path in source_inputs}
    original = identify()
    production = bundle_metadata(args.assets / 'renderer_child_bundle.mjs')
    spec = importlib.util.spec_from_file_location('foundation_browser_assembler', GENERATOR)
    sys.path.insert(0,str(GENERATOR.parent))
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    cases = args.case or ['authority', 'sibling', *PROTOCOL_CASES, *SERVICE_CASES,*INFRASTRUCTURE_CASES,'own-navigation']
    fixture_root = args.output / 'fixtures'
    fixture_root.mkdir()
    server = CanaryServer(fixture_root)
    thread = threading.Thread(target=server.serve_forever, name='renderer-canary-server')
    thread.start()
    outcomes = {};fixture_policies = {}
    try:
        prepared = {}
        for name in cases:
            marker, metadata, parent_csp = prepare_case(args, fixture_root / name, name, server.origin, generator)
            prepared[name] = marker
            fixture_policies[name] = {'child_script_sha256': metadata['CHILD_SCRIPT_SHA256'], 'child_csp': metadata['CHILD_CSP'],
                'sandbox': metadata['CHILD_SANDBOX'], 'protocol': metadata['CHILD_PROTOCOL'],
                'child_inputs': metadata['CHILD_INPUTS'], 'parent_csp': parent_csp,
                'fixture_inputs': {path.name: digest(path) for path in sorted((fixture_root / name).iterdir())}}
        with browser_workspace(args.output) as directory:
            browser = (Browser(args.firefox, directory) if args.browser == 'firefox' else
                ChromiumBrowser(args.browser_executable, args.driver, directory, args.browser_argument))
            try:
                for name in cases:
                    marker = prepared[name]
                    url = server.origin + '/' + name + '/index.html'
                    browser.root()
                    before_windows=browser.windows()
                    before_downloads={path.name:digest(path) for path in browser.downloads.iterdir() if path.is_file()}
                    browser.command('WebDriver:Navigate', {'url': url})
                    wait_for(browser, 'true')
                    try:
                        if name == 'sibling':wait_for(browser, 'foundationIsolationFixture.read().siblingReport?.complete')
                        if name=='concurrent-frontends':
                            wait_for(browser,'foundationIsolationFixture.read().ready&&foundationIsolationFixture.read().secondReady')
                            outcome=read(browser);stable_canaries(outcome,marker,url)
                            if outcome['windowCount']!=2 or outcome['secondSandbox']!='allow-scripts':raise AssertionError('Concurrent production frames did not both bind independently')
                            run_command(browser,'close()')
                            wait_for(browser,'foundationIsolationFixture.read().releases===1&&foundationIsolationFixture.read().secondReleases===1')
                        else:
                            outcome = (qualify_service(browser, name, marker, url) if name in SERVICE_CASES else
                                       qualify_attack(browser, server, name, marker, url))
                    except BaseException:
                        try:(args.output / (name+'-failure.json')).write_text(json.dumps({'observation':read(browser),'network_events':server.events},indent=2)+'\n')
                        except BaseException:pass
                        raise
                    if name == 'sibling' and (outcome['siblingReport']['connections'] != 0 or not outcome['siblingBeforeReady']):
                        raise AssertionError('A sibling with the correct nonce acquired the renderer port')
                    outcome['window_handles_before']=before_windows
                    outcome['window_handles_after']=browser.windows()
                    if outcome['window_handles_after']!=before_windows:raise AssertionError('Hostile renderer opened a browser window')
                    after_downloads={path.name:digest(path) for path in browser.downloads.iterdir() if path.is_file()}
                    if name in ('authority','sibling'):
                        if after_downloads!=before_downloads:raise AssertionError('Hostile child wrote a private download artifact')
                        run_command(browser,'downloadControl()')
                        expected_download=browser.downloads/('control-'+marker+'.txt')
                        expected_contents=b'trusted download positive control'
                        deadline=time.monotonic()+10
                        complete=False
                        while time.monotonic()<deadline:
                            try:complete=expected_download.is_file() and expected_download.read_bytes()==expected_contents
                            except OSError:complete=False
                            if complete:break
                            time.sleep(.05)
                        if not complete:raise AssertionError('Private download directory positive control failed')
                        outcome['trusted_download_control']={'filename':expected_download.name,'sha256':digest(expected_download)}
                    outcome['private_downloads_before']=before_downloads
                    outcome['private_downloads_after_child']=after_downloads
                    browser.script('foundationIsolationFixture.control();')
                    browser.wait('return document.documentElement.hasAttribute("data-fixture-control-done");')
                    if not any(event['kind'] == 'positive-control' for event in server.hits(marker)):
                        raise AssertionError('Canary-server positive control failed')
                    outcome['network_events'] = server.hits(marker)
                    outcomes[name] = outcome
                    (args.output / (name + '.json')).write_text(json.dumps(outcome, indent=2) + '\n')
                    print('Actual ' + args.browser + ' renderer isolation: ' + name + ' passed', flush=True)
                browser_version = browser.capabilities['browserVersion']
            finally:
                try:(args.output/'last-observation.json').write_text(json.dumps({'observation':read(browser),
                    'network_events':server.events,'window_handles':browser.windows(),
                    'private_downloads':{path.name:digest(path) for path in browser.downloads.iterdir() if path.is_file()}},indent=2)+'\n')
                except BaseException:pass
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    if thread.is_alive():
        raise RuntimeError('Canary server owner did not join')
    if identify() != original:
        raise RuntimeError('Browser security qualification inputs changed while running')
    checks = ['actual-browser', 'production-assembly', 'correct-hash-malicious-child',
              'malicious-top-level-ran', 'malicious-payload-ran', 'opaque-origin-parent-canaries',
              'transport-token-insulation', 'parent-service-file-url-insulation', 'canary-positive-controls',
              'browser-process-tree-joined', 'canary-server-joined']
    if 'authority' in cases:
        checks += ['child-resource-network-denials', 'storage-cookie-dom-denials', 'popup-top-navigation-download-denials']
    if 'sibling' in cases:
        checks += ['wrong-sibling-correct-nonce']
    checks += [name for name in (*PROTOCOL_CASES, *SERVICE_CASES) if name in cases]
    checks += [name for name in INFRASTRUCTURE_CASES if name in cases]
    if 'concurrent-frontends' in cases:checks += ['concurrent-frontends-isolated-lifetimes']
    if 'initial-navigation' in cases:checks += ['initial-navigation-no-rebinding']
    if 'own-navigation' in cases:
        checks += ['self-navigation-observed-and-channel-revoked']
    receipt = {'schema_version': 1, 'status': 'passed', 'engine': args.browser, 'browser_version': browser_version,
        'checks': checks, 'executed_cases': cases, 'inputs': original, 'production_child': {
            'script_sha256': production['CHILD_SCRIPT_SHA256'], 'csp': production['CHILD_CSP'],
            'sandbox': production['CHILD_SANDBOX'], 'protocol': production['CHILD_PROTOCOL'],
            'inputs': production['CHILD_INPUTS']}, 'fixture_policies': fixture_policies,
        'network_events': server.events, 'browser_arguments': args.browser_argument,
        'scope_limits': ['Currently eligible delegated UI intents can be forged by a renderer.',
            'Own-frame navigation may issue a network request before channel revocation.',
            'Bounds apply after browser delivery; this does not establish sender allocation or CPU confinement.',
            'An operation first dispatched while authorized may finish after revocation; revocation prevents new dispatch and late parent state/completion effects.'],
        'complete_security_inventory': set(cases) == set(('authority', 'sibling', *PROTOCOL_CASES, *SERVICE_CASES,*INFRASTRUCTURE_CASES,'own-navigation'))}
    temporary = args.output / 'qualification.tmp'
    with temporary.open('x') as stream:
        stream.write(json.dumps(receipt, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(args.output / 'qualification.json')


if __name__ == '__main__':
    main()
