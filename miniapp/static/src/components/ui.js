import { store } from '../app/store.js';
import { icons } from './icons.js';

export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

export function hasVisibleVacancyInfo(value) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim().replace(/[.!?]+$/, '').trim();
  return Boolean(text) && !/^(?:не указан[ао]?(?:\s|$)|уточняется(?:\s|$)|[-—–]$)/i.test(text);
}

export function hasVisibleSalary(value) {
  return hasVisibleVacancyInfo(value);
}

export function salaryChip(value) {
  if (!hasVisibleSalary(value)) return '';
  return `<span class="salary-chip"><strong class="salary-value">${escapeHtml(String(value).trim())}</strong></span>`;
}

export function appShell(content, { nav = false, className = '' } = {}) {
  return `<main class="screen ${className}">${content}</main>${nav ? bottomNav() : ''}`;
}

export function button(label, { variant = 'primary', action = '', route = '', url = '', disabled = false, icon = icons.arrowRight } = {}) {
  if (disabled) {
    return `<button class="btn btn-${variant}" type="button" disabled aria-disabled="true"><span>${escapeHtml(label)}</span>${icon || ''}</button>`;
  }
  const dataAttrs = [
    action ? `data-action="${escapeHtml(action)}"` : '',
    route ? `data-route="${escapeHtml(route)}"` : '',
    url ? `data-url="${escapeHtml(url)}"` : '',
  ]
    .filter(Boolean)
    .join(' ');
  return `<button class="btn btn-${variant}" type="button" ${dataAttrs}><span>${escapeHtml(label)}</span>${icon || ''}</button>`;
}

export function iconButton(label, icon, { action = '', route = '', url = '', className = '' } = {}) {
  return `<button class="icon-btn ${className}" type="button" aria-label="${escapeHtml(label)}" data-action="${escapeHtml(action)}" data-route="${escapeHtml(route)}"${url ? ` data-url="${escapeHtml(url)}"` : ''}>${icon}</button>`;
}

export function topTitle(title, right = '') {
  return `<header class="screen-header"><h1>${escapeHtml(title)}</h1>${right}</header>`;
}

export function bottomNav() {
  const hash = window.location.hash;
  const active = hash.includes('/partners') ? 'partners' : hash.includes('/events') ? 'events' : hash.includes('/profile') ? 'profile' : 'vacancies';
  const favCount = store.favorites.size;

  const item = (id, label, icon, route, extra = '') => `
    <button class="nav-item ${active === id ? 'is-active' : ''}" type="button" data-action="navigate" data-route="${route}" aria-label="${escapeHtml(label)}">
      ${icon}<span>${escapeHtml(label)}</span>${extra}
    </button>`;

  return `
    <nav class="bottom-nav" aria-label="Основная навигация">
      ${item('vacancies', 'Вакансии', icons.briefcase, '/vacancies')}
      ${item('partners', 'Партнеры', icons.building, '/partners')}
      ${item('events', 'События', icons.calendar, '/events')}
      ${item('profile', 'Профиль', icons.user, '/profile', `<i class="nav-badge" data-favorites-count ${favCount ? '' : 'hidden'}>${favCount}</i>`)}
    </nav>`;
}

export function chips(items, active, action) {
  // No view-transition-name here: naming the active pill made the browser
  // animate it as if the SAME element moved between the vacancies and events
  // screens (e.g. both default to an active "Все" chip), when they're really
  // two unrelated chips on two different screens — looked like the chip
  // floating/jumping during tab switches. Same class of bug as the bottom
  // nav highlight fixed earlier; the fix is the same: don't name it.
  return `
    <div class="chips" role="tablist">
      ${items
        .map(
          (item) =>
            `<button class="chip ${item === active ? 'is-active' : ''}" type="button" role="tab" aria-selected="${item === active}" data-action="${escapeHtml(action)}" data-value="${escapeHtml(item)}">${escapeHtml(item)}</button>`,
        )
        .join('')}
    </div>`;
}

export function skeletonList(count = 3) {
  return `<section class="list-stack" aria-busy="true" aria-label="Загрузка">${Array.from({ length: count }, () => `<article class="skeleton-card"><i></i><span></span><span style="width:72%"></span><b></b></article>`).join('')}</section>`;
}

export function emptyState(title, text, icon = '', extra = '') {
  return `<section class="state-card">${icon ? `<span class="state-icon">${icon}</span>` : ''}<strong>${escapeHtml(title)}</strong><p>${escapeHtml(text)}</p>${extra ? `<div class="state-actions">${extra}</div>` : ''}</section>`;
}

export function errorState(text = 'Не удалось загрузить данные. Попробуйте обновить экран.') {
  return emptyState('Что-то пошло не так', text, icons.link);
}

export function badge(label, className = '') {
  return `<span class="badge ${className}">${escapeHtml(label)}</span>`;
}

export function verifiedIcon() {
  return '<span class="verified" aria-label="Проверенная компания">✓</span>';
}
