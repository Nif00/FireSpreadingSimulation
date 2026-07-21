# Urban Fire Spread

A small, reproducible baseline for simulating an advancing fire front over urban streets and alleyways represented as a graph.

## Status

The repository contains a runnable baseline against a preserved real OpenStreetMap extract for Manhattan Island, New York. The earlier Polatlı extract remains available as a smaller regression dataset:

- validated normalized city-network model;
- 30,935 downloaded OSM highway ways with geometry;
- 147,121 normalized nodes and 161,601 street/alley links;
- 157,202 OSM building/building-part footprints with height provenance for the 3D viewer;
- configurable heuristic spread modifiers;
- deterministic event-driven propagation;
- JSON input/output CLI;
- local web UI with interactive WebGL 3D views, hotspot ranking, and result download;
- contract tests and a small hand-authored network used only for unit tests.

The architecture and staged roadmap are in [`PLAN.md`](PLAN.md). The current model is for exploration and ranking only; it is not a validated fire-behavior or life-safety system.

The current milestone is simulation-first: the real street/alley graph drives propagation. The web UI now includes an explicitly labeled, experimental QUIC-URB-inspired urban-wind layer that rasterizes OSM footprints and heights, then changes local wind speed and direction along graph links. It is a diagnostic approximation, not the QUIC-URB solver.

## Run the sample

From the repository root:

```text
python -m pip install -e .
python -m unittest discover -s tests
python -m fire_spread --network examples/sample_city.json --ignition A --horizon-minutes 20
```

If the package is not installed, set `PYTHONPATH=src` for the module command. On Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m fire_spread --network examples/sample_city.json --ignition A --horizon-minutes 20
```

Write a result file with `--output path/to/result.json`.

## Run the Manhattan dataset

```text
python -m fire_spread --network data/processed/manhattan_network.json --ignition osm:40.7911145:-73.9631218 --horizon-minutes 60 --output data/processed/manhattan_result.json
```

The default web dataset is Manhattan Island. Its study area is `40.7000,-74.0200` to `40.8825,-73.9065`; the normalized origin is the center of that bbox. The current extract contains 147,121 nodes, 161,601 links, and 157,202 building/building-part footprints.

## Run the legacy Polatlı dataset

```text
python -m fire_spread --network data/processed/polatli_network.json --ignition osm:39.5852148:32.1436842 --horizon-minutes 60 --output data/processed/polatli_result.json
```

The legacy dataset's default ignition node is the normalized node nearest the Polatlı town-center origin. The exact graph node ID is reported by the UI and `/api/status`.

The raw Overpass road response is preserved at `data/raw/polatli_osm_roads.json`. The building layer is preserved as direct OSM API XML tiles under `data/raw/polatli_osm_map_tiles/`. Queries, bounding boxes, source, license, coordinate origin, and height policy are recorded in `data/raw/polatli_metadata.json` and `data/raw/polatli_buildings_metadata.json`.

## Run the local web UI

```text
python -m fire_spread.web --dataset data/processed/manhattan_network.json --buildings data/processed/manhattan_buildings.json --host 127.0.0.1 --port 8000
```

On Windows, double-click [`launch_manhattan_ui.bat`](launch_manhattan_ui.bat). It creates `.venv` on the first run, installs the project, starts the server with the Manhattan network and detailed building layer, and opens the browser automatically. Press `Ctrl+C` in the launcher window to stop it. The older launcher now also points at Manhattan for compatibility.

The launcher intentionally prefers the `python` command on `PATH`; `py -3` can select an older installed interpreter even when `python --version` reports 3.11.9.

Open `http://127.0.0.1:8000`. The UI reads the real local graph and building layer, extrudes every OSM footprint into a 3D scene, applies tagged heights and `building:levels` estimates, highlights buildings adjacent to the advancing front in bright red, offers source-only or explicitly labeled 3 m massing fallback heights, applies the optional QUIC-URB-inspired urban-wind grid, and can draw a local flow-vector graph around the selected node. It also shows activated links, ranks advancement scores, and downloads the exact JSON result returned by the simulation.

Map navigation: use the mouse wheel or `E`/`Q` to zoom, drag with the left button to orbit, hold `Shift` while dragging (or use the right mouse button) to pan, use `W`/`A`/`S`/`D` to pan, and use the arrow keys to rotate. The scene has no distance fog; `Reset view` restores the fitted scene.


Vertical exaggeration is a visual control only. It changes how height is displayed, not the stored OSM heights or fire propagation calculations.
## Public data sources

- [OpenStreetMap Overpass API documentation](https://wiki.openstreetmap.org/wiki/Overpass_API)
- [OpenStreetMap API map endpoint](https://api.openstreetmap.org/api/0.6/map)
- [Nominatim API reference](https://nominatim.org/release-docs/latest/api/)
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)

## Input

The normalized JSON contract is documented in [`PLAN.md`](PLAN.md). Coordinates in processed data are local meters, while each normalized node retains its source latitude and longitude in metadata. GeoJSON and other city GIS layers can be added through adapters targeting the same contract.

