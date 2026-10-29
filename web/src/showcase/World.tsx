import { useLayoutEffect, useMemo, useRef, type RefObject } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, OrthographicCamera } from '@react-three/drei';
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { type Field, type Frame, type Layer, type Region, type Scene, regionColor } from './data';

function plantGeometry(maize: boolean) {
  const parts: THREE.BufferGeometry[] = [];
  const add = (g: THREE.BufferGeometry, color: string, pos: number[], scale = [1, 1, 1], rot = [0, 0, 0]) => {
    if (g.index) { const original = g; g = g.toNonIndexed(); original.dispose(); }
    g.scale(...scale as [number, number, number]);
    g.rotateX(rot[0]); g.rotateY(rot[1]); g.rotateZ(rot[2]); g.translate(...pos as [number, number, number]);
    const c = new THREE.Color(color), a = [];
    for (let i = 0; i < g.getAttribute('position').count; i++) a.push(c.r, c.g, c.b);
    g.setAttribute('color', new THREE.Float32BufferAttribute(a, 3)); parts.push(g);
  };
  add(new THREE.CylinderGeometry(.09, .16, maize ? 5.2 : 2.1, 5), '#486340', [0, maize ? 2.6 : 1.05, 0]);
  if (maize) {
    for (let i = 0; i < 6; i++) {
      const side = i % 2 ? -1 : 1;
      add(new THREE.SphereGeometry(1, 5, 3), i % 3 ? '#72934c' : '#91ad58', [side * .8, 1.2 + i * .55, (i % 3 - 1) * .35], [1.5, .12, .45], [0, i * .7, side * .55]);
    }
    add(new THREE.CylinderGeometry(.21, .28, 1.1, 6), '#dfc161', [.28, 3.25, .12], [1, 1, 1], [0, 0, -.3]);
    for (let i = 0; i < 3; i++) add(new THREE.ConeGeometry(.16, 1, 4), '#c8b474', [(i - 1) * .28, 5.1, 0], [1, 1, 1], [0, 0, (i - 1) * -.25]);
  } else {
    for (let i = 0; i < 5; i++) add(new THREE.IcosahedronGeometry(1, 0), ['#64834f', '#7e9f60', '#8ca86d'][i % 3], [Math.sin(i * 2.4) * .65, 1.1 + (i % 3) * .42, Math.cos(i * 2.4) * .55], [.85, .65, .8]);
  }
  const merged = mergeGeometries(parts);
  parts.forEach(p => p.dispose());
  return merged;
}
function Plants({ field, frame, layer }: { field: Field; frame: Frame; layer: Layer }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const geometry = useMemo(() => plantGeometry(field.crop === 'Maize'), [field.crop]);
  const points = useMemo(() => {
    const p: [number, number, number][] = [];
    for (let x = -field.width / 2 + 2.4; x < field.width / 2 - 1; x += 3.5)
      for (let z = -130; z < 132; z += 6) p.push([x + field.x, z, .82 + (Math.sin(x * 5 + z * 7) + 1) * .13]);
    return p;
  }, [field]);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const obj = new THREE.Object3D();
    points.forEach(([x, z, size], i) => {
      obj.position.set(x, .65, z); obj.rotation.set(0, i * 2.399, 0); obj.scale.setScalar(Math.max(.01, frame.growth) * size);
      obj.updateMatrix(); ref.current!.setMatrixAt(i, obj.matrix);
      ref.current!.setColorAt(i, new THREE.Color(layer === 'crop' ? '#ffffff' : '#dfe8da'));
    });
    ref.current.instanceMatrix.needsUpdate = true;
    if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
    ref.current.computeBoundingSphere();
  }, [points, frame, layer]);
  return <instancedMesh ref={ref} args={[geometry, undefined, points.length]} castShadow receiveShadow><meshStandardMaterial vertexColors roughness={.95} /></instancedMesh>;
}
function Box({ at, size, color, rotation = 0 }: { at: [number, number, number]; size: [number, number, number]; color: string; rotation?: number }) {
  return <mesh position={at} rotation={[0, rotation, 0]} castShadow receiveShadow><boxGeometry args={size} /><meshStandardMaterial color={color} roughness={.9} /></mesh>;
}
function Tractor({ x, z }: { x: number; z: number }) {
  return <group position={[x, 0, z]} rotation={[0, .2, 0]}>
    <Box at={[0, 2.2, 0]} size={[3.4, 2.1, 7]} color="#d9ac4e" />
    <Box at={[0, 4.2, 1]} size={[3, 3.1, 3]} color="#e6d7ad" /><Box at={[0, 4.4, -.55]} size={[2.7, 1.9, .15]} color="#658080" />
    <Box at={[0, 5.9, 1]} size={[3.8, .45, 3.7]} color="#e8d9b6" />
    {[-1, 1].flatMap(side => [-2, 2].map(z0 => <mesh key={`${side}:${z0}`} position={[side * 2, 1.5, z0]} rotation={[0, 0, Math.PI / 2]} castShadow><cylinderGeometry args={[1.6, 1.6, 1, 12]} /><meshStandardMaterial color="#3e4c44" /></mesh>))}
  </group>;
}
function Drone({ x, z }: { x: number; z: number }) {
  return <group position={[x, 18, z]}>
    <Box at={[0, 0, 0]} size={[2.5, 1, 3]} color="#f7f6e9" />
    {[0, 1].map(i => <Box key={i} at={[0, 0, 0]} size={[9, .35, .6]} rotation={i ? -.7 : .7} color="#566966" />)}
    {[-1, 1].flatMap(x => [-1, 1].map(z => <mesh key={`${x}:${z}`} position={[x * 3.2, .4, z * 2.7]}><cylinderGeometry args={[2.4, 2.4, .12, 18]} /><meshStandardMaterial color="#405653" transparent opacity={.65} /></mesh>))}
  </group>;
}
export function FarmScene({ scene, frame, layer, cells, selectedField, selectedRegion, onSelect, labels = true }: {
  scene: Scene; frame: Frame; layer: Layer; cells: Region[]; selectedField: string; selectedRegion: string;
  onSelect: (field: string, region?: string) => void; labels?: boolean;
}) {
  const extent = scene.id === 'two' ? 112 : 151;
  return <group>
    <Box at={[0, -2.5, 1]} size={[extent * 2 + 42, 5, 354]} color="#b4be9f" />
    <Box at={[0, .03, 150]} size={[extent * 2 + 42, .18, 13]} color="#d6ccb7" />
    <Box at={[extent - 6, .06, -5]} size={[9, .2, 307]} color="#d6ccb7" />
    <Box at={[0, .08, -148]} size={[extent * 2 + 42, .2, 9]} color="#d6ccb7" />
    {scene.fields.map(field => <group key={field.id}>
      <Box at={[field.x, .1, 0]} size={[field.width + 3, .3, 271]} color="#9b9e79" />
      <Box at={[field.x, .25, 0]} size={[field.width, .5, 268]} color="#9d8a65" />
      {cells.filter(c => c.fieldId === field.id).map(cell => <mesh key={cell.id} position={[cell.x, .54, cell.z]} rotation={[-Math.PI / 2, 0, 0]} onClick={e => { e.stopPropagation(); onSelect(field.id, cell.id); }}>
        <planeGeometry args={[cell.width - .08, cell.length - .08]} /><meshStandardMaterial color={layer === 'crop' ? '#a49a70' : regionColor(cell, field, layer)} roughness={1} />
      </mesh>)}
      {Array.from({ length: 64 }, (_, n) => <Box key={n} at={[field.x - field.width / 2 + (n + .5) * field.ridgeWidth, .57, 0]} size={[.16, .06, 268]} color={layer === 'crop' ? '#887a59' : '#ffffff'} />)}
      <Plants field={field} frame={frame} layer={layer} />
      {(selectedField === field.id ? [-1, 1] : []).map(sign => <group key={sign}>
        <Box at={[field.x + sign * field.width / 2, .9, 0]} size={[.5, .2, 268]} color="#e8f6d9" />
        <Box at={[field.x, .9, sign * 134]} size={[field.width, .2, .5]} color="#e8f6d9" />
      </group>)}
      <group position={[field.x - field.width / 2 - 3, 0, 25]}>
        <Box at={[0, 4, 0]} size={[.45, 8, .45]} color="#6d817c" /><Box at={[0, 8.2, 0]} size={[3, 1.7, 1.5]} color="#faf9ed" />
      </group>
    </group>)}
    {selectedRegion && cells.filter(c => c.id === selectedRegion).map(c => <group key={c.id}>
      {[-1, 1].map(sign => <group key={sign}><Box at={[c.x + sign * c.width / 2, 1.1, c.z]} size={[labels ? .75 : 1.5, .15, c.length]} color={labels ? '#ffe6a0' : '#ce694b'} /><Box at={[c.x, 1.1, c.z + sign * c.length / 2]} size={[c.width, .15, labels ? .75 : 1.5]} color={labels ? '#ffe6a0' : '#ce694b'} /></group>)}
    </group>)}
    <group position={[-extent + 17, 0, 160]}>
      <Box at={[0, 5, 0]} size={[23, 10, 15]} color="#e5ddc9" />
      <group position={[0, 11, 0]}><mesh position={[0, 0, -4]} rotation={[-.32, 0, 0]} castShadow><boxGeometry args={[25, .5, 9]} /><meshStandardMaterial color="#687e72" /></mesh><mesh position={[0, 0, 4]} rotation={[.32, 0, 0]} castShadow><boxGeometry args={[25, .5, 9]} /><meshStandardMaterial color="#768b7c" /></mesh></group>
      <Box at={[0, 3.5, -7.6]} size={[8, 7, .3]} color="#8c967e" />
    </group>
    <Tractor x={5} z={151} />
    <Box at={[22, 1.4, 151]} size={[3, 2.8, 4]} color="#f0ece0" />
    <Drone x={scene.fields[0].x} z={20} />
    {scene.id === 'three' && <Drone x={scene.fields[1].x} z={-60} />}
    {Array.from({ length: 18 }, (_, i) => {
      const x = i < 9 ? -extent - 8 : extent + 13, z = -130 + (i % 9) * 34;
      return <group key={i} position={[x, 0, z]}><Box at={[0, 3, 0]} size={[1.4, 6, 1.4]} color="#8f7f60" /><mesh position={[0, 8, 0]} castShadow><icosahedronGeometry args={[5.6, 1]} /><meshStandardMaterial color={i % 2 ? '#85996b' : '#657c58'} flatShading /></mesh></group>;
    })}
  </group>;
}
// Keep labels in the owning React DOM tree. Project them without creating per-label
// React roots, so rapid scene/view switches cannot race asynchronous Canvas cleanup.
function LabelProjector({ scene, nodes }: { scene: Scene; nodes: RefObject<Record<string, HTMLDivElement | null>> }) {
  const vector = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ camera, size }) => {
    const labels: [string, number, number, number][] = scene.fields.flatMap(f => [
      [f.id, f.x, 6, -140] as [string, number, number, number],
      [f.sensor, f.x - f.width / 2 - 3, 12, 25] as [string, number, number, number],
    ]);
    labels.push(['warehouse', -(scene.id === 'two' ? 112 : 151) + 17, 20, 160]);
    for (const [id, x, y, z] of labels) {
      const node = nodes.current[id]; if (!node) continue;
      vector.set(x, y, z).project(camera);
      node.style.transform = `translate(${(vector.x * .5 + .5) * size.width}px, ${(-vector.y * .5 + .5) * size.height}px) translate(-50%, -50%)`;
      node.style.visibility = vector.z > 1 || vector.z < -1 ? 'hidden' : 'visible';
    }
  });
  return null;
}
export default function World(props: Parameters<typeof FarmScene>[0] & { captureField?: Field; cameraKey?: number }) {
  const top = props.captureField;
  const labelNodes = useRef<Record<string, HTMLDivElement | null>>({});
  return <div className={top ? 'sc-capture-canvas' : 'sc-world'} data-testid="world-view">
    <Canvas shadows dpr={[1, 2]} gl={{ antialias: true, preserveDrawingBuffer: true }} onCreated={({ gl }) => { gl.domElement.dataset.rendered = 'true'; }}>
      <color attach="background" args={['#e9ede4']} />
      <ambientLight intensity={1.5} /><hemisphereLight args={['#fff9e9', '#617557', 1.1]} />
      <directionalLight position={[-120, 230, 90]} intensity={2.5} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-240} shadow-camera-right={240} shadow-camera-top={240} shadow-camera-bottom={-240} shadow-camera-far={650} shadow-bias={-.0004} />
      <OrthographicCamera key={`${props.scene.id}:${props.cameraKey}:${top?.id}`} makeDefault position={top ? [top.x, 400, 0] : [330, 330, 380]} zoom={top ? 3.1 : props.scene.id === 'two' ? 2.2 : 1.95} near={.1} far={1800} onUpdate={c => { c.up.set(top ? -1 : 0, top ? 0 : 1, 0); c.lookAt(top ? top.x : 0, 0, 0); }} />
      <FarmScene {...props} labels={!top && props.labels !== false} />
      {!top && <LabelProjector scene={props.scene} nodes={labelNodes} />}
      {!top && <OrbitControls key={`${props.scene.id}:${props.cameraKey}`} target={[0, 0, 0]} enableDamping={false} maxPolarAngle={Math.PI / 2.2} minZoom={1} maxZoom={8} />}
    </Canvas>
    {!top && <div className="sc-world-labels">{props.scene.fields.map(field => <div key={field.id}>
      <div className="sc-projected" ref={el => { labelNodes.current[field.id] = el; }}><button className={`sc-world-label ${field.id === props.selectedField ? 'chosen' : ''}`} onClick={() => props.onSelect(field.id)}><i style={{ background: field.color }} /><span>{field.name}<small>{field.cultivar}</small></span></button></div>
      <div className="sc-projected" ref={el => { labelNodes.current[field.sensor] = el; }}><button className="sc-world-sensor" onClick={() => props.onSelect(field.id)} title={field.sensor}><span />{field.sensor.replace('_Sensor', '')}</button></div>
    </div>)}<div className="sc-projected" ref={el => { labelNodes.current.warehouse = el; }}><span className="sc-place-label">Shared warehouse</span></div></div>}
  </div>;
}
