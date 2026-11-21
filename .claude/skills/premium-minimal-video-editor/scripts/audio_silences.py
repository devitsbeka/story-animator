#!/usr/bin/env python3
# Detect candidate silence spans. Requires ffmpeg. Does not automatically cut content.
import argparse,re,subprocess,json,pathlib
p=argparse.ArgumentParser();p.add_argument('media');p.add_argument('-o','--output',default='silences.json');p.add_argument('--noise',default='-35dB');p.add_argument('--min-duration',type=float,default=.30);p.add_argument('--padding-ms',type=int,default=30);a=p.parse_args()
cmd=['ffmpeg','-hide_banner','-i',a.media,'-af',f'silencedetect=noise={a.noise}:d={a.min_duration}','-f','null','-']
try: log=subprocess.run(cmd,capture_output=True,text=True).stderr
except FileNotFoundError:raise SystemExit('ffmpeg required')
starts=[];items=[]
for line in log.splitlines():
 m=re.search(r'silence_start:\s*([0-9.]+)',line)
 if m: starts.append(float(m.group(1)))
 m=re.search(r'silence_end:\s*([0-9.]+)',line)
 if m:
  end=float(m.group(1));start=starts.pop(0) if starts else None
  if start is not None:
   items.append({'start_ms':round(start*1000),'end_ms':round(end*1000),'duration_ms':round((end-start)*1000),'default_padding_ms':a.padding_ms,'status':'candidate_needs_listening'})
pathlib.Path(a.output).write_text(json.dumps({'media':a.media,'noise':a.noise,'min_duration':a.min_duration,'detected':items},indent=2));print(f'{len(items)} candidate silences -> {a.output}; requires manual boundary review')
