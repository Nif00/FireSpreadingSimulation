"""File adapters for normalized network data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CityNetwork, Edge, Node


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def network_from_dict(payload: dict[str, Any]) -> CityNetwork:
    """Build a validated graph from the v1 normalized network contract."""
    if not isinstance(payload, dict):
        raise ValueError("network payload must be an object")
    nodes_payload = payload.get("nodes")
    edges_payload = payload.get("edges")
    if not isinstance(nodes_payload, list) or not isinstance(edges_payload, list):
        raise ValueError("network payload must contain list fields: nodes and edges")

    nodes: list[Node] = []
    for index, raw in enumerate(nodes_payload):
        if not isinstance(raw, dict):
            raise ValueError(f"nodes[{index}] must be an object")
        try:
            nodes.append(
                Node(
                    id=str(raw["id"]),
                    x=_number(raw["x"], f"nodes[{index}].x"),
                    y=_number(raw["y"], f"nodes[{index}].y"),
                    kind=str(raw.get("kind", "intersection")),
                    elevation_m=(
                        None
                        if raw.get("elevation_m") is None
                        else _number(raw["elevation_m"], f"nodes[{index}].elevation_m")
                    ),
                    metadata=raw.get("metadata", {}),
                )
            )
        except KeyError as exc:
            raise ValueError(f"nodes[{index}] missing field: {exc.args[0]}") from exc

    edges: list[Edge] = []
    for index, raw in enumerate(edges_payload):
        if not isinstance(raw, dict):
            raise ValueError(f"edges[{index}] must be an object")
        try:
            edges.append(
                Edge(
                    id=str(raw["id"]),
                    start=str(raw["start"]),
                    end=str(raw["end"]),
                    length_m=_number(raw["length_m"], f"edges[{index}].length_m"),
                    width_m=_number(raw.get("width_m", 6.0), f"edges[{index}].width_m"),
                    surface=str(raw.get("surface", "unknown")),
                    slope=_number(raw.get("slope", 0.0), f"edges[{index}].slope"),
                    bidirectional=bool(raw.get("bidirectional", True)),
                    metadata=raw.get("metadata", {}),
                )
            )
        except KeyError as exc:
            raise ValueError(f"edges[{index}] missing field: {exc.args[0]}") from exc

    return CityNetwork(nodes, edges)


def load_network(path: str | Path) -> CityNetwork:
    """Load a normalized network from a UTF-8 JSON file."""
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc.msg}") from exc
    return network_from_dict(payload)


def dump_json(payload: Any, path: str | Path) -> None:
    """Write JSON with stable formatting for reproducible scenario artifacts."""
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
