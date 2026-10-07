#!/usr/bin/env python3
"""Record the committed documentation explorer and PDFs in a real local browser.

The published bundle is copied byte-for-byte. No documentation generator or
application command is invoked. Browser profiles and display resources are private.
"""
from pathlib import Path
import argparse, hashlib, json, os, shutil, signal, subprocess, tempfile, time
from run import Capture
BASE=Path(__file__).resolve().parents[1]

class Documentation(Capture):
 def __init__(self,args):
  args.editor=None;args.workspace=None;args.scene=None
  super().__init__(args);self.env.pop('WAYLAND_DISPLAY',None);self.env['MOZ_ENABLE_WAYLAND']='0';self.work.rmdir();self.work=Path(tempfile.mkdtemp(prefix='software-foundation-documentation-'));self.browser_process=None;self.events=[]
 def log(self,name):return super().log('doc-'+name)
 def prepare(self):
  source=self.repo/'documentation-tool/published'
  for name in ['index.html','explorer.js','explorer.css','data.js','atlas.json','pdf/00-edit-paths.pdf','pdf/02-compiler-reference.pdf']:
   if not (source/name).is_file():raise RuntimeError('Missing committed reader input: '+str(source/name))
  self.inputs=[{'path':str(p.relative_to(source)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(source.rglob('*')) if p.is_file()]
  shutil.copytree(source,self.work/'guide');self.atlas=json.loads((source/'atlas.json').read_text())
  for entry in self.inputs:
   if hashlib.sha256((self.work/'guide'/entry['path']).read_bytes()).hexdigest()!=entry['sha256']:raise RuntimeError('Published reader copy changed')
  self.browser=str(self.args.browser.absolute()) if self.args.browser else next((shutil.which(n) for n in ['chromium','chromium-browser','google-chrome','google-chrome-stable'] if shutil.which(n)),None)
  if not self.browser:raise RuntimeError('Missing local Chromium/Chrome; install one or supply --browser')
  self.browser_version=subprocess.check_output([self.browser,'--version'],text=True,stderr=subprocess.STDOUT,env=self.env,cwd=self.work).strip()
  if not any(name in self.browser_version.lower() for name in ['chromium','chrome']):raise RuntimeError('This recorded PDF walkthrough requires a Chromium/Chrome browser')
  for name in ['Xvfb','xdotool','ffmpeg','ffprobe','import']:self.tool(name)
 def start_browser(self):
  url=(self.work/'guide/index.html').as_uri()+'#home'
  argv=[self.browser,'--user-data-dir='+str(self.work/'profile'),'--no-first-run','--no-default-browser-check','--disable-dev-shm-usage','--ozone-platform=x11','--disable-background-networking','--force-device-scale-factor=1','--window-size=1440,900',url]
  f=self.log('browser.log');self.browser_process=subprocess.Popen(argv,cwd=self.work,env=self.env,stdout=f,stderr=f,start_new_session=True)
  self.children.append(self.browser_process);self.pause(3)
  windows=[]
  for attempt in range(12):
   try:windows=self.xd('search','--onlyvisible','--name','software.foundation|Software foundation|Where should I edit').splitlines()
   except subprocess.CalledProcessError:pass
   if windows:break
   self.pause(1)
  self.shot('doc-browser-start')
  if not windows:raise RuntimeError('Documentation browser did not open; see doc-browser.log')
  window=windows[0];self.xd('windowmove',window,0,0);self.xd('windowsize',window,1440,900);self.xd('windowfocus',window);self.pause(1)
 def goto(self,route):
  if route.startswith('#'):url=(self.work/'guide/index.html').as_uri()+route
  else:
   path,separator,fragment=route.partition('#');url=(self.work/'guide'/path).as_uri()+(separator+fragment if separator else '')
  self.key('ctrl+l');self.xd('type','--clearmodifiers','--delay',12,url);self.key('Return');self.pause(2)
  self.events.append({'navigation':route})
 def mark(self,name):
  self.events.append({'scene':self.recording,'seconds':round(time.monotonic()-self.record_started,3),'visible':name})
 def record(self,name,action):
  self.recording=name;self.record_started=time.monotonic()
  return super().record(name,action)
 def hold_until(self,seconds):self.pause(max(0,seconds-(time.monotonic()-self.record_started)))
 def close(self):
  if self.browser_process:
   try:os.killpg(self.browser_process.pid,signal.SIGTERM)
   except ProcessLookupError:pass
   try:self.browser_process.wait(timeout=6)
   except subprocess.TimeoutExpired:os.killpg(self.browser_process.pid,signal.SIGKILL);self.browser_process.wait()
  if self.args.keep_workspace:
   # Base cleanup owns process/handle shutdown; preserve the reviewed copy only
   # when an explicit probe request needs it for inspection.
   work=self.work;self.work=self.output/'doc-empty-cleanup';self.work.mkdir(exist_ok=True)
   super().close();self.work=work
  else:super().close()

def html_action(c):
 c.mark('Published local HTML: Where should I edit?');c.shot('doc-html-home');c.pause(2)
 c.click(418,591);c.key('Next');c.pause(2);c.mark('Add a widget & click handler: edit path diagram');c.shot('doc-html-map')
 c.click(416,329);c.pause(3);c.mark('Declare the widget: what, why, exact source path');c.shot('doc-html-widget')
 c.click(366,558);c.pause(2);c.mark('view_definition.hpp:22 highlighted source and October 4 capture date');c.shot('doc-html-source')
 c.key('alt+Left');c.pause(.7);c.click(374,680);c.pause(1);c.mark('ViewDefinition parameter guide: named fields');c.shot('doc-html-parameters')
 c.key('Next');c.pause(3);c.shot('doc-html-parameter-fields')
 c.click(111,265);c.click(1251,590);c.key('Next');c.pause(2);c.mark('Add a source file to the compiler: source-role map');c.shot('doc-html-source-map')
 c.click(831,425);c.pause(3);c.mark('Shared GUI .cpp: gui/CMakeLists.txt:104 and foundation_gui_application');c.shot('doc-html-source-list')
 c.click(111,450);c.pause(2);c.mark('Compiler & toolchain reference');c.shot('doc-html-compiler')
 c.click(825,866);c.pause(1);c.mark('foundation_gui_application: source entries and linked dependencies');c.shot('doc-html-compiler-target');c.hold_until(38)

def pdf_action(c):
 c.mark('Edit paths PDF, page 2: Add a clickable widget and a helper');c.shot('doc-pdf-edit-path');c.pause(6)
 c.xd('mousemove','--sync',1200,700);c.xd('click','--repeat',2,'--delay',150,5);c.pause(2);c.mark('Widget recipe: project state and new source file');c.shot('doc-pdf-edit-path-lower')
 c.field(530,117,'12');c.key('Return');c.pause(1);c.mark('Edit paths PDF, page 12: Make a new source file compile');c.shot('doc-pdf-source-files');c.pause(6)
 c.goto('pdf/02-compiler-reference.pdf#page=7&zoom=125');c.pause(1)
 c.xd('mousemove','--sync',1200,700);c.xd('click','--repeat',2,'--delay',150,5);c.pause(2);c.mark('Compiler reference PDF, page 7: foundation_gui_application declaration');c.shot('doc-pdf-compiler');c.hold_until(35)

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('command',nargs='?',default='all',choices=['all','probe'])
 parser.add_argument('--repo',type=Path,default=BASE.parent);parser.add_argument('--output-dir',type=Path,default=BASE/'.work/capture')
 parser.add_argument('--browser',type=Path);parser.add_argument('--tools',type=Path);parser.add_argument('--library-path');parser.add_argument('--display',type=int,default=97)
 parser.add_argument('--route',default='#home',help='Initial public reader route for a probe')
 parser.add_argument('--keep-workspace',action='store_true')
 for name in ['xvfb','xdotool','ffmpeg','ffprobe','imagemagick']:parser.add_argument('--'+name,type=Path)
 args=parser.parse_args()
 repo=args.repo.resolve();output=args.output_dir.resolve()
 if (output==repo or repo in output.parents) and not (output==BASE/'.work' or BASE/'.work' in output.parents):parser.error('Capture output inside the repository must be under tutorial-video/.work')
 c=Documentation(args)
 try:
  c.prepare();c.start_display();c.start_browser()
  if args.command=='probe':
   if args.route!='#home':c.goto(args.route)
   c.shot('doc-probe')
  else:
   c.record('documentation-html',lambda:html_action(c))
   c.goto('pdf/00-edit-paths.pdf#page=2&zoom=125');c.pause(1);c.click(32,117);c.pause(1)
   c.record('documentation-pdf',lambda:pdf_action(c))
  source=c.repo/'documentation-tool/published'
  for entry in c.inputs:
   if hashlib.sha256((source/entry['path']).read_bytes()).hexdigest()!=entry['sha256']:raise RuntimeError('Committed documentation inputs changed during recording')
  proof={'success':True,'browser':c.browser,'browser_version':c.browser_version,'source':str(source),'published_snapshot':c.atlas['generated_at'],'snapshot_fingerprint':c.atlas['fingerprint'],'inputs':c.inputs,'media':c.results,'actions':c.events,'workspace_retained':args.keep_workspace,'workspace':str(c.work),'source_files_unchanged':True}
  (c.output/'doc-capture-receipt.json').write_text(json.dumps(proof,indent=2)+'\n')
 except Exception as error:
  (c.output/'doc-capture-receipt.json').write_text(json.dumps({'success':False,'error':str(error),'inputs':c.inputs,'media':c.results,'actions':c.events},indent=2)+'\n');raise
 finally:c.close()
 return 0
if __name__=='__main__':raise SystemExit(main())
