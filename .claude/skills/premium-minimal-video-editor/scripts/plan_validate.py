#!/usr/bin/env python3
# Validate a scene plan; does not assert aesthetic or human QC.
import argparse,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('plan');a=p.parse_args();d=json.loads(Path(a.plan).read_text());errs=[];warn=[]
s=d.get('scenes',[]);allowed={'AROLL',*(f'P{i:02d}' for i in range(1,11))}
if not s:errs.append('No scenes')
last=0;ids=set()
for i,x in enumerate(s):
 name=x.get('id',f'index-{i}');start=x.get('start_ms');end=x.get('end_ms')
 if name in ids:errs.append(f'Duplicate scene id: {name}')
 ids.add(name)
 if x.get('principle_id') not in allowed:errs.append(f'{name}: invalid principle_id')
 if not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or end<=start:errs.append(f'{name}: invalid times');continue
 if start<last:errs.append(f'{name}: overlap or out of order')
 if start>last:warn.append(f'{name}: gap of {start-last} ms')
 last=end
 if not x.get('purpose'):warn.append(f'{name}: purpose missing')
 if not x.get('script'):warn.append(f'{name}: script missing')
 if not x.get('approved'):warn.append(f'{name}: not approved')
words=d.get('words',[])
for w in words:
 if not all(k in w for k in ('text','start_ms','end_ms')):errs.append('word missing timestamp or text');break
 if w.get('end_ms',0)<=w.get('start_ms',0):errs.append(f'invalid word duration: {w}')
print(json.dumps({'valid':not errs,'errors':errs,'warnings':warn,'scene_count':len(s),'principles_used':sorted(set(x.get('principle_id','') for x in s))},indent=2));sys.exit(bool(errs))
