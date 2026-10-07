import assert from 'node:assert/strict';
import {MessageChannel} from 'node:worker_threads';
import {pathToFileURL} from 'node:url';
const {clonePacket,validateRendererOperation,publicSnapshot,createHostChannel,createRendererRequests} = await import(pathToFileURL(process.argv[2]));
const {Client,MAX_OPERATION_BYTES} = await import(pathToFileURL(process.argv[3]));
const protocol='foundation-renderer-v1',generation='test-generation';
const flush=async()=>{for(let n=0;n<8;++n)await new Promise(resolve=>setImmediate(resolve));};
const key={id:'editor',generation:'1'};
const widget={key,kind:5,text:'old',visible:true,enabled:true,inModal:true,readOnly:false,submit:1,options:[],actions:[],records:[]};
const snapshot=text=>({revision:'1',title:'Fixture',palette:{},width:100,height:100,scale:1,pages:[],activePage:null,widgets:[{...widget,text}],measurements:[{id:'1',request:{text:'measure'}}],keyBindings:[],focus:null,popup:null,closed:false});
const state=(ack,text='old')=>({epoch:'test',ack:String(ack),snapshot:snapshot(text),service:null,error:''});
const sched=()=>{let next=0;const timers=new Map();return {timers,setTimeout(run){timers.set(++next,run);return next;},clearTimeout(id){timers.delete(id);}};};
assert.throws(()=>clonePacket(new Array(100000000)),/structure|Sparse/);
assert.throws(()=>clonePacket(new Array(3)),/Sparse/);
assert.throws(()=>clonePacket({text:'x'.repeat(MAX_OPERATION_BYTES+1)}),/byte limit/);
assert.throws(()=>clonePacket({number:Infinity}),/unsupported/);
assert.throws(()=>validateRendererOperation({type:'service',id:'7'},snapshot('old')),/not delegated/);
assert.throws(()=>validateRendererOperation({type:'editIntent',key,value:'new',base:'forged'},snapshot('old')),/shape/);
assert.throws(()=>validateRendererOperation({type:'measure',values:[{id:'1',width:NaN,height:1}]},snapshot('old')),/measurement/);
assert.throws(()=>validateRendererOperation({type:'measure',values:[{id:'99',width:1,height:1}]},snapshot('old')),error=>error.stale);
assert.throws(()=>validateRendererOperation({type:'editIntent',key:{...key,generation:'2'},value:'new'},snapshot('old')),error=>error.stale);
assert.doesNotThrow(()=>validateRendererOperation({type:'selection',key,anchor:'0',caret:'1'},{...snapshot('old'),widgets:[{...widget,readOnly:true}]}));
assert.doesNotThrow(()=>validateRendererOperation({type:'pointer',key,kind:'press',pointerId:'1',x:0,y:0,wheelX:0,wheelY:0,control:false,shift:false,alt:false},{...snapshot('old'),widgets:[{...widget,pointerInput:true}]}));
assert.deepEqual(publicSnapshot({...snapshot('old'),service:{token:'secret'},epoch:'secret',ack:'4'}),snapshot('old'));
// A queued check runs only at first preparation and has no sequence side effect.
{
  let current=true,checks=0;const sent=[];
  const client=new Client(async envelope=>{sent.push(envelope);return state(envelope.seq);},()=>{});
  client.failed=true;client.accept(state(0));
  const rejected=client.send({type:'poll'},null,()=>{++checks;if(!current)throw Error('obsolete');}).catch(error=>error);
  current=false;client.retry();assert.match((await rejected).message,/obsolete/);assert.equal(client.ack,0n);assert.equal(sent.length,0);assert.equal(checks,1);
  let fail=true;
  client.exchange=async envelope=>{sent.push(JSON.stringify(envelope));if(fail)throw Error('uncertain');return state(envelope.seq);};
  const result=client.send({type:'poll'},null,()=>{++checks;});await flush();assert(client.failed);
  current=false;fail=false;client.retry();await result;assert.equal(checks,2);assert.equal(sent[0],sent[1]);client.close();
}
{
  let client;
  client=new Client(async envelope=>state(envelope.seq),accepted=>{if(accepted.ack==='1')client.close();});
  client.accept(state(0));await assert.rejects(client.send({type:'poll'}),/closed/);assert.equal(client.queuedBytes,0);
}
// State acknowledgments precede completions, while only one state is in flight.
{
  const ports=new MessageChannel(),scheduler=sched(),accepted=[],presented=[],failures=[],sent=[];
  let hostChannel;
  const client=new Client(async envelope=>{sent.push(envelope);return state(envelope.seq,envelope.operation.value ?? 'updated');},value=>hostChannel?.accept(value));
  client.accept(state(0));
  hostChannel=createHostChannel({port:ports.port1,generation,client,scheduler,onBound:()=>hostChannel.accept(client.state),onFailure:error=>failures.push(error)});
  const renderer=createRendererRequests({port:ports.port2,generation,acceptSnapshot:value=>accepted.push(value),present:value=>presented.push(value),onFailure:error=>failures.push(error)});
  await flush();
  const edit=renderer.send({type:'editIntent',key,value:'new'});
  await edit;assert.equal(accepted.at(-1).widgets[0].text,'new');assert.equal(sent[0].operation.base,'old');assert.equal(sent[0].operation.type,'edit');
  await assert.rejects(renderer.send({type:'editIntent',key:{...key,generation:'2'},value:'stale'}),/available/);
  assert.equal(sent.length,1);assert.equal(failures.length,0);
  client.state=state(2,'authoritative');hostChannel.accept(client.state);await flush();
  hostChannel.close();renderer.close();client.close();assert.equal(scheduler.timers.size,0);
}
// A host dialog can finish while its ordered completion is still in flight.
// Input queued behind that completion validates service eligibility at dispatch.
{
  const ports=new MessageChannel(),scheduler=sched(),sent=[];let finishService,hostChannel;
  const client=new Client(envelope=>{
    sent.push(envelope);
    if(envelope.operation.type==='service')return new Promise(resolve=>{finishService=()=>resolve(state(envelope.seq,'after service'));});
    return Promise.resolve(state(envelope.seq,envelope.operation.value));
  },value=>hostChannel?.accept(value));
  client.accept({...state(0),service:{id:'7',kind:2}});
  hostChannel=createHostChannel({port:ports.port1,generation,client,scheduler,onBound:()=>hostChannel.accept(client.state),onFailure:error=>assert.fail(error.message)});
  const renderer=createRendererRequests({port:ports.port2,generation,acceptSnapshot(){},present(){},onFailure:error=>assert.fail(error.message)});
  await flush();
  const completion=client.send({type:'service',id:'7',status:'cancelled',value:'',error:''});
  const edit=renderer.send({type:'editIntent',key,value:'after dialog'});
  await flush();assert.equal(sent.length,1);finishService();await Promise.all([completion,edit]);
  assert.equal(sent[1].operation.type,'edit');assert.equal(sent[1].operation.base,'after service');
  hostChannel.close();renderer.close();client.close();
}
{
  const ports=new MessageChannel(),scheduler=sched();let hostChannel;
  const client=new Client(async()=>assert.fail('Input dispatched while host service remains active'),value=>hostChannel?.accept(value));
  client.accept({...state(0),service:{id:'7',kind:2}});
  hostChannel=createHostChannel({port:ports.port1,generation,client,scheduler,onBound:()=>hostChannel.accept(client.state),onFailure:error=>assert.fail(error.message)});
  const renderer=createRendererRequests({port:ports.port2,generation,acceptSnapshot(){},present(){},onFailure:error=>assert.fail(error.message)});
  await flush();await assert.rejects(renderer.send({type:'editIntent',key,value:'during prompt'}),/host service is active/);assert.equal(client.ack,0n);
  hostChannel.close();renderer.close();client.close();
}
// A stalled renderer retains one packet and only the newest replacement.
{
  const ports=new MessageChannel(),scheduler=sched(),received=[],failures=[];
  const client=new Client(async()=>assert.fail('no exchange'),()=>{});client.accept(state(0));
  const channel=createHostChannel({port:ports.port1,generation,client,scheduler,onBound:()=>channel.accept(client.state),onFailure:error=>failures.push(error)});
  ports.port2.onmessage=event=>received.push(event.data);ports.port2.start();
  ports.port2.postMessage({protocol,type:'bound',generation});await flush();
  for(let n=1;n<=100;++n)channel.accept(state(n,String(n)));
  await flush();assert.equal(received.length,1,'Do not enqueue snapshots behind a stalled child');assert.equal(scheduler.timers.size,1);
  ports.port2.postMessage({protocol,type:'stateAck',generation,revision:received[0].revision});await flush();
  assert.equal(received.length,2);assert.equal(received[1].snapshot.widgets[0].text,'100');
  [...scheduler.timers.values()][0]();assert.match(failures[0].message,/acknowledge/);channel.close();ports.port2.close();client.close();
}
// Unauthorized, duplicate, wrong-generation and oversized packets fail closed.
for(const malicious of [
  {protocol,type:'request',generation,id:'1',operation:{type:'fileRead',id:'7',offset:'0'}},
  {protocol,type:'request',generation:'old',id:'1',operation:{type:'editIntent',key,value:'x'}},
  {protocol,type:'request',generation,id:'2',operation:{type:'editIntent',key,value:'x'}},
  {protocol,type:'request',generation,id:'1',operation:{type:'editIntent',key,value:'x'.repeat(MAX_OPERATION_BYTES)}}
]) {
  const ports=new MessageChannel(),scheduler=sched(),failures=[];
  const client=new Client(async()=>assert.fail('unauthorized exchange'),()=>{});client.accept(state(0));
  const channel=createHostChannel({port:ports.port1,generation,client,scheduler,onFailure:error=>failures.push(error)});
  ports.port2.postMessage({protocol,type:'bound',generation});await flush();ports.port2.postMessage(malicious);await flush();
  assert.equal(failures.length,1);assert.equal(client.ack,0n);channel.close();ports.port2.close();client.close();
}
console.log('Typed current renderer intents, initial-only guards, exact retry, ordered state/completions, bounded stalled state and protocol rejection passed');
