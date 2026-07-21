"""Small local web UI server for real network scenarios."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence

from .io import load_network
from .models import CityNetwork
from .propagation import FireParameters, SimulationResult, simulate
from .urban_wind import UrbanWindField


class ScenarioService:
    """Owns one loaded dataset and executes real simulations against it."""

    def __init__(self, dataset_path: str | Path, buildings_path: str | Path | None = None) -> None:
        self.dataset_path = Path(dataset_path)
        self.network = load_network(self.dataset_path)
        payload = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        self.source = payload.get("source", {})
        self.buildings_path = Path(buildings_path) if buildings_path else None
        self.buildings_payload = self._load_buildings()
        self._prepare_building_index()
        self.default_ignition = min(
            self.network.nodes,
            key=lambda node_id: (
                self.network.nodes[node_id].x**2 + self.network.nodes[node_id].y**2,
                node_id,
            ),
        )
        self._lock = threading.Lock()
        self._last_result: SimulationResult | None = None
        self._last_urban_wind: dict[str, Any] = {
            "enabled": False,
            "name": "QUIC-URB-inspired diagnostic urban wind",
            "note": "Disabled for the current result.",
        }

    def _load_buildings(self) -> dict[str, Any]:
        if self.buildings_path is None or not self.buildings_path.exists():
            return {"buildings": [], "source": {}}
        payload = json.loads(self.buildings_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("buildings"), list):
            raise ValueError("building dataset must contain a buildings list")
        return payload

    def _prepare_building_index(self) -> None:
        """Index building centroids for the web-only fire/building coupling."""
        self._building_cell_size = 100.0
        self._building_records: list[dict[str, Any]] = []
        self._building_index: dict[tuple[int, int], list[int]] = {}
        largest_radius = 0.0
        for building in self.buildings_payload.get("buildings", []):
            polygon = building.get("polygon", [])
            if not isinstance(polygon, list) or len(polygon) < 3:
                continue
            points = [
                (float(point[0]), float(point[1]))
                for point in polygon
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            if len(points) < 3:
                continue
            center_x = sum(point[0] for point in points) / len(points)
            center_y = sum(point[1] for point in points) / len(points)
            radius = max(
                math.hypot(point[0] - center_x, point[1] - center_y)
                for point in points
            )
            record_index = len(self._building_records)
            self._building_records.append(
                {
                    "id": str(building.get("id", "")),
                    "x": center_x,
                    "y": center_y,
                    "radius": radius,
                }
            )
            largest_radius = max(largest_radius, radius)
            cell = (
                math.floor(center_x / self._building_cell_size),
                math.floor(center_y / self._building_cell_size),
            )
            self._building_index.setdefault(cell, []).append(record_index)
        self._building_search_radius = max(40.0, largest_radius + 20.0)

    def _building_candidates(self, x1: float, y1: float, x2: float | None = None, y2: float | None = None):
        x2 = x1 if x2 is None else x2
        y2 = y1 if y2 is None else y2
        search = self._building_search_radius
        cell_size = self._building_cell_size
        min_cell_x = math.floor((min(x1, x2) - search) / cell_size)
        max_cell_x = math.floor((max(x1, x2) + search) / cell_size)
        min_cell_y = math.floor((min(y1, y2) - search) / cell_size)
        max_cell_y = math.floor((max(y1, y2) + search) / cell_size)
        seen: set[int] = set()
        for cell_x in range(min_cell_x, max_cell_x + 1):
            for cell_y in range(min_cell_y, max_cell_y + 1):
                for record_index in self._building_index.get((cell_x, cell_y), []):
                    if record_index not in seen:
                        seen.add(record_index)
                        yield self._building_records[record_index]

    @staticmethod
    def _point_to_segment_distance(point_x: float, point_y: float, x1: float, y1: float, x2: float, y2: float) -> float:
        delta_x = x2 - x1
        delta_y = y2 - y1
        length_squared = delta_x * delta_x + delta_y * delta_y
        if length_squared == 0:
            return math.hypot(point_x - x1, point_y - y1)
        projection = ((point_x - x1) * delta_x + (point_y - y1) * delta_y) / length_squared
        projection = max(0.0, min(1.0, projection))
        closest_x = x1 + projection * delta_x
        closest_y = y1 + projection * delta_y
        return math.hypot(point_x - closest_x, point_y - closest_y)

    def _burning_buildings(self, result: SimulationResult) -> list[dict[str, Any]]:
        """Return buildings adjacent to the advancing front.

        This is deliberately a presentation coupling: a building is lit when
        its footprint centroid is within its footprint radius plus 18 m of an
        activated road segment or ignition node.
        """
        if not self._building_records:
            return []
        fronts: list[tuple[float, float, float, float, float, str | None]] = []
        for node_id in result.ignition_nodes:
            node = self.network.nodes[node_id]
            fronts.append((node.x, node.y, node.x, node.y, 0.0, None))
        for arrival in result.edge_arrivals:
            edge = self.network.edges.get(arrival.edge_id)
            if edge is None:
                continue
            start = self.network.nodes[edge.start]
            end = self.network.nodes[edge.end]
            fronts.append((start.x, start.y, end.x, end.y, arrival.start_minute, edge.id))

        burning: dict[str, dict[str, Any]] = {}
        for x1, y1, x2, y2, ignition_minute, edge_id in fronts:
            for building in self._building_candidates(x1, y1, x2, y2):
                distance = self._point_to_segment_distance(
                    building["x"], building["y"], x1, y1, x2, y2
                )
                if distance > building["radius"] + 18.0:
                    continue
                current = burning.get(building["id"])
                if current is None or ignition_minute < current["ignition_minute"]:
                    burning[building["id"]] = {
                        "building_id": building["id"],
                        "ignition_minute": ignition_minute,
                        "source_edge_id": edge_id,
                    }
        return sorted(
            burning.values(),
            key=lambda item: (item["ignition_minute"], item["building_id"]),
        )

    def status(self) -> dict[str, Any]:
        building_source = self.buildings_payload.get("source", {})
        return {
            "dataset": self.dataset_path.name,
            "nodes": len(self.network.nodes),
            "edges": len(self.network.edges),
            "default_ignition": self.default_ignition,
            "elevation_nodes": sum(node.elevation_m is not None for node in self.network.nodes.values()),
            "source": dict(self.source),
            "buildings": len(self.buildings_payload.get("buildings", [])),
            "building_height_sources": dict(building_source.get("height_source_counts", {})),
            "buildings_dataset": self.buildings_path.name if self.buildings_path else None,
        }

    def network_payload(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": node.id,
                    "x": node.x,
                    "y": node.y,
                    "elevation_m": node.elevation_m,
                    "metadata": dict(node.metadata),
                }
                for node in self.network.nodes.values()
            ],
            "edges": [
                {"id": edge.id, "start": edge.start, "end": edge.end}
                for edge in self.network.edges.values()
            ],
        }

    def buildings_payload_for_web(self) -> dict[str, Any]:
        return {
            "source": dict(self.buildings_payload.get("source", {})),
            "buildings": [
                {
                    "id": building["id"],
                    "polygon": building["polygon"],
                    "area_m2": building.get("area_m2", 0),
                    "height_m": building.get("height_m", 0),
                    "min_height_m": building.get("min_height_m", 0),
                    "height_source": building.get("height_source", "footprint_only"),
                    "levels": building.get("levels"),
                    "roof_height_m": building.get("roof_height_m"),
                    "roof_shape": building.get("roof_shape"),
                    "building": building.get("building"),
                    "building_part": building.get("building_part"),
                }
                for building in self.buildings_payload.get("buildings", [])
            ],
        }

    def run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        ignition = request.get("ignition", self.default_ignition)
        if isinstance(ignition, str):
            ignition_nodes = [ignition.strip()]
        elif isinstance(ignition, list):
            ignition_nodes = [str(value).strip() for value in ignition]
        else:
            raise ValueError("ignition must be a node ID or list of node IDs")
        ignition_nodes = [node_id for node_id in ignition_nodes if node_id]

        parameters = FireParameters(
            base_rate_m_per_min=float(request.get("base_rate_m_per_min", 30.0)),
            wind_direction_deg=float(request.get("wind_direction_deg", 0.0)),
            wind_speed_mps=float(request.get("wind_speed_mps", 0.0)),
            moisture=float(request.get("moisture", 0.0)),
        )
        horizon_minutes = float(request.get("horizon_minutes", 60.0))
        urban_wind_enabled = request.get("urban_wind_enabled", True) is not False
        cell_size_m = float(request.get("urban_wind_cell_size_m", 100.0))
        if not 25.0 <= cell_size_m <= 500.0:
            raise ValueError("urban_wind_cell_size_m must be between 25 and 500")
        urban_wind = None
        if urban_wind_enabled and self.buildings_payload.get("buildings"):
            urban_wind = UrbanWindField.from_buildings(
                self.buildings_payload.get("buildings", []),
                self._model_bounds(),
                wind_speed_mps=parameters.wind_speed_mps,
                wind_direction_deg=parameters.wind_direction_deg,
                cell_size_m=cell_size_m,
            )
        with self._lock:
            self._last_urban_wind = (
                urban_wind.metadata
                if urban_wind is not None
                else {
                    "enabled": False,
                    "name": "QUIC-URB-inspired diagnostic urban wind",
                    "note": "Disabled or no building geometry was available.",
                }
            )
            self._last_result = simulate(
                self.network,
                ignition_nodes,
                parameters=parameters,
                horizon_minutes=horizon_minutes,
                wind_field=urban_wind,
            )
            return self._result_payload_unlocked()

    def _model_bounds(self) -> tuple[float, float, float, float]:
        """Return bounds covering the network and available building footprints."""
        points = [(node.x, node.y) for node in self.network.nodes.values()]
        for building in self.buildings_payload.get("buildings", []):
            polygon = building.get("polygon", [])
            points.extend(
                (float(point[0]), float(point[1]))
                for point in polygon
                if isinstance(point, (list, tuple)) and len(point) >= 2
            )
        if not points:
            raise ValueError("cannot build urban wind field without geometry")
        xs, ys = zip(*points)
        return min(xs), max(xs), min(ys), max(ys)

    def _result_payload_unlocked(self) -> dict[str, Any]:
        if self._last_result is None:
            raise RuntimeError("no simulation result is available")
        payload = self._last_result.to_dict()
        payload["dataset"] = self.status()
        payload["burning_buildings"] = self._burning_buildings(self._last_result)
        payload["building_fire_model"] = {
            "description": "Buildings adjacent to an activated road segment or ignition node are highlighted.",
            "proximity_m": 18.0,
        }
        payload["urban_wind"] = dict(self._last_urban_wind)
        return payload

    def flow(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Return a local vector field centered on one selected network node."""
        node_id = str(request.get("node_id", "")).strip()
        if not node_id:
            raise ValueError("node_id is required")
        if node_id not in self.network.nodes:
            raise ValueError(f"unknown node: {node_id}")
        radius_m = float(request.get("radius_m", 2000.0))
        cell_size_m = float(request.get("cell_size_m", 100.0))
        if not 100.0 <= radius_m <= 5000.0:
            raise ValueError("radius_m must be between 100 and 5000")
        if not 25.0 <= cell_size_m <= 500.0:
            raise ValueError("cell_size_m must be between 25 and 500")
        parameters = FireParameters(
            wind_direction_deg=float(request.get("wind_direction_deg", 0.0)),
            wind_speed_mps=float(request.get("wind_speed_mps", 0.0)),
        )
        field = UrbanWindField.from_buildings(
            self.buildings_payload.get("buildings", []),
            self._model_bounds(),
            wind_speed_mps=parameters.wind_speed_mps,
            wind_direction_deg=parameters.wind_direction_deg,
            cell_size_m=cell_size_m,
        )
        center = self.network.nodes[node_id]
        samples: list[dict[str, Any]] = []
        extent = int(math.ceil(radius_m / cell_size_m))
        for grid_y in range(-extent, extent + 1):
            local_y = grid_y * cell_size_m
            for grid_x in range(-extent, extent + 1):
                local_x = grid_x * cell_size_m
                if math.hypot(local_x, local_y) > radius_m:
                    continue
                sample = field.sample(center.x + local_x, center.y + local_y)
                direction_radians = math.radians(sample.direction_deg)
                samples.append(
                    {
                        "x_m": local_x,
                        "y_m": local_y,
                        "speed_mps": sample.speed_mps,
                        "direction_deg": sample.direction_deg,
                        "u_mps": sample.speed_mps * math.cos(direction_radians),
                        "v_mps": sample.speed_mps * math.sin(direction_radians),
                        "obstruction": sample.obstruction,
                        "building_height_m": sample.building_height_m,
                    }
                )
        return {
            "model": field.metadata,
            "node_id": node_id,
            "center": {"x": center.x, "y": center.y},
            "radius_m": radius_m,
            "cell_size_m": cell_size_m,
            "samples": samples,
        }

    def last_result(self) -> dict[str, Any] | None:
        with self._lock:
            return None if self._last_result is None else self._result_payload_unlocked()


class RequestHandler(BaseHTTPRequestHandler):
    service: ScenarioService
    static_dir: Path

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _send_bytes(self, content: bytes, content_type: str, status: int = 200) -> None:
        compressed = False
        if content_type.startswith("application/json") and "gzip" in self.headers.get("Accept-Encoding", ""):
            gzipped = gzip.compress(content, compresslevel=6)
            if len(gzipped) < len(content):
                content = gzipped
                compressed = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        self._send_bytes(
            json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
        elif self.path == "/app.js":
            self._serve_static("app.js", "text/javascript; charset=utf-8")
        elif self.path == "/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
        elif self.path == "/api/status":
            self._send_json(self.service.status())
        elif self.path == "/api/network":
            self._send_json(self.service.network_payload())
        elif self.path == "/api/buildings":
            self._send_json(self.service.buildings_payload_for_web())
        elif self.path == "/api/result":
            result = self.service.last_result()
            self._send_json({"result": result})
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path not in {"/api/simulate", "/api/flow"}:
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            request = self._read_json()
            result = self.service.run(request) if self.path == "/api/simulate" else self.service.flow(request)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        response = {"result": result, "status": self.service.status()}
        if self.path == "/api/flow":
            response = {"flow": result, "status": self.service.status()}
        self._send_json(response)

    def _serve_static(self, filename: str, content_type: str) -> None:
        path = self.static_dir / filename
        try:
            content = path.read_bytes()
        except OSError:
            self._send_json({"error": "web asset unavailable"}, status=500)
            return
        self._send_bytes(content, content_type)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the urban fire spread web UI")
    parser.add_argument(
        "--dataset",
        default="data/processed/manhattan_network.json",
        help="normalized network JSON path",
    )
    parser.add_argument(
        "--buildings",
        default="data/processed/manhattan_buildings.json",
        help="normalized building layer JSON path",
    )
    parser.add_argument("--static-dir", default="web", help="directory containing web assets")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def serve(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    service = ScenarioService(args.dataset, args.buildings)
    handler = type(
        "UrbanFireRequestHandler",
        (RequestHandler,),
        {"service": service, "static_dir": Path(args.static_dir)},
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Urban Fire Spread UI: http://{args.host}:{args.port}")
    print(f"Dataset: {service.dataset_path} ({len(service.network.nodes)} nodes, {len(service.network.edges)} edges)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    finally:
        server.server_close()


def main(argv: Sequence[str] | None = None) -> int:
    serve(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
