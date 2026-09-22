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

# Bedrock model ID mapping
BEDROCK_MODELS = {
    "claude-sonnet-5": "anthropic.claude-sonnet-5",
    "claude-opus-5": "anthropic.claude-opus-5",
    "claude-haiku-4-5": "anthropic.claude-haiku-4-5",
    "claude-sonnet-4-20250514": "anthropic.claude-sonnet-4-20250514-v1:0",
}


def _resolve_bedrock_model(model: str) -> str:
    if model.startswith("anthropic."):
        return model
    return BEDROCK_MODELS.get(model, f"anthropic.{model}")


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
