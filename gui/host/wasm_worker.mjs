// This module deliberately needs no pthreads, SharedArrayBuffer, fibers or Asyncify.
const MAX_INPUT=1024*1024,MAX_OUTPUT=32*1024*1024,MAX_FACTORY=16*1024*1024,MAX_WASM=64*1024*1024;
const encoder=new TextEncoder();
const bounded=(text,limit)=>typeof text==='string'&&text.length<=limit&&encoder.encode(text).length<=limit;

export function installWasmWorker(scope,loadModule=url=>import(url)) {
  let state='new',module=null,busy=false,closeRequested=false,factoryURL=null;
  const post=message=>scope.postMessage(message);
  const cleanup=()=>{if(factoryURL){URL.revokeObjectURL(factoryURL);factoryURL=null;}};
  const destroy=()=>{
    if(module){const owned=module;module=null;owned.ccall('gui_web_destroy',null,[],[]);}
  };
  const fail=error=>{
    if(state==='closed'||state==='failed')return;
    state='failed';try{destroy();}catch{/* Original failure remains authoritative. */}
    cleanup();post({type:'error',message:String(error.message||error).slice(0,4096)});scope.close();
  };
  const close=()=>{
    if(state==='closed'||state==='failed')return;
    closeRequested=true;if(busy)return;
    try{destroy();state='closed';cleanup();post({type:'closed'});scope.close();}catch(error){fail(error);}
  };
  const output=(type,id,text)=>{if(!bounded(text,MAX_OUTPUT))throw Error('Worker response exceeds limit');post({type,id,text});};
  scope.onmessage=async event=>{
    const message=event.data;
    try {
      if(!message||typeof message!=='object')throw Error('Invalid Worker command');
      if(message.type==='close'){close();return;}
      if(closeRequested||state==='closed'||state==='failed')return;
      if(busy)throw Error('Worker operation already outstanding');
      if(message.type==='init'){
        if(state!=='new')throw Error('Worker already initialized');
        if(typeof message.epoch!=='string'||!message.epoch.length||message.epoch.length>128)throw Error('Invalid session epoch');
        if(message.wasmBinary!==undefined&&(!(message.wasmBinary instanceof Uint8Array)||message.wasmBinary.byteLength>MAX_WASM))throw Error('Invalid embedded Wasm');
        busy=true;state='starting';let url=message.moduleURL;
        if(message.factorySource!==undefined){
          if(!bounded(message.factorySource,MAX_FACTORY)||!message.wasmBinary)throw Error('Invalid embedded factory');
          factoryURL=URL.createObjectURL(new Blob([message.factorySource],{type:'text/javascript'}));url=factoryURL;
        }
        if(typeof url!=='string')throw Error('Missing Wasm module URL');
        const {default:createModule}=await loadModule(url);
        module=await createModule({...(message.wasmBinary?{wasmBinary:message.wasmBinary,locateFile:name=>name}:{}),print:()=>{},printErr:()=>{}});
        // A failure/close during async initialization never abandons a late module.
        if(state==='failed'){destroy();cleanup();return;}
        if(closeRequested){busy=false;close();return;}
        output('ready',null,module.ccall('gui_web_create','string',['string'],[message.epoch]));
        state='ready';busy=false;cleanup();
      }else if(message.type==='receive'){
        if(state!=='ready'||!Number.isSafeInteger(message.id)||message.id<=0||!bounded(message.text,MAX_INPUT))throw Error('Invalid Worker request');
        busy=true;
        output('response',message.id,module.ccall('gui_web_receive','string',['string'],[message.text]));
        busy=false;
      }else throw Error('Unknown Worker command');
    }catch(error){busy=false;fail(error);}
  };
}
if(typeof WorkerGlobalScope!=='undefined'&&globalThis instanceof WorkerGlobalScope)installWasmWorker(globalThis);
