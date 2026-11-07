const ENDPOINT = '/api/knowledge-guidance';
const TITLE = 'Knowledge·Guidance';
const INTRO = 'Here, you can provide your agent with knowledge and guidance, as well as review the history of any knowledge or guidance you have previously supplied.';
const RESTART_MESSAGE = 'Local knowledge is not available yet. Restart the local UI server, then try again.';

let dialog, triggerEntry, triggerButton, watchedSwitch, resizeObserver;
let controls, opener, readController, readVersion = 0, dialogVersion = 0, saving = false;
let entries = {}, nextKey = null, loaded = false;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function status(message = '', kind = '') {
  controls.status.textContent = message;
  controls.status.dataset.kind = kind;
}

function updatePreview() {
  controls.preview.textContent = nextKey ? JSON.stringify({ [nextKey]: controls.text.value }, null, 2) : 'Loading the next guidance key…';
  controls.save.disabled = saving || !nextKey || !controls.text.value.trim();
}

function renderEntries() {
  controls.list.replaceChildren();
  const rows = Object.entries(entries).sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }));
  controls.count.textContent = `${rows.length} saved ${rows.length === 1 ? 'entry' : 'entries'}`;
  if (!rows.length) {
    controls.list.append(element('p', 'kg-empty', loaded ? 'No knowledge or guidance has been saved yet.' : 'Loading local knowledge…'));
    return;
  }
  for (const [key, value] of rows) {
    const item = element('article', 'kg-knowledge-item');
    item.append(element('h3', 'kg-knowledge-key', key), element('p', 'kg-knowledge-text', typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
    controls.list.append(item);
  }
}

function isNextKey(value) {
  return typeof value === 'string' && /^expert_guidance_\d{3,}$/.test(value);
}

async function readResponse(response, writing = false) {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) throw new Error(writing && response.ok ? 'The save could not be confirmed. Check Local Knowledge before trying again.' : RESTART_MESSAGE);
  let payload;
  try { payload = await response.json(); }
  catch (_) { throw new Error(writing ? 'The save could not be confirmed. Check Local Knowledge before trying again.' : RESTART_MESSAGE); }
  if (!response.ok) {
    if ([404, 405, 501].includes(response.status)) throw new Error(RESTART_MESSAGE);
    const explanation = typeof payload?.message === 'string' ? payload.message : typeof payload?.error === 'string' ? payload.error : null;
    throw new Error(explanation || (writing ? 'Your guidance could not be saved. Please try again.' : 'Local knowledge could not be loaded. Please try again.'));
  }
  return payload;
}

async function loadKnowledge({ keepStatus = false } = {}) {
  readController?.abort();
  const controller = new AbortController(), version = ++readVersion;
  readController = controller;
  controls.refresh.disabled = true;
  controls.list.setAttribute('aria-busy', 'true');
  if (!keepStatus) status('Loading local knowledge…');
  try {
    const response = await fetch(ENDPOINT, { headers: { Accept: 'application/json' }, credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
    const payload = await readResponse(response);
    if (version !== readVersion) return;
    if (!payload || !payload.entries || typeof payload.entries !== 'object' || Array.isArray(payload.entries) || !isNextKey(payload.next_key)) throw new Error(RESTART_MESSAGE);
    entries = payload.entries; nextKey = payload.next_key; loaded = true;
    renderEntries(); updatePreview();
    if (!keepStatus) status();
  } catch (error) {
    if (error.name === 'AbortError' || version !== readVersion) return;
    if (!loaded) {
      nextKey = null;
      controls.preview.textContent = 'The guidance preview will appear when local knowledge is available.';
      controls.list.replaceChildren(element('p', 'kg-empty', 'Local knowledge is currently unavailable.'));
      controls.save.disabled = true;
    }
    status(error instanceof TypeError ? 'Could not reach local knowledge. Check that the local UI server is running, then try again.' : error.message, 'error');
  } finally {
    if (version === readVersion) {
      controls.refresh.disabled = false;
      controls.list.setAttribute('aria-busy', 'false');
    }
  }
}

async function saveGuidance(event) {
  event.preventDefault();
  if (saving || !nextKey) return;
  const text = controls.text.value;
  if (!text.trim()) { status('Enter some knowledge or guidance before saving.', 'error'); controls.text.focus(); return; }
  saving = true;
  const version = dialogVersion;
  // Invalidate older reads so they cannot replace the key returned by Save.
  readController?.abort(); ++readVersion;
  controls.text.readOnly = true;
  controls.save.textContent = 'Saving…'; controls.save.disabled = true;
  controls.refresh.disabled = true;
  status('Saving guidance…');
  try {
    const response = await fetch(ENDPOINT, {
      method: 'POST', credentials: 'same-origin', headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const payload = await readResponse(response, true);
    if (version !== dialogVersion) return;
    if (!payload || !isNextKey(payload.key) || typeof payload.value !== 'string' || !isNextKey(payload.next_key)) throw new Error('The save could not be confirmed. Check Local Knowledge before trying again.');
    entries = { ...entries, [payload.key]: payload.value };
    nextKey = payload.next_key; loaded = true;
    if (controls.text.value === text) controls.text.value = '';
    renderEntries();
    status(`Saved as ${payload.key}.`, 'success');
  } catch (error) {
    if (version === dialogVersion) status(error instanceof TypeError ? 'Could not reach local knowledge. Your text is still here; check the local UI server before trying again.' : error.message, 'error');
  } finally {
    if (version === dialogVersion) {
      saving = false;
      controls.text.readOnly = false;
      controls.save.textContent = 'Save'; controls.refresh.disabled = false;
      controls.list.setAttribute('aria-busy', 'false');
      updatePreview();
    }
  }
}

function switchMode() {
  const checking = controls.mode.value === 'check';
  controls.addPanel.hidden = checking; controls.checkPanel.hidden = !checking;
  if (checking && !saving) void loadKnowledge();
  else updatePreview();
}

function closeDialog() {
  if (dialog?.open) dialog.close();
}

function isolateEscape(event) {
  if (!dialog?.open || event.key !== 'Escape') return;
  event.preventDefault(); event.stopImmediatePropagation();
  closeDialog();
}

function ensureDialog() {
  if (dialog?.isConnected) return;
  ++dialogVersion;
  dialog = element('dialog', 'kg-dialog');
  dialog.id = 'knowledge-guidance-dialog';
  dialog.setAttribute('aria-labelledby', 'kg-dialog-title');
  dialog.setAttribute('aria-describedby', 'kg-dialog-intro');
  const content = element('div', 'kg-dialog-content');
  const header = element('div', 'kg-dialog-header');
  const title = element('h2', 'kg-title', TITLE); title.id = 'kg-dialog-title';
  const close = element('button', 'kg-close', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Close Knowledge·Guidance'); close.addEventListener('click', closeDialog);
  header.append(title, close);
  const intro = element('p', 'kg-intro', INTRO); intro.id = 'kg-dialog-intro';
  const modeLabel = element('label', 'kg-label', 'Action'); modeLabel.htmlFor = 'kg-mode';
  const mode = element('select', 'kg-select'); mode.id = 'kg-mode';
  for (const [value, text] of [['add', 'Adding Extra Guidance'], ['check', 'Check Local Knowledge']]) { const option = element('option', '', text); option.value = value; mode.append(option); }
  mode.value = 'add';
  mode.addEventListener('change', switchMode);
  const addPanel = element('form', 'kg-add-panel'); addPanel.addEventListener('submit', saveGuidance);
  const textLabel = element('label', 'kg-label', 'Knowledge or guidance'); textLabel.htmlFor = 'kg-text';
  const text = element('textarea', 'kg-textarea'); text.id = 'kg-text'; text.rows = 6; text.placeholder = 'Write knowledge or guidance for your agent…';
  text.addEventListener('input', () => { if (!saving) status(); updatePreview(); });
  const saveRow = element('div', 'kg-save-row'), save = element('button', 'kg-save', 'Save'); save.type = 'submit'; save.disabled = true; saveRow.append(save);
  const previewLabel = element('h3', 'kg-section-label', 'JSON preview'), preview = element('pre', 'kg-preview'); preview.setAttribute('aria-label', 'Guidance JSON preview');
  addPanel.append(textLabel, text, saveRow, previewLabel, preview);
  const checkPanel = element('section', 'kg-check-panel'); checkPanel.hidden = true;
  const checkHeader = element('div', 'kg-check-header'), count = element('span', 'kg-count', '0 saved entries'), refresh = element('button', 'kg-refresh', 'Refresh'); refresh.type = 'button'; refresh.addEventListener('click', () => { if (!saving) void loadKnowledge(); });
  checkHeader.append(count, refresh);
  const list = element('div', 'kg-knowledge-list'); list.setAttribute('aria-label', 'Saved local knowledge'); list.tabIndex = 0;
  checkPanel.append(checkHeader, list);
  const statusNode = element('p', 'kg-status'); statusNode.setAttribute('role', 'status'); statusNode.setAttribute('aria-live', 'polite'); statusNode.setAttribute('aria-atomic', 'true');
  content.append(header, intro, modeLabel, mode, addPanel, checkPanel, statusNode); dialog.append(content);
  controls = { mode, addPanel, checkPanel, text, save, preview, list, count, refresh, status: statusNode };
  dialog.addEventListener('cancel', event => { event.preventDefault(); event.stopPropagation(); closeDialog(); });
  let backdropDown = false;
  const outside = event => { const bounds = dialog.getBoundingClientRect(); return event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom; };
  dialog.addEventListener('pointerdown', event => { backdropDown = event.target === dialog && outside(event); });
  dialog.addEventListener('click', event => { event.stopPropagation(); if (backdropDown && event.target === dialog && outside(event)) closeDialog(); backdropDown = false; });
  dialog.addEventListener('close', () => { const target = opener?.isConnected ? opener : triggerButton; if (target?.isConnected) target.focus({ preventScroll: true }); });
  document.body.append(dialog);
  window.addEventListener('keydown', isolateEscape, true);
  window.addEventListener('resize', measureTrigger);
  renderEntries(); updatePreview();
}

function openDialog() {
  ensureDialog();
  if (dialog.open) return;
  opener = document.activeElement;
  dialog.showModal();
  (controls.mode.value === 'add' ? controls.text : controls.mode).focus({ preventScroll: true });
  if (!saving) void loadKnowledge();
}

function measureTrigger() {
  if (!watchedSwitch?.isConnected || !triggerEntry?.isConnected) return;
  const bounds = watchedSwitch.getBoundingClientRect();
  if (bounds.height > 0) triggerEntry.style.height = `${bounds.height}px`;
  const sample = watchedSwitch.querySelector('button');
  if (sample) {
    const font = getComputedStyle(sample);
    for (const property of ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight']) triggerButton.style[property] = font[property];
  }
}

/** Call after either scene renders #app. The shared dialog lives outside it. */
export function syncKnowledgeGuidance() {
  const modeSwitch = document.querySelector('.sidebar .mode-switch');
  if (!modeSwitch) return;
  ensureDialog();
  if (!triggerEntry?.isConnected || triggerEntry.parentElement !== modeSwitch.parentElement) {
    triggerEntry?.remove();
    triggerEntry = element('div', 'kg-entry'); triggerEntry.dataset.knowledgeGuidance = 'trigger';
    triggerButton = element('button', 'kg-trigger', TITLE); triggerButton.type = 'button'; triggerButton.setAttribute('aria-haspopup', 'dialog'); triggerButton.setAttribute('aria-controls', dialog.id);
    triggerButton.addEventListener('click', openDialog); triggerEntry.append(triggerButton);
    modeSwitch.before(triggerEntry);
  } else if (triggerEntry.nextElementSibling !== modeSwitch) modeSwitch.before(triggerEntry);
  if (watchedSwitch !== modeSwitch) {
    resizeObserver?.disconnect(); watchedSwitch = modeSwitch;
    if (typeof ResizeObserver !== 'undefined') { resizeObserver = new ResizeObserver(measureTrigger); resizeObserver.observe(modeSwitch); }
  }
  measureTrigger();
}

export function destroyKnowledgeGuidance() {
  readController?.abort(); ++readVersion; ++dialogVersion; saving = false; resizeObserver?.disconnect();
  window.removeEventListener('keydown', isolateEscape, true); window.removeEventListener('resize', measureTrigger);
  triggerEntry?.remove(); dialog?.remove();
  triggerEntry = triggerButton = watchedSwitch = dialog = null;
}
