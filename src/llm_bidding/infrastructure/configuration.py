"""Configuration loading and validation for the bidding system."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from ..domain.models import AgentProfile
from ..domain.policy import SELECTION_MODES, PolicyParams


class ConfigError(ValueError):
    """Raised when a bidding config file is invalid."""


DEFAULT_AGENTS: tuple[dict[str, object], ...] = (
    {
        "name": "claude-opus",
        "provider": "anthropic",
        "model_id": "claude-opus-4-8",
        "input_cost_per_mtok": 5.0,
        "output_cost_per_mtok": 25.0,
    },
    {
        "name": "claude-sonnet",
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "input_cost_per_mtok": 3.0,
        "output_cost_per_mtok": 15.0,
    },
    {
        "name": "gpt",
        "provider": "openai",
        "model_id": "gpt-5.2",
        "input_cost_per_mtok": 1.25,
        "output_cost_per_mtok": 10.0,
    },
)

DEFAULT_UTILITY: dict[str, object] = {
    "weights": {"quality": 0.5, "price": 0.2, "risk_fit": 0.3},
    "quality_mix": {"confidence": 0.6, "history": 0.4},
    "cost_ceiling_usd": 2.0,
}

DEFAULT_CALIBRATION: dict[str, object] = {
    "neutral_prior": 0.5,
    "prior_strength": 4.0,
    "max_calibration_shift": 0.2,
    "min_calibration_samples": 3,
    "min_band_samples": 3,
    "cost_ratio_prior_strength": 4.0,
    "cost_ratio_min": 0.25,
    "cost_ratio_max": 4.0,
}

DEFAULT_POLICY: dict[str, object] = {
    "min_award_utility": 0.0,
    "selection_mode": "utility",
    "adequacy_min_quality": 0.0,
    "high_risk_floor": {
        "min_band_success_rate": None,
        "min_calibrated_confidence": None,
    },
}

DEFAULT_PROVIDERS: dict[str, object] = {
    "timeout_seconds": 60.0,
    "retries": 1,
    "retry_backoff_seconds": 2.0,
}

DEFAULT_FAST_PATH: dict[str, object] = {
    "skip_bids_for_low_risk": False,
    "default_input_tokens": 2000,
    "default_output_tokens": 800,
}

DEFAULT_HISTORY_DB = "~/.llm-bidding/history.db"

_WEIGHT_EPSILON = 1e-6


@dataclass(frozen=True)
class UtilityWeights:
    quality: float
    price: float
    risk_fit: float

    def to_dict(self) -> dict[str, float]:
        return {"quality": self.quality, "price": self.price, "risk_fit": self.risk_fit}


@dataclass(frozen=True)
class CalibrationParams:
    neutral_prior: float
    prior_strength: float
    max_calibration_shift: float
    min_calibration_samples: int
    min_band_samples: int
    cost_ratio_prior_strength: float = 4.0
    cost_ratio_min: float = 0.25
    cost_ratio_max: float = 4.0


@dataclass(frozen=True)
class ProviderParams:
    timeout_seconds: float
    retries: int
    retry_backoff_seconds: float


@dataclass(frozen=True)
class FastPathParams:
    skip_bids_for_low_risk: bool
    default_input_tokens: int
    default_output_tokens: int


@dataclass(frozen=True)
class BiddingConfig:
    agents: tuple[AgentProfile, ...]
    weights: UtilityWeights
    quality_mix_confidence: float
    quality_mix_history: float
    cost_ceiling_usd: float
    calibration: CalibrationParams
    policy: PolicyParams
    providers: ProviderParams
    fast_path: FastPathParams
    history_db: str
    autonomy_score_config: str | None

    def agent(self, name: str) -> AgentProfile:
        for profile in self.agents:
            if profile.name == name:
                return profile
        raise ConfigError(f"Unknown agent {name!r}. Configured agents: "
                          + ", ".join(p.name for p in self.agents))


def _require_unit_interval(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"{label} must be a number.")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ConfigError(f"{label} must be between 0 and 1.")
    return number


def _require_positive(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"{label} must be a number.")
    number = float(value)
    if number <= 0:
        raise ConfigError(f"{label} must be greater than 0.")
    return number


def _require_non_negative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{label} must be an integer >= 0.")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{label} must be an integer >= 1.")
    return value


def _require_non_negative(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"{label} must be a number.")
    number = float(value)
    if number < 0:
        raise ConfigError(f"{label} must be >= 0.")
    return number


def _optional_unit_interval(value: object, label: str) -> float | None:
    if value is None:
        return None
    return _require_unit_interval(value, label)


def _require_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{label} must be a boolean.")
    return value


def _build_config(raw: dict[str, object]) -> BiddingConfig:
    raw_agents = raw.get("agents", list(DEFAULT_AGENTS))
    if not isinstance(raw_agents, list) or not raw_agents:
        raise ConfigError("'agents' must be a non-empty list.")
    try:
        agents = tuple(AgentProfile.from_dict(item) for item in raw_agents)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    names = [profile.name for profile in agents]
    if len(names) != len(set(names)):
        raise ConfigError("Agent names must be unique.")

    utility = {**DEFAULT_UTILITY, **raw.get("utility", {})}
    raw_weights = {**DEFAULT_UTILITY["weights"], **utility.get("weights", {})}
    weights = UtilityWeights(
        quality=_require_unit_interval(raw_weights.get("quality"), "utility.weights.quality"),
        price=_require_unit_interval(raw_weights.get("price"), "utility.weights.price"),
        risk_fit=_require_unit_interval(raw_weights.get("risk_fit"), "utility.weights.risk_fit"),
    )
    total = weights.quality + weights.price + weights.risk_fit
    if abs(total - 1.0) > _WEIGHT_EPSILON:
        raise ConfigError(f"utility.weights must sum to 1.0 (got {total}).")

    raw_mix = {**DEFAULT_UTILITY["quality_mix"], **utility.get("quality_mix", {})}
    mix_confidence = _require_unit_interval(
        raw_mix.get("confidence"), "utility.quality_mix.confidence"
    )
    mix_history = _require_unit_interval(raw_mix.get("history"), "utility.quality_mix.history")
    if abs(mix_confidence + mix_history - 1.0) > _WEIGHT_EPSILON:
        raise ConfigError("utility.quality_mix values must sum to 1.0.")

    cost_ceiling = _require_positive(
        utility.get("cost_ceiling_usd"), "utility.cost_ceiling_usd"
    )

    raw_calibration = {**DEFAULT_CALIBRATION, **raw.get("calibration", {})}
    calibration = CalibrationParams(
        neutral_prior=_require_unit_interval(
            raw_calibration.get("neutral_prior"), "calibration.neutral_prior"
        ),
        prior_strength=_require_positive(
            raw_calibration.get("prior_strength"), "calibration.prior_strength"
        ),
        max_calibration_shift=_require_unit_interval(
            raw_calibration.get("max_calibration_shift"),
            "calibration.max_calibration_shift",
        ),
        min_calibration_samples=_require_non_negative_int(
            raw_calibration.get("min_calibration_samples"),
            "calibration.min_calibration_samples",
        ),
        min_band_samples=_require_non_negative_int(
            raw_calibration.get("min_band_samples"), "calibration.min_band_samples"
        ),
        cost_ratio_prior_strength=_require_positive(
            raw_calibration.get("cost_ratio_prior_strength"),
            "calibration.cost_ratio_prior_strength",
        ),
        cost_ratio_min=_require_positive(
            raw_calibration.get("cost_ratio_min"), "calibration.cost_ratio_min"
        ),
        cost_ratio_max=_require_positive(
            raw_calibration.get("cost_ratio_max"), "calibration.cost_ratio_max"
        ),
    )
    if calibration.cost_ratio_min > calibration.cost_ratio_max:
        raise ConfigError("calibration.cost_ratio_min must be <= cost_ratio_max.")

    raw_policy = {**DEFAULT_POLICY, **raw.get("policy", {})}
    raw_floor = {**DEFAULT_POLICY["high_risk_floor"], **raw_policy.get("high_risk_floor", {})}
    selection_mode = raw_policy.get("selection_mode")
    if selection_mode not in SELECTION_MODES:
        raise ConfigError(
            "policy.selection_mode must be one of: " + ", ".join(SELECTION_MODES)
        )
    policy = PolicyParams(
        min_award_utility=_require_unit_interval(
            raw_policy.get("min_award_utility"), "policy.min_award_utility"
        ),
        selection_mode=selection_mode,
        adequacy_min_quality=_require_unit_interval(
            raw_policy.get("adequacy_min_quality"), "policy.adequacy_min_quality"
        ),
        high_risk_min_band_success_rate=_optional_unit_interval(
            raw_floor.get("min_band_success_rate"),
            "policy.high_risk_floor.min_band_success_rate",
        ),
        high_risk_min_calibrated_confidence=_optional_unit_interval(
            raw_floor.get("min_calibrated_confidence"),
            "policy.high_risk_floor.min_calibrated_confidence",
        ),
    )

    raw_providers = {**DEFAULT_PROVIDERS, **raw.get("providers", {})}
    providers = ProviderParams(
        timeout_seconds=_require_positive(
            raw_providers.get("timeout_seconds"), "providers.timeout_seconds"
        ),
        retries=_require_non_negative_int(raw_providers.get("retries"), "providers.retries"),
        retry_backoff_seconds=_require_non_negative(
            raw_providers.get("retry_backoff_seconds"), "providers.retry_backoff_seconds"
        ),
    )

    raw_fast_path = {**DEFAULT_FAST_PATH, **raw.get("fast_path", {})}
    fast_path = FastPathParams(
        skip_bids_for_low_risk=_require_bool(
            raw_fast_path.get("skip_bids_for_low_risk"), "fast_path.skip_bids_for_low_risk"
        ),
        default_input_tokens=_require_positive_int(
            raw_fast_path.get("default_input_tokens"), "fast_path.default_input_tokens"
        ),
        default_output_tokens=_require_positive_int(
            raw_fast_path.get("default_output_tokens"), "fast_path.default_output_tokens"
        ),
    )

    history_db = raw.get("history_db", DEFAULT_HISTORY_DB)
    if not isinstance(history_db, str) or not history_db.strip():
        raise ConfigError("'history_db' must be a non-empty string path.")

    autonomy_config = raw.get("autonomy_score_config")
    if autonomy_config is not None and not isinstance(autonomy_config, str):
        raise ConfigError("'autonomy_score_config' must be a string path or null.")

    return BiddingConfig(
        agents=agents,
        weights=weights,
        quality_mix_confidence=mix_confidence,
        quality_mix_history=mix_history,
        cost_ceiling_usd=cost_ceiling,
        calibration=calibration,
        policy=policy,
        providers=providers,
        fast_path=fast_path,
        history_db=history_db,
        autonomy_score_config=autonomy_config,
    )


def load_config(path: str | Path | None = None) -> BiddingConfig:
    """Load a config file, merging it over the built-in defaults."""
    raw: dict[str, object] = {}
    if path:
        with Path(path).open("r", encoding="utf-8") as handle:
            try:
                loaded = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"Config file is not valid JSON: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError("Config file must contain a JSON object.")
        raw = loaded
    return _build_config(raw)
