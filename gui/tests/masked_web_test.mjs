import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {Renderer,identity}=await import(pathToFileURL(resolve(process.argv[2])));

// A small DOM records the masking mode at every value assignment and models
// cancellable export events. It exercises renderer mechanics, not browser UI.
class Element {
  constructor(document,tag='div') {
    this.ownerDocument=document;this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};
    this.events=new Map();this.style={setProperty:(key,value)=>this.style[key]=value};
    this._type=tag==='input'?'text':'';this.typeWrites=[];this._value='';this.assignments=[];this.attributeWrites=[];this.scrollLeft=0;this.scrollTop=0;
    this.selectionStart=0;this.selectionEnd=0;this.selectionDirection='forward';
  }
  get type(){return this._type;}
  set type(value){this.typeWrites.push(value);this._type=value;}
  get value(){return this._value;}
  set value(value){this.assignments.push({type:this.type,value});this._value=value;}
  append(child){child.remove();this.children.push(child);child.parent=this;}
  insertBefore(child,before){child.remove();const index=before?this.children.indexOf(before):this.children.length;this.children.splice(index,0,child);child.parent=this;}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(value=>value!==this);this.parent=null;}
  replaceChildren(){for(const child of [...this.children])child.remove();}
  setAttribute(key,value){this.attributeWrites.push({key,value});this.attributes[key]=value;if(key==='type')this.type=value;}
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
const sent=[],edits=[];let acknowledge;
const renderer=new Renderer(root,pages,operation=>{
  const value=typeof operation==='function'?operation(renderer.snapshot):operation;sent.push(value);return Promise.resolve({});
},document,{sendEdit:(key,value)=>{edits.push({key,value});return new Promise(resolve=>{acknowledge=resolve;});}});
const font={size:14,bold:false,tone:0},secret='aé🔒z';
const widget=(id,overrides={})=>({key:{id,generation:'1'},kind:5,parent:'',page:'',bounds:[0,0,180,30],clip:[0,0,180,30],
  visible:true,enabled:true,inModal:true,label:'',text:secret,help:'',accessibleName:'',placeholder:'Enter text',font,
  wrap:false,readOnly:false,multiline:false,masked:false,options:[],selection:[0,0],scroll:[0,0],scrollRevision:'0',
  submit:1,pointerInput:false,contextInput:false,...overrides});
const snapshot=widgets=>({title:'Masking fixture',palette:{},width:300,height:100,pages:[],widgets,focus:null,
  closed:false,measurements:[],keyBindings:[],popup:null});
const masked=widget('masked',{masked:true});
renderer.render(snapshot([masked]));
let entry=renderer.nodes.get(identity(masked.key)),control=entry.control;
assert.equal(control.type,'password');assert.equal(control.value,secret);
assert(control.assignments.every(write=>write.type==='password'),'password mode must precede every value assignment');
assert.equal(control.attributes['aria-label'],'Masked text','unnamed masked editors need a non-value name');
assert.equal(control.spellcheck,false);assert.equal(control.draggable,false);
assert.equal(control.attributes.autocomplete,'off');assert.equal(control.attributes.autocorrect,'off');assert.equal(control.attributes.autocapitalize,'none');
assert.equal(entry.suggestions.hidden,true);assert.equal(entry.suggestions.disabled,true);
const allNodes=node=>[node,...node.children.flatMap(allNodes)];
const assertNoExportedValue=()=>{
  const privateValues=[secret,...entry.control.assignments.map(write=>write.value)];
  const containsValue=value=>privateValues.some(text=>text&&String(value).includes(text));
  for(const node of allNodes(entry.node)){
    assert(!node.attributeWrites.some(write=>containsValue(write.value)),'masked value leaked into an attribute');
    assert(!Object.values(node.dataset).some(containsValue),'masked value leaked into DOM metadata');
    assert(!containsValue(node.textContent??''),'masked value leaked into visible text');
  }
};
assertNoExportedValue();
let exportObservers=0;
for(const kind of ['copy','cut','dragstart']){
  control.addEventListener(kind,()=>{++exportObservers;});const before=sent.length;
  const event=control.emit(kind);assert.equal(event.defaultPrevented,true,`${kind} must be cancelled`);
  assert.equal(control.value,secret,'export cancellation must preserve the editor value');assert.equal(sent.length,before);
}
assert.equal(exportObservers,0,'cancelled exports must not reach later clipboard/drag observers');
assert.equal(control.emit('paste').defaultPrevented,undefined,'ordinary paste must remain native');
control.value='pastedé🔒';control.selectionStart=control.selectionEnd=control.value.length;control.emit('input');
assert.deepEqual(edits.at(-1),{key:masked.key,value:'pastedé🔒'},'editing must deliver actual UTF-8, not masking glyphs');
renderer.render(snapshot([masked]));
assert.equal(control.value,'pastedé🔒','pending edit must survive an older visual snapshot');
assert.equal(control.type,'password');assert.equal(control.spellcheck,false);assert.equal(control.attributes.autocomplete,'off');
const accepted={...masked,text:'acceptedé🔒'};renderer.acceptSnapshot(snapshot([accepted]));acknowledge({});
await Promise.resolve();await Promise.resolve();
assert.equal(control.value,accepted.text,'acknowledgment must preserve actual authoritative text');
assert(control.assignments.every(write=>write.type==='password'),'acknowledgment may not disable masking');
const beforeComposition=edits.length;control.emit('compositionstart');control.value='IMEé🔒';control.emit('input',{isComposing:true});
renderer.render(snapshot([accepted]));assert.equal(control.value,'IMEé🔒','composition must survive an authoritative render');
assert.equal(edits.length,beforeComposition,'unfinished composition must not dispatch an edit');
assert.equal(control.type,'password');assert.equal(control.spellcheck,false);assert.equal(control.attributes.autocomplete,'off');
control.emit('compositionend');assert.deepEqual(edits.at(-1),{key:masked.key,value:'IMEé🔒'},'composition must deliver actual Unicode text');
acknowledge({});await Promise.resolve();await Promise.resolve();assert.equal(control.value,accepted.text);
renderer.render(snapshot([{...accepted,accessibleName:'Declared private field'}]));
assert.equal(control.attributes['aria-label'],'Declared private field');
renderer.render(snapshot([{...accepted,label:'Private field'}]));assert.equal(control.attributes['aria-label'],'Private field');
control.setSelectionRange(8,11,'backward');control.emit('select');
assert.deepEqual(sent.at(-1),{type:'selection',key:masked.key,anchor:'14',caret:'8'},'selection offsets must use actual UTF-8 text');
await Promise.resolve();
const readOnly=widget('readonly',{masked:true,readOnly:true});renderer.render(snapshot([accepted,readOnly]));
assert.equal(renderer.nodes.get(identity(readOnly.key)).control.readOnly,true);
const beforeSubmit=sent.length;control.emit('keydown',{key:'Enter',defaultPrevented:true});assert.equal(sent.length,beforeSubmit);
control.emit('keydown',{key:'Enter'});assert.equal(sent.at(-1).type,'submit');
// Shared validation forbids masked suggestions. Defensive rendering must also
// keep their labels/values out of DOM nodes if a malformed synthetic view arrives.
renderer.render(snapshot([{...accepted,options:[{id:'private',label:secret,value:secret,enabled:true}]}]));
assert.equal(entry.suggestions.hidden,true);assert.equal(entry.suggestions.disabled,true);assertNoExportedValue();
// Oversized provisional input follows the ordinary rejection seam and restores
// the current text while retaining native password mode.
control.value='x'.repeat(1024*1024);control.emit('input');
assert.equal(control.value,accepted.text);assert(control.assignments.every(write=>write.type==='password'));
assert.equal(edits.at(-1).value.length,1024*1024);acknowledge({});await Promise.resolve();
// A policy change needs a new shared generation, giving the successor no old
// password native history; the retired control remains a password control.
const retired=control,ordinary=widget('masked',{key:{id:'masked',generation:'2'},text:'Ordinary text',label:'Public field'});
renderer.render(snapshot([ordinary]));entry=renderer.nodes.get(identity(ordinary.key));control=entry.control;
assert.notEqual(control,retired);assert.equal(retired.type,'password');
assert(retired.typeWrites.every(type=>type==='password'),'masked controls must never transiently become ordinary text');
assert.equal(retired.parent.parent,null,'old password subtree must leave the document');
assert.equal(control.type,'text');assert.equal(control.value,'Ordinary text');assert.equal(control.attributes['aria-label'],'Public field');
for(const kind of ['copy','cut','dragstart'])assert.equal(control.emit(kind).defaultPrevented,undefined,'ordinary export must remain native');
assert.equal(control.attributes.autocomplete,undefined,'ordinary fields preserve their existing browser editing configuration');
const plain=widget('plain',{text:'Plain fallback',options:[{id:'one',label:'One',value:'Value',enabled:true}]});
renderer.render(snapshot([ordinary,plain]));const plainEntry=renderer.nodes.get(identity(plain.key));
assert.equal(plainEntry.control.attributes['aria-label'],'Plain fallback');assert.equal(plainEntry.suggestions.hidden,false);
assert.equal(plainEntry.suggestions.children[1].textContent,'One');
renderer.destroy();
console.log('Masked browser type/value ordering, safe accessible names, export cancellation, paste/edit/UTF-8 selection and generation replacement passed');
