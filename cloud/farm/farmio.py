"""
farmio.py - the AWS plumbing shared by worker.py and orchestrator.py (S3 sync, SQS, DynamoDB job state).

Everything takes explicit boto3 clients so tests can run against moto and nothing is created at import.

S3 layout (one bucket, FARM_BUCKET):
  library_store/...                                  shared CC0 library (mirror of $LIBRARY_STORE)
  assets/...                                         repo assets referenced by episode specs (hero.glb, ...)
  episodes/<id>/runs/<runId>/episode.json            immutable spec snapshot per run
  episodes/<id>/runs/<runId>/plates/<shot>/####.png  plates (+ _render_<a>_<b>.json from the renderer)
  farm/runs/<runId>/run.json                         the submitted plan
  farm/runs/<runId>/jobs/<jobId>.json                per-job manifest; status DONE there == job complete
  farm/runs/<runId>/logs/<jobId>.<attempt>.log       Blender log of every attempt

DynamoDB (FARM_TABLE, pk/sk strings, on-demand):
  pk=RUN#<runId> sk=META          run record: episodeId, status, estUsd, jobCount, doneJobs, gpuSeconds, ...
  pk=RUN#<runId> sk=JOB#<jobId>   job record: status PENDING|RUNNING|DONE|FAILED|CANCELLED, attempts, lease
"""
import hashlib
import json
import os
import tempfile
import time

RUN_ACTIVE = ("QUEUED", "RUNNING", "RENDERED", "FINISHING")
TERMINAL_JOB = ("DONE", "FAILED", "CANCELLED")


# ----------------------------------------------------------------------------------------------- S3
def sha256_file(path, bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(bufsize), b""):
            h.update(b)
    return h.hexdigest()


def s3_list(s3, bucket, prefix):
    """-> {key: size}"""
    out = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []) or []:
            out[o["Key"]] = o["Size"]
    return out


def s3_exists(s3, bucket, key):
    from botocore.exceptions import ClientError
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def s3_get_json(s3, bucket, key, default=None):
    from botocore.exceptions import ClientError
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return default
        raise


def s3_put_json(s3, bucket, key, obj):
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(obj, indent=1).encode(), ContentType="application/json")


def download_atomic(s3, bucket, key, dst):
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".part-", dir=os.path.dirname(dst) or ".")
    os.close(fd)
    try:
        s3.download_file(bucket, key, tmp)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dst


def sync_down(s3, bucket, prefix, dest, strip=None):
    """Mirror s3://bucket/prefix -> dest (skip files whose local size already matches). -> (fetched, skipped)."""
    strip = prefix if strip is None else strip
    fetched = skipped = 0
    for key, size in s3_list(s3, bucket, prefix).items():
        if key.endswith("/"):
            continue
        rel = key[len(strip):].lstrip("/")
        dst = os.path.join(dest, rel)
        if os.path.isfile(dst) and os.path.getsize(dst) == size:
            skipped += 1
            continue
        download_atomic(s3, bucket, key, dst)
        fetched += 1
    return fetched, skipped


def sync_up(s3, bucket, src_dir, prefix, content_type=None, skip=lambda rel: False):
    """Mirror src_dir -> s3://bucket/prefix (skip keys whose remote size matches). -> (uploaded, skipped)."""
    remote = s3_list(s3, bucket, prefix)
    up = sk = 0
    for d, _, files in os.walk(src_dir):
        for f in sorted(files):
            p = os.path.join(d, f)
            rel = os.path.relpath(p, src_dir).replace(os.sep, "/")
            if f.startswith(".part-") or skip(rel):
                continue
            key = prefix.rstrip("/") + "/" + rel
            if remote.get(key) == os.path.getsize(p):
                sk += 1
                continue
            extra = {"ContentType": content_type or _ctype(p)}
            s3.upload_file(p, bucket, key, ExtraArgs=extra)
            up += 1
    return up, sk


def _ctype(path):
    ext = os.path.splitext(path)[1].lower()
    return {".png": "image/png", ".json": "application/json", ".log": "text/plain", ".exr": "image/x-exr",
            ".glb": "model/gltf-binary", ".jpg": "image/jpeg", ".mp4": "video/mp4"}.get(ext, "application/octet-stream")


# ----------------------------------------------------------------------------------------------- keys
def spec_key(episode_id, run_id):
    return f"episodes/{episode_id}/runs/{run_id}/episode.json"


def plates_prefix(episode_id, run_id):
    return f"episodes/{episode_id}/runs/{run_id}/plates/"


def manifest_key(run_id, job_id):
    return f"farm/runs/{run_id}/jobs/{job_id}.json"


def log_key(run_id, job_id, attempt):
    return f"farm/runs/{run_id}/logs/{job_id}.{attempt}.log"


def run_key(run_id):
    return f"farm/runs/{run_id}/run.json"


# ----------------------------------------------------------------------------------------------- DynamoDB
def _ser(v):
    from boto3.dynamodb.types import TypeSerializer
    return TypeSerializer().serialize(_dec(v))


def _dec(v):
    from decimal import Decimal
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _dec(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_dec(x) for x in v]
    return v


def _des(item):
    from boto3.dynamodb.types import TypeDeserializer
    from decimal import Decimal
    td = TypeDeserializer()

    def plain(x):
        if isinstance(x, Decimal):
            return int(x) if x == x.to_integral_value() else float(x)
        if isinstance(x, dict):
            return {k: plain(v) for k, v in x.items()}
        if isinstance(x, list):
            return [plain(v) for v in x]
        return x
    return {k: plain(td.deserialize(v)) for k, v in item.items()}


class Store:
    """Job/run state in one DynamoDB table (client API, so moto and real AWS behave the same)."""

    def __init__(self, ddb, table):
        self.ddb, self.table = ddb, table

    # --- runs
    def put_run(self, run):
        item = {"pk": f"RUN#{run['runId']}", "sk": "META", **run}
        self.ddb.put_item(TableName=self.table, Item={k: _ser(v) for k, v in item.items() if v is not None},
                          ConditionExpression="attribute_not_exists(pk)")

    def get_run(self, run_id):
        r = self.ddb.get_item(TableName=self.table, Key={"pk": {"S": f"RUN#{run_id}"}, "sk": {"S": "META"}},
                              ConsistentRead=True).get("Item")
        return _des(r) if r else None

    def set_run_status(self, run_id, status, **extra):
        names, vals, sets = {"#s": "status"}, {":s": _ser(status), ":t": _ser(int(time.time()))}, ["#s = :s", "updatedAt = :t"]
        for i, (k, v) in enumerate(extra.items()):
            names[f"#e{i}"] = k
            vals[f":e{i}"] = _ser(v)
            sets.append(f"#e{i} = :e{i}")
        self.ddb.update_item(TableName=self.table, Key={"pk": {"S": f"RUN#{run_id}"}, "sk": {"S": "META"}},
                             UpdateExpression="SET " + ", ".join(sets), ExpressionAttributeNames=names,
                             ExpressionAttributeValues=vals)

    def list_runs(self):
        out, kw = [], {}
        while True:
            r = self.ddb.scan(TableName=self.table, FilterExpression="sk = :m",
                              ExpressionAttributeValues={":m": {"S": "META"}}, **kw)
            out += [_des(i) for i in r.get("Items", [])]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def add_run_progress(self, run_id, done=0, gpu_seconds=0.0):
        self.ddb.update_item(TableName=self.table, Key={"pk": {"S": f"RUN#{run_id}"}, "sk": {"S": "META"}},
                             UpdateExpression="ADD doneJobs :d, gpuSeconds :g",
                             ExpressionAttributeValues={":d": _ser(done), ":g": _ser(float(gpu_seconds))})

    # --- jobs
    def put_jobs(self, run_id, jobs):
        for j in jobs:
            item = {"pk": f"RUN#{run_id}", "sk": f"JOB#{j['jobId']}", "status": "PENDING", "attempts": 0,
                    "shot": j["shot"], "frameStart": j["frameStart"], "frameEnd": j["frameEnd"],
                    "estSeconds": j["estSeconds"]}
            self.ddb.put_item(TableName=self.table, Item={k: _ser(v) for k, v in item.items()})

    def list_jobs(self, run_id):
        out, kw = [], {}
        while True:
            r = self.ddb.query(TableName=self.table, KeyConditionExpression="pk = :p AND begins_with(sk, :j)",
                               ExpressionAttributeValues={":p": {"S": f"RUN#{run_id}"}, ":j": {"S": "JOB#"}},
                               ConsistentRead=True, **kw)
            out += [_des(i) for i in r.get("Items", [])]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def get_job(self, run_id, job_id):
        r = self.ddb.get_item(TableName=self.table, Key=self._jk(run_id, job_id), ConsistentRead=True).get("Item")
        return _des(r) if r else None

    @staticmethod
    def _jk(run_id, job_id):
        return {"pk": {"S": f"RUN#{run_id}"}, "sk": {"S": f"JOB#{job_id}"}}

    def claim_job(self, run_id, job_id, worker, lease_s):
        """Take the job lease. False if it is DONE/CANCELLED or another worker holds a live lease."""
        from botocore.exceptions import ClientError
        now = int(time.time())
        try:
            self.ddb.update_item(
                TableName=self.table, Key=self._jk(run_id, job_id),
                UpdateExpression="SET #s = :r, worker = :w, leaseUntil = :l, startedAt = :n ADD attempts :one",
                ConditionExpression="attribute_not_exists(#s) OR (#s <> :d AND #s <> :c AND "
                                    "(#s <> :r OR leaseUntil < :n OR worker = :w))",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":r": _ser("RUNNING"), ":w": _ser(worker), ":l": _ser(now + lease_s),
                                           ":n": _ser(now), ":one": _ser(1), ":d": _ser("DONE"),
                                           ":c": _ser("CANCELLED")})
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def renew_lease(self, run_id, job_id, worker, lease_s):
        from botocore.exceptions import ClientError
        try:
            self.ddb.update_item(TableName=self.table, Key=self._jk(run_id, job_id),
                                 UpdateExpression="SET leaseUntil = :l", ConditionExpression="worker = :w",
                                 ExpressionAttributeValues={":l": _ser(int(time.time()) + lease_s), ":w": _ser(worker)})
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def finish_job(self, run_id, job_id, status, **extra):
        """Set a job's status; when it first becomes DONE also bump the run's progress counters (exactly once)."""
        from botocore.exceptions import ClientError
        names, vals = {"#s": "status"}, {":s": _ser(status), ":t": _ser(int(time.time()))}
        sets = ["#s = :s", "finishedAt = :t"]
        for i, (k, v) in enumerate(extra.items()):
            names[f"#e{i}"] = k
            vals[f":e{i}"] = _ser(v)
            sets.append(f"#e{i} = :e{i}")
        vals[":dn"] = _ser("DONE")
        try:  # a DONE job is final: never overwrite it (late failure of a duplicate delivery, double count)
            self.ddb.update_item(TableName=self.table, Key=self._jk(run_id, job_id),
                                 UpdateExpression="SET " + ", ".join(sets), ExpressionAttributeNames=names,
                                 ExpressionAttributeValues=vals,
                                 ConditionExpression="attribute_not_exists(#s) OR #s <> :dn")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False  # already DONE: keep it, do not double count
            raise
        if status == "DONE":
            self.add_run_progress(run_id, done=1, gpu_seconds=float(extra.get("gpuSeconds", 0.0)))
        return True


# ----------------------------------------------------------------------------------------------- SQS
def send_jobs(sqs, queue_url, messages):
    """Batch-send job messages (10 per call); raise if any entry fails."""
    sent = 0
    for i in range(0, len(messages), 10):
        batch = messages[i:i + 10]
        r = sqs.send_message_batch(QueueUrl=queue_url, Entries=[
            {"Id": str(n), "MessageBody": json.dumps(m)} for n, m in enumerate(batch)])
        if r.get("Failed"):
            raise RuntimeError(f"SQS send failed for {len(r['Failed'])} messages: {r['Failed'][:2]}")
        sent += len(r.get("Successful", []))
    return sent


def stack_outputs(cfn, stack_name):
    """Read-only: the farm stack's outputs as {OutputKey: value}."""
    st = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in st.get("Outputs", [])}
