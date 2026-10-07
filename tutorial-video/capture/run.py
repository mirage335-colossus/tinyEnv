#!/usr/bin/env python3
"""Recreate fresh editor footage from private copies of retained repo examples."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, time
BASE=Path(__file__).resolve().parents[1]

class Capture:
 def __init__(self,args):
  self.args=args
  if args.tools:args.tools=args.tools.absolute()
  self.repo=args.repo.resolve(); self.output=args.output_dir.resolve(); self.output.mkdir(parents=True,exist_ok=True)
  self.env=os.environ.copy(); self.env['DISPLAY']=':'+str(args.display)
  if args.library_path: self.env['LD_LIBRARY_PATH']=args.library_path
  elif args.tools: self.env['LD_LIBRARY_PATH']=str(args.tools/'usr/lib/x86_64-linux-gnu')
  self.editor=(args.editor or self.repo/'build/editor-fltk-sdk/foundation-editor-fltk').resolve()
  # Editor source titles include absolute paths: use physical neutral copies.
  self.work=Path(tempfile.mkdtemp(prefix='software-foundation-video-'))
  self.fixture_output=args.workspace.resolve() if args.workspace else None
  self.children=[]; self.handles=[]; self.editor_process=None; self.results=[]; self.inputs=[]
 def tool(self,name):
  override=getattr(self.args,{'Xvfb':'xvfb','import':'imagemagick'}.get(name,name),None)
  if override:return str(override.absolute())
  if self.args.tools:
   for path in (self.args.tools/name,self.args.tools/'usr/bin'/name):
    if path.is_file():return str(path)
  path=shutil.which(name)
  if not path:raise RuntimeError('Missing '+name+'; install it or supply --tools/tool override')
  return path
 def prepare(self):
  for name in ('simple-c','simple','demo'):
   source=self.repo/'editor/examples'/name
   if not (source/'project.json').is_file():raise RuntimeError('Missing retained example: '+str(source))
   self.inputs.extend({'example':name,'path':str(p.relative_to(source)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(source.rglob('*')) if p.is_file())
   shutil.copytree(source,self.work/name)
   if name in ('simple-c','simple'):
    project_path=self.work/name/'project.json'; project=json.loads(project_path.read_text())
    project['forms'][0]['height']=280
    project['forms'][0]['controls'][0]['label']='Ordinary '+('C' if name=='simple-c' else 'C++')+' sample processing'
    project_path.write_text(json.dumps(project,indent=2)+'\n')
  if not self.editor.is_file():raise RuntimeError('Missing editor; build through ./build.sh editor build dev --backend fltk and supply --editor')
  for name in ('Xvfb','xdotool','ffmpeg','ffprobe','import'):self.tool(name)
  self.export_projects()
 def export_projects(self):
  if self.fixture_output:
   self.fixture_output.mkdir(parents=True,exist_ok=True)
   names=('demo',) if self.args.scene and self.args.scene.startswith('mimo-') else ('simple',) if self.args.scene=='cpp-events' else ('simple-c',) if self.args.scene else ('simple-c','simple','demo')
   for name in names:
    target=self.fixture_output/name
    if target.exists():shutil.rmtree(target)
    shutil.copytree(self.work/name,target)
 def pause(self,seconds=1):time.sleep(seconds)
 def xd(self,*args):return subprocess.run([self.tool('xdotool'),*map(str,args)],env=self.env,cwd=self.work,check=True,capture_output=True,text=True).stdout
 def click(self,x,y,n=1):
  self.xd('mousemove','--sync',x,y);self.pause(.2);self.xd('click','--repeat',n,'--delay',140,1);self.pause(.6)
 def key(self,*keys):self.xd('key','--clearmodifiers',*keys);self.pause(.4)
 def type_text(self,value):self.xd('type','--clearmodifiers','--delay',45,value);self.pause(.4)
 def field(self,x,y,value):self.click(x,y);self.key('ctrl+a');self.type_text(value)
 def shot(self,name):
  target=self.output/(name+'.png');subprocess.run([self.tool('import'),'-display',self.env['DISPLAY'],'-window','root',str(target)],env=self.env,cwd=self.work,check=True);return target
 def log(self,name):
  handle=open(self.output/name,'w');self.handles.append(handle);return handle
 def start_display(self):
  number=self.args.display
  if Path(f'/tmp/.X{number}-lock').exists() or Path(f'/tmp/.X11-unix/X{number}').exists():raise RuntimeError(f'Display :{number} is already owned; choose --display')
  log=self.log('xvfb.log');child=subprocess.Popen([self.tool('Xvfb'),self.env['DISPLAY'],'-screen','0','1440x900x24','-nolisten','tcp'],env=self.env,cwd=self.work,stdout=log,stderr=log);self.children.append(child);self.pause(1)
  if child.poll() is not None:raise RuntimeError('Private display failed; see xvfb.log')
 def stop_editor(self):
  if self.editor_process is not None:
   if self.editor_process.poll() is None:self.editor_process.terminate()
   self.editor_process.wait(timeout=5);self.editor_process=None;self.pause(.5)
 def launch(self,example):
  self.stop_editor();log=self.log(example+'-editor.log')
  child=subprocess.Popen([str(self.editor),'--project','project.json'],cwd=self.work/example,env=self.env,stdout=log,stderr=log);self.editor_process=child;self.children.append(child);self.pause(1.8)
  if child.poll() is not None:raise RuntimeError('Editor failed; see '+log.name)
  windows=self.xd('search','--pid',child.pid).splitlines()
  if not windows:raise RuntimeError('Editor window did not open')
  self.xd('windowmove',windows[0],0,0);self.xd('windowsize',windows[0],1440,900);self.xd('windowfocus',windows[0]);self.pause(1)
 def paste_code(self,value):
  log=self.log('clipboard.log');child=subprocess.Popen([sys.executable,str(BASE/'capture/clipboard.py')],stdin=subprocess.PIPE,env=self.env,cwd=self.work,stdout=log,stderr=log);self.children.append(child)
  child.stdin.write(value.encode());child.stdin.close();self.pause(.7)
  try:
   if child.poll() is not None:raise RuntimeError('Clipboard helper failed')
   self.key('ctrl+v');self.pause(1)
  finally:
   if child.poll() is None:child.terminate()
   child.wait(timeout=5)
 def record(self,name,action):
  target=self.output/(name+'.mp4');log=self.log(name+'-ffmpeg.log')
  child=subprocess.Popen([self.tool('ffmpeg'),'-y','-f','x11grab','-framerate','30','-video_size','1440x900','-i',self.env['DISPLAY']+'.0','-an','-c:v','libx264','-preset','ultrafast','-crf','16','-pix_fmt','yuv420p',str(target)],env=self.env,cwd=self.work,stdin=subprocess.PIPE,stdout=log,stderr=log);self.children.append(child);self.pause(1)
  try:action();self.pause(2)
  finally:child.communicate(b'q',timeout=20)
  if child.returncode:raise RuntimeError('Recording failed: '+log.name)
  probe=json.loads(subprocess.check_output([self.tool('ffprobe'),'-v','error','-show_entries','format=duration:stream=width,height,codec_name','-of','json',str(target)],env=self.env,cwd=self.work,text=True))
  result={'scene':name,'file':str(target),'bytes':target.stat().st_size,'probe':probe,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()};self.results.append(result);print(json.dumps(result),flush=True)
 def close(self):
  for child in reversed(self.children):
   if child.poll() is None:
    child.terminate()
    try:child.wait(timeout=5)
    except subprocess.TimeoutExpired:child.kill();child.wait()
  for handle in self.handles:handle.close()
  shutil.rmtree(self.work)

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('command',choices=('all','prepare','probe'),nargs='?',default='all')
 parser.add_argument('--repo',type=Path,default=BASE.parent);parser.add_argument('--output-dir',type=Path,default=BASE/'.work/capture')
 parser.add_argument('--workspace',type=Path,default=BASE/'.work/projects',help='Export private edited projects here; editor runs in neutral /tmp copies')
 parser.add_argument('--editor',type=Path);parser.add_argument('--tools',type=Path);parser.add_argument('--library-path');parser.add_argument('--display',type=int,default=95)
 parser.add_argument('--example',choices=('simple-c','simple','demo'),default='simple-c')
 parser.add_argument('--scene',choices=('form-widget','new-event','cpp-events','mimo-properties','mimo-flow','mimo-edit','files-navigation'))
 parser.add_argument('--skip-rust',action='store_true')
 for name in ('xvfb','xdotool','ffmpeg','ffprobe','imagemagick'):parser.add_argument('--'+name,type=Path)
 args=parser.parse_args();capture=Capture(args)
 manifest_name='capture-'+args.scene+'-manifest.json' if args.scene else 'capture-manifest.json'
 try:
  capture.prepare()
  if args.command!='prepare':
   capture.start_display()
   if args.command=='probe':capture.launch(args.example);capture.shot('probe-'+args.example)
   else:
    from scenes import run_scenes
    run_scenes(capture,args.scene)
   capture.stop_editor();capture.export_projects()
   if args.command=='all' and args.scene is None:
    from composite import create_mimo
    capture.results.append(create_mimo(capture.output,capture.tool('ffmpeg'),capture.tool('ffprobe'),capture.env))
  manifest={'success':True,'repository':str(capture.repo),'editor':str(capture.editor),'neutral_workspace':str(capture.work),'exported_projects':str(capture.fixture_output) if capture.fixture_output else None,'inputs':capture.inputs,'editor_sha256':hashlib.sha256(capture.editor.read_bytes()).hexdigest(),'clips':capture.results}
  if args.command=='all' and args.scene is None and not args.skip_rust:manifest['success']=False;manifest['status']='awaiting-rust'
  (capture.output/manifest_name).write_text(json.dumps(manifest,indent=2)+'\n')
 except Exception as error:
  (capture.output/manifest_name).write_text(json.dumps({'success':False,'error':str(error),'clips':capture.results},indent=2)+'\n')
  raise
 finally:capture.close()
 if args.command=='all' and args.scene is None and not args.skip_rust:
  command=[sys.executable,str(BASE/'capture/rust-capture.py'),'--repo',str(args.repo),'--editor',str(capture.editor),'--output-dir',str(args.output_dir),'--display',str(args.display+1)]
  if args.tools:command+=['--tools',str(args.tools)]
  if args.library_path:command+=['--library-path',args.library_path]
  for name in ('xvfb','xdotool','ffmpeg','ffprobe','imagemagick'):
   if getattr(args,name):command+=['--'+name,str(getattr(args,name))]
  subprocess.run(command,check=True)
  rust=json.loads((capture.output/'rust-capture-receipt.json').read_text())
  manifest['rust_inputs']=rust['inputs']
  manifest['rust_source_files_unchanged']=rust['source_files_unchanged']
  for media in rust['media']:
   manifest['clips'].append({'scene':Path(media['file']).stem,**media})
  manifest['success']=True;manifest['status']='complete'
  (capture.output/manifest_name).write_text(json.dumps(manifest,indent=2)+'\n')
 return 0

if __name__=='__main__':sys.exit(main())
