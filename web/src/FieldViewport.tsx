import { Component, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { Clone, Html, OrbitControls, OrthographicCamera, PerspectiveCamera, TransformControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import type { AuditSnapshot, Farm, Layout, LayoutObject, Ridge, Vec3 } from './types';

type Props = {
  farms: Farm[]; layout: Layout | null; audit: AuditSnapshot | null;
  selectedFarm: string; range: [number, number]; selectedObject: string | null;
  onRidge: (farmId: string, ridge: number, extend: boolean) => void;
  onObject: (id: string) => void;
  onTransform: (id: string, values: Partial<LayoutObject>) => void;
  camera: 'perspective' | 'top'; editing: boolean; transform: 'translate' | 'rotate';
  overlay: 'stage' | 'root_vwc' | 'lai'; labels: boolean;
};

export class RenderBoundary extends Component<{ children: ReactNode; fallback: ReactNode; onError?: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onError?.(); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

function GLB({ url, onLoaded }: { url: string; onLoaded: () => void }) {
  const { scene } = useGLTF(url);
  useEffect(onLoaded, [url, onLoaded]);
  return <Clone object={scene} castShadow receiveShadow />;
}

function AssetModel({ object, selected, onStatus }: { object: LayoutObject; selected: boolean; onStatus: (id: string, url: string, status: string) => void }) {
  const fallback = <Machine kind={object.kind} selected={selected} />;
  const url = object.asset_url || '';
  const valid = /^\/models\/[A-Za-z0-9_/-]+\.glb$/.test(url) && !url.includes('..');
  const loaded = useCallback(() => onStatus(object.id, url, 'loaded'), [object.id, url, onStatus]);
  const failed = useCallback(() => onStatus(object.id, url, 'fallback'), [object.id, url, onStatus]);
  return valid ? <RenderBoundary key={url} fallback={fallback} onError={failed}><Suspense fallback={fallback}><GLB url={url} onLoaded={loaded} /></Suspense></RenderBoundary> : fallback;
}

const stageColor = (ridge: Ridge) => ridge.harvested ? '#b59c69' : !ridge.planted ? '#927b58'
  : /R[678]|matur|ripe/i.test(ridge.growth_stage || '') ? '#b1b054' : '#65814d';

function Plants({ farm }: { farm: Farm }) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const positions = useMemo(() => {
    const rows: { x: number; z: number; color: string; height: number }[] = [];
    const width = farm.geometry.num_ridges * farm.geometry.ridge_width_m;
    for (const ridge of farm.ridges) {
      if (!ridge.planted || ridge.harvested) continue;
      for (let n = 0; n < 32; n++) {
        rows.push({ x: (ridge.ridge_id + .5) * farm.geometry.ridge_width_m - width / 2,
          z: (n + .5) * farm.geometry.length_m / 32 - farm.geometry.length_m / 2,
          color: stageColor(ridge), height: /BARE|sow|VE/i.test(ridge.growth_stage || '') ? .8 : 1.7 });
      }
    }
    return rows;
  }, [farm]);
  useEffect(() => {
    if (!mesh.current) return;
    const object = new THREE.Object3D();
    positions.forEach((p, i) => {
      object.position.set(p.x, p.height / 2 + .5, p.z);
      object.scale.set(.7, p.height, 2.3);
      object.updateMatrix();
      mesh.current!.setMatrixAt(i, object.matrix);
      mesh.current!.setColorAt(i, new THREE.Color(p.color));
    });
    mesh.current.instanceMatrix.needsUpdate = true;
    if (mesh.current.instanceColor) mesh.current.instanceColor.needsUpdate = true;
    mesh.current.computeBoundingSphere();
  }, [positions]);
  return positions.length > 0 ? <instancedMesh ref={mesh} args={[undefined, undefined, positions.length]} raycast={() => {}}>
    <coneGeometry args={[.65, 1, 5]} /><meshStandardMaterial roughness={1} />
  </instancedMesh> : null;
}

function Machine({ kind, selected }: { kind: string; selected: boolean }) {
  const color = selected ? '#d8af51' : '#426d54';
  if (/sensor|probe/.test(kind)) return <group>
    <mesh position={[0, 2.5, 0]}><cylinderGeometry args={[.13, .13, 5, 8]} /><meshStandardMaterial color="#a7b3a0" /></mesh>
    <mesh position={[0, 5, 0]}><boxGeometry args={[1.8, .7, 1]} /><meshStandardMaterial color={color} /></mesh>
  </group>;
  if (/drone/.test(kind)) return <group position={[0, 5, 0]}>
    <mesh><boxGeometry args={[2, .5, 2]} /><meshStandardMaterial color={color} /></mesh>
    {[-1, 1].flatMap(x => [-1, 1].map(z => <mesh key={`${x}-${z}`} position={[x * 1.6, 0, z * 1.6]} rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[1, 1, .12, 16]} /><meshStandardMaterial color="#53615c" /></mesh>))}
  </group>;
  return <group>
    <mesh position={[0, 1.1, 0]} castShadow><boxGeometry args={[2.8, 1.6, 4.5]} /><meshStandardMaterial color={color} /></mesh>
    <mesh position={[0, 2.4, -.6]} castShadow><boxGeometry args={[2.1, 1.5, 1.8]} /><meshStandardMaterial color="#b4cbc2" roughness={.4} /></mesh>
    {[-1, 1].flatMap(x => [-1, 1].map(z => <mesh key={`${x}-${z}`} position={[x * 1.5, .8, z * 1.4]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[.9, .9, .55, 14]} /><meshStandardMaterial color="#39443d" /></mesh>))}
  </group>;
}

function EditableObject({ object, props, children }: { object: LayoutObject; props: Props; children: ReactNode }) {
  const ref = useRef<THREE.Group>(null);
  const [target, setTarget] = useState<THREE.Group | null>(null);
  const attach = useCallback((node: THREE.Group | null) => { ref.current = node; setTarget(node); }, []);
  const selected = props.selectedObject === object.id;
  const commit = () => {
    if (!ref.current) return;
    props.onTransform(object.id, {
      position: ref.current.position.toArray().map(v => Math.round(v * 1000) / 1000) as Vec3,
      rotation: [ref.current.rotation.x, ref.current.rotation.y, ref.current.rotation.z],
    });
  };
  return <>
    <group ref={attach} position={object.position} rotation={object.rotation}
      onClick={event => { if (props.editing || object.kind !== 'field') { event.stopPropagation(); props.onObject(object.id); } }}>
      {children}
      {props.labels && object.kind !== 'field' && <Html center position={[0, 7, 0]} distanceFactor={140} zIndexRange={[20, 0]} style={{ pointerEvents: 'none' }}><span className={`scene-label ${selected ? 'selected' : ''}`}>{object.label}</span></Html>}
    </group>
    {props.editing && selected && target && <TransformControls object={target} mode={props.transform} size={.75} onMouseUp={commit} />}
  </>;
}

function Field({ farm, props }: { farm: Farm; props: Props }) {
  const width = farm.geometry.num_ridges * farm.geometry.ridge_width_m;
  const length = farm.geometry.length_m;
  const auditRidges = props.audit?.farms.find(f => f.farm_id === farm.farm_id)?.ridges;
  return <group>
    <mesh position={[0, -.35, 0]} receiveShadow><boxGeometry args={[farm.geometry.boundary_width_m || width, .8, length]} /><meshStandardMaterial color="#a58c65" /></mesh>
    {farm.ridges.map(ridge => {
      const selected = farm.farm_id === props.selectedFarm && ridge.ridge_id >= props.range[0] && ridge.ridge_id <= props.range[1];
      let color = stageColor(ridge);
      if (props.overlay !== 'stage') {
        const values = auditRidges?.find(r => r.ridge_id === ridge.ridge_id)?.values;
        const value = props.overlay === 'root_vwc' ? values?.root_vwc ?? values?.SM : values?.lai ?? values?.LAI;
        color = typeof value === 'number' && Number.isFinite(value)
          ? new THREE.Color('#cfb477').lerp(new THREE.Color(props.overlay === 'root_vwc' ? '#397f94' : '#305e40'), Math.max(0, Math.min(1, value / (props.overlay === 'root_vwc' ? .5 : 6)))).getStyle()
          : '#a9ada4';
      }
      return <mesh key={ridge.ridge_id} position={[(ridge.ridge_id + .5) * farm.geometry.ridge_width_m - width / 2, .13, 0]}
        onClick={event => { event.stopPropagation(); if (props.editing) { const object = props.layout?.objects.find(o => o.kind === 'field' && o.farm_id === farm.farm_id); if (object) props.onObject(object.id); } else props.onRidge(farm.farm_id, ridge.ridge_id, event.shiftKey); }}>
        <boxGeometry args={[farm.geometry.ridge_width_m * .88, .26, length]} />
        <meshStandardMaterial color={selected ? '#e1b957' : color} roughness={1} emissive={selected ? '#8f7325' : '#000'} emissiveIntensity={.2} />
      </mesh>;
    })}
    {props.overlay === 'stage' && <Plants farm={farm} />}
    {[0, 15, 31, 47, farm.geometry.num_ridges - 1].filter((n, i, arr) => n < farm.geometry.num_ridges && arr.indexOf(n) === i).map(rid => <Html key={rid} position={[(rid + .5) * farm.geometry.ridge_width_m - width / 2, .6, length / 2 + 6]} center distanceFactor={180} zIndexRange={[15, 0]} style={{ pointerEvents: 'none' }}><span className="ridge-marker">{rid}</span></Html>)}
  </group>;
}

function Camera({ props }: { props: Props }) {
  const { size } = useThree();
  const farm = props.farms.find(f => f.farm_id === props.selectedFarm) || props.farms[0];
  const length = farm?.geometry.length_m || 268;
  const width = farm ? farm.geometry.num_ridges * farm.geometry.ridge_width_m : 70;
  const object = props.layout?.objects.find(o => o.kind === 'field' && o.farm_id === farm?.farm_id);
  const p = object?.position || [0, 0, 0];
  const span = Math.max(width, length);
  const zoom = Math.min(size.width / (width + 80), size.height / (length + 50));
  return <>
    {props.camera === 'top'
      ? <OrthographicCamera makeDefault position={[p[0], p[1] + span * 2, p[2] + .01]} zoom={zoom} near={.1} far={5000} />
      : <PerspectiveCamera makeDefault position={[p[0] + span * .72, p[1] + span * .82, p[2] + span * .86]} fov={43} near={.1} far={5000} />}
    <OrbitControls key={`${props.camera}-${farm?.farm_id}`} makeDefault target={[p[0], p[1], p[2]]} enableRotate={props.camera !== 'top'} maxPolarAngle={Math.PI / 2.08} minDistance={8} maxDistance={span * 5} minZoom={.1} maxZoom={50} enableDamping />
  </>;
}

export default function FieldViewport(props: Props) {
  const [modelStates, setModelStates] = useState<Record<string, { url: string; status: string }>>({});
  const onStatus = useCallback((id: string, url: string, status: string) => {
    setModelStates(old => old[id]?.url === url && old[id]?.status === status ? old : { ...old, [id]: { url, status } });
  }, []);
  const statuses = Object.fromEntries((props.layout?.objects || []).filter(o => o.asset_url).map(o => [o.id, o.kind === 'field' ? 'unsupported' : !/^\/models\/[A-Za-z0-9_/-]+\.glb$/.test(o.asset_url!) || o.asset_url!.includes('..') ? 'fallback' : modelStates[o.id]?.url === o.asset_url ? modelStates[o.id].status : 'loading']));
  return <div className="field-viewport" data-model-status={JSON.stringify(statuses)} role="region" aria-label="三维农田。点击选择垄，按 Shift 扩展范围；也可使用右侧数值框选择。">
    <RenderBoundary fallback={<div className="canvas-fallback"><strong>三维视图暂不可用</strong><p>请检查浏览器 WebGL 支持。列表、观测与操作面板仍可使用。</p></div>}>
      <Canvas dpr={[1, 1.5]} gl={{ antialias: true, alpha: false }}>
        <color attach="background" args={['#e8eddf']} />
        <fog attach="fog" args={['#e8eddf', 650, 1700]} />
        <Camera props={props} />
        <ambientLight intensity={1.5} />
        <hemisphereLight args={['#fff9e6', '#91a478', 1.5]} />
        <directionalLight position={[120, 200, 100]} color="#fff2d3" intensity={2} />
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -.9, 0]}><planeGeometry args={[4000, 4000]} /><meshStandardMaterial color="#ced7b8" roughness={1} /></mesh>
        {props.farms.map(farm => {
          const object = props.layout?.objects.find(o => o.kind === 'field' && o.farm_id === farm.farm_id);
          const body = <Field farm={farm} props={props} />;
          return object ? <EditableObject key={farm.farm_id} object={object} props={props}>{body}</EditableObject> : <group key={farm.farm_id}>{body}</group>;
        })}
        {props.layout?.objects.filter(o => o.kind !== 'field').map(object => <EditableObject key={object.id} object={object} props={props}><AssetModel object={object} selected={props.selectedObject === object.id} onStatus={onStatus} /></EditableObject>)}
      </Canvas>
    </RenderBoundary>
    <div className="viewport-note">米制场景 · 代表性植株 · 设备位置为展示布局 · 外观映射 visual-v1</div>
  </div>;
}
