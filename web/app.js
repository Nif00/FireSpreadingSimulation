const state = {
  status: null,
  network: null,
  buildings: [],
  result: null,
  edgeElements: new Map(),
  nodeElements: new Map(),
  projection: null,
  heightMode: "source",
  verticalScale: 25,
};

const SCENE_WIDTH = 1000;
const SCENE_HEIGHT = 700;
const $ = (id) => document.getElementById(id);

function setRunState(label, detail = "", progress = 12) {
  $("run-label").textContent = label;
  $("run-detail").textContent = detail;
  $("progress-fill").style.width = `${progress}%`;
}

function escapeText(value) {
  return String(value ?? "—");
}

async function getJson(path) {
  const response = await fetch(path);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
  return payload;
}

function setDatasetMetadata(status) {
  const bbox = status.source?.bbox;
  const bboxText = bbox && typeof bbox === "object"
    ? `${bbox.south}, ${bbox.west} to ${bbox.north}, ${bbox.east}`
    : bbox;
  const heights = status.building_height_sources || {};
  const heightSummary = [
    `${(heights.height_tag || 0).toLocaleString()} tagged`,
    `${(heights.levels_estimate || 0).toLocaleString()} level estimates`,
    `${(heights.footprint_only || 0).toLocaleString()} footprint only`,
  ].join(" / ");
  $("dataset-file").textContent = escapeText(status.dataset);
  $("dataset-nodes").textContent = status.nodes.toLocaleString();
  $("dataset-edges").textContent = status.edges.toLocaleString();
  $("dataset-buildings").textContent = Number(status.buildings || 0).toLocaleString();
  $("dataset-heights").textContent = heightSummary;
  $("dataset-source").textContent = escapeText(status.source?.provider);
  $("dataset-license").textContent = escapeText(status.source?.license);
  $("dataset-bbox").textContent = escapeText(bboxText);
  $("ignition").value = status.default_ignition;
  $("service-state").textContent = `${status.nodes.toLocaleString()} nodes / ${status.edges.toLocaleString()} links / ${Number(status.buildings || 0).toLocaleString()} buildings`;
}

function makeSvgElement(name, attributes) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function effectiveBuildingHeight(building) {
  const sourceHeight = Number(building.height_m) || 0;
  if (sourceHeight > 0) return sourceHeight;
  return state.heightMode === "massing" ? 3 : 0;
}

function createSceneProjection() {
  const yaw = -0.68;
  const pitch = 0.62;
  let minWorldX = Infinity;
  let maxWorldX = -Infinity;
  let minWorldY = Infinity;
  let maxWorldY = -Infinity;
  const includeWorld = (x, y) => {
    minWorldX = Math.min(minWorldX, x);
    maxWorldX = Math.max(maxWorldX, x);
    minWorldY = Math.min(minWorldY, y);
    maxWorldY = Math.max(maxWorldY, y);
  };
  for (const node of state.network.nodes) includeWorld(node.x, node.y);
  for (const building of state.buildings) {
    for (const [x, y] of building.polygon) includeWorld(x, y);
  }
  const worldSpan = Math.max(maxWorldX - minWorldX, maxWorldY - minWorldY, 1);
  const focal = worldSpan * 2.5;
  const mode = $("view-mode").value;
  const rawPoint = (x, y, z) => {
    const scaledZ = z * state.verticalScale;
    const horizontal = Math.cos(yaw) * x - Math.sin(yaw) * y;
    const depthGround = Math.sin(yaw) * x + Math.cos(yaw) * y;
    const vertical = -Math.sin(pitch) * depthGround - Math.cos(pitch) * scaledZ;
    const depth = Math.cos(pitch) * depthGround - Math.sin(pitch) * scaledZ;
    const factor = mode === "perspective" ? focal / (focal + depth) : 1;
    return {x: horizontal * factor, y: vertical * factor, depth};
  };

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  const samples = [];
  const includeSample = (x, y, z) => {
    const sample = rawPoint(x, y, z);
    samples.push(sample);
    minX = Math.min(minX, sample.x);
    maxX = Math.max(maxX, sample.x);
    minY = Math.min(minY, sample.y);
    maxY = Math.max(maxY, sample.y);
  };
  for (const node of state.network.nodes) includeSample(node.x, node.y, 0);
  for (const building of state.buildings) {
    const base = Number(building.min_height_m) || 0;
    const top = Math.max(base, effectiveBuildingHeight(building));
    for (const [x, y] of building.polygon) {
      includeSample(x, y, base);
      includeSample(x, y, top);
    }
  }
  const pad = 30;
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const scale = Math.min((SCENE_WIDTH - 2 * pad) / spanX, (SCENE_HEIGHT - 2 * pad) / spanY);
  const offsetX = pad + (SCENE_WIDTH - 2 * pad - spanX * scale) / 2;
  const offsetY = pad + (SCENE_HEIGHT - 2 * pad - spanY * scale) / 2;
  return (x, y, z = 0) => {
    const raw = rawPoint(x, y, z);
    return {
      x: offsetX + (raw.x - minX) * scale,
      y: SCENE_HEIGHT - (offsetY + (raw.y - minY) * scale),
      depth: raw.depth,
    };
  };
}

function drawBuildings() {
  const canvas = $("building-scene");
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, SCENE_WIDTH, SCENE_HEIGHT);
  if (!state.projection) return;
  const ordered = state.buildings.map((building) => {
    const base = Number(building.min_height_m) || 0;
    const top = Math.max(base, effectiveBuildingHeight(building));
    const basePoints = building.polygon.map(([x, y]) => state.projection(x, y, base));
    const topPoints = building.polygon.map(([x, y]) => state.projection(x, y, top));
    const depth = basePoints.reduce((sum, point) => sum + point.depth, 0) / Math.max(basePoints.length, 1);
    return {building, basePoints, topPoints, top, base, depth};
  }).sort((a, b) => b.depth - a.depth);

  for (const item of ordered) {
    const {building, basePoints, topPoints, top, base} = item;
    const hasHeight = top - base > 0.05;
    context.beginPath();
    basePoints.forEach((point, index) => {
      if (index === 0) context.moveTo(point.x, point.y);
      else context.lineTo(point.x, point.y);
    });
    context.closePath();
    context.fillStyle = hasHeight ? "#d8d3cb" : "#e6e2da";
    context.globalAlpha = hasHeight ? 0.9 : 0.62;
    context.fill();
    context.strokeStyle = "#b5b0a8";
    context.lineWidth = 0.35;
    context.stroke();
    if (hasHeight) {
      for (let index = 0; index < topPoints.length; index += 1) {
        const next = (index + 1) % topPoints.length;
        context.beginPath();
        context.moveTo(basePoints[index].x, basePoints[index].y);
        context.lineTo(basePoints[next].x, basePoints[next].y);
        context.lineTo(topPoints[next].x, topPoints[next].y);
        context.lineTo(topPoints[index].x, topPoints[index].y);
        context.closePath();
        context.fillStyle = building.height_source === "footprint_only" ? "#c6c0b8" : "#b9b3aa";
        context.fill();
        context.stroke();
      }
      context.beginPath();
      topPoints.forEach((point, index) => {
        if (index === 0) context.moveTo(point.x, point.y);
        else context.lineTo(point.x, point.y);
      });
      context.closePath();
      context.fillStyle = building.height_source === "height_tag" ? "#b8b0a5" : "#cec7bd";
      context.fill();
      context.stroke();
    }
  }
  context.globalAlpha = 1;
}

function updateSceneGeometry() {
  if (!state.network) return;
  state.projection = createSceneProjection();
  const nodesById = new Map(state.network.nodes.map((node) => [node.id, node]));
  for (const edge of state.network.edges) {
    const line = state.edgeElements.get(edge.id);
    if (!line) continue;
    const start = state.projection(nodesById.get(edge.start).x, nodesById.get(edge.start).y);
    const end = state.projection(nodesById.get(edge.end).x, nodesById.get(edge.end).y);
    line.setAttribute("x1", start.x);
    line.setAttribute("y1", start.y);
    line.setAttribute("x2", end.x);
    line.setAttribute("y2", end.y);
  }
  for (const node of state.network.nodes) {
    const circle = state.nodeElements.get(node.id);
    if (!circle) continue;
    const point = state.projection(node.x, node.y);
    circle.setAttribute("cx", point.x);
    circle.setAttribute("cy", point.y);
  }
  drawBuildings();
}

function renderNetwork() {
  const svg = $("network-map");
  svg.replaceChildren();
  state.edgeElements.clear();
  state.nodeElements.clear();
  const nodesById = new Map(state.network.nodes.map((node) => [node.id, node]));
  const edgeLayer = makeSvgElement("g", {"aria-hidden": "true"});
  const nodeLayer = makeSvgElement("g", {"aria-label": "network junctions"});
  for (const edge of state.network.edges) {
    const line = makeSvgElement("line", {class: "network-link"});
    edgeLayer.appendChild(line);
    state.edgeElements.set(edge.id, line);
  }
  for (const node of state.network.nodes) {
    const circle = makeSvgElement("circle", {r: 1.5, class: "map-node"});
    circle.setAttribute("tabindex", "0");
    circle.setAttribute("aria-label", `Use node ${node.id} as ignition`);
    const selectNode = () => {
      $("ignition").value = node.id;
      for (const item of state.nodeElements.values()) item.classList.remove("selected");
      circle.classList.add("selected");
      setRunState("Ignition selected.", node.id, state.result ? 100 : 20);
    };
    circle.addEventListener("click", selectNode);
    circle.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") selectNode();
    });
    nodeLayer.appendChild(circle);
    state.nodeElements.set(node.id, circle);
  }
  svg.append(edgeLayer, nodeLayer);
  updateSceneGeometry();
  $("map-message").textContent = "Click a junction to set ignition.";
}

function colorForScore(score) {
  const intensity = Math.max(0, Math.min(1, Number(score) || 0));
  const red = 180 + Math.round(intensity * 55);
  const green = 208 - Math.round(intensity * 150);
  const blue = 197 - Math.round(intensity * 175);
  return `rgb(${red}, ${green}, ${blue})`;
}

function renderResult(result) {
  state.result = result;
  const arrivals = new Map(result.edge_arrivals.map((arrival) => [arrival.edge_id, arrival]));
  for (const [edgeId, line] of state.edgeElements) {
    const arrival = arrivals.get(edgeId);
    line.classList.toggle("active", Boolean(arrival));
    if (arrival) {
      line.style.stroke = colorForScore(result.edge_scores[edgeId]);
      line.style.opacity = "0.95";
    } else {
      line.style.stroke = "#b7b8b2";
      line.style.opacity = "0.55";
    }
  }
  for (const [nodeId, circle] of state.nodeElements) {
    circle.classList.toggle("selected", result.ignition_nodes.includes(nodeId));
  }
  $("reached-nodes").textContent = Object.keys(result.arrival_times).length.toLocaleString();
  $("activated-links").textContent = result.edge_arrivals.length.toLocaleString();
  $("result-horizon").textContent = `${Number(result.horizon_minutes).toFixed(1)} min`;
  const rows = $("hotspot-rows");
  rows.replaceChildren();
  const ranked = [...arrivals.keys()]
    .map((edgeId) => [edgeId, result.edge_scores[edgeId] ?? 0])
    .sort((a, b) => {
      const scoreDifference = Number(b[1]) - Number(a[1]);
      if (scoreDifference !== 0) return scoreDifference;
      return arrivals.get(a[0]).start_minute - arrivals.get(b[0]).start_minute;
    })
    .slice(0, 15);
  if (!ranked.length) {
    rows.innerHTML = '<tr><td colspan="4" class="empty">No links in this result.</td></tr>';
  } else {
    for (const [edgeId, score] of ranked) {
      const arrival = arrivals.get(edgeId);
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${escapeText(edgeId)}</td>
        <td>${(Number(score) * 100).toFixed(1)}%</td>
        <td>${arrival ? `${Number(arrival.start_minute).toFixed(2)} min` : "—"}</td>
        <td>${arrival ? (arrival.complete ? `${Number(arrival.end_minute).toFixed(2)} min` : "partial") : "not reached"}</td>`;
      rows.appendChild(row);
    }
  }
  $("download-result").disabled = false;
  setRunState("Scenario complete.", `${Object.keys(result.arrival_times).length.toLocaleString()} nodes reached`, 100);
}

async function runScenario(event) {
  event.preventDefault();
  const button = $("run-simulation");
  button.disabled = true;
  setRunState("Running simulation…", "computing network arrivals", 55);
  const body = {
    ignition: $("ignition").value.trim(),
    horizon_minutes: Number($("horizon").value),
    base_rate_m_per_min: Number($("base-rate").value),
    wind_direction_deg: Number($("wind-direction").value),
    wind_speed_mps: Number($("wind-speed").value),
    moisture: Number($("moisture").value),
  };
  try {
    const response = await fetch("/api/simulate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Simulation failed");
    renderResult(payload.result);
  } catch (error) {
    setRunState("Simulation failed.", error.message, 12);
  } finally {
    button.disabled = false;
  }
}

function downloadResult() {
  if (!state.result) return;
  const blob = new Blob([JSON.stringify(state.result, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "polatli-fire-spread-result.json";
  link.click();
  URL.revokeObjectURL(url);
}

function setSceneMode() {
  state.heightMode = $("height-mode").value;
  state.verticalScale = Number($("vertical-scale").value);
  updateSceneGeometry();
  const mode = $("view-mode").value;
  const heightText = state.heightMode === "massing" ? "3 m fallback enabled" : "source heights only";
  $("scene-summary").textContent = `${mode} / ${state.verticalScale}× vertical / ${heightText} / ${Number(state.status?.buildings || 0).toLocaleString()} footprints`;
}

async function initialize() {
  try {
    setRunState("Loading dataset.", "reading local network and buildings", 24);
    const [status, network, buildings] = await Promise.all([
      getJson("/api/status"),
      getJson("/api/network"),
      getJson("/api/buildings"),
    ]);
    state.status = status;
    state.network = network;
    state.buildings = buildings.buildings || [];
    setDatasetMetadata(status);
    renderNetwork();
    setSceneMode();
    setRunState("Ready.", "select ignition and run", 35);
  } catch (error) {
    setRunState("Dataset unavailable.", error.message, 12);
    $("map-message").textContent = "Could not load network or building geometry.";
  }
}

$("scenario-form").addEventListener("submit", runScenario);
$("use-center").addEventListener("click", () => {
  if (state.status) $("ignition").value = state.status.default_ignition;
});
$("view-mode").addEventListener("change", setSceneMode);
$("height-mode").addEventListener("change", setSceneMode);
$("vertical-scale").addEventListener("change", setSceneMode);
$("download-result").addEventListener("click", downloadResult);
initialize();
