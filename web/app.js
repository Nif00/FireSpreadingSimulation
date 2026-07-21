const state = {
  status: null,
  network: null,
  buildings: [],
  result: null,
  scene: null,
  renderer: null,
  cameras: {},
  activeCamera: null,
  world: null,
  buildingMesh: null,
  roadLines: null,
  fireLines: null,
  flowLines: null,
  flowBoundary: null,
  nodePoints: null,
  selectedNodePoints: null,
  selectedNodePin: null,
  selectedNode: null,
  ignitionPoints: null,
  grid: null,
  bounds: null,
  burningBuildingIds: new Set(),
  heightMode: "massing",
  verticalScale: 25,
  camera: {
    yaw: -0.68,
    pitch: 0.7,
    radius: 6000,
    targetX: 0,
    targetZ: 0,
  },
  gesture: null,
  suppressClick: false,
};

const $ = (id) => document.getElementById(id);
const THREE = window.THREE;
const MIN_CAMERA_RADIUS = 25;
const MAX_CAMERA_RADIUS = 100000;

function setRunState(label, detail = "", progress = 12) {
  $("run-label").textContent = label;
  $("run-detail").textContent = detail;
  $("progress-fill").style.width = `${progress}%`;
}

function focusSceneCanvas() {
  const canvas = $("building-scene");
  if (canvas) canvas.focus({preventScroll: true});
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
  $("terrain-status").textContent = status.elevation_nodes
    ? `${Number(status.elevation_nodes).toLocaleString()} OSM elevation points`
    : "No OSM terrain elevations in source";
  $("wind-model-status").textContent = "QUIC-URB-inspired (experimental)";
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function colorForScore(score) {
  const intensity = Math.max(0, Math.min(1, Number(score) || 0));
  const red = 180 + Math.round(intensity * 55);
  const green = 208 - Math.round(intensity * 150);
  const blue = 197 - Math.round(intensity * 175);
  return new THREE.Color(red / 255, green / 255, blue / 255);
}

function makeLineGeometry(segments) {
  const positions = new Float32Array(segments.length * 6);
  segments.forEach((segment, index) => {
    positions.set(segment, index * 6);
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  return geometry;
}

function networkNode(nodeId) {
  return state.network.nodes.find((node) => node.id === nodeId);
}

function buildingHeight(building) {
  const sourceHeight = Math.max(0, Number(building.height_m) || 0);
  const base = Math.max(0, Number(building.min_height_m) || 0);
  const fallback = state.heightMode === "massing" && sourceHeight <= base ? 3 : sourceHeight;
  return Math.max(base, fallback);
}

function buildingColors(building, side = false) {
  if (state.burningBuildingIds.has(building.id)) {
    return side ? new THREE.Color(0xb51218) : new THREE.Color(0xff2b2b);
  }
  if (building.height_source === "height_tag") {
    return side ? new THREE.Color(0x9d8d7e) : new THREE.Color(0xd1bca8);
  }
  if (building.height_source === "levels_estimate") {
    return side ? new THREE.Color(0x897f73) : new THREE.Color(0xbeb2a2);
  }
  return side ? new THREE.Color(0x626a68) : new THREE.Color(0x919c98);
}

function addVertex(positions, colors, point, color) {
  const index = positions.length / 3;
  positions.push(point.x, point.y, point.z);
  colors.push(color.r, color.g, color.b);
  return index;
}

function createBuildingMesh() {
  if (state.buildingMesh) {
    state.world.remove(state.buildingMesh);
    state.buildingMesh.geometry.dispose();
    state.buildingMesh.material.dispose();
  }
  const positions = [];
  const colors = [];
  const indices = [];
  for (const building of state.buildings) {
    const polygon = Array.isArray(building.polygon) ? building.polygon : [];
    if (polygon.length < 3) continue;
    const base = Math.max(0, Number(building.min_height_m) || 0);
    const top = buildingHeight(building);
    const topColor = buildingColors(building, false);
    const sideColor = buildingColors(building, true);
    const points = polygon.map(([x, y]) => ({x: Number(x), y: top, z: -Number(y)}));
    const basePoints = polygon.map(([x, y]) => ({x: Number(x), y: base, z: -Number(y)}));

    const topIndices = points.map((point) => addVertex(positions, colors, point, topColor));
    const baseIndices = basePoints.map((point) => addVertex(positions, colors, point, sideColor));
    for (let index = 1; index < topIndices.length - 1; index += 1) {
      indices.push(topIndices[0], topIndices[index], topIndices[index + 1]);
    }
    for (let index = 0; index < points.length; index += 1) {
      const next = (index + 1) % points.length;
      indices.push(
        baseIndices[index], baseIndices[next], topIndices[next],
        baseIndices[index], topIndices[next], topIndices[index],
      );
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.88,
    metalness: 0.02,
    side: THREE.DoubleSide,
  });
  state.buildingMesh = new THREE.Mesh(geometry, material);
  state.world.add(state.buildingMesh);
}

function createRoadLines() {
  if (state.roadLines) {
    state.world.remove(state.roadLines);
    state.roadLines.geometry.dispose();
    state.roadLines.material.dispose();
  }
  const nodesById = new Map(state.network.nodes.map((node) => [node.id, node]));
  const segments = [];
  for (const edge of state.network.edges) {
    const start = nodesById.get(edge.start);
    const end = nodesById.get(edge.end);
    if (!start || !end) continue;
    segments.push([start.x, 0.35, -start.y, end.x, 0.35, -end.y]);
  }
  state.roadLines = new THREE.LineSegments(
    makeLineGeometry(segments),
    new THREE.LineBasicMaterial({color: 0x8f9996, transparent: true, opacity: 0.7}),
  );
  state.world.add(state.roadLines);
}

function createNodePoints() {
  if (state.nodePoints) {
    state.world.remove(state.nodePoints);
    state.nodePoints.geometry.dispose();
    state.nodePoints.material.dispose();
  }
  const positions = new Float32Array(state.network.nodes.length * 3);
  state.network.nodes.forEach((node, index) => {
    positions.set([node.x, 0.7, -node.y], index * 3);
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  state.nodePoints = new THREE.Points(
    geometry,
    new THREE.PointsMaterial({color: 0xd7e2df, size: 6, sizeAttenuation: true, transparent: true, opacity: 0.92}),
  );
  state.nodePoints.userData.nodeIds = state.network.nodes.map((node) => node.id);
  state.world.add(state.nodePoints);
}

function setSelectedNode(nodeId) {
  const node = networkNode(nodeId);
  if (!node) return;
  state.selectedNode = node;
  clearFlowField();
  if (state.selectedNodePoints) {
    state.world.remove(state.selectedNodePoints);
    state.selectedNodePoints.geometry.dispose();
    state.selectedNodePoints.material.dispose();
  }
  if (state.selectedNodePin) {
    state.world.remove(state.selectedNodePin);
    state.selectedNodePin.geometry.dispose();
    state.selectedNodePin.material.dispose();
  }
  const markerGeometry = new THREE.BufferGeometry();
  markerGeometry.setAttribute("position", new THREE.Float32BufferAttribute([node.x, 0.9, -node.y], 3));
  state.selectedNodePoints = new THREE.Points(
    markerGeometry,
    new THREE.PointsMaterial({color: 0xffd166, size: 20, sizeAttenuation: true}),
  );
  const pinGeometry = makeLineGeometry([[node.x, 0.05, -node.y, node.x, 0.9, -node.y]]);
  state.selectedNodePin = new THREE.Line(
    pinGeometry,
    new THREE.LineBasicMaterial({color: 0xffd166, transparent: true, opacity: 0.9}),
  );
  state.world.add(state.selectedNodePin, state.selectedNodePoints);
  const metadata = node.metadata || {};
  const coordinates = Number.isFinite(Number(metadata.latitude)) && Number.isFinite(Number(metadata.longitude))
    ? ` / ${Number(metadata.latitude).toFixed(6)}, ${Number(metadata.longitude).toFixed(6)}`
    : "";
  const elevation = node.elevation_m == null ? "" : ` / ele ${Number(node.elevation_m).toFixed(1)} m`;
  $("node-selection").textContent = `Selected ${node.id}${coordinates}${elevation}`;
  $("selected-node-pin").classList.remove("is-hidden");
  $("selected-node-pin").querySelector(".selected-node-label").textContent = `SELECTED · ${node.id}`;
  $("run-flow").disabled = false;
  $("flow-status").textContent = `Selected ${node.id}; ready to run flow`;
  $("ignition").value = node.id;
  setRunState("Ignition selected.", node.id, state.result ? 100 : 20);
  updateSelectedNodeOverlay();
}

function clearFlowField() {
  for (const key of ["flowLines", "flowBoundary"]) {
    const object = state[key];
    if (!object) continue;
    state.world.remove(object);
    object.geometry.dispose();
    object.material.dispose();
    state[key] = null;
  }
}

function updateSelectedNodeOverlay() {
  const overlay = $("selected-node-pin");
  if (!overlay || !state.selectedNode || !state.activeCamera || !state.world) return;
  const rect = $("building-scene").getBoundingClientRect();
  const projected = new THREE.Vector3(state.selectedNode.x, 0.8, -state.selectedNode.y);
  state.world.localToWorld(projected);
  projected.project(state.activeCamera);
  const visible = projected.z >= -1 && projected.z <= 1;
  if (!visible) {
    overlay.classList.add("is-hidden");
    return;
  }
  overlay.classList.remove("is-hidden");
  overlay.style.left = `${(projected.x * 0.5 + 0.5) * rect.width}px`;
  overlay.style.top = `${(-projected.y * 0.5 + 0.5) * rect.height}px`;
}

function createGround() {
  if (state.grid) {
    state.world.remove(state.grid);
    state.grid.geometry.dispose();
    state.grid.material.dispose();
  }
  const size = Math.max(state.bounds.spanX, state.bounds.spanY) * 1.12;
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(size, size),
    new THREE.MeshStandardMaterial({color: 0x25302f, roughness: 1, metalness: 0}),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(state.bounds.centerX, -0.2, -state.bounds.centerY);
  state.world.add(ground);
  state.grid = new THREE.GridHelper(size, 36, 0x52615d, 0x35403e);
  state.grid.position.set(state.bounds.centerX, -0.16, -state.bounds.centerY);
  state.world.add(state.grid);
}

function createScene() {
  if (!THREE) throw new Error("Three.js failed to load");
  const canvas = $("building-scene");
  state.renderer = new THREE.WebGLRenderer({canvas, antialias: true, logarithmicDepthBuffer: true});
  state.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  state.renderer.setClearColor(0x141b1b, 1);
  state.renderer.outputColorSpace = THREE.SRGBColorSpace;
  state.scene = new THREE.Scene();
  // The study area is already large; distance fog hides the far side of the city.
  state.scene.fog = null;
  state.world = new THREE.Group();
  state.scene.add(state.world);
  state.scene.add(new THREE.HemisphereLight(0xc6d4d0, 0x121817, 2.1));
  const sun = new THREE.DirectionalLight(0xffe5c7, 2.4);
  sun.position.set(-900, 1600, 1100);
  state.scene.add(sun);
  state.cameras.perspective = new THREE.PerspectiveCamera(48, 1, 0.5, 250000);
  state.cameras.orthographic = new THREE.OrthographicCamera(-1000, 1000, 700, -700, 0.5, 250000);
  state.activeCamera = state.cameras.perspective;
  canvas.addEventListener("pointerdown", beginSceneGesture);
  canvas.addEventListener("pointermove", moveSceneGesture);
  canvas.addEventListener("pointerup", endSceneGesture);
  canvas.addEventListener("pointercancel", endSceneGesture);
  canvas.addEventListener("wheel", zoomScene, {passive: false});
  canvas.addEventListener("click", selectNodeAtPointer);
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  window.addEventListener("keydown", handleSceneKeydown);
  window.addEventListener("resize", resizeScene);
  resizeScene();
  requestAnimationFrame(renderFrame);
}

function calculateBounds() {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  const include = (x, y) => {
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  };
  for (const node of state.network.nodes) include(Number(node.x), Number(node.y));
  for (const building of state.buildings) {
    for (const [x, y] of building.polygon || []) include(Number(x), Number(y));
  }
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  state.bounds = {
    minX, maxX, minY, maxY, spanX, spanY,
    centerX: (minX + maxX) / 2,
    centerY: (minY + maxY) / 2,
    span: Math.max(spanX, spanY),
  };
  state.camera.targetX = state.bounds.centerX;
  state.camera.targetZ = -state.bounds.centerY;
  state.camera.radius = clamp(state.bounds.span * 1.25, MIN_CAMERA_RADIUS, MAX_CAMERA_RADIUS);
}

function updateCamera() {
  const {yaw, pitch, radius, targetX, targetZ} = state.camera;
  const target = new THREE.Vector3(targetX, 0, targetZ);
  const horizontal = Math.cos(pitch) * radius;
  const position = new THREE.Vector3(
    targetX + Math.sin(yaw) * horizontal,
    Math.sin(pitch) * radius,
    targetZ + Math.cos(yaw) * horizontal,
  );
  for (const camera of Object.values(state.cameras)) {
    camera.position.copy(position);
    camera.lookAt(target);
  }
  const aspect = Math.max(1, $("building-scene").clientWidth / Math.max(1, $("building-scene").clientHeight));
  state.cameras.perspective.aspect = aspect;
  state.cameras.perspective.updateProjectionMatrix();
  const viewHeight = Math.max(100, radius * 0.9);
  state.cameras.orthographic.left = -viewHeight * aspect;
  state.cameras.orthographic.right = viewHeight * aspect;
  state.cameras.orthographic.top = viewHeight;
  state.cameras.orthographic.bottom = -viewHeight;
  state.cameras.orthographic.updateProjectionMatrix();
}

function resizeScene() {
  if (!state.renderer) return;
  const canvas = $("building-scene");
  const width = Math.max(1, canvas.clientWidth);
  const height = Math.max(1, canvas.clientHeight);
  state.renderer.setSize(width, height, false);
  updateCamera();
}

function renderFrame() {
  if (state.renderer && state.scene && state.activeCamera) state.renderer.render(state.scene, state.activeCamera);
  updateSelectedNodeOverlay();
  requestAnimationFrame(renderFrame);
}

function updateWorldScale() {
  if (!state.world) return;
  state.world.scale.y = state.verticalScale;
  updateCamera();
}

function renderNetwork() {
  calculateBounds();
  createGround();
  createBuildingMesh();
  createRoadLines();
  createNodePoints();
  createFireLines([]);
  createIgnitionPoints([]);
  updateWorldScale();
  $("map-message").textContent = "Click a junction to set ignition. WASD pan · arrows rotate · E/Q zoom.";
}

function renderFlowField(flow) {
  clearFlowField();
  const center = flow.center;
  const samples = flow.samples || [];
  const cellSize = Number(flow.cell_size_m) || 50;
  const radius = Number(flow.radius_m) || 1;
  const maxSpeed = Math.max(...samples.map((sample) => Number(sample.speed_mps) || 0), 0);
  const sampleGrid = new Map(
    samples.map((sample) => [`${Math.round(Number(sample.x_m) / cellSize)}:${Math.round(Number(sample.y_m) / cellSize)}`, sample]),
  );
  const sampleAt = (x, y) => {
    if (Math.hypot(x, y) > radius) return null;
    return sampleGrid.get(`${Math.round(x / cellSize)}:${Math.round(y / cellSize)}`) || null;
  };
  const trace = (seedX, seedY, direction) => {
    const points = [];
    let x = seedX;
    let y = seedY;
    const stepSize = cellSize * 0.62;
    const maxSteps = Math.min(100, Math.ceil(radius / stepSize) * 2 + 6);
    for (let step = 0; step < maxSteps; step += 1) {
      const sample = sampleAt(x, y);
      if (!sample || Number(sample.speed_mps) <= 0.001) break;
      points.push({x, y, sample});
      const speed = Number(sample.speed_mps);
      x += direction * Number(sample.u_mps) / speed * stepSize;
      y += direction * Number(sample.v_mps) / speed * stepSize;
    }
    return points;
  };
  const positions = [];
  const colors = [];
  const addSegment = (x1, z1, x2, z2, color) => {
    positions.push(x1, 4.0, z1, x2, 4.0, z2);
    colors.push(color.r, color.g, color.b, color.r, color.g, color.b);
  };
  const seedSpacing = cellSize * 3;
  let streamlineCount = 0;
  for (let seedY = -radius + cellSize; seedY <= radius - cellSize; seedY += seedSpacing) {
    for (let seedX = -radius + cellSize; seedX <= radius - cellSize; seedX += seedSpacing) {
      if (Math.hypot(seedX, seedY) > radius) continue;
      const backwards = trace(seedX, seedY, -1).reverse();
      const forwards = trace(seedX, seedY, 1);
      const path = backwards.concat(forwards.slice(1));
      if (path.length < 2) continue;
      streamlineCount += 1;
      for (let index = 1; index < path.length; index += 1) {
        const previous = path[index - 1];
        const current = path[index];
        const speed = Number(current.sample.speed_mps) || 0;
        const intensity = maxSpeed ? speed / maxSpeed : 0;
        const color = new THREE.Color().setHSL(0.53 - 0.12 * intensity, 0.82, 0.43 + 0.15 * intensity);
        addSegment(
          Number(center.x) + previous.x,
          -(Number(center.y) + previous.y),
          Number(center.x) + current.x,
          -(Number(center.y) + current.y),
          color,
        );
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  state.flowLines = new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({vertexColors: true, transparent: true, opacity: 0.92, depthTest: false}),
  );
  state.world.add(state.flowLines);

  const boundaryPoints = [];
  for (let index = 0; index < 64; index += 1) {
    const a = index / 64 * Math.PI * 2;
    const b = (index + 1) / 64 * Math.PI * 2;
    boundaryPoints.push(
      Number(center.x) + Math.cos(a) * radius, 2.8, -(Number(center.y) + Math.sin(a) * radius),
      Number(center.x) + Math.cos(b) * radius, 2.8, -(Number(center.y) + Math.sin(b) * radius),
    );
  }
  const boundaryGeometry = new THREE.BufferGeometry();
  boundaryGeometry.setAttribute("position", new THREE.Float32BufferAttribute(boundaryPoints, 3));
  state.flowBoundary = new THREE.LineSegments(
    boundaryGeometry,
    new THREE.LineBasicMaterial({color: 0x167a8a, transparent: true, opacity: 0.6, depthTest: false}),
  );
  state.world.add(state.flowBoundary);
  $("flow-status").textContent = `${flow.node_id}: ${streamlineCount.toLocaleString()} flow lines / ${radius.toFixed(0)} m radius / max ${maxSpeed.toFixed(1)} m/s`;
}

async function runFlowField() {
  if (!state.selectedNode) {
    $("flow-status").textContent = "Select a node first";
    return;
  }
  const button = $("run-flow");
  button.disabled = true;
  $("flow-status").textContent = "Computing local urban flow…";
  const body = {
    node_id: state.selectedNode.id,
    radius_m: Number($("flow-radius").value),
    cell_size_m: Number($("urban-wind-cell").value),
    wind_direction_deg: Number($("wind-direction").value),
    wind_speed_mps: Number($("wind-speed").value),
  };
  try {
    const response = await fetch("/api/flow", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Flow simulation failed");
    renderFlowField(payload.flow);
  } catch (error) {
    $("flow-status").textContent = `Flow failed: ${error.message}`;
  } finally {
    button.disabled = false;
    focusSceneCanvas();
  }
}

function createFireLines(arrivals) {
  if (state.fireLines) {
    state.world.remove(state.fireLines);
    state.fireLines.geometry.dispose();
    state.fireLines.material.dispose();
  }
  const nodesById = new Map(state.network.nodes.map((node) => [node.id, node]));
  const segments = [];
  const colors = [];
  for (const arrival of arrivals) {
    const edge = state.network.edges.find((item) => item.id === arrival.edge_id);
    if (!edge) continue;
    const start = nodesById.get(edge.start);
    const end = nodesById.get(edge.end);
    if (!start || !end) continue;
    segments.push(start.x, 1.7, -start.y, end.x, 1.7, -end.y);
    const color = colorForScore(state.result?.edge_scores?.[edge.id] ?? 0.5);
    colors.push(color.r, color.g, color.b, color.r, color.g, color.b);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(segments, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  state.fireLines = new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({vertexColors: true, transparent: true, opacity: 1}),
  );
  state.world.add(state.fireLines);
}

function createIgnitionPoints(nodeIds) {
  if (state.ignitionPoints) {
    state.world.remove(state.ignitionPoints);
    state.ignitionPoints.geometry.dispose();
    state.ignitionPoints.material.dispose();
  }
  const nodes = nodeIds.map(networkNode).filter(Boolean);
  const positions = new Float32Array(nodes.length * 3);
  nodes.forEach((node, index) => positions.set([node.x, 3.2, -node.y], index * 3));
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  state.ignitionPoints = new THREE.Points(
    geometry,
    new THREE.PointsMaterial({color: 0xff6b46, size: 13, sizeAttenuation: true}),
  );
  state.world.add(state.ignitionPoints);
}

function renderResult(result) {
  state.result = result;
  state.burningBuildingIds = new Set(
    (result.burning_buildings || []).map((building) => building.building_id),
  );
  createBuildingMesh();
  createFireLines(result.edge_arrivals || []);
  createIgnitionPoints(result.ignition_nodes || []);
  $("reached-nodes").textContent = Object.keys(result.arrival_times).length.toLocaleString();
  $("activated-links").textContent = result.edge_arrivals.length.toLocaleString();
  $("burning-buildings").textContent = state.burningBuildingIds.size.toLocaleString();
  $("result-horizon").textContent = `${Number(result.horizon_minutes).toFixed(1)} min`;
  const wind = result.urban_wind || {};
  $("wind-model-status").textContent = wind.enabled
    ? `${wind.name} / ${Number(wind.cell_size_m).toFixed(0)} m grid / ${Number(wind.obstacle_cells).toLocaleString()} obstacle cells`
    : "Urban wind disabled";
  const rows = $("hotspot-rows");
  rows.replaceChildren();
  const arrivals = new Map(result.edge_arrivals.map((arrival) => [arrival.edge_id, arrival]));
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
    urban_wind_enabled: $("urban-wind").checked,
    urban_wind_cell_size_m: Number($("urban-wind-cell").value),
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
    focusSceneCanvas();
  }
}

function downloadResult() {
  if (!state.result) return;
  const blob = new Blob([JSON.stringify(state.result, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "manhattan-fire-spread-result.json";
  link.click();
  URL.revokeObjectURL(url);
  focusSceneCanvas();
}

function updateSceneSummary() {
  const mode = $("view-mode").value;
  const heightText = state.heightMode === "massing" ? "3 m fallback enabled" : "source heights only";
  const yawDegrees = Math.round(((state.camera.yaw * 180 / Math.PI) % 360 + 360) % 360);
  const radiusText = state.camera.radius >= 1000
    ? `${(state.camera.radius / 1000).toFixed(1)} km radius`
    : `${state.camera.radius.toFixed(0)} m radius`;
  $("scene-summary").textContent = `${mode} / ${radiusText} / ${state.verticalScale}x vertical / ${heightText} / yaw ${yawDegrees} deg`;
}

function setSceneMode() {
  state.heightMode = $("height-mode").value;
  state.verticalScale = Number($("vertical-scale").value);
  if (state.world) {
    createBuildingMesh();
    updateWorldScale();
  }
  state.activeCamera = state.cameras[$("view-mode").value] || state.cameras.perspective;
  updateSceneSummary();
  focusSceneCanvas();
}

function resetSceneView() {
  calculateBounds();
  state.camera.yaw = -0.68;
  state.camera.pitch = 0.7;
  updateCamera();
  updateSceneSummary();
  focusSceneCanvas();
}

function beginSceneGesture(event) {
  if (event.button !== 0 && event.button !== 2) return;
  state.gesture = {
    pointerId: event.pointerId,
    mode: event.shiftKey || event.button === 2 ? "pan" : "orbit",
    x: event.clientX,
    y: event.clientY,
    moved: false,
  };
  state.suppressClick = false;
  event.currentTarget.setPointerCapture(event.pointerId);
  event.currentTarget.classList.add("dragging");
  event.preventDefault();
}

function moveSceneGesture(event) {
  if (!state.gesture || state.gesture.pointerId !== event.pointerId) return;
  const deltaX = event.clientX - state.gesture.x;
  const deltaY = event.clientY - state.gesture.y;
  if (Math.hypot(deltaX, deltaY) > 3) state.gesture.moved = true;
  if (state.gesture.mode === "orbit") {
    state.camera.yaw += deltaX * 0.008;
    state.camera.pitch = clamp(state.camera.pitch + deltaY * 0.006, 0.12, 1.42);
  } else {
    const panScale = state.camera.radius * 0.0015;
    state.camera.targetX -= deltaX * panScale;
    state.camera.targetZ += deltaY * panScale;
  }
  state.gesture.x = event.clientX;
  state.gesture.y = event.clientY;
  updateCamera();
  updateSceneSummary();
  event.preventDefault();
}

function endSceneGesture(event) {
  if (!state.gesture || state.gesture.pointerId !== event.pointerId) return;
  const moved = state.gesture.moved;
  if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  state.gesture = null;
  event.currentTarget.classList.remove("dragging");
  if (moved) {
    state.suppressClick = true;
    window.setTimeout(() => { state.suppressClick = false; }, 0);
  }
}

function zoomScene(event) {
  event.preventDefault();
  state.camera.radius = clamp(
    state.camera.radius * Math.exp(event.deltaY * 0.001),
    MIN_CAMERA_RADIUS,
    MAX_CAMERA_RADIUS,
  );
  updateCamera();
  updateSceneSummary();
}

function panCamera(forward, right) {
  const amount = clamp(state.camera.radius * 0.04, 20, 1200);
  state.camera.targetX += (-Math.sin(state.camera.yaw) * forward + Math.cos(state.camera.yaw) * right) * amount;
  state.camera.targetZ += (-Math.cos(state.camera.yaw) * forward - Math.sin(state.camera.yaw) * right) * amount;
}

function handleSceneKeydown(event) {
  if (!state.bounds || !state.activeCamera) return;
  const activeElement = document.activeElement;
  const editingText = activeElement && (
    ["INPUT", "TEXTAREA"].includes(activeElement.tagName)
    || activeElement.isContentEditable
  );
  if (editingText) return;
  const key = event.key.toLowerCase();
  if (key === "w") panCamera(1, 0);
  else if (key === "s") panCamera(-1, 0);
  else if (key === "a") panCamera(0, -1);
  else if (key === "d") panCamera(0, 1);
  else if (key === "e") state.camera.radius = clamp(state.camera.radius * 0.84, MIN_CAMERA_RADIUS, MAX_CAMERA_RADIUS);
  else if (key === "q") state.camera.radius = clamp(state.camera.radius * 1.19, MIN_CAMERA_RADIUS, MAX_CAMERA_RADIUS);
  else if (event.key === "ArrowLeft") state.camera.yaw -= 0.08;
  else if (event.key === "ArrowRight") state.camera.yaw += 0.08;
  else if (event.key === "ArrowUp") state.camera.pitch = clamp(state.camera.pitch - 0.06, 0.12, 1.42);
  else if (event.key === "ArrowDown") state.camera.pitch = clamp(state.camera.pitch + 0.06, 0.12, 1.42);
  else return;
  updateCamera();
  updateSceneSummary();
  focusSceneCanvas();
  event.preventDefault();
}

function selectNodeAtPointer(event) {
  if (!state.nodePoints || state.gesture || state.suppressClick || event.button !== 0) return;
  const rect = $("building-scene").getBoundingClientRect();
  const clickX = event.clientX - rect.left;
  const clickY = event.clientY - rect.top;
  const projected = new THREE.Vector3();
  let closestNode = null;
  let closestDistance = 24;
  for (const node of state.network.nodes) {
    projected.set(node.x, 0.7, -node.y);
    state.world.localToWorld(projected);
    projected.project(state.activeCamera);
    if (projected.z < -1 || projected.z > 1) continue;
    const screenX = (projected.x * 0.5 + 0.5) * rect.width;
    const screenY = (-projected.y * 0.5 + 0.5) * rect.height;
    const distance = Math.hypot(screenX - clickX, screenY - clickY);
    if (distance < closestDistance) {
      closestDistance = distance;
      closestNode = node;
    }
  }
  if (closestNode) setSelectedNode(closestNode.id);
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
    createScene();
    renderNetwork();
    setSelectedNode(status.default_ignition);
    setSceneMode();
    setRunState("Ready.", "select ignition and run", 35);
  } catch (error) {
    setRunState("Dataset unavailable.", error.message, 12);
    $("map-message").textContent = "Could not load the 3D network or OSM building geometry.";
  }
}

$("scenario-form").addEventListener("submit", runScenario);
$("use-center").addEventListener("click", () => {
  if (state.status) $("ignition").value = state.status.default_ignition;
  focusSceneCanvas();
});
$("view-mode").addEventListener("change", setSceneMode);
$("height-mode").addEventListener("change", setSceneMode);
$("vertical-scale").addEventListener("change", setSceneMode);
$("urban-wind").addEventListener("change", focusSceneCanvas);
$("urban-wind-cell").addEventListener("change", focusSceneCanvas);
$("download-result").addEventListener("click", downloadResult);
$("reset-view").addEventListener("click", resetSceneView);
$("run-flow").addEventListener("click", runFlowField);
$("flow-radius").addEventListener("change", focusSceneCanvas);
initialize();
