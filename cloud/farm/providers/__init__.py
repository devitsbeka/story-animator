"""Compute providers for the render farm: one interface (providers.base.Provider), several back ends.

    aws_ec2  the CloudFormation spot/on-demand ASGs (needs the G/VT quota)
    runpod   RunPod GPU pods (RUNPOD_API_KEY)
    vastai   Vast.ai marketplace instances (VAST_API_KEY)
    local    worker processes on this machine (CPU, last resort)

scheduler.py chooses between them; see docs/farm.md "Providers and fallback".
"""
from .base import (FAILED, PENDING, RUNNING, STOPPED, TERMINATED, AuthError, CapacityError, Provider,  # noqa: F401
                   ProviderError, QuotaError, WorkerHandle)


def make(name, cfg=None, env=None, **kw):
    if name == "aws_ec2":
        from .aws_ec2 import AwsEc2
        return AwsEc2(cfg, env, **kw)
    if name == "runpod":
        from .runpod import RunPod
        return RunPod(cfg, env, **kw)
    if name == "vastai":
        from .vastai import VastAI
        return VastAI(cfg, env, **kw)
    if name == "local":
        from .local import Local
        return Local(cfg, env, **kw)
    raise ValueError(f"unknown provider {name!r}")


NAMES = ("aws_ec2", "runpod", "vastai", "local")
__all__ = ["FAILED", "PENDING", "RUNNING", "STOPPED", "TERMINATED", "AuthError", "CapacityError", "Provider",
           "ProviderError", "QuotaError", "WorkerHandle", "make", "NAMES"]
