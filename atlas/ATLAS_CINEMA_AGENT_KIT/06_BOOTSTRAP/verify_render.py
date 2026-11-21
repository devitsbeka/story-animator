"""Check frame existence and visual changes; does not prove premium quality."""
import sys, argparse, hashlib, json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--frames',type=int,default=48);a=p.parse_args()
f=Path(a.folder);files=[f/f'frame_{x:04d}.png' for x in range(1,a.frames+1)]
missing=[x.name for x in files if not x.is_file() or x.stat().st_size<100]
if missing:raise SystemExit('Missing or tiny frames: '+', '.join(missing))
hashes=[hashlib.sha256(x.read_bytes()).hexdigest() for x in files]
if len(set(hashes))<2:raise SystemExit('Output has no pixel variation across frames')
print(json.dumps({'passed':True,'frames':len(files),'unique_frames':len(set(hashes)),'scene_saved':(f/'scene.blend').is_file()},indent=2))
