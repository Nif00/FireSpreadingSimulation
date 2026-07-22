"""Convert Overpass OSM road ways into the normalized graph contract."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import CityNetwork, Edge, Node

_DEFAULT_WIDTHS = {
    "motorway": 12.0,
    "trunk": 10.0,
    "primary": 8.0,
    "secondary": 7.0,
    "tertiary": 6.0,
    "unclassified": 5.0,
    "residential": 5.0,
    "living_street": 4.0,
    "service": 3.0,
    "track": 3.0,
    "pedestrian": 4.0,
    "road": 5.0,
}


def _coordinate_key(lat: float, lon: float) -> str:
    return f"osm:{lat:.7f}:{lon:.7f}"


def _local_xy(lat: float, lon: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    earth_radius_m = 6_378_137.0
    x = math.radians(lon - origin_lon) * earth_radius_m * math.cos(math.radians(origin_lat))
    y = math.radians(lat - origin_lat) * earth_radius_m
    return x, y


def _segment_length_m(point_a: Mapping[str, Any], point_b: Mapping[str, Any]) -> float:
    earth_radius_m = 6_371_008.8
    lat_a, lon_a = math.radians(float(point_a["lat"])), math.radians(float(point_a["lon"]))
    lat_b, lon_b = math.radians(float(point_b["lat"])), math.radians(float(point_b["lon"]))
    d_lat = lat_b - lat_a
    d_lon = lon_b - lon_a
    haversine = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
    )
    return 2 * earth_radius_m * math.asin(math.sqrt(haversine))


def _numeric_tag(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", value)
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def _width_m(tags: Mapping[str, Any], highway: str) -> float:
    width = _numeric_tag(tags.get("width"))
    return width if width and width > 0 else _DEFAULT_WIDTHS.get(highway, 5.0)


def _surface(tags: Mapping[str, Any]) -> str:
    raw = str(tags.get("surface", "unknown")).lower().replace(" ", "_")
    if raw in {"asphalt", "paved"}:
        return "asphalt" if raw == "asphalt" else "paved"
    if raw in {"concrete", "concrete:lanes", "cement"}:
        return "concrete"
    if raw in {"gravel", "fine_gravel", "compacted", "dirt", "ground", "sand", "pebblestone"}:
        return "gravel"
    if raw in {"grass", "grass_paver", "mud"}:
        return "vegetated"
    return "unknown"


def _slope(tags: Mapping[str, Any]) -> float:
    value = tags.get("incline")
    if value is None:
        return 0.0
    numeric = _numeric_tag(value)
    if numeric is None:
        return 0.0
    if "%" in str(value):
        numeric /= 100.0
    return max(-1.0, min(1.0, numeric))


def _is_reverse_oneway(value: Any) -> bool:
    return str(value).strip().lower() == "-1"


def _is_oneway(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1", "-1"}


def _way_geometry(element: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    geometry = element.get("geometry")
    if not isinstance(geometry, list):
        return []
    return [point for point in geometry if isinstance(point, Mapping) and "lat" in point and "lon" in point]


def network_from_osm(
    payload: Mapping[str, Any],
    *,
    origin_lat: float,
    origin_lon: float,
) -> CityNetwork:
    """Convert Overpass JSON with way geometry into a validated graph."""
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    elements = payload.get("elements", [])
    if not isinstance(elements, list):
        raise ValueError("OSM payload elements must be a list")

    for element in elements:
        if not isinstance(element, Mapping) or element.get("type") != "way":
            continue
        tags = element.get("tags", {})
        if not isinstance(tags, Mapping) or "highway" not in tags:
            continue
        geometry = _way_geometry(element)
        if len(geometry) < 2:
            continue
        if _is_reverse_oneway(tags.get("oneway")):
            geometry.reverse()
        way_id = str(element.get("id", "unknown"))
        highway = str(tags["highway"])
        for point in geometry:
            lat = float(point["lat"])
            lon = float(point["lon"])
            node_id = _coordinate_key(lat, lon)
            if node_id not in nodes:
                x, y = _local_xy(lat, lon, origin_lat, origin_lon)
                elevation = _numeric_tag(point.get("ele") or point.get("elevation"))
                nodes[node_id] = Node(
                    id=node_id,
                    x=x,
                    y=y,
                    kind="road_node",
                    elevation_m=elevation,
                    metadata={"latitude": lat, "longitude": lon},
                )

        for index, (point_a, point_b) in enumerate(zip(geometry, geometry[1:])):
            start = _coordinate_key(float(point_a["lat"]), float(point_a["lon"]))
            end = _coordinate_key(float(point_b["lat"]), float(point_b["lon"]))
            length_m = _segment_length_m(point_a, point_b)
            if start == end or length_m <= 0:
                continue
            metadata = {
                "osm_way_id": way_id,
                "osm_highway": highway,
                "name": tags.get("name"),
                "ref": tags.get("ref"),
                "maxspeed": tags.get("maxspeed"),
                "lanes": tags.get("lanes"),
                "bridge": tags.get("bridge"),
                "tunnel": tags.get("tunnel"),
                "source_surface": tags.get("surface"),
            }
            edges.append(
                Edge(
                    id=f"osm:{way_id}:{index}",
                    start=start,
                    end=end,
                    length_m=length_m,
                    width_m=_width_m(tags, highway),
                    surface=_surface(tags),
                    slope=_slope(tags),
                    bidirectional=not _is_oneway(tags.get("oneway")),
                    metadata={key: value for key, value in metadata.items() if value is not None},
                )
            )

    if not nodes or not edges:
        raise ValueError("OSM payload did not contain usable highway geometry")
    return CityNetwork(list(nodes.values()), edges)


def normalized_payload(
    network: CityNetwork,
    *,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    """Wrap a graph with provenance needed to interpret its coordinates."""
    payload = network.to_dict()
    payload["schema_version"] = 1
    payload["coordinate_reference"] = {
        "system": "local equirectangular projection",
        "units": "meters",
        "origin_latitude": source["origin_latitude"],
        "origin_longitude": source["origin_longitude"],
        "source_crs": "EPSG:4326",
    }
    payload["source"] = dict(source)
    return payload


def convert_file(
    source_path: str | Path,
    output_path: str | Path,
    *,
    origin_lat: float,
    origin_lon: float,
    source_metadata: Mapping[str, Any],
) -> CityNetwork:
    source = Path(source_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    network = network_from_osm(payload, origin_lat=origin_lat, origin_lon=origin_lon)
    source_record = dict(source_metadata)
    source_record.update(
        {
            "origin_latitude": origin_lat,
            "origin_longitude": origin_lon,
            "osm_element_count": len(payload.get("elements", [])),
            "normalized_node_count": len(network.nodes),
            "normalized_edge_count": len(network.edges),
        }
    )
    Path(output_path).write_text(
        json.dumps(normalized_payload(network, source=source_record), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return network


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert Overpass OSM JSON to a fire-spread network")
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--origin-latitude", type=float, required=True)
    parser.add_argument("--origin-longitude", type=float, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--bbox", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    convert_file(
        args.source,
        args.output,
        origin_lat=args.origin_latitude,
        origin_lon=args.origin_longitude,
        source_metadata={
            "provider": "OpenStreetMap contributors",
            "source_url": args.source_url,
            "bbox": args.bbox,
            "license": "ODbL 1.0",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
