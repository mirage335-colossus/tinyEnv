import assert from 'node:assert/strict';
import {Worker} from 'node:worker_threads';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const transportURL=pathToFileURL(resolve(process.argv[2])),workerURL=pathToFileURL(resolve(process.argv[3]));
const {createWasmTransport,MAX_REQUEST_BYTES}=await import(transportURL);
const {installWasmWorker}=await import(workerURL);
const initial={epoch:'test',ack:'0',snapshot:{}};
const flush=async()=>{for(let n=0;n<8;++n)await Promise.resolve();};
let cases=0;
const run=async(name,body)=>{await body();console.log('PASS '+name);++cases;};
function fake(){
  const timers=new Map();let id=0,worker;
  const scheduler={setTimeout(fn){timers.set(++id,fn);return id;},clearTimeout(key){timers.delete(key);}};
  const transport=createWasmTransport({epoch:'test',scheduler,workerFactory:()=>worker={sent:[],terminated:false,postMessage(x){this.sent.push(x);},terminate(){this.terminated=true;}}});
  return {transport,worker,timers,message(value){worker.onmessage?.({data:value});},ready(){this.message({type:'ready',text:JSON.stringify(initial)});}};
}
await run('one outstanding request, byte limits and response identity',async()=>{
  const f=fake();f.ready();assert.deepEqual(await f.transport.ready,initial);
  const request=f.transport.exchange({epoch:'test',seq:'1',operation:{type:'poll'}});
  await assert.rejects(f.transport.exchange({}),/outstanding/);
  const id=f.worker.sent.at(-1).id;f.message({type:'response',id,text:JSON.stringify(initial)});await request;
  await assert.rejects(f.transport.exchange({value:'é'.repeat(MAX_REQUEST_BYTES/2)}),/limit/);
  assert.equal(f.worker.sent.length,2);
  const close=f.transport.close();assert.equal(f.worker.terminated,false);f.message({type:'closed'});assert.deepEqual(await close,{graceful:true});
  assert.equal(f.worker.terminated,true);assert.equal(f.timers.size,0);
});
await run('crash settles pending work and never restarts or replays',async()=>{
  const f=fake();f.ready();await f.transport.ready;const pending=f.transport.exchange({seq:'1'});
  const rejected=assert.rejects(pending,/crashed/);f.worker.onerror({message:'crashed'});await rejected;
  assert.equal(f.transport.state,'failed');assert.equal(f.worker.terminated,true);
  await assert.rejects(f.transport.exchange({seq:'1'}),/new session/);assert.equal(f.worker.sent.length,2);
});
await run('invalid response fails closed and initialization timeout settles',async()=>{
  const f=fake();const rejected=assert.rejects(f.transport.ready,/initialization timed out/);
  f.timers.values().next().value();await rejected;assert.equal(f.worker.terminated,true);
  const g=fake();g.ready();await g.transport.ready;const pending=g.transport.exchange({});
  const bad=assert.rejects(pending,/Unexpected/);g.message({type:'response',id:99,text:'{}'});await bad;
});
await run('close during startup, late responses and bounded forced termination',async()=>{
  const f=fake();const ready=assert.rejects(f.transport.ready,/closed/);const closed=f.transport.close();
  f.ready();assert.equal(f.transport.state,'closing');assert.strictEqual(f.transport.close(),closed);
  f.timers.values().next().value();assert.equal((await closed).graceful,false);await ready;assert.equal(f.worker.terminated,true);
});
await run('failed Worker construction and postMessage cannot strand callers',async()=>{
  const a=createWasmTransport({epoch:'test',workerFactory:()=>{throw Error('construction');}});
  await assert.rejects(a.ready,/construction/);assert.equal(a.state,'failed');
  const b=createWasmTransport({epoch:'test',workerFactory:()=>({postMessage(){throw Error('clone');},terminate(){}})});
  await assert.rejects(b.ready,/clone/);assert.equal(b.state,'failed');
});
await run('Worker rejects overload during init and cleans a late module',async()=>{
  let finish,destroyed=0;const scope={sent:[],postMessage(x){this.sent.push(x);},close(){this.closed=true;}};
  installWasmWorker(scope,async()=>({default:()=>new Promise(resolve=>{finish=resolve;})}));
  const creating=scope.onmessage({data:{type:'init',moduleURL:'test',epoch:'test'}});await flush();
  await scope.onmessage({data:{type:'receive',id:1,text:'{}'}});
  finish({ccall(name){assert.equal(name,'gui_web_destroy');++destroyed;}});await creating;
  assert.equal(destroyed,1);assert.equal(scope.closed,true);assert.equal(scope.sent[0].type,'error');
});
await run('Worker close waits for initialization then destroys without create',async()=>{
  let finish;const calls=[];const scope={sent:[],postMessage(x){this.sent.push(x);},close(){this.closed=true;}};
  installWasmWorker(scope,async()=>({default:()=>new Promise(resolve=>{finish=resolve;})}));
  const creating=scope.onmessage({data:{type:'init',moduleURL:'test',epoch:'test'}});await flush();
  await scope.onmessage({data:{type:'close'}});assert.equal(scope.closed,undefined);
  finish({ccall(name){calls.push(name);}});await creating;assert.deepEqual(calls,['gui_web_destroy']);
  assert.deepEqual(scope.sent,[{type:'closed'}]);assert.equal(scope.closed,true);
});
await run('Worker rejects invalid input and destroys exactly once',async()=>{
  let destroyed=0;const scope={sent:[],postMessage(x){this.sent.push(x);},close(){}};
  installWasmWorker(scope,async()=>({default:async()=>({ccall(name){if(name==='gui_web_destroy'){++destroyed;return;}return JSON.stringify(initial);}})}));
  await scope.onmessage({data:{type:'init',moduleURL:'test',epoch:'test'}});
  await scope.onmessage({data:{type:'receive',id:1,text:'x'.repeat(MAX_REQUEST_BYTES+1)}});
  await scope.onmessage({data:{type:'close'}});assert.equal(destroyed,1);assert.equal(scope.sent.at(-1).type,'error');
});
await run('embedded factory supplies bytes and a Blob-safe Wasm location',async()=>{
  const scope={sent:[],postMessage(x){this.sent.push(x);},close(){}};
  installWasmWorker(scope,async url=>{assert.equal(new URL(url).protocol,'blob:');return {default:async options=>{
    assert.deepEqual(options.wasmBinary,new Uint8Array([0,97,115,109]));
    assert.equal(options.locateFile('gui_web_wasm.wasm'),'gui_web_wasm.wasm');
    return {ccall:name=>name==='gui_web_destroy'?undefined:JSON.stringify(initial)};
  }};});
  await scope.onmessage({data:{type:'init',epoch:'test',factorySource:'fixture',wasmBinary:new Uint8Array([0,97,115,109])}});
  assert.equal(scope.sent[0].type,'ready');await scope.onmessage({data:{type:'close'}});
});
// The real thread intentionally blocks only its synthetic receive handler. A main
// thread timer must fire before completion, independent of machine throughput.
await run('real Worker leaves main event loop responsive and acknowledges destruction',async()=>{
  const factory=`export default async()=>({ccall(name,type,kinds,args){if(name==='gui_web_create')return JSON.stringify({epoch:args[0],ack:'0'});if(name==='gui_web_receive'){const end=Date.now()+150;while(Date.now()<end){};return JSON.stringify({ack:JSON.parse(args[0]).seq});}}});`;
  const url='data:text/javascript,'+encodeURIComponent(factory);
  const threads=[];
  const workerFactory=()=>{
    const bootstrap=`import {parentPort} from 'node:worker_threads';import {installWasmWorker} from ${JSON.stringify(workerURL.href)};const scope={postMessage:x=>parentPort.postMessage(x),close:()=>parentPort.close()};parentPort.on('message',data=>scope.onmessage({data}));installWasmWorker(scope);`;
    const thread=new Worker(new URL('data:text/javascript,'+encodeURIComponent(bootstrap)),{type:'module'});threads.push(thread);
    const wrapper={postMessage:x=>thread.postMessage(x),terminate:()=>thread.terminate()};
    thread.on('message',data=>wrapper.onmessage?.({data}));thread.on('error',error=>wrapper.onerror?.(error));return wrapper;
  };
  const transport=createWasmTransport({epoch:'test',moduleURL:url,workerFactory});
  try{
    await transport.ready;let timer=false;const tick=new Promise(resolve=>setTimeout(()=>{timer=true;resolve();},10));
    let completed=false;const work=transport.exchange({epoch:'test',seq:'1',operation:{type:'poll'}}).then(value=>{completed=true;return value;});await tick;
    assert.equal(timer,true);assert.equal(completed,false,'main timer must run before the blocked Worker operation completes');assert.equal((await work).ack,'1');assert.equal((await transport.close()).graceful,true);
  }finally{await transport.close();await Promise.all(threads.map(thread=>thread.terminate()));}
});
console.log(`${cases} Worker lifecycle, bound and responsiveness cases passed`);
