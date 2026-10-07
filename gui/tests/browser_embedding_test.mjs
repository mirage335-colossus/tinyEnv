import assert from 'node:assert/strict';
import {MessageChannel} from 'node:worker_threads';
import {webcrypto} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {runInNewContext} from 'node:vm';
const {createEmbeddedFrontend}=await import(pathToFileURL(process.argv[2]));
const {browserComposition}=await import(pathToFileURL(process.argv[3]));
const {CHILD_SCRIPT}=await import(new URL('./renderer_child_bundle.mjs',pathToFileURL(process.argv[2])));
const protocol='foundation-renderer-v1';
const flush=async()=>{for(let n=0;n<8;++n)await new Promise(resolve=>setImmediate(resolve));};
assert.equal(browserComposition('file:///app.html#renderer=isolated'),'isolated');
assert.equal(browserComposition('http://localhost/?renderer=standalone'),'standalone');
assert.equal(browserComposition('http://localhost/'),'standalone');
for(const selector of ['?renderer=x','?renderer=isolated&renderer=isolated','?renderer=isolated#renderer=standalone','?renderer=isolated#renderer=isolated'])assert.throws(()=>browserComposition('http://localhost/'+selector),/selector/);
class Element {
  constructor(tag){this.tag=tag;this.style={};this.events=new Map();this.attributes={};this.contentWindow={postMessage(){assert.fail('Parent must never send an endpoint to a replacement WindowProxy');}};}
  addEventListener(kind,callback){(this.events.get(kind)||this.events.set(kind,new Set()).get(kind)).add(callback);}
  removeEventListener(kind,callback){this.events.get(kind)?.delete(callback);}
  setAttribute(name,value){this.attributes[name]=value;}
  emit(kind,event={}){for(const callback of this.events.get(kind)||[])callback(event);}
  remove(){this.removed=true;}
}
const initial={epoch:'SECRET-EPOCH-NEVER-DISPLAYED',ack:'0',error:'',service:null,snapshot:{revision:'1',title:'Fixture',palette:{},width:10,height:10,scale:1,pages:[],activePage:null,widgets:[],measurements:[],keyBindings:[],focus:null,popup:null,closed:false}};
function environment(){
  let next=0;const events=new Map(),timers=new Map(),mount={clientWidth:100,clientHeight:80,append(frame){this.frame=frame;}};
  const host={crypto:webcrypto,devicePixelRatio:1,MessageChannel,document:{createElement:tag=>new Element(tag)},
    setTimeout(run){timers.set(++next,run);return next;},clearTimeout(id){timers.delete(id);},
    addEventListener(kind,callback){(events.get(kind)||events.set(kind,new Set()).get(kind)).add(callback);},removeEventListener(kind,callback){events.get(kind)?.delete(callback);},
    ResizeObserver:class {observe(){}disconnect(){host.disconnected=(host.disconnected||0)+1;}}};
  host.emit=(kind,event)=>{for(const callback of events.get(kind)||[])callback(event);};
  return {host,mount,events,timers};
}
function child(env,frontend,{ack=true}={}){
  const generation=frontend.frame.srcdoc.match(/name="foundation-channel" content="([^"]+)"/)[1];
  const ports=new MessageChannel(),received=[];
  ports.port1.onmessage=event=>{
    received.push(event.data);
    if(event.data.type==='connect')ports.port1.postMessage({protocol,type:'bound',generation});
    if(event.data.type==='state'&&ack)ports.port1.postMessage({protocol,type:'stateAck',generation,revision:event.data.revision});
  };ports.port1.start();
  env.host.emit('message',{source:frontend.frame.contentWindow,origin:'null',data:{protocol,type:'ready',generation},ports:[ports.port2]});
  return {ports,received,generation};
}
{
  const env=environment(),sent=[],statuses=[];let releases=0;
  const frontend=createEmbeddedFrontend({mount:env.mount,initialState:initial,host:env.host,status:value=>statuses.push(value),release:()=>++releases,
    exchange:async envelope=>{sent.push(envelope);return {...initial,ack:envelope.seq};}});
  assert.equal(frontend.frame.attributes.sandbox,'allow-scripts');assert.equal(frontend.frame.attributes['data-foundation-embedded'],'');
  assert(frontend.frame.srcdoc.includes('Content-Security-Policy'));assert(!frontend.frame.srcdoc.includes(initial.epoch));
  const renderer=child(env,frontend);await flush();assert.equal(renderer.received.length,0,'Wait for load before binding initial endpoint');
  frontend.frame.emit('load');await frontend.ready;await flush();assert.equal(renderer.received[0].type,'connect');assert(sent.some(value=>value.operation.type==='resize'));
  env.host.emit('pagehide',{});await flush();assert.equal(releases,1);assert(frontend.frame.removed);assert.equal(env.host.disconnected,1);assert.equal(env.timers.size,0);
  const previous=sent.length;renderer.ports.port1.postMessage({protocol,type:'request',generation:renderer.generation,id:'1',operation:{type:'service',id:'7'}});await flush();assert.equal(sent.length,previous);
  frontend.close();await flush();assert.equal(releases,1);assert.equal(env.events.get('message').size,0);renderer.ports.port1.close();
}
// The original document can announce and navigate before its load. Its endpoint
// is lost; the replacement WindowProxy receives no connect or transferred port.
{
  const env=environment();let releases=0;const statuses=[];
  const frontend=createEmbeddedFrontend({mount:env.mount,initialState:initial,host:env.host,status:message=>statuses.push(message),release:()=>++releases,exchange:async()=>assert.fail('No transport before startup')});
  const renderer=child(env,frontend);renderer.ports.port1.close();frontend.frame.contentWindow={postMessage(){assert.fail('Replacement document received channel');}};
  frontend.frame.emit('load');await flush();assert.equal(renderer.received.length,0);
  [...env.timers.values()][0]();await assert.rejects(frontend.ready,/timed out/);await flush();assert.equal(releases,1);assert.match(statuses[0],/timed out/);
}
{
  const env=environment();let releases=0;
  const frontend=createEmbeddedFrontend({mount:env.mount,initialState:initial,host:env.host,release:()=>++releases,exchange:async envelope=>({...initial,ack:envelope.seq})});
  const renderer=child(env,frontend);frontend.frame.emit('load');await frontend.ready;await flush();frontend.frame.emit('load');await flush();assert(frontend.frame.removed);assert.equal(releases,1);renderer.ports.port1.close();
}
// Shared parent windows may mount independent frontends and use unrelated ports.
// A listener owns only messages originating from its own iframe WindowProxy.
{
  const env=environment();let releases=0;
  const make=()=>createEmbeddedFrontend({mount:{...env.mount},initialState:initial,host:env.host,release:()=>++releases,exchange:async envelope=>({...initial,ack:envelope.seq})});
  const a=make(),b=make(),ar=child(env,a),br=child(env,b);
  let foreignClosed=false;
  env.host.emit('message',{source:{},origin:'null',data:{protocol,type:'ready',generation:ar.generation},ports:[{close(){foreignClosed=true;}}]});
  assert.equal(foreignClosed,false);
  a.frame.emit('load');b.frame.emit('load');await Promise.all([a.ready,b.ready]);await flush();
  assert(ar.received.some(value=>value.type==='state'));assert(br.received.some(value=>value.type==='state'));
  a.close();await flush();assert.equal(releases,1);assert.equal(b.frame.removed,undefined);
  b.close();await flush();assert.equal(releases,2);ar.ports.port1.close();br.ports.port1.close();
}
{
  const env=environment(),frontend=createEmbeddedFrontend({mount:env.mount,initialState:initial,host:env.host,exchange:async()=>assert.fail('Malformed startup reached transport')});
  const generation=frontend.frame.srcdoc.match(/name="foundation-channel" content="([^"]+)"/)[1];
  const malformed=Object.assign([],{protocol,type:'ready',generation}),ports=new MessageChannel();
  env.host.emit('message',{source:frontend.frame.contentWindow,origin:'null',data:malformed,ports:[ports.port2]});
  await assert.rejects(frontend.ready,/startup/);assert(frontend.frame.removed);ports.port1.close();
}
// The generated child entry rejects the same named-property array at connect.
{
  let childPort,closed=false;
  class FakeMessageChannel {constructor(){childPort=this.port1={start(){},close(){closed=true;}};this.port2={};}}
  const context={TextEncoder,MessageChannel:FakeMessageChannel,document:{querySelector:()=>({content:'child-generation'})},parent:{postMessage(){}},addEventListener(){},removeEventListener(){}};
  runInNewContext(CHILD_SCRIPT,context);
  childPort.onmessage({data:Object.assign([],{protocol,type:'connect',generation:'child-generation'}),ports:[]});
  assert.equal(closed,true);
}
console.log('Fixed opaque sandbox, strict selectors, document-owned startup channel, navigation/startup revocation and idempotent teardown passed');
