from emg_collector.multimodal.schema import Attempt


class RepetitionDetector:
    def __init__(self, protocol, set_id="SET1"):
        self.p = protocol
        self.set_id = set_id
        self.phase = "ready"
        self.attempts = []
        self.last_ns = None
        self.start_ns = None
        self.phases = {}
        self.angles = []
        self.unknown = False
        self.reasons = set()
        self.violation_since = {}
        self.candidate = None
        self.armed = False

    def update(self, ns, angle, trunk, upperarm, valid):
        if self.last_ns is not None and ns <= self.last_ns:
            raise ValueError("pose timestamps must increase")
        if (
            self.last_ns is not None
            and ns - self.last_ns > self.p.max_pose_gap_ns
            and self.start_ns is not None
        ):
            self.unknown = True
        self.last_ns = ns
        if not valid or angle is None:
            if self.start_ns is not None:
                self.unknown = True
            return None
        target = None
        if self.phase == "ready" and angle >= self.p.start_angle_deg:
            self.armed = True
        if (
            self.phase == "ready"
            and self.armed
            and angle < self.p.start_angle_deg - self.p.hysteresis_deg
        ):
            target = "concentric"
        elif self.phase == "concentric" and angle <= self.p.top_angle_deg:
            target = "top"
        elif self.phase == "concentric" and angle >= self.p.start_angle_deg:
            target = "return_before_top"
        elif (
            self.phase == "top" and angle > self.p.top_angle_deg + self.p.hysteresis_deg
        ):
            target = "eccentric"
        elif self.phase == "eccentric" and angle >= self.p.start_angle_deg:
            target = "completed"
        if target:
            if self.candidate is None or self.candidate[0] != target:
                self.candidate = (target, ns)
            if ns - self.candidate[1] >= self.p.debounce_ns:
                if target == "return_before_top":
                    self.reasons.add("return_before_top")
                    return self.finish(ns)
                if target == "concentric":
                    self.start_ns = self.candidate[1]
                    self.angles = [self.p.start_angle_deg]
                self.phase = target
                self.phases[target] = self.candidate[1]
                self.candidate = None
        else:
            self.candidate = None
        if self.start_ns is not None:
            self.angles.append(angle)
            for name, value, limit in [
                ("trunk", trunk, self.p.max_trunk_tilt_deg),
                ("upperarm", upperarm, self.p.max_upperarm_delta_deg),
            ]:
                if value is None:
                    self.unknown = True
                elif abs(value) > limit:
                    self.violation_since.setdefault(name, ns)
                    if (
                        ns - self.violation_since[name]
                        >= self.p.violation_duration_s * 1e9
                    ):
                        self.reasons.add(name)
                else:
                    self.violation_since.pop(name, None)
            if self.phase == "completed":
                return self.finish(ns, completed=True)
            phase_start = max(self.phases.values(), default=self.start_ns)
            if ns - phase_start > self.p.phase_timeout_s * 1e9:
                self.reasons.add("phase_timeout")
                return self.finish(ns)
        return None

    def finish(self, ns, completed=False):
        # A pending first transition is still an incomplete attempt.
        if self.start_ns is None and self.candidate:
            self.start_ns = self.candidate[1]
            self.unknown = True
        if self.start_ns is None:
            return None
        duration = (ns - self.start_ns) / 1e9
        rom = max(self.angles) - min(self.angles) if self.angles else None
        if not completed:
            self.reasons.add("partial_attempt")
        if rom is None or rom < self.p.min_rom_deg:
            self.reasons.add("rom")
        if not self.p.min_duration_s <= duration <= self.p.max_duration_s:
            self.reasons.add("tempo")
        attempt = Attempt(
            attempt_id=f"{self.set_id}-A{len(self.attempts)+1}",
            set_id=self.set_id,
            start_ns=self.start_ns,
            end_ns=ns,
            validity=(
                "unknown" if self.unknown else ("invalid" if self.reasons else "valid")
            ),
            reasons=sorted(
                self.reasons | ({"tracking_loss"} if self.unknown else set())
            ),
            phases=self.phases.copy(),
            rom_deg=rom,
        )
        self.attempts.append(attempt)
        self.phase = "ready"
        self.start_ns = None
        self.phases = {}
        self.angles = []
        self.unknown = False
        self.reasons = set()
        self.violation_since = {}
        self.candidate = None
        self.armed = False
        return attempt
