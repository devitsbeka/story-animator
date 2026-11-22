"""
deploy.py - create/update the Lambda render workers in the operator's AWS account (boto3; no Docker, no AWS CLI).

    OP="env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN"     # ~/.aws default profile
    $OP python3 -m factory.compute.aws_lambda.deploy up        # stack -> CodeBuild image -> function
    $OP python3 -m factory.compute.aws_lambda.deploy status
    $OP python3 -m factory.compute.aws_lambda.deploy down      # delete the stack (+ images)

Steps of `up` (idempotent):
  1. zip Dockerfile + handler.py + buildspec.yml -> s3://<story-farm bucket>/compute/lambda-build/source.zip;
     the image tag is the sha256[:16] of that zip (same sources -> same tag -> no rebuild).
  2. CloudFormation stack `story-compute` (stack.yaml) with CreateFunction=false: ECR repo, CodeBuild project,
     roles, log groups.
  3. CodeBuild build (BUILD_GENERAL1_SMALL: 100 free build-minutes/month) unless the tag is already in ECR; the
     official Blender tarball is staged in S3 first (sha256-checked; download.blender.org 403s CodeBuild). With a
     CodeBuild build quota of 0 (new accounts) `--builder auto` falls back to imagebuild.py (Docker-free).
  4. stack update with CreateFunction=true, ImageTag=<tag>: the function (10240 MB, 10240 MB /tmp, 900 s). If the
     account refuses 10240 MB (new accounts can be capped at 3008 MB) it retries with --memory-fallback.

Equivalent AWS CLI (for operators who prefer it):
  aws s3 cp source.zip s3://$BUCKET/compute/lambda-build/source.zip
  aws cloudformation deploy --stack-name story-compute --template-file factory/compute/aws_lambda/stack.yaml \
      --capabilities CAPABILITY_NAMED_IAM --parameter-overrides SourceBucket=$BUCKET ImageTag=$TAG CreateFunction=false
  aws codebuild start-build --project-name story-compute-blender-lambda --environment-variables-override \
      name=IMAGE_TAG,value=$TAG
  aws cloudformation deploy ... CreateFunction=true
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
STACK = "story-compute"
FARM_STACK = "story-farm"
SOURCE_KEY = "compute/lambda-build/source.zip"
SOURCES = ("Dockerfile", "handler.py", "buildspec.yml")


def log(msg, **kw):
    print(json.dumps({"t": round(time.time(), 1), "msg": msg, **kw}, default=str), file=sys.stderr, flush=True)


def source_zip(here=HERE):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in SOURCES:
            info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            with open(os.path.join(here, name), "rb") as fh:
                z.writestr(info, fh.read())
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()[:16]


def farm_bucket(sess):
    outs = sess.client("cloudformation").describe_stacks(StackName=FARM_STACK)["Stacks"][0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outs}["BucketName"]


def stack_outputs(cfn, stack=STACK):
    try:
        st = cfn.describe_stacks(StackName=stack)["Stacks"][0]
    except Exception:  # noqa: BLE001 - missing stack
        return None, {}
    return st["StackStatus"], {o["OutputKey"]: o["OutputValue"] for o in st.get("Outputs", [])}


def stack_param(cfn, name, stack=STACK):
    st = cfn.describe_stacks(StackName=stack)["Stacks"][0]
    return {p["ParameterKey"]: p.get("ParameterValue") for p in st.get("Parameters", [])}.get(name)


def deploy_stack(cfn, params, stack=STACK, template=os.path.join(HERE, "stack.yaml")):
    with open(template) as fh:
        body = fh.read()
    p = [{"ParameterKey": k, "ParameterValue": str(v)} for k, v in params.items()]
    status, _ = stack_outputs(cfn, stack)
    kw = dict(StackName=stack, TemplateBody=body, Parameters=p, Capabilities=["CAPABILITY_NAMED_IAM"],
              Tags=[{"Key": "project", "Value": "story-animator"}, {"Key": "component", "Value": "compute-broker"}])
    if status is None or status == "REVIEW_IN_PROGRESS":
        cfn.create_stack(**kw, OnFailure="DELETE")
        waiter = "stack_create_complete"
    elif status == "ROLLBACK_COMPLETE":
        cfn.delete_stack(StackName=stack)
        cfn.get_waiter("stack_delete_complete").wait(StackName=stack)
        cfn.create_stack(**kw, OnFailure="DELETE")
        waiter = "stack_create_complete"
    else:
        try:
            cfn.update_stack(**kw)
        except cfn.exceptions.ClientError as e:
            if "No updates are to be performed" in str(e):
                return stack_outputs(cfn, stack)[1]
            raise
        waiter = "stack_update_complete"
    log("stack " + waiter.split("_")[1], stack=stack, params=params)
    try:
        cfn.get_waiter(waiter).wait(StackName=stack, WaiterConfig={"Delay": 10, "MaxAttempts": 180})
    except Exception as e:
        events = cfn.describe_stack_events(StackName=stack)["StackEvents"][:15]
        bad = [f"{ev['LogicalResourceId']}: {ev.get('ResourceStatusReason')}" for ev in events
               if "FAILED" in ev.get("ResourceStatus", "")]
        raise RuntimeError(f"stack {stack} failed: {bad or e}") from e
    return stack_outputs(cfn, stack)[1]


def image_exists(ecr, repo_name, tag):
    try:
        ecr.describe_images(repositoryName=repo_name, imageIds=[{"imageTag": tag}])
        return True
    except Exception:  # noqa: BLE001
        return False


def run_build(sess, project, tag, poll=15):
    cb, logs = sess.client("codebuild"), sess.client("logs")
    b = cb.start_build(projectName=project,
                       environmentVariablesOverride=[{"name": "IMAGE_TAG", "value": tag, "type": "PLAINTEXT"}])["build"]
    bid = b["id"]
    log("codebuild started", build=bid)
    t0 = time.time()
    while True:
        b = cb.batch_get_builds(ids=[bid])["builds"][0]
        if b["buildStatus"] != "IN_PROGRESS":
            break
        log("codebuild", phase=b.get("currentPhase"), elapsed_s=round(time.time() - t0))
        time.sleep(poll)
    minutes = sum((p.get("durationInSeconds") or 0) for p in b.get("phases", [])) / 60.0
    tail = []
    lg = b.get("logs", {})
    if lg.get("groupName") and lg.get("streamName"):
        try:
            ev = logs.get_log_events(logGroupName=lg["groupName"], logStreamName=lg["streamName"], limit=400,
                                     startFromHead=False)["events"]
            tail = [e["message"].rstrip() for e in ev]
        except Exception:  # noqa: BLE001
            pass
    res = {"build": bid, "status": b["buildStatus"], "minutes": round(minutes, 2),
           "computeType": b.get("environment", {}).get("computeType"),
           "imageBytes": next((int(x.split()[1]) for x in tail if x.startswith("IMAGE_BYTES")), None)}
    if b["buildStatus"] != "SUCCEEDED":
        res["logTail"] = tail[-150:]
    return res


def local_build(ecr, repo_name, out):
    """Docker-free fallback: assemble the same image in Python, run its Blender, push the layers to ECR."""
    from . import imagebuild
    plan = imagebuild.build(out)
    v = imagebuild.verify_rootfs(plan["rootfs"])
    if not v["ok"]:
        raise SystemExit(f"assembled image failed the Blender smoke test: {v}")
    pushed = imagebuild.push(plan, ecr, repo_name)
    return {"builder": "imagebuild", "status": "SUCCEEDED", "tag": pushed["tag"], "digest": pushed["digest"],
            "imageMb": round(plan["bytes"] / 1e6, 1), "pushedMb": pushed["pushedMb"], "smoke": v["out"],
            "rpms": [f"{r['name']}-{r['version']}" for r in plan["rpms"]]}


BLENDER_KEY = "compute/lambda-build/blender-4.2.3-linux-x64.tar.xz"


def stage_blender(s3, bucket, out):
    """Put the sha256-verified official Blender tarball next to the build source (once)."""
    from . import imagebuild
    try:
        h = s3.head_object(Bucket=bucket, Key=BLENDER_KEY)
        if h.get("Metadata", {}).get("sha256") == imagebuild.BLENDER_SHA256:
            return {"key": BLENDER_KEY, "uploaded": False}
    except Exception:  # noqa: BLE001 - not there yet
        pass
    os.makedirs(out, exist_ok=True)
    tb = os.path.join(out, os.path.basename(BLENDER_KEY))
    if not (os.path.isfile(tb) and imagebuild.sha256_file(tb) == imagebuild.BLENDER_SHA256):
        imagebuild.http(imagebuild.BLENDER_URL, dest=tb)
    if imagebuild.sha256_file(tb) != imagebuild.BLENDER_SHA256:
        raise SystemExit("blender tarball sha256 mismatch")
    s3.upload_file(tb, bucket, BLENDER_KEY, ExtraArgs={"Metadata": {"sha256": imagebuild.BLENDER_SHA256}})
    return {"key": BLENDER_KEY, "uploaded": True}


def up(sess, memory=10240, memory_fallback=3008, ephemeral=10240, compute="BUILD_GENERAL1_SMALL", force_build=False,
       builder="auto", out="/tmp/compute_broker/image"):
    """builder: codebuild | local | auto (CodeBuild; on a 0 build quota fall back to the Docker-free builder)."""
    cfn, s3, ecr = sess.client("cloudformation"), sess.client("s3"), sess.client("ecr")
    bucket = farm_bucket(sess)
    data, tag = source_zip()
    s3.put_object(Bucket=bucket, Key=SOURCE_KEY, Body=data, ContentType="application/zip")
    staged = stage_blender(s3, bucket, out) if builder != "local" else None
    log("build inputs staged", blender=staged)
    base = {"SourceBucket": bucket, "SourceKey": SOURCE_KEY, "BuildComputeType": compute, "BlenderKey": BLENDER_KEY}
    status, outs = stack_outputs(cfn)
    params = {**base, "ImageTag": tag, "CreateFunction": "true" if outs.get("FunctionName") else "false",
              "MemoryMb": outs.get("MemoryMb", memory), "EphemeralMb": ephemeral}
    # (re)deploy first so the build project's env (BLENDER_KEY, ...) matches this template; a live function keeps
    # its current image tag until the new image exists
    prev_tag = stack_param(cfn, "ImageTag") if outs.get("FunctionName") else tag
    outs = deploy_stack(cfn, {**params, "ImageTag": prev_tag,
                              "CreateFunction": "true" if outs.get("FunctionName") else "false"})
    repo_uri = outs["RepositoryUri"]
    repo_name = repo_uri.split("/", 1)[1]
    build = {"skipped": True, "reason": "image tag already in ECR"}
    if builder == "local":
        build = local_build(ecr, repo_name, out)
        tag = build["tag"]
    elif force_build or not image_exists(ecr, repo_name, tag):
        try:
            build = run_build(sess, outs["BuildProject"], tag)
        except Exception as e:  # noqa: BLE001 - AccountLimitExceededException: build quota 0
            if builder != "auto" or "AccountLimitExceeded" not in f"{type(e).__name__} {e}":
                raise
            log("codebuild unavailable; using the Docker-free builder", error=str(e)[:300])
            build = {"codebuild": str(e)[:300], **local_build(ecr, repo_name, out)}
            tag = build["tag"]
        log("image build done", **{k: v for k, v in build.items() if k != "logTail"})
        if build["status"] != "SUCCEEDED":
            print("\n".join(build.get("logTail", [])), file=sys.stderr)
            raise SystemExit(f"image build failed: {build['status']}")
    params["ImageTag"] = tag
    for mem in dict.fromkeys([int(memory), int(memory_fallback)]):
        try:
            outs = deploy_stack(cfn, {**params, "CreateFunction": "true", "MemoryMb": mem})
            break
        except RuntimeError as e:
            log("function deploy failed", memory=mem, error=str(e)[:400])
            if mem == int(memory_fallback):
                raise
    return {"stack": STACK, "bucket": bucket, "imageTag": tag, "build": build, "outputs": outs}


def status(sess):
    cfn, lam = sess.client("cloudformation"), sess.client("lambda")
    st, outs = stack_outputs(cfn)
    res = {"stack": STACK, "status": st, "outputs": outs}
    if outs.get("FunctionName"):
        c = lam.get_function_configuration(FunctionName=outs["FunctionName"])
        res["function"] = {k: c.get(k) for k in ("MemorySize", "Timeout", "State", "LastUpdateStatus", "CodeSize")}
        res["function"]["EphemeralMb"] = c.get("EphemeralStorage", {}).get("Size")
    res["account"] = lam.get_account_settings()["AccountLimit"]
    return res


def down(sess):
    cfn, ecr = sess.client("cloudformation"), sess.client("ecr")
    _, outs = stack_outputs(cfn)
    if outs.get("RepositoryUri"):
        name = outs["RepositoryUri"].split("/", 1)[1]
        ids = ecr.list_images(repositoryName=name).get("imageIds", [])
        if ids:
            ecr.batch_delete_image(repositoryName=name, imageIds=ids)
    cfn.delete_stack(StackName=STACK)
    cfn.get_waiter("stack_delete_complete").wait(StackName=STACK)
    return {"deleted": STACK}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("cmd", choices=["up", "status", "down", "zip"])
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--memory", type=int, default=10240)
    p.add_argument("--memory-fallback", type=int, default=3008)
    p.add_argument("--compute", default="BUILD_GENERAL1_SMALL")
    p.add_argument("--force-build", action="store_true")
    p.add_argument("--builder", choices=["auto", "codebuild", "local"], default="auto")
    p.add_argument("--out", default="/tmp/compute_broker/image", help="work dir of the Docker-free builder")
    a = p.parse_args(argv)
    if a.cmd == "zip":
        data, tag = source_zip()
        print(json.dumps({"bytes": len(data), "tag": tag}))
        return 0
    import boto3
    sess = boto3.session.Session(region_name=a.region)
    if a.cmd == "up":
        out = up(sess, a.memory, a.memory_fallback, compute=a.compute, force_build=a.force_build, builder=a.builder,
                 out=a.out)
    elif a.cmd == "status":
        out = status(sess)
    else:
        out = down(sess)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
