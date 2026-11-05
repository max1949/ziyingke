"""Production hybrid monitor. Live orders stay denied unless allow_live_trading is set true."""

from hybrid_base import HybridCtaBase


class Production_Hybrid_Monitor(HybridCtaBase):
    """Combined 2=3=5 and 1=23=5 monitor. Live orders stay denied.

    A copper-only search preferred signed exits at 1.0 / 2.5 ATR. That
    candidate lost on SR, so these class thresholds stay at the original
    1.5 / 3.5 absolute exit. See output/quality_observation_report.json.
    """

    author = "Architect"
    enable_235 = True
    enable_1235 = True
    log_heartbeat = True
