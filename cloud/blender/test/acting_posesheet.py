import bpy, sys, math
sys.path.insert(0, "/home/user/story-animator/cloud/blender")
import acting
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath="/home/user/story-animator/studio/public/assets/characters/hero/hero.glb")
objs = list(bpy.context.selected_objects)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for o in bpy.data.objects:
    if o.name.startswith("Icosphere"): o.hide_render = True
holder = bpy.data.objects.new("holder", None); sc.collection.objects.link(holder)
pup = acting.Puppet(arm, holder)
for o in [o for o in bpy.data.objects if o.parent is None and o is not holder]:
    o.parent = holder
# a sequence of test poses, each held at frame 10*i+8
tests = [("stand", None), ("helm", None), ("brace", None), ("stand", "radio_shout"), ("stand", "shush"), ("stand", "phone_up"),
         ("stand", "wave"), ("stand", "hands_face"), ("stand", "look_back"), ("sit_deck", None), ("down", None), ("stand", "point_ahead")]
perf = {"stance": [], "poses": [], "blend": 1}
for i, (st, ps) in enumerate(tests):
    perf["stance"].append([i * 10, st])
    if ps: perf["poses"].append({"pose": ps, "from": i * 10, "to": i * 10 + 9, "in": 1, "out": 1})
perf["stance"][0][0] = -100
pup.bake(perf, 0, len(tests) * 10)
# stage
bpy.ops.mesh.primitive_plane_add(size=20); fl = bpy.context.object
m = bpy.data.materials.new("floor"); m.use_nodes = True; m.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.2, 0.17, 0.14, 1); fl.data.materials.append(m)
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True; w.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.06, 0.09, 1)
def light(n, loc, e, size=1.0):
    d = bpy.data.lights.new(n, "AREA"); d.energy = e; d.size = size
    o = bpy.data.objects.new(n, d); sc.collection.objects.link(o); o.location = loc
    c = o.constraints.new("TRACK_TO"); c.target = holder; c.track_axis = "TRACK_NEGATIVE_Z"; c.up_axis = "UP_Y"
light("key", (-2.0, -3.0, 2.8), 900, 2); light("rim", (2.2, 2.5, 2.4), 700, 1); light("fill", (2.5, -2.0, 1.2), 200, 3)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.location = (-1.0, -3.0, 1.3); cam.data.lens = 40
t = bpy.data.objects.new("t", None); sc.collection.objects.link(t); t.location = (0, 0, 0.95)
c = cam.constraints.new("TRACK_TO"); c.target = t; c.track_axis = "TRACK_NEGATIVE_Z"; c.up_axis = "UP_Y"
sc.render.engine = "CYCLES"; sc.cycles.samples = 12; sc.cycles.device = "CPU"
sc.render.resolution_x, sc.render.resolution_y = 300, 450
for i in range(len(tests)):
    sc.frame_set(i * 10 + 8)
    sc.render.filepath = f"/tmp/bl/act/p{i:02d}.png"
    bpy.ops.render.render(write_still=True)
