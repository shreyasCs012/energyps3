"""Plant-side legal state transitions and minimum dwell enforcement."""

from dataclasses import dataclass

from contracts.models import EquipmentState

LEGAL_TRANSITIONS: dict[EquipmentState, frozenset[EquipmentState]] = {
    EquipmentState.OFF: frozenset(
        {EquipmentState.STANDBY, EquipmentState.MAINTENANCE, EquipmentState.FAULT}
    ),
    EquipmentState.STANDBY: frozenset(
        {
            EquipmentState.OFF,
            EquipmentState.WARMUP,
            EquipmentState.MAINTENANCE,
            EquipmentState.FAULT,
        }
    ),
    EquipmentState.WARMUP: frozenset(
        {EquipmentState.RUNNING, EquipmentState.IDLE, EquipmentState.STANDBY, EquipmentState.FAULT}
    ),
    EquipmentState.IDLE: frozenset(
        {
            EquipmentState.RUNNING,
            EquipmentState.STANDBY,
            EquipmentState.MAINTENANCE,
            EquipmentState.FAULT,
        }
    ),
    EquipmentState.RUNNING: frozenset({EquipmentState.IDLE, EquipmentState.FAULT}),
    EquipmentState.MAINTENANCE: frozenset({EquipmentState.OFF, EquipmentState.STANDBY}),
    EquipmentState.FAULT: frozenset({EquipmentState.MAINTENANCE, EquipmentState.OFF}),
}


def is_legal_transition(previous: EquipmentState, current: EquipmentState) -> bool:
    """Return whether the state edge is allowed by the plant state machine."""
    return previous == current or current in LEGAL_TRANSITIONS[previous]


@dataclass
class MachineState:
    """One machine's state and dwell timers; one call to ``advance`` is one minute."""

    state: EquipmentState = EquipmentState.OFF
    state_minutes: int = 1_000_000
    powered_minutes: int = 0
    warmup_minutes: int = 0

    def advance(
        self,
        target: EquipmentState,
        *,
        min_on_min: int,
        min_off_min: int,
        warmup_min: int,
    ) -> EquipmentState:
        """Move at most one legal edge toward target, respecting dwell/warmup rules."""
        old_state = self.state
        next_state = old_state

        if old_state in {EquipmentState.OFF, EquipmentState.STANDBY}:
            if target in {EquipmentState.RUNNING, EquipmentState.IDLE, EquipmentState.WARMUP}:
                if old_state == EquipmentState.OFF and self.state_minutes >= min_off_min:
                    next_state = EquipmentState.STANDBY
                elif old_state == EquipmentState.STANDBY:
                    next_state = EquipmentState.WARMUP
            elif old_state == EquipmentState.STANDBY and target == EquipmentState.OFF:
                if self.state_minutes >= min_off_min:
                    next_state = EquipmentState.OFF
        elif old_state == EquipmentState.WARMUP:
            self.warmup_minutes += 1
            if self.warmup_minutes >= warmup_min:
                next_state = (
                    EquipmentState.RUNNING
                    if target == EquipmentState.RUNNING
                    else EquipmentState.IDLE
                )
            elif (
                target in {EquipmentState.OFF, EquipmentState.STANDBY}
                and self.powered_minutes >= min_on_min
            ):
                next_state = EquipmentState.STANDBY
        elif old_state == EquipmentState.RUNNING:
            if (
                target in {EquipmentState.IDLE, EquipmentState.OFF, EquipmentState.STANDBY}
                and self.powered_minutes >= min_on_min
            ):
                next_state = EquipmentState.IDLE
        elif old_state == EquipmentState.IDLE:
            if target == EquipmentState.RUNNING:
                next_state = EquipmentState.RUNNING
            elif (
                target in {EquipmentState.OFF, EquipmentState.STANDBY}
                and self.powered_minutes >= min_on_min
            ):
                next_state = EquipmentState.STANDBY

        if not is_legal_transition(old_state, next_state):
            raise RuntimeError(f"Illegal plant state transition: {old_state} -> {next_state}")

        if next_state != old_state:
            self.state = next_state
            self.state_minutes = 0
            if next_state == EquipmentState.WARMUP:
                self.warmup_minutes = 0
                self.powered_minutes = 0
        else:
            self.state_minutes += 1

        if self.state in {EquipmentState.STANDBY, EquipmentState.OFF}:
            if self.state == EquipmentState.OFF:
                self.powered_minutes = 0
        else:
            self.powered_minutes += 1

        return self.state
