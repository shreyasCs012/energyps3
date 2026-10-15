"""Small policy output types shared by the first policy implementations."""

from dataclasses import dataclass, field

from contracts.models import ControlCommand


@dataclass
class PolicyAlert:
    timestamp: object
    rule: str
    message: str
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass
class PolicyDecision:
    commands: list[ControlCommand] = field(default_factory=list)
    alerts: list[PolicyAlert] = field(default_factory=list)
