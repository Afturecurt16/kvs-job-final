import { store } from '../app/store.js';
import { vacancyCard } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, button, chips, emptyState, errorState, escapeHtml, skeletonList, topTitle } from '../components/ui.js';
import { getVacancies } from '../services/api.js';

export function renderJobsLoading() {
  return appShell(
    `
    ${topTitle('Вакансии')}
    <label class="search-field">${icons.search}<input type="search" placeholder="Поиск стажировок и вакансий" disabled /></label>
    ${chips(['Все', 'ИТиАБД', 'ИОО', 'МЭО', 'ФЭБ', 'СНиМК', 'НАБ', 'ВШУ', 'ФФ', 'ЮФ'], store.filters.vacancyCategory, 'set-vacancy-category')}
    ${skeletonList(3)}
    `,
    { nav: true },
  );
}

export async function renderJobs() {
  try {
    const data = await getVacancies({
      query: store.filters.vacancyQuery,
      category: store.filters.vacancyCategory,
    });
    store.vacancies = data.items || [];

    if (data.maintenance) {
      return appShell(
        `
        ${topTitle('Вакансии')}
        ${emptyState(
          'Технический перерыв',
          data.maintenanceMessage || 'Обновляем вакансии. Попробуй открыть раздел через несколько минут.',
          icons.clock,
        )}
        `,
        { nav: true },
      );
    }

    const hasFilters = Boolean(store.filters.vacancyQuery) || store.filters.vacancyCategory !== 'Все';
    const list = data.items.length
      ? `<section class="list-stack">${data.items.map((item, i) => vacancyCard(item, { index: i })).join('')}</section>`
      : emptyState(
          'Вакансий не найдено',
          'Попробуй изменить поиск или выбрать другую категорию.',
          icons.search,
          hasFilters ? button('Сбросить фильтры', { variant: 'dark', action: 'reset-vacancy-filters', icon: '' }) : '',
        );

    return appShell(
      `
      ${topTitle('Вакансии')}
      ${data.syncing ? `<aside class="sync-banner">${icons.clock}<span>Обновляем список. Пока можно пользоваться предыдущей версией.</span></aside>` : ''}
      <label class="search-field">${icons.search}<input id="vacancySearch" type="search" value="${escapeHtml(store.filters.vacancyQuery)}" placeholder="Поиск стажировок и вакансий" autocomplete="off" /></label>
      ${chips(data.categories, store.filters.vacancyCategory, 'set-vacancy-category')}
      ${list}
      `,
      { nav: true },
    );
  } catch {
    return appShell(
      `
      ${topTitle('Вакансии')}
      ${errorState('Вакансии временно недоступны из-за технического перерыва. Попробуй ещё раз через несколько минут.')}
      `,
      { nav: true },
    );
  }
}
