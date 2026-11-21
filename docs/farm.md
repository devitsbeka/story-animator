# GPU render farm (AWS, as code)

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
| `tests/farm/` | Job-splitting unit tests + worker/orchestrator end to end on moto with a fake Blender. |

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

## Not done / open

- No real AWS deploy, image build, or GPU render (no spend allowed; quota is 0 anyway). Seconds/frame on L4/A10G
  are extrapolated, not measured; OptiX inside the container is untested.
- The `Finish` composition (`studio/src/finish`) and `factory.qc` are other workstreams; `finish` calls them through
  overridable command templates (`--finish-cmd`/`--qc-cmd`, `FARM_FINISH_CMD`/`FARM_QC_CMD`) and runs where the
  orchestrator runs (needs Node + the studio deps), not on the GPU farm.
- Plates are PNG (what `render_episode.py` writes), not EXR as the architecture table says.
