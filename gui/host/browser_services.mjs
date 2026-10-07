import {executeFileService} from './file_services.mjs';

// Host capabilities consume only public service descriptors. The renderer has
// no dialog, file or transport ownership.
const encoder = new TextEncoder();
const current = host => !host.signal?.aborted && (!host.isCurrent || host.isCurrent());
const freezeDescriptor = value => {
  if(value && typeof value === 'object') {
    for(const child of Object.values(value))freezeDescriptor(child);
    Object.freeze(value);
  }
  return value;
};
export async function executeService(service, host = globalThis) {
  const base={type:'service',id:service.id,value:'',error:''};
  if (!current(host)) return {...base,status:'cancelled'};
  if(service.kind===5||service.kind===6)return executeFileService(service,host);
  if(service.kind!==2)return {...base,status:'error',error:'This browser profile supports prompts only; file paths and external host services are unsupported.'};
  const document=host.document;
  if(!document)return {...base,status:'error',error:'This host has no DOM dialog support.'};
  return new Promise(resolve=>{
    const previous=document.activeElement,dialog=document.createElement('dialog');dialog.className='service-prompt';
    const form=document.createElement('form'),label=document.createElement('label'),title=document.createElement('span'),input=document.createElement('input');
    const error=document.createElement('p'),actions=document.createElement('div'),cancel=document.createElement('button'),accept=document.createElement('button');
    title.textContent=service.title;input.type='text';input.value=service.value;input.setAttribute('aria-label',service.title);
    error.setAttribute('role','status');actions.className='service-actions';cancel.type='button';cancel.textContent='Cancel';accept.type='submit';accept.textContent='OK';
    label.append(title,input);actions.append(cancel,accept);form.append(label,error,actions);dialog.append(form);
    let settled=false;
    const finish=(status,value='',failure='')=>{
      if(settled)return;settled=true;
      host.signal?.removeEventListener('abort',abort);
      if(dialog.open)dialog.close();dialog.remove();
      // Removing an obsolete dialog is cleanup; restoring focus is a new effect.
      if(current(host)&&previous?.isConnected)previous.focus({preventScroll:true});
      resolve({...base,status,value,error:failure});
    };
    const abort=()=>finish('cancelled');
    const check=()=>{if(settled)return false;if(current(host))return true;abort();return false;};
    host.signal?.addEventListener('abort',abort,{once:true});
    if(!check())return;
    const submit=()=>{
      if(!check())return;
      const value=input.value;
      if(BigInt(encoder.encode(value).length)>BigInt(service.byteLimit)){
        if(!check())return;error.textContent=`Text exceeds the ${service.byteLimit}-byte limit.`;
        if(check())input.focus();return;
      }
      if(check())finish('success',value);
    };
    form.addEventListener('submit',event=>{event.preventDefault();submit();});
    cancel.addEventListener('click',()=>finish('cancelled'));
    dialog.addEventListener('cancel',event=>{event.preventDefault();finish('cancelled');});
    dialog.addEventListener('close',()=>finish('cancelled'));
    dialog.addEventListener('keydown',event=>{
      event.stopPropagation();
      if(event.key==='Escape'){event.preventDefault();finish('cancelled');}
      else if(event.key==='Enter'&&event.target===input&&!event.isComposing){event.preventDefault();submit();}
    });
    try{
      if(!check())return;(host.serviceRoot||document.querySelector?.('#stage')||document.body).append(dialog);
      if(!check())return;dialog.showModal();
      if(!check())return;input.focus();
      if(check())input.select();
    }catch(failure){finish(current(host)?'error':'cancelled','',failure.message||'Could not open prompt');}
  });
}

// Dispatch from accepted Client state, independently of coalesced presentation.
// A queued completion gets one final ownership check before its first envelope;
// a prepared envelope keeps its transport identity through uncertain retries.
export function createBrowserServices({client,host=globalThis,signal=host.signal,
  scheduler=host.document?.defaultView||globalThis,status=()=>{}}) {
  let active=null,stopped=false;
  const downloads=new Set();
  const ownDownloadURL=(url,revoke)=>{
    let timer=null,released=false;
    const release=()=>{
      if(released)return;released=true;
      if(timer!==null)scheduler.clearTimeout(timer);
      timer=null;downloads.delete(resource);revoke(url);
    };
    const resource={revoke:release,schedule(delay=1000){
      if(released)return;
      if(stopped){release();return;}
      if(timer!==null)scheduler.clearTimeout(timer);
      timer=scheduler.setTimeout(release,delay);
    }};
    downloads.add(resource);
    if(stopped)release();
    return resource;
  };
  const cancel=()=>{
    if(!active)return;
    if(active.timer!==null)scheduler.clearTimeout(active.timer);
    active.timer=null;active.controller.abort();active=null;
  };
  const close=()=>{
    if(stopped)return;stopped=true;cancel();
    for(const resource of [...downloads])resource.revoke();
    signal?.removeEventListener('abort',close);
  };
  signal?.addEventListener('abort',close,{once:true});
  if(signal?.aborted)close();
  return {
    accept() {
      if(stopped)return;
      const state=client.state;
      if(client.closed||state?.snapshot?.closed){close();return;}
      let signature;
      try{signature=state?.service?JSON.stringify(state.service):null;}
      catch(error){cancel();status(error.message);return;}
      if(active&&active.epoch===state?.epoch&&active.signature===signature)return;
      cancel();
      if(signature===null||signature===undefined)return;
      const descriptor=freezeDescriptor(JSON.parse(signature)),controller=new (host.AbortController||globalThis.AbortController)();
      const owner={epoch:state.epoch,signature,descriptor,controller,timer:null};active=owner;
      const isCurrent=()=>{
        if(stopped||client.closed||active!==owner||controller.signal.aborted||signal?.aborted||client.state?.snapshot?.closed||client.state?.epoch!==owner.epoch)return false;
        try{return JSON.stringify(client.state?.service)===signature;}catch{return false;}
      };
      const check=()=>{if(!isCurrent())throw Error('Service request was replaced');return true;};
      const exchange=async operation=>{check();const state=await client.send(operation,null,check);check();return state;};
      const serviceHost=Object.create(host);
      // Window accessors require their actual Window receiver. Capture those
      // capabilities here rather than invoking them through a prototype proxy.
      Object.defineProperties(serviceHost,{
        signal:{value:controller.signal},isCurrent:{value:isCurrent},exchange:{value:exchange},ownDownloadURL:{value:ownDownloadURL},
        document:{value:host.document},serviceRoot:{value:host.serviceRoot},URL:{value:host.URL},Blob:{value:host.Blob},
        setTimeout:{value:host.setTimeout?.bind(host)}
      });
      if(!isCurrent()){cancel();return;}
      owner.timer=scheduler.setTimeout(async()=>{
        owner.timer=null;
        try{
          check();
          const result=await (host.executeService||executeService)(descriptor,serviceHost);
          check();
          await client.send(result,null,check);
          check();
        }catch(error){if(isCurrent())status(error.message);}
      },0);
    },
    close
  };
}
