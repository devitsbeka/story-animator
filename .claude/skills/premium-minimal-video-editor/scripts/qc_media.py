#!/usr/bin/env python3
# Basic objective media checks, not a substitute for visual/audio QC.
import argparse,subprocess,json,pathlib
p=argparse.ArgumentParser();p.add_argument('video');p.add_argument('-o','--output',default='qc-report.json');a=p.parse_args();issues=[]
try:
 result=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',a.video],capture_output=True,text=True,check=True)
 meta=json.loads(result.stdout)
 dec=subprocess.run(['ffmpeg','-v','error','-i',a.video,'-f','null','-'],capture_output=True,text=True)
 if dec.returncode:issues.append('Decode failed: '+dec.stderr[-1000:])
except (FileNotFoundError,subprocess.SubprocessError,ValueError) as e:meta={};issues.append(str(e))
video=next((s for s in meta.get('streams',[]) if s.get('codec_type')=='video'),{})
audio=next((s for s in meta.get('streams',[]) if s.get('codec_type')=='audio'),{})
if not video:issues.append('No video stream')
if not audio:issues.append('No audio stream (may be intentional)')
report={'file':a.video,'probe':meta,'issues':issues,'verified_decode':not any('Decode failed' in x for x in issues),'visual_inspection':'not_verified','sound_quality':'not_verified','copyright_clearance':'not_verified'}
pathlib.Path(a.output).write_text(json.dumps(report,indent=2));print(f'QC metadata -> {a.output}; issues: {len(issues)}; aesthetic/audio/manual inspection still required')
