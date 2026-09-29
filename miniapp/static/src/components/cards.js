import { isAdminProfile, store } from '../app/store.js';
import { icons } from './icons.js';
import { badge, escapeHtml, hasVisibleVacancyInfo, salaryChip } from './ui.js';

// Older database rows still point every VK product at the same generic VK
// logo. Give those placeholders distinct product marks without replacing a
// custom logo that an administrator has set.
const vkProductMarks = {
  'ВКонтакте': ['ВК', '#0077ff'],
  'Одноклассники': ['OK', '#f58220'],
  'Дзен': ['Д', '#171717'],
  'VK Видео': ['VI', '#7856ff'],
  'VK Play': ['PL', '#704bde'],
  'VK Cloud': ['CL', '#2286eb'],
  'VK Education': ['ED', '#0088bc'],
  'Учи.ру': ['У', '#ed5b5b'],
};

function textMark(text, color, size = '', extraClass = '') {
  return `<span class="company-logo company-logo-mark ${extraClass} ${size}" style="--brand:${color}" aria-hidden="true">${escapeHtml(text)}</span>`;
}

export function companyLogo(company, size = '') {
  const productMark = company.logoUrl === '/assets/images/logos/vk.svg' && vkProductMarks[company.name];
  if (productMark) return textMark(productMark[0], productMark[1], size, 'vk-product-logo');
  if (company.logoUrl) {
    // Explicit width/height (not just CSS) stop the browser from ever laying the
    // <img> out at its native intrinsic size — or the ~300x150 broken-image
    // placeholder size — for the instant before/if the real asset loads.
    const box = size === 'large' ? 76 : 56;
    const archiveClass = company.logoUrl.startsWith('/assets/images/logos/vacancy/') ? 'vacancy-icon-image' : '';
    return `<span class="company-logo company-logo-image ${archiveClass} ${size}"><img src="${escapeHtml(company.logoUrl)}" width="${box}" height="${box}" alt="" loading="lazy" /></span>`;
  }
  return `<span class="company-logo ${size}" style="--brand:${escapeHtml(company.brandColor)}">${escapeHtml(company.initial)}</span>`;
}

function vacancyPreview(description) {
  const text = String(description || '').replace(/\s+/g, ' ').trim();
  const limit = 150;
  if (text.length <= limit) return text;
  const lastSpace = text.lastIndexOf(' ', limit);
  return `${text.slice(0, lastSpace > limit / 2 ? lastSpace : limit).trimEnd()}…`;
}

export function vacancyCard(vacancy, { compact = false, index = 0 } = {}) {
  const isFavorite = store.favorites.has(vacancy.id);
  const formatClass = vacancy.format === 'Гибрид' ? 'blue' : vacancy.format === 'Офис' ? 'green' : 'yellow';
  const meta = [
    hasVisibleVacancyInfo(vacancy.metro) ? `<span class="metro" style="--metro:${escapeHtml(vacancy.metroColor)}">${escapeHtml(vacancy.metro)}</span>` : '',
    hasVisibleVacancyInfo(vacancy.format) ? badge(vacancy.format, formatClass) : '',
    hasVisibleVacancyInfo(vacancy.kind) ? badge(vacancy.kind, vacancy.kind === 'Стажировка' ? 'red-soft' : '') : '',
  ].filter(Boolean).join('');

  return `
    <article class="vacancy-card ${compact ? 'is-compact' : ''}" style="--i:${index}" aria-label="${escapeHtml(vacancy.title)} · ${escapeHtml(vacancy.company.name)}">
      <div class="vacancy-main">
        ${companyLogo(vacancy.company)}
        <div class="vacancy-info">
          <p class="company-line">${escapeHtml(vacancy.company.name)}</p>
        </div>
        <button class="heart-btn ${isFavorite ? 'is-active' : ''}" type="button" data-action="toggle-favorite" data-id="${escapeHtml(vacancy.id)}" aria-label="${isFavorite ? 'Убрать из избранного' : 'Добавить в избранное'}">
          ${isFavorite ? icons.heart : icons.heartOutline}
        </button>
      </div>
      <h2 class="vacancy-title">${escapeHtml(vacancy.title)}</h2>
      ${salaryChip(vacancy.salary)}
      ${meta ? `<div class="meta-row">${meta}</div>` : ''}
      ${compact || !vacancy.description ? '' : `<p class="card-copy vacancy-preview">${escapeHtml(vacancyPreview(vacancy.description))}</p>`}
      <div class="card-footer">
        ${hasVisibleVacancyInfo(vacancy.experience) ? badge(vacancy.experience) : ''}
        <button class="btn btn-primary btn-small" type="button" data-action="apply" data-url="${escapeHtml(vacancy.applyUrl)}">Откликнуться</button>
      </div>
      <button class="card-hit" type="button" data-action="navigate" data-route="/vacancies/${escapeHtml(vacancy.id)}" aria-label="Открыть вакансию: ${escapeHtml(vacancy.title)}, ${escapeHtml(vacancy.company.name)}"></button>
    </article>`;
}

export function eventCard(event, index = 0, { registeredView = false } = {}) {
  const formatClass = event.format === 'Онлайн' ? 'green' : event.format === 'Гибрид' ? 'blue-solid' : 'red';

  // Same manage controls as the admin panel's own event list — shown right on
  // the public card so an admin browsing this tab doesn't have to separately
  // remember to go to Профиль → Панель разработчика to edit/delete something
  // they're looking at right now.
  const adminControls = isAdminProfile()
    ? `
    <div class="event-admin-actions">
      <button class="btn btn-ghost btn-small" type="button" data-action="edit-admin-event" data-id="${escapeHtml(event.id)}">${icons.pencil}<span>Редактировать</span></button>
      <button class="btn btn-ghost btn-small" type="button" data-action="delete-admin-event" data-id="${escapeHtml(event.id)}">${icons.trash}<span>Удалить</span></button>
    </div>`
    : '';
  const displayDate = event.date || (event.startsAt
    ? new Date(event.startsAt).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
    : '');
  const registrationNotice = event.registrationStatus === 'reserve'
    ? `<p class="event-registration-status is-reserve">${icons.clock}<span>Вы в резерве${event.reservePosition ? ` · позиция ${event.reservePosition}` : ''}</span></p>`
    : event.registrationStatus === 'confirmed'
      ? `<p class="event-registration-status is-confirmed">${icons.check}<span>Вы зарегистрированы</span></p>`
      : '';
  const registrationButton = event.startsAt
    ? `<button class="btn ${event.isRegistered ? 'btn-registered' : 'btn-primary'} btn-small" type="button" data-action="toggle-event-registration" data-id="${escapeHtml(event.id)}" data-registered="${event.isRegistered ? 'true' : 'false'}">
        ${event.isRegistered ? icons.trash : icons.plus}<span>${event.isRegistered ? 'Отказаться от участия' : 'Зарегистрироваться'}</span>
      </button>`
    : `<button class="btn btn-ghost btn-small" type="button" disabled><span>Дата уточняется</span></button>`;

  return `
    <article class="event-card" style="--i:${index}">
      <div class="event-image" style="background-image:url('${escapeHtml(event.image)}')">
        <span class="event-format ${formatClass}">${escapeHtml(event.format)}</span>
        <span class="event-kind">${escapeHtml(event.category)}</span>
      </div>
      <div class="event-body">
        <p class="event-lead">${escapeHtml(event.lead)}</p>
        <h2>${escapeHtml(event.title)}</h2>
        <p class="event-meta">${icons.calendar}${escapeHtml(displayDate)}</p>
        <p class="event-meta">${icons.mapPin}${escapeHtml(event.place)}</p>
        <p class="card-copy">${escapeHtml(event.description)}</p>
        ${registrationNotice}
        ${adminControls}
        <div class="event-actions">
          ${event.deadline ? `<div class="event-deadline">${badge(event.deadline, 'red-soft deadline')}</div>` : ''}
          <div class="event-action-buttons">
            ${registrationButton}
            ${event.isRegistered && event.url ? `<button class="btn btn-ghost btn-small event-link-button" type="button" data-action="open-link" data-url="${escapeHtml(event.url)}" aria-label="Перейти в чат мероприятия">${icons.arrowUpRight}<span>Перейти в чат</span></button>` : ''}
          </div>
        </div>
      </div>
    </article>`;
}
