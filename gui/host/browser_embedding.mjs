import {Client} from './browser_client.mjs';
import {createBrowserServices} from './browser_services.mjs';
import {startPolling} from './browser_lifecycle.mjs';
import {createHostChannel} from './renderer_channel.mjs';
import {CHANNEL_PROTOCOL} from './browser_limits.mjs';
import {CHILD_SCRIPT,CHILD_SCRIPT_SHA256,CHILD_STYLE,CHILD_CSP,CHILD_SANDBOX,CHILD_PROTOCOL} from './renderer_child_bundle.mjs';

const attribute = value => String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');

// The privileged API has one composition. The child bundle is inert data in
// this realm: neither its entry point nor any renderer module is imported here.
export function createEmbeddedFrontend({mount,initialState,exchange,release=()=>{},host=globalThis,status=()=>{},serviceHost=host,startupTimeout=10000,pollingInterval=25}) {
  if (!mount || typeof exchange !== 'function') throw Error('Embedded frontend requires a mount and transport');
  if (CHILD_PROTOCOL !== CHANNEL_PROTOCOL || CHILD_SANDBOX !== 'allow-scripts' || !CHILD_CSP.includes(`'sha256-${CHILD_SCRIPT_SHA256}'`) || /<\/script/i.test(CHILD_SCRIPT) || /<\/style/i.test(CHILD_STYLE)) throw Error('Invalid isolated renderer bundle');
  const document = host.document, frame = document.createElement('iframe');
  const random = new Uint8Array(32); host.crypto.getRandomValues(random);
  const generation = Array.from(random,value=>value.toString(16).padStart(2,'0')).join('');
  let state = 'created', loaded = false, announced = false, transferred = false, released = false, bootstrapPort = null, channel = null, observer = null, stopPolling = ()=>{}, startupTimer = null;
  let resolveReady, rejectReady;
  const ready = new Promise((resolve,reject)=>{resolveReady=resolve;rejectReady=reject;});
  // Callers may dispose during startup without having attached their await yet.
  ready.catch(()=>{});
  const lifetime = new AbortController();
  const client = new Client(exchange,accepted=>{
    if (state === 'closed' || state === 'closing') return;
    for (const [name,color] of Object.entries(accepted.snapshot.palette)) mount.style?.setProperty(`--${name}`,`rgb(${color.join(',')})`);
    channel?.accept(accepted); services.accept(accepted);
  },status);
  // Capture branded Window capabilities with their actual receivers and keep
  // host dialogs within this frontend's palette and mount.
  const provider = {document:serviceHost.document,URL:serviceHost.URL,Blob:serviceHost.Blob,
    setTimeout:serviceHost.setTimeout?.bind(serviceHost),AbortController:serviceHost.AbortController,
    executeService:serviceHost.executeService,serviceRoot:mount};
  const services = createBrowserServices({client,host:provider,signal:lifetime.signal,scheduler:host,status});
  const cleanupListeners = () => {
    host.removeEventListener('message',handshake); host.removeEventListener('pagehide',close);
    frame.removeEventListener('load',load); frame.removeEventListener('error',frameError);
  };
  const close = (reason=Error('Embedded frontend closed')) => {
    if (state === 'closed' || state === 'closing') return;
    const wasReady = state === 'ready'; state = 'closing';
    if (startupTimer !== null) host.clearTimeout(startupTimer); startupTimer = null;
    cleanupListeners(); lifetime.abort(); services.close(); stopPolling(); observer?.disconnect(); channel?.close(); bootstrapPort?.close(); bootstrapPort = null; client.close(); frame.remove();
    if (!released) { released = true; Promise.resolve().then(release).catch(error=>status(`Could not release application: ${error.message}`)); }
    state = 'closed'; if (!wasReady) rejectReady(reason instanceof Error ? reason : Error('Embedded frontend closed'));
  };
  const fail = error => {
    if (state === 'closed' || state === 'closing') return;
    state = 'failed'; status(`Isolated renderer failed: ${String(error.message || error).slice(0,1024)}`,true); close(error);
  };
  const bind = () => {
    if (!loaded || !announced || transferred || state === 'closed') return;
    transferred = true;
    channel = createHostChannel({port:bootstrapPort,generation,client,scheduler:host,timeout:startupTimeout,onFailure:fail,onBound:()=>{
      if (state !== 'awaiting') return;
      state = 'ready'; if (startupTimer !== null) host.clearTimeout(startupTimer); startupTimer = null;
      host.removeEventListener('message',handshake);
      channel.accept(client.state);
      let previousSize = '';
      const resize = () => {
        if (state !== 'ready') return;
        const width = Math.min(4096,Math.max(0,Math.round(mount.clientWidth))), height = Math.min(4096,Math.max(0,Math.round(mount.clientHeight)));
        const scale = Math.min(4,host.devicePixelRatio || 1), signature = JSON.stringify([width,height,scale]);
        if (signature !== previousSize) { previousSize = signature; client.send({type:'resize',width,height,scale},'resize').catch(error=>status(error.message)); }
      };
      observer = new host.ResizeObserver(resize); observer.observe(mount); resize();
      stopPolling = startPolling(client,host,pollingInterval); resolveReady();
    }});
    bootstrapPort.postMessage({protocol:CHANNEL_PROTOCOL,type:'connect',generation});
  };
  const handshake = event => {
    if (state !== 'awaiting' || event.source !== frame.contentWindow || event.origin !== 'null') return;
    const message = event.data;
    if (!message || message.protocol !== CHANNEL_PROTOCOL) return;
    if (message.generation !== generation) { for(const port of event.ports || [])port.close(); fail(Error('Invalid renderer startup identity')); return; }
    const plain = !Array.isArray(message) && typeof message === 'object' && [Object.prototype,null].includes(Object.getPrototypeOf(message));
    if (!plain || announced || message.type !== 'ready' || Object.keys(message).length !== 3 || !['protocol','type','generation'].every(key=>Object.hasOwn(message,key)) || event.ports?.length !== 1) { for(const port of event.ports || [])port.close(); fail(Error('Invalid renderer startup')); return; }
    bootstrapPort = event.ports[0]; announced = true; bind();
  };
  const load = () => { if (loaded) { fail(Error('Renderer document navigated')); return; } loaded = true; bind(); };
  const frameError = () => fail(Error('Renderer document failed to load'));
  frame.setAttribute('data-foundation-embedded',''); frame.setAttribute('title','Application controls');
  frame.setAttribute('sandbox','allow-scripts'); frame.setAttribute('referrerpolicy','no-referrer');
  Object.assign(frame.style,{border:'0',display:'block',width:'100%',height:'100%'});
  frame.addEventListener('load',load); frame.addEventListener('error',frameError);
  host.addEventListener('message',handshake); host.addEventListener('pagehide',close,{once:true});
  frame.srcdoc = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${attribute(CHILD_CSP)}"><meta name="foundation-channel" content="${attribute(generation)}"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${CHILD_STYLE}\n#viewport{height:100vh;min-height:0}</style></head><body><main id="viewport"><div id="stage"><nav id="pages" aria-label="Pages"></nav></div></main><script>${CHILD_SCRIPT}</script></body></html>`;
  state = 'awaiting';
  startupTimer = host.setTimeout(()=>fail(Error('Renderer startup timed out')),startupTimeout);
  try { client.accept(initialState); mount.append(frame); } catch (error) { fail(error); }
  return Object.freeze({frame,ready,close,retry:()=>{if(state === 'ready')client.retry();}});
}
