import { store } from '../app/store.js';
import { eventCard } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, chips, emptyState, errorState, skeletonList, topTitle } from '../components/ui.js';
import { getEvents } from '../services/api.js';

function notificationButton(count = store.notificationsCount) {
  return `
    <button class="icon-btn notification-button" type="button" aria-label="Уведомления" data-action="navigate" data-route="/notifications">
      ${icons.bell}
      <span ${count ? '' : 'hidden'}>${count > 99 ? '99+' : count}</span>
    </button>`;
}

export function renderEventsLoading() {
  return appShell(
    `
    ${topTitle('Мероприятия', notificationButton())}
    ${chips(['Все', 'Хакатоны', 'Воркшопы', 'Дни карьеры'], store.filters.eventCategory, 'set-event-category')}
    ${skeletonList(3)}
    `,
    { nav: true },
  );
}

export async function renderEvents() {
  try {
    const data = await getEvents({ category: store.filters.eventCategory });
    // Lets the admin's "Редактировать" button on a public event card look up
    // the full event record without a separate round trip — same list shape
    // as the admin panel's own fetch, just possibly category-filtered; the
    // panel re-fetches the unfiltered list itself whenever it's opened.
    store.adminEvents = data.items;

    const list = data.items.length
      ? `<section class="list-stack">${data.items.map((item, i) => eventCard(item, i)).join('')}</section>`
      : emptyState('Мероприятий пока нет', 'Когда появятся новые события, они будут здесь.', icons.calendar);

    return appShell(
      `
      ${topTitle('Мероприятия', notificationButton())}
      ${chips(data.categories, store.filters.eventCategory, 'set-event-category')}
      ${list}
      `,
      { nav: true },
    );
  } catch {
    return appShell(`${topTitle('Мероприятия', notificationButton())}${errorState('Не удалось загрузить мероприятия.')}`, { nav: true });
  }
}
