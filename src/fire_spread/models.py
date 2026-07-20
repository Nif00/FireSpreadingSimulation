"""Domain types for a normalized urban street network."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


_ALLOWED_SURFACES = frozenset({"paved", "concrete", "asphalt", "gravel", "vegetated", "unknown"})


def _metadata(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class Node:
    """A junction or location at which the fire front can change links."""

    id: str
    x: float
    y: float
    kind: str = "intersection"
    elevation_m: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("node id must not be empty")
        if self.elevation_m is not None and not isinstance(self.elevation_m, (int, float)):
            raise TypeError("node elevation_m must be numeric or None")
        object.__setattr__(self, "metadata", _metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class Edge:
    """A street or alley link connecting two network nodes."""

    id: str
    start: str
    end: str
    length_m: float
    width_m: float = 6.0
    surface: str = "unknown"
    slope: float = 0.0
    bidirectional: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("edge id must not be empty")
        if not self.start.strip() or not self.end.strip():
            raise ValueError(f"edge {self.id!r} must have non-empty endpoints")
        if self.start == self.end:
            raise ValueError(f"edge {self.id!r} cannot connect a node to itself")
        if self.length_m <= 0:
            raise ValueError(f"edge {self.id!r} length_m must be positive")
        if self.width_m <= 0:
            raise ValueError(f"edge {self.id!r} width_m must be positive")
        if not -1.0 <= self.slope <= 1.0:
            raise ValueError(f"edge {self.id!r} slope must be between -1 and 1")
        if self.surface not in _ALLOWED_SURFACES:
            raise ValueError(
                f"edge {self.id!r} surface must be one of {sorted(_ALLOWED_SURFACES)}"
            )
        object.__setattr__(self, "metadata", _metadata(self.metadata))


class CityNetwork:
    """Validated immutable graph with deterministic neighbor iteration."""

    __slots__ = ("_nodes", "_edges", "_adjacency")

    def __init__(self, nodes: list[Node] | tuple[Node, ...], edges: list[Edge] | tuple[Edge, ...]) -> None:
        node_map = {node.id: node for node in nodes}
        if len(node_map) != len(nodes):
            raise ValueError("node ids must be unique")

        edge_map = {edge.id: edge for edge in edges}
        if len(edge_map) != len(edges):
            raise ValueError("edge ids must be unique")

        missing = sorted(
            {endpoint for edge in edges for endpoint in (edge.start, edge.end) if endpoint not in node_map}
        )
        if missing:
            raise ValueError(f"edges reference missing nodes: {', '.join(missing)}")

        adjacency: dict[str, list[tuple[str, Edge]]] = {node_id: [] for node_id in node_map}
        for edge in edges:
            adjacency[edge.start].append((edge.end, edge))
            if edge.bidirectional:
                adjacency[edge.end].append((edge.start, edge))
        for neighbors in adjacency.values():
            neighbors.sort(key=lambda pair: (pair[0], pair[1].id))

        self._nodes = MappingProxyType(node_map)
        self._edges = MappingProxyType(edge_map)
        self._adjacency = MappingProxyType(
            {node_id: tuple(neighbors) for node_id, neighbors in adjacency.items()}
        )

    @property
    def nodes(self) -> Mapping[str, Node]:
        return self._nodes

    @property
    def edges(self) -> Mapping[str, Edge]:
        return self._edges

    def neighbors(self, node_id: str) -> tuple[tuple[str, Edge], ...]:
        try:
            return self._adjacency[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown node: {node_id}") from exc

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "nodes": [
                {
                    "id": node.id,
                    "x": node.x,
                    "y": node.y,
                    "kind": node.kind,
                    "elevation_m": node.elevation_m,
                    "metadata": dict(node.metadata),
                }
                for node in self._nodes.values()
            ],
            "edges": [
                {
                    "id": edge.id,
                    "start": edge.start,
                    "end": edge.end,
                    "length_m": edge.length_m,
                    "width_m": edge.width_m,
                    "surface": edge.surface,
                    "slope": edge.slope,
                    "bidirectional": edge.bidirectional,
                    "metadata": dict(edge.metadata),
                }
                for edge in self._edges.values()
            ],
        }
