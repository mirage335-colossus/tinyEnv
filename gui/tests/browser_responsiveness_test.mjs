import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {Renderer,identity}=await import(pathToFileURL(resolve(process.argv[2])));
let clock=0, probeCost=0, hidden=false, next=0, probes=0, created=0;
const frames=new Map(), view={addEventListener(){},performance:{now:()=>clock},
  requestAnimationFrame(run){frames.set(++next,run);return next;},cancelAnimationFrame(id){frames.delete(id);}};
const advance=()=>{assert.equal(frames.size,1);const [id,run]=frames.entries().next().value;frames.delete(id);run();};
class Element {
  constructor(document){this.ownerDocument=document;this.children=[];this.dataset={};this.attributes={};this.events={};this.style={setProperty:(key,value)=>this.style[key]=value};this.scrollLeft=0;this.scrollTop=0;}
  append(child){child.remove();this.children.push(child);child.parent=this;}
  insertBefore(child,before){child.remove();const index=before?this.children.indexOf(before):this.children.length;this.children.splice(index,0,child);child.parent=this;}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(value=>value!==this);this.parent=null;}
  replaceChildren(){for(const child of [...this.children])child.remove();}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(name,run){(this.events[name]??=[]).push(run);}
  emit(name){for(const run of this.events[name]??[])run({});}
  focus(){this.ownerDocument.activeElement=this;}
  getBoundingClientRect(){++probes;clock+=probeCost;return {width:100,height:hidden?0:18};}
}
const document={defaultView:view,addEventListener(){},createElement(){++created;return new Element(this);}};
document.body=document.createElement();
const sent=[];let rejectSend=false;
const renderer=new Renderer(document.createElement(),document.createElement(),operation=>{
  sent.push(operation);return rejectSend?Promise.reject(Error('queue full')):Promise.resolve({});
},document);
const font={size:14,bold:false,tone:0};
const requests=(start,count)=>Array.from({length:count},(_,offset)=>({id:String(start+offset),request:{text:'Text',font,wrap:false,width:100}}));
const initialCreated=created;
renderer.measure(requests(1,150));
assert.equal(probes,64,'cheap probes must be bounded by count');
assert.equal(sent[0].values.length,64);assert.equal(frames.size,1);
const probe=renderer.measureProbe;
advance();assert.equal(probes,128);advance();assert.equal(probes,150);assert.equal(frames.size,0);
assert.equal(created,initialCreated+1,'reuse one hidden probe across all batches');assert.equal(renderer.measureProbe,probe);
renderer.measure(requests(1000,2));assert.equal(renderer.measurements.size,2,'retired backend ids must leave the cache');
assert.deepEqual([...renderer.measurements],['1000','1001']);
probeCost=2;const beforeSlow=probes;renderer.measure(requests(2000,7));
assert.equal(probes-beforeSlow,2,'yield once four milliseconds of layout work elapsed');
advance();advance();advance();assert.equal(probes-beforeSlow,7);
renderer.measure([{id:'wrap',request:{font,text:'wrapped',wrap:true,width:37}}]);assert.equal(probe.style.width,'37px');
renderer.measure([{id:'plain',request:{font,text:'',wrap:false,width:90}}]);assert.equal(probe.style.width,'');assert.equal(sent.at(-1).values[0].width,0);
probeCost=0;hidden=true;const beforeHidden=probes;renderer.measure(requests(3000,150));
advance();advance();assert.equal(probes-beforeHidden,150);assert.equal(frames.size,0,'zero geometry must not create an endless retry loop');
assert.equal(renderer.measurements.size,0);hidden=false;renderer.measure(requests(3000,150));advance();advance();assert.equal(renderer.measurements.size,150);
rejectSend=true;renderer.measure(requests(4000,1));await Promise.resolve();assert.equal(renderer.measurements.size,0,'rejected sends are eligible for a later retry');rejectSend=false;renderer.measure(requests(4000,1));assert.equal(renderer.measurements.size,1);
renderer.measure(requests(5000,150));assert.equal(frames.size,1);renderer.measure([]);assert.equal(frames.size,0);assert.equal(renderer.measureProbe,null);assert.equal(document.body.children.length,0);
const common={key:{id:'records',generation:'1'},kind:6,bounds:[0,0,160,90],clip:[0,0,160,90],visible:true,enabled:true,inModal:true,label:'Records',text:'',font,help:'',accessibleName:'',placeholder:'Empty',contentSize:[200,0],rowHeight:22,scroll:[0,0],selected:null};
const row=(id,text)=>({id,text,enabled:true,cells:[{text,bounds:[0,0,100,20],font,wrap:false}]});
const snap=records=>({title:'Fixture',palette:{},width:200,height:100,pages:[],widgets:[{...common,records}],focus:null,closed:false,measurements:[],keyBindings:[]});
renderer.render(snap([row('a','A'),row('b','B')]));const entry=renderer.nodes.get(identity(common.key));const a=entry.recordRows.get('a').node,b=entry.recordRows.get('b').node,cell=a.children[0];
renderer.render({...snap([row('b','B updated'),row('a','A updated')]),widgets:[{...common,selected:'b',records:[row('b','B updated'),row('a','A updated')]}]});
assert.deepEqual(entry.rows.children,[b,a]);assert.equal(a.children[0],cell);assert.equal(cell.textContent,'A updated');assert.equal(b.attributes['aria-selected'],'true');
a.emit('click');assert.equal(sent.at(-1).id,'a');
renderer.render(snap([row('b','B')]));const count=sent.length;a.emit('click');assert.equal(sent.length,count,'retired row callbacks must not act on a replacement row');
renderer.render(snap([]));assert.equal(entry.recordRows.size,0);assert.equal(entry.rows.children[0].textContent,'Empty');
renderer.render({...snap([]),widgets:[{...common,records:[],placeholder:'Nothing available'}]});assert.equal(entry.rows.children[0].textContent,'Nothing available');
renderer.render(snap([row('a','New A')]));assert.equal(entry.rows.children.length,1);assert.notEqual(entry.recordRows.get('a').node,a);a.emit('dblclick');assert.equal(sent.length,count);
// An accepted edit acknowledgment can precede its visual frame. Never restore
// the old painted value or steal focus using that older snapshot.
const acceptedRenderer=new Renderer(document.createElement(),document.createElement(),()=>Promise.resolve({}),document);
const editKey={id:'editor',generation:'1'}, acceptedKey={id:'not-painted-yet',generation:'1'};
acceptedRenderer.snapshot={widgets:[{key:editKey,text:'old painted text'}],focus:null};
acceptedRenderer.acceptSnapshot({widgets:[{key:editKey,text:'accepted text'}],focus:acceptedKey});
let acknowledge;acceptedRenderer.send=()=>new Promise(resolve=>{acknowledge=resolve;});
const editor={value:'typed text',selectionStart:0,selectionEnd:0};
const editEntry={widget:{key:editKey},control:editor,lastSelection:[0,0]};
acceptedRenderer.edit(editEntry);acknowledge({});await Promise.resolve();
assert.equal(editor.value,'accepted text','edit completion must use accepted state before paint');
acceptedRenderer.syncFocus();assert.equal(acceptedRenderer.lastFocus,null,'unpainted focus must remain eligible for the next frame');
const focusControl=document.createElement();acceptedRenderer.nodes.set(identity(acceptedKey),{control:focusControl});acceptedRenderer.syncFocus();
assert.equal(document.activeElement,focusControl);assert.equal(acceptedRenderer.lastFocus,identity(acceptedKey));acceptedRenderer.destroy();
renderer.measure(requests(6000,150));assert.equal(frames.size,1);renderer.destroy();assert.equal(frames.size,0);assert.equal(renderer.measureProbe,null);assert.equal(renderer.measurements.size,0);renderer.measure(requests(7000,1));assert.equal(frames.size,0);renderer.destroy();
console.log('Bounded timed measurements, live cache/probe lifecycle, retries and keyed retained rows passed');
