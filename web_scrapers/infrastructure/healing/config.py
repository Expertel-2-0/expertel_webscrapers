import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_csv(name: str) -> set:
    raw = os.getenv(name, "").strip()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


@dataclass(frozen=True)
class HealingConfig:
    """All healing behavior is driven by environment variables so the feature
    can be enabled per environment (and per carrier) without a deploy.

    With HEALING_ENABLED unset/false the scraper system is byte-for-byte
    unchanged: the plain PlaywrightWrapper is used and no healing code runs.
    """

    enabled: bool = field(default_factory=lambda: _env_bool("HEALING_ENABLED", False))
    # Empty set = all carriers (when enabled). Otherwise csv allowlist, e.g. "bell,telus".
    carriers: set = field(default_factory=lambda: _env_csv("HEALING_CARRIERS"))
    model: str = field(default_factory=lambda: os.getenv("HEALING_MODEL", "claude-sonnet-5"))
    max_heals_per_job: int = field(default_factory=lambda: int(os.getenv("HEALING_MAX_HEALS_PER_JOB", "3")))
    # Hard wall-clock cap for one heal attempt (evidence + API + retry). Some
    # carrier sessions are time-sensitive (Bell 45-min queue, T-Mobile ~16-min
    # jobs) - beyond this we fail with evidence instead of blowing the session.
    step_budget_seconds: int = field(default_factory=lambda: int(os.getenv("HEALING_STEP_BUDGET_SECONDS", "120")))
    # Global daily cap on Claude calls (cost guardrail). ~5-15k input tokens per
    # call on Sonnet => the default cap bounds worst-case spend to ~$1-2/day.
    daily_max_calls: int = field(default_factory=lambda: int(os.getenv("HEALING_DAILY_MAX_CALLS", "25")))
    include_screenshot: bool = field(default_factory=lambda: _env_bool("HEALING_SCREENSHOTS", True))
    overrides_path: str = field(
        default_factory=lambda: os.getenv("HEALING_OVERRIDES_PATH", os.path.abspath("healing_overrides.json"))
    )
    dom_max_chars: int = field(default_factory=lambda: int(os.getenv("HEALING_DOM_MAX_CHARS", "60000")))

    def carrier_enabled(self, carrier: str) -> bool:
        if not self.enabled:
            return False
        return not self.carriers or (carrier or "").lower() in self.carriers


def load_config() -> HealingConfig:
    return HealingConfig()
