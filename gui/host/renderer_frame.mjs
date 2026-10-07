import {Renderer} from './renderer_dom.mjs';
import {createBrowserPresenter} from './browser_presenter.mjs';
import {createRendererRequests} from './renderer_channel.mjs';
import {CHANNEL_PROTOCOL} from './browser_limits.mjs';

// This module executes only inside the opaque sandbox document. It has no
// Client, transport, token, Worker, file or service provider in its module graph.
export function startRendererFrame(host = globalThis) {
  const document = host.document;
  const generation = document.querySelector('meta[name="foundation-channel"]')?.content;
  if (!generation || host.parent === host) throw Error('Renderer has no isolated host');
  // The initial document owns its endpoint before announcing readiness. A
  // navigation can replace the WindowProxy, but cannot receive this endpoint.
  const ports = new host.MessageChannel();
  let bound = false, closed = false, requests = null, renderer = null, presenter = null;
  const close = () => {
    if (closed) return; closed = true;
    host.removeEventListener('pagehide',close);
    ports.port1.onmessage = null; ports.port1.onmessageerror = null; ports.port1.close();
    requests?.close(); presenter?.close(); renderer?.destroy();
  };
  const connect = event => {
    if (closed) return;
    const data = event.data;
    const plain = data && !Array.isArray(data) && typeof data === 'object' && [Object.prototype,null].includes(Object.getPrototypeOf(data));
    if (!plain || data.protocol !== CHANNEL_PROTOCOL || data.generation !== generation || bound || data.type !== 'connect' || Object.keys(data).length !== 3 || !['protocol','type','generation'].every(key=>Object.hasOwn(data,key)) || event.ports?.length) { close(); return; }
    bound = true;
    renderer = new Renderer(document.querySelector('#stage'),document.querySelector('#pages'),operation=>requests.send(operation),document,
      {sendEdit:(key,value)=>requests.send({type:'editIntent',key,value})});
    presenter = createBrowserPresenter(snapshot=>renderer.render(snapshot),host);
    requests = createRendererRequests({port:ports.port1,generation,
      acceptSnapshot(snapshot,cancelPointers) { renderer.acceptSnapshot(snapshot); if (cancelPointers || snapshot.closed) renderer.cancelPointers(); },
      present(snapshot,barrier) { presenter.accept({snapshot,error:'',service:null}); if (barrier) presenter.flush(); },
      onFailure:close});
  };
  ports.port1.onmessage = connect; ports.port1.onmessageerror = close; ports.port1.start();
  host.addEventListener('pagehide',close,{once:true});
  host.parent.postMessage({protocol:CHANNEL_PROTOCOL,type:'ready',generation},'*',[ports.port2]);
  return {close};
}

startRendererFrame();
