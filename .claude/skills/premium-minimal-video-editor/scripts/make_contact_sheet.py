#!/usr/bin/env python3
# Extract sampled video frames using FFmpeg and create a contact sheet (Pillow required).
import argparse,subprocess,pathlib,math,tempfile
p=argparse.ArgumentParser();p.add_argument('video');p.add_argument('-o','--output',default='contact-sheet.jpg');p.add_argument('--fps',type=float,default=.5);p.add_argument('--columns',type=int,default=5);p.add_argument('--max-frames',type=int,default=60);a=p.parse_args()
try:from PIL import Image,ImageDraw
except ImportError:raise SystemExit('Pillow required: pip install pillow')
with tempfile.TemporaryDirectory() as d:
 cmd=['ffmpeg','-hide_banner','-loglevel','error','-i',a.video,'-vf',f'fps={a.fps},scale=320:-1','-frames:v',str(a.max_frames),str(pathlib.Path(d)/'frame-%04d.jpg')]
 subprocess.run(cmd,check=True);files=sorted(pathlib.Path(d).glob('frame-*.jpg'))
 if not files:raise SystemExit('No frames extracted')
 thumbs=[]
 for f in files:
  im=Image.open(f).convert('RGB');im.thumbnail((320,220));thumbs.append(im.copy())
 w=320;h=245;cols=max(1,a.columns);rows=math.ceil(len(thumbs)/cols);out=Image.new('RGB',(w*cols,h*rows),'#171a20');draw=ImageDraw.Draw(out)
 for i,im in enumerate(thumbs):
  x=i%cols*w;y=i//cols*h;out.paste(im,(x+(w-im.width)//2,y));draw.text((x+6,y+222),f'{i/a.fps:.2f}s',fill='white')
 out.save(a.output,quality=90);print(f'{len(thumbs)} frames -> {a.output}')
