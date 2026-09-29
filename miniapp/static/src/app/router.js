import { store } from './store.js';

export function navigate(path) {
  window.location.hash = path;
}

export function parseRoute() {
  const raw = window.location.hash.replace(/^#/, '') || '/vacancies';
  const [path, queryString = ''] = raw.split('?');
  const params = new URLSearchParams(queryString);

  if (path.startsWith('/vacancies/')) {
    return { name: 'vacancy-detail', path, id: path.split('/').pop(), params };
  }
  const departmentMatch = path.match(/^\/partners\/(\d+)\/departments\/(\d+)$/);
  if (departmentMatch) {
    return { name: 'department-detail', path, partnerId: departmentMatch[1], departmentId: departmentMatch[2], params };
  }
  const partnerMatch = path.match(/^\/partners\/(\d+)$/);
  if (partnerMatch) return { name: 'partner-detail', path, id: partnerMatch[1], params };
  if (path === '/partners') return { name: 'partners', path, params };
  if (path === '/events') return { name: 'events', path, params };
  if (path === '/notifications') return { name: 'notifications', path, params };
  if (path === '/profile/edit' || path === '/profile') return { name: 'profile', path: '/profile', params };
  return { name: 'vacancies', path: '/vacancies', params };
}

export function setRoute(route) {
  store.route = route;
  if (route.name === 'profile') {
    store.profileTab = route.params.get('tab') || store.profileTab || 'resume';
  }
}
