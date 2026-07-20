"""Small local web UI server for real network scenarios."""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence

from .io import load_network
from .models import CityNetwork
from .propagation import FireParameters, SimulationResult, simulate


class ScenarioService:
    """Owns one loaded dataset and executes real simulations against it."""

    def __init__(self, dataset_path: str | Path, buildings_path: str | Path | None = None) -> None:
        self.dataset_path = Path(dataset_path)
        self.network = load_network(self.dataset_path)
        payload = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        self.source = payload.get("source", {})
        self.buildings_path = Path(buildings_path) if buildings_path else None
        self.buildings_payload = self._load_buildings()
        self.default_ignition = min(
            self.network.nodes,
            key=lambda node_id: (
                self.network.nodes[node_id].x**2 + self.network.nodes[node_id].y**2,
                node_id,
            ),
        )
        self._lock = threading.Lock()
        self._last_result: SimulationResult | None = None

    def _load_buildings(self) -> dict[str, Any]:
        if self.buildings_path is None or not self.buildings_path.exists():
            return {"buildings": [], "source": {}}
        payload = json.loads(self.buildings_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("buildings"), list):
            raise ValueError("building dataset must contain a buildings list")
        return payload

    def status(self) -> dict[str, Any]:
        building_source = self.buildings_payload.get("source", {})
        return {
            "dataset": self.dataset_path.name,
            "nodes": len(self.network.nodes),
            "edges": len(self.network.edges),
            "default_ignition": self.default_ignition,
            "source": dict(self.source),
            "buildings": len(self.buildings_payload.get("buildings", [])),
            "building_height_sources": dict(building_source.get("height_source_counts", {})),
            "buildings_dataset": self.buildings_path.name if self.buildings_path else None,
        }

    def network_payload(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": node.id, "x": node.x, "y": node.y}
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
        with self._lock:
            self._last_result = simulate(
                self.network,
                ignition_nodes,
                parameters=parameters,
                horizon_minutes=horizon_minutes,
            )
            return self._result_payload_unlocked()

    def _result_payload_unlocked(self) -> dict[str, Any]:
        if self._last_result is None:
            raise RuntimeError("no simulation result is available")
        payload = self._last_result.to_dict()
        payload["dataset"] = self.status()
        return payload

    def last_result(self) -> dict[str, Any] | None:
        with self._lock:
            return None if self._last_result is None else self._result_payload_unlocked()


class RequestHandler(BaseHTTPRequestHandler):
    service: ScenarioService
    static_dir: Path

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _send_bytes(self, content: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
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
        if self.path != "/api/simulate":
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            result = self.service.run(self._read_json())
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"result": result, "status": self.service.status()})

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
        default="data/processed/polatli_network.json",
        help="normalized network JSON path",
    )
    parser.add_argument(
        "--buildings",
        default="data/processed/polatli_buildings.json",
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
