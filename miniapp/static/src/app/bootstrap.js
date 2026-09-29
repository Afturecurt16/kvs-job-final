let started = false;
const MAX_INIT_DATA_SESSION_KEY = 'kvs-job:max-init-data';

function launchParam(name) {
  const hash = window.location.hash.replace(/^#/, '');
  const fromHash = new URLSearchParams(hash).get(name);
  if (fromHash) return fromHash;
  return new URLSearchParams(window.location.search).get(name) || '';
}

function preserveMaxInitData() {
  const bridgeData = window.WebApp?.initData?.trim();
  // MAX normally puts WebAppData in the fragment. Some clients preserve it in
  // the query string during a WebView reload, so support both locations.
  const launchData = launchParam('WebAppData').trim();
  let cachedData = '';
  try {
    cachedData = window.sessionStorage.getItem(MAX_INIT_DATA_SESSION_KEY) || '';
  } catch {
    /* Session storage can be unavailable in restricted WebViews. */
  }
  const initData = bridgeData || launchData || cachedData;
  if (!initData) return;

  const changed = window.KVS_MAX_INIT_DATA !== initData;
  window.KVS_MAX_INIT_DATA = initData;
  if (bridgeData || launchData) {
    try {
      window.sessionStorage.setItem(MAX_INIT_DATA_SESSION_KEY, initData);
    } catch {
      /* The in-memory value is still sufficient for the current page. */
    }
  }
  if (changed) window.dispatchEvent(new Event('kvs:max-data-ready'));
}

// Some MAX clients publish launch parameters after the document has loaded.
window.addEventListener('hashchange', preserveMaxInitData);
window.addEventListener('pageshow', preserveMaxInitData);

function startApplication() {
  if (started) return;
  started = true;
  preserveMaxInitData();
  const startParam = window.WebApp?.initDataUnsafe?.start_param
    || new URLSearchParams(window.KVS_MAX_INIT_DATA || '').get('start_param')
    || launchParam('WebAppStartParam');
  if (startParam === 'notifications' && !window.location.hash.startsWith('#/')) {
    // Open the profile login first; its Events tab fetches existing
    // registrations and links a signed MAX ID to an email-only entry.
    window.location.hash = '/profile?tab=events';
  }
  import('./main.js').catch((error) => {
    console.error('Failed to start KVS Job miniapp', error);
    const app = document.querySelector('#app');
    if (app) {
      app.innerHTML = `
        <main class="screen">
          <section class="state-card">
            <strong>Не удалось запустить приложение</strong>
            <p>Обновите страницу. Если ошибка повторится, сообщите администратору.</p>
          </section>
        </main>`;
    }
  });
}

const hostname = window.location.hostname;
const isLocal = hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';

// MAX Bridge is unnecessary in a regular local browser. Skipping the remote
// script keeps development usable without internet access or access to st.max.ru.
if (isLocal || window.WebApp) {
  startApplication();
} else {
  const bridge = document.createElement('script');
  bridge.src = 'https://st.max.ru/js/max-web-app.js';
  bridge.async = true;
  bridge.addEventListener('load', () => {
    preserveMaxInitData();
    window.dispatchEvent(new Event('kvs:max-bridge-ready'));
    startApplication();
  }, { once: true });
  bridge.addEventListener('error', startApplication, { once: true });
  document.head.append(bridge);

  // A temporary MAX CDN failure must never leave the user on a blank screen.
  window.setTimeout(startApplication, 700);
}
