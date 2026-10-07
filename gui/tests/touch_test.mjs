import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {Renderer}=await import(pathToFileURL(process.argv[2]).href);
class Element {
  constructor(){this.events=new Map();this.style={};this.dataset={};this.children=[];}
  append(child){this.children.push(child);child.parent=this;}
  setAttribute(){}
  addEventListener(kind,callback,capture=false){const list=this.events.get(kind)||[];list.push({callback,capture:capture===true});this.events.set(kind,list);}
  getBoundingClientRect(){return {left:10,top:20};}
  setPointerCapture(id){this.captured=id;}
  emit(kind,values={}) {
    let stopped=false;const event={pointerId:0,isPrimary:true,button:0,clientX:40,clientY:50,ctrlKey:false,shiftKey:false,altKey:false,
      preventDefault(){this.defaultPrevented=true;},stopImmediatePropagation(){stopped=true;},...values};
    const path=[];for(let node=this;node;node=node.parent)path.push(node);
    for(const node of [...path].reverse())for(const item of node.events.get(kind)||[])if(item.capture&&!stopped)item.callback(event);
    for(const node of path)for(const item of node.events.get(kind)||[])if(!item.capture&&!stopped)item.callback(event);
  }
}
const document={createElement(){return new Element();},addEventListener(){},defaultView:new Element()};
const root=new Element(),pages=new Element(),sent=[];
const renderer=new Renderer(root,pages,async op=>{sent.push(op);return {};},document);
const raw=renderer.create({kind:2,key:{id:'raw',generation:'1'},pointerInput:true});
raw.node.emit('pointerdown');
raw.node.emit('pointerdown',{pointerId:2,isPrimary:false});
raw.node.emit('pointerup',{pointerId:2,isPrimary:false});
raw.node.emit('pointermove',{clientX:-20,clientY:-10});
raw.node.emit('pointerup',{clientX:300,clientY:400});
raw.node.emit('lostpointercapture');raw.control.emit('click');raw.control.emit('dblclick');
assert.deepEqual(sent.map(op=>op.kind),['press','move','release','double']);
assert.equal(sent[3].pointerId,'0');
assert.equal(sent[0].pointerId,'1','zero browser contact must receive nonzero shared identity');
assert(sent.slice(0,3).every(op=>op.pointerId==='1'));
assert.equal(sent[1].x,-30);assert.equal(sent[2].y,380);
raw.node.emit('pointerdown');raw.node.emit('pointercancel');raw.node.emit('lostpointercapture');raw.node.emit('pointerup');
raw.control.emit('dblclick');
assert.deepEqual(sent.slice(4).map(op=>op.kind),['press','cancel']);
assert.equal(sent[4].pointerId,'2','reused platform contact must have fresh gesture identity');
raw.node.emit('pointerdown');raw.node.emit('lostpointercapture');
assert.deepEqual(sent.slice(6).map(op=>op.kind),['press','cancel']);
raw.node.emit('pointerdown');document.defaultView.emit('blur');raw.control.emit('dblclick');raw.node.emit('pointerup');
assert.deepEqual(sent.slice(8).map(op=>op.kind),['press','cancel']);
raw.node.emit('pointerdown');document.defaultView.emit('pagehide');raw.control.emit('dblclick');raw.node.emit('pointerup');
assert.deepEqual(sent.slice(10).map(op=>op.kind),['press','cancel']);
const ordinary=renderer.create({kind:2,key:{id:'native',generation:'1'},pointerInput:false});
ordinary.node.emit('pointerdown');ordinary.node.emit('pointerup');ordinary.control.emit('click');
assert.equal(sent.at(-1).type,'activate','ordinary native click must remain semantic');
assert.equal(sent.length,13);
const failed=renderer.create({kind:1,key:{id:'capture-fails',generation:'1'},pointerInput:true});
failed.node.setPointerCapture=()=>{throw Error('no capture');};failed.node.emit('pointerdown');failed.node.emit('pointerup');
assert.equal(sent.length,13,'uncaptured raw gesture must not activate');
console.log('Browser raw capture, outside coordinates, cancellation, duplicate suppression and native clicks passed');
