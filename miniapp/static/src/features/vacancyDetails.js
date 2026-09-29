import { companyLogo, vacancyCard } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, badge, escapeHtml, errorState, hasVisibleVacancyInfo, iconButton, salaryChip, skeletonList } from '../components/ui.js';
import { getVacancies, getVacancy } from '../services/api.js';

export function renderVacancyDetailLoading() {
  return appShell(`<div class="detail-loading">${skeletonList(1)}</div>`, { className: 'detail-screen' });
}

export async function renderVacancyDetail(id) {
  try {
    const [item, all] = await Promise.all([
      getVacancy(id),
      getVacancies().catch(() => ({ items: [] })),
    ]);
    const formatClass = item.format === 'Гибрид' ? 'blue' : item.format === 'Офис' ? 'green' : 'yellow';
    const itemFaculties = item.faculties ?? [];
    const requirements = (item.requirements ?? []).filter(hasVisibleVacancyInfo);
    const offer = (item.offer ?? []).filter(hasVisibleVacancyInfo);
    const detailMeta = [
      hasVisibleVacancyInfo(item.experience) ? badge(item.experience) : '',
      hasVisibleVacancyInfo(item.metro) ? `<span class="metro" style="--metro:${escapeHtml(item.metroColor)}">${escapeHtml(item.metro)}</span>` : '',
      salaryChip(item.salary),
    ].filter(Boolean).join('');
    const related = (all.items || [])
      .filter((v) => v.id !== item.id && (v.faculties ?? []).some((f) => itemFaculties.includes(f)))
      .slice(0, 2);

    return appShell(
      `
      <section class="detail-cover" style="--brand:${escapeHtml(item.company.brandColor)}">
        ${iconButton('Назад', icons.back, { action: 'back', className: 'back-floating' })}
        ${iconButton('Поделиться вакансией', icons.share, { action: 'share-vacancy', url: item.applyUrl, className: 'share-floating' })}
      </section>
      <article class="detail-content">
        <div class="detail-logo-wrap">${companyLogo(item.company, 'large')}</div>
        <p class="detail-company">${escapeHtml(item.company.name)}</p>
        <h1>${escapeHtml(item.title)}</h1>
        <div class="detail-badges">
          ${hasVisibleVacancyInfo(item.format) ? badge(item.format, formatClass) : ''}
          ${hasVisibleVacancyInfo(item.kind) ? badge(item.kind, item.kind === 'Стажировка' ? 'red-soft' : '') : ''}
          ${(itemFaculties.length ? itemFaculties : [item.category]).map((f) => badge(f)).join('')}
        </div>

        ${hasVisibleVacancyInfo(item.fullDescription || item.description) ? `<section class="content-section">
          <h2>О вакансии</h2>
          <p>${escapeHtml(item.fullDescription || item.description)}</p>
        </section>` : ''}

        ${requirements.length ? `<section class="content-section">
          <h2>Требования</h2>
          <ul class="red-list">${requirements.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}</ul>
        </section>` : ''}

        ${offer.length ? `<section class="offer-panel">
          <h2>Что предлагают</h2>
          <ul class="red-list">${offer.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}</ul>
        </section>` : ''}

        ${detailMeta ? `<section class="detail-meta-row">${detailMeta}</section>` : ''}

        ${related.length ? `
        <section class="related-section" aria-label="Похожие вакансии">
          <h2>Похожие вакансии</h2>
          <div class="list-stack">${related.map((v, i) => vacancyCard(v, { compact: true, index: i })).join('')}</div>
        </section>` : ''}
      </article>

      <footer class="sticky-cta">
        <button class="btn btn-primary" type="button" data-action="apply" data-url="${escapeHtml(item.applyUrl)}">
          <span>Откликнуться</span>${icons.arrowUpRight}
        </button>
      </footer>
      `,
      { className: 'detail-screen' },
    );
  } catch {
    return appShell(
      `${iconButton('Назад', icons.back, { action: 'back', className: 'plain-back' })}${errorState('Вакансия не найдена или временно недоступна.')}`,
      { className: 'detail-screen' },
    );
  }
}
