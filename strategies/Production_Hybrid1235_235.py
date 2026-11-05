"""Both 1=23=5 and 2=3=5 entry paths. Same bar rules and live deny as the monitor."""

from hybrid_base import HybridCtaBase


class Production_Hybrid1235_235(HybridCtaBase):
    author = "Architect"
    enable_235 = True
    enable_1235 = True
    log_heartbeat = False


# Historical import name used by the local load check.
Production_Hybrid_235 = Production_Hybrid1235_235
