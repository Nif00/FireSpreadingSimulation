"""Command-line interface for repeatable propagation scenarios."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .io import dump_json, load_network
from .propagation import FireParameters, simulate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", required=True, help="normalized network JSON path")
    parser.add_argument(
        "--ignition",
        action="append",
        required=True,
        help="node ID where the front starts; repeat for multiple ignitions",
    )
    parser.add_argument("--horizon-minutes", type=float, default=60.0)
    parser.add_argument("--base-rate-m-per-min", type=float, default=30.0)
    parser.add_argument("--wind-direction-deg", type=float, default=0.0)
    parser.add_argument("--wind-speed-mps", type=float, default=0.0)
    parser.add_argument("--moisture", type=float, default=0.0)
    parser.add_argument("--output", help="optional JSON output path; stdout by default")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        network_path = Path(args.network)
        network = load_network(network_path)
        network_payload = json.loads(network_path.read_text(encoding="utf-8"))
        result = simulate(
            network,
            args.ignition,
            parameters=FireParameters(
                base_rate_m_per_min=args.base_rate_m_per_min,
                wind_direction_deg=args.wind_direction_deg,
                wind_speed_mps=args.wind_speed_mps,
                moisture=args.moisture,
            ),
            horizon_minutes=args.horizon_minutes,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    payload = result.to_dict()
    payload["dataset"] = {
        "path": str(network_path),
        "source": network_payload.get("source", {}),
    }
    if args.output:
        try:
            dump_json(payload, args.output)
        except OSError as exc:
            print(f"error: cannot write {args.output}: {exc}", file=sys.stderr)
            return 2
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0
