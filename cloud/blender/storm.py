"""
STORM: weather + archival grade for a shot, applied after the world, props and camera are built.

  env.weather = {
     "rain": 0..1            density of camera-space rain streaks (motion-blur friendly cyclic fall)
     "wind": deg             slant of the rain in frame (default 14)
     "speed": m/s            fall speed (default 11)
     "overcast": 0..1        thicker cloud cover in the procedural sky, dimmer moon
     "moonScale": x          extra multiplier on the moon key
     "lightning": [f, ...]   strike frames (absolute) -> flash of a cold sun light + sky + rain
     "lightningDir": [x,y,z] spec-space direction TO the flash (default high behind the camera's right)
     "glassRain": true       scroll the rivulets on any 'rivulet_map' glass material
  }
  env.grade = "sepia" | {"look": "sepia", "amount": 0..1}   archival 1981 grade in the compositor

Everything is keyed per frame (or cyclic) so a frame renders the same in any job split.
"""
import math
import random

import bpy
import bmesh
from mathutils import Vector


def flash_at(f, strikes):
    """0..1 flash intensity of a set of strikes at absolute frame f (a stuttering double flash)."""
    pat = {0: 1.0, 1: 0.3, 2: 0.85, 3: 0.25, 4: 0.1, 5: 0.04}
    v = 0.0
    for s in strikes or ():
        v = max(v, pat.get(int(f - s), 0.0))
    return v


def _rain_mat(name="rain_streak", strength=0.22):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    N, Lk = m.node_tree.nodes, m.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    tr = N.new("ShaderNodeBsdfTransparent")
    em = N.new("ShaderNodeEmission")
    em.name = "rain_emit"
    em.inputs["Color"].default_value = (0.78, 0.84, 0.92, 1)
    em.inputs["Strength"].default_value = strength
    # streak fades toward its ends (UV along the length)
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    Lk.new(tc.outputs["UV"], sep.inputs["Vector"])
    pp = N.new("ShaderNodeMath")
    pp.operation = "PINGPONG"
    pp.inputs[1].default_value = 0.5
    Lk.new(sep.outputs["Y"], pp.inputs[0])
    fac = N.new("ShaderNodeMath")
    fac.operation = "MULTIPLY"
    fac.inputs[1].default_value = 1.1
    Lk.new(pp.outputs[0], fac.inputs[0])
    mx = N.new("ShaderNodeMixShader")
    Lk.new(fac.outputs[0], mx.inputs[0])
    Lk.new(tr.outputs[0], mx.inputs[1])
    Lk.new(em.outputs[0], mx.inputs[2])
    Lk.new(mx.outputs[0], out.inputs["Surface"])
    return m


def build_rain(cam, frames, fps, density=1.0, wind=14.0, speed=11.0, seed=3, dmin=3.0, dmax=16.0):
    """Streak quads in camera space (-Z forward, +Y up), two stacked layers falling cyclically."""
    rnd = random.Random(seed)
    H = 2 * (dmax * 0.48 + 0.6)
    n = int(650 * density)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UV")
    for layer in (0.0, H):
        r2 = random.Random(seed)  # same streaks in both layers -> seamless wrap
        for _ in range(n):
            u = r2.random()
            d = dmin + (dmax - dmin) * u ** 0.7
            x = r2.uniform(-1, 1) * (d * 0.34 + 0.8)
            y = r2.uniform(-H / 2, H / 2) + layer
            ln = r2.uniform(0.35, 0.7) * (0.5 + 0.5 * d / dmax)
            w = 0.0015 + 0.0005 * d
            vs = [bm.verts.new((x - w, y - ln / 2, -d)), bm.verts.new((x + w, y - ln / 2, -d)),
                  bm.verts.new((x + w, y + ln / 2, -d)), bm.verts.new((x - w, y + ln / 2, -d))]
            f = bm.faces.new(vs)
            for lp, (a, b) in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                lp[uv].uv = (a, b)
    me = bpy.data.meshes.new("Rain")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(_rain_mat())
    rig = bpy.data.objects.new("RainRig", None)
    bpy.context.scene.collection.objects.link(rig)
    rig.parent = cam
    rig.rotation_euler = (0, 0, math.radians(wind))
    ob = bpy.data.objects.new("Rain", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = rig
    ob.visible_shadow = False
    try:
        ob.visible_diffuse = ob.visible_glossy = ob.visible_transmission = False
    except AttributeError:
        pass
    period = max(2, int(round(H / speed * fps)))
    for f, v in ((0, 0.0), (period, -H)):
        ob.location.y = v
        ob.keyframe_insert("location", index=1, frame=f)
    fc = ob.animation_data.action.fcurves.find("location", index=1)
    for kp in fc.keyframe_points:
        kp.interpolation = "LINEAR"
    fc.modifiers.new("CYCLES")
    return ob


def _world_bg(world):
    if not world or not world.node_tree:
        return None
    return next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)


def overcast_sky(world, amount):
    """Thicken the procedural cloud banks (the cloud-coverage map range of build_world)."""
    hit = 0
    for n in world.node_tree.nodes:
        if n.type == "MAP_RANGE" and abs(n.inputs["From Min"].default_value - 0.5) < 1e-4 \
                and abs(n.inputs["From Max"].default_value - 0.68) < 1e-4:
            n.inputs["From Min"].default_value = 0.5 - 0.32 * amount
            n.inputs["From Max"].default_value = 0.68 - 0.3 * amount
            hit += 1
    return hit


def apply_grade(scene, grade):
    if not grade:
        return False
    if isinstance(grade, str):
        grade = {"look": grade}
    look, amt = grade.get("look", "sepia"), float(grade.get("amount", 0.85))
    if look != "sepia" or not scene.use_nodes:
        return False
    nt = scene.node_tree
    comp = next((n for n in nt.nodes if n.type == "COMPOSITE"), None)
    if comp is None or not comp.inputs["Image"].links:
        return False
    src = comp.inputs["Image"].links[0].from_socket
    hs = nt.nodes.new("CompositorNodeHueSat")
    hs.inputs["Saturation"].default_value = 1.0 - 0.85 * amt
    tint = nt.nodes.new("CompositorNodeMixRGB")
    tint.blend_type = "COLOR"
    tint.inputs[0].default_value = 0.8 * amt
    tint.inputs[2].default_value = (0.66, 0.47, 0.27, 1)
    fade = nt.nodes.new("CompositorNodeMixRGB")
    fade.blend_type = "ADD"
    fade.inputs[0].default_value = amt
    fade.inputs[2].default_value = (0.03, 0.022, 0.012, 1)   # lifted, warm blacks
    nt.links.new(src, hs.inputs["Image"])
    nt.links.new(hs.outputs["Image"], tint.inputs[1])
    nt.links.new(tint.outputs["Image"], fade.inputs[1])
    nt.links.new(fade.outputs["Image"], comp.inputs["Image"])
    return True


def apply(shot, env, frames, cam, fps, log=print):
    """Hook called by render_episode.build_shot once the camera is keyed."""
    sc = bpy.context.scene
    w = env.get("weather") or {}
    f0, f1 = frames[0] - 1, frames[-1] + 1
    done = []
    world = sc.world
    if w.get("overcast"):
        overcast_sky(world, float(w["overcast"]))
        done.append("overcast")
    moon = bpy.data.objects.get("Moon")
    ms = float(w.get("moonScale", 1.0)) * (1.0 - 0.5 * float(w.get("overcast", 0.0)))
    if moon is not None and abs(ms - 1.0) > 1e-6:
        moon.data.energy *= ms
    rain = None
    if w.get("rain"):
        rain = build_rain(cam, frames, fps, float(w["rain"]), float(w.get("wind", 14.0)), float(w.get("speed", 11.0)))
        done.append("rain")
    strikes = w.get("lightning") or []
    if strikes:
        ld = bpy.data.lights.new("Lightning", "SUN")
        ld.color = (0.72, 0.8, 1.0)
        ld.angle = math.radians(8)
        lo = bpy.data.objects.new("Lightning", ld)
        sc.collection.objects.link(lo)
        d = w.get("lightningDir") or [0.6, 0.8, -0.4]
        dv = Vector((d[0], -d[2], d[1])).normalized()
        lo.rotation_mode = "QUATERNION"
        lo.rotation_quaternion = (-dv).to_track_quat("-Z", "Y")
        bg = _world_bg(world)
        bg0 = bg.inputs["Strength"].default_value if bg else 1.0
        em = rain.data.materials[0].node_tree.nodes.get("rain_emit") if rain else None
        em0 = em.inputs["Strength"].default_value if em else 0.0
        for f in range(f0, f1 + 1):
            fl = flash_at(f, strikes)
            ld.energy = 9.0 * fl
            ld.keyframe_insert("energy", frame=f)
            if bg:
                bg.inputs["Strength"].default_value = bg0 * (1.0 + 7.0 * fl)
                bg.inputs["Strength"].keyframe_insert("default_value", frame=f)
            if em:
                em.inputs["Strength"].default_value = em0 * (1.0 + 5.0 * fl)
                em.inputs["Strength"].keyframe_insert("default_value", frame=f)
        done.append(f"lightning x{len(strikes)}")
    if w.get("glassRain", bool(w.get("rain"))):
        for m in bpy.data.materials:
            mp = m.node_tree.nodes.get("rivulet_map") if m.node_tree else None
            if mp is not None:
                for f in (f0, f1):
                    mp.inputs["Location"].default_value[2] = f / fps * 0.35
                    mp.inputs["Location"].keyframe_insert("default_value", index=2, frame=f)
                done.append("glass rivulets")
    if apply_grade(sc, env.get("grade")):
        done.append("grade")
    if done:
        log(f"storm: {', '.join(done)}")
    return done
