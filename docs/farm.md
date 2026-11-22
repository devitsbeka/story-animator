# GPU render farm (AWS queue + any GPU provider, as code)

Stage 7 of the factory (`factory/ARCHITECTURE.md`): Blender plates for an episode are rendered on spot GPU
instances, then the orchestrator pulls them back, runs the Remotion finish and QC.

```
orchestrator.py submit ──► S3 spec snapshot + DynamoDB run/jobs ──► SQS render queue ──► spot ASG (g6/g5, scale on backlog)
                                                                       │  (DLQ after 4 receives)     │ worker.py in Docker:
orchestrator.py watch ◄── DynamoDB progress + S3 job manifests ◄───────┘                             │ sync S3 → Blender → S3
        │ all jobs DONE                                                                               │ idle 10 min → terminate
        └─► pull plates ─► Remotion "Finish" ─► factory.qc ─► episodes/<id>/runs/<run>/final/ in S3   on-demand ASG = fallback
```

| File | What it is |
|---|---|
| `cloud/farm/jobs.py` | Splits `episode.json` into jobs (one shot, inclusive frame range, ~15 GPU-min each), cost and wall-clock estimate. Pure Python. |
| `cloud/farm/worker.py` | Container entrypoint. SQS → S3 sync (library + spec + assets + earlier partial frames) → `render_episode.py` → plates, log and manifest to S3. |
| `cloud/farm/orchestrator.py` | `plan`, `submit`, `status`, `watch`, `finish`, `cancel`, `retry`, `sync-library`. |
| `cloud/farm/farmio.py` | S3 sync, DynamoDB state (leases, exactly-once progress), SQS batching. |
| `cloud/farm/Dockerfile` (+ `.dockerignore`) | NVIDIA base, checksum-pinned Blender 4.2.3, repo code, non-root, healthcheck. |
| `cloud/farm/infra/farm.yaml` | CloudFormation: bucket, queue + DLQ, table, ECR, IAM, launch template, two ASGs, scaling, alarms, budget. |
| `cloud/farm/scheduler.py` + `providers.yaml` | Picks where workers run (AWS ASG → RunPod → Vast.ai → local), falls back, enforces the budget. See [Providers and fallback](#providers-and-fallback). |
| `cloud/farm/providers/` | `aws_ec2.py`, `runpod.py`, `vastai.py`, `local.py` behind one interface; `worker_startup.sh` + `startup.py` boot a worker on a plain CUDA container. |
| `tests/farm/` | Job-splitting unit tests + worker/orchestrator end to end on moto with a fake Blender; provider tests on mocked HTTP; fallback scenarios; startup-script lint + stub run. |

## Account state (checked read-only, 2026-11-21, us-east-1)

| Quota | Value | Note |
|---|---|---|
| Running On-Demand G and VT instances (L-DB2E81BA) | **0 vCPU** | increase to 8 requested — status `CASE_OPENED` |
| All G and VT Spot Instance Requests (L-3819A6DF) | **0 vCPU** | increase to 8 requested — status `CASE_OPENED` |
| Standard on-demand / spot | 8 / 8 vCPU | |

**Nothing GPU can launch until those cases are approved.** G/VT quotas count vCPUs: 8 vCPU = two `g6.xlarge`
(or one `g6.2xlarge`). The stack defaults (`MaxSpotWorkers=2`, `MaxOnDemandWorkers=1`) fit 8 vCPU; raise them only
together with the quota. Check with:

```bash
aws service-quotas get-service-quota --region us-east-1 --service-code ec2 --quota-code L-3819A6DF --query Quota.Value
aws service-quotas list-requested-service-quota-change-history --region us-east-1 --service-code ec2 \
  --query 'RequestedQuotas[].[QuotaName,DesiredValue,Status]' --output table
```

The ECS GPU-optimized AL2023 AMI (`/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id`,
currently `al2023-ami-ecs-gpu-hvm-2023.0.20261119`) exists in us-east-1, and g6.xlarge / g5.xlarge are offered in
us-east-1a/b/c/d/f. A default VPC is present.

## Cost model

Prices in us-east-1, Linux, read on 2026-11-21 (Pricing API + 7-day spot history):

| Instance | GPU | On-demand $/h | Spot $/h (7-day min / median / max) |
|---|---|---|---|
| g6.xlarge | 1x L4 24 GB | 0.8048 | 0.37 / **0.60** / 0.73 |
| g5.xlarge | 1x A10G 24 GB | 1.006 | 0.51 / 0.69 / 0.89 |
| g6.2xlarge | 1x L4 | 0.9776 | ~0.68–0.78 |
| g5.2xlarge | 1x A10G | 1.212 | ~0.74–1.01 |

(g4dn.xlarge, T4, is $0.526 / ~$0.22 spot but about 2–3x slower in Cycles; add it to `AllowedInstanceTypes` if
cost matters more than wall-clock.)

**Per job:** `est_seconds = 25 s overhead + build_s + frames x spf(shot)`;
`spf(shot) = preset spf x complexity` (1.0 + 0.15/actor + 0.04/prop + 0.20 island + 0.15 fires, max 2.5).

| Preset | Resolution, samples | base spf (GPU) | build_s |
|---|---|---|---|
| preview | 540x960, 16 spp | 3 s | 40 s |
| final | 1080x1920, 128 spp adaptive, OptiX denoise | 40 s | 60 s |

Where the base numbers come from: measured Cycles CPU plates of Sentinel v2 (270x480, 16 spp) take 8.6–13.5 s/frame
on 2 shared CPU threads (`/tmp/bl/v2/*/_render_*.json`); a shot build takes ~27 s on that CPU (measured in the worker
integration run below). Scaled by pixels (x4 preview, x16 final) and samples (x8 final), divided by ~35 for an
L4/A10G against 2 CPU threads (Blender Open Data ratio). **These are estimates**; after the first cloud run, feed the
measured numbers back:

```bash
python3 - <<'EOF'   # per-shot calibration from the worker manifests of a run
import json, subprocess, sys; sys.path.insert(0, "cloud/farm"); import jobs
# aws s3 sync s3://<bucket>/farm/runs/<run>/jobs/ /tmp/manifests/ first
import glob; ms = [json.load(open(p)) for p in glob.glob("/tmp/manifests/*.json")]
json.dump(jobs.calibration_from_manifests(ms), open("calibration.json", "w"), indent=1)
EOF
python3 cloud/farm/orchestrator.py plan --spec episodes/sentinel/episode_v2.json --calibration calibration.json
```

**Sentinel (2416 frames, 33 shots), from `orchestrator.py plan`:**

| | jobs | GPU-hours | 2 workers (quota today) | 8 workers | $ spot g6 ($0.60) | $ on-demand g6 ($0.80) | $ on-demand g5 ($1.006) |
|---|---|---|---|---|---|---|---|
| preview | 33 | 3.4 | 1 h 49 min | 33 min | **$2.15–2.39** | $2.88–3.20 | $3.60–4.00 |
| final | 168 | 41.9 | 21 h | 5 h 19 min | **$25–26** | $34 | $42–43 |

i.e. final ≈ 2416 frames x ~59 s/frame average + 168 builds; a 20-minute docuseries episode (36 000 frames) is
~15x that (~$380 spot). Fixed costs are small: S3 ~$0.023/GB-month (library 0.5 GB + plates ~2.5 GB per final
episode at PNG), DynamoDB/SQS cents, CloudWatch alarms $0.10 each/month (8 alarms), ECR ~$0.10/GB-month for the
~3 GB image. Idle cost is zero: both groups scale to zero.

## Deploy (exact commands)

Prereqs: AWS CLI v2 with credentials allowed to create the stack (IAM, EC2, ASG, S3, SQS, DynamoDB, ECR,
CloudWatch, Budgets, SNS), Docker with BuildKit, the G/VT quota approved.

```bash
export AWS_REGION=us-east-1 STACK=story-farm
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
TAG=$(git rev-parse --short HEAD)
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC Name=default-for-az,Values=true \
          --query 'Subnets[].SubnetId' --output text | tr '\t' ',')

# 0. validate (no resources)
pip install cfn-lint && cfn-lint cloud/farm/infra/farm.yaml
aws cloudformation validate-template --template-body file://cloud/farm/infra/farm.yaml

# 1. stack with zero workers possible (the ASGs start at 0; nothing bills until jobs are queued)
#    ECR repo must exist before the image push, and ImageTag must name the image the instances will pull.
aws cloudformation deploy --stack-name $STACK --template-file cloud/farm/infra/farm.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides VpcId=$VPC SubnetIds=$SUBNETS ImageTag=$TAG AlarmEmail=you@example.com \
                        MonthlyBudgetUsd=100 MaxSpotWorkers=2 MaxOnDemandWorkers=1

# 2. build + push the worker image (from the repo root)
REPO_URI=$(aws cloudformation describe-stacks --stack-name $STACK \
  --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" --output text)
aws ecr get-login-password | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com
DOCKER_BUILDKIT=1 docker build -f cloud/farm/Dockerfile -t $REPO_URI:$TAG .
docker push $REPO_URI:$TAG

# 3. operator permissions for whoever runs the orchestrator
POLICY=$(aws cloudformation describe-stacks --stack-name $STACK \
  --query "Stacks[0].Outputs[?OutputKey=='OperatorPolicyArn'].OutputValue" --output text)
aws iam attach-user-policy --user-name <operator-user> --policy-arn $POLICY

# 4. upload the shared library once (delta sync afterwards)
pip install boto3
LIBRARY_STORE=/home/user/story-animator/library_store python3 cloud/farm/orchestrator.py --stack $STACK sync-library

# 5. render: preview first (cheap), then final; several episodes may be submitted at once
python3 cloud/farm/orchestrator.py plan --spec episodes/sentinel/episode_v2.json --quality final --workers 2
python3 cloud/farm/orchestrator.py --stack $STACK submit --spec episodes/sentinel/episode_v2.json --quality preview --budget 10
python3 cloud/farm/orchestrator.py --stack $STACK watch --finish          # progress, budget guard, finish + QC
python3 cloud/farm/orchestrator.py --stack $STACK submit --spec episodes/sentinel/episode_v2.json \
        --spec episodes/other/episode.json --quality final --budget 80
```

New worker code = new image tag: build/push with the new `TAG`, then re-run step 1 with `ImageTag=$TAG` (the launch
template gets a new version; new instances pull it). Tags are immutable in ECR.

Operations:

```bash
python3 cloud/farm/orchestrator.py --stack $STACK status                  # all runs
python3 cloud/farm/orchestrator.py --stack $STACK cancel --run <run>      # workers drop its remaining jobs
python3 cloud/farm/orchestrator.py --stack $STACK retry  --run <run>      # re-enqueue FAILED jobs
aws logs tail /story-farm/worker --follow                                 # worker JSON logs (one stream per instance)
aws s3 cp s3://story-farm-$ACCOUNT-$AWS_REGION/farm/runs/<run>/logs/<job>.<attempt>.log -   # Blender log
# after fixing the cause, the DLQ copies can simply be purged (retry re-sends from the stored plan):
aws sqs purge-queue --queue-url $(aws cloudformation describe-stacks --stack-name $STACK \
  --query "Stacks[0].Outputs[?OutputKey=='DeadLetterQueueUrl'].OutputValue" --output text)
```

Tear down: `aws cloudformation delete-stack --stack-name $STACK` (bucket and table are `Retain`: empty and delete
them by hand if wanted; delete the ECR images first or the repo deletion fails).

## How it behaves

- **Jobs**: never straddle a cut (each shot is rebuilt per job), sized to ~15 GPU-min (short enough to lose little
  to a spot interruption, long enough to amortise the 40–60 s scene build), at least 8 frames. Ids are
  deterministic (`sentinel-A01-f00000-00014-final`). Enqueued longest-first; several runs submitted together are
  interleaved round-robin so episodes progress in parallel.
- **Budget**: `submit --budget X` refuses a run if active runs' `max(estimate, spent)` plus the new estimate exceed X
  (also `$FARM_BUDGET_USD`). Each run gets a cap of 1.5x its estimate (`--overrun`); `watch` cancels a run that
  spends past it. The AWS Budget (EC2 compute) e-mails at 50 %/80 % actual and 100 % forecast as a last line.
- **Worker**: refuses to start without a GPU; fails a job if Cycles fell back to CPU; claims a DynamoDB lease so
  duplicate SQS deliveries do not render twice; extends message visibility + lease every 2 min while Blender runs;
  checks the IMDS spot notice every poll and on a notice uploads finished frames and releases the message (the next
  attempt downloads them and Blender runs `--skip-existing`); verifies every expected PNG and writes the job manifest
  (sha256 per plate, seconds/frame, device, attempt) last, so "manifest DONE" means "all plates are in S3"; a
  re-delivered DONE job is acknowledged without rendering. Failures back off 60 s, 120 s, 240 s; the 4th failure
  marks the job FAILED and SQS moves the message to the DLQ (alarm).
- **Scaling**: spot group desired = f(backlog = visible + in-flight jobs) in steps 1, 2, 4, 8, 16, max (clamped
  to `MaxSpotWorkers`); busy workers set scale-in protection. No waiting jobs and no spot instance for
  `OnDemandFallbackMinutes` (spot unavailable) → on-demand group starts. Queue empty 15 min → both groups to 0;
  idle workers also terminate themselves after 10 min (decrementing the group). A host watchdog powers the
  instance off if the worker container has been down for 10 min.
- **IAM**: the instance role can read the library/assets/episode inputs, write only plates/manifests/logs, consume
  only the render queue, `GetItem`/`UpdateItem` only on the job table, pull only the worker repo, and
  protect/terminate only instances in `story-farm-*` groups. Bucket-level `s3:ListBucket` is granted unconditioned
  so a HEAD of a missing manifest returns 404 (not 403). IMDSv2 only, hop limit 2 for the container. No inbound.

## Verified here (no AWS resources created)

- `cfn-lint cloud/farm/infra/farm.yaml` → clean; `aws cloudformation validate-template` → valid, needs
  `CAPABILITY_NAMED_IAM`.
- `hadolint cloud/farm/Dockerfile` → clean (apt packages intentionally unpinned, documented inline). The image
  was **not built** (no Docker daemon in this sandbox); the Blender tarball sha256 is the official one.
- `pytest tests/farm` → 31 passed: splitting/coverage/cost on the real Sentinel spec; worker + orchestrator end to
  end on moto (two episodes in parallel, idempotent redelivery, budget ceiling, retries → FAILED → retry, missing
  plate, CPU fallback, cancel, lease, resume from partial plates, poison messages, finish/QC hooks, overspend).
- Integration: `worker.py` driving **real Blender 4.2.3** (`render_episode.py`, shot B10 frame 700, 135x240,
  4 spp, CPU) against moto: job DONE, plate + manifest in (mock) S3, run RENDERED.
- Providers/scheduler (2026-11-21): `pytest tests/farm` → 91 passed (the 31 above + 60 new): RunPod and Vast request
  shapes and error mapping on mocked HTTP; aws_ec2 on fake service-quotas/autoscaling; local with real child
  processes; fallback AWS quota 0 → RunPod, RunPod capacity 400 → Vast, all down → local; health timeout, lost
  heartbeat and exited container → terminate + cooldown + next option; hourly and total budget; idle
  termination; rebalance local → AWS; manifests/job items/heartbeats record the provider (moto);
  `worker_startup.sh` run end to end against stubs (pinned commit checkout, token not leaked, no-GPU / CPU-only
  Cycles / missing secret exits). `shellcheck -S style` (shellcheck-py 0.11) and `bash -n` clean on the template and
  the rendered script; `cfn-lint` clean with the new policy/user; `scheduler.py dry-run` writes the payloads.
- `orchestrator.py status` now prints `{"runs": [...], "compute": {...}}` (was a bare list of runs); `submit`
  prints `{"runs": [...], "compute": <tick>}` unless `--dry-run`/`--no-scale`.

## Providers and fallback

Rendering must not depend on one vendor approving a quota. The **queue (SQS), job state (DynamoDB) and storage
(S3) stay on AWS** — they need no quota — and only the machines that poll the queue move. `worker.py` is the same
everywhere; it learns where it runs from `FARM_PROVIDER` / `FARM_PROVIDER_WORKER_ID` / `FARM_GPU_CLASS` and
records them in every job manifest (`provider`, `providerWorkerId`, `gpuClass`, `gpus`) and job item, and writes a
heartbeat item (`pk=WORKER sk=<provider>:<id>`, state idle/rendering, every 60 s or on change).

```
orchestrator submit ─► SQS ◄──── poll ──── worker.py  on  aws_ec2 (ASG, ECR image)   1st: needs G/VT quota
                  │                                     runpod  (CUDA base image)   2nd: RUNPOD_API_KEY
                  └─► scheduler.py tick ─► launch/kill ─►vastai  (CUDA base image)   3rd: VAST_API_KEY
                        ▲   heartbeats (DynamoDB)        local   (CPU processes)     last resort
                        └──────────────────────────────────┘
```

### Provider interface

`providers/base.py`: `available() -> (ok, reason)`, `launch(n, gpu_class, env, startup) -> [handles]`, `list()`,
`terminate(ids)`, `price_per_hour(gpu_class)`. Failures are typed — `CapacityError` (no stock, placement failed,
offer gone), `QuotaError` (quota 0, no balance), `AuthError`, `ProviderError` (API/network) — so the scheduler can
fall back. Only machines named `story-farm-*` are ever listed or terminated.

| Provider | available() checks | launch | API (read 2026-11-21) |
|---|---|---|---|
| `aws_ec2` | service-quotas L-3819A6DF (spot) / L-DB2E81BA (on-demand) > 0; stack groups exist; no InsufficientInstanceCapacity/VcpuLimitExceeded in the last 15 min of scaling activities | raise the spot group's desired capacity (on-demand group when spot quota is 0), clamped to group max and quota/4 | boto3 |
| `runpod` | key set; `GET /v2/catalog/gpus?include=AVAILABILITY&product=POD&cloud=…` shows stock for a configured GPU | `POST /v2/pods` `{name, image, gpu:{id,count}, cloud, disk, env, entrypoint:["/bin/bash","-c"], cmd:[bootstrap], ports:[]}`; 400 (no capacity / placement) → next cloud, then `CapacityError`; 402 → `QuotaError` | REST v2 `https://api.runpod.io/v2` (OpenAPI). Spot: only the deprecated GraphQL `podRentInterruptable`, opt-in (`interruptible: true`) and falls back to on-demand |
| `vastai` | key set; `GET /api/v0/users/current` balance > 0; `POST /api/v0/bundles` returns offers (gpu_name in list, 1 GPU, reliability ≥ 0.98, verified, $/h ≤ `max_dph`) | `PUT /api/v0/asks/{offer}` `{image, disk, label, runtype:"args", args:["bash","-c",bootstrap], env:"-e K=V …", price (bids)}` cheapest offer first; 410/no_such_ask → next offer | `https://console.vast.ai` REST |
| `local` | slots free (`max_workers`) | `python3 cloud/farm/worker.py` subprocesses, `REQUIRE_GPU=0`, 2 threads | — |

GPU classes are provider-neutral: `L4`, `A10G` (AWS g6/g5), `RTX4090` (`NVIDIA GeForce RTX 4090` / `RTX 4090`),
`L40S`, `A100`, `CPU`.

### Workers outside AWS: no custom image

RunPod and Vast boot the public `nvidia/cuda:12.4.1-base-ubuntu22.04` image with a **startup script** as the
container command (`providers/worker_startup.sh`, rendered by `providers/startup.py` with a settings block and
shipped gzip+base64 in one line, ~4.5 KB). It:

1. checks the secrets in its env and derives its id (`runpod:$RUNPOD_POD_ID`, `vastai:<CONTAINER_ID>`);
2. apt-installs Blender's runtime libs, git, python3-venv; checks `nvidia-smi -L` (exit 3 without a GPU when
   `REQUIRE_GPU=1`) and whether `libnvoptix` is mounted (sets `NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics`);
3. downloads **Blender 4.2.3, sha256-verified** (same pin as the Dockerfile);
4. fetches the code **at a pinned commit**: `code.source: git` → `git fetch --depth 1 <url> <commit>` (a private
   repo uses `GIT_TOKEN`, a read-only deploy token sent as an `http.extraHeader` and unset before the worker
   starts), or `code.source: s3` → the scheduler uploads `farm/code/<commit>.tar.gz` (`git archive` of the
   renderer paths, sha256 checked on the worker);
5. probes Cycles devices inside Blender (OptiX, then CUDA; exit 3 if neither when a GPU is required);
6. `exec`s `worker.py` (`FARM_IMDS=0`). The worker syncs the library from S3 at preflight, as on AWS.

When the worker exits (idle 10 min) the container stops; the scheduler sees EXITED/stopped and terminates the
machine, so nothing idles on a bill.

### Scheduling policy (`providers.yaml`)

Each `tick` (run by `orchestrator.py submit` right after enqueueing and by every `watch` loop; `--no-scale` skips
it; `scheduler.py tick` runs one by hand):

- **Rank options** (provider, GPU class, spot/on-demand). `strategy: priority` (default): `order`
  `[aws_ec2, runpod, vastai, local]`, spot before on-demand inside a provider, then the GPU with the lowest
  $ per unit of Cycles speed. `strategy: cheapest`: lowest $/speed across providers, `local` always last.
- **Size**: desired capacity = backlog (A10G GPU-seconds from the job table) / `drain_target_hours`, capped by
  the number of queued jobs and `max_workers_total`; per provider by `max_workers` and `max_usd_per_hour`.
- **Fall back**: an unavailable provider, or a launch that raises, puts that option (capacity 10 min, API error
  5 min) or provider (quota/auth 1 h) on cooldown and the next option is tried in the same tick. A worker that
  has not heartbeated `health_timeout_s` (20 min) after launch, whose heartbeat stops for `heartbeat_lost_s`, or
  whose container exits before its first heartbeat is terminated and its option cooled down 30 min — its jobs are
  simply redelivered by SQS (resuming from plates already in S3).
- **Local** runs only while no GPU worker is up or launching (`only_when_no_gpu`).
- **Rebalance**: when a better option becomes usable (AWS quota approved, RunPod stock back) a replacement is
  launched for the worst-placed worker; the old one is terminated once the replacement heartbeats and the old one
  is idle — never mid-job.
- **Scale down**: queue empty → workers idle ≥ `idle_terminate_s` are terminated; surplus idle workers too.
- **Budget**: the summed hourly price of live workers never exceeds `budget.max_usd_per_hour` (launches are
  refused; over the cap, idle then most expensive workers are cut); compute spend (price × uptime per worker,
  per provider, in the state file) reaching `budget.max_total_usd` terminates everything. Per-run budgets stay in
  `orchestrator.py submit --budget`.
- **State** (`~/.story-farm/scheduler.json`, `FARM_STATE_DIR`): workers, cooldowns, spend, the last 500 decisions.
  `orchestrator.py status` / `scheduler.py status [--probe]` show them per provider.

### Price / speed planning

Cycles speed relative to an A10G (defaults in `providers.yaml`, override with measured numbers:
`scheduler.py calibrate --manifests <dir of job manifests> --out speed_calibration.json`, then set
`speed_calibration:`; it divides each job's model estimate by its measured seconds, median per `gpuClass`).
Sentinel final (41.9 A10G GPU-hours), `scheduler.py plan --spec episodes/sentinel/episode_v2.json --quality final`;
RunPod/Vast prices are the built-in list prices (live catalog/offer prices are used once a key is set):

| option | $/h | speed | $ per A10G-h | workers | wall h | $ |
|---|---|---|---|---|---|---|
| `aws_ec2/L4/spot` | 0.600 | 0.90 | 0.667 | 2 | 23.3 | 27.94 |
| `aws_ec2/A10G/spot` | 0.690 | 1.00 | 0.690 | 2 | 21.0 | 28.92 |
| `aws_ec2/L4/ondemand` | 0.805 | 0.90 | 0.894 | 2 | 23.3 | 37.48 |
| `aws_ec2/A10G/ondemand` | 1.006 | 1.00 | 1.006 | 2 | 21.0 | 42.17 |
| `runpod/RTX4090/ondemand` | 0.690 | 2.50 | 0.276 | 4 | 4.2 | 11.57 |
| `runpod/L40S/ondemand` | 0.860 | 2.20 | 0.391 | 4 | 4.8 | 16.39 |
| `vastai/RTX4090/ondemand` | 0.400 | 2.50 | 0.160 | 4 | 4.2 | 6.71 |
| `vastai/L40S/ondemand` | 0.750 | 2.20 | 0.341 | 4 | 4.8 | 14.29 |
| `local/CPU/ondemand` | 0 | 0.03 | — | 1 | ~1400 | 0 |

(The consumer-GPU speeds are Blender Open Data ratios, not measured here; on these numbers `strategy: cheapest`
would put Vast first. The default stays `priority` with AWS first because AWS workers use the instance role
(no static keys leave the account) and S3 traffic stays in-region; switch to `cheapest` to optimise cost.)

### Setup: what the operator creates (nothing here was created)

1. **External worker IAM user** (keys for RunPod/Vast/local workers: SQS consume, S3 inputs + `farm/code/*` read,
   plates/manifests/logs write, job table Get/UpdateItem — `ExternalWorkerPolicy` in `farm.yaml`). Either deploy
   the stack with `CreateExternalWorkerUser=true`, or attach the policy to a user you create:
   ```bash
   POLICY=$(aws cloudformation describe-stacks --stack-name $STACK \
     --query "Stacks[0].Outputs[?OutputKey=='ExternalWorkerPolicyArn'].OutputValue" --output text)
   aws iam create-user --user-name farm-worker-external                 # skip if CreateExternalWorkerUser=true
   aws iam attach-user-policy --user-name farm-worker-external --policy-arn $POLICY
   aws iam create-access-key --user-name farm-worker-external           # -> AccessKeyId / SecretAccessKey
   export FARM_EXTERNAL_AWS_ACCESS_KEY_ID=AKIA... FARM_EXTERNAL_AWS_SECRET_ACCESS_KEY=...
   ```
   The operator policy now also allows the scheduler's AWS calls (`servicequotas:GetServiceQuota`,
   `autoscaling:Describe*`, `SetDesiredCapacity`/`TerminateInstanceInAutoScalingGroup` on `story-farm-*` groups).
2. **RunPod**: console → **Settings → API Keys** → *Create API Key* (read/write; Pods + Catalog are enough) →
   `export RUNPOD_API_KEY=...`, and add credit (Billing). Optional: store the worker keys as RunPod secrets
   (console → Secrets) and set `secret_names: {AWS_SECRET_ACCESS_KEY: story_farm_aws_secret, ...}` so pods get
   `{{ RUNPOD_SECRET_story_farm_aws_secret }}` instead of the value.
3. **Vast.ai**: cloud.vast.ai → **Account → Keys** → *+ New* API key → `export VAST_API_KEY=...`; add credit.
4. **Code**: push the commit the workers should run (`code.commit: null` = local HEAD). Private repo: create a
   read-only deploy token (GitHub fine-grained token, Contents: read, this repo only) → `export FARM_GIT_TOKEN=...`;
   or set `code.source: s3` and no token is needed.
5. Review exactly what would be sent, then run:
   ```bash
   python3 cloud/farm/scheduler.py dry-run --out /tmp/farm-dry-run   # startup.sh, bootstrap.txt, payloads/*.json, plan.json
   python3 cloud/farm/scheduler.py --stack $STACK status --probe     # available() of every provider, no launches
   python3 cloud/farm/orchestrator.py --stack $STACK submit --spec episodes/sentinel/episode_v2.json --quality preview --budget 10
   python3 cloud/farm/orchestrator.py --stack $STACK watch --finish  # ticks the scheduler every loop
   python3 cloud/farm/scheduler.py --stack $STACK stop-all           # terminate every farm worker everywhere
   ```

## Presigned mode: GPU pods with no cloud credentials (`cloud/farm/presigned.py`)

External pods (RunPod first, Vast.ai) must not hold AWS keys, and creating IAM keys is not allowed. In presigned
mode the operator machine does every AWS call; a pod gets ONE env var, `MANIFEST_URL` (a presigned S3 GET of its
pod manifest), plus the non-secret `NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics` the container runtime
needs at create time to mount OptiX. No SQS, no DynamoDB, no tokens in the pod.

```
operator (AWS creds)                                   pod (no creds)
  split episode -> jobs (jobs.py), LPT onto N pods
  upload code tarball <root>code/<sha>.tar.gz           presigned_startup.sh  (container cmd, gzip+base64)
  reuse library_store/<rel> (sync-library) or upload      apt tools -> GET manifest -> GPU fail-fast
  spec snapshot, pod manifest (presigned URLs, 7 d) ->    Blender 4.2.3 (sha256) -> GET code (sha256)
  POST /v2/pods {env: {MANIFEST_URL}}                   presigned_pod.py
  watch: heartbeat/done/plates in S3, provider list       GET spec + library (sha256), render each job with
    dead -> terminate + new pod for missing frames         render_episode.py --skip-existing (OptiX/CUDA),
    done/idle -> terminate; budget -> stop all             PUT each PNG as soon as it is logged, PUT heartbeat
    complete -> pull plates -> episodes/<id>/plates/       every 60 s, job logs/manifests, done marker, idle
```

The manifest (`kind: story-farm-presigned-pod`) holds GET URLs for code/spec/library files (with sha256) and PUT
URLs (Content-Type signed) for every expected plate `<root>plates/<run>/<shot>/<frame>.png`, each job's log and
manifest, the heartbeat object (overwritten each beat), the pod log and the done marker. Keys: see the module
docstring. Presigned URLs expire after at most 7 days (SigV4 limit; sign with the IAM-user profile, not session
credentials, or URLs die with the session).

```bash
OP="env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN"   # use ~/.aws default profile
$OP python3 cloud/farm/presigned.py plan   --spec episodes/sentinel/episode_v4.json --quality preview --workers 4
$OP python3 cloud/farm/presigned.py submit --spec episodes/sentinel/episode_v4.json --quality preview \
      --provider runpod --gpu RTX4090 --workers 2 --budget 10 --frames 0-119 --dry-run   # prints create payloads
$OP python3 cloud/farm/presigned.py submit ... (same, without --dry-run)               # launches pods
$OP python3 cloud/farm/presigned.py watch --run <run>        # loop; --once for one tick; pulls plates when done
$OP python3 cloud/farm/presigned.py stop  --run <run>        # terminate every pod of the run
```

- RunPod: `POST https://api.runpod.io/v2/pods` (v2 OpenAPI, the same shape `providers/runpod.py` uses):
  `image nvidia/cuda:12.4.1-base-ubuntu22.04`, `gpu {id: "NVIDIA GeForce RTX 4090", count 1, minCudaVersion}`,
  `cloud SECURE`, `disk 40`, `entrypoint ["/bin/bash","-c"]`, `cmd [<bootstrap>]`, `ports []`. The key is
  injected by the network proxy for api.runpod.io: `RUNPOD_API_KEY` defaults to `proxy-injected`. The proxied key
  lists pods but has no `catalog:read`, so prices fall back to list prices (`--price` overrides).
- Vast.ai: the env field is a docker-flag string that rejects `&`/`%`, so the manifest URL rides inside the
  base64 startup script instead.
- Library: `--library auto` (default) ships catalog assets the spec / its world kits name plus the ones the
  renderer's own sources reference (HDRIs, deck texture, island trees + their `lod/` caches; ~860 MB for Sentinel);
  `spec` = spec/kits only; `none`. Audio kinds never ship.
- Code: `--code head` (default) = `git archive HEAD` of cloud/, factory/, studio/src/data, the assets symlink, plus
  the spec and every asset it references read from disk. `--code worktree` for uncommitted changes.
- Watch policy (`DEFAULTS` in presigned.py): no heartbeat 1800 s after launch or silent 600 s or provider says
  gone -> dead; up to 3 replacement generations per pod; `--budget` total and `--max-usd-per-hour` (default
  providers.yaml runpod.max_usd_per_hour) are enforced at submit, on replacements and every tick.
- Verified: `tests/farm/test_presigned.py` (moto S3 + mocked RunPod; and a local pod = subprocess running the real
  bootstrap command against a moto S3 server with curl), and `PRESIGNED_LIVE=1 ... tests/farm/test_presigned_live.py`
  (the REAL bucket under a throw-away prefix, real local CPU Blender, 2 frames at 64x112, everything deleted
  afterwards). No real pod has been launched.

## Not done / open

- **compute_fallback**: no real RunPod/Vast launch, account or key was created (no spend allowed); request shapes
  come from RunPod's v2 OpenAPI spec and Vast's API reference, verified only against mocks. RunPod's REST v2 has no
  spot/interruptible pods; the GraphQL path is deprecated and untested live. Vast `gpu_name` values ("RTX 4090")
  follow the API's stored names; the docs' examples also show "RTX_4090" (results are matched either way).
  Speeds of RTX 4090 / L40S / A100 are defaults, not measured. The AWS ASG's own backlog alarms still scale the spot
  group too; the scheduler only raises/lowers desired capacity and terminates instances. Per-run `spentUsd` in
  `orchestrator.py status` still prices GPU-seconds at the AWS rate; the scheduler's state has the real
  per-provider spend.

- No real AWS deploy, image build, or GPU render (no spend allowed; quota is 0 anyway). Seconds/frame on L4/A10G
  are extrapolated, not measured; OptiX inside the container is untested.
- The `Finish` composition (`studio/src/finish`) and `factory.qc` are other workstreams; `finish` calls them through
  overridable command templates (`--finish-cmd`/`--qc-cmd`, `FARM_FINISH_CMD`/`FARM_QC_CMD`) and runs where the
  orchestrator runs (needs Node + the studio deps), not on the GPU farm.
- Plates are PNG (what `render_episode.py` writes), not EXR as the architecture table says.
