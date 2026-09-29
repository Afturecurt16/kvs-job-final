const FAVORITES_KEY = 'kvs-job:favorites';
const ADMIN_EMAIL = '253103@edu.fa.ru';
const PROFILE_EMAIL_KEY = 'kvs-job:profile-email';
const ADMIN_DEVELOPERS_KEY = 'kvs-job:admin-developers';
const ADMIN_PLACES_KEY = 'kvs-job:admin-places';

function readList(key) {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function favoritesKey(email = '') {
  const normalized = String(email || '').trim().toLowerCase();
  return normalized ? `${FAVORITES_KEY}:${normalized}` : null;
}

export function readFavorites(email = '') {
  const key = favoritesKey(email);
  if (!key) return new Set();
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || '[]');
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

function emptyEventDraft() {
  return {
    category: '',
    format: 'Офлайн',
    image: '',
    lead: '',
    title: '',
    date: '',
    startsAt: '',
    place: '',
    description: '',
    deadline: '',
    url: '',
    capacity: '',
    isActive: true,
  };
}

function emptyPartnerDraft() {
  return {
    name: '',
    logo: '',
    description: '',
    achievements: '',
    parentId: '',
    isActive: true,
    departments: [{ name: '', description: '' }],
  };
}

export const store = {
  route: null,
  filters: {
    vacancyQuery: '',
    vacancyCategory: 'Все',
    eventCategory: 'Все',
  },
  vacancies: [],
  profileTab: 'resume',
  profileLoginMode: 'button',
  // Authentication is intentionally session-only. A stale browser storage
  // value must never open the developer panel for the next person on a shared
  // MAX/WebView device.
  profileEmail: '',
  profileEmailError: '',
  profileData: null,
  profileEditing: false,
  profileEditError: '',
  profileDraft: { faculty: '', course: '', group: '' },
  adminMode: 'profile',
  adminSection: 'events',
  adminVacancySyncStatus: '',
  adminDevelopers: readList(ADMIN_DEVELOPERS_KEY),
  adminPlaces: readList(ADMIN_PLACES_KEY),
  adminFormError: '',
  adminEvents: [],
  adminEventsLoaded: false,
  adminEventDraft: emptyEventDraft(),
  adminEventEditingId: null,
  adminEventError: '',
  subscription: { checked: false, required: false, subscribed: true, channelUrl: '', error: '' },
  myEvents: [],
  notificationsCount: 0,
  notificationsThroughId: 0,
  adminPartners: [],
  adminPartnerDraft: emptyPartnerDraft(),
  adminPartnerEditingId: null,
  adminPartnerError: '',
  adminMetrics: null,
  adminMetricsRange: 30,
  adminMetricsError: '',
  favorites: new Set(),
};

export function isProfileAuthenticated() {
  return Boolean(store.profileEmail);
}

export function isAdminProfile() {
  return store.profileEmail === ADMIN_EMAIL;
}

export function startProfileLogin() {
  store.profileLoginMode = 'email';
  store.profileEmailError = '';
}

export function submitProfileEmail(email) {
  const normalized = String(email || '').trim().toLowerCase();
  if (!/^[a-z0-9._%+-]+@edu\.fa\.ru$/i.test(normalized)) {
    store.profileEmailError = 'Почта должна заканчиваться на @edu.fa.ru';
    return false;
  }
  store.profileEmail = normalized;
  store.profileData = null;
  store.profileEditing = false;
  store.profileEditError = '';
  store.favorites = readFavorites(normalized);
  store.profileEmailError = '';
  store.profileLoginMode = 'button';
  store.adminMode = normalized === ADMIN_EMAIL ? 'panel' : 'profile';
  return true;
}

export function logoutProfile() {
  store.profileEmail = '';
  store.profileData = null;
  store.profileEditing = false;
  store.profileEditError = '';
  store.myEvents = [];
  store.notificationsCount = 0;
  store.notificationsThroughId = 0;
  window.localStorage.removeItem(PROFILE_EMAIL_KEY);
  store.profileLoginMode = 'button';
  store.profileEmailError = '';
  store.favorites = new Set();
  store.adminMode = 'panel';
  store.adminFormError = '';
}

export function setAdminMode(mode) {
  store.adminMode = mode === 'profile' ? 'profile' : 'panel';
  store.adminFormError = '';
}

export function addAdminDeveloper({ name, email }) {
  const n = String(name || '').trim();
  const e = String(email || '').trim().toLowerCase();
  if (!n || !/^[a-z0-9._%+-]+@edu\.fa\.ru$/i.test(e)) {
    store.adminFormError = 'Укажи имя и почту разработчика в домене edu.fa.ru';
    return false;
  }
  store.adminDevelopers = [
    { id: window.crypto?.randomUUID?.() || `${Date.now()}`, name: n, email: e },
    ...store.adminDevelopers,
  ];
  store.adminFormError = '';
  window.localStorage.setItem(ADMIN_DEVELOPERS_KEY, JSON.stringify(store.adminDevelopers));
  return true;
}

export function addAdminPlace({ title, address }) {
  const t = String(title || '').trim();
  const addr = String(address || '').trim();
  if (!t || !addr) {
    store.adminFormError = 'Укажи название и адрес места';
    return false;
  }
  store.adminPlaces = [
    { id: window.crypto?.randomUUID?.() || `${Date.now()}`, title: t, address: addr },
    ...store.adminPlaces,
  ];
  store.adminFormError = '';
  window.localStorage.setItem(ADMIN_PLACES_KEY, JSON.stringify(store.adminPlaces));
  return true;
}

export function startCreateEvent() {
  store.adminEventEditingId = null;
  store.adminEventDraft = emptyEventDraft();
  store.adminEventError = '';
}

export function startEditEvent(event) {
  const startsAt = event.startsAt ? new Date(event.startsAt) : null;
  const localStartsAt = startsAt && !Number.isNaN(startsAt.getTime())
    ? new Date(startsAt.getTime() - startsAt.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
    : '';
  store.adminEventEditingId = event.id;
  store.adminSection = 'events';
  store.adminEventDraft = {
    category: event.category || '',
    format: event.format || 'Офлайн',
    image: event.image || '',
    lead: event.lead || '',
    title: event.title || '',
    date: event.date || '',
    startsAt: localStartsAt,
    place: event.place || '',
    description: event.description || '',
    deadline: event.deadline || '',
    url: event.url || '',
    capacity: Number.isInteger(event.capacity) && event.capacity > 0 ? String(event.capacity) : '',
    isActive: event.isActive !== false,
  };
  store.adminEventError = '';
}

export function startCreatePartner() {
  store.adminPartnerEditingId = null;
  store.adminPartnerDraft = emptyPartnerDraft();
  store.adminPartnerError = '';
}

export function startEditPartner(partner) {
  store.adminPartnerEditingId = partner.id;
  store.adminPartnerDraft = {
    name: partner.name || '',
    logo: partner.logoUrl || '',
    description: partner.description || '',
    achievements: partner.achievements || '',
    parentId: partner.parentId || '',
    isActive: partner.isActive !== false,
    departments: partner.departments?.length
      ? partner.departments.map((item) => ({ name: item.name || '', description: item.description || '' }))
      : [{ name: '', description: '' }],
  };
  store.adminPartnerError = '';
}

export function setPartnerDraft(draft) {
  store.adminPartnerDraft = draft;
}

export function addPartnerDepartment() {
  store.adminPartnerDraft.departments.push({ name: '', description: '' });
}

export function removePartnerDepartment(index) {
  store.adminPartnerDraft.departments.splice(index, 1);
  if (!store.adminPartnerDraft.departments.length) {
    store.adminPartnerDraft.departments.push({ name: '', description: '' });
  }
}

export function saveFavorites() {
  const key = favoritesKey(store.profileEmail);
  if (key) window.localStorage.setItem(key, JSON.stringify([...store.favorites]));
}

export function toggleFavorite(id) {
  if (store.favorites.has(id)) {
    store.favorites.delete(id);
  } else {
    store.favorites.add(id);
  }
  saveFavorites();
}
