import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {readTextFile, executeFileService, uploadTextFile, downloadTextFile} = await import(pathToFileURL(process.argv[2]));
const encode = text => new TextEncoder().encode(text).buffer;
const file = text => ({size: encode(text).byteLength, slice: () => ({arrayBuffer: async () => encode(text)})});
assert.equal(await readTextFile(file('a\nb'),3),'a\nb');
// Preserve a leading BOM as content, matching the native host byte path.
assert.equal(await readTextFile(file('\ufefffirst\n'),9),'\ufefffirst\n');
await assert.rejects(readTextFile(file('abcd'),3), /no larger/);
await assert.rejects(readTextFile({size: 0, slice:()=>({arrayBuffer:async()=>encode('abcd')})},3),/exceeds/);
await assert.rejects(readTextFile({size: 1, slice:()=>({arrayBuffer:async()=>new Uint8Array([255]).buffer})},3));
class Element {
  constructor(tag) { this.tag=tag;this.children=[];this.listeners={};this.open=false;this.disabled=false; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute() {} focus() {} remove() {this.removed=true;}
  addEventListener(name, handler) {(this.listeners[name] ||= []).push(handler);}
  fire(name) {for(const handler of this.listeners[name]||[])handler({preventDefault(){},stopPropagation(){}});}
  showModal() {this.open=true;} close() {this.open=false;this.fire('close');}
  click() {this.clicked=true;this.fire('click');}
}
function environment() {
 const nodes=[],revoked=[],timers=[];
 const document={body:new Element('body'),activeElement:null,createElement(tag){const e=new Element(tag);nodes.push(e);return e;},querySelector(){return null;}};
 document.defaultView={Blob, URL:{createObjectURL(){return 'blob:owned';},revokeObjectURL(url){revoked.push(url);}},setTimeout(fn){timers.push(fn);}};
 return {document,nodes,revoked,timers};
}
const request={id:'7',kind:5,title:'Import',value:'',byteLimit:'32'};
{
 const env=environment(),controller=new AbortController();
 let release;const pending=new Promise(resolve=>release=resolve);
 const result=executeFileService(request,{document:env.document,signal:controller.signal});
 env.nodes.find(n=>n.tag==='input').files=[{size:3,slice:()=>({arrayBuffer:()=>pending})}];
 env.nodes.find(n=>n.tag==='form').fire('submit'); controller.abort();
 assert.equal((await result).status,'cancelled');assert.ok(env.nodes[0].removed);
 release(encode('old'));await pending;await Promise.resolve();
 assert.ok(env.nodes[0].removed,'Late file completion resurrected dialog');
}
{
 const env=environment(),controller=new AbortController();controller.abort();
 assert.equal((await executeFileService(request,{document:env.document,signal:controller.signal})).status,'cancelled');
 assert.equal(env.document.body.children.length,0);
}
{
 const env=environment();const result=executeFileService({...request,kind:6,value:'abc'},{document:env.document});
 env.nodes.find(n=>n.tag==='form').fire('submit');
 assert.equal((await result).status,'success');assert.ok(env.nodes.find(n=>n.tag==='a').clicked);
 assert.equal(env.revoked.length,0);env.timers.forEach(fn=>fn());assert.deepEqual(env.revoked,['blob:owned']);
}
{
 const env=environment();const result=executeFileService(request,{document:env.document});
 env.nodes.find(n=>n.tag==='input').files=[file('line')];env.nodes.find(n=>n.tag==='form').fire('submit');
 assert.equal((await result).value,'line');
}
console.log('Bounded UTF-8 files, withdrawal, late completion and user-triggered download passed');

{
 const data=new TextEncoder().encode('x'.repeat(4095)+'é'+'y'.repeat(100));
 const sliced={size:data.length,slice:(start,end)=>({arrayBuffer:async()=>data.slice(start,end).buffer})};
 const operations=[];
 const service={...request,byteLimit:'65536',chunked:true};
 const exchange=async operation=>{operations.push(operation);return {error:'',service};};
 assert.deepEqual(await uploadTextFile(sliced,service,exchange),{type:'fileFinish',id:service.id});
 assert.equal(operations[0].type,'fileBegin');assert.equal(operations[1].hex.length,8192);assert.equal(operations[2].offset,'4096');
 await assert.rejects(uploadTextFile({size:2,slice:()=>({arrayBuffer:async()=>new Uint8Array([1]).buffer})},service,exchange),/truncated/);
 await assert.rejects(uploadTextFile(sliced,service,async()=>({error:'Stale file transfer',service})),/Stale/);
 const controller=new AbortController();controller.abort();await assert.rejects(uploadTextFile(sliced,service,exchange,controller.signal),/cancelled/);
 const exporting={...service,kind:6,byteSize:String(data.length)};
 const download=async operation=>({error:'',service:exporting,transfer:{id:service.id,offset:operation.offset,total:String(data.length),hex:Array.from(data.slice(Number(operation.offset),Number(operation.offset)+4096),x=>x.toString(16).padStart(2,'0')).join('')}});
 const chunks=await downloadTextFile(exporting,download);assert.equal(chunks.length,2);assert.deepEqual(new Uint8Array(await new Blob(chunks).arrayBuffer()),data);
 await assert.rejects(downloadTextFile(exporting,async operation=>({...await download(operation),transfer:{id:'wrong'}})),/identity/);
 const env=environment();const result=executeFileService(exporting,{document:env.document,exchange:download});
 assert.equal(env.nodes.find(n=>n.tag==='button'&&n.type==='submit').disabled,true,'Download enabled before chunks arrived');
 for(let i=0;i<12;i++)await Promise.resolve();
 assert.equal(env.nodes.find(n=>n.tag==='button'&&n.type==='submit').disabled,false);
 env.nodes.find(n=>n.tag==='form').fire('submit');assert.equal((await result).status,'success');
}
console.log('Acknowledged bounded import/export chunks, split UTF-8, cancellation and download activation passed');
