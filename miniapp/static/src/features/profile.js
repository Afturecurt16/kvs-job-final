import { isAdminProfile, isProfileAuthenticated, store } from '../app/store.js';
import { vacancies } from '../mock/data.js';
import { eventCard, vacancyCard } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, button, emptyState, errorState, escapeHtml, skeletonList, topTitle } from '../components/ui.js';
import { getAdminEvents, getAdminMetrics, getAdminPartners, getMyEvents, getProfile } from '../services/api.js';

function tabs() {
  const count = store.favorites.size;
  return `
    <div class="profile-tabs" role="tablist">
      <button class="${store.profileTab === 'resume' ? 'is-active' : ''}" type="button" role="tab" aria-selected="${store.profileTab === 'resume'}" data-action="profile-tab" data-value="resume">Профиль</button>
      <button class="${store.profileTab === 'favorites' ? 'is-active' : ''}" type="button" role="tab" aria-selected="${store.profileTab === 'favorites'}" data-action="profile-tab" data-value="favorites">
        Избранное <span data-favorites-count ${count > 0 ? '' : 'hidden'}>${count}</span>
      </button>
      <button class="${store.profileTab === 'events' ? 'is-active' : ''}" type="button" role="tab" aria-selected="${store.profileTab === 'events'}" data-action="profile-tab" data-value="events">События</button>
    </div>`;
}

export function renderProfileLoading() {
  if (!isProfileAuthenticated()) {
    return appShell(loginGateView(), { nav: true, className: 'profile-login-screen' });
  }
  if (isAdminProfile() && store.adminMode === 'panel') {
    return appShell(adminPanelShell(skeletonList(2)), { nav: true, className: 'admin-profile-screen' });
  }
  return appShell(`${topTitle('Мой профиль')}${tabs()}${skeletonList(2)}`, { nav: true });
}

function loginGateView() {
  if (store.profileLoginMode === 'email') {
    return `
      <section class="profile-login-only">
        <div class="login-card">
          <span class="login-icon">${icons.user}</span>
          <h2>Вход в профиль</h2>
          <p>Введи корпоративную почту Финансового университета</p>
          <div class="profile-email-form">
            <label class="sr-only" for="profileEmail">Корпоративная почта</label>
            <input id="profileEmail" type="email" inputmode="email" autocomplete="email" placeholder="student@edu.fa.ru" value="${escapeHtml(store.profileEmail)}" aria-invalid="${Boolean(store.profileEmailError)}" ${store.profileEmailError ? 'aria-describedby="profileEmailError"' : ''} />
            ${store.profileEmailError ? `<p class="form-error" id="profileEmailError" role="alert">${escapeHtml(store.profileEmailError)}</p>` : ''}
            ${button('Войти', { variant: 'primary', action: 'submit-profile-email', icon: icons.arrowRight })}
          </div>
        </div>
      </section>`;
  }

  return `
    <section class="profile-login-only">
      <div class="login-card">
        <span class="login-icon">${icons.user}</span>
        <h2>Мой профиль</h2>
        <p>Войди с корпоративной почтой, чтобы видеть данные об обучении, избранные вакансии и события</p>
        ${button('Войти в профиль', { variant: 'primary', action: 'start-profile-login', icon: icons.arrowRight })}
      </div>
    </section>`;
}

function resumeView(profile) {
  const pendingValue = 'Не указано';
  const draft = store.profileDraft;

  return `
    ${isAdminProfile() ? `<section class="admin-entry">${button('Панель разработчика', { variant: 'primary', action: 'admin-mode', route: 'panel', icon: icons.sparkle })}</section>` : ''}

    <section class="profile-head">
      <span class="avatar">${icons.user}</span>
      <div>
        <h2>Мой профиль</h2>
        <p>${escapeHtml(profile.email)}</p>
      </div>
    </section>

    <section class="student-info-card" aria-labelledby="studentInfoTitle">
      <h3 id="studentInfoTitle">Обучение</h3>
      <dl class="student-info-list">
        <div>
          <dt>Почта</dt>
          <dd>${escapeHtml(profile.email)}</dd>
        </div>
        <div>
          <dt>Факультет</dt>
          <dd>${escapeHtml(profile.faculty || pendingValue)}</dd>
        </div>
        <div>
          <dt>Курс</dt>
          <dd>${escapeHtml(profile.course || pendingValue)}</dd>
        </div>
        <div>
          <dt>Группа</dt>
          <dd>${escapeHtml(profile.group || pendingValue)}</dd>
        </div>
      </dl>
      ${store.profileEditing ? `
        <div class="student-profile-form">
          <p class="student-profile-hint">Почта привязана к входу и здесь не меняется.</p>
          <label for="studentFaculty">Факультет</label>
          <input id="studentFaculty" type="text" maxlength="120" autocomplete="organization" placeholder="Укажи факультет" value="${escapeHtml(draft.faculty)}" />
          <label for="studentCourse">Курс</label>
          <input id="studentCourse" type="text" maxlength="32" placeholder="Например, 3 курс" value="${escapeHtml(draft.course)}" />
          <label for="studentGroup">Группа</label>
          <input id="studentGroup" type="text" maxlength="80" placeholder="Укажи группу" value="${escapeHtml(draft.group)}" />
          ${store.profileEditError ? `<p class="form-error" role="alert">${escapeHtml(store.profileEditError)}</p>` : ''}
          ${button('Сохранить', { variant: 'primary', action: 'save-student-profile', icon: icons.check })}
          ${button('Отмена', { variant: 'ghost', action: 'cancel-student-profile-edit' })}
        </div>` : `<div class="student-profile-edit">${button('Редактировать профиль', { variant: 'ghost', action: 'edit-student-profile' })}</div>`}
    </section>

    <section class="profile-actions">
      ${button('Выйти', { variant: 'ghost', action: 'logout-profile', icon: icons.logout })}
    </section>`;
}

function listRows(items, emptyText, renderItem) {
  return items.length ? items.map(renderItem).join('') : `<p class="admin-empty">${escapeHtml(emptyText)}</p>`;
}

const ACTION_LABELS = {
  navigate: 'Переходы между экранами',
  apply: 'Отклики на вакансии',
  'open-link': 'Внешние ссылки',
  'toggle-favorite': 'Избранное',
  'set-vacancy-category': 'Фильтры вакансий',
  'set-event-category': 'Фильтры событий',
  'toggle-event-registration': 'Добавление и отмена мероприятий',
  'profile-tab': 'Вкладки профиля',
  back: 'Возвраты назад',
};

function metricNumber(value) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(Number(value || 0));
}

function analyticsBars(items) {
  const max = Math.max(...items.map((item) => item.events), 1);
  const stride = items.length > 45 ? 7 : items.length > 14 ? 3 : 1;
  return `
    <div class="analytics-chart-scroll">
      <div class="analytics-bars" style="--columns:${items.length}">
        ${items.map((item, index) => {
          const height = item.events ? Math.max(6, Math.round((item.events / max) * 100)) : 2;
          const label = new Date(`${item.date}T00:00:00`).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
          return `
            <div class="analytics-bar" title="${escapeHtml(label)}: ${item.events} событий, ${item.users} пользователей">
              <b>${item.events || ''}</b>
              <span style="height:${height}%"></span>
              <small>${index % stride === 0 || index === items.length - 1 ? escapeHtml(label) : ''}</small>
            </div>`;
        }).join('')}
      </div>
    </div>`;
}

function analyticsRanking(items, { actionLabels = false } = {}) {
  if (!items.length) return '<p class="analytics-empty">Данных за выбранный период пока нет.</p>';
  const max = Math.max(...items.map((item) => item.count), 1);
  return `
    <div class="analytics-ranking">
      ${items.map((item, index) => {
        const label = actionLabels ? ACTION_LABELS[item.label] || item.label : item.label;
        const width = Math.max(5, Math.round((item.count / max) * 100));
        return `
          <div class="analytics-rank">
            <span class="analytics-rank-number">${index + 1}</span>
            <div><p><span>${escapeHtml(label)}</span><strong>${metricNumber(item.count)}</strong></p><i style="width:${width}%"></i></div>
          </div>`;
      }).join('')}
    </div>`;
}

function adminMetricsSection() {
  const metrics = store.adminMetrics;
  return `
    <section class="analytics-dashboard">
      <div class="analytics-head">
        <div><span>Аналитика mini app</span><h2>Активность пользователей</h2></div>
        <button class="icon-btn analytics-download" type="button" data-action="download-admin-metrics" aria-label="Скачать статистику CSV">${icons.download}</button>
      </div>
      <div class="analytics-range" role="group" aria-label="Период статистики">
        ${[7, 30, 90].map((days) => `<button class="${store.adminMetricsRange === days ? 'is-active' : ''}" type="button" data-action="set-admin-metrics-range" data-days="${days}">${days} дней</button>`).join('')}
      </div>
      ${store.adminMetricsError ? `<p class="admin-error" role="alert">${escapeHtml(store.adminMetricsError)}</p>` : ''}
      ${metrics ? `
        <div class="analytics-kpis">
          <article><span>Клики</span><strong>${metricNumber(metrics.summary.clicks)}</strong></article>
          <article><span>Просмотры</span><strong>${metricNumber(metrics.summary.pageViews)}</strong></article>
          <article><span>Пользователи</span><strong>${metricNumber(metrics.summary.uniqueUsers)}</strong></article>
          <article><span>Сегодня</span><strong>${metricNumber(metrics.summary.activeToday)}</strong></article>
          <article class="analytics-kpi-wide"><span>Кликов на пользователя</span><strong>${metricNumber(metrics.summary.clicksPerUser)}</strong></article>
        </div>
        <section class="analytics-panel">
          <div class="analytics-panel-head"><h3>Динамика активности</h3><span>${metrics.days} дней</span></div>
          ${analyticsBars(metrics.daily)}
          <div class="analytics-legend"><span><i></i>Все события</span></div>
        </section>
        <section class="analytics-panel">
          <h3>Популярные действия</h3>
          ${analyticsRanking(metrics.topActions, { actionLabels: true })}
        </section>
        <section class="analytics-panel">
          <h3>Самые посещаемые экраны</h3>
          ${analyticsRanking(metrics.topRoutes)}
        </section>
        <section class="analytics-panel">
          <h3>По чему кликают</h3>
          ${analyticsRanking(metrics.topTargets)}
        </section>` : skeletonList(2)}
    </section>`;
}

function adminPanelShell(managedContentHtml) {
  return `
    ${topTitle('Панель разработчика')}
    <section class="admin-window">
      <div class="admin-window-head">
        <div>
          <span>Админ-доступ</span>
          <strong>${escapeHtml(store.profileEmail)}</strong>
        </div>
        ${button('Обычный профиль', { variant: 'ghost', action: 'admin-mode', route: 'profile', icon: icons.user })}
      </div>
      <nav class="admin-sections" aria-label="Разделы панели">
        ${[
          ['vacancies', 'Вакансии'],
          ['events', 'Мероприятия'],
          ['partners', 'Партнёры'],
          ['metrics', 'Статистика'],
          ['settings', 'Настройки'],
        ].map(([id, label]) => `<button type="button" class="${store.adminSection === id ? 'is-active' : ''}" data-action="set-admin-section" data-value="${id}">${label}</button>`).join('')}
      </nav>
      <button class="btn btn-ghost admin-sync-vacancies" type="button" data-action="sync-admin-vacancies">
        Обновить вакансии из Google Таблицы
      </button>
    </section>

    ${managedContentHtml}

    <section class="profile-actions">
      ${button('Выйти из профиля', { variant: 'ghost', action: 'logout-profile', icon: icons.logout })}
    </section>`;
}

function adminSettingsSection() {
  return `
    <section class="admin-window">
      ${store.adminFormError ? `<p class="admin-error" role="alert">${escapeHtml(store.adminFormError)}</p>` : ''}
      <section class="admin-form">
        <h2>Добавить разработчика</h2>
        <label class="sr-only" for="adminDeveloperName">Имя разработчика</label>
        <input id="adminDeveloperName" type="text" autocomplete="name" placeholder="Имя разработчика" />
        <label class="sr-only" for="adminDeveloperEmail">Почта разработчика</label>
        <input id="adminDeveloperEmail" type="email" inputmode="email" autocomplete="email" placeholder="developer@edu.fa.ru" />
        ${button('Добавить разработчика', { variant: 'primary', action: 'add-admin-developer', icon: '' })}
      </section>
      <section class="admin-form">
        <h2>Добавить место</h2>
        <label class="sr-only" for="adminPlaceTitle">Название места</label>
        <input id="adminPlaceTitle" type="text" placeholder="Название места" />
        <label class="sr-only" for="adminPlaceAddress">Адрес или описание</label>
        <input id="adminPlaceAddress" type="text" placeholder="Адрес или описание" />
        ${button('Добавить место', { variant: 'primary', action: 'add-admin-place', icon: '' })}
      </section>
    </section>
    <section class="admin-list"><h2>Разработчики</h2>${listRows(store.adminDevelopers, 'Разработчики пока не добавлены.', (item) => `<article><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.email)}</span></article>`)}</section>
    <section class="admin-list"><h2>Места</h2>${listRows(store.adminPlaces, 'Места пока не добавлены.', (item) => `<article><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.address)}</span></article>`)}</section>`;
}

function adminVacanciesSection() {
  return `
    <section class="admin-window">
      <section class="admin-form admin-vacancies-form">
        <h2>Вакансии для пользователей</h2>
        <p class="admin-help-text">Здесь можно вручную загрузить актуальные вакансии из подключённой Google Таблицы. После успешного обновления они сразу появятся в разделе «Вакансии».</p>
        <button class="btn btn-primary" type="button" data-action="sync-admin-vacancies">Обновить вакансии сейчас</button>
        ${store.adminVacancySyncStatus ? `<p class="admin-sync-result" role="status">${escapeHtml(store.adminVacancySyncStatus)}</p>` : ''}
      </section>
    </section>`;
}

function adminPartnerFormSection() {
  const draft = store.adminPartnerDraft;
  const isEditing = Boolean(store.adminPartnerEditingId);
  const parentOptions = store.adminPartners
    .filter((partner) => partner.id !== String(store.adminPartnerEditingId || ''))
    .map((partner) => `
      <option value="${escapeHtml(partner.id)}" ${String(draft.parentId || '') === String(partner.id) ? 'selected' : ''}>
        ${escapeHtml(partner.parentName ? `${partner.parentName} → ${partner.name}` : partner.name)}
      </option>`)
    .join('');

  return `
    <section class="admin-window partner-admin-window">
      ${store.adminPartnerError ? `<p class="admin-error" role="alert">${escapeHtml(store.adminPartnerError)}</p>` : ''}
      <section class="admin-form">
        <h2>${isEditing ? 'Редактировать партнера' : 'Добавить партнера'}</h2>
        <label class="sr-only" for="adminPartnerName">Название компании</label>
        <input id="adminPartnerName" type="text" placeholder="Название компании" value="${escapeHtml(draft.name)}" />
        <label class="sr-only" for="adminPartnerLogo">Ссылка на логотип</label>
        <input id="adminPartnerLogo" type="text" placeholder="Ссылка на логотип" value="${escapeHtml(draft.logo)}" />
        <label class="admin-field-label" for="adminPartnerParent">Родительская компания или группа</label>
        <select id="adminPartnerParent">
          <option value="">Верхний уровень — отдельная карточка</option>
          ${parentOptions}
        </select>
        <label class="admin-field-label" for="adminPartnerDescription">О компании</label>
        <textarea id="adminPartnerDescription" rows="6" placeholder="Краткое описание компании">${escapeHtml(draft.description)}</textarea>
        <label class="admin-field-label" for="adminPartnerAchievements">Заслуги и достижения</label>
        <textarea id="adminPartnerAchievements" rows="7" placeholder="Рейтинги, награды и другие достижения">${escapeHtml(draft.achievements)}</textarea>

        <div class="admin-department-head">
          <h3>Департаменты</h3>
          <button class="icon-btn admin-add-department" type="button" data-action="add-admin-partner-department" aria-label="Добавить департамент">${icons.plus}</button>
        </div>
        <div class="admin-departments">
          ${draft.departments.map((department, index) => `
            <section class="admin-department" data-partner-department="${index}">
              <div class="admin-department-title">
                <strong>Департамент ${index + 1}</strong>
                <button class="icon-btn" type="button" data-action="remove-admin-partner-department" data-index="${index}" aria-label="Удалить департамент">${icons.trash}</button>
              </div>
              <input data-department-name type="text" placeholder="Название департамента" value="${escapeHtml(department.name)}" />
              <textarea data-department-description rows="5" placeholder="Описание и направления работы">${escapeHtml(department.description)}</textarea>
            </section>`).join('')}
        </div>

        <label class="admin-checkbox">
          <input type="checkbox" id="adminPartnerActive" ${draft.isActive ? 'checked' : ''} />
          Показывать в приложении
        </label>
        <div class="admin-form-actions">
          ${button(isEditing ? 'Сохранить партнера' : 'Добавить партнера', { variant: 'primary', action: 'submit-admin-partner', icon: icons.check })}
          ${isEditing ? button('Отмена', { variant: 'ghost', action: 'cancel-admin-partner', icon: '' }) : ''}
        </div>
      </section>
    </section>

    <section class="admin-list">
      <h2>Партнеры</h2>
      ${listRows(store.adminPartners, 'Партнеры пока не добавлены.', (partner) => `
        <article>
          <strong>${escapeHtml(partner.name)}</strong>
          <span>${partner.parentName ? `${escapeHtml(partner.parentName)} · ` : ''}${partner.departmentCount} департаментов${partner.childCount ? ` · ${partner.childCount} вложенных компаний` : ''}${partner.isActive ? '' : ' · скрыто'}</span>
          <div class="admin-list-actions">
            <button class="btn btn-ghost btn-small" type="button" data-action="edit-admin-partner" data-id="${escapeHtml(partner.id)}">${icons.pencil}<span>Редактировать</span></button>
            <button class="btn btn-ghost btn-small" type="button" data-action="delete-admin-partner" data-id="${escapeHtml(partner.id)}">${icons.trash}<span>Удалить</span></button>
          </div>
        </article>`)}
    </section>`;
}

function adminEventFormSection() {
  const draft = store.adminEventDraft;
  const isEditing = Boolean(store.adminEventEditingId);

  return `
    <section class="admin-window">
      ${store.adminEventError ? `<p class="admin-error" role="alert">${escapeHtml(store.adminEventError)}</p>` : ''}

      <section class="admin-form">
        <h2>${isEditing ? 'Редактировать мероприятие' : 'Добавить мероприятие'}</h2>
        <label class="sr-only" for="adminEventTitle">Название</label>
        <input id="adminEventTitle" type="text" placeholder="Название мероприятия" value="${escapeHtml(draft.title)}" />
        <div class="form-grid">
          <div class="admin-field-with-help">
            <label class="admin-field-label" for="adminEventCategory">Категория</label>
            <input id="adminEventCategory" type="text" placeholder="Например: Хакатоны" value="${escapeHtml(draft.category)}" />
            <small>Группа события для фильтра в приложении: «Хакатоны», «Воркшопы», «Дни карьеры» или своё значение.</small>
          </div>
          <div class="admin-field-with-help">
            <label class="admin-field-label" for="adminEventFormat">Формат</label>
            <input id="adminEventFormat" type="text" placeholder="Онлайн / Офлайн / Гибрид" value="${escapeHtml(draft.format)}" />
          </div>
        </div>
        <label class="admin-field-label" for="adminEventStartsAt">Точная дата и время для регистрации и уведомлений</label>
        <input id="adminEventStartsAt" type="datetime-local" value="${escapeHtml(draft.startsAt)}" />
        <label class="admin-field-label" for="adminEventCapacity">Лимит участников (виден только администраторам)</label>
        <input id="adminEventCapacity" type="number" min="1" max="100000" inputmode="numeric" placeholder="Например, 50" value="${escapeHtml(draft.capacity)}" />
        <label class="sr-only" for="adminEventLead">Короткий анонс</label>
        <input id="adminEventLead" type="text" placeholder="Короткий анонс над заголовком" value="${escapeHtml(draft.lead)}" />
        <div class="form-grid">
          <label class="sr-only" for="adminEventDate">Дата</label>
          <input id="adminEventDate" type="text" placeholder="Дата и время" value="${escapeHtml(draft.date)}" />
          <label class="sr-only" for="adminEventPlace">Место</label>
          <input id="adminEventPlace" type="text" placeholder="Место проведения" value="${escapeHtml(draft.place)}" />
        </div>
        <label class="admin-field-label" for="adminEventDescription">Описание мероприятия</label>
        <textarea id="adminEventDescription" rows="6" placeholder="Программа, формат участия и важные детали">${escapeHtml(draft.description)}</textarea>
        <label class="admin-field-label" for="adminEventDeadline">Пояснение по регистрации</label>
        <input id="adminEventDeadline" type="text" placeholder="Например: Регистрация до 20 сентября" value="${escapeHtml(draft.deadline)}" />
        <label class="admin-field-label" for="adminEventImageFile">Обложка мероприятия</label>
        ${draft.image ? `<img class="admin-event-preview" src="${escapeHtml(draft.image)}" alt="Текущая обложка мероприятия" />` : ''}
        <input id="adminEventImageFile" type="file" accept="image/jpeg,image/png,image/webp,image/gif" />
        <input id="adminEventImage" type="hidden" value="${escapeHtml(draft.image)}" />
        <label class="admin-field-label" for="adminEventUrl">Ссылка на чат мероприятия</label>
        <input id="adminEventUrl" type="url" placeholder="Ссылка на чат в MAX" value="${escapeHtml(draft.url)}" />
        <small class="admin-field-hint">Показывается пользователю только после успешной регистрации как кнопка «Перейти в чат».</small>
        <label class="admin-checkbox">
          <input type="checkbox" id="adminEventActive" ${draft.isActive ? 'checked' : ''} />
          Показывать в приложении
        </label>
        <div class="admin-form-actions">
          ${button(isEditing ? 'Сохранить изменения' : 'Добавить мероприятие', { variant: 'primary', action: 'submit-admin-event', icon: icons.check })}
          ${isEditing ? button('Отмена', { variant: 'ghost', action: 'cancel-admin-event', icon: '' }) : ''}
        </div>
      </section>
    </section>

    <section class="admin-list">
      <h2>Мероприятия</h2>
      ${listRows(store.adminEvents, 'Мероприятия пока не добавлены.', (event) => `
        <article data-admin-event-row="${escapeHtml(event.id)}">
          <strong>${escapeHtml(event.title)}</strong>
          <span>${escapeHtml(event.category || 'Без категории')} · ${escapeHtml(event.date || 'дата не указана')}${event.isActive ? '' : ' · скрыто'}</span>
          <span class="admin-event-stats">Основной список: ${event.mainCount || 0} / ${event.capacity || 0} · Резерв: ${event.reserveCount || 0}</span>
          <div class="admin-list-actions">
            <button class="btn btn-ghost btn-small" type="button" data-action="edit-admin-event" data-id="${escapeHtml(event.id)}">${icons.pencil}<span>Редактировать</span></button>
            <button class="btn btn-ghost btn-small" type="button" data-action="delete-admin-event" data-id="${escapeHtml(event.id)}">${icons.trash}<span>Удалить</span></button>
          </div>
          <details class="admin-message-panel">
            <summary>Написать участникам в приложении</summary>
            <label>Получатели
              <select data-event-message-audience>
                <option value="all">Все участники</option>
                <option value="confirmed">Только основной список</option>
                <option value="reserve">Только резерв</option>
              </select>
            </label>
            <textarea data-event-message-text rows="4" placeholder="Текст сообщения"></textarea>
            <button class="btn btn-primary btn-small" type="button" data-action="send-admin-event-message" data-id="${escapeHtml(event.id)}">${icons.mail}<span>Отправить в уведомления</span></button>
          </details>
        </article>`)}
    </section>`;
}

async function adminPanelView() {
  const request = store.adminSection === 'events'
    ? getAdminEvents()
    : store.adminSection === 'partners'
      ? getAdminPartners()
      : store.adminSection === 'metrics'
        ? getAdminMetrics(store.adminMetricsRange)
        : Promise.resolve(null);
  const result = await Promise.allSettled([request]);
  const eventsResult = store.adminSection === 'events' ? result[0] : null;
  const partnersResult = store.adminSection === 'partners' ? result[0] : null;
  const metricsResult = store.adminSection === 'metrics' ? result[0] : null;
  if (eventsResult?.status === 'fulfilled') {
    store.adminEvents = eventsResult.value.items;
  } else if (eventsResult) {
    store.adminEventError = 'Не удалось загрузить мероприятия.';
  }
  if (partnersResult?.status === 'fulfilled') {
    store.adminPartners = partnersResult.value.items;
  } else if (partnersResult) {
    store.adminPartnerError = 'Не удалось загрузить партнеров.';
  }
  if (metricsResult?.status === 'fulfilled') {
    store.adminMetrics = metricsResult.value;
    store.adminMetricsError = '';
  } else if (metricsResult) {
    store.adminMetricsError = 'Не удалось загрузить статистику.';
  }
  const sections = {
    vacancies: adminVacanciesSection,
    events: adminEventFormSection,
    partners: adminPartnerFormSection,
    metrics: adminMetricsSection,
    settings: adminSettingsSection,
  };
  return adminPanelShell((sections[store.adminSection] || adminEventFormSection)());
}

function favoritesView() {
  const favorites = (store.vacancies.length ? store.vacancies : vacancies)
    .filter((v) => store.favorites.has(v.id));
  return favorites.length
    ? `<section class="list-stack">${favorites.map((v, i) => vacancyCard(v, { compact: true, index: i })).join('')}</section>`
    : emptyState('В избранном пусто', 'Добавляй подходящие вакансии — нажми сердечко на любой карточке.', icons.heartOutline);
}

function myEventsView() {
  return store.myEvents.length
    ? `<section class="list-stack">${store.myEvents.map((event, index) => eventCard(event, index, { registeredView: true })).join('')}</section>`
    : emptyState('Нет добавленных событий', 'Добавь мероприятие, и оно появится в профиле и под колокольчиком.', icons.bell);
}

export async function renderProfile(route) {
  if (!isProfileAuthenticated()) {
    return appShell(loginGateView(), { nav: true, className: 'profile-login-screen' });
  }

  if (isAdminProfile() && store.adminMode === 'panel') {
    return appShell(await adminPanelView(), { nav: true, className: 'admin-profile-screen' });
  }

  try {
    const profile = store.profileData || await getProfile();
    if (store.profileEmail === profile.email) store.profileData = profile;

    if (store.profileTab === 'events') {
      const data = await getMyEvents();
      store.myEvents = data.items || [];
    }

    const profileContent = store.profileTab === 'favorites'
      ? favoritesView()
      : store.profileTab === 'events'
        ? myEventsView()
        : resumeView(profile);

    return appShell(
      `${topTitle('Мой профиль')}${tabs()}${profileContent}`,
      { nav: true },
    );
  } catch {
    return appShell(`${topTitle('Мой профиль')}${errorState('Не удалось загрузить профиль.')}`, { nav: true });
  }
}
