/** Scene-specific illustration choices from recorded state and executed events.
 * Images are generic simulation illustrations, never acquired photographs.
 * No new agronomic threshold or inferred diagnosis is introduced here.
 */
const finite = value => typeof value === 'number' && Number.isFinite(value);
const DAY = 86400;
const CONFIDENCE = .6; // Existing UI threshold for presenting ground observations.
const DISEASE_SURVEYS = new Set(['disease_multispectral']);
const WATER_SURVEYS = new Set(['drought_thermal', 'drought_second_thermal']);
const method = event => String(event?.tool_name || '').split('__').at(-1);
const resultOf = event => event?.result && typeof event.result === 'object' && !Array.isArray(event.result) ? event.result : null;
const timeOf = event => finite(event?.time_after) ? event.time_after : Date.parse(event?.datetime_after || '') / 1000;
const farmOf = event => resultOf(event)?.farm_id || event?.arguments?.farm_id ||
  (event?.scope?.farm_ids?.length === 1 ? event.scope.farm_ids[0] : null);
const successful = event => event?.status === 'ok' && !event.error && resultOf(event) &&
  !event.result.error && !['error', 'failed', 'rejected'].includes(event.result.status);
const covers = (event, key, ridgeId) => Array.isArray(resultOf(event)?.[key]) && event.result[key].includes(ridgeId);
const latest = (events, predicate) => events.findLast(predicate);

function soilReading(event, ridgeId) {
  if (method(event) !== 'read_soil_sensors') return null;
  return resultOf(event)?.soil_sensors?.find(row =>
    Number.isInteger(row.ridge_start) && Number.isInteger(row.ridge_end) &&
    row.ridge_start <= ridgeId && ridgeId <= row.ridge_end && finite(row.vwc)) || null;
}

function cropReading(event, ridgeId, farmId) {
  if (method(event) !== 'get_ridge_range_state') return null;
  const rows = resultOf(event)?.ridges;
  return Array.isArray(rows) ? rows.find(row => row.ridge_id === ridgeId &&
    (!row.farm_id || row.farm_id === farmId)) || null : null;
}

function soybeanFollowup(events, ridgeId, pressure) {
  const treatment = latest(events, event => method(event) === 'apply_fungicide' &&
    covers(event, 'sprayed_ridges', ridgeId));
  if (!treatment || !finite(pressure) || pressure <= 0) return false;
  const check = latest(events, event => method(event) === 'inspect_crop_health' &&
    event.sequence > treatment.sequence && covers(event, 'covered_ridges', ridgeId));
  if (!check || !finite(timeOf(check)) || !finite(timeOf(treatment)) ||
      timeOf(check) - timeOf(treatment) < 7 * DAY) return false;
  const rows = resultOf(check).observations;
  const observation = rows && Object.values(rows).find(row => row?.ridge_id === ridgeId);
  // A low-confidence detection is unknown, not proof of either cure or disease.
  return observation?.disease_present === false && finite(observation.disease_confidence) &&
    observation.disease_confidence >= CONFIDENCE;
}

function maizeFollowup(events, ridgeId, farmId, now) {
  const irrigation = latest(events, event => method(event) === 'irrigate' &&
    covers(event, 'irrigated_ridges', ridgeId));
  if (!irrigation || !finite(now) || !finite(timeOf(irrigation))) return false;
  const elapsed = now - timeOf(irrigation);
  // The scenario's acceptance contract checks the following day, within two
  // days. This time window is not a biological recovery threshold.
  if (elapsed < DAY || elapsed > 2 * DAY) return false;
  const before = latest(events, event => event.sequence < irrigation.sequence && soilReading(event, ridgeId));
  const after = latest(events, event => event.sequence > irrigation.sequence &&
    timeOf(event) - timeOf(irrigation) >= DAY && soilReading(event, ridgeId));
  const crop = latest(events, event => event.sequence > irrigation.sequence &&
    timeOf(event) - timeOf(irrigation) >= DAY && cropReading(event, ridgeId, farmId));
  if (!before || !after || !crop) return false;
  const a = soilReading(before, ridgeId), b = soilReading(after, ridgeId);
  return a.sensor_id === b.sensor_id && a.ridge_start === b.ridge_start &&
    a.ridge_end === b.ridge_end && b.vwc > a.vwc;
}

function illustration(crop, state, title, detail) {
  return {
    id: `${crop}-${state}`,
    url: `assets/media/simulated/${crop}-${state}.png`,
    title,
    caption: `${detail} Simulation illustration; not a captured image or a measured symptom assessment.`,
    kind: 'simulation illustration',
  };
}

export function selectPlantIllustration({ farm, ridge, step, events = [] } = {}) {
  const crop = farm?.crop_id, ridgeId = ridge?.ridge_id;
  if (!['soybean', 'maize'].includes(crop) || typeof farm?.id !== 'string' ||
      !Number.isInteger(step) || step < 0 || !Array.isArray(events) ||
      !Number.isInteger(ridgeId) || ridgeId < 0 ||
      (Number.isInteger(farm.num_ridges) && ridgeId >= farm.num_ridges) ||
      ridge.planted !== true || ridge.harvested !== false ||
      !finite(ridge.stand_fraction) || ridge.stand_fraction <= 0 ||
      !finite(ridge.root_vwc) || !finite(ridge.disease_pressure)) return null;
  const stage = String(ridge.growth_stage || '').toUpperCase();
  const past = events.filter(event => Number.isInteger(event?.sequence) &&
    event.sequence > 0 && event.sequence <= step).sort((a, b) => a.sequence - b.sequence);
  const local = past.filter(event => successful(event) && farmOf(event) === farm.id);
  const now = timeOf(past.at(-1));
  const name = crop === 'soybean' ? 'Soybean' : 'Maize';

  if (/^(VE|VC|V[12])(?:_|$)/.test(stage))
    return illustration(crop, 'seedling', `${name} seedling`, 'Generic reference for the recorded seedling stage.');
  if (/^V\d+(?:_|$)/.test(stage))
    return illustration(crop, 'vegetative', `${name} vegetative stage`, 'Generic reference for the recorded vegetative stage.');
  if ((crop === 'soybean' && /^R[78](?:_|$)/.test(stage)) ||
      (crop === 'maize' && /^R6(?:_|$)/.test(stage)))
    return illustration(crop, 'mature', `${name} maturity`, 'Generic reference for the recorded maturity stage.');

  if (crop === 'soybean') {
    const domain = latest(local, event => DISEASE_SURVEYS.has(event.step_id) &&
      method(event) === 'fly_survey' && covers(event, 'surveyed_ridges', ridgeId));
    if (/^R3(?:_|$)/.test(stage)) {
      if (domain && soybeanFollowup(local, ridgeId, ridge.disease_pressure))
        return illustration(crop, 'followup', 'Soybean follow-up',
          'Early pods and residual marks illustrate the post-treatment follow-up; they do not establish a cure.');
      return null;
    }
    if (!/^R[12](?:_|$)/.test(stage)) return null;
    if (domain && ridge.disease_pressure > 0)
      return illustration(crop, 'disease', 'Soybean disease context',
        'Illustrative leaf marks within the recorded disease survey area; disease pressure is a model index.');
    return illustration(crop, 'flowering', 'Soybean flowering stage',
      'Generic flowering-stage reference; this image does not assert absence of disease.');
  }

  // The available reproductive pictures depict early reproductive maize.
  // VT tasseling and R4/R5 use the existing state schematic instead.
  if (!/^R[123](?:_|$)/.test(stage)) return null;
  const domain = latest(local, event => WATER_SURVEYS.has(event.step_id) &&
    method(event) === 'fly_survey' && covers(event, 'surveyed_ridges', ridgeId));
  if (domain && /^R[23](?:_|$)/.test(stage)) {
    if (maizeFollowup(local, ridgeId, farm.id, now))
      return illustration(crop, 'followup', 'Maize water follow-up',
        'Irrigation and later soil/crop checks are recorded; the illustration retains residual water stress.');
    return illustration(crop, 'water-stress', 'Maize water-stress context',
      'Illustrative leaf posture within the recorded drought survey area; moisture values remain separate.');
  }
  return illustration(crop, 'reproductive', 'Maize reproductive stage',
    'Generic early reproductive-stage reference; this image does not assert absence of stress.');
}
