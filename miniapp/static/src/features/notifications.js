import { store } from '../app/store.js';
import { eventCard } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, button, emptyState, errorState, escapeHtml, iconButton, skeletonList, topTitle } from '../components/ui.js';
import { getMyEvents, getMyNotifications } from '../services/api.js';

function header() {
  return topTitle('Уведомления', iconButton('Назад', icons.back, { action: 'back', className: 'notifications-back' }));
}

function notificationList(items) {
  if (!items.length) {
    return emptyState('Пока нет уведомлений', 'Сообщения о ваших мероприятиях появятся здесь.', icons.bell);
  }
  return `<section class="notification-list" aria-label="Сообщения о мероприятиях">${items.map((item) => {
    const date = new Date(item.createdAt);
    const dateText = Number.isNaN(date.getTime()) ? '' : date.toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' });
    return `<article class="notification-card">
      <div class="notification-card-heading"><strong>${escapeHtml(item.eventTitle)}</strong>${dateText ? `<time datetime="${escapeHtml(item.createdAt)}">${escapeHtml(dateText)}</time>` : ''}</div>
      <p>${escapeHtml(item.text)}</p>
    </article>`;
  }).join('')}</section>`;
}

export function registeredEventsList(items) {
  return items.length
    ? `<section class="list-stack">${items.map((item, index) => eventCard(item, index, { registeredView: true })).join('')}</section>`
    : emptyState(
      'Нет добавленных событий',
      'Добавь мероприятие на вкладке «События», и оно появится здесь.',
      icons.bell,
    );
}

export function renderNotificationsLoading() {
  return appShell(`${header()}${skeletonList(2)}`, { className: 'notifications-screen' });
}

export async function renderNotifications() {
  store.notificationsThroughId = 0;
  if (!store.profileEmail) {
    return appShell(`${header()}${emptyState('Войдите в профиль', 'Чтобы увидеть уведомления и свои мероприятия, сначала войдите с почтой @edu.fa.ru.', icons.bell)}${button('Войти в профиль', { action: 'navigate', route: '/profile' })}`, { className: 'notifications-screen' });
  }
  try {
    const [notifications, events] = await Promise.all([
      getMyNotifications(),
      getMyEvents().catch(() => null),
    ]);
    if (events) store.myEvents = events.items || [];
    const items = notifications.items || [];
    store.notificationsCount = Number(notifications.unreadCount || 0);
    store.notificationsThroughId = store.notificationsCount
      ? items.reduce((max, item) => Math.max(max, Number(item.id) || 0), 0)
      : 0;
    const eventsContent = events
      ? registeredEventsList(store.myEvents)
      : errorState('Не удалось загрузить ваши мероприятия.');
    return appShell(`${header()}${notificationList(items)}<h2 class="notifications-subtitle">Мои мероприятия</h2>${eventsContent}`, { className: 'notifications-screen' });
  } catch {
    return appShell(`${header()}${errorState('Не удалось загрузить уведомления.')}`, { className: 'notifications-screen' });
  }
}
