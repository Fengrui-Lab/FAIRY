"""Checksummed offline evidence. Runtime never authors or optimizes a plan."""
import ast
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent
ARTIFACT_ROOT = ROOT / "artifacts"
SCHEMA = 2
REBUILD = "python scripts/build_crop_challenges.py"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def source_digest(crop):
    repo = ROOT.parents[2]
    paths = [ROOT / "catalog.py", ROOT / "worlds.py", ROOT / "runtime.py", ROOT / "artifacts.py"]
    if crop == "rice":
        paths += [repo / "fairy/apps/paddy" / f"{name}.py"
                  for name in ("models", "operations", "observations", "world", "infrastructure")]
        paths += [repo / "fairy/physics/rice_backend.py", repo / "fairy/physics/paddy_waterbalance.py"]
    else:
        paths += [repo / "fairy/physics/wofost_backend.py",
                  repo / "fairy/scenarios/maize/maize_scenario_helpers.py",
                  repo / "fairy/scenarios/maize/farm_checkpoint_state.py"]
    return digest({str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def load(source_id):
    from .catalog import CHALLENGES
    definition = CHALLENGES[source_id]
    try:
        manifest = json.loads((ARTIFACT_ROOT / "manifest.json").read_text())
        compressed = (ARTIFACT_ROOT / f"{source_id}.json.gz").read_bytes()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing challenge artifacts; rebuild with {REBUILD}") from exc
    if manifest.get("schema_version") != SCHEMA or manifest["files"].get(source_id) != hashlib.sha256(compressed).hexdigest():
        raise ValueError(f"Challenge artifact checksum/schema mismatch; rebuild with {REBUILD}")
    data = json.loads(gzip.decompress(compressed))
    if data.get("source_id") != source_id or data.get("source_digest") != source_digest(definition.crop):
        raise ValueError(f"Challenge source changed; rebuild with {REBUILD}")
    return data


def load_maize_plans(source_id, data):
    """Read the reviewed Python literal without executing arbitrary code."""
    raw = (ARTIFACT_ROOT / f"{source_id}.plan.py").read_bytes()
    if hashlib.sha256(raw).hexdigest() != data["python_plan_sha256"]:
        raise ValueError("Maize Python plan checksum mismatch")
    tree = ast.parse(raw)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign):
        raise ValueError("Expected one static Python plan assignment")
    return ast.literal_eval(tree.body[0].value)


def write(root, source_id, data, manifest):
    root.mkdir(parents=True, exist_ok=True)
    raw = gzip.compress(canonical(data), mtime=0)
    (root / f"{source_id}.json.gz").write_bytes(raw)
    manifest["files"][source_id] = hashlib.sha256(raw).hexdigest()
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
