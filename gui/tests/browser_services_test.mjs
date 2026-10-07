import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {createBrowserServices,executeService}=await import(pathToFileURL(resolve(process.argv[2])));
const {readTextFile,uploadTextFile}=await import(new URL('./file_services.mjs',pathToFileURL(resolve(process.argv[2]))));
const {Client}=await import(pathToFileURL(resolve(process.argv[3])));
const drain=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
function scheduler() {
  let next=0;const timers=new Map();
  return {timers,setTimeout(run){timers.set(++next,run);return next;},clearTimeout(id){timers.delete(id);},run(){assert.equal(timers.size,1);const [id,run]=timers.entries().next().value;timers.delete(id);return run();}};
}
class Element {
  constructor(tag,env){this.tag=tag;this.env=env;this.children=[];this.listeners={};this.open=false;this.disabled=false;}
  append(...nodes){this.children.push(...nodes);this.env.append?.(this,nodes);}
  setAttribute(){} select(){this.selected=true;} focus(){this.focused=true;} remove(){this.removed=true;}
  addEventListener(name,run){(this.listeners[name]||=[]).push(run);}
  fire(name,values={}){for(const run of this.listeners[name]||[])run({preventDefault(){},stopPropagation(){},...values});}
  showModal(){this.open=true;this.shown=true;} close(){this.open=false;this.fire('close');}
  click(){this.clicked=true;this.fire('click');}
}
function environment() {
  const env={nodes:[],revoked:[],timers:[],blobs:0};
  const document={body:new Element('body',env),activeElement:null,querySelector(){return null;},createElement(tag){const node=new Element(tag,env);env.nodes.push(node);return node;}};
  const capability={Blob:class extends Blob{constructor(...args){super(...args);++env.blobs;}},URL:{createObjectURL(){env.created=true;env.createURL?.();return 'blob:owned';},revokeObjectURL(url){env.revoked.push(url);}},setTimeout(run){env.timers.push(run);}};
  document.defaultView=capability;env.document=document;return env;
}
const prompt={id:'prompt',kind:2,title:'Heading',value:'initial',byteLimit:'4'};
const reading={id:'read',kind:5,title:'Import',value:'',byteLimit:'65536',chunked:true};
const exporting={...reading,id:'write',kind:6,byteSize:'1',value:''};
const state=(ack,service=null,closed=false)=>({epoch:'test',ack:String(ack),service,error:'',snapshot:{closed}});

// Preserve the retained prompt's validation, Enter/IME and cancellation behavior.
{
  const env=environment();const result=executeService(prompt,{document:env.document});
  const input=env.nodes.find(node=>node.tag==='input'),dialog=env.nodes[0];
  input.value='ééé';env.nodes.find(node=>node.tag==='form').fire('submit');assert.equal(dialog.removed,undefined);
  assert.match(env.nodes.find(node=>node.tag==='p').textContent,/4-byte/);
  input.value='éé';dialog.fire('keydown',{key:'Enter',target:input,isComposing:true});assert.equal(dialog.removed,undefined);
  dialog.fire('keydown',{key:'Enter',target:input,isComposing:false});assert.deepEqual(await result,{type:'service',id:'prompt',value:'éé',error:'',status:'success'});
}
{
  const env=environment();let live=true;
  env.append=(node)=>{if(node===env.document.body)live=false;};
  const result=await executeService(prompt,{document:env.document,isCurrent:()=>live});
  assert.equal(result.status,'cancelled');assert.equal(env.nodes[0].shown,undefined,'withdrawal during mount must prevent opening');assert.equal(env.nodes[0].removed,true);
}
{
  const env=environment(),mount=new Element('mount',env),clock=scheduler();
  env.document.querySelector=()=>{throw Error('Explicit service root must take precedence over stage lookup');};
  const client={state:state(0,prompt),async send(){return client.state;}};
  const services=createBrowserServices({client,scheduler:clock,host:{document:env.document,serviceRoot:mount}});
  services.accept();const pending=clock.run();assert.equal(mount.children[0],env.nodes[0]);assert.equal(env.document.body.children.length,0);
  services.close();await pending;
  const result=executeService(reading,{document:env.document,serviceRoot:mount});const dialog=env.nodes.filter(node=>node.tag==='dialog').at(-1);
  assert.equal(mount.children.at(-1),dialog);dialog.close();assert.equal((await result).status,'cancelled');
}

// The accepted descriptor is cloned, and same-ID replacement revokes ownership.
{
  const clock=scheduler(),calls=[],sent=[],pending=[];
  const client={state:state(0,prompt),closed:false,async send(operation,_coalesce,check){check();sent.push(operation);return client.state;}};
  const services=createBrowserServices({client,scheduler:clock,host:{executeService(service,host){
    assert.equal(Object.isFrozen(service),true);assert.throws(()=>{service.value='changed by host';},TypeError);
    calls.push({service,host});const wait=deferred();pending.push(wait);return wait.promise;
  }}});
  services.accept(client.state);client.state=state(1);services.accept(client.state);assert.equal(clock.timers.size,0);assert.equal(calls.length,0);
  client.state=state(2,{...prompt});services.accept(client.state);const first=clock.run();assert.equal(calls.length,1);
  client.state.service.value='changed';assert.equal(calls[0].service.value,'initial','caller mutation must not alter the owned descriptor');assert.equal(calls[0].host.isCurrent(),false);
  services.accept(client.state);assert.equal(calls[0].host.signal.aborted,true);const second=clock.run();assert.equal(calls.length,2);
  pending[0].resolve({type:'service',id:'prompt',status:'success',value:'old'});await first;assert.equal(sent.length,0);
  services.close();assert.equal(calls[1].host.signal.aborted,true);pending[1].resolve({type:'service',id:'prompt',status:'success',value:'late'});await second;assert.equal(sent.length,0);
}

// A result queued behind an action is rejected before acquiring a sequence.
{
  const clock=scheduler(),firstReply=deferred(),operations=[];
  let services;
  const client=new Client(async envelope=>{operations.push(envelope);if(envelope.operation.type==='action')return firstReply.promise;return state(envelope.seq);},()=>services?.accept());
  services=createBrowserServices({client,scheduler:clock,host:{executeService:async service=>({type:'service',id:service.id,status:'success',value:'ready'})}});
  client.accept(state(0,prompt));const action=client.send({type:'action'});const completion=clock.run();await drain();assert.equal(client.queue.length,1);
  firstReply.resolve(state(1));await action;await completion;assert.deepEqual(operations.map(value=>value.operation.type),['action']);assert.equal(client.ack,1n);assert.equal(client.queuedBytes,0);
  await client.send({type:'next'});assert.equal(operations.at(-1).seq,'2','cancelled completion cannot consume a sequence');services.close();client.close();
}

// Once an envelope exists, uncertainty retries preserve its exact identity.
{
  const clock=scheduler(),operations=[];let services,fail=true;
  const client=new Client(async envelope=>{operations.push(envelope);if(fail)throw Error('lost receipt');return state(envelope.seq);},()=>services?.accept());
  services=createBrowserServices({client,scheduler:clock,host:{executeService:async service=>({type:'service',id:service.id,status:'success',value:'ready'})}});
  client.accept(state(0,prompt));const completion=clock.run();await drain();assert.equal(client.failed,true);const envelope=operations[0];
  client.accept(state(0));fail=false;client.retry();await completion;assert.equal(operations[1],envelope);assert.equal(client.ack,1n);services.close();client.close();
}

// Closing from an external lifetime cancels deferred effects immediately.
{
  const clock=scheduler(),controller=new AbortController();let called=0;
  const client={state:state(0,prompt)};
  const services=createBrowserServices({client,signal:controller.signal,scheduler:clock,host:{executeService(){++called;}}});
  services.accept();controller.abort();assert.equal(clock.timers.size,0);services.accept();assert.equal(called,0);
}
{
  const clock=scheduler();let frozen;
  const client={state:state(0,{...prompt,extension:{items:[{value:'owned'}]}})};
  const services=createBrowserServices({client,scheduler:clock,host:{executeService(service){frozen=service;return new Promise(()=>{});}}});
  services.accept();clock.run();assert.equal(Object.isFrozen(frozen.extension.items[0]),true);assert.throws(()=>{frozen.extension.items.push({});},TypeError);services.close();
}

// A valid offered download retains its delay after completion, while the
// frontend lifetime owns and clears that URL and timer on close.
{
  const env=environment(),clock=scheduler();
  const client={state:state(0,{...exporting,chunked:false,value:'A'}),async send(){return client.state;}};
  const services=createBrowserServices({client,scheduler:clock,host:{document:env.document}});
  services.accept();const pending=clock.run();env.nodes.find(node=>node.tag==='form').fire('submit');await pending;
  assert.equal(env.nodes.find(node=>node.tag==='a').clicked,true);assert.equal(clock.timers.size,1);assert.deepEqual(env.revoked,[]);
  const delayed=[...clock.timers.values()][0];client.state=state(1);services.accept();assert.equal(clock.timers.size,1,'completion must preserve the valid download offer');
  services.close();assert.equal(clock.timers.size,0);assert.deepEqual(env.revoked,['blob:owned']);delayed();assert.deepEqual(env.revoked,['blob:owned'],'late cleanup cannot double revoke');
}

// Every asynchronous file stage rechecks ownership before starting another one.
{
  let live=true,slices=0;
  await assert.rejects(uploadTextFile({size:1,slice(){++slices;}},reading,async()=>{live=false;return state(1,reading);},undefined,()=>live),/cancelled/);
  assert.equal(slices,0,'withdrawal after begin must prevent reading');
}
{
  let live=true,buffers=0;
  await assert.rejects(readTextFile({size:1,slice(){live=false;return {arrayBuffer(){++buffers;}};}},1,{isCurrent:()=>live}),/cancelled/);
  assert.equal(buffers,0,'withdrawal during slice must prevent arrayBuffer');
}
{
  let live=true;const wait=deferred(),operations=[];
  const upload=uploadTextFile({size:1,slice(){return {arrayBuffer:()=>wait.promise};}},reading,async operation=>{operations.push(operation);return state(1,reading);},undefined,()=>live);
  await drain();live=false;wait.resolve(new Uint8Array([65]).buffer);await assert.rejects(upload,/cancelled/);assert.deepEqual(operations.map(value=>value.type),['fileBegin']);
}
{
  const env=environment(),wait=deferred();let live=true;
  const result=executeService(exporting,{document:env.document,isCurrent:()=>live,exchange:()=>wait.promise});
  const button=env.nodes.find(node=>node.type==='submit');assert.equal(button.disabled,true);live=false;
  wait.resolve({...state(1,exporting),transfer:{id:'write',offset:'0',total:'1',hex:'41'}});assert.equal((await result).status,'cancelled');await drain();assert.equal(button.disabled,true);assert.equal(env.blobs,0);
}
{
  const env=environment();let live=true;env.createURL=()=>{live=false;};
  const result=executeService({...exporting,chunked:false,value:'A'},{document:env.document,isCurrent:()=>live});
  env.nodes.find(node=>node.tag==='form').fire('submit');assert.equal((await result).status,'cancelled');assert.equal(env.nodes.some(node=>node.clicked),false);assert.deepEqual(env.revoked,['blob:owned']);assert.equal(env.timers.length,0,'obsolete export must revoke without scheduling');
}
console.log('Browser service ownership, exact descriptors, guarded queue preparation, retries, prompt semantics and file effects passed');
