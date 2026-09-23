import logging
from strategy.base import BaseStrategy, StockPick
from strategy.momentum_breakout import MomentumBreakout
from strategy.mean_reversion import MeanReversion
from strategy.macd_rsi_confluence import MACDRSIConfluence
from strategy.fundamental_value import FundamentalValue
from strategy.trend_following import TrendFollowing
from strategy.volatility_contraction import VolatilityContraction
from strategy.fifty_two_week_high import FiftyTwoWeekHigh
from strategy.relative_strength import RelativeStrength
from strategy.inside_bar_breakout import InsideBarBreakout
from strategy.gap_and_go import GapAndGo
from strategy.bollinger_squeeze import BollingerSqueeze
from strategy.vwap_bounce import VWAPBounce

logger = logging.getLogger(__name__)

STRATEGY_CLASSES: dict[str, type[BaseStrategy]] = {
    "momentum_breakout": MomentumBreakout,
    "mean_reversion": MeanReversion,
    "macd_rsi_confluence": MACDRSIConfluence,
    "fundamental_value": FundamentalValue,
    "trend_following": TrendFollowing,
    "volatility_contraction": VolatilityContraction,
    "52_week_high": FiftyTwoWeekHigh,
    "relative_strength": RelativeStrength,
    "inside_bar_breakout": InsideBarBreakout,
    "gap_and_go": GapAndGo,
    "bollinger_squeeze": BollingerSqueeze,
    "vwap_bounce": VWAPBounce,
}


class StrategyManager:
    def __init__(self, strategy_configs: dict, weights: dict[str, float] | None = None):
        self.strategies: dict[str, BaseStrategy] = {}
        self.weights = weights or {}

        for name, config in strategy_configs.items():
            if not config.get("enabled", True):
                continue
            cls = STRATEGY_CLASSES.get(name)
            if cls:
                self.strategies[name] = cls(config)
                if name not in self.weights:
                    self.weights[name] = config.get("weight", 1.0)

    def scan_stock(self, df, fundamentals: dict) -> list[StockPick]:
        picks = []
        for name, strategy in self.strategies.items():
            try:
                pick = strategy.scan(df, fundamentals)
                if pick:
                    weight = self.weights.get(name, 1.0)
                    pick.score *= weight
                    picks.append(pick)
            except Exception as e:
                logger.debug(f"Strategy {name} failed on {df.get('symbol', ['?']).iloc[-1] if 'symbol' in df.columns else '?'}: {e}")
        return picks

    def scan_universe(self, universe_data: dict) -> list[StockPick]:
        all_picks = []
        for symbol, data in universe_data.items():
            ohlcv = data["ohlcv"]
            fund = data.get("fundamentals", {})
            picks = self.scan_stock(ohlcv, fund)
            all_picks.extend(picks)

        all_picks.sort(key=lambda p: p.score, reverse=True)
        return all_picks

    def get_top_picks(self, universe_data: dict, max_picks: int = 2,
                      min_score: float = 0.4) -> list[StockPick]:
        all_picks = self.scan_universe(universe_data)

        filtered = [p for p in all_picks if p.score >= min_score]

        seen_symbols = set()
        unique_picks = []
        for pick in filtered:
            if pick.symbol not in seen_symbols:
                seen_symbols.add(pick.symbol)
                unique_picks.append(pick)
            if len(unique_picks) >= max_picks:
                break

        return unique_picks

    def update_weights(self, new_weights: dict[str, float]):
        self.weights.update(new_weights)
