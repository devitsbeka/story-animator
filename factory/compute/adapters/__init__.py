"""Compute adapters (see base.py for the contract). make(pid, cfg) picks the implementation by cfg['adapter']."""
from .base import Adapter, AuthError, CapacityError, ProviderError, QuotaError, StubAdapter  # noqa: F401


def make(pid, cfg, session=None, members=None, clock=None):
    kind = cfg.get("adapter", pid)
    if kind == "aws_lambda":
        from .aws_lambda import AwsLambda
        return AwsLambda(pid, cfg, session=session, clock=clock)
    if kind == "local_cpu":
        from .local_cpu import LocalCpu
        return LocalCpu(pid, cfg, clock=clock)
    if kind == "presigned_pod":
        from .presigned_pod import PresignedPod
        return PresignedPod(pid, cfg, clock=clock)
    if kind == "member_node":
        from ..members import MemberNodes
        return MemberNodes(pid, cfg, members, clock=clock)
    from .stubs import STUBS
    if kind in STUBS:
        return STUBS[kind](pid, cfg, clock=clock)
    raise ValueError(f"unknown adapter {kind!r} for provider {pid!r}")
