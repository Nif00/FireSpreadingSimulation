"""Event-driven fire-front propagation over a city network."""

from __future__ import annotations

import heapq
import math
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .models import CityNetwork, Edge

_SURFACE_FACTOR = {
    "paved": 1.00,
    "asphalt": 1.00,
    "concrete": 0.95,
    "gravel": 1.05,
    "vegetated": 1.30,
    "unknown": 1.00,
}


@dataclass(frozen=True, slots=True)
class FireParameters:
    """Explicit baseline coefficients for the link travel-time heuristic."""

    base_rate_m_per_min: float = 30.0
    wind_direction_deg: float = 0.0
    wind_speed_mps: float = 0.0
    moisture: float = 0.0

    def __post_init__(self) -> None:
        if self.base_rate_m_per_min <= 0:
            raise ValueError("base_rate_m_per_min must be positive")
        if not 0 <= self.wind_direction_deg < 360:
            raise ValueError("wind_direction_deg must be in [0, 360)")
        if self.wind_speed_mps < 0:
            raise ValueError("wind_speed_mps must not be negative")
        if not 0 <= self.moisture <= 1:
            raise ValueError("moisture must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class EdgeArrival:
    """The interval during which the front advances over one link."""

    edge_id: str
    from_node: str
    to_node: str
    start_minute: float
    end_minute: float
    speed_m_per_min: float
    complete: bool


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Serializable output from one deterministic propagation scenario."""

    ignition_nodes: tuple[str, ...]
    horizon_minutes: float
    parameters: FireParameters
    arrival_times: Mapping[str, float]
    edge_arrivals: tuple[EdgeArrival, ...]
    edge_scores: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "arrival_times", MappingProxyType(dict(self.arrival_times)))
        object.__setattr__(self, "edge_scores", MappingProxyType(dict(self.edge_scores)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ignition_nodes": list(self.ignition_nodes),
            "horizon_minutes": self.horizon_minutes,
            "parameters": asdict(self.parameters),
            "arrival_times": dict(sorted(self.arrival_times.items())),
            "edge_arrivals": [asdict(arrival) for arrival in self.edge_arrivals],
            "edge_scores": dict(sorted(self.edge_scores.items())),
        }


def _wind_alignment(bearing_deg: float, wind_direction_deg: float) -> float:
    difference = math.radians(bearing_deg - wind_direction_deg)
    return math.cos(difference)


def _bearing_deg(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 360


def edge_speed_m_per_min(
    network: CityNetwork,
    edge: Edge,
    source_node: str,
    target_node: str,
    parameters: FireParameters,
    wind_field: Any | None = None,
) -> float:
    """Return the heuristic spread speed for one oriented edge traversal.

    Positive edge slope is uphill from ``edge.start`` to ``edge.end``. The
    orientation is reversed automatically when a bidirectional edge is used
    in the opposite direction.
    """
    if source_node == edge.start and target_node == edge.end:
        oriented_slope = edge.slope
    elif source_node == edge.end and target_node == edge.start:
        oriented_slope = -edge.slope
    else:
        raise ValueError(f"{source_node!r}->{target_node!r} is not edge {edge.id!r}")

    source = network.nodes[source_node]
    target = network.nodes[target_node]
    bearing = _bearing_deg(source.x, source.y, target.x, target.y)
    wind_speed_mps = parameters.wind_speed_mps
    wind_direction_deg = parameters.wind_direction_deg
    if wind_field is not None:
        sample = wind_field.sample_edge(source.x, source.y, target.x, target.y)
        wind_speed_mps = sample.speed_mps
        wind_direction_deg = sample.direction_deg
    alignment = _wind_alignment(bearing, wind_direction_deg)

    wind_factor = max(
        0.35,
        1.0 + 0.12 * min(wind_speed_mps, 20.0) * alignment,
    )
    slope_factor = max(0.50, min(1.80, 1.0 + 0.80 * oriented_slope))
    width_factor = max(0.75, min(1.35, (6.0 / edge.width_m) ** 0.20))
    moisture_factor = max(0.30, 1.0 - 0.70 * parameters.moisture)
    return (
        parameters.base_rate_m_per_min
        * _SURFACE_FACTOR[edge.surface]
        * wind_factor
        * slope_factor
        * width_factor
        * moisture_factor
    )


def _edge_score(
    network: CityNetwork,
    edge: Edge,
    parameters: FireParameters,
    wind_field: Any | None = None,
) -> float:
    directions = [(edge.start, edge.end)]
    if edge.bidirectional:
        directions.append((edge.end, edge.start))
    return max(
        edge_speed_m_per_min(network, edge, source, target, parameters, wind_field)
        for source, target in directions
    )


def simulate(
    network: CityNetwork,
    ignition_nodes: list[str] | tuple[str, ...],
    parameters: FireParameters | None = None,
    horizon_minutes: float = 60.0,
    wind_field: Any | None = None,
) -> SimulationResult:
    """Propagate the front from ignition nodes until the time horizon."""
    if horizon_minutes < 0:
        raise ValueError("horizon_minutes must not be negative")
    if not ignition_nodes:
        raise ValueError("at least one ignition node is required")

    params = parameters or FireParameters()
    unique_ignitions = tuple(dict.fromkeys(ignition_nodes))
    unknown = sorted(node_id for node_id in unique_ignitions if node_id not in network.nodes)
    if unknown:
        raise ValueError(f"unknown ignition nodes: {', '.join(unknown)}")

    arrival_times: dict[str, float] = {node_id: 0.0 for node_id in unique_ignitions}
    queue: list[tuple[float, str]] = [(0.0, node_id) for node_id in unique_ignitions]
    heapq.heapify(queue)
    edge_arrivals: list[EdgeArrival] = []
    started_edges: set[str] = set()

    while queue:
        arrival, node_id = heapq.heappop(queue)
        if arrival > arrival_times[node_id] + 1e-12:
            continue
        if arrival >= horizon_minutes:
            continue

        for target_id, edge in network.neighbors(node_id):
            if edge.id in started_edges:
                continue
            started_edges.add(edge.id)
            speed = edge_speed_m_per_min(network, edge, node_id, target_id, params, wind_field)
            travel_minutes = edge.length_m / speed
            completion = arrival + travel_minutes
            edge_arrivals.append(
                EdgeArrival(
                    edge_id=edge.id,
                    from_node=node_id,
                    to_node=target_id,
                    start_minute=arrival,
                    end_minute=min(completion, horizon_minutes),
                    speed_m_per_min=speed,
                    complete=completion <= horizon_minutes,
                )
            )
            if completion <= horizon_minutes and (
                target_id not in arrival_times
                or completion < arrival_times[target_id] - 1e-12
            ):
                arrival_times[target_id] = completion
                heapq.heappush(queue, (completion, target_id))

    edge_arrivals.sort(key=lambda item: (item.start_minute, item.edge_id, item.from_node, item.to_node))
    raw_scores = {
        edge.id: _edge_score(network, edge, params, wind_field)
        for edge in sorted(network.edges.values(), key=lambda item: item.id)
    }
    minimum = min(raw_scores.values(), default=0.0)
    maximum = max(raw_scores.values(), default=0.0)
    if maximum == minimum:
        scores = {edge_id: (1.0 if maximum else 0.0) for edge_id in raw_scores}
    else:
        scores = {
            edge_id: (score - minimum) / (maximum - minimum)
            for edge_id, score in raw_scores.items()
        }

    return SimulationResult(
        ignition_nodes=unique_ignitions,
        horizon_minutes=horizon_minutes,
        parameters=params,
        arrival_times=arrival_times,
        edge_arrivals=tuple(edge_arrivals),
        edge_scores=scores,
    )
