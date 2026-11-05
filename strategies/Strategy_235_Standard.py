"""2=3=5 only. Entry state is exposed as entry_stage for the old variable name."""

from hybrid_base import HybridCtaBase


class Strategy_235_Standard(HybridCtaBase):
    author = "Architect"
    enable_235 = True
    enable_1235 = False
    log_heartbeat = False
    variables = HybridCtaBase.variables + ["entry_stage"]

    @property
    def entry_stage(self) -> int:
        return self.stage_235

    @entry_stage.setter
    def entry_stage(self, value: int) -> None:
        self.stage_235 = value
