"""Task-derived seed choices; no queries, oracle access or simulator mutation."""
import re

_PLAN = re.compile(r'ridges?\s+(\d+)\s*[-–—]\s*(\d+)\s*[:：]\s*([A-Z][A-Z0-9_]*)[^;；\n]*?seed_spacing_cm\s*=\s*(\d+(?:\.\d+)?)', re.I)


def seed_amount_hint(world, seed_type, task_text, steps, capacity, *, snapshot=None):
    """Return an optional positive choice and its provenance from logged observations."""
    plans = list(_PLAN.finditer(task_text))
    if not plans or not seed_type:
        return None, ''
    targets = {}; seen = set()
    for m in plans:
        lo, hi = int(m[1]), int(m[2])
        if not 0 <= lo <= hi < world.num_ridges or seen.intersection(range(lo, hi + 1)):
            return None, ''
        seen.update(range(lo, hi + 1))
        if m[3] == seed_type:
            count = world.plants_per_ridge_from_spacing(float(m[4]))
            targets.update({i: count for i in range(lo, hi + 1)})
    if not targets:
        return None, ''
    hopper = None; loaded_type = None; planted = set(); stock = None
    for step in steps:
        get = step.get if isinstance(step, dict) else lambda k, d=None: getattr(step, k, d)
        raw = get('content'); name = get('tool_name', '')
        if get('op_type') == 'TOOL_ERROR' or not isinstance(raw, dict):
            continue
        if isinstance(raw.get('ok'), bool):
            if not raw['ok']: continue
            data = raw.get('data')
        else:
            if 'error' in raw: continue
            data = raw
        if not isinstance(data, dict): continue
        if name in ('TractorApp__get_status', 'TractorApp__load_seeds'):
            if 'seed_hopper' in data and 'seed_type' in data:
                hopper, loaded_type = data['seed_hopper'], data['seed_type']
        if name == 'FarmWorldApp__get_inventory':
            stock = data.get('seed_stock', {}).get(seed_type)
        if name in ('TractorApp__plant_seeds', 'TractorApp__replant_seeds'):
            if name.endswith('__plant_seeds'):
                planted.update(data.get('planted_ridges', []))
            used = data.get('seeds_used')
            if hopper is not None:
                hopper = max(0, hopper - used) if isinstance(used, (int, float)) else None
        if name == 'TractorApp__load_seeds' and stock is not None:
            # Inventory observation predates transfer; do not reuse stale stock.
            stock = None
    if snapshot is not None:
        machine = snapshot.get("machine", {})
        hopper = machine.get("seed_hopper")
        loaded_type = machine.get("seed_type")
        stock = snapshot.get("inventory", {}).get("seed_stock", {}).get(seed_type)
        # The existing visible snapshot is authoritative at decision time.
        planted = {r["ridge_id"] for r in snapshot.get("ridges", [])
                   if r.get("planted") or r.get("harvested")}
    if hopper is None:
        return None, '' 
    if hopper > 0 and loaded_type != seed_type:
        return None, 'Observed hopper contains another variety; this suggestion cannot resolve a nonempty-hopper variety conflict.'
    need = sum(n for ridge, n in targets.items() if ridge not in planted) - hopper
    amount = min(need, capacity - hopper)
    if stock is not None: amount = min(amount, stock)
    if amount <= 0: return None, ''
    return int(amount), ('Task-zone seed demand using native spacing calculation, minus observed hopper and successful sowing; '
                         'clipped to hopper capacity and observed stock when available. Candidate is not a guarantee of field readiness.')
