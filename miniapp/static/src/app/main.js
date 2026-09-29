import { navigate, parseRoute, setRoute } from './router.js';
import {
  addPartnerDepartment,
  addAdminDeveloper,
  addAdminPlace,
  isAdminProfile,
  logoutProfile,
  removePartnerDepartment,
  setAdminMode,
  setPartnerDraft,
  startCreateEvent,
  startCreatePartner,
  startEditEvent,
  startEditPartner,
  startProfileLogin,
  store,
  submitProfileEmail,
  toggleFavorite,
} from './store.js';
import { icons } from '../components/icons.js';
import { appShell, button, emptyState } from '../components/ui.js';
import { renderEvents, renderEventsLoading } from '../features/events.js';
import { renderJobs, renderJobsLoading } from '../features/jobs.js';
import { renderNotifications, renderNotificationsLoading } from '../features/notifications.js';
import {
  renderDepartmentDetail,
  renderPartnerDetail,
  renderPartnerDetailLoading,
  renderPartners,
  renderPartnersLoading,
} from '../features/partners.js';
import { renderProfile, renderProfileLoading } from '../features/profile.js';
import { renderVacancyDetail, renderVacancyDetailLoading } from '../features/vacancyDetails.js';
import {
  createEvent,
  createPartner,
  deleteEvent,
  deletePartner,
  downloadAdminMetrics,
  getAdminEvents,
  getMyEvents,
  getUnreadNotificationCount,
  getSubscriptionStatus,
  markMyNotificationsRead,
  registerEvent,
  sendEventMessage,
  syncAdminVacancies,
  trackMetric,
  unregisterEvent,
  uploadEventImage,
  updateEvent,
  updatePartner,
  updateProfile,
} from '../services/api.js';

const app = document.querySelector('#app');
let maxBridge = window.WebApp || {};
const METRICS_SESSION_KEY = 'kvs-job:metrics-session';
// Signed MAX initData is the reliable signal that the app is embedded.
let isEmbedded = Boolean(maxBridge?.initData || window.KVS_MAX_INIT_DATA);

function metricsSessionId() {
  let value = window.localStorage.getItem(METRICS_SESSION_KEY);
  if (!value) {
    value = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    window.localStorage.setItem(METRICS_SESSION_KEY, value);
  }
  return value;
}

function recordMetric(eventType, action, route, target = '', metadata = {}) {
  if (isAdminProfile()) return;
  trackMetric({
    eventType,
    action,
    route: route || '/',
    target: String(target || '').slice(0, 255),
    sessionId: metricsSessionId(),
    metadata,
  });
}

maxBridge?.ready?.();
maxBridge?.expand?.();
maxBridge?.disableVerticalSwipes?.();

const THEME_COLORS = {
  light: { header: '#ffffff', bg: '#f2f2f2' },
  dark: { header: '#1c1c1e', bg: '#121214' },
};

function applyTheme(scheme) {
  const theme = scheme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme].header);
  maxBridge?.setHeaderColor?.(THEME_COLORS[theme].header);
  maxBridge?.setBackgroundColor?.(THEME_COLORS[theme].bg);
}

function resolveScheme() {
  if (isEmbedded) return maxBridge.colorScheme === 'dark' ? 'dark' : 'light';
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

applyTheme(resolveScheme());
if (isEmbedded) {
  maxBridge.onEvent?.('themeChanged', () => applyTheme(resolveScheme()));
} else {
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(resolveScheme()));
}
window.addEventListener('kvs:max-bridge-ready', () => {
  const wasEmbedded = isEmbedded;
  maxBridge = window.WebApp || {};
  isEmbedded = Boolean(maxBridge.initData || window.KVS_MAX_INIT_DATA);
  maxBridge.ready?.();
  maxBridge.expand?.();
  maxBridge.disableVerticalSwipes?.();
  if (isEmbedded) {
    maxBridge.onEvent?.('themeChanged', () => applyTheme(resolveScheme()));
    maxBridge.BackButton?.onClick(goBack);
    if (store.route) syncBackButton(store.route);
  }
  applyTheme(resolveScheme());
  if (!wasEmbedded && isEmbedded && !store.subscription.checked) render({ silent: true });
});

function haptic(type = 'light') {
  maxBridge?.HapticFeedback?.impactOccurred(type);
}

/* ─── Navigation direction & view transitions ─────────────────── */
// Route "depth": deeper routes slide in (push), shallower slide out (pop),
// same-level tab switches slide sideways following the tab order.
const ROUTE_LEVELS = { vacancies: 1, partners: 1, events: 1, profile: 1, notifications: 2, 'vacancy-detail': 2, 'partner-detail': 2, 'department-detail': 3 };
const TAB_ORDER = { vacancies: 0, partners: 1, events: 2, profile: 3 };
const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
const scrollMemory = new Map();
let prevRoute = null;
let lastTrackedRouteKey = '';

function routeKey(route) {
  const query = route.params.toString();
  return query ? `${route.path}?${query}` : route.path;
}

function directionFor(prev, next) {
  if (!prev) return 'fade';
  const from = ROUTE_LEVELS[prev.name] ?? 1;
  const to = ROUTE_LEVELS[next.name] ?? 1;
  if (to > from) return 'push';
  if (to < from) return 'pop';
  const a = TAB_ORDER[prev.name];
  const b = TAB_ORDER[next.name];
  if (a !== undefined && b !== undefined && a !== b) return b > a ? 'tab-forward' : 'tab-back';
  return 'fade';
}

// Never let a caller wait on a promise indefinitely — transition.finished can
// reject (transition interrupted by another navigation) or, in rare browser
// edge cases, simply never settle. Capping the wait keeps render() from
// hanging forever if that happens.
function withTimeout(promise, ms) {
  return Promise.race([
    Promise.resolve(promise).catch(() => {}),
    new Promise((resolve) => window.setTimeout(resolve, ms)),
  ]);
}

// Returns a promise that resolves once it's safe to mutate the DOM again —
// once the slide animation has finished (or ANIMATION_MAX_WAIT_MS elapses,
// whichever first), not just once the callback ran. render() awaits this
// before swapping the loading skeleton for real content: replacing innerHTML
// mid-animation (which happens whenever data arrives faster than the ~300ms
// transition) changed the live page's height under the still-playing
// transition and looked like the whole screen jerking/scrolling.
const ANIMATION_MAX_WAIT_MS = 400;

function swapView(html, direction, scrollTop = null) {
  const apply = () => {
    app.innerHTML = html;
    bindInputs();
    if (scrollTop !== null) window.scrollTo({ top: scrollTop, behavior: 'instant' });
  };

  if (reduceMotion?.matches || !document.startViewTransition) {
    apply();
    return Promise.resolve();
  }

  document.documentElement.dataset.nav = direction;
  const transition = document.startViewTransition(apply);
  const cleanup = () => {
    if (document.documentElement.dataset.nav === direction) delete document.documentElement.dataset.nav;
  };
  transition.finished.finally(cleanup);
  // Never render the resolved view before the transition has run its DOM
  // update callback. A fast API response can otherwise paint the real view
  // first, then let a delayed callback replace it with the loading skeleton.
  return transition.updateCallbackDone
    .catch(() => {})
    .then(() => withTimeout(transition.finished, ANIMATION_MAX_WAIT_MS));
}

/* ─── MAX native back button on nested screens ───────────────── */
function goBack() {
  if (window.history.length > 1) {
    window.history.back();
  } else {
    navigate('/vacancies');
  }
}

if (isEmbedded && maxBridge.BackButton) maxBridge.BackButton.onClick(goBack);

function syncBackButton(route) {
  if (!isEmbedded || !maxBridge.BackButton) return;
  if ((ROUTE_LEVELS[route.name] ?? 1) > 1) {
    maxBridge.BackButton.show();
  } else {
    maxBridge.BackButton.hide();
  }
}

/* ─── Toast ───────────────────────────────────────────────────── */
let toastTimer = 0;

function showToast(message, icon = '') {
  document.querySelector('.toast')?.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  el.innerHTML = `${icon}<span></span>`;
  el.querySelector('span').textContent = message;
  document.body.append(el);
  requestAnimationFrame(() => el.classList.add('is-visible'));
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    el.classList.remove('is-visible');
    window.setTimeout(() => el.remove(), 320);
  }, 2100);
}

function updateFavoriteCounters() {
  const count = store.favorites.size;
  document.querySelectorAll('[data-favorites-count]').forEach((el) => {
    el.textContent = count;
    el.hidden = count === 0;
  });
}

function updateNotificationBadge() {
  const badge = document.querySelector('.notification-button span');
  if (!badge) return;
  badge.textContent = store.notificationsCount > 99 ? '99+' : String(store.notificationsCount);
  badge.hidden = store.notificationsCount === 0;
}

function loadingFor(route) {
  if (route.name === 'partners') return renderPartnersLoading();
  if (route.name === 'partner-detail' || route.name === 'department-detail') return renderPartnerDetailLoading();
  if (route.name === 'events') return renderEventsLoading();
  if (route.name === 'notifications') return renderNotificationsLoading();
  if (route.name === 'profile') return renderProfileLoading();
  if (route.name === 'vacancy-detail') return renderVacancyDetailLoading();
  return renderJobsLoading();
}

async function viewFor(route) {
  if (route.name === 'partners') return renderPartners();
  if (route.name === 'partner-detail') return renderPartnerDetail(route.id);
  if (route.name === 'department-detail') return renderDepartmentDetail(route.partnerId, route.departmentId);
  if (route.name === 'events') return renderEvents();
  if (route.name === 'notifications') return renderNotifications();
  if (route.name === 'profile') return renderProfile(route);
  if (route.name === 'vacancy-detail') return renderVacancyDetail(route.id);
  return renderJobs();
}

async function refreshSubscription() {
  try {
    const data = await getSubscriptionStatus();
    store.subscription = { checked: true, error: '', ...data };
  } catch (error) {
    store.subscription = {
      ...store.subscription,
      checked: true,
      subscribed: false,
      error: error.message || 'Не удалось проверить подписку в MAX',
    };
  }
}

function subscriptionGate() {
  const subscription = store.subscription;
  const actions = `
    ${subscription.channelUrl ? button('Открыть канал в MAX', { action: 'open-max-channel', icon: icons.arrowUpRight }) : ''}
    ${button('Проверить подписку', { variant: 'ghost', action: 'check-max-subscription', icon: icons.check })}`;
  const text = subscription.error
    || 'Подпишитесь на канал проекта в MAX, затем нажмите «Проверить подписку».';
  return appShell(emptyState('Нужна подписка на канал', text, icons.bell, actions));
}

async function render({ silent = false, transition = null } = {}) {
  const route = parseRoute();
  const key = routeKey(route);
  const prev = prevRoute;
  const direction = transition ?? directionFor(prev, route);
  setRoute(route);
  prevRoute = { name: route.name, key };
  syncBackButton(route);

  const focused = document.activeElement;
  const focusedId = focused?.id;
  const selStart = focused?.selectionStart;
  const selEnd = focused?.selectionEnd;

  let scrollTarget = 0;
  let transitionDone = Promise.resolve();
  if (!silent) {
    if (prev && prev.key !== key) scrollMemory.set(prev.key, window.scrollY);
    scrollTarget = direction === 'pop' ? scrollMemory.get(key) ?? 0 : 0;
    transitionDone = swapView(loadingFor(route), direction, scrollTarget);
  }

  if (isEmbedded && !store.subscription.checked) await refreshSubscription();
  if (isEmbedded && (!store.subscription.subscribed || store.subscription.error)) {
    await transitionDone;
    app.innerHTML = subscriptionGate();
    return;
  }

  const [html] = await Promise.all([viewFor(route), transitionDone]);
  if (store.route !== route) return;

  app.innerHTML = html;
  bindInputs();
  if (route.name === 'notifications' && store.profileEmail && store.notificationsThroughId) {
    const accountEmail = store.profileEmail;
    const throughId = store.notificationsThroughId;
    markMyNotificationsRead(throughId).then((data) => {
      if (store.profileEmail !== accountEmail) return;
      store.notificationsCount = Number(data.unreadCount || 0);
      updateNotificationBadge();
    }).catch((error) => console.warn('Could not mark notifications as read', error));
  }
  if (route.name === 'events' && store.profileEmail) refreshNotificationCount();
  if (!silent) window.scrollTo({ top: scrollTarget, behavior: 'instant' });

  if (lastTrackedRouteKey !== key) {
    lastTrackedRouteKey = key;
    recordMetric('page_view', 'view', route.path, '', { query: route.params.toString() });
  }

  if (silent && focusedId) {
    const el = document.getElementById(focusedId);
    if (el) {
      el.focus({ preventScroll: true });
      if (typeof selStart === 'number' && el.setSelectionRange) {
        try {
          el.setSelectionRange(selStart, selEnd);
        } catch {
          /* not a text-selectable input, ignore */
        }
      }
    }
  }
}

function bindInputs() {
  const search = document.querySelector('#vacancySearch');
  if (search) {
    search.addEventListener('input', (e) => {
      store.filters.vacancyQuery = e.target.value;
      window.clearTimeout(search._timer);
      search._timer = window.setTimeout(() => render({ silent: true }), 220);
    });
  }
}

function openExternal(url) {
  if (!url) return;
  haptic('medium');
  if (maxBridge?.openLink) {
    maxBridge.openLink(url);
  } else {
    window.open(url, '_blank', 'noopener');
  }
}

function shareVacancy(url) {
  if (!url) return;
  const title = document.querySelector('.detail-content h1')?.textContent?.trim() || 'Вакансия';
  const text = `${title} — нашёл в KVS Job`;

  if (isEmbedded && maxBridge.shareMaxContent) {
    maxBridge.shareMaxContent({ text, link: url });
  } else if (navigator.share) {
    navigator.share({ title, text, url }).catch(() => {});
  } else if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(url).then(() => showToast('Ссылка скопирована', icons.link)).catch(() => {});
  }
}

function readPartnerDraft() {
  return {
    name: document.querySelector('#adminPartnerName')?.value?.trim() || '',
    logo: document.querySelector('#adminPartnerLogo')?.value?.trim() || '',
    description: document.querySelector('#adminPartnerDescription')?.value?.trim() || '',
    achievements: document.querySelector('#adminPartnerAchievements')?.value?.trim() || '',
    parentId: document.querySelector('#adminPartnerParent')?.value
      ? Number(document.querySelector('#adminPartnerParent').value)
      : null,
    isActive: document.querySelector('#adminPartnerActive')?.checked ?? true,
    departments: [...document.querySelectorAll('[data-partner-department]')].map((row) => ({
      name: row.querySelector('[data-department-name]')?.value?.trim() || '',
      description: row.querySelector('[data-department-description]')?.value?.trim() || '',
    })),
  };
}

document.addEventListener('click', (e) => {
  const target = e.target.closest('[data-action]');
  if (!target) return;

  const action = target.dataset.action;
  haptic();
  const metricTarget = target.dataset.route
    || target.dataset.value
    || target.getAttribute('aria-label')
    || target.textContent?.trim().replace(/\s+/g, ' ')
    || target.dataset.id
    || '';
  recordMetric('click', action, parseRoute().path, metricTarget, {
    entityId: target.dataset.id || null,
  });

  if (action === 'navigate') navigate(target.dataset.route);
  if (action === 'back') goBack();
  if (action === 'open-link' || action === 'apply') openExternal(target.dataset.url);
  if (action === 'share-vacancy') shareVacancy(target.dataset.url);
  if (action === 'open-max-channel') {
    const url = store.subscription.channelUrl;
    if (url) maxBridge?.openMaxLink ? maxBridge.openMaxLink(url) : window.open(url, '_blank', 'noopener');
  }
  if (action === 'check-max-subscription') {
    target.disabled = true;
    store.subscription.checked = false;
    refreshSubscription().then(() => render());
  }

  if (action === 'toggle-event-registration') {
    e.preventDefault();
    if (!store.profileEmail) {
      maxBridge?.HapticFeedback?.notificationOccurred?.('warning');
      startProfileLogin();
      navigate('/profile');
      return;
    }
    const eventId = target.dataset.id;
    const isRegistered = target.dataset.registered === 'true';
    target.disabled = true;
    (isRegistered ? unregisterEvent(eventId) : registerEvent(eventId))
      .then((result) => {
        maxBridge?.HapticFeedback?.notificationOccurred?.(isRegistered ? 'warning' : 'success');
        const message = isRegistered
          ? 'Вы отказались от участия'
          : result?.registrationStatus === 'reserve'
            ? `Вы в резерве${result.reservePosition ? ` · позиция ${result.reservePosition}` : ''}. Как только освободится место, мы сообщим здесь.`
            : 'Вы зарегистрированы. Место подтверждено.';
        showToast(message, isRegistered ? icons.trash : icons.check);
        if (!isRegistered) {
          if (maxBridge?.showAlert) maxBridge.showAlert(message);
          else window.alert(message);
        }
        render({ silent: true });
      })
      .catch((error) => {
        target.disabled = false;
        maxBridge?.HapticFeedback?.notificationOccurred?.('error');
        if (error.status === 403) store.subscription.checked = false;
        showToast(error.message || 'Не удалось изменить регистрацию', icons.link);
        if (error.status === 403) render();
      });
  }

  if (action === 'start-profile-login') {
    startProfileLogin();
    render();
  }

  if (action === 'submit-profile-email') {
    const email = document.querySelector('#profileEmail')?.value;
    const ok = submitProfileEmail(email);
    if (!ok) maxBridge?.HapticFeedback?.notificationOccurred?.('error');
    render().then(() => { if (!ok) document.querySelector('#profileEmail')?.focus(); });
    if (ok) {
      // Refresh the account's event list and in-app notification badge.
      const accountEmail = store.profileEmail;
      Promise.all([getMyEvents(), getUnreadNotificationCount()]).then(([events, notifications]) => {
        if (store.profileEmail !== accountEmail) return;
        store.myEvents = events.items || [];
        store.notificationsCount = Number(notifications.unreadCount || 0);
        render({ silent: true });
      }).catch((error) => console.warn('Could not load account notifications', error));
    }
  }

  if (action === 'logout-profile') {
    logoutProfile();
    render();
  }

  if (action === 'edit-student-profile') {
    const profile = store.profileData || {};
    store.profileDraft = {
      faculty: profile.faculty || '',
      course: profile.course || '',
      group: profile.group || '',
    };
    store.profileEditError = '';
    store.profileEditing = true;
    render({ silent: true });
  }

  if (action === 'cancel-student-profile-edit') {
    store.profileEditing = false;
    store.profileEditError = '';
    render({ silent: true });
  }

  if (action === 'save-student-profile') {
    const accountEmail = store.profileEmail;
    store.profileDraft = {
      faculty: document.querySelector('#studentFaculty')?.value.trim() || '',
      course: document.querySelector('#studentCourse')?.value.trim() || '',
      group: document.querySelector('#studentGroup')?.value.trim() || '',
    };
    target.disabled = true;
    updateProfile(store.profileDraft).then((profile) => {
      if (store.profileEmail !== accountEmail) return;
      store.profileData = profile;
      store.profileEditing = false;
      store.profileEditError = '';
      showToast('Профиль сохранён', icons.check);
      render({ silent: true });
    }).catch((error) => {
      if (store.profileEmail !== accountEmail) return;
      store.profileEditError = error.message || 'Не удалось сохранить профиль';
      render({ silent: true });
    });
  }

  if (action === 'admin-mode') {
    setAdminMode(target.dataset.route);
    render();
  }

  if (action === 'set-admin-section') {
    store.adminSection = target.dataset.value || 'events';
    render();
  }

  if (action === 'sync-admin-vacancies') {
    target.disabled = true;
    store.adminVacancySyncStatus = 'Загружаем вакансии из Google Таблицы…';
    render();
    syncAdminVacancies()
      .then((result) => {
        store.adminVacancySyncStatus = `Готово: загружено вакансий — ${result.sourceCount || 0}.`;
        showToast(`Вакансии обновлены: ${result.sourceCount || 0}`, icons.check);
        render();
      })
      .catch((error) => {
        store.adminVacancySyncStatus = error.message || 'Не удалось обновить вакансии.';
        target.disabled = false;
        showToast(error.message || 'Не удалось обновить вакансии', icons.link);
        render();
      });
  }

  if (action === 'add-admin-developer') {
    const ok = addAdminDeveloper({
      name: document.querySelector('#adminDeveloperName')?.value,
      email: document.querySelector('#adminDeveloperEmail')?.value,
    });
    if (!ok) maxBridge?.HapticFeedback?.notificationOccurred?.('error');
    render().then(() => { if (!ok) document.querySelector('#adminDeveloperName')?.focus(); });
  }

  if (action === 'add-admin-place') {
    const ok = addAdminPlace({
      title: document.querySelector('#adminPlaceTitle')?.value,
      address: document.querySelector('#adminPlaceAddress')?.value,
    });
    if (!ok) maxBridge?.HapticFeedback?.notificationOccurred?.('error');
    render().then(() => { if (!ok) document.querySelector('#adminPlaceTitle')?.focus(); });
  }

  if (action === 'add-admin-partner-department') {
    setPartnerDraft(readPartnerDraft());
    addPartnerDepartment();
    render({ silent: true });
  }

  if (action === 'remove-admin-partner-department') {
    setPartnerDraft(readPartnerDraft());
    removePartnerDepartment(Number(target.dataset.index));
    render({ silent: true });
  }

  if (action === 'submit-admin-partner') {
    const payload = readPartnerDraft();
    setPartnerDraft(payload);
    if (!payload.name) {
      store.adminPartnerError = 'Укажи название компании';
      maxBridge?.HapticFeedback?.notificationOccurred?.('error');
      render().then(() => document.querySelector('#adminPartnerName')?.focus());
    } else {
      payload.departments = payload.departments.filter((item) => item.name);
      const editingId = store.adminPartnerEditingId;
      (editingId ? updatePartner(editingId, payload) : createPartner(payload))
        .then(() => {
          startCreatePartner();
          maxBridge?.HapticFeedback?.notificationOccurred?.('success');
          showToast(editingId ? 'Партнер обновлен' : 'Партнер добавлен', icons.check);
          render();
        })
        .catch((error) => {
          store.adminPartnerError = error.message || 'Не удалось сохранить партнера';
          maxBridge?.HapticFeedback?.notificationOccurred?.('error');
          render();
        });
    }
  }

  if (action === 'edit-admin-partner') {
    const partner = store.adminPartners.find((item) => item.id === target.dataset.id);
    if (partner) {
      startEditPartner(partner);
      render().then(() => document.querySelector('.partner-admin-window')?.scrollIntoView({ behavior: 'smooth' }));
    }
  }

  if (action === 'cancel-admin-partner') {
    startCreatePartner();
    render();
  }

  if (action === 'delete-admin-partner') {
    const partnerId = target.dataset.id;
    if (window.confirm('Удалить этого партнера из приложения?')) {
      deletePartner(partnerId)
        .then(() => {
          if (store.adminPartnerEditingId === partnerId) startCreatePartner();
          maxBridge?.HapticFeedback?.notificationOccurred?.('success');
          showToast('Партнер удален', icons.trash);
          render();
        })
        .catch((error) => {
          store.adminPartnerError = error.message || 'Не удалось удалить партнера';
          maxBridge?.HapticFeedback?.notificationOccurred?.('error');
          render();
        });
    }
  }

  if (action === 'set-admin-metrics-range') {
    store.adminMetricsRange = Number(target.dataset.days) || 30;
    store.adminMetrics = null;
    store.adminMetricsError = '';
    render({ silent: true });
  }

  if (action === 'download-admin-metrics') {
    downloadAdminMetrics(store.adminMetricsRange)
      .then(() => showToast('Статистика скачана', icons.download))
      .catch((error) => {
        store.adminMetricsError = error.message || 'Не удалось скачать статистику';
        maxBridge?.HapticFeedback?.notificationOccurred?.('error');
        render({ silent: true });
      });
  }

  if (action === 'submit-admin-event') {
    const title = document.querySelector('#adminEventTitle')?.value?.trim() || '';
    const capacity = Number(document.querySelector('#adminEventCapacity')?.value || 0);
    if (!title || !Number.isInteger(capacity) || capacity < 1) {
      store.adminEventError = !title ? 'Укажи название мероприятия' : 'Укажи лимит участников больше нуля';
      maxBridge?.HapticFeedback?.notificationOccurred?.('error');
      showToast(store.adminEventError, icons.link);
      document.querySelector(!title ? '#adminEventTitle' : '#adminEventCapacity')?.focus();
    } else {
      const editingId = store.adminEventEditingId;
      const imageFile = document.querySelector('#adminEventImageFile')?.files?.[0];
      target.disabled = true;
      Promise.resolve()
        .then(async () => {
          let image = document.querySelector('#adminEventImage')?.value?.trim() || '';
          if (imageFile) image = (await uploadEventImage(imageFile)).url;
          const payload = {
            title,
            capacity,
            category: document.querySelector('#adminEventCategory')?.value?.trim() || '',
            format: document.querySelector('#adminEventFormat')?.value?.trim() || '',
            lead: document.querySelector('#adminEventLead')?.value?.trim() || '',
            date: document.querySelector('#adminEventDate')?.value?.trim() || '',
            startsAt: document.querySelector('#adminEventStartsAt')?.value
              ? new Date(document.querySelector('#adminEventStartsAt').value).toISOString()
              : null,
            place: document.querySelector('#adminEventPlace')?.value?.trim() || '',
            description: document.querySelector('#adminEventDescription')?.value?.trim() || '',
            deadline: document.querySelector('#adminEventDeadline')?.value?.trim() || '',
            image,
            url: document.querySelector('#adminEventUrl')?.value?.trim() || '',
            isActive: document.querySelector('#adminEventActive')?.checked ?? true,
          };
          return editingId ? updateEvent(editingId, payload) : createEvent(payload);
        })
        .then(() => {
          store.adminEventError = '';
          startCreateEvent();
          maxBridge?.HapticFeedback?.notificationOccurred?.('success');
          showToast(editingId ? 'Мероприятие обновлено' : 'Мероприятие добавлено', icons.check);
          render();
        })
        .catch((error) => {
          target.disabled = false;
          store.adminEventError = error.message || 'Не удалось сохранить мероприятие';
          maxBridge?.HapticFeedback?.notificationOccurred?.('error');
          showToast(store.adminEventError, icons.link);
        });
    }
  }

  if (action === 'edit-admin-event') {
    const eventToEdit = store.adminEvents.find((item) => item.id === target.dataset.id);
    const openEditor = (event) => {
      if (!event) {
        maxBridge?.HapticFeedback?.notificationOccurred?.('error');
        showToast('Не удалось открыть мероприятие для редактирования', icons.link);
        return;
      }
      startEditEvent(event);
      store.adminMode = 'panel';
      // This button also lives on public event cards (Мероприятия tab) now —
      // the edit *form* only exists in the admin panel, so jump there when
      // clicked from anywhere else instead of re-rendering in place.
      if (parseRoute().name === 'profile') {
        render();
        window.scrollTo({ top: 0, behavior: 'instant' });
      } else {
        navigate('/profile');
      }
    };

    // Public event cards intentionally omit capacity. Fetch the administrator
    // version before opening the form, otherwise saving would erase the limit.
    if (!Number.isInteger(eventToEdit?.capacity)) {
      target.disabled = true;
      getAdminEvents()
        .then((data) => {
          store.adminEvents = data.items || [];
          openEditor(store.adminEvents.find((item) => item.id === target.dataset.id));
        })
        .catch((error) => {
          showToast(error.message || 'Не удалось загрузить лимит мероприятия', icons.link);
        })
        .finally(() => { target.disabled = false; });
    } else {
      openEditor(eventToEdit);
    }
  }

  if (action === 'cancel-admin-event') {
    startCreateEvent();
    render();
  }

  if (action === 'send-admin-event-message') {
    const row = target.closest('[data-admin-event-row]');
    const text = row?.querySelector('[data-event-message-text]')?.value?.trim() || '';
    const audience = row?.querySelector('[data-event-message-audience]')?.value || 'all';
    if (!text) {
      showToast('Введите текст сообщения', icons.link);
    } else {
      target.disabled = true;
      sendEventMessage(target.dataset.id, { text, audience })
        .then((result) => {
          const sent = Number(result.sent || 0);
          maxBridge?.HapticFeedback?.notificationOccurred?.(sent ? 'success' : 'warning');
          showToast(sent
            ? `Добавлено в уведомления: ${sent} из ${result.total}`
            : 'Для выбранной группы нет участников', icons.mail);
          if (sent && row?.querySelector('[data-event-message-text]')) row.querySelector('[data-event-message-text]').value = '';
          target.disabled = false;
        })
        .catch((error) => {
          target.disabled = false;
          maxBridge?.HapticFeedback?.notificationOccurred?.('error');
          showToast(error.message || 'Не удалось отправить сообщение', icons.link);
        });
    }
  }

  if (action === 'delete-admin-event') {
    const eventId = target.dataset.id;
    const runDelete = () => {
      deleteEvent(eventId)
        .then(() => {
          if (store.adminEventEditingId === eventId) startCreateEvent();
          maxBridge?.HapticFeedback?.notificationOccurred?.('success');
          showToast('Мероприятие удалено', icons.trash);
          render();
        })
        .catch((error) => {
          const message = error.message || 'Не удалось удалить мероприятие';
          store.adminEventError = message;
          maxBridge?.HapticFeedback?.notificationOccurred?.('error');
          // The admin panel's own error banner isn't visible from other
          // screens (e.g. this button also lives on public event cards now),
          // so show a toast too rather than failing silently there.
          showToast(message, icons.link);
          render();
        });
    };
    // Native confirmation availability varies by MAX client version.
    // API version — on a client that doesn't support it, it can silently do
    // nothing (no error, no callback), which looked exactly like "delete is
    // broken". window.confirm() is a plain browser API and works reliably
    // inside the embedded WebView regardless of bridge version.
    if (window.confirm('Удалить это мероприятие?')) {
      runDelete();
    }
  }

  if (action === 'set-vacancy-category') {
    store.filters.vacancyCategory = target.dataset.value;
    render();
  }

  if (action === 'set-event-category') {
    store.filters.eventCategory = target.dataset.value;
    render();
  }

  if (action === 'reset-vacancy-filters') {
    store.filters.vacancyQuery = '';
    store.filters.vacancyCategory = 'Все';
    render();
  }

  if (action === 'toggle-favorite') {
    e.preventDefault();
    e.stopPropagation();
    if (!store.profileEmail) {
      startProfileLogin();
      showToast('Сначала войдите по почте, чтобы сохранять вакансии', icons.user);
      navigate('/profile');
      return;
    }
    const id = target.dataset.id;
    toggleFavorite(id);
    const active = store.favorites.has(id);
    maxBridge?.HapticFeedback?.notificationOccurred?.(active ? 'success' : 'warning');

    // Update hearts in place so the pop animation plays instead of a full re-render.
    document.querySelectorAll('.heart-btn').forEach((btn) => {
      if (btn.dataset.id !== id) return;
      btn.classList.toggle('is-active', active);
      btn.innerHTML = active ? icons.heart : icons.heartOutline;
      btn.setAttribute('aria-label', active ? 'Убрать из избранного' : 'Добавить в избранное');
      btn.classList.remove('heart-pop');
      void btn.offsetWidth;
      btn.classList.add('heart-pop');
    });
    updateFavoriteCounters();
    showToast(active ? 'Добавлено в избранное' : 'Убрано из избранного', active ? icons.heart : icons.heartOutline);

    if (store.route?.name === 'profile' && store.profileTab === 'favorites') render({ silent: true });
  }

  if (action === 'profile-tab') {
    store.profileTab = target.dataset.value;
    navigate(`/profile?tab=${store.profileTab}`);
  }
});

window.addEventListener('hashchange', () => render());
window.addEventListener('kvs:max-data-ready', () => {
  if (!store.profileEmail) return;
  getMyEvents().then((data) => {
    store.myEvents = data.items || [];
    render({ silent: true });
  }).catch((error) => console.warn('Could not refresh MAX identity', error));
});

let notificationCountLoading = false;
async function refreshNotificationCount() {
  if (document.hidden || !store.profileEmail) return;
  if (notificationCountLoading) return;
  notificationCountLoading = true;
  const email = store.profileEmail;
  try {
    const data = await getUnreadNotificationCount();
    if (store.profileEmail !== email) return;
    const count = Number(data.unreadCount || 0);
    if (count !== store.notificationsCount) {
      store.notificationsCount = count;
      if (['events', 'notifications'].includes(store.route?.name)) render({ silent: true });
    }
  } catch {
    // Keep the last count; opening the inbox will show a loading error if needed.
  } finally {
    notificationCountLoading = false;
  }
}

window.setInterval(refreshNotificationCount, 30000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refreshNotificationCount();
});
render();
