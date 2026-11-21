"""Real Blender headless smoke animation; run through Blender's bundled Python.
Usage: blender -b --python smoke_scene.py -- --output /tmp/atlas-smoke --frames 48 --res 480
"""
import bpy, math, sys, argparse
from mathutils import Vector

a = argparse.ArgumentParser()
a.add_argument('--output', default='/tmp/atlas-smoke')
a.add_argument('--frames', type=int, default=48)
a.add_argument('--res', type=int, default=480)
args = a.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.render.resolution_x = args.res
scene.render.resolution_y = int(args.res * 16 / 9)
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.frame_start, scene.frame_end = 1, args.frames
scene.render.fps = 24
scene.world.color = (0.075, 0.075, 0.075)

# studio floor
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, -0.3))
floor = bpy.context.object; floor.name='Studio plinth'; floor.scale=(2.5, 2.5, .3)
mat=bpy.data.materials.new('Dark matte plinth'); mat.diffuse_color=(.09,.09,.11,1); mat.use_nodes=True
bsdf=mat.node_tree.nodes.get('Principled BSDF'); bsdf.inputs['Base Color'].default_value=(.055,.06,.07,1); bsdf.inputs['Roughness'].default_value=.78
floor.data.materials.append(mat)

# hero object
bpy.ops.mesh.primitive_torus_add(major_radius=1, minor_radius=.27, major_segments=72, minor_segments=16, location=(0,0,.75))
hero=bpy.context.object; hero.name='Hero torus'; hero.rotation_euler[0]=math.radians(60)
metal=bpy.data.materials.new('Brushed metallic');metal.use_nodes=True
shader=metal.node_tree.nodes.get('Principled BSDF');shader.inputs['Base Color'].default_value=(.4,.56,.72,1);shader.inputs['Metallic'].default_value=.85;shader.inputs['Roughness'].default_value=.19
hero.data.materials.append(metal)
mod=hero.modifiers.new('Smooth edges','BEVEL');mod.width=.04;mod.segments=2
mod=hero.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
for obj in [hero]:
  for p in obj.data.polygons:p.use_smooth=True
hero.rotation_euler[2]=0;hero.keyframe_insert(data_path='rotation_euler',frame=1)
hero.rotation_euler[2]=math.tau;hero.keyframe_insert(data_path='rotation_euler',frame=args.frames)
for curve in hero.animation_data.action.fcurves:
  for kp in curve.keyframe_points:kp.interpolation='BEZIER'

# camera with actual animated motion
bpy.ops.object.camera_add(location=(3.5,-6,2.6));camera=bpy.context.object;scene.camera=camera
camera.data.type='PERSP';camera.data.lens=40
for frame,pos in [(1,(3.5,-6,2.6)),(args.frames,(2.2,-5.2,2.1))]:
  camera.location=pos;camera.rotation_euler=(Vector((0,0,.7))-camera.location).to_track_quat('-Z','Y').to_euler()
  camera.keyframe_insert(data_path='location',frame=frame);camera.keyframe_insert(data_path='rotation_euler',frame=frame)

for loc,power,scale,name in [((-4,-3,5),700,4,'Key softbox'),((3,-1,3),500,3,'Fill softbox'),((1,4,4),850,2,'Rim softbox')]:
  light_data=bpy.data.lights.new(name,'AREA');light_data.energy=power;light_data.shape='DISK';light_data.size=scale
  light_obj=bpy.data.objects.new(name,light_data);scene.collection.objects.link(light_obj);light_obj.location=loc
  light_obj.rotation_euler=(Vector((0,0,.5))-light_obj.location).to_track_quat('-Z','Y').to_euler()

from pathlib import Path
out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
for frame in range(1,args.frames+1):
  scene.frame_set(frame)
  scene.render.filepath=str(out/f'frame_{frame:04d}.png')
  bpy.ops.render.render(write_still=True)
print(f'ATLAS_SMOKE_OK frames={args.frames} dir={out}')
