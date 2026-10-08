import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {Renderer,identity}=await import(pathToFileURL(resolve(process.argv[2])));

class Element {
  constructor(document,tag='div') {
    this.ownerDocument=document;this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};
    this.events=new Map();this.style={setProperty:(key,value)=>this.style[key]=value};
    this.scrollLeft=0;this.scrollTop=0;this.clientWidth=180;this.clientHeight=100;this.scrollWidth=300;this.scrollHeight=1000;
    this.value='';this.selectionStart=0;this.selectionEnd=0;this.selectionDirection='forward';this.focusCount=0;
  }
  append(child){child.remove();this.children.push(child);child.parent=this;}
  insertBefore(child,before){child.remove();const index=before?this.children.indexOf(before):this.children.length;this.children.splice(index,0,child);child.parent=this;}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(value=>value!==this);this.parent=null;}
  replaceChildren(){for(const child of [...this.children])child.remove();}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(kind,callback,options){const list=this.events.get(kind)||[];list.push({callback,capture:options===true||options?.capture===true});this.events.set(kind,list);}
  removeEventListener(kind,callback){this.events.set(kind,(this.events.get(kind)||[]).filter(item=>item.callback!==callback));}
  setSelectionRange(start,end,direction){this.selectionStart=start;this.selectionEnd=end;this.selectionDirection=direction;}
  focus(){this.ownerDocument.activeElement=this;++this.focusCount;}
  blur(){this.ownerDocument.activeElement=null;}
  emit(kind,values={}) {
    let stopped=false;const event={key:'',isComposing:false,ctrlKey:false,shiftKey:false,altKey:false,
      preventDefault(){this.defaultPrevented=true;},stopImmediatePropagation(){stopped=true;},...values};
    const path=[];for(let node=this;node;node=node.parent)path.push(node);
    for(const node of [...path].reverse())for(const item of node.events.get(kind)||[])if(item.capture&&!stopped)item.callback(event);
    for(const node of path)for(const item of node.events.get(kind)||[])if(!item.capture&&!stopped)item.callback(event);
    return event;
  }
}
const document=new Element(null);document.ownerDocument=document;document.defaultView=new Element(document);
document.createElement=tag=>new Element(document,tag);document.body=document.createElement('body');document.body.parent=document;
const root=document.createElement('div'),pages=document.createElement('div');document.body.append(root);document.body.append(pages);
const sent=[];let renderer;
renderer=new Renderer(root,pages,operation=>{sent.push(typeof operation==='function'?operation(renderer.snapshot):operation);return Promise.resolve({});},document);
const font={size:14,bold:false,tone:0};
const widget=(id,extra={})=>({key:{id,generation:'1'},kind:5,parent:'',page:'',bounds:[20,20,180,100],clip:[20,20,180,100],
  visible:true,enabled:true,inModal:true,label:'',text:'one é two',help:'',accessibleName:'',placeholder:'',font,
  wrap:true,readOnly:true,multiline:true,masked:false,options:[],actions:[],records:[],selection:[4,6],scroll:[15,40],scrollRevision:'1',
  submit:0,pointerInput:false,contextInput:false,rowHeight:20,contentSize:[300,1000],...extra});
const text=widget('text'),masked=widget('masked',{multiline:false,masked:true,text:'synthetic',selection:[0,0],scroll:[0,0],textFrame:false});
const snapshot=(value=text)=>({title:'Frame fixture',palette:{},width:400,height:300,pages:[],widgets:[value,masked],focus:value.key,
  closed:false,measurements:[],keyBindings:[],popup:null});
renderer.render(snapshot());const entry=renderer.nodes.get(identity(text.key)),control=entry.control;
assert.equal(control.style.borderColor??'','');assert.equal(control.style.outline??'','');assert.equal(entry.node.style.outline??'','');
assert.equal(document.activeElement,control);assert.equal(control.focusCount,1);assert.equal(control.readOnly,true);
const unchanged=()=>({clientWidth:control.clientWidth,clientHeight:control.clientHeight,scrollWidth:control.scrollWidth,scrollHeight:control.scrollHeight,
  scrollLeft:control.scrollLeft,scrollTop:control.scrollTop,value:control.value,selectionStart:control.selectionStart,selectionEnd:control.selectionEnd,
  paddingRight:control.style.paddingRight,width:entry.node.style.width,height:entry.node.style.height,clipPath:entry.node.style.clipPath});
const geometry=unchanged();
renderer.render(snapshot({...text,textFrame:false}));
assert.equal(renderer.nodes.get(identity(text.key)),entry);assert.equal(entry.control,control,'appearance must retain the native control');
assert.equal(control.style.borderColor,'transparent');assert.equal(control.style.outline,'none');assert.equal(entry.node.style.outline,'none');
assert.deepEqual(unchanged(),geometry,'framing must retain padding, scroll geometry, text and selection');
assert.equal(document.activeElement,control);assert.equal(control.focusCount,1,'appearance updates must not transfer focus');
for(const name of ['border','borderWidth','borderStyle','padding','outlineOffset','boxSizing'])
  assert.equal(Object.hasOwn(control.style,name),false,`${name} must retain its CSS default rather than change inner geometry`);
assert.equal(control.emit('copy').defaultPrevented,undefined,'ordinary readonly copying must remain native');
control.setSelectionRange(4,5,'backward');control.emit('select');
assert.deepEqual(sent.at(-1),{type:'selection',key:text.key,anchor:'6',caret:'4'},'selection must retain actual UTF-8 byte offsets');
await Promise.resolve();await Promise.resolve();
const secret=renderer.nodes.get(identity(masked.key)).control;
assert.equal(secret.type,'password');assert.equal(secret.style.borderColor,'transparent');assert.equal(secret.emit('copy').defaultPrevented,true);
for(const value of [{...text,textFrame:true},text]) {
  renderer.render(snapshot(value));assert.equal(entry.control,control);assert.equal(control.style.borderColor,'');
  assert.equal(control.style.outline,'');assert.equal(entry.node.style.outline,'');
  assert.equal(control.focusCount,1,'restoring defaults must not replace or refocus the editor');
}
renderer.render(snapshot({...text,textFrame:false}));
const replacement={...text,key:{id:'text',generation:'2'}};renderer.render(snapshot(replacement));
const successor=renderer.nodes.get(identity(replacement.key)).control;
assert.notEqual(successor,control);assert.equal(successor.style.borderColor,'');assert.equal(successor.style.outline,'');
assert.equal(control.style.borderColor,'transparent','retired control appearance must not leak into its successor');
const editable={...text,key:{id:'editable',generation:'1'},multiline:false,readOnly:false,textFrame:false};
renderer.render(snapshot(editable));const input=renderer.nodes.get(identity(editable.key)).control;
assert.equal(input.type,'text');assert.equal(input.style.borderColor,'transparent');
input.value='Edited';input.selectionStart=input.selectionEnd=input.value.length;input.emit('input');
assert.deepEqual(sent.at(-1),{type:'edit',key:editable.key,value:'Edited',base:editable.text},'frameless editing must retain its authoritative text operation');
renderer.destroy();
console.log('Browser text-frame false/default/reset, retained geometry/focus/UTF-8 selection, native copy and masking passed');
