// One Worker owns one C++ session. Client supplies ordered epoch/sequence envelopes.
export const MAX_REQUEST_BYTES=1024*1024;
export const MAX_RESPONSE_BYTES=32*1024*1024;
const encoder=new TextEncoder();

export function createWasmTransport({workerURL=new URL('./wasm_worker.mjs',import.meta.url),
  moduleURL=new URL('./gui_web_wasm.js',import.meta.url).href,factorySource,wasmBinary,
  epoch=globalThis.crypto.randomUUID(),workerFactory=url=>new Worker(url,{type:'module'}),
  scheduler=globalThis,startTimeout=30000,closeTimeout=1000}={}) {
  let state='starting',worker,pending=null,closePromise=null,closeResolve,startTimer,closeTimer;
  let readyResolve,readyReject,nextId=0;
  const ready=new Promise((resolve,reject)=>{readyResolve=resolve;readyReject=reject;});
  // The owner may close during startup before attaching its awaiting continuation.
  ready.catch(()=>{});
  const clearTimers=()=>{scheduler.clearTimeout(startTimer);scheduler.clearTimeout(closeTimer);};
  const terminate=()=>{clearTimers();if(worker){worker.onmessage=null;worker.onerror=null;worker.onmessageerror=null;worker.terminate();}};
  const rejectPending=error=>{if(pending){pending.reject(error);pending=null;}};
  const fail=error=>{
    if(state==='closed'||state==='failed')return;
    state='failed';readyReject(error);rejectPending(error);terminate();
    if(closeResolve)closeResolve({graceful:false,reason:error.message});
  };
  const post=message=>{try{worker.postMessage(message);}catch(error){fail(error);throw error;}};
  const decode=text=>{
    if(typeof text!=='string'||text.length>MAX_RESPONSE_BYTES||encoder.encode(text).length>MAX_RESPONSE_BYTES)throw Error('Worker response exceeds limit');
    const value=JSON.parse(text);if(!value||typeof value!=='object')throw Error('Invalid Worker response');return value;
  };
  const exchange=envelope=>{
    if(state!=='ready')return Promise.reject(Error(`Wasm transport is ${state}; create a new session after failure`));
    if(pending)return Promise.reject(Error('Wasm exchange already outstanding'));
    let text;try{text=JSON.stringify(envelope);if(typeof text!=='string'||text.length>MAX_REQUEST_BYTES||encoder.encode(text).length>MAX_REQUEST_BYTES)throw Error('Worker request exceeds limit');}
    catch(error){return Promise.reject(error);}
    const id=++nextId;
    return new Promise((resolve,reject)=>{pending={id,resolve,reject};try{post({type:'receive',id,text});}catch{/* fail rejected pending */}});
  };
  const close=()=>{
    if(closePromise)return closePromise;
    if(state==='closed'||state==='failed')return Promise.resolve({graceful:state==='closed'});
    state='closing';const error=Error('Wasm transport closed');readyReject(error);rejectPending(error);
    closePromise=new Promise(resolve=>{closeResolve=resolve;});
    scheduler.clearTimeout(startTimer);
    closeTimer=scheduler.setTimeout(()=>fail(Error('Worker close acknowledgment timed out')),closeTimeout);
    try{post({type:'close'});}catch{/* fail settles close */}
    return closePromise;
  };
  try {
    worker=workerFactory(workerURL);
    worker.onerror=event=>fail(Error(event.message||'Application Worker failed'));
    worker.onmessageerror=()=>fail(Error('Application Worker message could not be decoded'));
    worker.onmessage=event=>{
      const message=event.data;
      try {
        if(!message||typeof message!=='object')throw Error('Invalid Worker message');
        if(state==='closing'){
          if(message.type==='closed'){state='closed';terminate();closeResolve({graceful:true});}
          else if(message.type==='error')fail(Error(message.message||'Worker shutdown failed'));
          return; // Late initialization or an already dispatched response cannot revive us.
        }
        if(state==='closed'||state==='failed')return;
        if(message.type==='error')throw Error(message.message||'Application Worker failed');
        if(message.type==='ready'&&state==='starting'){
          const initial=decode(message.text);state='ready';scheduler.clearTimeout(startTimer);readyResolve(initial);
        }else if(message.type==='response'&&state==='ready'&&pending&&message.id===pending.id){
          const result=decode(message.text),request=pending;pending=null;request.resolve(result);
        }else throw Error('Unexpected Worker response');
      }catch(error){fail(error);}
    };
    startTimer=scheduler.setTimeout(()=>fail(Error('Worker initialization timed out')),startTimeout);
    post({type:'init',epoch,moduleURL,factorySource,wasmBinary});
  }catch(error){fail(error);}
  return {ready,exchange,close,get state(){return state;}};
}
