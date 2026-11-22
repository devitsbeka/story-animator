# Member nodes: lend your own machine to the episode farm

A **member node** is a team member's own computer (or a VM in *their own* cloud account) that renders chunks of an
episode for the compute broker (`factory/compute/`). It is one command, needs no cloud credentials, and the member
stays in control of it.

## Ground rules

- **The broker never creates accounts, never signs up anywhere, never registers on any provider on anyone's behalf,
  and never holds anyone else's credentials.** If a member wants to use a cloud VM, they create it in their own
  account themselves and run the node there.
- **No credentials travel in either direction.** The lead's AWS keys never leave the lead's machine; the node gets
  only presigned S3 URLs (time-limited, one object each). The node never sends the lead any secret either.
- **The member sets the limits** (maximum render hours, GPU only when idle, no CPU work, which qualities) on the node
  itself. The broker reads them and respects them, and the node enforces them locally too.
- **The lead can revoke an invite at any time.** The node stops on its next poll (every 20 s by default).
- **Results from member nodes are not trusted** until verified (checksums + spot re-renders, below).

## For the lead

```bash
OP="env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN"   # the operator's ~/.aws profile
$OP python -m factory.compute invite --name alice --days 7     # -> {"node": "n-…", "token": "sfc1.…"}
$OP python -m factory.compute nodes                            # who joined, capabilities, limits, heartbeat, trust
$OP python -m factory.compute revoke --node n-…                # any time
```

Send the token to the member privately (it is a capability: whoever holds it can join as that node until it is
revoked or expires). Invites last at most 7 days (the SigV4 presigning limit); a joined node's URLs are renewed
through its inbox while it keeps working, so a long-running node does not need a new token.

Member nodes then take part in every broker run like any other provider (`member_node` in
`factory/compute/broker.yaml`): the planner counts each live, idle node with its own capabilities, and the
work-stealing queue gives it chunks sized for it.

## For the member

Requirements: Linux (or WSL), Python 3.9+, Blender 4.2 LTS (`blender` on PATH or `--blender /path/to/blender`),
an NVIDIA GPU optional (CPU works for previews), outbound HTTPS to `*.s3.amazonaws.com`.

```bash
git clone <this repo> && cd story-animator          # only factory/compute is used on the node
python -m factory.compute.node --join sfc1.XXXX \
    --blender ~/blender-4.2.3-linux-x64/blender \
    --max-hours 20 \                                # stop taking work after 20 h of rendering on this node
    --gpu-only-when-idle \                          # pause while a game / training job / anything uses the GPU
    --qualities preview,final                       # or just preview
#   --no-cpu                                        # refuse work if this machine has no GPU
```

Or in a container (the broker's Lambda image already has Blender 4.2.3 and the node code is fetched with the repo):

```bash
docker run --rm --gpus all -e JOIN=sfc1.XXXX -v $PWD:/repo -w /repo \
    <account>.dkr.ecr.us-east-1.amazonaws.com/story-compute/blender-lambda:<tag> \
    python3 -m factory.compute.node --join "$JOIN" --blender /opt/blender/blender --gpu-only-when-idle
```

Ctrl-C stops the node at any time; the chunk it was rendering is simply re-queued elsewhere when its heartbeat
stops. Local state (hours used) is in `~/.story-compute-node/<node>.json`.

What the node does — nothing else:

1. resolves the token (a presigned GET of its invite) into three URLs: PUT `hello.json`, PUT `heartbeat.json`,
   GET `inbox.json`;
2. detects its capabilities (`nvidia-smi`: GPU model, VRAM, utilisation; CPU count; RAM) and PUTs them with the
   member's limits;
3. polls the inbox. An assignment is ONE chunk-manifest URL (the same document a Lambda worker gets): GET the code
   tarball, episode spec and library files (each sha256-checked), run Blender `render_episode.py` on the chunk's
   frames, PUT each frame, the job log/manifest and a done marker to the presigned PUT URLs in the manifest;
4. heartbeats its state (`idle`, `rendering`, `paused`, `limit`, `failed`, `revoked`) and hours used.

## Protocol (S3, all under `compute/nodes/<node>/`, written with the lead's credentials unless noted)

| object | written by | content |
|---|---|---|
| `record.json` | lead | name, created/expiry, revoked, strikes, accepted / verified chunk counts |
| `invite.json` | lead | presigned PUT hello + heartbeat, GET inbox; deleted on revoke (the token stops resolving) |
| `hello.json` | node (presigned PUT) | capabilities + limits + node version |
| `heartbeat.json` | node (presigned PUT) | state, current attempt, hours used, last finished attempt |
| `inbox.json` | lead | `{state: idle|work|revoked, assignment: {attempt, chunk, manifestUrl}, renew: {…}}` |

Frames of a member's chunk are PUT to an **attempt-scoped prefix** (`compute/runs/<run>/pods/<attempt>/plates/…`),
never straight into the run's plates.

## Trust: checksums and spot checks

Results from untrusted nodes are accepted atom by atom only if:

1. every frame of the atom exists, is a complete PNG (IHDR … IEND) of the requested resolution, and its sha256
   equals the sha256 the node reported in its job manifest (catches truncated/corrupt uploads and mismatched
   reports) — then the broker copies the frames into the run's plates;
2. a deterministic ~2 % of a node's accepted atoms (`spot_check_fraction` in `broker.yaml`; selection =
   `sha256(attempt + atom) mod 10000 < 200`, so anyone can recompute which were checked) **plus the node's first
   accepted atom (probation)** are re-rendered on a trusted provider (Lambda / local / pod) and compared with a
   noise-robust metric (PSNR after a 4x box downsample, threshold 28 dB — Monte-Carlo noise passes, a wrong
   picture does not).

Consequences: a rejected result strikes the node (2 strikes: no more work for it; 3: revoked). A failed spot check
revokes the node immediately and **re-opens every atom it delivered in that run**, so trusted providers render
them again and the run only completes with trusted (or verified) frames.

## Tested

`tests/compute/test_members.py` (moto S3, fake network = presigned URL -> S3 key, fake `nvidia-smi`): token
round-trip and no credentials in the invite; hello registers GPU/VRAM + limits; an honest node renders and passes
its probation spot check; a bad-checksum node is rejected and its frames re-rendered elsewhere; a node with right
checksums but wrong pictures fails the spot check, is revoked and its work re-opened (final plates = trusted
renders); revocation at any time (node sees `revoked`, invite gone, no more work); member limits (max hours, GPU
busy -> paused, no GPU + `--no-cpu`); ~2 % deterministic selection. No live member node has been run.
