# Free compute for the render factory (checked 2026-11-22)

This is a list of every free or nearly free source of compute that can run headless Blender 4.2.3 renders through an API or CLI. Each entry gives the terms, the setup steps and the free frames per month. The machine-readable version is [`registry.yaml`](registry.yaml), which the compute broker reads (`factory/briefs/compute_broker.md`). Only sources marked `USE` can be scheduled by default. A `USE-WITH-CARE` source needs an explicit opt-in. An `AVOID` source is never scheduled.

How this was checked: provider pricing, terms and docs pages were fetched on 2026-11-22. Where a page would not render (Kaggle, Cloud Run), 2026 search snippets of the official pages and dated third-party trackers were used instead. Every entry in the registry lists its sources. Nothing was signed up for, no money was spent and no credentials were used. Values that could not be confirmed are marked "verify" in the registry.

## Headline

- **Free final frames (1080x1920, 64 spp plus denoise): about 12,000 per month**, counting every source except those marked AVOID. Most of this is Kaggle (5,600, opt-in), Oracle A1 (3,750, needs an arm64 Blender build) and Modal (2,000). Sources marked plain USE give about **2,600 per month**: Modal, Lambda, Cloud Run and Azure Container Apps. That is roughly one Sentinel-length episode (2,416 frames) per month at final quality, or about five per month if every source is enabled.
- **Free preview frames (270x480, 12 spp): over 450,000 per month**, which is more than the factory will ever need. Previews never need paid compute.
- **One-time credits** add roughly 30,000 final frames: the $300 GCP trial (~20k), the $200 Azure trial (~6k), Lightning AI (~1.2k) and the Alibaba FC trial (~0.85k). Startup credit programs add about 120k final frames per $1k granted, but only if the studio honestly qualifies.
- **Paid overflow is very cheap.** Salad gives an RTX 4090 for $0.16/h at batch priority, about $1.1 per 1,000 final frames. The Vast and Runpod community 4090 pools cost about $1.9–2.4 per 1,000. A whole Sentinel final costs about $3–6 on these pools. Free compute is about avoiding friction; it does not save much money.

## Throughput model (estimates; calibrate after the first run on each provider)

These figures start from the measured Sentinel v2 CPU plates: 8.6–13.5 s/frame at 270x480 and 16 spp on 2 shared threads (`docs/farm.md`). The measured Runpod RTX 4090 farm takes about 40 s/frame at full quality and 128 spp (`factory/briefs/_gpu_verify.md`). GPU-to-GPU ratios come from Blender Open Data.

| | preview 270x480 / 12 spp | final 1080x1920 / 64 spp + denoise |
|---|---|---|
| x86 CPU | ~20 vCPU-s/frame | ~1,100 vCPU-s/frame |
| Ampere A1 (arm64) core | ~25 core-s | ~1,375 core-s |
| RTX 4090 | ~2 s | ~25 s |
| L40S | ~2 s | ~28 s |
| L4 / A10G | ~2.5 s | ~50 s |
| T4 | ~4 s | ~150 s |
| P100 (CUDA, no OptiX) | ~5 s | ~220 s |

Per-shot scene build time (~27 s on 2 threads) is spread across each chunk. The cost per frame is therefore higher for tiny serverless chunks, and the CPU preview figure includes it.

## Ranked table: recurring free capacity, best first (final frames/month)

| # | id | type / hardware | free quota (reset) | max run | free final/mo | free preview/mo | verdict |
|---|---|---|---|---|---|---|---|
| 1 | `kaggle_gpu` | 2x T4 16 GB (or P100), 4 CPU, 29 GB | ~30 GPU-h/week (weekly, floating) | 12 h session | **~5,600** | ~200k | USE-WITH-CARE: opt-in, private kernels, ToS ambiguity |
| 2 | `oracle_a1_always_free` | 2 OCPU Ampere arm64, 12 GB, 200 GB | 1,500 OCPU-h + 9,000 GB-h (monthly), i.e. 24/7 | unlimited | **~3,750** | ~210k | USE-WITH-CARE: needs an arm64 Blender 4.2.3 that passes the goldens |
| 3 | `modal_starter` | L4 24 GB (T4…H100 available) | $30 credit (monthly) | 24 h | **~2,000** | ~40k | **USE** |
| 4 | `gcp_cloud_run_jobs` | 4–8 vCPU, up to 32 GiB, CPU | 240k vCPU-s + 450k GiB-s (monthly) | 168 h/task | ~218 | ~12,000 | **USE** |
| 5 | `aws_lambda` | ~5.8 vCPU, 10 GB, 10 GB /tmp | 400k GB-s + 1M req (monthly, always free) | **30 min** | ~200 | ~11,300 | **USE** |
| 6 | `azure_container_apps_jobs` | 4 vCPU, 8 GiB | 180k vCPU-s + 360k GiB-s (monthly) | configurable | ~160 | ~9,000 | **USE** |
| 7 | `ibm_code_engine` | CPU | 100k vCPU-s + 200k GB-s (monthly) | verify | ~90 | ~5,000 | USE-WITH-CARE: verify limits |
| 8 | `cloudflare_containers` | 4 vCPU, 12 GiB, 20 GB | 375 vCPU-min with Workers Paid **$5/mo** | — | ~20 | ~1,100 | USE-WITH-CARE: not free |
| | **Total (all non-AVOID)** | | | | **~12,000** | **>450k** | |

### One-time credits and trials

| id | what | free final frames (once) | verdict |
|---|---|---|---|
| `gcp_trial_credit` | $300 / 90 days. GPUs need the billing account upgraded to paid, and the trial cannot raise quota. Cloud Run L4 is $0.0001867/s for the GPU, about $1.05/h with 4 vCPU and 16 GiB | ~20,000 | USE-WITH-CARE: new customers only; the ledger stops at $300 |
| `azure_trial_credit` | $200 / 30 days, CPU in practice (GPU quota on a trial is normally 0) | ~6,000 (CPU) | USE-WITH-CARE: 30-day window |
| `lightning_ai_free` | 5 credits, plus 25 with a card, about 50 interruptible GPU-hours. **One-time since late 2026** and they expire after 12 months. One Studio, restarted every 4 h | ~1,200 | USE-WITH-CARE |
| `alibaba_fc_trial` | $29.7 over 3 months: 500k vCPU-s + 1M GB-s of GPU memory (~17 T4-h) | ~850 | USE-WITH-CARE: KYC, low priority |
| `aws_free_plan_credit` | $100 + $100 over 6 months, **new customers only** | — | AVOID: the factory already has an AWS account |
| `startup_credit_programs` | Google for Startups (~$2k Start tier, up to $200k/$350k), AWS Activate Founders ($1k, up to $5k), Microsoft for Startups ($1k, then $5k), NVIDIA Inception (partner credits), Modal and Intel Liftoff | ~120k per $1k | USE-WITH-CARE: only on honest eligibility; the user applies |

### Not farm capacity

| id | verdict | why |
|---|---|---|
| `sheepit` | USE-WITH-CARE (manual only) | Free volunteer Blender farm, ~500 machines, gated by points (your own frames earn 30%). No upload API. 3 projects at once, 2 GB per project, **no Python scripts**, so scenes must be fully baked. Your .blend files go to strangers' machines. Use only for non-confidential scenes. |
| `github_actions` | USE-WITH-CARE (tests only) | Terms forbid "any other activity unrelated to the production, testing, deployment, or publication of the software project" and use "as part of a serverless application". Fine for golden and stress renders in `tools/merge_gate.sh`; never for episode frames. |
| `github_codespaces` | AVOID | Limited to development and testing by the same terms. |

### AVOID (and why)

- **Google Colab (free):** the FAQ disallows "remote control such as SSH shells… bypassing the notebook UI… running distributed computing workers" on free runtimes. A farm worker is exactly that, and Colab has no launch API.
- **HF ZeroGPU:** 5 GPU-minutes per day, Gradio Spaces only. That is about 10 frames.
- **HF Spaces CPU Basic:** the docs list 2 vCPU / 16 GB free, but mid-2026 forum reports describe "CPU-basic quota limit" errors and staff saying PRO is required. Spaces exist to host demos, and keeping a worker awake games the 48 h sleep policy.
- **SageMaker Studio Lab:** closed to new customers.
- **Paperspace Gradient Free:** the M4000 is from 2015 and has no RT cores. Free notebooks are public, capacity is rarely available, there is a 6 h cap and a card is required.
- **Saturn Cloud:** the free-hours figure (150 h) dates from 2023 and is no longer published. Re-check later.
- **Deepnote:** no GPU on free plans.
- **Intel Tiber AI Cloud free:** "Premium or Enterprise account is required to deploy or test production workloads." The paid Intel Max GPU is $0.39/h, and Cycles can use it through oneAPI.
- **NVIDIA Brev / LaunchPad:** credits must be prepaid, and there is no published free grant.
- **Vercel / Netlify functions:** the ~250 MB bundle limit is too small for Blender (~1 GB unpacked). They also have short timeouts, no container images, and Vercel Hobby is non-commercial.
- **Cloudflare Workers:** V8 isolates cannot run native binaries. Cloudflare Containers is the option instead.
- **GCP e2-micro / OCI E2.1.Micro:** 1 GB RAM cannot load a shot.
- **Azure Functions:** the Consumption plan has no custom containers and a 10-minute cap. Container Apps jobs come with the same free grant.
- **Cloud Run functions:** they share the Cloud Run services free tier, and Cloud Run jobs do the same work better.
- **Huawei FunctionGraph / Tencent SCF:** the free quotas could not be verified, and mainland real-name KYC is required.

## Paid baselines (cheapest $ per 1,000 final frames)

| provider | GPU | $/h | $/1k final frames |
|---|---|---|---|
| Salad (batch priority) | RTX 3090 / 4090 / 5090 | 0.09 / 0.16 / 0.25 | 1.00 / 1.11 / ~1.25 |
| Vast.ai (cheapest host; median) | RTX 3090 | 0.09 (0.20) | 1.00 (2.2) |
| Vast.ai | RTX 4090 | 0.27 (0.50) | 1.9 (3.5) |
| Runpod Community | 4090 / 3090 / A5000 / L4 | 0.34 / 0.22 / 0.16 / 0.44 | 2.4 / 2.4 / 2.7 / 6.1 |
| Runpod Secure | 4090 | 0.89 | 6.2 |
| AWS g6.xlarge spot (L4) | L4 | ~0.60 | 8.3 |
| Modal (after the credit) | L4 / T4 | 0.80 / 0.59 | 14.2 / 18 |
| Cloud Run GPU | L4 + 4 vCPU/16 GiB | ~1.05 | 14.6 |

Lambda Labs, TensorDock and CoreWeave prices were not verified in this pass. CoreWeave sells only by contract and has no T4/L4 spot. Salad and Vast hosts are third-party consumer machines, so scene assets leave your control there.

## Per-source notes and setup

**Modal (USE, priority 1).** The $30 monthly Starter credit allows 100 containers and 10 concurrent GPUs. The terms ban only mining, DoS, P2P and media hosting (§1.5); rendering is fine for "Customer's internal business". To set it up, run `pip install modal && modal token new` and keep the token in `~/.factory_secrets.env`. Build a `modal.Image` from Debian plus the 4.2.3 tarball, then `.map()` the chunks over `gpu="L4"` and PUT the frames to presigned S3 URLs. Set the workspace spend limit to $0 above the credit. L4 gives the most frames per credit dollar (~72 final frames/h at ~$1.02/h including CPU and RAM).

**Oracle A1 (USE-WITH-CARE, priority 2).** This is the largest *safe-by-terms* recurring CPU source. It runs 24/7 and is never idle while rendering, so it is not reclaimed. Two caveats: (1) the allowance was **halved in mid-2026 to 2 OCPU / 12 GB** for Always-Free tenancies, and going over it disables the A1 instances and deletes them after 30 days; (2) **blender.org ships no linux-arm64 build**, so a 4.2.3 arm64 build is needed (community or from source). It must match the x86 goldens before it renders finals. Use it for previews right away and for finals once the goldens pass. Capacity errors ("out of host capacity") are common, so choose the home region carefully.

**Kaggle (USE-WITH-CARE, priority 3).** This is the biggest free GPU pool: about 30 h/week on 2x T4 with 12 h sessions, launched with `kaggle kernels push` / `status` / `output`. The AUP bans "abuse [of] resources … e.g. cryptomining, DDOS attacks, server farming". Rendering is not named, but a render farm is close enough to "server farming" that the risk is real. Conditions: opt-in only, private kernels, a single account, stay within the weekly quota, and treat the loss of the account as acceptable. Internet access needs a phone-verified account. Store Blender as a private Dataset to skip the download.

**AWS Lambda (USE, priority 4).** As of 2026-11-22 the docs give the **max timeout as 30 min (1,800 s)**, up from 15 min. That fits about 9 final frames or about 500 preview frames per invocation at 10,240 MB (~5.8 vCPU). The free 400k GB-s is about 11 h at 10 GB, roughly 226k vCPU-s. This account's concurrency is 10 for now. The image is up to 10 GB from ECR, so build it with CodeBuild (compute_broker brief).

**Cloud Run jobs (USE, priority 5).** The jobs tier is 240k vCPU-s and 450k GiB-s per month (services get 180k/360k). Tasks can run up to 168 h. Use 4 vCPU / 7.5 GiB per task and `CLOUD_RUN_TASK_INDEX` to pick the chunk. It needs a billing account. Watch egress: 1 GiB is free from North America, so write PNG previews to GCS in the same region or keep the EXRs small.

**Azure Container Apps jobs (USE, priority 6).** The grant is 180k vCPU-s and 360k GiB-s per subscription per month, on the Consumption plan at up to 4 vCPU / 8 GiB per replica. Create it with `az containerapp job create --trigger-type Manual --parallelism N`.

**IBM Code Engine (USE-WITH-CARE, priority 7).** The always-free allowance is 100k vCPU-s and 200k GB-s. Verify the job max runtime on the first test run.

## What the user must sign up for (ordered by value; no sign-up was done here)

1. **Modal**: GitHub login and a card. Set a spend limit equal to the credit. Gives $30/mo, about 2,000 final frames. Low risk.
2. **Oracle Cloud Always Free**: card and phone. Pick a home region with A1 capacity, because it cannot be changed later. About 3,750 final frames or 210k previews per month, 24/7. Needs the arm64 Blender build.
3. **Kaggle**: phone verification and an API token. Opt-in only, given the AUP risk. About 5,600 final frames per month.
4. **Google Cloud**: billing account. Gives Cloud Run jobs free every month, plus the $300 trial (upgrade to paid to use the L4; cap it with a budget), about 20k final frames once.
5. **Azure**: card and phone. Gives the Container Apps monthly grant plus $200 over 30 days. Activate it right before a big render.
6. *(Optional)* **Startup programs**: Google for Startups, AWS Activate Founders, Microsoft for Startups, NVIDIA Inception. Apply only if the studio genuinely qualifies; these give the largest grants.
7. *(Optional)* **Lightning AI** (one-time ~50 GPU-h) and **IBM Cloud** (Code Engine free tier).
8. *(Already done)* **AWS**: the existing account and Lambda free tier. Raise the Lambda concurrency quota (requested 1,000).
9. *(Paid overflow, no free tier)* **Salad**, plus the existing Vast and Runpod accounts.

Secrets (Modal token, kaggle.json, OCI API key, Azure and GCP service principals) belong only in `~/.factory_secrets.env` (CLAUDE.md rule 5).
