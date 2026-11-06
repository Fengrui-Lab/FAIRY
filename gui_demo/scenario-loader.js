// Keep the original scene entirely on its existing code and data path.
const isHit = new URL(location.href).searchParams.get('scenario') === 'hit';
const scenarios = [
  ['season', 'Soybean & maize · Disease and water'],
  ['hit', 'HIT smart farm · Satellite & drone'],
];
function syncSelector() {
  const select = document.querySelector('select[aria-label="Scenario"]');
  if (!select) return;
  for (const [value, label] of scenarios) {
    let option = [...select.options].find(item => item.value === value || item.textContent === label);
    if (!option) { option = document.createElement('option'); option.textContent = label; select.append(option); }
    if (option.value !== value) option.value = value;
  }
  select.value = isHit ? 'hit' : 'season';
}
document.addEventListener('change', event => {
  if (!event.target.matches('select[aria-label="Scenario"]')) return;
  const url = new URL(location.href);
  url.search = ''; url.hash = '';
  if (event.target.value === 'hit') url.searchParams.set('scenario', 'hit');
  location.assign(url.href);
});
const observer = new MutationObserver(syncSelector);
observer.observe(document.getElementById('app'), {childList: true, subtree: true});
window.addEventListener('pagehide', () => observer.disconnect(), {once: true});
try {
  if (isHit) {
    for (const path of ['scenarios/hit/styles.css', 'scenarios/hit/results.css']) {
      const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = path; document.head.append(link);
    }
    await import('./scenarios/hit/app.js');
  } else await import('./app.js');
  syncSelector();
} catch (error) {
  const host = document.getElementById('app');
  host.replaceChildren();
  const box = document.createElement('div'); box.className = 'loading';
  const title = document.createElement('b'); title.textContent = 'FAIRY 2.0 could not load';
  const message = document.createElement('p'); message.textContent = error.message;
  box.append(title, message); host.append(box); console.error(error);
}
