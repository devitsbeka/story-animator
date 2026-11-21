#!/usr/bin/env python3
# Inventory local video and audio with ffprobe. Usage: python inventory.py INPUT_DIR -o inventory.json
import argparse,json,subprocess,pathlib,hashlib
p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('-o','--output',default='inventory.json');a=p.parse_args()
media_ext={'.mp4','.mov','.m4v','.webm','.mkv','.mp3','.wav','.m4a','.flac'}
entries=[]
for f in sorted(pathlib.Path(a.directory).rglob('*')):
 if not f.is_file() or f.suffix.lower() not in media_ext:continue
 h=hashlib.sha256()
 with f.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
 try:
  out=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(f)],capture_output=True,text=True,check=True)
  meta=json.loads(out.stdout);error=None
 except (subprocess.SubprocessError,ValueError,FileNotFoundError) as e:meta={};error=str(e)
 entries.append({'file':str(f),'sha256':h.hexdigest(),'bytes':f.stat().st_size,'metadata':meta,'probe_error':error,'rights':'unverified'})
pathlib.Path(a.output).write_text(json.dumps(entries,indent=2));print(f'Inventoried {len(entries)} media files -> {a.output}')
