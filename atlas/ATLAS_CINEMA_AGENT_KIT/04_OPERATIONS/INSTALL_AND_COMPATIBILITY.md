# Installation and headless compatibility

1. Select one Blender LTS build for production (recommended initial baseline: 4.5 LTS, check currently supported patch). Record OS/arch, Blender full version and image digest.
2. Smoke render native Blender scene before installing extras.
3. Pin Python libraries separately for the backend and Blender-embedded Python; do not assume pip inside Blender matches host Python.
4. Install only `RECOMMENDED` free extensions initially, one by one, checking their Blender extension package and current version compatibility.
5. For commercial plugins, record purchase entitlement and plugin version. Verify install, enable, import and a real `blender -b` operation with tests before enabling an adapter.
6. Keep native-camera and native-light fallbacks; optional plugin failures must not break the entire platform.
7. Verify NVIDIA driver, GPU visibility and Blender Cycles backend by checking actual device enumeration and sample render; CPU smoke test does not prove GPU support.
8. Use signed/container-pinned worker images; build test should import Blender and render under the same runtime.

Compatibility registry fields: name, version, Blender version, OS, Python version, install source, SHA256, license, headless tested, test command, screenshot, status, last verified date. Do not auto-enable unverified code.

Suggested verification sequence:

```bash
blender -b --python-expr 'import bpy; print(bpy.app.version_string)'
blender -b -t 2 --python 06_BOOTSTRAP/smoke_scene.py -- --output /tmp/atlas-smoke --frames 48 --res 480
python3 06_BOOTSTRAP/verify_render.py /tmp/atlas-smoke --frames 48
```

For GPU use on worker, use a separate render benchmark that logs available Cycles devices and captures actual timing. Do not treat `nvidia-smi` alone as render availability proof.
