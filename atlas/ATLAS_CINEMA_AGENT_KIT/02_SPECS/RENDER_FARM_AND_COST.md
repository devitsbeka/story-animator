# Render pipeline, performance and cost engineering

**Stages:** scene preflight → low-sample low-res preview → visual review → optional render benchmark → render chunks → frame verification → compositing → audio/video assembly → delivery.

Use RunPod (or interchangeable official provider adapter). For workers pin Blender version/image digest, GPU type, driver/OptiX/CUDA compatibility, dependency list, asset hashes, GPU memory envelope, output format. Render offline from pre-staged files when possible.

## GPU economics

Cost = GPU billed seconds × actual rate + CPU + storage + networking + Claude API tokens + TTS + other licensed media + retries. Compute a measured per-shot render estimate from representative frame samples, never from fixed universal FPS or 3-second/frame assumption. Batch frames or shots to minimize cold starts; scale workers to zero. Every render has total cost cap, retry cap and variance alert.

## Render contracts

Track frame ranges inclusive, exact expected count, render pass, scene hash, random seed, named output, checksums, render engine, samples, transparency, codec and duration. Resume missing frames only; detect gaps and duplicates. A nonzero subprocess exit indicates failure, a zero exit does not guarantee artifact validity.

## Multi-pass

EXR linear workflow when compositing depth, denoise passes, normals, albedo, motion vectors and object IDs are needed. Avoid excessive passes for simple short-form clips. Persist render metadata and quality sample frames.

## Failure policy

On out-of-memory: reduce tile/scene complexity only via documented controlled fallback or swap GPU; on asset missing: fail preflight rather than black/grey placeholders; on repeated preview failure: stop and return actionable error; on budget exceed: pause pending approval.
