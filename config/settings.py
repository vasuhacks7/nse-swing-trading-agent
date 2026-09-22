import os
import yaml
import copy
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

_BASE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _BASE_DIR / "config" / "default_config.yaml"


class Settings:
    def __init__(self, config_path: str | None = None):
        with open(config_path or _DEFAULT_CONFIG) as f:
            self._cfg = yaml.safe_load(f)

        self.aws_region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", ""))
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.alpha_vantage_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self.alpaca_api_key = os.getenv("ALPACA_API_KEY", "")
        self.alpaca_secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        self.alpaca_paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"

        self.db_path = _BASE_DIR / "db" / "trading.db"
        self.log_dir = _BASE_DIR / "logs"
        self.log_dir.mkdir(exist_ok=True)

    @property
    def market(self) -> dict:
        return self._cfg["market"]

    @property
    def strategies(self) -> dict:
        return self._cfg["strategies"]

    @property
    def alerts(self) -> dict:
        return self._cfg["alerts"]

    @property
    def scoring(self) -> dict:
        return self._cfg["scoring"]

    @property
    def risk(self) -> dict:
        return self._cfg["risk"]

    @property
    def improvement(self) -> dict:
        return self._cfg["improvement"]

    @property
    def reflection(self) -> dict:
        return self._cfg["reflection"]

    def get_enabled_strategies(self) -> list[str]:
        return [name for name, cfg in self.strategies.items() if cfg.get("enabled", True)]

    def get_strategy_config(self, name: str) -> dict:
        return copy.deepcopy(self._cfg["strategies"].get(name, {}))

    def update_strategy_weight(self, name: str, weight: float):
        if name in self._cfg["strategies"]:
            self._cfg["strategies"][name]["weight"] = weight

    def save(self, path: str):
        with open(path, "w") as f:
            yaml.dump(self._cfg, f, default_flow_style=False)
