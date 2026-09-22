import logging

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, risk_config: dict):
        self.max_position_pct = risk_config.get("max_position_pct", 0.10)
        self.max_portfolio_risk_pct = risk_config.get("max_portfolio_risk_pct", 0.02)
        self.stop_loss_atr_mult = risk_config.get("stop_loss_atr_multiplier", 2.0)
        self.take_profit_atr_mult = risk_config.get("take_profit_atr_multiplier", 3.0)
        self.max_drawdown_pct = risk_config.get("max_drawdown_pct", 0.15)
        self.max_open_positions = risk_config.get("max_open_positions", 5)
        self.max_sector_exposure_pct = risk_config.get("max_sector_exposure_pct", 0.30)
        self.peak_equity = 0.0

    def calculate_position_size(self, portfolio_value: float, entry_price: float,
                                atr: float, signal_strength: float = 1.0) -> dict:
        max_dollars = portfolio_value * self.max_position_pct
        risk_per_share = atr * self.stop_loss_atr_mult
        if risk_per_share <= 0:
            risk_per_share = entry_price * 0.02

        max_risk_dollars = portfolio_value * self.max_portfolio_risk_pct
        risk_based_shares = max_risk_dollars / risk_per_share
        pct_based_shares = max_dollars / entry_price

        shares = min(risk_based_shares, pct_based_shares)
        shares = max(1, int(shares * min(abs(signal_strength), 1.0)))

        stop_loss = entry_price - risk_per_share
        take_profit = entry_price + atr * self.take_profit_atr_mult

        return {
            "shares": shares,
            "position_value": shares * entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_per_share": risk_per_share,
            "total_risk": shares * risk_per_share,
        }

    def check_can_open_position(self, current_positions: list[dict],
                                portfolio_value: float) -> dict:
        if len(current_positions) >= self.max_open_positions:
            return {"allowed": False, "reason": f"Max positions reached ({self.max_open_positions})"}

        total_exposure = sum(p.get("market_value", 0) for p in current_positions)
        exposure_pct = total_exposure / portfolio_value if portfolio_value else 1
        if exposure_pct > 0.9:
            return {"allowed": False, "reason": f"Portfolio exposure too high ({exposure_pct:.1%})"}

        return {"allowed": True, "reason": "OK"}

    def check_drawdown(self, current_equity: float) -> dict:
        self.peak_equity = max(self.peak_equity, current_equity)
        if self.peak_equity == 0:
            return {"within_limits": True, "drawdown": 0}

        drawdown = (self.peak_equity - current_equity) / self.peak_equity
        within = drawdown < self.max_drawdown_pct

        if not within:
            logger.warning(f"DRAWDOWN LIMIT BREACHED: {drawdown:.2%} >= {self.max_drawdown_pct:.2%}")

        return {
            "within_limits": within,
            "drawdown": drawdown,
            "peak_equity": self.peak_equity,
            "limit": self.max_drawdown_pct,
        }

    def check_stop_loss(self, entry_price: float, current_price: float,
                        atr: float) -> bool:
        stop = entry_price - atr * self.stop_loss_atr_mult
        return current_price <= stop

    def check_take_profit(self, entry_price: float, current_price: float,
                          atr: float) -> bool:
        target = entry_price + atr * self.take_profit_atr_mult
        return current_price >= target
