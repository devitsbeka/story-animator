# Compute broker: one render job, many providers at once, $0 capacity first (`factory/compute/`)

```
            plan (planner.py)                      work-stealing queue (workqueue.py, S3 conditional writes)
spec ──► jobs.py ──► atoms ──► free providers first ──► leases/<atom>/<gen>.json  If-None-Match: *   (claim / steal)
                               paid spot GPUs only        heartbeat / release      If-Match: <etag>
                               for the deadline           spec/<atom>/<gen>.json   one straggler copy
                                                          done/<atom>.json         first result wins
   broker.py tick:  reconcile ─► verify ─► ledger.commit ─► re-plan ─► fill free slots (chunk sized per provider)
                       ▲                                                   │ presigned chunk manifest (no creds)
                       │       aws_lambda (async invoke) ◄─────────────────┤
                       │       local_cpu (child process, same handler)  ◄──┤
                       │       member_node (inbox, untrusted, verified) ◄──┤
                       │       runpod / vastai presigned pods (paid)    ◄──┘
                       └──── done marker + frames + job manifest in S3 (presigned PUTs)
```

| File | What it is |
|---|---|
| `broker.yaml` | capability model per provider (type, hardware, max runtime, concurrency, cold start, scene build, s/frame, quota in native unit + unit price, $/h, terms verdict, trusted, priority). `registry.yaml` from the free-compute hunt is merged on top by `id`. |
| `registry.py` | loads both + `calibration.json` (measured s/frame, build, cold start, written after every run); **terms gate**: only `USE` is schedulable, `USE-WITH-CARE` only with `--allow-care <id>`, `AVOID` never. |
| `ledger.py` | **quota ledger** per provider per billing period (month / ISO week / day) in the native unit (GB-s, vCPU-s, GPU-h, credits, h). `reserve` before a task (refused past `free x (1 - safety)` unless paid overflow is allowed and within budget), `commit` the measured amount, `observe` the provider's account-wide meter (Lambda: CloudWatch Duration x MemorySize of **every** function, since they share the free tier). S3 If-Match documents (or a flock'ed local dir). |
| `workqueue.py` | atoms (contiguous frames of one shot), claims sized per worker (`max_frames`, `max_s`), atomic leases with generations (a stolen expired lease = next generation), heartbeats, release / failure parking, quality gating (final on CPU only if it meets the deadline), speculative straggler copies, first-result-wins completion, reopen. |
| `planner.py` | free providers in parallel (water-filling finish time with quota caps), then cheapest paid $/frame until the deadline holds; small jobs shrink chunks so every worker gets a share. |
| `broker.py` | the tick loop above; untrusted verification + spot checks; calibration; state in `s3://…/compute/runs/<run>/broker.json`. |
| `adapters/` | `aws_lambda`, `local_cpu`, `presigned_pod` (RunPod / Vast via `cloud/farm/presigned.py`), `member_node` (`members.py`), stubs with launch contracts: `gcp_cloud_run_jobs`, `azure_container_apps`, `modal`, `kaggle`, `oracle_always_free`, `hf_spaces`. |
| `aws_lambda/` | the Lambda worker: `Dockerfile` (Lambda python 3.12 base + AL2023 X11/GL libs + checksum-pinned Blender 4.2.3), `handler.py` (GET manifest -> code/spec/library sha256-checked -> `presigned_pod.Pod` -> PUT frames), `buildspec.yml`, `stack.yaml` (ECR, CodeBuild, least-privilege roles, function), `deploy.py`, `imagebuild.py` (Docker-free image assembler + ECR push used when CodeBuild's build quota is 0). |
| `members.py`, `node.py` | member nodes, see [member_nodes.md](member_nodes.md). |
| `api.py` | `render(spec, quality, frames, res, samples, dest, …)` for the rest of the factory. |

## Commands

```bash
OP="env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN"   # ~/.aws default profile
export LIBRARY_STORE=/home/user/story-animator/library_store
$OP python -m factory.compute providers                      # schedulable vs gated (terms) providers
$OP python -m factory.compute plan   --spec EP.json --quality preview --frames 0-23 --res 270x480 --samples 12 --deadline-min 30 --budget 0
$OP python -m factory.compute run    --spec EP.json --quality preview --frames 0-23 --res 270x480 --samples 12 \
        --providers aws_lambda,local_cpu --deadline-min 30 --budget 0 [--allow-paid] --pull /tmp/frames
$OP python -m factory.compute status [--run RUN]
$OP python -m factory.compute ledger                         # free-tier use per provider, incl. account meters
$OP python -m factory.compute.aws_lambda.deploy up|status|down
python3 cloud/farm/scheduler.py plan --spec EP.json --quality preview --deadline-min 120   # adds "computeBroker"
python -m factory.run "idea" --render compute                 # render stage + previs keyframes through the broker
```

Integration: `factory/run --render compute` renders plates through `api.render` (and previs keyframes with
`render_keys(backend="compute")`); `cloud/farm/scheduler.py plan` shows the broker's free mix next to the GPU farm
options. Paid overflow never happens unless `--allow-paid` (or `COMPUTE_ALLOW_PAID=1`) and a budget allow it.

## AWS resources (created in the operator account, us-east-1, stack `story-compute`)

ECR repo `story-compute/blender-lambda` (immutable tags, keep 2), CodeBuild project `story-compute-blender-lambda`
(BUILD_GENERAL1_SMALL, privileged, reads only its source zip + the staged Blender tarball, pushes only to that repo),
roles `story-compute-codebuild` and `story-compute-render-lambda` (**CloudWatch Logs only** — the function has no S3
or DynamoDB permission; every byte moves through presigned URLs), function `story-compute-render` (image, 10 GB
/tmp, 900 s, async retries 0), 7-day log groups. Inputs staged in the story-farm bucket under `compute/lambda-build/`.

Account findings (2026-11-22): every CodeBuild "concurrently running builds" quota was **0**; a request for
Linux/Small = 1 (L-9D07B6EF) was approved within minutes. Lambda **MemorySize is capped at 3008 MB** on this account
(10240 MB refused), so a task gets ~1.8 vCPU instead of 6; `deploy.py` falls back to 3008 automatically. Raising
it needs an AWS support case (not a Service Quotas item). Concurrency is 10 (1000 requested).
download.blender.org answers CodeBuild's IPs with HTTP 403, hence the staged, sha256-checked tarball.

## Live proof (2026-11-22)

`python -m factory.compute run --spec episodes/sentinel/episode_v5.json --quality preview --frames 0-23
--res 270x480 --samples 12 --providers aws_lambda --deadline-min 30 --budget 0 --code head` -> run
`sentinel-preview-20261122-133601`:

| | |
|---|---|
| result | COMPLETE, 24/24 real Cycles frames of shot A01a (yacht at night, island shoreline), pulled locally |
| parallelism | 10 concurrent Lambda invocations (chunks of 3+3+3+3+2x6 frames, 1 frame per atom) |
| wall time | **334.7 s** from submit to complete (cold start + 1.07 GB library/code download per invocation ~30 s, scene build ~85 s, ~66 s/frame at 1.8 vCPU) |
| invocations | 16 (10 chunks + 6 speculative copies, see lesson L022) |
| GB-s | **9,511.9 GB-s** billed (CloudWatch REPORT lines = AWS/Lambda meter), 2.4 % of the 400,000 GB-s monthly free tier; account total this month incl. the Remotion function 10,699 GB-s |
| $ | **$0.00** (inside the free tier; the same usage paid would be $0.16). Peak memory 3008 MB (at the cap) |
| other costs | CodeBuild 4.15 build-minutes on general1.small (free tier 100 min; $0.02 if billed), ECR 1.11 GB image (~$0.06/month beyond the 500 MB free tier), S3 requests/storage < $0.01 |

## Not done / open

- 10240 MB Lambda memory (needs an AWS support case); at 3008 MB peak memory hit the cap on island shots.
- Cancelled speculative Lambda tasks are booked at their estimate until the next `ledger` reconcile replaces own
  commits with the CloudWatch meter (`used = max(own, observed)`), which matched exactly in the live run.
- No live run of local_cpu + Lambda together, RunPod/Vast overflow, or a real member node (unit-tested with fakes).
- Stub adapters (Cloud Run Jobs, Container Apps, Modal, Kaggle, Oracle, HF Spaces) only document their contract.
- DynamoDB lease backend not implemented (S3 conditional writes are used; both are atomic).
