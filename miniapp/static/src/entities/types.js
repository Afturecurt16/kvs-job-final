/**
 * @typedef {'Стажировка' | 'Вакансия'} VacancyKind
 * @typedef {'Офис' | 'Гибрид' | 'Удалёнка'} WorkFormat
 *
 * @typedef {Object} Company
 * @property {string} id
 * @property {string} name
 * @property {string} initial
 * @property {string} brandColor
 * @property {string} [logoUrl] - real brand logo; falls back to initial+brandColor when absent
 * @property {boolean} verified
 *
 * @typedef {Object} Vacancy
 * @property {string} id
 * @property {Company} company
 * @property {string} title
 * @property {string} salary
 * @property {string} metro
 * @property {string} metroColor
 * @property {WorkFormat} format
 * @property {VacancyKind} kind
 * @property {string} [sphere]
 * @property {string[]} [faculties]
 * @property {string} category - primary faculty (first checked), or sphere/fallback text
 * @property {string} experience
 * @property {string} description
 * @property {string} [fullDescription]
 * @property {string[]} requirements
 * @property {string[]} offer
 * @property {string} applyUrl
 *
 * @typedef {Object} CareerEvent
 * @property {string} id
 * @property {string} category
 * @property {string} format
 * @property {string} image
 * @property {string} lead
 * @property {string} title
 * @property {string} date
 * @property {string} startsAt - ISO date used for registration and reminders
 * @property {string} place
 * @property {string} description
 * @property {string} deadline
 * @property {string} url
 * @property {boolean} [isActive] - admin-only visibility toggle, present on /admin/events
 * @property {boolean} [isRegistered]
 *
 * @typedef {Object} Profile
 * @property {string} email
 * @property {string} faculty
 * @property {string} course
 * @property {string} group
 *
 * @typedef {Object} Route
 * @property {string} name
 * @property {string} path
 * @property {string} [id]
 * @property {URLSearchParams} params
 */

export {};
