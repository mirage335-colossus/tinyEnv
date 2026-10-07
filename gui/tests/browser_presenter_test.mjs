import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {createBrowserPresenter}=await import(pathToFileURL(resolve(process.argv[2])));
const {Client}=await import(pathToFileURL(resolve(process.argv[3])));
const {createBrowserServices}=await import(new URL('./browser_services.mjs',pathToFileURL(resolve(process.argv[3]))));
const {browserComposition}=await import(new URL('./browser_composition.mjs',pathToFileURL(resolve(process.argv[3]))));
let next=0;const frames=new Map();
const scheduler={requestAnimationFrame(run){frames.set(++next,run);return next;},cancelAnimationFrame(id){frames.delete(id);}};
const runFrame=()=>{assert.equal(frames.size,1);const [id,run]=frames.entries().next().value;frames.delete(id);run();};
const shown=[],received=[],errors=[];const presenter=createBrowserPresenter(snapshot=>shown.push(snapshot.value),scheduler);
const state=(ack,value,service=null,error='',closed=false)=>({epoch:'test',ack:String(ack),snapshot:{value,closed},service,error});
const client=new Client(async envelope=>{received.push(envelope);return state(envelope.seq,envelope.operation.value);},value=>presenter.accept(value),error=>errors.push(error));
client.accept(state(0,0));assert.deepEqual(shown,[0]);
await client.send({type:'edit',value:1});await client.send(snapshot=>({type:'activate',value:snapshot.value+1}));await client.send({type:'edit',value:3});
assert.equal(client.ack,3n);assert.deepEqual(received.map(value=>value.seq),['1','2','3']);assert.deepEqual(received.map(value=>value.operation.value),[1,2,3]);assert.deepEqual(shown,[0]);assert.equal(frames.size,1);
runFrame();assert.deepEqual(shown,[0,3]);
client.accept(state(4,4));client.accept(state(5,5,{id:'prompt-a'}));assert.equal(frames.size,0);assert.equal(shown.at(-1),5);
client.accept(state(6,6,{id:'prompt-a'}));assert.equal(frames.size,1);client.accept(state(7,7,null));assert.equal(frames.size,0);assert.equal(shown.at(-1),7,'service withdrawal is an immediate barrier');
client.accept(state(8,8));client.accept(state(9,9,null,'visible error'));assert.equal(shown.at(-1),9);assert.deepEqual(errors,['visible error']);assert.equal(frames.size,0);
client.accept(state(10,10));client.accept(state(11,11,null,'',true));assert.equal(shown.at(-1),11);assert.equal(frames.size,0);client.accept(state(12,12));assert.equal(shown.at(-1),11);presenter.close();
// Exercise the actual generated boot path with deterministic browser primitives.
const bootSource=await readFile(process.argv[4],'utf8');
for(const newline of ['\n','\r\n']) {
const source=bootSource.replace(/\r?\n/g,newline).replace(/^import .*;\r?\n/gm,'')
  .replace("await import('./renderer.mjs')","await standaloneModules()");
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
let bootClient,closed=0,stopped=0,disconnected=0,abortedResult;
const paints=[],services=[],timers=new Map(),events=new Map();
class BootClient extends Client {constructor(...args){super(...args);bootClient=this;}}
class BootRenderer {acceptSnapshot(value){this.accepted=value;}render(value){paints.push(value.value);}destroy(){++closed;}}
const status={textContent:'',hidden:true,addEventListener(){}},viewport={clientWidth:100,clientHeight:100};
const document={querySelector:selector=>selector==='#viewport'?viewport:status};
const window={devicePixelRatio:1,addEventListener(name,run){events.set(name,run);}};
const executeService=(request,options)=>{services.push({request,signal:options.signal});return new Promise(resolve=>{abortedResult=resolve;});};
const setTimer=run=>{timers.set(++next,run);return next;},clearTimer=id=>timers.delete(id);
const servicesFactory=options=>createBrowserServices({...options,host:{document,executeService,AbortController},scheduler:{setTimeout:setTimer,clearTimeout:clearTimer}});
const boot=new AsyncFunction('standaloneModules','executeService','startPolling','createWasmTransport','createBrowserPresenter','createBrowserServices','createEmbeddedFrontend','browserComposition','document','window','location','fetch','ResizeObserver','setTimeout','clearTimeout','AbortController','globalThis',source);
await boot(async()=>({Client:BootClient,Renderer:BootRenderer}),executeService,()=>()=>++stopped,()=>{throw Error('unexpected Wasm branch');},render=>createBrowserPresenter(render,scheduler),servicesFactory,()=>{throw Error('unexpected isolated branch');},browserComposition,document,window,{href:'http://fixture/',reload(){}},async()=>({ok:true,json:async()=>({state:state(0,0,{id:'withdraw-before-open'}),token:'fixture'})}),class {observe(){}disconnect(){++disconnected;}},setTimer,clearTimer,AbortController,{});
const runTimer=async()=>{assert.equal(timers.size,1);const [id,run]=timers.entries().next().value;timers.delete(id);return run();};
bootClient.accept(state(1,1));assert.equal(timers.size,0);assert.equal(services.length,0,'withdrawn deferred prompt must never open');
bootClient.accept(state(2,2,{id:'opened'}));const pending=runTimer();assert.equal(services.length,1);assert.equal(services[0].signal.aborted,false);
bootClient.accept(state(3,3,{id:'opened'}));assert.equal(timers.size,0,'same request must not reissue');
bootClient.accept(state(4,4));assert.equal(services[0].signal.aborted,true);abortedResult({type:'service',id:'opened',status:'ok',value:'late'});await pending;assert.equal(bootClient.queue.length,0);assert.equal(bootClient.ack,4n,'withdrawn late result cannot enter the operation stream');
bootClient.accept(state(5,5,{id:'pagehide'}));const pendingClose=runTimer();events.get('pagehide')();assert.equal(services[1].signal.aborted,true);abortedResult({type:'service',id:'pagehide',status:'ok',value:'late'});await pendingClose;
assert.equal(bootClient.closed,true);assert.equal(closed,1);assert.equal(stopped,1);assert.equal(disconnected,1);assert.equal(frames.size,0);
}
console.log('Visual coalescing preserves ordered receipts, services, errors, closure and LF/CRLF boot teardown');
