# GPU verification renders (use instead of slow local CPU renders)
The shared CPU box takes 6-15 min/frame at 540x960; the Runpod RTX 4090 farm takes ~40 s/frame at full quality. Agents MAY render their verification frames on the farm from their own worktree code:

  cd <your worktree>
  export LIBRARY_STORE=/home/user/story-animator/library_store RUNPOD_API_KEY=proxy-injected
  env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
    python3 cloud/farm/presigned.py submit --spec <episode.json> --run <yourname>-<n> --quality final --res 540x960 \
      --provider runpod --gpu RTX4090 --workers 1 --budget 0.6 --frames <A-B> --code worktree --stack story-farm
  env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
    python3 cloud/farm/presigned.py watch --run <yourname>-<n> --stack story-farm --interval 30 --dest /tmp/<yourname>/gpu_plates

Rules: ONE pod at a time per agent; frames for a single shot per run (a run renders a contiguous frame range; pick keyframes by running several small runs sequentially or a short range); budget <= $0.60 per run and <= $3 total per agent; always let `watch` terminate the pod (or run `presigned.py stop --run ...` if you abort). Pods take ~3-5 min to boot; batch your frames. Read the pulled PNGs.
