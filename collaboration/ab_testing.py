"""
A/B Testing Framework for hermes-agent-collab.
Supports experiment management, consistent hashing, and statistical significance testing.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    """A single variant in an A/B experiment."""
    id: str
    name: str
    config: dict = field(default_factory=dict)
    traffic_weight: float = 1.0  # 0.0-1.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MetricConfig:
    """Configuration for a single metric being tracked."""
    name: str
    metric_type: str = "gauge"  # "counter" | "gauge" | "latency"
    higher_is_better: bool = True
    min_sample_size: int = 100


@dataclass
class MetricObservation:
    """A single observation of a metric for an entity."""
    entity_id: str
    variant_id: str
    value: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class VariantStats:
    """Computed statistics for a variant."""
    variant_id: str
    sample_size: int
    mean: float
    stddev: float
    sum: float = 0.0
    sum_sq: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SignificanceResult:
    """Statistical significance result for a variant comparison."""
    variant_id: str
    control_id: str
    control_mean: float
    control_stddev: float
    treatment_mean: float
    treatment_stddev: float
    z_statistic: float | None
    t_statistic: float | None
    degrees_of_freedom: float | None
    p_value: float
    significant: bool
    confidence_level: float
    mean_diff: float
    relative_lift: float | None
    recommended: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExperimentResults:
    """Full results of an A/B experiment."""
    experiment_id: str
    status: str  # "running" | "stopped" | "analyzed"
    total_samples: int
    variant_stats: list[VariantStats]
    significance: list[SignificanceResult]
    winner: str | None
    recommendation: str
    analyzed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Experiment:
    """An A/B experiment definition."""
    id: str
    name: str
    description: str = ""
    variants: list[Variant] = field(default_factory=list)
    metrics: list[MetricConfig] = field(default_factory=list)
    traffic_allocation: float = 1.0  # Fraction of total traffic in experiment
    status: str = "draft"  # "draft" | "running" | "stopped" | "analyzed"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    stopped_at: str | None = None
    tags: list[str] = field(default_factory=list)

    # Internal state
    _observations: dict[str, list[MetricObservation]] = field(default_factory=dict, repr=False)
    _entity_assignments: dict[str, str] = field(default_factory=dict, repr=False)  # entity_id -> variant_id

    def to_dict(self) -> dict:
        d = asdict(self)
        del d["_observations"]
        del d["_entity_assignments"]
        return d


# ---------------------------------------------------------------------------
# Statistical Functions
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stddev(values: list[float], mean_val: float | None = None) -> float:
    if len(values) < 2:
        return 0.0
    m = mean_val if mean_val is not None else _mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _pooled_stddev(s1: float, n1: int, s2: float, n2: int) -> float:
    """Pooled standard deviation for two samples."""
    if n1 < 2 or n2 < 2:
        return 0.0
    df = (n1 - 1) + (n2 - 1)
    if df == 0:
        return 0.0
    pooled = ((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / df
    return math.sqrt(pooled)


def _welch_ttest(m1: float, s1: float, n1: int, m2: float, s2: float, n2: int) -> tuple[float, float]:
    """
    Welch's t-test for two independent samples.
    Returns (t_statistic, degrees_of_freedom).
    """
    if n1 < 2 or n2 < 2:
        return 0.0, 0.0
    if s1 == 0 and s2 == 0:
        return 0.0, 0.0

    # Welch-Satterthwaite degrees of freedom
    s1_sq = s1 ** 2
    s2_sq = s2 ** 2
    se = math.sqrt(s1_sq / n1 + s2_sq / n2)
    if se == 0:
        return 0.0, 0.0

    t = (m1 - m2) / se

    num = (s1_sq / n1 + s2_sq / n2) ** 2
    denom = (s1_sq / n1) ** 2 / (n1 - 1) + (s2_sq / n2) ** 2 / (n2 - 1)
    df = num / denom if denom > 0 else 0.0

    return t, df


def _normal_cdf(x: float) -> float:
    """Approximation of the standard normal CDF."""
    # Abramowitz and Stegun approximation
    if x < 0:
        return 1 - _normal_cdf(-x)
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911
    sign = -1
    z = abs(x)
    t = 1.0 / (1.0 + p * z)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-z * z)
    return 1.0 - sign * y


def _two_tailed_p_value(z: float) -> float:
    """Two-tailed p-value from z-score."""
    return 2.0 * (1.0 - _normal_cdf(abs(z)))


def _min_sample_size(baseline_rate: float, mde: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """
    Calculate minimum sample size per variant for a binary metric.
    
    Args:
        baseline_rate: Baseline conversion rate (0.0-1.0)
        mde: Minimum detectable effect (relative, e.g., 0.1 for 10% lift)
        alpha: Significance level
        power: Statistical power (1 - beta)
    
    Returns:
        Minimum sample size per variant
    """
    if baseline_rate <= 0 or baseline_rate >= 1:
        return 100
    
    p1 = baseline_rate
    p2 = baseline_rate * (1 + mde)
    
    z_alpha = 1.96  # for alpha = 0.05
    z_beta = 0.842  # for power = 0.8
    
    pooled = (p1 + p2) / 2
    effect = abs(p2 - p1)
    
    if effect == 0:
        return 100
    
    n = ((z_alpha * math.sqrt(2 * pooled * (1 - pooled)) + 
          z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2) / (effect ** 2)
    
    return max(int(math.ceil(n)), 10)


# ---------------------------------------------------------------------------
# Experiment Manager
# ---------------------------------------------------------------------------

class ExperimentManager:
    """
    Manages A/B experiments lifecycle.
    Supports consistent hashing, metric tracking, and statistical significance testing.
    """

    def __init__(self):
        self._experiments: dict[str, Experiment] = {}
        self._entity_assignments: dict[str, dict[str, str]] = {}  # exp_id -> {entity_id: variant_id}

    def create_experiment(
        self,
        name: str,
        variants: list[Variant],
        metrics: list[MetricConfig],
        description: str = "",
        traffic_allocation: float = 1.0,
        tags: list[str] | None = None,
    ) -> str:
        """Create a new experiment. Returns experiment ID."""
        if not variants or len(variants) < 2:
            raise ValueError("At least 2 variants required")
        if not metrics:
            raise ValueError("At least 1 metric required")
        if not 0 < traffic_allocation <= 1:
            raise ValueError("traffic_allocation must be between 0 and 1")
        if any(v.traffic_weight < 0 for v in variants):
            raise ValueError("Traffic weights must be non-negative")

        exp_id = str(uuid.uuid4())[:8]
        exp = Experiment(
            id=exp_id,
            name=name,
            description=description,
            variants=variants,
            metrics=[MetricConfig(**m) if isinstance(m, dict) else m for m in metrics],
            traffic_allocation=traffic_allocation,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            tags=tags or [],
        )
        self._experiments[exp_id] = exp
        self._entity_assignments[exp_id] = {}
        return exp_id

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        return self._experiments.get(experiment_id)

    def get_variant(self, experiment_id: str, entity_id: str) -> Variant | None:
        """
        Get variant for an entity using consistent hashing.
        Same entity_id always returns the same variant for the same experiment.
        """
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return None

        # Check cache
        if experiment_id in self._entity_assignments:
            cached = self._entity_assignments[experiment_id].get(entity_id)
            if cached:
                for v in exp.variants:
                    if v.id == cached:
                        return v

        # Consistent hash
        key = f"{experiment_id}:{entity_id}"
        hash_val = int(hashlib.md5(key.encode()).hexdigest(), 16)
        
        # Normalize weights
        total_weight = sum(v.traffic_weight for v in exp.variants)
        if total_weight <= 0:
            return exp.variants[0] if exp.variants else None

        scaled = hash_val / (2**128) * total_weight
        cumulative = 0.0
        for v in exp.variants:
            cumulative += v.traffic_weight
            if scaled < cumulative:
                # Cache assignment
                if experiment_id not in self._entity_assignments:
                    self._entity_assignments[experiment_id] = {}
                self._entity_assignments[experiment_id][entity_id] = v.id
                return v

        # Fallback to last variant
        last = exp.variants[-1]
        if experiment_id not in self._entity_assignments:
            self._entity_assignments[experiment_id] = {}
        self._entity_assignments[experiment_id][entity_id] = last.id
        return last

    def record_metric(
        self,
        experiment_id: str,
        variant_id: str,
        entity_id: str,
        metric_name: str,
        value: float,
    ) -> bool:
        """Record a metric observation. Returns True if recorded."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return False

        # Validate variant
        if not any(v.id == variant_id for v in exp.variants):
            return False

        # Validate metric
        if not any(m.name == metric_name for m in exp.metrics):
            return False

        obs = MetricObservation(
            entity_id=entity_id,
            variant_id=variant_id,
            value=value,
        )

        key = f"{experiment_id}:{variant_id}:{metric_name}"
        if key not in exp._observations:
            exp._observations[key] = []
        exp._observations[key].append(obs)
        return True

    def get_variant_stats(self, experiment_id: str, variant_id: str, metric_name: str) -> VariantStats | None:
        """Compute statistics for a variant on a specific metric."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return None

        key = f"{experiment_id}:{variant_id}:{metric_name}"
        obs = exp._observations.get(key, [])
        if not obs:
            return VariantStats(
                variant_id=variant_id,
                sample_size=0,
                mean=0.0,
                stddev=0.0,
            )

        values = [o.value for o in obs]
        mean_val = _mean(values)
        stddev_val = _stddev(values, mean_val)

        return VariantStats(
            variant_id=variant_id,
            sample_size=len(values),
            mean=mean_val,
            stddev=stddev_val,
            sum=sum(values),
            sum_sq=sum(x**2 for x in values),
        )

    def _compute_significance(
        self,
        exp: Experiment,
        metric: MetricConfig,
        control_stats: VariantStats,
        treatment_stats: VariantStats,
    ) -> SignificanceResult:
        """Compute statistical significance between two variants."""
        if control_stats.sample_size < 2 or treatment_stats.sample_size < 2:
            return SignificanceResult(
                variant_id=treatment_stats.variant_id,
                control_id=control_stats.variant_id,
                control_mean=control_stats.mean,
                control_stddev=control_stats.stddev,
                treatment_mean=treatment_stats.mean,
                treatment_stddev=treatment_stats.stddev,
                z_statistic=None,
                t_statistic=None,
                degrees_of_freedom=None,
                p_value=1.0,
                significant=False,
                confidence_level=0.0,
                mean_diff=0.0,
                relative_lift=None,
                recommended=False,
            )

        # Use Welch's t-test
        t_stat, df = _welch_ttest(
            treatment_stats.mean, treatment_stats.stddev, treatment_stats.sample_size,
            control_stats.mean, control_stats.stddev, control_stats.sample_size,
        )

        # Convert t to approximate p-value (two-tailed)
        # Using normal approximation for large samples
        if df > 30:
            # Normal approximation
            z_approx = t_stat
            p_value = _two_tailed_p_value(z_approx)
            z_stat = z_approx
        else:
            # For small samples, use a conservative estimate
            p_value = min(1.0, 0.5)  # Conservative
            z_stat = None

        mean_diff = treatment_stats.mean - control_stats.mean
        relative_lift = None
        if control_stats.mean != 0:
            relative_lift = mean_diff / abs(control_stats.mean)

        confidence = (1.0 - p_value) * 100
        significant = p_value < 0.05

        # Recommendation logic
        if metric.higher_is_better:
            recommended = significant and treatment_stats.mean > control_stats.mean
        else:
            recommended = significant and treatment_stats.mean < control_stats.mean

        return SignificanceResult(
            variant_id=treatment_stats.variant_id,
            control_id=control_stats.variant_id,
            control_mean=control_stats.mean,
            control_stddev=control_stats.stddev,
            treatment_mean=treatment_stats.mean,
            treatment_stddev=treatment_stats.stddev,
            z_statistic=z_stat,
            t_statistic=t_stat,
            degrees_of_freedom=df,
            p_value=p_value,
            significant=significant,
            confidence_level=confidence,
            mean_diff=mean_diff,
            relative_lift=relative_lift,
            recommended=recommended,
        )

    def get_results(self, experiment_id: str) -> ExperimentResults | None:
        """Compute statistical significance and return results."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return None

        all_stats: list[VariantStats] = []
        all_significance: list[SignificanceResult] = []

        for metric in exp.metrics:
            metric_stats: list[VariantStats] = []
            for variant in exp.variants:
                stats = self.get_variant_stats(experiment_id, variant.id, metric.name)
                if stats and stats.sample_size > 0:
                    metric_stats.append(stats)
                    if stats not in all_stats:
                        all_stats.append(stats)

            # Compare each variant to the first (control)
            if len(metric_stats) >= 2:
                control = metric_stats[0]
                for treatment in metric_stats[1:]:
                    sig = self._compute_significance(exp, metric, control, treatment)
                    if sig not in all_significance:
                        all_significance.append(sig)

        # Determine winner (variant with most significant positive lifts)
        winner = None
        if all_significance:
            recommended = [s for s in all_significance if s.recommended]
            if recommended:
                # Pick the one with lowest p-value
                winner = min(recommended, key=lambda s: s.p_value).variant_id

        recommendation = ""
        if exp.status == "running":
            recommendation = "Experiment is still running. Collect more samples."
        elif winner:
            recommendation = f"Variant '{winner}' shows statistically significant improvement."
        elif all_stats:
            recommendation = "No statistically significant difference detected between variants."
        else:
            recommendation = "No observations recorded yet."

        total_samples = sum(s.sample_size for s in all_stats)

        return ExperimentResults(
            experiment_id=experiment_id,
            status=exp.status,
            total_samples=total_samples,
            variant_stats=all_stats,
            significance=all_significance,
            winner=winner,
            recommendation=recommendation,
        )

    def stop_experiment(self, experiment_id: str) -> bool:
        """Stop an experiment."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return False
        exp.status = "stopped"
        exp.stopped_at = datetime.now(timezone.utc).isoformat()
        return True

    def delete_experiment(self, experiment_id: str) -> bool:
        """Delete an experiment and all its data."""
        if experiment_id in self._experiments:
            del self._experiments[experiment_id]
        if experiment_id in self._entity_assignments:
            del self._entity_assignments[experiment_id]
        return True

    def list_experiments(self, status: str | None = None) -> list[dict]:
        """List all experiments, optionally filtered by status."""
        result = []
        for exp in self._experiments.values():
            if status and exp.status != status:
                continue
            d = exp.to_dict()
            # Compute total samples
            total = 0
            for variant in exp.variants:
                for metric in exp.metrics:
                    key = f"{exp.id}:{variant.id}:{metric.name}"
                    total += len(exp._observations.get(key, []))
            d["total_observations"] = total
            result.append(d)
        return result

    def get_experiment_summary(self, experiment_id: str) -> dict | None:
        """Get a summary of an experiment including quick stats."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return None

        results = self.get_results(experiment_id)
        d = exp.to_dict()
        if results:
            d["results_summary"] = {
                "total_samples": results.total_samples,
                "winner": results.winner,
                "recommendation": results.recommendation,
                "variant_count": len(exp.variants),
                "metric_count": len(exp.metrics),
            }
        return d
