"""
EYES: procedural, art-directable eyeballs that replace the MakeHuman eye proxy.
- one object per eye, origin at the eyeball centre, local -Y = gaze direction, parented to the head bone
- shader built from the eye-local direction: sclera (warm white, soft vein noise, darker toward the edge),
  iris (radial fibres, darker limbal ring, lighter collarette), keyable pupil size, wet coat for crisp catchlights
- a thin cornea shell with refraction-free clear coat gives the bright specular 'life' highlight
Gaze/saccades/pupils are baked from face.py (pure functions of the frame).
"""
import math
import bpy
from mathutils import Matrix, Vector

IRIS = {"hazel": ((0.18, 0.11, 0.04), (0.42, 0.30, 0.10)), "brown": ((0.09, 0.05, 0.025), (0.30, 0.17, 0.07)),
        "blue": ((0.08, 0.16, 0.30), (0.35, 0.55, 0.75)), "green": ((0.07, 0.15, 0.07), (0.30, 0.45, 0.20))}


def eye_material(name="eye", iris="hazel", iris_angle=0.58):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    N, Lk = nt.nodes, nt.links
    for n in list(N):
        N.remove(n)
    out = N.new("ShaderNodeOutputMaterial")
    bsdf = N.new("ShaderNodeBsdfPrincipled")
    Lk.new(bsdf.outputs[0], out.inputs[0])
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    nrm = N.new("ShaderNodeVectorMath"); nrm.operation = "NORMALIZE"
    Lk.new(tc.outputs["Object"], nrm.inputs[0]); Lk.new(nrm.outputs[0], sep.inputs[0])
    # angle from the gaze axis (-Y): theta = acos(-y)
    neg = N.new("ShaderNodeMath"); neg.operation = "MULTIPLY"; neg.inputs[1].default_value = -1.0
    Lk.new(sep.outputs["Y"], neg.inputs[0])
    th = N.new("ShaderNodeMath"); th.operation = "ARCCOSINE"; Lk.new(neg.outputs[0], th.inputs[0])
    # azimuth for iris fibres
    az = N.new("ShaderNodeMath"); az.operation = "ARCTAN2"; Lk.new(sep.outputs["Z"], az.inputs[0]); Lk.new(sep.outputs["X"], az.inputs[1])
    # pupil size driver (radians) and iris size
    pup = N.new("ShaderNodeValue"); pup.name = "pupil"; pup.label = "pupil"; pup.outputs[0].default_value = 0.2
    # normalised radius inside the iris: r = theta / iris_angle
    r = N.new("ShaderNodeMath"); r.operation = "DIVIDE"; r.inputs[1].default_value = iris_angle; Lk.new(th.outputs[0], r.inputs[0])
    # fibres: noise stretched radially (az * 18, r * 2)
    comb = N.new("ShaderNodeCombineXYZ")
    azs = N.new("ShaderNodeMath"); azs.operation = "MULTIPLY"; azs.inputs[1].default_value = 9.0; Lk.new(az.outputs[0], azs.inputs[0])
    rs = N.new("ShaderNodeMath"); rs.operation = "MULTIPLY"; rs.inputs[1].default_value = 1.6; Lk.new(r.outputs[0], rs.inputs[0])
    Lk.new(azs.outputs[0], comb.inputs[0]); Lk.new(rs.outputs[0], comb.inputs[1])
    fib = N.new("ShaderNodeTexNoise"); fib.inputs["Scale"].default_value = 3.0; fib.inputs["Detail"].default_value = 6.0; fib.inputs["Roughness"].default_value = 0.65
    Lk.new(comb.outputs[0], fib.inputs["Vector"])
    dark, light = IRIS.get(iris, IRIS["hazel"])
    ramp_i = N.new("ShaderNodeValToRGB")  # iris colour across the radius (collarette lighter, limbal ring dark)
    cr = ramp_i.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.0, (*[c * 0.7 for c in dark], 1)
    cr.elements[1].position, cr.elements[1].color = 1.0, (0.02, 0.018, 0.015, 1)
    e = cr.elements.new(0.32); e.color = (*light, 1)
    e = cr.elements.new(0.62); e.color = (*dark, 1)
    e = cr.elements.new(0.86); e.color = (*[c * 0.55 for c in dark], 1)
    Lk.new(r.outputs[0], ramp_i.inputs[0])
    mixf = N.new("ShaderNodeMixRGB"); mixf.blend_type = "OVERLAY"; mixf.inputs[0].default_value = 0.55
    Lk.new(ramp_i.outputs[0], mixf.inputs[1]); Lk.new(fib.outputs["Color"], mixf.inputs[2])
    # sclera: warm white, slightly pink/darker toward the back, faint veins
    vein = N.new("ShaderNodeTexNoise"); vein.inputs["Scale"].default_value = 14.0; vein.inputs["Detail"].default_value = 8.0
    Lk.new(tc.outputs["Object"], vein.inputs["Vector"])
    ramp_s = N.new("ShaderNodeValToRGB")
    cs = ramp_s.color_ramp
    cs.elements[0].position, cs.elements[0].color = 0.0, (0.86, 0.84, 0.80, 1)
    cs.elements[1].position, cs.elements[1].color = 1.0, (0.62, 0.48, 0.45, 1)
    sth = N.new("ShaderNodeMath"); sth.operation = "DIVIDE"; sth.inputs[1].default_value = math.pi; Lk.new(th.outputs[0], sth.inputs[0])
    Lk.new(sth.outputs[0], ramp_s.inputs[0])
    vm = N.new("ShaderNodeMixRGB"); vm.blend_type = "MULTIPLY"; vm.inputs[0].default_value = 0.08
    Lk.new(ramp_s.outputs[0], vm.inputs[1]); Lk.new(vein.outputs["Color"], vm.inputs[2])
    # masks: iris = smoothstep around r=1 ; pupil = theta < pupil
    im = N.new("ShaderNodeMapRange"); im.inputs["From Min"].default_value = 1.03; im.inputs["From Max"].default_value = 0.97
    Lk.new(r.outputs[0], im.inputs["Value"])
    mix_is = N.new("ShaderNodeMixRGB"); Lk.new(im.outputs[0], mix_is.inputs[0]); Lk.new(vm.outputs[0], mix_is.inputs[1]); Lk.new(mixf.outputs[0], mix_is.inputs[2])
    pm = N.new("ShaderNodeMath"); pm.operation = "LESS_THAN"; Lk.new(th.outputs[0], pm.inputs[0]); Lk.new(pup.outputs[0], pm.inputs[1])
    pmix = N.new("ShaderNodeMixRGB"); Lk.new(pm.outputs[0], pmix.inputs[0]); Lk.new(mix_is.outputs[0], pmix.inputs[1]); pmix.inputs[2].default_value = (0.004, 0.004, 0.005, 1)
    Lk.new(pmix.outputs[0], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.35
    bsdf.inputs["Subsurface Weight"].default_value = 0.08
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.015
    bsdf.inputs["Coat IOR"].default_value = 1.376
    return m


def build_eyes(rig, head_bone, centres, radius, iris="hazel", name="eye"):
    """centres: {'L': Vector, 'R': Vector} (world). Returns {'L': obj, 'R': obj}."""
    mat = eye_material(f"{name}_mat", iris)
    eyes = {}
    for side, c in centres.items():
        bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=48, radius=radius, location=c)
        o = bpy.context.object
        o.name = f"{name}_{side}"
        for p in o.data.polygons:
            p.use_smooth = True
        o.data.materials.append(mat)
        # cornea bulge: push the front cap forward a touch (stylised read of the iris dome)
        for v in o.data.vertices:
            d = v.co.normalized()
            fwd = -d.y
            if fwd > 0.82:
                v.co += d * radius * 0.10 * ((fwd - 0.82) / 0.18) ** 1.5
        # pivot keeps the rest orientation in world axes; the eye rotates inside it (yaw = Z, pitch = X)
        piv = bpy.data.objects.new(f"{name}_{side}_pivot", None)
        bpy.context.scene.collection.objects.link(piv)
        piv.location = c
        if rig and head_bone:
            bpy.context.view_layer.update()
            mw = piv.matrix_world.copy()
            piv.parent, piv.parent_type, piv.parent_bone = rig, "BONE", head_bone
            bpy.context.view_layer.update()
            piv.matrix_world = mw
        o.location = (0, 0, 0)
        o.parent = piv
        o.matrix_parent_inverse = Matrix.Identity(4)
        bpy.context.view_layer.update()
        o.rotation_mode = "XYZ"
        o["rest_rot"] = tuple(o.rotation_euler)
        eyes[side] = o
    return eyes


def bake_gaze(eyes, gaze_fn, f0, f1, pupil_fn=None):
    """gaze_fn(f) -> (yaw_deg, pitch_deg) in head space; pupil_fn(f) -> radians."""
    for f in range(int(f0), int(f1) + 1):
        yaw, pitch = gaze_fn(f)
        for side, o in eyes.items():
            # eye-local axes follow the head bone; rotate about local Z (yaw) and X (pitch)
            o.rotation_euler = (math.radians(pitch), 0.0, math.radians(yaw))
            o.keyframe_insert("rotation_euler", frame=f)
        if pupil_fn:
            for o in eyes.values():
                n = o.data.materials[0].node_tree.nodes.get("pupil")
                if n:
                    n.outputs[0].default_value = pupil_fn(f)
                    n.outputs[0].keyframe_insert("default_value", frame=f)
                break
