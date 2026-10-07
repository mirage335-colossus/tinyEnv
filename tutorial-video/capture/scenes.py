"""Original, deterministic editor actions for the standalone video project."""
import hashlib
import json

NEW_EVENT_CODE='''#pragma once
#include "signal.h"
#include "visual/ui/ui.hpp"

// An ordinary C++ event can call an ordinary C function.
template<class Services>
void on_i_button1_activate(Services& services, foundation::visual::Ui& ui,
                           const gui::Activate& event) {
    (void)event;
    simple_c_state_init(&services.state);
    ui.set_text("simple_c.output", "State reset. Choose a gain and run again.");
}
'''

def form_widget(c):
 c.pause(2);c.click(252,779);c.pause(2)
 c.field(1310,214,'Reset output');c.field(1310,277,'12, 224')
 c.click(1257,383);c.pause(3);c.shot('form-widget');c.click(180,23);c.pause(5)
 project=json.loads((c.work/'simple-c/project.json').read_text())
 button=next((w for w in project['forms'][0]['controls'] if w['id']=='button1'),None)
 if not button or button['label']!='Reset output' or button['layout']['y']!=224:
  raise RuntimeError('Widget demonstration did not save the expected Reset output button')

def new_event(c):
 c.pause(2);c.click(1363,383);c.pause(3);c.shot('new-event-skeleton')
 c.click(512,280);c.key('ctrl+Home');c.key('ctrl+shift+End');c.paste_code(NEW_EVENT_CODE);c.pause(5)
 c.shot('new-event-code');c.key('F3');c.pause(2);c.shot('new-event-saved');c.key('Escape');c.pause(2);c.click(180,23);c.pause(3);c.shot('new-event-form-saved')
 source=c.work/'simple-c/src/ui/i_button1_activate.hpp'
 if not source.is_file() or source.read_text()!=NEW_EVENT_CODE:
  raise RuntimeError('Actual saved Reset handler differs from the demonstrated source')
 project=json.loads((c.work/'simple-c/project.json').read_text())
 button=next(w for w in project['forms'][0]['controls'] if w['id']=='button1')
 if not (button.get('event_bindings',{}).get('activate') or button['binding']) or not any(b['file']=='src/ui/i_button1_activate.hpp' for b in project['bindings']):
  raise RuntimeError('Reset handler has not been bound into the saved design')
 generated=c.work/'simple-c/generated/visual/events.hpp'
 if 'on_i_button1_activate' not in generated.read_text():
  raise RuntimeError('Reset handler is missing from the generated event registrations')
 (c.output/'new-event-verification.json').write_text(json.dumps({'saved_source':str(c.fixture_output/'simple-c/src/ui/i_button1_activate.hpp' if c.fixture_output else source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_matches':True,'generated_binding_present':True},indent=2)+'\n')

def cpp_events(c):
 c.pause(2);c.click(490,186,2);c.pause(5);c.shot('cpp-events');c.pause(14)

def flows(c):
 c.click(93,89);c.key('Home');c.key('Down');c.key('Return');c.pause(4)

def mimo_flow(c):
 flows(c);c.shot('mimo-flow');c.pause(16)

def mimo_properties(c):
 flows(c);c.click(625,188);c.pause(2);c.click(1310,321);c.pause(5)
 c.shot('mimo-properties');c.pause(12)

def mimo_wiring(c):
 c.pause(2);c.click(80,447);c.pause(1);c.click(1368,473);c.pause(3);c.shot('mimo-disconnected')
 c.click(180,23);c.pause(1)
 draft=json.loads((c.work/'demo/project.json').read_text())
 if any(e['from_block']=='demo.mixer' and e['from_port']=='trace' for e in draft['edges']):
  raise RuntimeError('Trace wire was not deleted in the saved draft')
 c.click(798,272);c.pause(2);c.click(837,382);c.pause(3);c.shot('mimo-reconnected')
 c.click(180,23);c.pause(4);c.shot('mimo-edit')
 final=json.loads((c.work/'demo/project.json').read_text())
 edges=[e for e in final['edges'] if e['from_block']=='demo.mixer' and e['from_port']=='trace' and e['to_block']=='demo.trace_sink' and e['to_port']=='trace']
 if len(draft['edges'])!=5 or len(final['edges'])!=6 or len(edges)!=1:
  raise RuntimeError('Trace output has not been restored to the Trace collector input')
 (c.output/'mimo-edit-verification.json').write_text(json.dumps({'draft_edges':5,'final_edges':6,'trace_connection':edges[0],'saved_design_sha256':hashlib.sha256((c.work/'demo/project.json').read_bytes()).hexdigest()},indent=2)+'\n')

def files_navigation(c):
 c.pause(2);c.click(93,89);c.key('Home');c.key('Down');c.key('Down');c.key('Return');c.pause(3);c.shot('files-workspace')
 # The explicit project-relative path gives a stable, short route to each file.
 c.field(590,194,'events.c');c.pause(2);c.click(260,237);c.pause(3)
 c.shot('files-events');c.field(650,143,'simple_c_on_run');c.key('Return');c.pause(4);c.shot('files-event-function')
 c.key('Escape');c.pause(1);c.field(590,194,'signal.c');c.pause(2);c.click(260,237);c.pause(3)
 c.field(650,143,'simple_c_apply_gain');c.key('Return');c.pause(5);c.shot('files-signal-function')
 c.key('Escape');c.pause(1);c.field(590,194,'CMakeLists.txt');c.pause(2);c.click(260,237);c.pause(4);c.shot('files-cmake');c.pause(4)

def run_scenes(c,only=None):
 names=('form-widget','new-event','cpp-events','mimo-properties','mimo-flow','mimo-edit','files-navigation') if only is None else (only,)
 for name in names:
  if name in ('form-widget','new-event'):
   if name=='form-widget' or only=='new-event':c.launch('simple-c')
   if only=='new-event':form_widget(c)
   c.record(name,lambda:form_widget(c) if name=='form-widget' else new_event(c))
  elif name=='cpp-events':c.launch('simple');c.record(name,lambda:cpp_events(c))
  elif name=='mimo-properties':c.launch('demo');c.record(name,lambda:mimo_properties(c))
  elif name=='mimo-flow':c.launch('demo');c.record(name,lambda:mimo_flow(c))
  elif name=='mimo-edit':c.launch('demo');flows(c);c.record(name,lambda:mimo_wiring(c))
  else:c.launch('simple-c');c.record(name,lambda:files_navigation(c))
