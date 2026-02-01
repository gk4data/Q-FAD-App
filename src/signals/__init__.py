from .generator import add_long_signal
from .buy_signals import generate_buy_signals
from .sell_signals import generate_sell_signals
from .regime_detection import detect_regimes_relaxed
from .angle_classification import classify_trend_by_angles

__all__ = [
    "add_long_signal",
    "generate_buy_signals",
    "generate_sell_signals",
    "detect_regimes_relaxed",
    "classify_trend_by_angles",
]
