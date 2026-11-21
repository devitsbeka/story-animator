# Deployment runbook

**Control plane:** Next.js on Vercel; FastAPI in managed container host; PostgreSQL on managed DB; queue (Temporal or selected durable alternative) with worker; R2 object storage; RunPod GPU workers. Match all versioned API/DB contracts. Choose one primary workflow orchestrator.

**Plan:** development compose → local cloud VM demo → provider API authenticated smoke → worker image published → one real GPU render → scaled parallel test → signed artifact delivery. Secrets via provider secret manager; no free-form production secret access to GPU Blender process.

**Deploy gates:** 1) real health checks; 2) authenticated project creation; 3) DB migrations applied; 4) storage read/write signed URLs; 5) queue activity; 6) one real worker startup/shutdown; 7) GPU backend render test; 8) frame upload/retrieval; 9) MP4 assembly and signed download; 10) cancellation; 11) spend cap; 12) retry a deliberately failed frame.

**Observability:** structured JSON logs, trace IDs per project/shot/job, durable render manifest, queue depth, failed jobs, worker startup latency, GPU hour total, data transfer, per-project actual vs estimated spend, broken asset imports, plugin failures.

**Recovery:** abort jobs safely, clean stale orphan workers, retry only invalidated frames, detect uncommitted uploads, enforce retention policy, restore DB from backups. GPU jobs require idempotent task IDs and content-addressed outputs.

**Cost:** Never create paid pods without explicit funding approval. Use a capped development deployment and automatic idle shutdown. Infrastructure setup is not deployment success until real service and worker smoke tests pass.
