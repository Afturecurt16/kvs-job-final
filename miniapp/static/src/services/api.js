import { categories, eventCategories, events, partners, vacancies } from '../mock/data.js';
import { store } from '../app/store.js';

const API_BASE = window.KVS_API_BASE ?? '/api/v1';
const MOCK_DELAY = 200;

const wait = (ms = MOCK_DELAY) => new Promise((resolve) => window.setTimeout(resolve, ms));

function getMode() {
  return new URLSearchParams(window.location.search).get('mockState') || 'normal';
}

function canUseMockFallback() {
  const params = new URLSearchParams(window.location.search);
  return params.has('mockState') || window.KVS_USE_MOCK === true;
}

async function request(path) {
  if (!API_BASE) return null;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8000);
  const response = await fetch(`${API_BASE}${path}`, { headers: profileAuthHeaders(), signal: controller.signal });
  window.clearTimeout(timeout);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function userRequest(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { ...profileAuthHeaders(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (data?.detail) detail = data.detail;
    } catch {
      /* keep generic status */
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function authHeaders() {
  // The bridge can finish initialising after the module has loaded. Bootstrap
  // preserves the launch value from either the bridge or the MAX URL fragment
  // so user actions do not lose their signed session after hash navigation.
  let cachedData = '';
  try {
    cachedData = window.sessionStorage.getItem('kvs-job:max-init-data') || '';
  } catch {
    /* Session storage can be unavailable in restricted WebViews. */
  }
  const initData = window.WebApp?.initData?.trim() || window.KVS_MAX_INIT_DATA || cachedData;
  return initData ? { 'X-Max-Init-Data': initData } : {};
}

function profileAuthHeaders() {
  const email = store.profileEmail || '';
  return {
    ...authHeaders(),
    ...(email ? { 'X-Profile-Email': email } : {}),
  };
}

function adminAuthHeaders() {
  // Profile authentication is session-only, so the current email lives in
  // the in-memory store rather than persistent localStorage.
  const email = store.profileEmail || '';
  return { ...authHeaders(), 'X-Admin-Email': email };
}

// Admin mutations hit the real backend directly — there's no meaningful "mock
// mode" for writes against the database, and the server verifies the caller
// is an admin via signed MAX initData regardless of what the client sends.
async function adminRequest(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...adminAuthHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (data?.detail) detail = data.detail;
    } catch {
      /* non-JSON error body, keep the generic message */
    }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

function normalize(value) {
  return String(value || '').trim().toLowerCase();
}

function matchesCategory(item, category) {
  if (!category || category === 'Все') return true;
  // Vacancies can belong to several faculties at once; events keep a single category.
  return Array.isArray(item.faculties) ? item.faculties.includes(category) : item.category === category;
}

function matchesQuery(item, query) {
  const q = normalize(query);
  if (!q) return true;
  return [
    item.title,
    item.company?.name,
    item.salary,
    item.metro,
    item.format,
    item.kind,
    item.sphere ?? item.category,
    ...(item.faculties ?? []),
    item.description,
  ].some((v) => normalize(v).includes(q));
}

async function withMockState(factory) {
  await wait();
  const mode = getMode();
  if (mode === 'error') throw new Error('Mock error');
  if (mode === 'empty') return factory(true);
  return factory(false);
}

export async function getVacancies({ query = '', category = 'Все' } = {}) {
  try {
    const real = await request(`/vacancies?q=${encodeURIComponent(query)}&category=${encodeURIComponent(category)}`);
    if (real) return real;
  } catch (error) {
    if (!canUseMockFallback()) throw error;
  }

  return withMockState((forceEmpty) => ({
    categories,
    items: forceEmpty ? [] : vacancies.filter((v) => matchesCategory(v, category) && matchesQuery(v, query)),
  }));
}

export async function getVacancy(id) {
  try {
    const real = await request(`/vacancies/${encodeURIComponent(id)}`);
    if (real) return real;
  } catch (error) {
    if (!canUseMockFallback()) throw error;
  }

  await wait(140);
  const item = vacancies.find((v) => v.id === id);
  if (!item) throw new Error('Not found');
  return item;
}

export async function getEvents({ category = 'Все' } = {}) {
  try {
    const real = await request(`/events?category=${encodeURIComponent(category)}`);
    if (real) return real;
  } catch (error) {
    // Demo cards belong only to explicit mock mode. In production, surface an
    // API outage instead of presenting stale placeholders as real events.
    if (!canUseMockFallback()) throw error;
  }

  return withMockState((forceEmpty) => ({
    categories: eventCategories,
    items: forceEmpty ? [] : events.filter((e) => matchesCategory(e, category)),
  }));
}

export async function getMyEvents() {
  try {
    return await userRequest('/me/events');
  } catch (error) {
    if (!canUseMockFallback()) throw error;
    return { items: events.filter((item) => item.isRegistered), total: 0 };
  }
}

export async function getMyNotifications() {
  return userRequest('/me/notifications');
}

export async function getUnreadNotificationCount() {
  return userRequest('/me/notifications/unread-count');
}

export async function markMyNotificationsRead(throughId) {
  return userRequest('/me/notifications/read', { method: 'POST', body: { throughId } });
}

export async function registerEvent(id) {
  return userRequest(`/events/${encodeURIComponent(id)}/register`, { method: 'POST' });
}

export async function unregisterEvent(id) {
  return userRequest(`/events/${encodeURIComponent(id)}/register`, { method: 'DELETE' });
}

export async function getSubscriptionStatus() {
  return userRequest('/subscription');
}

export async function getProfile() {
  return userRequest('/me/profile');
}

export async function updateProfile(fields) {
  return userRequest('/me/profile', { method: 'PUT', body: fields });
}

export async function getPartners() {
  try {
    const real = await request('/partners');
    if (real) return real;
  } catch (error) {
    if (!canUseMockFallback()) throw error;
  }
  return withMockState((forceEmpty) => ({ items: forceEmpty ? [] : partners, total: forceEmpty ? 0 : partners.length }));
}

export async function getPartner(id) {
  try {
    const real = await request(`/partners/${encodeURIComponent(id)}`);
    if (real) return real;
  } catch (error) {
    if (!canUseMockFallback()) throw error;
  }
  await wait(140);
  const partner = partners.find((item) => item.id === id);
  if (!partner) throw new Error('Not found');
  return partner;
}

export async function getPartnerDepartment(partnerId, departmentId) {
  try {
    const real = await request(`/partners/${encodeURIComponent(partnerId)}/departments/${encodeURIComponent(departmentId)}`);
    if (real) return real;
  } catch (error) {
    if (!canUseMockFallback()) throw error;
  }
  await wait(140);
  const partner = partners.find((item) => item.id === partnerId);
  const department = partner?.departments.find((item) => item.id === departmentId);
  if (!department) throw new Error('Not found');
  return { ...department, companyLogoUrl: partner.logoUrl };
}

export async function getAdminEvents() {
  return adminRequest('/admin/events');
}

export async function syncAdminVacancies() {
  return adminRequest('/admin/vacancies/sync', { method: 'POST' });
}

export async function createEvent(payload) {
  return adminRequest('/admin/events', { method: 'POST', body: payload });
}

export async function updateEvent(id, payload) {
  return adminRequest(`/admin/events/${encodeURIComponent(id)}`, { method: 'PUT', body: payload });
}

export async function deleteEvent(id) {
  return adminRequest(`/admin/events/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function uploadEventImage(file) {
  const response = await fetch(`${API_BASE}/admin/events/upload`, {
    method: 'POST',
    headers: { ...adminAuthHeaders(), 'Content-Type': file.type },
    body: file,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function sendEventMessage(id, payload) {
  return adminRequest(`/admin/events/${encodeURIComponent(id)}/message`, {
    method: 'POST',
    body: payload,
  });
}

export async function getAdminPartners() {
  return adminRequest('/admin/partners');
}

export async function createPartner(payload) {
  return adminRequest('/admin/partners', { method: 'POST', body: payload });
}

export async function updatePartner(id, payload) {
  return adminRequest(`/admin/partners/${encodeURIComponent(id)}`, { method: 'PUT', body: payload });
}

export async function deletePartner(id) {
  return adminRequest(`/admin/partners/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function trackMetric(payload) {
  if (!API_BASE) return;
  fetch(`${API_BASE}/metrics/actions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {});
}

export async function getAdminMetrics(days = 30) {
  return adminRequest(`/admin/metrics?days=${encodeURIComponent(days)}`);
}

export async function downloadAdminMetrics(days = 30) {
  const response = await fetch(`${API_BASE}/admin/metrics/export?days=${encodeURIComponent(days)}`, {
    headers: adminAuthHeaders(),
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (data?.detail) detail = data.detail;
    } catch {
      /* keep generic status */
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `kvs-metrics-${days}d.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
