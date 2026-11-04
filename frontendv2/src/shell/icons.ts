/**
 * Les icônes de la maquette (frontendv2/maquette/index.html) : un trait de 1,7 px sur une grille de 24.
 * Une table plutôt qu'un sprite collé dans la page : un nom d'icône inconnu ne compile pas.
 */

export const ICONS = {
  chat: `<path d="M20.5 11.5a8 8 0 0 1-11.7 7.1L4 20l1.3-4.4A8 8 0 1 1 20.5 11.5Z"/>`,
  tools: `<path d="M14.6 6.2a4 4 0 0 0-5.3 5.2L3.5 17.2a1.9 1.9 0 0 0 2.7 2.7l5.8-5.8a4 4 0 0 0 5.2-5.3l-2.4 2.4-2.3-.4-.4-2.3Z"/>`,
  mail: `<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 7 8.5 6 8.5-6"/>`,
  teams: `<circle cx="9" cy="8" r="3.2"/><path d="M3 19.5a6 6 0 0 1 12 0"/><circle cx="17.2" cy="9" r="2.4"/><path d="M15.8 14.1A4.9 4.9 0 0 1 21 19"/>`,
  phone: `<rect x="6.5" y="2.5" width="11" height="19" rx="2.5"/><path d="M10.8 18.5h2.4"/>`,
  settings: `<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="17" r="2"/>`,
  search: `<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>`,
  plus: `<path d="M12 5v14M5 12h14"/>`,
  send: `<path d="M20.5 3.5 3.8 10.2l6.6 2.9 2.9 6.6Z"/><path d="m10.4 13.1 4.2-4.2"/>`,
  clip: `<path d="m20.5 11.3-8.2 8.2a5 5 0 0 1-7.1-7.1l8.6-8.6a3.4 3.4 0 0 1 4.8 4.8l-8.5 8.5a1.8 1.8 0 0 1-2.6-2.6l7.6-7.6"/>`,
  star: `<path d="m12 3.5 2.6 5.3 5.9.8-4.3 4.1 1 5.8L12 16.8l-5.2 2.7 1-5.8-4.3-4.1 5.9-.8Z"/>`,
  archive: `<rect x="3" y="4" width="18" height="4.5" rx="1"/><path d="M5 8.5V19a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8.5M10 12.5h4"/>`,
  trash: `<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>`,
  reply: `<path d="M9.5 14.5 4.5 9.5l5-5"/><path d="M4.5 9.5H14a6 6 0 0 1 6 6v4"/>`,
  "reply-all": `<path d="M7.5 14.5 2.5 9.5l5-5"/><path d="M12.5 14.5l-5-5 5-5"/><path d="M7.5 9.5H15a6 6 0 0 1 6 6v4"/>`,
  forward: `<path d="m14.5 14.5 5-5-5-5"/><path d="M19.5 9.5H10a6 6 0 0 0-6 6v4"/>`,
  more: `<circle cx="5.5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18.5" cy="12" r="1.3" fill="currentColor"/>`,
  check: `<path d="M5 12.5 9.8 17 19 7"/>`,
  checks: `<path d="M2.5 12.5 7 17l2-2.2M8.5 12.5 13 17l9-10M13.5 9.5 16 7"/>`,
  x: `<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>`,
  "chev-down": `<path d="m6.5 9.5 5.5 5.5 5.5-5.5"/>`,
  "chev-right": `<path d="m9.5 6.5 5.5 5.5-5.5 5.5"/>`,
  "chev-left": `<path d="m14.5 6.5-5.5 5.5 5.5 5.5"/>`,
  eye: `<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.8"/>`,
  "eye-off": `<path d="M4 4l16 16M9.9 5.8A9.7 9.7 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 0 1-2.9 3.6M6.2 7.6A15.6 15.6 0 0 0 2.5 12S6 18.5 12 18.5a9.3 9.3 0 0 0 4.4-1.1"/><path d="M10 10.1a2.8 2.8 0 0 0 3.9 3.9"/>`,
  shield: `<path d="M12 3 4.5 6v5.6c0 4.6 3.2 7.9 7.5 9.4 4.3-1.5 7.5-4.8 7.5-9.4V6Z"/>`,
  "shield-check": `<path d="M12 3 4.5 6v5.6c0 4.6 3.2 7.9 7.5 9.4 4.3-1.5 7.5-4.8 7.5-9.4V6Z"/><path d="m8.8 12 2.2 2.2 4.2-4.4"/>`,
  bolt: `<path d="M13 2.5 4.5 13.5h6.5l-1 8 8.5-11h-6.5Z"/>`,
  pin: `<path d="M12 21s7-6 7-11.5a7 7 0 0 0-14 0C5 15 12 21 12 21Z"/><circle cx="12" cy="9.5" r="2.5"/>`,
  download: `<path d="M12 3.5v11.5M7 10.5l5 5 5-5M5 20.5h14"/>`,
  upload: `<path d="M12 15.5V4M7 8.5l5-5 5 5M5 20.5h14"/>`,
  qr: `<rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1"/><rect x="14" y="3.5" width="6.5" height="6.5" rx="1"/><rect x="3.5" y="14" width="6.5" height="6.5" rx="1"/><path d="M14 14h3v3h-3zM20.5 14v.5M14 20.5h.5M17 20.5h3.5V17"/>`,
  key: `<circle cx="7.5" cy="15.5" r="4"/><path d="m10.4 12.6 9.1-9.1M16.5 6.5l2.5 2.5M14.5 8.5 16 10"/>`,
  link: `<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.1 1.1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.1-1.1"/>`,
  user: `<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>`,
  "user-plus": `<circle cx="10" cy="8" r="4"/><path d="M3 20.5a7 7 0 0 1 12.5-4.3M18.5 14v6M15.5 17h6"/>`,
  users: `<circle cx="9" cy="8.5" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M15.5 5.2a3.4 3.4 0 0 1 0 6.6M18 14.4A6.5 6.5 0 0 1 21.5 20"/>`,
  lock: `<rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>`,
  globe: `<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5a13 13 0 0 1 0 17M12 3.5a13 13 0 0 0 0 17"/>`,
  server: `<rect x="3.5" y="4" width="17" height="7" rx="1.5"/><rect x="3.5" y="13" width="17" height="7" rx="1.5"/><path d="M7.5 7.5h.01M7.5 16.5h.01"/>`,
  plug: `<path d="M9 2.5v5M15 2.5v5M6 7.5h12v3.5a6 6 0 0 1-12 0Z"/><path d="M12 17v4.5"/>`,
  sparkle: `<path d="M11 3.5 12.7 9 18 10.7 12.7 12.4 11 18l-1.7-5.6L4 10.7 9.3 9Z"/><path d="m18.5 15.5.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8Z"/>`,
  sun: `<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M2.5 12h2M19.5 12h2M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>`,
  moon: `<path d="M20 14.5A8.2 8.2 0 1 1 9.5 4a6.6 6.6 0 0 0 10.5 10.5Z"/>`,
  monitor: `<rect x="3" y="4" width="18" height="12.5" rx="1.8"/><path d="M8.5 20.5h7M12 16.5v4"/>`,
  bell: `<path d="M6 8.5a6 6 0 0 1 12 0c0 6.5 2.5 8 2.5 8h-17S6 15 6 8.5"/><path d="M10 20a2 2 0 0 0 4 0"/>`,
  filter: `<path d="M3.5 5h17l-6.5 7.6V19l-4 2v-8.4Z"/>`,
  inbox: `<path d="M3.5 13h5l1.5 3h4l1.5-3h5"/><path d="M6 5h12l2.5 8v6a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1v-6Z"/>`,
  file: `<path d="M14 3H6.5a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V7.5Z"/><path d="M14 3v4.5h4.5"/>`,
  image: `<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="m20.5 15.5-4.5-4.5-8.5 8.5"/>`,
  folder: `<path d="M3.5 6.5a1 1 0 0 1 1-1h4.8l2 2.2h8.2a1 1 0 0 1 1 1V18a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1Z"/>`,
  tag: `<path d="M3.5 12.3V4.5a1 1 0 0 1 1-1h7.8l8.7 8.7-8.5 8.5Z"/><circle cx="8" cy="8" r="1.4"/>`,
  clock: `<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>`,
  refresh: `<path d="M19.5 11a7.6 7.6 0 0 0-14-3.5M4.5 4v4h4"/><path d="M4.5 13a7.6 7.6 0 0 0 14 3.5M19.5 20v-4h-4"/>`,
  external: `<path d="M14 4h6v6M20 4l-8.5 8.5"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>`,
  copy: `<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V4.5a1 1 0 0 0-1-1h-10a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h4"/>`,
  pen: `<path d="M4 20h4L19 9l-4-4L4 16Z"/><path d="m13.5 6.5 4 4"/>`,
  smile: `<circle cx="12" cy="12" r="8.5"/><path d="M8.5 14.2a4.5 4.5 0 0 0 7 0M9.2 9.5h.01M14.8 9.5h.01"/>`,
  menu: `<path d="M4 6.5h16M4 12h16M4 17.5h16"/>`,
  expand: `<path d="M14.5 4.5h5v5M19.5 4.5l-6 6M9.5 19.5h-5v-5M4.5 19.5l6-6"/>`,
  shrink: `<path d="M14 10h5.5M14 10V4.5M14 10l6-6M10 14H4.5M10 14v5.5M10 14l-6 6"/>`,
  minus: `<path d="M5.5 12h13"/>`,
  map: `<path d="M9 4.5 3.5 6.5v13L9 17.5l6 2 5.5-2v-13l-5.5 2Z"/><path d="M9 4.5v13M15 6.5v13"/>`,
  terminal: `<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="m7 9.5 2.8 2.5L7 14.5M12.5 14.5h4.5"/>`,
  threads: `<path d="M4.5 6.5h15M4.5 12h10M4.5 17.5h6.5"/>`,
  at: `<circle cx="12" cy="12" r="3.8"/><path d="M15.8 12v1.4a2.6 2.6 0 0 0 5.2 0V12a9 9 0 1 0-3.6 7.2"/>`,
  calendar: `<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>`,
  book: `<path d="M4.5 5.5a2 2 0 0 1 2-2h13v15h-13a2 2 0 0 0-2 2Z"/><path d="M4.5 20.5a2 2 0 0 1 2-2h13v2"/>`,
  code: `<path d="m8 7.5-5 4.5 5 4.5M16 7.5l5 4.5-5 4.5M13.5 4.5l-3 15"/>`,
  logout: `<path d="M14.5 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M9.5 16.5 5 12l4.5-4.5M5 12h10"/>`,
  grip: `<circle cx="9" cy="6" r="1.2" fill="currentColor"/><circle cx="15" cy="6" r="1.2" fill="currentColor"/><circle cx="9" cy="12" r="1.2" fill="currentColor"/><circle cx="15" cy="12" r="1.2" fill="currentColor"/><circle cx="9" cy="18" r="1.2" fill="currentColor"/><circle cx="15" cy="18" r="1.2" fill="currentColor"/>`,
  heart: `<path d="M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.4a4.3 4.3 0 0 1 7.5 2.4C19.5 15.4 12 20 12 20Z"/>`,
  "thumb-up": `<path d="M7.5 10.5v9h-3v-9ZM7.5 10.5 11 3.5a2.2 2.2 0 0 1 2.5 2.5l-.7 3.5h5.4a2 2 0 0 1 2 2.4l-1.4 6a2 2 0 0 1-2 1.6H7.5"/>`,
  "thumb-down": `<path d="M7.5 13.5v-9h-3v9ZM7.5 13.5 11 20.5a2.2 2.2 0 0 0 2.5-2.5l-.7-3.5h5.4a2 2 0 0 0 2-2.4l-1.4-6a2 2 0 0 0-2-1.6H7.5"/>`,
  alert: `<path d="M12 4 2.8 19.5h18.4Z"/><path d="M12 10v4.2M12 17.2h.01"/>`,
  info: `<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8h.01"/>`,
  wifi: `<path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.5a9.5 9.5 0 0 1 13 0M8.5 16a5 5 0 0 1 7 0M12 19.5h.01"/>`,
  battery: `<rect x="2.5" y="7.5" width="17" height="9" rx="2"/><path d="M21.5 10.5v3M5.5 10.5v3M8.5 10.5v3M11.5 10.5v3"/>`,
  history: `<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6L3.5 8.5"/><path d="M3.5 4v4.5H8M12 7.5V12l3 2"/>`,
  pause: `<path d="M9 5.5v13M15 5.5v13"/>`,
  mic: `<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5v3.5"/>`,
  sort: `<path d="M7 4.5v15M3.5 16 7 19.5l3.5-3.5M17 19.5v-15M13.5 8 17 4.5 20.5 8"/>`,
  "moon-z": `<path d="M19 14.5A7.8 7.8 0 1 1 9.5 5a6.2 6.2 0 0 0 9.5 9.5Z"/><path d="M15 3.5h4l-4 4h4"/>`,
} as const;

export type IconName = keyof typeof ICONS;

/** Le sprite, posé une fois en tête du corps de la page : chaque icône s'y réfère par `<use href="#i-…">`. */
export function injectSprite(doc: Document = document): void {
  if (doc.getElementById("mika-sprite")) return;
  const symbols = Object.entries(ICONS)
    .map(([name, body]) => `<symbol id="i-${name}" viewBox="0 0 24 24">${body}</symbol>`)
    .join("");
  doc.body.insertAdjacentHTML(
    "afterbegin",
    `<svg class="sprite" id="mika-sprite" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">${symbols}</svg>`,
  );
}

/** Une icône : `ico("mail")`, `ico("check", "xs")`. */
export function ico(name: IconName, cls?: string): string {
  return `<svg class="ico${cls ? ` ${cls}` : ""}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}
