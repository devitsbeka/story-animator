"""
stubs.py - providers whose launch contract is fixed here but not implemented yet (never schedulable).

Every adapter implements the same contract (base.py): start(task) gets {chunk, attempt, manifestUrl} and must
run, on the provider, the equivalent of

    BLENDER=/opt/blender/blender CHUNK_TMP=<scratch> python3 handler.py   # factory/compute/aws_lambda/handler.py
    handler({"manifestUrl": <url>, "attempt": <id>})

i.e. GET the manifest, GET code/spec/library (sha256-checked), render with cloud/blender/render_episode.py, PUT
every frame + job manifest + done marker to the presigned URLs. No cloud credentials ever leave the operator:
the task only receives the manifest URL. The image is the same one the Lambda uses (ECR
story-compute/blender-lambda, x86_64) or any image with Blender 4.2.3 + Python 3.

Implementing one = fill start()/poll()/cancel() with the provider's API and set the per-provider quota unit so the
ledger can meter it. Contracts (as read from the providers' docs; the free-compute registry re-verifies terms):
"""
from .base import StubAdapter


class GcpCloudRunJobs(StubAdapter):
    name = "gcp_cloud_run_jobs"
    contract = """Cloud Run Jobs (gcloud / run.googleapis.com v2):
    create once: jobs.create {template.template.containers[0]: {image: <Artifact Registry copy of the image>,
                 command: ["python3", "/var/task/handler.py"], resources.limits: {cpu: "8", memory: "32Gi"}},
                 timeout: "3600s", maxRetries: 0}
    start(task): jobs.run with overrides.containerOverrides[0].env = [{name: MANIFEST_URL, value: <url>}],
                 taskCount 1 -> execution name;  poll: executions.get -> succeededCount/failedCount, and
                 completionTime-startTime x vCPU / GiB for the ledger (free: 180k vCPU-s + 360k GiB-s / month).
    auth: the operator's own gcloud credentials; the job's service account needs NO bucket access."""


class AzureContainerApps(StubAdapter):
    name = "azure_container_apps"
    contract = """Azure Container Apps jobs (az containerapp job / ARM):
    create once: job with triggerType Manual, replicaTimeout 3600, container image + 4 vCPU / 8 GiB.
    start(task): POST .../jobs/<job>/start with template.containers[0].env [{name: MANIFEST_URL, value}]
                 -> execution; poll: GET .../executions/<id> status Succeeded/Failed; meter vCPU-s / GiB-s
                 (free grant 180k vCPU-s + 360k GiB-s / month per subscription)."""


class Modal(StubAdapter):
    name = "modal"
    contract = """Modal (modal Python SDK, the operator's own token):
    app = modal.App("story-compute"); image = modal.Image.from_registry(<image>) ;
    @app.function(gpu="L4", timeout=3600) def render(manifest_url): handler({"manifestUrl": manifest_url, ...})
    start(task): render.spawn(url) -> FunctionCall id;  poll: FunctionCall.from_id(id).get(timeout=0);
    meter: credits-usd from Modal's usage (monthly free credits)."""


class Kaggle(StubAdapter):
    name = "kaggle"
    contract = """Kaggle kernels API (kaggle CLI, the operator's own kaggle.json):
    start(task): `kaggle kernels push` of a generated notebook (enable_gpu true, enable_internet true) whose
                 first cell downloads Blender 4.2.3 (sha256) and runs handler.py with MANIFEST_URL baked into
                 the notebook source;  poll: `kaggle kernels status`;  meter GPU-h per ISO week (30 h free).
    terms: USE-WITH-CARE - only when the registry verdict says batch rendering is acceptable."""


class OracleAlwaysFree(StubAdapter):
    name = "oracle_always_free"
    contract = """Oracle Cloud Always Free Ampere A1 VM (OCI CLI, the operator's own tenancy):
    a long-lived VM runs the member-node worker (python -m factory.compute.node --join <invite>) - i.e. it is
    driven through the member_node pull protocol, not push. Needs an arm64 Blender build (4.2 has none
    official; use 4.4+ arm64 or a distro build) - so it stays a stub until the renderer is validated there."""


class HfSpaces(StubAdapter):
    name = "hf_spaces"
    contract = """Hugging Face Spaces (Docker SDK, CPU basic 2 vCPU / 16 GB, the operator's own HF token):
    a Space runs the member-node worker (pull protocol) with the invite token as a Space secret; Spaces sleep
    when idle and are meant for demos - terms USE-WITH-CARE."""


STUBS = {c.name: c for c in (GcpCloudRunJobs, AzureContainerApps, Modal, Kaggle, OracleAlwaysFree, HfSpaces)}
