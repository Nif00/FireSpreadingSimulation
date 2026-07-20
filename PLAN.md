# Urban Fire Propagation Simulator

## Objective

Use city street and alleyway data to estimate how an advancing fire front can move through a connected urban network, then identify links and places where the front advances quickly or concentrates.

This first slice establishes a reproducible graph-based simulation. It is a planning and engineering baseline, not a fire-behavior or evacuation-safety model.

## Decisions for the first vertical slice

- **Language:** Python 3.11+.
- **Core representation:** a directed-capable graph of street/alley nodes and links. Fire spread uses physical connectivity; links are bidirectional unless the input explicitly marks them otherwise.
- **Input boundary:** accept a normalized JSON network and a real Overpass/OpenStreetMap adapter. The propagation core stays independent of source format.
- **Simulation method:** event-driven earliest-arrival propagation over the network. Each reached node schedules its neighboring links on a priority queue.
- **Baseline behavior model:** link travel time is derived from length and explicit heuristic modifiers for wind alignment, slope, width, surface, and moisture. All modifiers are configuration, not hidden constants.
- **Outputs:** node arrival times, traversed-link arrival intervals, and a normalized link advancement score so hotspots can be mapped or ranked later.
- **Reproducibility:** deterministic inputs, parameters, and tie-breaking; no random ignition or stochastic spread in this slice.

## System shape

```text
city data -> ingestion/normalization -> CityNetwork -> propagation engine
                                                  -> SimulationResult
SimulationResult -> ranked hotspots / downloadable JSON / restrained local web UI
```

### Planned modules

- `fire_spread.models`: immutable domain types and graph validation.
- `fire_spread.io`: normalized JSON loading.
- `fire_spread.osm`: converts real Overpass road ways into projected graph segments while preserving OSM tags and provenance.
- `fire_spread.buildings`: converts preserved direct OSM XML map tiles into projected building footprints and height-confidence records.
- `fire_spread.propagation`: configurable edge traversal and event-driven spread.
- `fire_spread.cli`: a small command-line entry point for repeatable runs.
- `fire_spread.web`: local HTTP API and small static UI for scenario controls, network view, 2.5D building rendering, and hotspot output.
- `tests`: contract tests for graph validation, directional links, modifiers, horizon handling, deterministic results, OSM conversion, and building provenance.
- `data/raw`: preserved source city files and provenance records.
- `data/processed`: normalized network artifacts and derived simulation outputs.
- `examples`: a tiny hand-authored network for unit tests; real Polatlı data is stored separately.

## Normalized network contract (v1)

```json
{
  "nodes": [
    {"id": "A", "x": 0, "y": 0, "kind": "intersection"}
  ],
  "edges": [
    {
      "id": "A-B",
      "start": "A",
      "end": "B",
      "length_m": 40,
      "width_m": 5,
      "surface": "paved",
      "slope": 0,
      "bidirectional": true
    }
  ]
}
```

Coordinates are projected/local meters in normalized data. The Polatlı adapter uses a local equirectangular projection centered on the Nominatim town-relation result, with the source WGS84 coordinates retained in node metadata.

## Real starting dataset: Polatlı, Ankara

- Source: OpenStreetMap road geometry retrieved from the public Overpass API.
- Coverage: `39.54,32.08` to `39.63,32.22`, covering the Polatlı urban area and immediate outskirts rather than the full administrative district.
- Filter: motorways, trunks, primary/secondary/tertiary roads, unclassified/residential/living streets, service roads, tracks, and pedestrian links.
- Retrieved elements: 1,837 OSM highway ways, all with geometry.
- Normalized graph: 12,266 nodes and 13,920 links after splitting way geometry into segments and preserving one-way tags.
- Building layer: 12,151 OSM building/building-part footprints from direct OSM API XML tiles. Only 7 carry explicit `height`, 6 carry `building:levels`, and 12,138 are footprint-only.
- Files: `data/raw/polatli_osm_roads.json`, `data/raw/polatli_metadata.json`, `data/raw/polatli_buildings_metadata.json`, `data/raw/polatli_osm_map_tiles/`, `data/processed/polatli_network.json`, and `data/processed/polatli_buildings.json`.
- License: OpenStreetMap data © OpenStreetMap contributors, ODbL 1.0. Source URLs, tile coverage, and height policy are preserved in the metadata files and normalized outputs.

## Current boundary decision

The street graph remains the only spatial input to fire propagation. The OSM building layer is currently presentation-only: it drives the 2.5D viewer but does not alter spread speed, connectivity, or hotspot scores.

The viewer exposes orthographic and perspective projections plus a clearly labeled vertical exaggeration control. Unknown building heights remain flat in source-only mode; the optional 3 m massing fallback is a visualization assumption, not a measured height.

## Simulation phases

1. **Baseline graph:** load and validate a normalized network; reject missing endpoints, duplicate IDs, non-positive lengths, and invalid parameter ranges.
2. **Deterministic propagation:** simulate one or more ignition nodes over a finite time horizon; preserve earliest arrival per node and link interval.
3. **Hotspot ranking:** rank links by normalized advancement score and nodes by arrival/exposure metrics.
4. **City ingestion:** retrieve and preserve the Polatlı OSM extract, reproject to local meters, split ways at geometry vertices, preserve one-way/surface/width tags, and validate topology.
5. **Current web UI:** run real scenarios against the Polatlı graph, show the full network and activated links, and allow JSON result download.
6. **Calibration:** compare modeled travel times and spread patterns against historical incidents or expert-labelled scenarios; keep calibrated coefficients versioned.
7. **Scenario analysis:** support multiple ignitions, barriers/closures, time-varying wind, fuel/moisture rasters, and repeated stochastic runs only when validated data exists. Building footprints and 3D tags may become simulation inputs only after their effect is specified and validated.
8. **Presentation:** export GeoJSON and extend the current map view with a timestamp slider and richer city layers after the baseline is validated.

## Risks and guardrails

- This heuristic model must not be used for life-safety decisions without validation by fire-science and emergency-management specialists.
- Street connectivity is not equivalent to fire access: building setbacks, wind eddies, fuel continuity, hydrants, walls, and suppression response are future data layers.
- The model should report assumptions and input provenance with every output.
- Geographic CRS errors can make distances and wind bearings meaningless; ingestion must fail loudly when units are ambiguous.
- A single deterministic run can hide uncertainty; uncertainty bounds and sensitivity analysis belong after the baseline is measurable.

## Definition of done for the current baseline

- The preserved Polatlı OSM road and building extracts load from disk through source-specific adapters.
- A normalized Polatlı graph and building layer are available with provenance, local-meter coordinates, and height-source labels.
- A CLI and local web UI run real propagation scenarios against the road graph.
- The UI offers orthographic and perspective 2.5D views without feeding unvalidated building heights into propagation.
- Outputs include arrival times, activated links, ranked advancement scores, and dataset/scenario provenance.
- Tests cover the observable baseline contracts, OSM conversion, and building conversion boundaries.
