# Camera department: software cinematographer

**Core implementation:** native `bpy` cameras, constraints, path curves, rig empties, keyframes and graph/fcurve controls. Paid add-ons are optional artist-authoring aides. All rig state is serializable.

## 36 camera movement presets

dolly_in, dolly_out, truck_left, truck_right, pedestal_up, pedestal_down, crane_rise, crane_descend, orbit_cw, orbit_ccw, arc_track, follow_tracking, over_shoulder, pov, low_reveal, high_reveal, establishing, extreme_closeup, push_reveal, pullback_reveal, whip_pan, tilt_up, tilt_down, pan_left, pan_right, handheld_subtle, handheld_documentary, stabilized_tracking, tripod, dolly_zoom, rack_focus, parallax_reveal, orbit_track, product_turntable, architecture_walkthrough, aerial_flyover.

## Physical/look controls

Focal length (18/24/35/50/85/135 mm presets), sensor width, anamorphic look where genuinely modeled, f-stop/DOF, focus target and smooth rack-focus, motion blur shutter, exposure, lens breathing when artistically desired, camera tilt/roll. Use Blender's native model honestly; complex lens artifacts may require compositing.

## Temporal language

Write parameterized tracks with velocity/acceleration shaping (Bezier or 5th-order smoothstep), anticipation, hold, motivated movement, cadence, target following, noise layered in local camera space. No pointless continuous movement. 24 fps master default; 30 fps for short-form when brief demands. Animate at physical scale (meters/second) and check velocity spikes.

## Composition guardrails

Subject bbox projected in normalized camera frame; safe crop for 9:16 and caption zones; headroom/lookroom, thirds, leading lines, foreground separation, horizon. For dialogue ensure mouth visibility. Prevent clipping and large occlusion; ray-cast collision-avoidance where practical. Track face/eye screen positions and maintain shot continuity.

## Tests

Render low-res frame 1, midpoint and last frame for each preset. Assert camera path differs when requested, focus-distance changes for rack-focus, subject visible within margin, paths avoid solid objects in test fixtures, and frame-to-frame motion is smooth. Compare contact sheets visually. Include `03_CATALOGS/camera_presets.yaml` as initial catalog and augment with params.
