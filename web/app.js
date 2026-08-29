/* Letterboxd Cinema — a film-first front-end for Jellyfin.
   Talks to the Jellyfin API on the same origin; Jellyfin's own UI stays at /web/. */

const CLIENT = 'Letterboxd Cinema', VERSION = '0.2.0';
const $ = (s, r = document) => r.querySelector(s);
const store = {
  get: (k) => { try { return JSON.parse(localStorage.getItem('cp.' + k)); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem('cp.' + k, JSON.stringify(v)); } catch {} },
  del: (k) => { try { localStorage.removeItem('cp.' + k); } catch {} },
};
const deviceId = store.get('device') || (() => { const d = crypto.randomUUID(); store.set('device', d); return d; })();
let session = store.get('session'); // { token, userId, userName, serverId }
let films = [], view = 'reel', sortKey = 'added', country = null;
let startMode = store.get('start') || 'newest'; // what leads the reel on load: 'newest' or 'random'
const ratings = new Map(); // itemId -> { value, source }
const meta = new Map();    // itemId -> Letterboxd data { rating, countries, languages } or null

/* ---------- API ---------- */
function authHeader(token) {
  return `MediaBrowser Client="${CLIENT}", Device="Browser", DeviceId="${deviceId}", Version="${VERSION}"` + (token ? `, Token="${token}"` : '');
}
async function api(path, { method = 'GET', body, token = session?.token } = {}) {
  const r = await fetch(path, { method, headers: { 'Authorization': authHeader(token), 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401) { signOut(); throw new Error('Signed out'); }
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.status === 204 ? null : r.json();
}
async function signIn(user, pass) {
  const d = await api('/Users/AuthenticateByName', { method: 'POST', body: { Username: user, Pw: pass }, token: null });
  session = { token: d.AccessToken, userId: d.User.Id, userName: d.User.Name, serverId: d.ServerId };
  store.set('session', session);
}
function signOut() { session = null; store.del('session'); location.reload(); }

async function loadFilms() {
  const q = new URLSearchParams({
    IncludeItemTypes: 'Movie', Recursive: 'true', SortBy: 'DateCreated', SortOrder: 'Descending',
    Fields: 'Overview,ProductionLocations,People,ProviderIds,DateCreated,Genres,Taglines', ImageTypeLimit: '10', EnableImageTypes: 'Backdrop,Primary',
  });
  const d = await api(`/Users/${session.userId}/Items?${q}`);
  const img = (it, type, i, tag, w) => `/Items/${it.Id}/Images/${type}${i != null ? '/' + i : ''}?maxWidth=${w}&quality=82&tag=${tag}`;
  const shuffle = (a) => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  return d.Items.map(it => {
    // every visit deals the film's backdrops in a fresh order: the first one is the still and thumbnail, the rest feed the slideshow
    const order = shuffle((it.BackdropImageTags || []).map((tag, i) => ({ i, tag })));
    const lead = order[0];
    return {
      id: it.Id, t: it.Name, y: it.ProductionYear, d: (it.People || []).filter(p => p.Type === 'Director').map(p => p.Name).join(', '),
      countries: it.ProductionLocations || [], c: (it.ProductionLocations || [])[0] || '', r: it.RunTimeTicks ? Math.round(it.RunTimeTicks / 600000000) : null,
      backdrops: order.map(b => img(it, 'Backdrop', b.i, b.tag, 1920)),
      s: it.Overview || it.Taglines?.[0] || '', genres: it.Genres || [], added: it.DateCreated, tmdb: it.ProviderIds?.Tmdb,
      community: it.CommunityRating, played: it.UserData?.Played, pos: it.UserData?.PlaybackPositionTicks || 0,
      still: lead ? img(it, 'Backdrop', lead.i, lead.tag, 1920) : it.ImageTags?.Primary ? img(it, 'Primary', null, it.ImageTags.Primary, 1920) : '',
      thumb: lead ? img(it, 'Backdrop', lead.i, lead.tag, 800) : it.ImageTags?.Primary ? img(it, 'Primary', null, it.ImageTags.Primary, 800) : '',
    };
  });
}

/* Letterboxd data via the helper at /api/letterboxd (rating, countries, languages); TMDB community rating as the fallback. */
async function getMeta(f) {
  if (meta.has(f.id)) return meta.get(f.id);
  let d = null;
  if (f.tmdb) { try { const r = await fetch(`/api/letterboxd/${f.tmdb}`); if (r.ok) d = await r.json(); } catch {} }
  meta.set(f.id, d);
  const c = chooseCountry(f, d); if (c !== f.c) { f.c = c; document.querySelectorAll(`[data-country="${f.id}"]`).forEach(el => el.textContent = c); }
  return d;
}
async function getRating(f) {
  if (ratings.has(f.id)) return ratings.get(f.id);
  const d = await getMeta(f);
  const out = d?.rating ? { value: d.rating, source: 'Letterboxd' } : f.community ? { value: Math.round(f.community / 2 * 10) / 10, source: 'TMDB' } : null;
  ratings.set(f.id, out); return out;
}

/* Which country is a film "from"? Co-productions list several; the primary spoken language is the better tell.
   Pick the listed country that matches the film's primary language, else the first listed. */
const LANG_HOME = {
  Romanian: ['Romania'], French: ['France', 'Belgium', 'Canada', 'Switzerland'], German: ['Germany', 'Austria', 'Switzerland'],
  Italian: ['Italy'], Spanish: ['Spain', 'Mexico', 'Argentina', 'Chile', 'Colombia', 'Peru', 'Uruguay', 'Cuba'], Portuguese: ['Portugal', 'Brazil'],
  Japanese: ['Japan'], Korean: ['South Korea'], Cantonese: ['Hong Kong'], Mandarin: ['China', 'Taiwan', 'Hong Kong'], Thai: ['Thailand'],
  Hindi: ['India'], Tamil: ['India'], Bengali: ['India', 'Bangladesh'], Persian: ['Iran'], Arabic: ['Egypt', 'Lebanon', 'Morocco', 'Palestine', 'Tunisia', 'Algeria'],
  Turkish: ['Turkey'], Greek: ['Greece'], Hebrew: ['Israel'], Russian: ['Russia', 'Ussr'], Ukrainian: ['Ukraine'], Polish: ['Poland'], Czech: ['Czechia', 'Czech Republic'],
  Hungarian: ['Hungary'], Swedish: ['Sweden'], Danish: ['Denmark'], Norwegian: ['Norway'], Finnish: ['Finland'], Icelandic: ['Iceland'],
  Dutch: ['Netherlands', 'Belgium'], Serbian: ['Serbia'], Croatian: ['Croatia'], Bosnian: ['Bosnia And Herzegovina'], Georgian: ['Georgia'],
  English: ['UK', 'USA', 'Ireland', 'Australia', 'New Zealand', 'Canada'],
};
function chooseCountry(f, d) {
  const list = d?.countries?.length ? d.countries : f.countries;
  if (!list.length) return '';
  const lang = d?.languages?.[0]; const homes = lang && LANG_HOME[lang];
  if (homes) { const hit = list.find(c => homes.includes(c)); if (hit) return hit; }
  return list[0];
}
const visible = () => country ? films.filter(f => f.c === country) : films;

/* ---------- rendering ---------- */
const STAR = 'M12 2.6l2.9 6.2 6.7.8-4.9 4.6 1.3 6.7L12 17.6 6 20.9l1.3-6.7L2.4 9.6l6.7-.8z';
let clipN = 0;
function stars(v) {
  let out = '';
  for (let i = 1; i <= 5; i++) {
    const f = Math.max(0, Math.min(1, v - (i - 1))); const id = 'cp' + (++clipN);
    out += `<svg viewBox="0 0 24 24" aria-hidden="true"><defs><clipPath id="${id}"><rect width="${24 * f}" height="24"/></clipPath></defs><path class="base" d="${STAR}"/><path class="fill" d="${STAR}" clip-path="url(#${id})"/></svg>`;
  }
  return `<span class="stars" role="img" aria-label="${v} out of 5">${out}</span>`;
}
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const play = `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 3.5v17l14-8.5z"/></svg>`;
const eyebrow = (f) => `<div class="eyebrow label">${[f.d && `<span>${esc(f.d)}</span>`, f.y && `<span>${f.y}</span>`,
  `<span><button data-filter-country="${f.id}" data-country="${f.id}">${esc(f.c)}</button></span>`, f.r && `<span>${f.r} min</span>`].filter(Boolean).join('')}</div>`;
const ratingSlot = (f, cls = '') => `<span class="rating ${cls}" data-rating="${f.id}"></span>`;
const playBtn = (f) => `<button class="btn" data-play="${f.id}">${play} ${f.pos ? 'Resume' : 'Play'}</button>`;
const stillEl = (f) => `<div class="still" data-slides="${f.backdrops.length}" style="background-image:url('${f.still}')">${f.backdrops.slice(1).map(u => `<div class="layer" data-src="${u}"></div>`).join('')}</div>`;

/* Slideshow: after a few seconds on a panel, crossfade through the film's other backdrops. */
const shows = new WeakMap();
function startShow(still) {
  if (shows.has(still) || +still.dataset.slides < 2) return;
  const layers = [...still.querySelectorAll('.layer')]; let i = -1;
  const step = () => {
    layers.forEach(l => l.classList.remove('on'));
    i = (i + 1) % (layers.length + 1);                // slot 0 = the base still, 1.. = layers
    if (i > 0) { const l = layers[i - 1]; if (!l.style.backgroundImage) l.style.backgroundImage = `url('${l.dataset.src}')`; l.classList.add('on'); }
  };
  const t = { first: setTimeout(() => { step(); t.every = setInterval(step, 7000); }, 4500) };
  shows.set(still, t);
}
function stopShow(still) { const t = shows.get(still); if (!t) return; clearTimeout(t.first); clearInterval(t.every); shows.delete(still); }
const watcher = new IntersectionObserver(es => es.forEach(e => { const st = e.target.querySelector('.still'); if (!st) return; e.intersectionRatio >= .6 ? startShow(st) : stopShow(st); }), { threshold: [0, .6] });

async function fillRating(el, f, small) {
  const r = await getRating(f);
  if (!r) { el.remove(); return; }
  el.innerHTML = small ? stars(r.value) : `${stars(r.value)}<span class="num">${r.value.toFixed(1)}</span><span class="src">${r.source}</span>`;
}
function hydrateRatings(root) {
  root.querySelectorAll('[data-rating]').forEach(el => { const f = films.find(x => x.id === el.dataset.rating); if (f) fillRating(el, f, el.classList.contains('small')); });
}

function renderReel(list) {
  $('#reel').innerHTML = list.map((f, i) => `
    <article class="panel" data-id="${f.id}">
      ${stillEl(f)}<div class="scrim"></div>
      <div class="foot-row">
        <div class="copy">
          ${eyebrow(f)}
          <h2>${esc(f.t)}</h2>
          <p>${esc(f.s)}</p>
          ${ratingSlot(f)}
        </div>
        <div class="controls">
          <div class="index">${String(i + 1).padStart(2, '0')} / ${list.length}</div>
          <div class="row">${playBtn(f)}<button class="btn ghost" data-open="${f.id}">About the film</button></div>
        </div>
      </div>
    </article>`).join('');
  hydrateRatings($('#reel'));
  $('#reel').querySelectorAll('.panel').forEach(p => watcher.observe(p));
}

function sorted() {
  const l = visible().slice();
  const by = { added: (a, b) => b.added.localeCompare(a.added), title: (a, b) => a.t.localeCompare(b.t), year: (a, b) => (b.y || 0) - (a.y || 0),
               rating: (a, b) => ((ratings.get(b.id)?.value ?? b.community / 2 ?? 0) - (ratings.get(a.id)?.value ?? a.community / 2 ?? 0)) }[sortKey];
  return l.sort(by);
}
function renderGrid() {
  const list = sorted();
  $('#grid').innerHTML = list.map(f => `
    <button class="card" data-open="${f.id}" data-id="${f.id}">
      <div class="frame" style="background-image:url('${f.thumb}')"></div>
      <div class="t">${esc(f.t)}</div>
      <div class="m"><span>${esc([f.d, f.y].filter(Boolean).join(' · '))}</span>${ratingSlot(f, 'small')}</div>
    </button>`).join('');
  $('#count').textContent = `${list.length} film${list.length === 1 ? '' : 's'}`;
  $('#empty').hidden = list.length > 0;
  $('#empty').textContent = country ? `No films from ${country} yet.` : 'Nothing here yet.';
  hydrateRatings($('#grid'));
}

function openFilm(f) {
  const el = $('#film');
  el.innerHTML = `
    <button class="close" id="close">Close <span aria-hidden="true">✕</span></button>
    <div class="hero">
      ${stillEl(f)}<div class="scrim"></div>
      <div class="foot-row">
        <div class="copy">${eyebrow(f)}<h2 id="film-title">${esc(f.t)}</h2>${ratingSlot(f)}</div>
      </div>
    </div>
    <div class="controls"><div class="row">${playBtn(f)}<button class="btn ghost" id="another">Pick another</button></div></div>
    <div class="body">
      <div><p>${esc(f.s)}</p>${f.genres.length ? `<div class="genres">${f.genres.map(g => `<span>${esc(g)}</span>`).join('')}</div>` : ''}</div>
      <dl>${[['Director', f.d], ['Year', f.y], ['Country', (meta.get(f.id)?.countries || f.countries).join(', ')], ['Language', meta.get(f.id)?.languages?.[0]], ['Runtime', f.r && f.r + ' min']].filter(x => x[1]).map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
    </div>
    ${session.admin && f.tmdb ? `<div class="remove" id="remove">
      <button class="remove-link" id="remove-ask">Remove from library</button>
      <div class="remove-confirm" id="remove-confirm" hidden>
        <span>Remove <i>${esc(f.t)}</i> — deletes the file, the torrent if it's still seeding, and stops Radarr re-adding it.</span>
        <button class="btn ghost" id="remove-no">Keep</button><button class="btn" id="remove-yes">Remove</button>
      </div>
      <p class="remove-status" id="remove-status" hidden></p>
    </div>` : ''}`;
  hydrateRatings(el);
  stopShowAll(el); startShow(el.querySelector('.still'));
  el.setAttribute('data-open', ''); el.scrollTop = 0; document.body.style.overflow = 'hidden';
  $('#close').onclick = closeFilm;
  $('#another').onclick = () => { closeFilm(); setTimeout(randomFilm, 200); };
  if ($('#remove-ask')) {
    $('#remove-ask').onclick = () => { $('#remove-ask').hidden = true; $('#remove-confirm').hidden = false; };
    $('#remove-no').onclick = () => { $('#remove-confirm').hidden = true; $('#remove-ask').hidden = false; };
    $('#remove-yes').onclick = () => removeFilm(f);
  }
  $('#close').focus();
}
async function removeFilm(f) {
  const st = $('#remove-status'); $('#remove-confirm').hidden = true; st.hidden = false; st.textContent = 'Removing…';
  try {
    const r = await fetch(`/api/admin/remove/${f.tmdb}`, { method: 'POST', headers: { 'X-Jellyfin-Token': session.token } });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || (r.status === 404 ? 'the helper is not reachable (restart Caddy?)' : r.statusText));
    st.textContent = `Removed${d.torrents_removed ? ` · ${d.torrents_removed} torrent${d.torrents_removed > 1 ? 's' : ''} deleted` : ''}.`;
    films = films.filter(x => x.id !== f.id); meta.delete(f.id); ratings.delete(f.id);
    setTimeout(() => { closeFilm(); buildCountries(); renderReel(reelOrder()); if (view === 'grid') renderGrid(); }, 900);
  } catch (e) { st.textContent = 'Could not remove — ' + e.message; }
}
function closeFilm() { const el = $('#film'); stopShowAll(el); el.removeAttribute('data-open'); document.body.style.overflow = ''; }
function stopShowAll(root) { root.querySelectorAll('.still').forEach(stopShow); }

function setView(v) {
  view = v; document.body.dataset.view = v;
  $('#v-reel').setAttribute('aria-pressed', v === 'reel'); $('#v-grid').setAttribute('aria-pressed', v === 'grid');
  if (v === 'grid') renderGrid();
  window.scrollTo({ top: 0, behavior: 'instant' }); $('#reel').scrollTo({ top: 0, behavior: 'instant' });
}

let busy = false;
function randomFilm() {
  const pool = visible(); if (busy || !pool.length) return; busy = true;
  const pick = pool[Math.floor(Math.random() * pool.length)];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (view === 'grid' && !reduce) {
    const cards = [...document.querySelectorAll('.card')]; let n = 0, last;
    const step = () => {
      if (last) last.classList.remove('lit');
      last = cards[Math.floor(Math.random() * cards.length)]; last?.classList.add('lit'); n++;
      if (n < 8) setTimeout(step, 60 + n * 30); else { last?.classList.remove('lit'); busy = false; openFilm(pick); }
    }; step();
  } else { busy = false; openFilm(pick); }
}

/* film grain, generated once */
function makeGrain() {
  const s = 160, c = document.createElement('canvas'); c.width = c.height = s;
  const x = c.getContext('2d'), d = x.createImageData(s, s);
  for (let i = 0; i < d.data.length; i += 4) { const v = 90 + Math.random() * 120; d.data[i] = d.data[i + 1] = d.data[i + 2] = v; d.data[i + 3] = 255; }
  x.putImageData(d, 0, 0); return `url(${c.toDataURL()})`;
}

/* ---------- boot ---------- */
let config = {};
async function loadConfig() {
  try { config = await (await fetch('/api/config', { cache: 'no-store' })).json(); } catch {}
  if (config.name) { document.title = config.name; document.querySelectorAll('.js-name').forEach(el => el.textContent = config.name); }
}

/* ---------- onboarding (first visit only) ---------- */
const wizard = { step: 1, data: {} };
function showStep(n) {
  wizard.step = n;
  document.querySelectorAll('#setup-form fieldset').forEach(f => f.hidden = +f.dataset.step !== n);
  document.querySelectorAll('#steps li').forEach((li, i) => { li.classList.toggle('done', i + 1 < n); li.classList.toggle('now', i + 1 === n); });
  $('#setup-back').hidden = n === 1 || n === 5;
  $('#setup-next').hidden = n === 5;
  $('#setup-next').textContent = n === 4 ? 'Set up my cinema' : 'Continue';
  $('#setup-err').hidden = true;
  const first = document.querySelector(`#setup-form fieldset[data-step="${n}"] input[type="text"], #setup-form fieldset[data-step="${n}"] input[type="password"]`); first?.focus();
  if (n === 4) loadSources();
}
async function loadSources() {
  const box = $('#sources'); if (box.dataset.loaded) return;
  try {
    const d = await (await fetch('/api/setup/sources', { cache: 'no-store' })).json();
    box.innerHTML = d.sources?.length ? d.sources.map(s => `<label><input type="checkbox" name="indexers" value="${esc(s.id)}"><span><span class="n">${esc(s.name)}</span><span class="d">${esc(s.description)}</span></span></label>`).join('')
      : `<span class="label">None available yet — you can add sources later.</span>`;
    box.dataset.loaded = '1';
  } catch { box.innerHTML = `<span class="label">Could not load sources — you can add them later.</span>`; }
}
async function runSetup() {
  showStep(5);
  const log = $('#setup-log'); log.innerHTML = '<li class="busy">Talking to the projection booth…</li>';
  try {
    const r = await fetch('/api/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(wizard.data) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || r.statusText);
    log.innerHTML = (d.log || []).map(l => `<li>${esc(l)}</li>`).join('') + '<li>Done.</li>';
    const b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = 'Enter'; b.style.marginTop = '10px';
    b.onclick = () => { $('#setup').hidden = true; document.body.dataset.view = 'login'; $('#login').hidden = false; $('#login-form').user.value = wizard.data.admin_user; $('#login-form').pass.focus(); loadConfig(); };
    $('#setup-form').appendChild(b); b.focus();
  } catch (e) { log.innerHTML = `<li>Something went wrong: ${esc(e.message)}</li>`; $('#setup-back').hidden = false; }
}
$('#setup-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = new FormData(e.target); const err = (m) => { $('#setup-err').textContent = m; $('#setup-err').hidden = false; };
  if (wizard.step === 1) { const v = (f.get('name') || '').trim(); if (!v) return err('Give it a name.'); wizard.data.name = v; return showStep(2); }
  if (wizard.step === 2) {
    const u = (f.get('admin_user') || '').trim(), p = f.get('admin_password') || '';
    if (!u) return err('Choose a username.'); if (p.length < 8) return err('Use a password of at least 8 characters — this account can be reached from the internet.');
    wizard.data.admin_user = u; wizard.data.admin_password = p; return showStep(3);
  }
  if (wizard.step === 3) { wizard.data.letterboxd_user = (f.get('letterboxd_user') || '').trim().replace(/^.*letterboxd\.com\//, '').replace(/\/.*$/, ''); return showStep(4); }
  if (wizard.step === 4) { wizard.data.indexers = f.getAll('indexers'); return runSetup(); }
});
$('#setup-back').onclick = () => showStep(Math.max(1, wizard.step - 1));

async function start() {
  document.documentElement.style.setProperty('--grain', makeGrain());
  await loadConfig();
  if (config.setup) { document.body.dataset.view = 'setup'; $('#setup').hidden = false; showStep(1); return; }
  if (!session) { document.body.dataset.view = 'login'; $('#login').hidden = false; return; }
  $('#bar').hidden = false; $('#me').textContent = session.userName[0].toUpperCase();
  api('/Users/Me').then(me => { session.admin = !!me?.Policy?.IsAdministrator; }).catch(() => {});
  $('#reel').innerHTML = `<div class="loading">Loading</div>`;
  try { films = await loadFilms(); } catch (e) { $('#reel').innerHTML = `<div class="loading">Could not load the library — ${esc(e.message)}</div>`; return; }
  if (!films.length) { $('#reel').innerHTML = `<div class="loading">No films yet</div>`; return; }
  renderReel(reelOrder());
  setView(store.get('view') || 'reel');
  prefetchMeta();
}
async function prefetchMeta() {
  const queue = films.slice(); const worker = async () => { while (queue.length) await getMeta(queue.shift()); };
  await Promise.all(Array.from({ length: 4 }, worker));
  buildCountries();
}
function reelOrder() {
  const base = visible();
  if (startMode !== 'random') return base;
  const l = base.slice();
  for (let i = l.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [l[i], l[j]] = [l[j], l[i]]; }
  return l;
}
function setStart(mode) {
  startMode = mode; store.set('start', mode);
  document.querySelectorAll('[data-start]').forEach(b => b.setAttribute('aria-pressed', b.dataset.start === mode));
  if (films.length) { renderReel(reelOrder()); $('#reel').scrollTo({ top: 0, behavior: 'instant' }); }
}

/* ---------- countries ---------- */
function buildCountries() {
  const counts = new Map();
  films.forEach(f => { if (f.c) counts.set(f.c, (counts.get(f.c) || 0) + 1); });
  const list = [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  $('#countries').innerHTML = [`<button data-c="" ${country ? '' : 'aria-pressed="true"'}>All countries <span class="n">${films.length}</span></button>`]
    .concat(list.map(([c, n]) => `<button data-c="${esc(c)}" ${country === c ? 'aria-pressed="true"' : ''}>${esc(c)} <span class="n">${n}</span></button>`)).join('');
}
function setCountry(c) {
  country = c || null;
  $('#country-label').textContent = country || 'Countries';
  $('#country-btn').classList.toggle('active', !!country);
  $('#countries').hidden = true; $('#country-btn').setAttribute('aria-expanded', 'false');
  buildCountries();
  renderReel(reelOrder()); $('#reel').scrollTo({ top: 0, behavior: 'instant' });
  if (view === 'grid') { renderGrid(); window.scrollTo({ top: 0, behavior: 'instant' }); }
}

$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault(); const fd = new FormData(e.target); $('#login-err').hidden = true;
  try { await signIn(fd.get('user'), fd.get('pass')); $('#login').hidden = true; start(); }
  catch { $('#login-err').textContent = 'That username and password did not match.'; $('#login-err').hidden = false; }
});
$('#v-reel').onclick = () => { setView('reel'); store.set('view', 'reel'); };
$('#v-grid').onclick = () => { setView('grid'); store.set('view', 'grid'); };
$('#pick').onclick = randomFilm;
$('#country-btn').onclick = () => { const m = $('#countries'); m.hidden = !m.hidden; $('#country-btn').setAttribute('aria-expanded', String(!m.hidden)); $('#menu').hidden = true; };
$('#countries').addEventListener('click', (e) => { const b = e.target.closest('[data-c]'); if (b) setCountry(b.dataset.c); });
$('#sort').addEventListener('click', (e) => { const b = e.target.closest('[data-sort]'); if (!b) return; sortKey = b.dataset.sort; $('#sort').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b)); renderGrid(); });
$('#me').onclick = () => { $('#menu').hidden = !$('#menu').hidden; };
document.querySelectorAll('[data-start]').forEach(b => { b.setAttribute('aria-pressed', b.dataset.start === startMode); b.onclick = () => setStart(b.dataset.start); });
$('#signout').onclick = signOut;
document.addEventListener('click', (e) => {
  if (!e.target.closest('#menu, #me')) $('#menu').hidden = true;
  if (!e.target.closest('#countries, #country-btn')) { $('#countries').hidden = true; $('#country-btn').setAttribute('aria-expanded', 'false'); }
  const fc = e.target.closest('[data-filter-country]'); if (fc) { const f = films.find(x => x.id === fc.dataset.filterCountry); if (f?.c) { closeFilm(); setCountry(f.c === country ? '' : f.c); } return; }
  const p = e.target.closest('[data-play]'); if (p) { const f = films.find(x => x.id === p.dataset.play); if (f) return playFilm(f); }
  const b = e.target.closest('[data-open]'); if (b) { const f = films.find(x => x.id === b.dataset.open); if (f) openFilm(f); }
});
/* Lights down: the page dims to black, then the player takes over and the picture fades up. */
function playFilm(f) {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.body.classList.add('lights-down');
  setTimeout(() => Player.open(f, { api, session, onStop: (film) => {
    document.body.classList.remove('lights-down');
    document.querySelectorAll(`[data-play="${film.id}"]`).forEach(b => { b.innerHTML = `${play} ${film.pos > 600000000 ? 'Resume' : 'Play'}`; });
  }}), reduce ? 0 : 1500);
}
document.addEventListener('keydown', (e) => {
  const typing = ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName);
  if (e.key === 'Escape') { closeFilm(); $('#menu').hidden = true; $('#countries').hidden = true; }
  if (typing || e.metaKey || e.ctrlKey) return;
  if (e.key.toLowerCase() === 'r') randomFilm();
  if (e.key.toLowerCase() === 'g') setView(view === 'grid' ? 'reel' : 'grid');
});
start();
