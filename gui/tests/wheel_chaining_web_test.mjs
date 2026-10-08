import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {Renderer,identity}=await import(pathToFileURL(resolve(process.argv[2])));

const group=(id,parent='',values={})=>({key:{id,generation:'1'},kind:0,parent,
  visible:true,enabled:true,inModal:true,bounds:[0,0,100,100],contentSize:[100,500],scroll:[0,50],...values});
// Actual native child metrics determine wheel ownership. Logical group bounds
// use shared metadata, since their DOM objects are siblings rather than parents.
function exercise({kind=5,readOnly=true,metrics={},groups=[group('outer')],deltaX=0,deltaY=40,
                   target='control',eventValues={},childValues={}}={}) {
  const child={key:{id:'child',generation:'1'},kind,readOnly,parent:groups.at(-1).key.id,...childValues};
  const node={dataset:{key:identity(child.key)}};
  const control={clientWidth:100,clientHeight:100,scrollWidth:100,scrollHeight:100,scrollLeft:0,scrollTop:0,
    value:'Untouched text',selectionStart:2,selectionEnd:8,...metrics};
  const descendant={};
  control.contains=value=>value===descendant;
  const selected=target==='control'?control:target==='descendant'?descendant:{};
  selected.closest=selector=>selector==='.widget'?node:selector==='select'&&target==='select'?selected:null;
  const entry={widget:child,control,node},operations=[];
  const renderer={snapshot:{widgets:[...groups,child]},nodes:new Map([[identity(child.key),entry]]),
    operation:(...arguments_)=>{operations.push(arguments_);return Promise.resolve({});}};
  const event={target:selected,deltaX,deltaY,ctrlKey:false,defaultPrevented:false,
    preventDefault(){this.defaultPrevented=true;},...eventValues};
  Renderer.prototype.groupWheel.call(renderer,event);
  assert.equal(control.value,'Untouched text');assert.equal(control.selectionStart,2);assert.equal(control.selectionEnd,8);
  return {operations,event,control};
}
function routed(result,target,x,y) {
  assert.equal(result.event.defaultPrevented,true,'a logical ancestor scroll must own the default event');
  assert.equal(result.operations.length,1,'one wheel may scroll only one logical ancestor');
  const [widget,type,offset,coalesce]=result.operations[0];
  assert.equal(widget.key.id,target);assert.equal(type,'scroll');assert.deepEqual(offset,{x,y});
  assert.equal(coalesce,`scroll:${identity(widget.key)}`);
}
function native(result) {
  assert.equal(result.event.defaultPrevented,false,'native scrolling must keep its default event');
  assert.equal(result.operations.length,0,'native-owned or exhausted wheel input must not send a group request');
}
for(const kind of [5,6])for(const readOnly of [false,true]) {
  routed(exercise({kind,readOnly}),'outer',0,90);
  native(exercise({kind,readOnly,metrics:{scrollHeight:250,scrollTop:60}}));
  routed(exercise({kind,readOnly,metrics:{scrollHeight:250,scrollTop:150}}),'outer',0,90);
  routed(exercise({kind,readOnly,metrics:{scrollHeight:250,scrollTop:0},deltaY:-40}),'outer',0,10);
  native(exercise({kind,readOnly,metrics:{scrollHeight:250,scrollTop:60},deltaY:-40}));
}
// Rows inside a native list keep list scrolling; its non-control frame can
// route directly to the logical parent even when the list itself has room.
native(exercise({kind:6,target:'descendant',metrics:{scrollHeight:250,scrollTop:60}}));
routed(exercise({kind:6,target:'descendant',metrics:{scrollHeight:250,scrollTop:150}}),'outer',0,90);
routed(exercise({kind:6,target:'frame',metrics:{scrollHeight:250,scrollTop:60}}),'outer',0,90);
// A code editor with horizontal room keeps the entire diagonal native stroke.
native(exercise({metrics:{scrollWidth:300,scrollLeft:40},deltaX:40,deltaY:40}));
native(exercise({metrics:{scrollWidth:300,scrollLeft:40},deltaX:-40,deltaY:40}));
routed(exercise({metrics:{scrollWidth:300,scrollLeft:200},deltaX:40}),'outer',0,90);
// Browser overscroll outside the native extent cannot advertise false room.
routed(exercise({metrics:{scrollHeight:250,scrollTop:180}}),'outer',0,90);
routed(exercise({metrics:{scrollHeight:250,scrollTop:-10},deltaY:-40}),'outer',0,10);
native(exercise({metrics:{clientWidth:0}}));native(exercise({metrics:{clientHeight:0}}));
native(exercise({target:'select'}));native(exercise({kind:4,target:'select'}));
native(exercise({eventValues:{ctrlKey:true}}));
const consumed=exercise({eventValues:{defaultPrevented:true}});
assert.equal(consumed.event.defaultPrevented,true);assert.equal(consumed.operations.length,0);
for(const delta of [{deltaX:0,deltaY:0},{deltaX:NaN},{deltaY:Infinity}])native(exercise(delta));
// Nested groups at either bound or with fitting content yield to an outer one.
const outer=group('outer'),inner=group('inner','outer',{contentSize:[100,250],scroll:[0,150]});
routed(exercise({groups:[outer,inner]}),'outer',0,90);
routed(exercise({groups:[outer,{...inner,scroll:[0,0]}],deltaY:-40}),'outer',0,10);
routed(exercise({groups:[outer,{...inner,contentSize:[80,80],scroll:[0,0]}]}),'outer',0,90);
routed(exercise({groups:[outer,{...inner,scroll:[0,60]}]}),'inner',0,100);
routed(exercise({groups:[outer,{...inner,enabled:false}]}),'outer',0,90);
native(exercise({groups:[{...outer,scroll:[0,400]},inner]}));
native(exercise({groups:[{...outer,scroll:[0,0]},{...inner,scroll:[0,0]}],deltaY:-100}));
// Group clamps match intersect(local bounds, contentClip), including a valid
// child viewport extending partly outside its group frame.
const clipped=group('clipped','outer',{contentClip:[-20,50,100,80],contentSize:[200,200],scroll:[100,140]});
routed(exercise({groups:[outer,clipped],deltaX:40}),'clipped',120,150);
routed(exercise({groups:[outer,{...clipped,scroll:[120,150]}]}),'outer',0,90);
// Native group scrollbar gutters must not create movement that the shared
// declared viewport would clamp to zero. No negative offsets are sent either.
native(exercise({groups:[group('fit','',{contentSize:[100,100],scroll:[0,0]})],deltaX:40,deltaY:0}));
routed(exercise({groups:[{...outer,scroll:[0,20]}],deltaY:-100}),'outer',0,0);
routed(exercise({eventValues:{deltaMode:1}}),'outer',0,90); // Preserve existing raw-delta policy.

// Use the real raw-pointer closure and root wheel listener on one mutable
// bubbling event, proving that chaining does not duplicate a consumed bitmap.
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.events=new Map();this.children=[];this.style={};this.dataset={};}
  append(child){this.children.push(child);child.parent=this;}
  setAttribute(){}
  addEventListener(kind,callback,options){const list=this.events.get(kind)||[];list.push({callback,capture:options===true||options?.capture===true});this.events.set(kind,list);}
  getBoundingClientRect(){return {left:10,top:20};}
  closest(selector){for(let node=this;node;node=node.parent)if(selector==='.widget'?node.className?.split(' ').includes('widget'):selector==='select'&&node.tagName==='SELECT')return node;return null;}
  emit(kind,values={}) {
    const event={target:this,clientX:40,clientY:50,deltaX:20,deltaY:100,ctrlKey:true,shiftKey:false,altKey:false,
      preventDefault(){this.defaultPrevented=true;},...values};
    const path=[];for(let node=this;node;node=node.parent)path.push(node);
    for(const node of [...path].reverse())for(const item of node.events.get(kind)||[])if(item.capture)item.callback(event);
    for(const node of path)for(const item of node.events.get(kind)||[])if(!item.capture)item.callback(event);
    return event;
  }
}
const document={createElement:tag=>new Element(tag),addEventListener(){},defaultView:new Element()};
const root=new Element(),pages=new Element(),sent=[];
const renderer=new Renderer(root,pages,async operation=>{sent.push(operation);return {};},document);
const bitmap={key:{id:'raw',generation:'1'},kind:7,parent:'outer',pointerInput:true,actions:[]};
const raw=renderer.create(bitmap);renderer.nodes.set(identity(bitmap.key),raw);renderer.snapshot={widgets:[outer,bitmap]};
const wheel=raw.control.emit('wheel');
assert.equal(wheel.defaultPrevented,true);assert.equal(sent.length,1);
assert.deepEqual(sent[0],{type:'pointer',key:bitmap.key,kind:'wheel',pointerId:'0',x:30,y:30,
  wheelX:.2,wheelY:-1,control:true,shift:false,alt:false},'raw wheel ownership and right/up sign convention must remain exact');
console.log('Native text/list ownership, bounded logical ancestor chaining, clipped/nested groups, native selects and raw bitmap wheel passed');
