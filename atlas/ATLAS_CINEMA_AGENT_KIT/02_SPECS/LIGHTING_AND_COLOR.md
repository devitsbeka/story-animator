# Lighting department and color pipeline

**Core:** `bpy.data.lights`, physical dimensions of emitters, world HDRI, Cycles multiple importance sampling where supported, procedural shader nodes, atmospheric volumes. Default linear-light computation, display/view transform validated for chosen Blender version, compositing on scene-linear EXR.

## Looks and reusable rigs

- Portrait: 3-point, Rembrandt, butterfly, split, rim, dramatic low-key, editorial high-key, motivated window.
- Architecture: overcast north-light, late-afternoon raking sun, moonlit blue hour, sodium streetlight, overcast wet street, tungsten practicals, neon night, foggy dawn.
- Products: oversized softbox, strip card reflection, silhouette edge, black-on-black, white seamless, jewelry, glass/transmission, metal/specular gradient.
- VFX: volumetric shafts, lighting through diffusion, haze, practical fire flicker (controlled), procedural gobos and LED screens.

## Physical parameters

Emitter dimensions/shape, power, temperature, falloff, source distance, angle, world orientation, HDRI map intensity, color, volumetric density, exposure, shadow softness, render visibility, view layer. Ratios are descriptive targets, not universal physically correct intensity values.

## Procedural validation

Compute rough histograms with shadow/midtone/highlight occupancy; detect near-clipped highlights, deeply crushed shadows, exposure discontinuity and unexpectedly absent lights. Compare shots using common subject test charts, textured metal and calibrated neutral materials. Preview multiple light variants then select on narrative/visual grounds. Do not use simple brightness as a surrogate for cinematography.

## Color finishing

Keep EXR plates with passes, denoise correctly, preserve scene-linear values, confirm Blender AgX support/version, handle tone map into delivery SDR; ensure no double transfer function. Color grade consistently across sequences. Sound/visual QC remains separate.
