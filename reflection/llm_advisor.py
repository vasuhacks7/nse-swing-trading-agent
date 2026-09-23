import json
import logging
import os

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a quantitative trading analyst reviewing an Indian stock market swing trading system. The system runs 5 strategies that generate daily stock alerts on NSE-listed stocks. Your job is to:

1. Identify which strategies are performing well and why
2. Identify which strategies are underperforming and what patterns lead to losses
3. Suggest specific, actionable adjustments to strategy weights
4. Spot any market regime changes that require adaptation
5. Flag any stocks that should be added/removed from the watchlist

You must respond with valid JSON only:
{
    "market_regime": "description of current Indian market conditions",
    "winning_patterns": ["pattern 1", "pattern 2"],
    "losing_patterns": ["pattern 1", "pattern 2"],
    "strategy_analysis": {
        "strategy_name": {
            "assessment": "strong/moderate/weak",
            "reasoning": "why"
        }
    },
    "weight_suggestions": [
        {
            "strategy": "strategy_name",
            "current_weight": 1.0,
            "suggested_weight": 1.5,
            "reasoning": "why"
        }
    ],
    "parameter_adjustments": [
        {
            "strategy": "strategy_name",
            "parameter": "param_name",
            "current_value": 0,
            "suggested_value": 0,
            "reasoning": "why"
        }
    ],
    "watchlist_changes": {
        "add": ["SYMBOL.NS"],
        "remove": ["SYMBOL.NS"],
        "reasoning": "why"
    },
    "key_insights": ["insight 1", "insight 2"],
    "risk_warnings": ["warning 1"],
    "confidence": 0.7
}"""

def _resolve_bedrock_model(model: str) -> str:
    """Convert any Claude model name to Bedrock format (anthropic.xxx)."""
    if model.startswith("anthropic."):
        return model
    return f"anthropic.{model}"


def _create_client():
    """Create the best available Anthropic client (Bedrock > direct API)."""
    aws_region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", ""))

    if aws_region:
        try:
            from anthropic import AnthropicBedrock
            return AnthropicBedrock(aws_region=aws_region), "bedrock"
        except ImportError:
            logger.warning("anthropic[bedrock] not installed, trying direct API")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        import anthropic
        return anthropic.Anthropic(api_key=api_key), "direct"

    return None, None


class LLMAdvisor:
    def __init__(self, model: str = "claude-sonnet-5"):
        self.client, self.backend = _create_client()
        if self.backend == "bedrock":
            self.model = _resolve_bedrock_model(model)
        else:
            self.model = model

        if self.client:
            logger.info(f"LLM advisor ready (backend={self.backend}, model={self.model})")
        else:
            logger.warning("No LLM backend configured (set AWS_REGION or ANTHROPIC_API_KEY)")

    def validate_pick(self, pick_data: dict) -> dict:
        if not self.client:
            return {"verdict": pick_data.get("signal", "BUY"), "confidence": 0.5, "reasoning": "LLM not configured", "skip": False}

        prompt = f"""You are a senior swing trader reviewing an NSE stock pick. Analyze this candidate and decide if it's worth trading.

## Stock: {pick_data.get('symbol', '?')}
- Current Price: Rs.{pick_data.get('current_price', 0):.2f}
- Entry: Rs.{pick_data.get('entry', 0):.2f} | Target: Rs.{pick_data.get('target', 0):.2f} | Stop Loss: Rs.{pick_data.get('stop_loss', 0):.2f}
- Signal: {pick_data.get('signal', '?')}

## Technical Analysis
- RSI: {pick_data.get('rsi', '?')} | MACD Hist: {pick_data.get('macd_hist', '?')} | ADX: {pick_data.get('adx', '?')}
- Bollinger %B: {pick_data.get('bb_pct', '?')} | Volume Ratio: {pick_data.get('volume_ratio', '?')}
- EMA 20: {pick_data.get('ema_20', '?')} | EMA 50: {pick_data.get('ema_50', '?')} | EMA 200: {pick_data.get('ema_200', '?')}

## Confluence Analysis
- Confluence Score: {pick_data.get('confluence_score', '?')}/{pick_data.get('max_confluence', 12)}
- Factors: {pick_data.get('factors', '?')}
- Weekly Trend: {pick_data.get('weekly_trend', '?')} | Relative Strength: {pick_data.get('rs_trend', '?')}

## Strategy Signals
{pick_data.get('strategy_signals', 'None')}

## Fundamentals
{pick_data.get('fundamentals', 'Not available')}

## Market Context
- Regime: {pick_data.get('market_regime', '?')} | FII Sentiment: {pick_data.get('fii_sentiment', '?')}
- Sector: {pick_data.get('sector', '?')} | Sector Strength: {pick_data.get('sector_strength', '?')}

Respond with JSON only:
{{
    "verdict": "STRONG_BUY" or "BUY" or "SKIP",
    "confidence": 0.0 to 1.0,
    "reasoning": "2-3 sentence explanation",
    "risk_flags": ["any red flags"],
    "adjusted_target": null or price if you think target should change,
    "adjusted_stop": null or price if you think stop should change
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(text)
            result.setdefault("verdict", "BUY")
            result.setdefault("confidence", 0.5)
            result.setdefault("reasoning", "")
            result.setdefault("risk_flags", [])
            return result
        except Exception as e:
            logger.error(f"LLM pick validation failed for {pick_data.get('symbol', '?')}: {e}")
            return {"verdict": pick_data.get("signal", "BUY"), "confidence": 0.5, "reasoning": f"LLM error: {e}", "risk_flags": [], "skip": False}

    def analyze_performance(self, performance_text: str, strategy_scores: dict) -> dict:
        if not self.client:
            return {"error": "LLM not configured"}

        user_prompt = f"""Analyze this Indian stock market swing trading system's performance and suggest improvements.

{performance_text}

## Current Strategy Configuration
```json
{json.dumps(strategy_scores, indent=2, default=str)}
```

Focus on:
1. Which strategies are genuinely working and should get more weight?
2. Which are consistently losing and should be demoted or have parameters adjusted?
3. Are there patterns in the winners — sector, market cap, technical setup?
4. Are losses mainly from stop-loss hits (volatility issue) or max-hold exits (entry timing issue)?
5. Any signs of regime change in the Indian market?
6. Should any strategy parameters be tightened or loosened?

Be specific and data-driven. This system self-improves, so your recommendations will be automatically applied with confidence-based blending.

Respond with JSON only."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2500,
                messages=[{"role": "user", "content": user_prompt}],
                system=SYSTEM_PROMPT,
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return {"error": "JSON parse failed", "raw": text[:500]}
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return {"error": str(e)}
