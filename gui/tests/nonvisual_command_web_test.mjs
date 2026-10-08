import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {Renderer,identity}=await import(pathToFileURL(resolve(process.argv[2])));

// This DOM models one mutable event through document capture and the native
// control's handlers. It observes generic renderer mechanics, not browser UI.
class Element {
  constructor(document,tag='div') {
    this.ownerDocument=document;this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};
    this.events=new Map();this.style={setProperty:(key,value)=>this.style[key]=value};this.scrollLeft=0;this.scrollTop=0;
    this.value='';this.selectionStart=0;this.selectionEnd=0;this.selectionDirection='forward';
  }
  append(child){child.remove();this.children.push(child);child.parent=this;}
  insertBefore(child,before){child.remove();const index=before?this.children.indexOf(before):this.children.length;this.children.splice(index,0,child);child.parent=this;}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(value=>value!==this);this.parent=null;}
  replaceChildren(){for(const child of [...this.children])child.remove();}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(kind,callback,options){const list=this.events.get(kind)||[];list.push({callback,capture:options===true||options?.capture===true});this.events.set(kind,list);}
  removeEventListener(kind,callback){this.events.set(kind,(this.events.get(kind)||[]).filter(item=>item.callback!==callback));}
  setSelectionRange(start,end,direction){this.selectionStart=start;this.selectionEnd=end;this.selectionDirection=direction;}
  focus(){this.ownerDocument.activeElement=this;}
  blur(){this.ownerDocument.activeElement=null;}
  emit(kind,values={}) {
    let stopped=false;
    const event={key:'',isComposing:false,ctrlKey:false,shiftKey:false,altKey:false,
      preventDefault(){this.defaultPrevented=true;},stopImmediatePropagation(){stopped=true;},...values};
    const path=[];for(let node=this;node;node=node.parent)path.push(node);
    for(const node of [...path].reverse())for(const item of node.events.get(kind)||[])if(item.capture&&!stopped)item.callback(event);
    for(const node of path)for(const item of node.events.get(kind)||[])if(!item.capture&&!stopped)item.callback(event);
    return event;
  }
}
const document=new Element(null);document.ownerDocument=document;
document.defaultView=new Element(document);document.createElement=tag=>new Element(document,tag);
document.body=document.createElement('body');document.body.parent=document;
const root=document.createElement('div'),pages=document.createElement('div');document.body.append(root);document.body.append(pages);
const sent=[];
const renderer=new Renderer(root,pages,operation=>{sent.push(operation);return Promise.resolve({});},document);
const font={size:14,bold:false,tone:0};
const widget=(id,overrides={})=>({key:{id,generation:'1'},kind:5,parent:'',page:'',bounds:[0,0,180,30],clip:[0,0,180,30],
  visible:true,enabled:true,inModal:true,label:'',text:'Ordinary editing',help:'',accessibleName:'',placeholder:'',font,
  wrap:false,readOnly:false,multiline:false,masked:false,options:[],actions:[],records:[],selection:[0,0],scroll:[0,0],scrollRevision:'0',
  submit:1,pointerInput:false,contextInput:false,rowHeight:20,contentSize:[180,0],...overrides});
const first=widget('first'),second=widget('second',{bounds:[0,40,180,30],clip:[0,40,180,30]});
const list=widget('list',{kind:6,bounds:[0,80,180,50],clip:[0,80,180,50],records:[{id:'row',text:'Row',enabled:true,activatable:true,cells:[]}]});
const undo={key:{id:'command.undo',generation:'1'},enabled:true,scope:first.key};
const redo={key:{id:'command.redo',generation:'1'},enabled:false,scope:first.key};
const other={key:{id:'command.other',generation:'1'},enabled:true,scope:second.key};
const listCommand={key:{id:'command.list',generation:'1'},enabled:true,scope:list.key};
const binding=(key,target,focus,shift=false)=>({key,target,focus,control:true,shift,alt:false});
const view={title:'Nonvisual fixture',palette:{},width:200,height:160,pages:[],widgets:[first,second,list],focus:null,
  closed:false,measurements:[],popup:null,commands:[undo,redo,other,listCommand],keyBindings:[
    binding(14,undo.key,first.key),binding(14,redo.key,first.key,true),binding(15,redo.key,first.key),
    binding(14,other.key,second.key),{...binding(1,listCommand.key,list.key),control:false}]};
const present=snapshot=>{renderer.acceptSnapshot(snapshot);renderer.render(snapshot);};
const allNodes=node=>[node,...node.children.flatMap(allNodes)];
present(view);
assert.equal(renderer.nodes.size,view.widgets.length,'commands must not create retained DOM controls');
for(const command of view.commands){
  assert.equal(renderer.nodes.has(identity(command.key)),false,'command identities must not have DOM entries');
  assert(!allNodes(root).some(node=>node.dataset.key===identity(command.key)),'commands must not create paint, hit, click or tab targets');
}
assert.equal(allNodes(root).filter(node=>node.tagName==='BUTTON').length,0,'commands must not create invisible buttons');
let firstControl=renderer.nodes.get(identity(first.key)).control;
const secondControl=renderer.nodes.get(identity(second.key)).control;
let nativeUndo=0;
const observeNativeUndo=control=>control.addEventListener('keydown',event=>{
  if(!event.defaultPrevented&&event.ctrlKey&&['z','y'].includes(event.key.toLowerCase()))++nativeUndo;
});
observeNativeUndo(firstControl);observeNativeUndo(secondControl);
const stroke=(control,key='z',overrides={})=>control.emit('keydown',{key,ctrlKey:true,...overrides});
firstControl.focus();
for(const [key,shift] of [['z',false],['Z',true],['y',false]]){
  const before=sent.length;assert.equal(stroke(firstControl,key,{shiftKey:shift}).defaultPrevented,true);
  assert.equal(sent.length,before+1,'one declared stroke must emit one shortcut');
  assert.deepEqual(sent.at(-1),{type:'shortcut',key:key.toLowerCase()==='z'?14:15,control:true,shift,alt:false},
    'renderer shortcuts must not supply an activation target or initiating source');
}
assert.equal(nativeUndo,0,'disabled command declarations must suppress native undo/redo');
// Scope visibility/enabled/modal availability controls activation in shared
// policy. The declared stroke remains consumed even before the next DOM paint.
const unavailable={...view,widgets:[{...first,visible:false,enabled:false,inModal:false},second,list]};
renderer.acceptSnapshot(unavailable);
assert.equal(stroke(firstControl).defaultPrevented,true,'unavailable declared command scopes must still consume native editing strokes');
assert.equal(nativeUndo,0);
renderer.acceptSnapshot(view);secondControl.focus();
assert.equal(stroke(secondControl).defaultPrevented,true);
const beforeUnbound=sent.length;
assert.equal(stroke(secondControl,'y').defaultPrevented,undefined,'another editor must retain unbound native editing');
assert.equal(sent.length,beforeUnbound);assert.equal(nativeUndo,1);
firstControl.focus();
for(const extra of [{altKey:true},{isComposing:true},{defaultPrevented:true}]){
  const before=sent.length;stroke(firstControl,'z',extra);assert.equal(sent.length,before,'unbound/composing/already consumed strokes must not emit a command');
}
// Accepted declarations precede painting. Revoking a command binding must take
// effect while the old input object and old visual snapshot are still retained.
renderer.acceptSnapshot({...view,commands:[],keyBindings:[]});
const beforeRevoke=sent.length;
assert.equal(stroke(firstControl).defaultPrevented,undefined,'revoked accepted bindings must not use the old painted declaration');
assert.equal(sent.length,beforeRevoke);
const replacement={...first,key:{id:'first',generation:'2'}};
const replaced={...view,widgets:[replacement,second,list],commands:[{...undo,key:{id:undo.key.id,generation:'2'},scope:replacement.key}],
  keyBindings:[binding(14,{id:undo.key.id,generation:'2'},replacement.key)]};
renderer.acceptSnapshot(replaced);
assert.equal(stroke(firstControl).defaultPrevented,undefined,'old DOM focus may not impersonate a replacement editor generation');
const retired=firstControl;present(replaced);firstControl=renderer.nodes.get(identity(replacement.key)).control;firstControl.focus();
assert.notEqual(firstControl,retired);assert.equal(retired.parent.parent,null);
assert.equal(stroke(firstControl).defaultPrevented,true,'current replacement focus must receive its declared command');
assert.equal(renderer.nodes.size,3,'command generations must not create retained DOM objects');
// Capture consumes Enter before the record list sees the same event. Native
// list activation must not follow a declared nonvisual command.
present(view);const listControl=renderer.nodes.get(identity(list.key)).control;listControl.focus();
const beforeEnter=sent.length;const enter=listControl.emit('keydown',{key:'Enter'});
assert.equal(enter.defaultPrevented,true);assert.equal(sent.length,beforeEnter+1);
assert.deepEqual(sent.at(-1),{type:'shortcut',key:1,control:false,shift:false,alt:false},'captured Enter must not also send listKey');
present({...view,keyBindings:[]});listControl.focus();listControl.emit('keydown',{key:'Enter'});
assert.deepEqual(sent.at(-1),{type:'listKey',key:list.key,value:'enter'},'unbound Enter must retain ordinary list behavior');
renderer.destroy();
console.log('Nonvisual command DOM absence, Ctrl+Z/Shift+Z/Y scopes, disabled consumption, accepted generations and single Enter delivery passed');
