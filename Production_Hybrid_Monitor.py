"""Same class as strategies/Production_Hybrid_Monitor.py. That folder is the source."""

import sys
from pathlib import Path

_STRATEGIES = Path(__file__).resolve().parent / "strategies"
if str(_STRATEGIES) not in sys.path:
    sys.path.insert(0, str(_STRATEGIES))

from Production_Hybrid_Monitor import Production_Hybrid_Monitor  # noqa: E402,F401
