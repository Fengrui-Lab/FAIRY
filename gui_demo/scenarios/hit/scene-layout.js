/** Shared display layout. The left panel enlarges the one selected ROI; it is
 * not another farm or a second simulation world. All points are image XY. */
export function hitSceneLayout(data = {}) {
  const ratio = (Number(data.farm?.height_m) || 147) / (Number(data.farm?.width_m) || 283);
  const farmWidth = Math.min(490, 365 / ratio), farmHeight = farmWidth * ratio;
  const bounds = data.roi?.bounds || [.45, .34, .52, .42];
  const roiAspect = data.orthomosaicMetadata?.display_aspect_ratio || data.orthomosaicMetadata?.aspect_ratio || ((bounds[2] - bounds[0]) / (bounds[3] - bounds[1]) / ratio);
  const insetHeight = Math.min(310, 310 / roiAspect), insetWidth = insetHeight * roiAspect;
  return {
    width: 1100, height: 600,
    farm: { x: 460 + (490 - farmWidth) / 2, y: (600 - farmHeight) / 2 + 12, width: farmWidth, height: farmHeight },
    inset: { x: 44 + (310 - insetWidth) / 2, y: (600 - insetHeight) / 2 + 30, width: insetWidth, height: insetHeight },
    roiBounds: bounds,
  };
}

export const inRect = (point, rect) => [rect.x + point[0] * rect.width, rect.y + point[1] * rect.height];
export const roiLocal = (point, bounds) => [(point[0] - bounds[0]) / (bounds[2] - bounds[0]), (point[1] - bounds[1]) / (bounds[3] - bounds[1])];

// Schematic field surfaces and access tracks traced from the supplied UAV
// orthomosaic. These are display geometry, not additional segmentation output.
export const DRONE_FIELDS = [
  [[.181, .087], [.462, .273], [.254, .673], [.143, .599]],
  [[.475, .283], [.917, .570], [.589, .916], [.268, .682]],
];
export const DRONE_ROADS = [
  { points: [[.169, .059], [.944, .557], [.592, .944], [.130, .630], [.169, .059]], width: .014 },
  { points: [[.468, .276], [.260, .678]], width: .010 },
  { points: [[.146, .095], [.129, .365], [.115, .598]], width: .008 },
];
export const DRONE_TREE_STRIPS = [
  [[.102, .171], [.137, .105], [.125, .356], [.105, .541], [.085, .602], [.048, .568], [.060, .449]],
  [[.618, .947], [.955, .611], [.961, .566], [.939, .571], [.593, .929]],
];

export function insidePolygon(point, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    if ((a[1] > point[1]) !== (b[1] > point[1]) && point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

export function droneCropSamples() {
  const samples = [];
  for (let row = -25; row < 60; row++) for (let column = 0; column < 52; column++) {
    const x = .045 + column * .018, y = row * .017 + x * .64;
    if (DRONE_FIELDS.some(polygon => insidePolygon([x, y], polygon))) samples.push({ x, y, cropId: 'rice', classId: 1 });
  }
  return samples;
}

/** A display-only sweep follows the two visible rice quadrilaterals. Crossing
 * the narrow dividing track is intentional; no sweep runs in the blank frame. */
export function droneScanRoute() {
  const route = [], slope = .64;
  for (let row = 0; row < 7; row++) {
    const intercept = .015 + row * .078, intersections = [];
    for (const polygon of DRONE_FIELDS) for (let i = 0; i < polygon.length; i++) {
      const a = polygon[i], b = polygon[(i + 1) % polygon.length];
      const fa = a[1] - slope * a[0] - intercept, fb = b[1] - slope * b[0] - intercept;
      if ((fa < 0) === (fb < 0) || fa === fb) continue;
      const t = fa / (fa - fb); intersections.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
    intersections.sort((a, b) => a[0] - b[0]);
    if (intersections.length < 2) continue;
    const a = intersections[0], b = intersections.at(-1), margin = .035;
    const left = [a[0] + (b[0] - a[0]) * margin, a[1] + (b[1] - a[1]) * margin];
    const right = [b[0] - (b[0] - a[0]) * margin, b[1] - (b[1] - a[1]) * margin];
    route.push(...(row % 2 ? [right, left] : [left, right]));
  }
  return route;
}
