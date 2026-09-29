import { companyLogo } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, emptyState, errorState, escapeHtml, iconButton, skeletonList, topTitle } from '../components/ui.js';
import { getPartner, getPartnerDepartment, getPartners } from '../services/api.js';

function partnerCard(partner, index) {
  const departments = Number(partner.departmentCount || 0);
  const children = Number(partner.childCount || 0);
  return `
    <article class="partner-card" style="--i:${index}">
      ${companyLogo(partner)}
      <div class="partner-card-copy">
        <h2>${escapeHtml(partner.name)}</h2>
        <p>${escapeHtml(partner.description)}</p>
        <span>${children ? `${children} ${children === 1 ? 'компания' : children > 1 && children < 5 ? 'компании' : 'компаний'} · ` : ''}${departments} ${departments === 1 ? 'департамент' : departments > 1 && departments < 5 ? 'департамента' : 'департаментов'}</span>
      </div>
      <span class="partner-card-arrow">${icons.arrowRight}</span>
      <button class="card-hit partner-card-hit" type="button" data-action="navigate" data-route="/partners/${escapeHtml(partner.id)}" aria-label="Открыть карточку компании ${escapeHtml(partner.name)}"></button>
    </article>`;
}

function childCompanyCard(parentId, company, index) {
  const departments = Number(company.departmentCount || 0);
  return `
    <article class="partner-card partner-child-card" style="--i:${index}">
      ${companyLogo(company)}
      <div class="partner-card-copy">
        <h2>${escapeHtml(company.name)}</h2>
        <p>${escapeHtml(company.description)}</p>
        <span>${departments} ${departments === 1 ? 'департамент' : departments > 1 && departments < 5 ? 'департамента' : 'департаментов'}</span>
      </div>
      <span class="partner-card-arrow">${icons.arrowRight}</span>
      <button class="card-hit partner-card-hit" type="button" data-action="navigate" data-route="/partners/${escapeHtml(company.id)}" aria-label="Открыть компанию ${escapeHtml(company.name)} внутри ${escapeHtml(parentId)}"></button>
    </article>`;
}

function departmentCard(partnerId, department, index) {
  return `
    <article class="department-card" style="--i:${index}">
      <div>
        <h3>${escapeHtml(department.name)}</h3>
        <p>${escapeHtml(department.description)}</p>
      </div>
      <span class="department-arrow">${icons.arrowRight}</span>
      <button class="card-hit department-card-hit" type="button" data-action="navigate" data-route="/partners/${escapeHtml(partnerId)}/departments/${escapeHtml(department.id)}" aria-label="Открыть департамент ${escapeHtml(department.name)}"></button>
    </article>`;
}

export function renderPartnersLoading() {
  return appShell(`${topTitle('Партнеры')}${skeletonList(3)}`, { nav: true, className: 'partners-screen' });
}

export async function renderPartners() {
  try {
    const data = await getPartners();
    const content = data.items.length
      ? `<section class="partner-list">${data.items.map(partnerCard).join('')}</section>`
      : emptyState('Партнеров пока нет', 'Новые компании появятся здесь после публикации.', icons.building);
    return appShell(`${topTitle('Партнеры')}${content}`, { nav: true, className: 'partners-screen' });
  } catch {
    return appShell(`${topTitle('Партнеры')}${errorState('Не удалось загрузить партнеров.')}`, { nav: true, className: 'partners-screen' });
  }
}

export function renderPartnerDetailLoading() {
  return appShell(`<div class="detail-loading">${skeletonList(1)}</div>`, { className: 'partner-detail-screen' });
}

export async function renderPartnerDetail(id) {
  try {
    const partner = await getPartner(id);
    return appShell(
      `
      <header class="partner-detail-head">
        ${iconButton('Назад', icons.back, { action: 'back', className: 'partner-back' })}
        <span>${partner.parentName ? `${escapeHtml(partner.parentName)} · ` : ''}Компания-партнер</span>
      </header>
      <article class="partner-identity">
        ${companyLogo(partner, 'large')}
        <h1>${escapeHtml(partner.name)}</h1>
      </article>
      <section class="partner-copy-section">
        <h2>О компании</h2>
        <p>${escapeHtml(partner.description)}</p>
      </section>
      ${partner.achievements ? `
        <section class="partner-copy-section partner-achievements">
          <span class="section-icon">${icons.star}</span>
          <h2>Заслуги и достижения</h2>
          <p>${escapeHtml(partner.achievements)}</p>
        </section>` : ''}
      ${partner.children?.length ? `
        <section class="partner-departments partner-child-companies">
          <div class="section-heading">
            <h2>Компании и проекты</h2>
            <span>${partner.children.length}</span>
          </div>
          <div class="partner-list">${partner.children.map((item, index) => childCompanyCard(partner.name, item, index)).join('')}</div>
        </section>` : ''}
      <section class="partner-departments">
        <div class="section-heading">
          <h2>Департаменты</h2>
          <span>${partner.departments.length}</span>
        </div>
        ${partner.departments.length
          ? partner.departments.map((item, index) => departmentCard(partner.id, item, index)).join('')
          : `<p class="muted-copy">Информация о департаментах пока не добавлена.</p>`}
      </section>`,
      { className: 'partner-detail-screen' },
    );
  } catch {
    return appShell(`${iconButton('Назад', icons.back, { action: 'back', className: 'plain-back' })}${errorState('Компания не найдена или временно недоступна.')}`, { className: 'partner-detail-screen' });
  }
}

export async function renderDepartmentDetail(partnerId, departmentId) {
  try {
    const department = await getPartnerDepartment(partnerId, departmentId);
    return appShell(
      `
      <header class="partner-detail-head">
        ${iconButton('Назад', icons.back, { action: 'back', className: 'partner-back' })}
        <span>${escapeHtml(department.companyName)}</span>
      </header>
      <article class="department-detail-identity">
        <p>${escapeHtml(department.companyName)}</p>
        <h1>${escapeHtml(department.name)}</h1>
      </article>
      <section class="partner-copy-section department-copy">
        <h2>О департаменте</h2>
        <p>${escapeHtml(department.description)}</p>
      </section>`,
      { className: 'partner-detail-screen department-detail-screen' },
    );
  } catch {
    return appShell(`${iconButton('Назад', icons.back, { action: 'back', className: 'plain-back' })}${errorState('Департамент не найден или временно недоступен.')}`, { className: 'partner-detail-screen' });
  }
}
