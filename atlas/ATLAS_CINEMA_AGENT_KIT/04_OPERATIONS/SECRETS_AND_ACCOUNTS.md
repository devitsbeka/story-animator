# Required accounts, credentials and permissions

## Essential for live operation

| Provider | Required from owner | Free-path fallback |
|---|---|---|
| Anthropic | API key and funded account, approved model | deterministic sample shot planner |
| RunPod | API key, billing, permitted GPU max spend | CPU render via Docker, much slower |
| R2/S3 | account, bucket, scoped keys | local disk / MinIO in dev |
| PostgreSQL | managed DB URL/admin setup | local PostgreSQL container |
| Narration | ElevenLabs API key | licensed local TTS / prerecorded voice |
| GitHub/Vercel | authorized repo + deploy access | run app locally in cloud VM |

## Free/public without mandatory keys

Poly Haven open API; ambientCG API public assets; Blender itself; official free Blender extensions subject to version compatibility; FFmpeg; native Cycles/Eevee, Geometry Nodes and camera/light controls.

## Optional paid / entitled

KitBash3D, CGTrader, Fab/Quixel, BlenderKit subscriptions, Faceit, Auto-Rig Pro, Geo-Scatter, Photographer, physical atmosphere packs. User purchases/licenses through vendors; agent imports legitimately acquired files. Do not assume vendor offers public API keys.

## Human approvals needed

Creating account/billing plan; paying for API/GPU; purchasing assets, fonts or plug-ins; authorized production publishing; any external asset licensing beyond free terms; granting persistent permissions to cloud projects. Never request credentials in chat logs. Set access in encrypted platform environment or agent secret store.

## Secrets hygiene

`.env.example` is **not** a secrets file. Never commit `.env`, `credentials.json`, SSH keys, commercial downloads or generated audio using restricted licenses. Never pass Anthropic/RunPod/R2 secrets into browser bundles or untrusted Blender workers. Use least-privilege scoped accounts and rotate keys after accidental exposure.
