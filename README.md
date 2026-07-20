# Urban Fire Spread

A small, reproducible baseline for simulating an advancing fire front over urban streets and alleyways represented as a graph.

## Status

The repository contains a runnable baseline against a preserved real OpenStreetMap extract for Polatlı, Ankara:

- validated normalized city-network model;
- 1,837 downloaded OSM highway ways with geometry;
- 12,266 normalized nodes and 13,920 street/alley links;
- 12,151 OSM building/building-part footprints for the 2.5D viewer;
- configurable heuristic spread modifiers;
- deterministic event-driven propagation;
- JSON input/output CLI;
- local web UI with orthographic/perspective 2.5D views, hotspot ranking, and result download;
- contract tests and a small hand-authored network used only for unit tests.

The architecture and staged roadmap are in [`PLAN.md`](PLAN.md). The current model is for exploration and ranking only; it is not a validated fire-behavior or life-safety system.

The current milestone is simulation-first: the real street/alley graph drives propagation. OSM building footprints and height tags are currently presentation-only and do not alter spread calculations.

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

## Run the real Polatlı dataset

```text
python -m fire_spread --network data/processed/polatli_network.json --ignition osm:39.5852148:32.1436842 --horizon-minutes 60 --output data/processed/polatli_result.json
```

The default ignition node used by the web UI is the normalized node nearest the Polatlı town-center origin. The exact graph node ID is reported by the UI and `/api/status`.

The raw Overpass road response is preserved at `data/raw/polatli_osm_roads.json`. The building layer is preserved as direct OSM API XML tiles under `data/raw/polatli_osm_map_tiles/`. Queries, bounding boxes, source, license, coordinate origin, and height policy are recorded in `data/raw/polatli_metadata.json` and `data/raw/polatli_buildings_metadata.json`.

## Run the local web UI

```text
python -m fire_spread.web --dataset data/processed/polatli_network.json --buildings data/processed/polatli_buildings.json --host 127.0.0.1 --port 8000
```

On Windows, double-click [`launch_polatli_ui.bat`](launch_polatli_ui.bat). It creates `.venv` on the first run, installs the project, starts the server with the real Polatlı network and building layer, and opens the browser automatically. Press `Ctrl+C` in the launcher window to stop it.

Open `http://127.0.0.1:8000`. The UI reads the real local graph and building layer, allows a node ignition and parameterized run, supports orthographic and perspective projections, offers source-only or explicitly labeled 3 m massing fallback heights, shows activated links, ranks advancement scores, and downloads the exact JSON result returned by the simulation.


Vertical exaggeration is a visual control only. It changes how height is displayed, not the stored OSM heights or fire propagation calculations.
## Public data sources

- [OpenStreetMap Overpass API documentation](https://wiki.openstreetmap.org/wiki/Overpass_API)
- [OpenStreetMap API map endpoint](https://api.openstreetmap.org/api/0.6/map)
- [Nominatim API reference](https://nominatim.org/release-docs/latest/api/)
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)

## Input

The normalized JSON contract is documented in [`PLAN.md`](PLAN.md). Coordinates in processed data are local meters, while each normalized node retains its source latitude and longitude in metadata. GeoJSON and other city GIS layers can be added through adapters targeting the same contract.

