"""P0 fixed-schedule baseline: observe the schedule and emit no controls."""

from policies.models import PolicyDecision


def evaluate() -> PolicyDecision:
    return PolicyDecision()
