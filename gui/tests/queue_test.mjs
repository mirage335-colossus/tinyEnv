import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {Client,Renderer,MAX_OPERATION_BYTES,MAX_QUEUED_BYTES}=await import(pathToFileURL(process.argv[2]).href);
const state=ack=>({epoch:'queue-session',ack:String(ack),snapshot:{widgets:[]},error:''});
const flush=async()=>{for(let n=0;n<10;++n)await Promise.resolve();};
let cases=0;const run=async(name,fn)=>{await fn();console.log('PASS '+name);++cases;};
await run('total byte bound includes in-flight request and close settles every reservation',async()=>{
  const client=new Client(()=>new Promise(()=>{}),()=>{});client.accept(state(0));
  const calls=[];for(let n=0;n<8;++n)calls.push(client.send(()=>({type:'poll'})).catch(error=>error));
  assert.equal(client.queuedBytes,MAX_QUEUED_BYTES);assert.equal(client.queue.length,7);
  await assert.rejects(client.send(()=>({type:'poll'})),/queue is full/);assert.equal(client.queuedBytes,MAX_QUEUED_BYTES);
  client.close();assert.equal(client.queuedBytes,0);assert((await Promise.all(calls)).every(value=>value instanceof Error));
});
await run('coalesced replacements release old bytes but actions remain barriers',async()=>{
  const client=new Client(async envelope=>state(envelope.seq),()=>{});client.failed=true;client.accept(state(0));
  const a=client.send({type:'edit',value:'x'.repeat(20000)},'edit');const old=client.queuedBytes;
  const b=client.send({type:'edit',value:'small'},'edit');assert(client.queuedBytes<old);assert.equal(client.queue.length,1);
  const action=client.send({type:'activate'});const c=client.send({type:'edit',value:'after'},'edit');assert.equal(client.queue.length,3);
  client.retry();await Promise.all([a,b,action,c]);assert.equal(client.queuedBytes,0);
});
await run('caller mutation cannot change queued payload or identical retry',async()=>{
  const sent=[];let failure=true;const client=new Client(async envelope=>{sent.push(JSON.stringify(envelope));if(failure)throw Error('response lost');return state(envelope.seq);},()=>{});
  const operation={type:'edit',value:'original'};const result=client.send(operation);operation.value='changed';client.accept(state(0));client.pump();await flush();
  assert.equal(client.failed,true);const reserved=client.queuedBytes;assert(reserved>0);failure=false;client.retry();await result;
  assert.equal(sent.length,2);assert.equal(sent[0],sent[1]);assert.equal(JSON.parse(sent[0]).operation.value,'original');assert.equal(client.queuedBytes,0);
});
await run('oversized and cyclic objects rejected before queue retention',async()=>{
  const client=new Client(async()=>assert.fail('must not exchange'),()=>{});
  await assert.rejects(client.send({value:'é'.repeat(MAX_OPERATION_BYTES/2)}),/byte limit/);
  const cycle={};cycle.cycle=cycle;await assert.rejects(client.send(cycle),/circular/i);
  assert.equal(client.queue.length,0);assert.equal(client.queuedBytes,0);
});
await run('throwing or oversized dynamic operation rejects its callers without losing later actions',async()=>{
  const sent=[];const client=new Client(async envelope=>{sent.push(envelope);return state(envelope.seq);},()=>{});
  const bad=client.send(()=>{throw Error('bad dynamic input');}).catch(error=>error);
  const huge=client.send(()=>({value:'x'.repeat(MAX_OPERATION_BYTES)})).catch(error=>error);
  const good=client.send({type:'poll'});client.accept(state(0));client.pump();
  assert.match((await bad).message,/bad dynamic/);assert.match((await huge).message,/byte limit/);await good;
  assert.equal(sent.length,1);assert.equal(sent[0].seq,'1');assert.equal(client.failed,false);assert.equal(client.queuedBytes,0);
});
await run('oversized provisional editor text is restored without capturing a dynamic closure',async()=>{
  const operations=[];const renderer=Object.create(Renderer.prototype);renderer.editVersion=0;renderer.pendingEdits=new Map();
  renderer.send=operation=>{operations.push(operation);return Promise.reject(Error('oversized'));};
  const entry={widget:{key:{id:'editor',generation:'1'},text:'authoritative'},control:{value:'x'.repeat(MAX_OPERATION_BYTES)}};
  renderer.edit(entry);await flush();assert.equal(entry.control.value,'authoritative');assert.equal(renderer.pendingEdits.size,0);
  assert.equal(operations.length,1);assert.equal(typeof operations[0],'object');
});
console.log(`${cases} bounded ordered queue cases passed`);
