"""Convert OSM building footprints and height tags into a 3D scene layer."""

from __future__ import annotations

import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def _local_xy(lat: float, lon: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    earth_radius_m = 6_378_137.0
    x = math.radians(lon - origin_lon) * earth_radius_m * math.cos(math.radians(origin_lat))
    y = math.radians(lat - origin_lat) * earth_radius_m
    return x, y


def _number(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    number = float(match.group(0).replace(",", "."))
    if re.search(r"(?:ft|feet|foot)\b", str(value), re.IGNORECASE):
        number *= 0.3048
    return number


def _positive_number(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number >= 0 else None


def _area_m2(polygon: Sequence[tuple[float, float]]) -> float:
    return abs(
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(polygon, (*polygon[1:], polygon[0]))
        )
    ) / 2


def _height(tags: Mapping[str, str]) -> tuple[float, str, float | None]:
    explicit = _positive_number(tags.get("height"))
    levels = _positive_number(tags.get("building:levels"))
    if explicit is not None:
        return explicit, "height_tag", levels
    if levels is not None:
        return levels * 3.0, "levels_estimate", levels
    return 0.0, "footprint_only", None


def _parse_tile(path: Path) -> tuple[dict[str, tuple[float, float]], dict[str, dict[str, Any]]]:
    nodes: dict[str, tuple[float, float]] = {}
    buildings: dict[str, dict[str, Any]] = {}
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag == "node":
            node_id = element.attrib.get("id")
            lat = element.attrib.get("lat")
            lon = element.attrib.get("lon")
            if node_id is not None and lat is not None and lon is not None:
                nodes[node_id] = (float(lat), float(lon))
            element.clear()
        elif element.tag == "way":
            tags = {
                tag.attrib["k"]: tag.attrib.get("v", "")
                for tag in element.findall("tag")
                if "k" in tag.attrib
            }
            if "building" in tags or "building:part" in tags:
                way_id = element.attrib.get("id")
                refs = [
                    node.attrib["ref"]
                    for node in element.findall("nd")
                    if "ref" in node.attrib
                ]
                if way_id is not None and len(refs) >= 3:
                    buildings[way_id] = {"id": way_id, "refs": refs, "tags": tags}
            element.clear()
    return nodes, buildings


def _collect_tiles(tile_paths: Iterable[str | Path]) -> tuple[dict[str, tuple[float, float]], dict[str, dict[str, Any]]]:
    nodes: dict[str, tuple[float, float]] = {}
    buildings: dict[str, dict[str, Any]] = {}
    for tile_path in tile_paths:
        tile_nodes, tile_buildings = _parse_tile(Path(tile_path))
        nodes.update(tile_nodes)
        buildings.update(tile_buildings)
    return nodes, buildings


def normalize_buildings(
    tile_paths: Iterable[str | Path],
    *,
    origin_lat: float,
    origin_lon: float,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a normalized building layer from direct OSM API XML tiles."""
    tile_paths = list(tile_paths)
    nodes, ways = _collect_tiles(tile_paths)
    normalized: list[dict[str, Any]] = []
    height_counts = {"height_tag": 0, "levels_estimate": 0, "footprint_only": 0}
    for way_id in sorted(ways, key=lambda value: int(value) if value.isdigit() else value):
        record = ways[way_id]
        coordinates = [nodes[ref] for ref in record["refs"] if ref in nodes]
        if len(coordinates) < 3:
            continue
        if coordinates[0] != coordinates[-1]:
            coordinates.append(coordinates[0])
        polygon = [_local_xy(lat, lon, origin_lat, origin_lon) for lat, lon in coordinates]
        area = _area_m2(polygon[:-1] if polygon[0] == polygon[-1] else polygon)
        if area < 1.0:
            continue
        tags = record["tags"]
        height_m, height_source, levels = _height(tags)
        height_counts[height_source] += 1
        normalized.append(
            {
                "id": f"osm:building:{way_id}",
                "polygon": [[x, y] for x, y in polygon[:-1]],
                "area_m2": area,
                "height_m": height_m,
                "min_height_m": _positive_number(tags.get("min_height")) or 0.0,
                "height_source": height_source,
                "levels": levels,
                "building": tags.get("building"),
                "building_part": tags.get("building:part"),
                "roof_shape": tags.get("roof:shape"),
                "roof_height_m": _positive_number(tags.get("roof:height")),
                "tags": {
                    key: tags[key]
                    for key in (
                        "building",
                        "building:part",
                        "building:levels",
                        "height",
                        "min_height",
                        "roof:shape",
                        "roof:height",
                        "roof:levels",
                        "name",
                    )
                    if key in tags
                },
            }
        )

    source_record = dict(source)
    source_record.update(
        {
            "origin_latitude": origin_lat,
            "origin_longitude": origin_lon,
            "tile_count": len(tile_paths),
            "building_count": len(normalized),
            "height_source_counts": height_counts,
        }
    )
    return {
        "schema_version": 1,
        "coordinate_reference": {
            "system": "local equirectangular projection",
            "units": "meters",
            "origin_latitude": origin_lat,
            "origin_longitude": origin_lon,
            "source_crs": "EPSG:4326",
        },
        "source": source_record,
        "buildings": normalized,
    }


def normalize_buildings_from_osm(
    payload: Mapping[str, Any],
    *,
    origin_lat: float,
    origin_lon: float,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize Overpass JSON building ways with inline geometry."""
    elements = payload.get("elements", [])
    if not isinstance(elements, list):
        raise ValueError("OSM payload elements must be a list")
    normalized: list[dict[str, Any]] = []
    height_counts = {"height_tag": 0, "levels_estimate": 0, "footprint_only": 0}
    for element in elements:
        if not isinstance(element, Mapping) or element.get("type") != "way":
            continue
        tags = element.get("tags", {})
        if not isinstance(tags, Mapping) or ("building" not in tags and "building:part" not in tags):
            continue
        geometry = element.get("geometry", [])
        coordinates = [
            (float(point["lat"]), float(point["lon"]))
            for point in geometry
            if isinstance(point, Mapping) and "lat" in point and "lon" in point
        ]
        if len(coordinates) < 3:
            continue
        if coordinates[0] != coordinates[-1]:
            coordinates.append(coordinates[0])
        polygon = [_local_xy(lat, lon, origin_lat, origin_lon) for lat, lon in coordinates]
        area = _area_m2(polygon[:-1] if polygon[0] == polygon[-1] else polygon)
        if area < 1.0:
            continue
        height_m, height_source, levels = _height(tags)
        height_counts[height_source] += 1
        way_id = str(element.get("id", "unknown"))
        normalized.append(
            {
                "id": f"osm:building:{way_id}",
                "polygon": [[x, y] for x, y in polygon[:-1]],
                "area_m2": area,
                "height_m": height_m,
                "min_height_m": _positive_number(tags.get("min_height")) or 0.0,
                "height_source": height_source,
                "levels": levels,
                "building": tags.get("building"),
                "building_part": tags.get("building:part"),
                "roof_shape": tags.get("roof:shape"),
                "roof_height_m": _positive_number(tags.get("roof:height")),
                "tags": {
                    key: tags[key]
                    for key in (
                        "building",
                        "building:part",
                        "building:levels",
                        "height",
                        "min_height",
                        "roof:shape",
                        "roof:height",
                        "roof:levels",
                        "name",
                    )
                    if key in tags
                },
            }
        )
    source_record = dict(source)
    source_record.update(
        {
            "origin_latitude": origin_lat,
            "origin_longitude": origin_lon,
            "osm_element_count": len(elements),
            "building_count": len(normalized),
            "height_source_counts": height_counts,
        }
    )
    return {
        "schema_version": 1,
        "coordinate_reference": {
            "system": "local equirectangular projection",
            "units": "meters",
            "origin_latitude": origin_lat,
            "origin_longitude": origin_lon,
            "source_crs": "EPSG:4326",
        },
        "source": source_record,
        "buildings": normalized,
    }


def convert_osm_json(
    source_path: str | Path,
    output_path: str | Path,
    *,
    origin_lat: float,
    origin_lon: float,
    source_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert an Overpass JSON building extract into the 3D layer contract."""
    payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
    normalized = normalize_buildings_from_osm(
        payload,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        source=source_metadata,
    )
    Path(output_path).write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def convert_directory(
    tile_dir: str | Path,
    output_path: str | Path,
    *,
    origin_lat: float,
    origin_lon: float,
    source_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    tile_paths = sorted(Path(tile_dir).glob("*.osm"))
    if not tile_paths:
        raise ValueError(f"no .osm tiles found in {tile_dir}")
    payload = normalize_buildings(
        tile_paths,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        source=source_metadata,
    )
    Path(output_path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert OSM XML map tiles to a 3D building layer")
    parser.add_argument("tile_dir")
    parser.add_argument("output")
    parser.add_argument("--origin-latitude", type=float, required=True)
    parser.add_argument("--origin-longitude", type=float, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--bbox", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    convert_directory(
        args.tile_dir,
        args.output,
        origin_lat=args.origin_latitude,
        origin_lon=args.origin_longitude,
        source_metadata={
            "provider": "OpenStreetMap contributors",
            "source_url": args.source_url,
            "bbox": args.bbox,
            "license": "ODbL 1.0",
            "data_type": "OSM map XML tiles filtered to building and building:part ways",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
