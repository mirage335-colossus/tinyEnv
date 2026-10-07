#!/usr/bin/env python3
"""Combine freshly captured port details and the completed MIMO graph."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess
BASE=Path(__file__).resolve().parents[1]

def create_mimo(output,ffmpeg,ffprobe,env):
 output=Path(output).resolve()
 inputs=[{'file':'mimo-properties.mp4','start':14.0,'end':24.0,'rate':1.0},
         {'file':'mimo-edit.mp4','start':1.0,'target_duration':22.0}]
 for item in inputs:
  source=output/item['file']
  if not source.is_file():raise RuntimeError('Missing fresh MIMO input: '+str(source))
  item['sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
 wire_probe=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_entries','format=duration','-of','json',str(output/'mimo-edit.mp4')],env=env,cwd=output,text=True))
 inputs[1]['end']=float(wire_probe['format']['duration'])
 inputs[1]['rate']=(inputs[1]['end']-inputs[1]['start'])/inputs[1]['target_duration']
 target=output/'mimo-tutorial.mp4'
 filters=f"[0:v]trim=start=14:end=24,setpts=PTS-STARTPTS[p];[1:v]trim=start=1:end={inputs[1]['end']},setpts=(PTS-STARTPTS)/{inputs[1]['rate']}[f];[p][f]concat=n=2:v=1:a=0[v]"
 command=[str(ffmpeg),'-y','-v','error','-i',str(output/inputs[0]['file']),'-i',str(output/inputs[1]['file']),'-filter_complex',filters,'-map','[v]','-an','-r','30','-c:v','libx264','-preset','ultrafast','-crf','16','-pix_fmt','yuv420p',str(target)]
 subprocess.run(command,env=env,cwd=output,check=True)
 probe=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_entries','format=duration:stream=width,height,codec_name','-of','json',str(target)],env=env,cwd=output,text=True))
 result={'scene':'mimo-tutorial','file':str(target),'bytes':target.stat().st_size,'probe':probe,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'inputs':inputs}
 (output/'mimo-edit.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result),flush=True)
 return result

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output-dir',type=Path,default=BASE/'.work/capture')
 parser.add_argument('--tools',type=Path);parser.add_argument('--ffmpeg',type=Path);parser.add_argument('--ffprobe',type=Path);parser.add_argument('--library-path')
 args=parser.parse_args();env=os.environ.copy()
 if args.library_path:env['LD_LIBRARY_PATH']=args.library_path
 elif args.tools:env['LD_LIBRARY_PATH']=str(args.tools.resolve()/'usr/lib/x86_64-linux-gnu')
 def tool(name):
  override=getattr(args,name)
  if override:return override.absolute()
  if args.tools:
   for path in (args.tools.resolve()/name,args.tools.resolve()/'usr/bin'/name):
    if path.is_file():return path
  path=shutil.which(name)
  if not path:raise RuntimeError('Missing '+name+'; install it or supply tool paths')
  return path
 create_mimo(args.output_dir,tool('ffmpeg'),tool('ffprobe'),env)
 return 0
if __name__=='__main__':raise SystemExit(main())
