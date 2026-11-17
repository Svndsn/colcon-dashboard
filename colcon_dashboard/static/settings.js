import { getNotifyMode, notifyBlocked, serverNotifies, setNotifyMode, testNotify } from './notify.js';
import { loadScanRoots, mountScanRoots } from './pickers.js';
import { App } from './state.js';
import { savedTheme, setTheme } from './theme.js';
import { $, copyText, esc, fmtAgo, icon, initPanel, restartServer } from './util.js';

/* ---------------- settings side panel ----------------
   One place for the choices this browser keeps (theme, notifications,
   log panes, layout), the scan roots (saved in config.ini at once), and
   a read-only view of the rest of the server configuration. The header buttons stay as shortcuts; the
   dialog reads their state each time it opens. */

// the keys of the page layout; "reset" forgets them
const LAYOUT_KEYS = ['cmc-view', 'cmc-split', 'cmc-dock-h', 'cmc-layout',
                     'cmc-gsort', 'cmc-spread', 'cmc-scope', 'cmc-wssort'];

const pick = (seg, v) => seg.querySelectorAll('button').forEach(b =>
  b.classList.toggle('on', b.dataset.v === v));

function render() {
  pick($('#setTheme'), savedTheme());
  const mode = getNotifyMode();
  pick($('#setNotify'), mode);
  const blocked = notifyBlocked();
  const note = $('#setNotifyNote');
  note.textContent = blocked ? `Desktop notifications do not work: ${blocked}.`
    : mode !== 'off' && serverNotifies() ? 'The server shows them on this desktop, also with no dashboard open.' : '';
  note.hidden = !note.textContent;
  $('#setNotifyTest').disabled = mode === 'off';
  $('#setTs').checked = localStorage.getItem('cmc-ts') !== '0';
  $('#setWrap').checked = localStorage.getItem('cmc-wrap') === '1';
  $('#setRaw').checked = localStorage.getItem('cmc-raw') === '1';
  loadScanRoots();
  renderServer();
  loadServerInfo();
}

// how the server runs, and the switches for the service and the tray
let serverInfo = null;
async function loadServerInfo() {
  try {
    serverInfo = await (await fetch('/api/server', { cache: 'no-store' })).json();
  } catch (e) {
    serverInfo = null;
  }
  renderServer();
  renderSwitches();
}

function renderSwitches(message) {
  const s = serverInfo;
  const login = $('#setLogin');
  const tray = $('#setTray');
  login.checked = !!s?.login;
  login.disabled = !s?.systemd;
  tray.checked = !!s?.tray?.autostart;
  tray.disabled = !s?.tray?.supported;
  const notes = [];
  if (message) notes.push(message);
  if (s && !s.systemd) notes.push('Start at login needs systemd user services, which this machine does not have.');
  if (s && !s.tray?.supported) notes.push('The tray icon needs PyGObject: sudo apt install python3-gi');
  const note = $('#setServerNote');
  note.textContent = notes.join(' ');
  note.hidden = !notes.length;
}

async function setSwitch(kind, on) {
  try {
    const r = await (await fetch(`/api/server/${kind}?on=${on ? 1 : 0}`, { method: 'POST' })).json();
    const { ok, message, ...info } = r;
    serverInfo = info;
    renderSwitches(ok ? '' : message);
  } catch (e) {
    renderSwitches('The server does not answer.');
  }
}

async function restartFromSettings() {
  const btn = $('#restartBtn');
  btn.disabled = true;
  btn.textContent = 'Restarting…';
  if (await restartServer()) return;
  btn.disabled = false;
  btn.textContent = 'Restart the server';
  renderSwitches('The server did not come back. Start it from the tray icon or a terminal.');
}

// a version links to its release notes: the tag name equals the version
const releaseUrl = v =>
  `https://github.com/autowarefoundation/colcon-dashboard/releases/tag/${encodeURIComponent(v)}`;

// the About section: this version, the newest version from the last
// check, and the command that upgrades this install
function renderAbout(message) {
  const ver = App.cfg?.version;
  const verLink = $('#setVersion');
  verLink.textContent = ver ? `v${ver}` : 'unknown';
  if (ver) verLink.href = releaseUrl(ver);
  else verLink.removeAttribute('href');
  const u = serverInfo?.update;
  const muted = s => `<span class="muted">${s}</span>`;
  const link = v => `<a href="${esc(releaseUrl(v))}" target="_blank" rel="noopener">v${esc(v)}</a>`;
  const when = u?.checked_at ? ` ${muted(`(checked ${fmtAgo(u.checked_at)})`)}` : '';
  // the versions come from apt or PyPI: escape
  $('#setLatest').innerHTML = !u ? muted('unknown')
    : u.installed ? `${link(u.installed)} is installed. ${u.auto_restart
      ? 'The server restarts to it by itself when no build runs.' : 'Restart the server to run it.'}`
      : u.newer ? `${link(u.latest)} is available${when}`
        : u.latest ? `this is the newest version${when}`
          : u.checked_at ? `${muted('unknown: the check failed')}${when}`
            : muted('not checked yet');
  const check = $('#setCheck');
  check.disabled = !u;
  check.title = u?.source === 'apt' ? 'read the newest version from the apt package lists now'
    : 'ask PyPI for the newest version now';
  $('#setUpgrade').innerHTML = !u ? muted('unknown')
    : `<code>${esc(u.command)}</code> <button class="copy" data-copy="${esc(u.command)}" title="copy the command" aria-label="copy the command">${icon('copy')}</button>`;
  const note = $('#setUpdateNote');
  note.textContent = message || '';
  note.hidden = !message;
}

async function checkUpdate() {
  const btn = $('#setCheck');
  btn.disabled = true;
  btn.textContent = 'Checking…';
  let message = '';
  try {
    const { ok, ...update } = await (await fetch('/api/update/check', { method: 'POST' })).json();
    if (serverInfo) serverInfo.update = update;
    if (!ok) message = update.source === 'apt' ? 'apt knows no version of the package.' : 'PyPI did not answer.';
  } catch (e) {
    message = 'The server does not answer.';
  }
  btn.textContent = 'Check now';
  renderAbout(message);
}

function renderServer() {
  const cfg = App.cfg?.config;
  renderAbout();
  if (!cfg) {
    $('#setServer').innerHTML = '<dt>configuration</dt><dd>not loaded</dd>';
    return;
  }
  const unset = s => `<span class="muted">${s}</span>`;
  const keep = cfg.auto_prune_keep;
  const runs = !serverInfo ? unset('unknown')
    : serverInfo.service ? 'as the systemd user service'
      : `as a process that you started (pid ${serverInfo.pid})`;
  const rows = [
    ['runs', runs],
    ['configuration file', `<code>${esc(cfg.path)}</code> <button class="copy" data-copy="${esc(cfg.path)}" title="copy the path" aria-label="copy the path">${icon('copy')}</button>`
      + (cfg.exists ? '' : ` ${unset('(not created yet: every value is the default)')}`)],
    ['address', esc(location.host)],
    ['log directory', cfg.log_base ? `<code>${esc(cfg.log_base)}</code>` : `<code>log</code> ${unset('(default)')}`],
    ['old builds', keep != null && keep >= 0 ? `keep the newest ${keep} of each kind` : unset('kept forever')],
    ['editor links', cfg.editor_url ? `<code>${esc(cfg.editor_url)}</code>` : unset('off')],
    ['claude CLI', cfg.claude_bin ? `<code>${esc(cfg.claude_bin)}</code>` : unset('found on PATH')],
    ['installed with', { apt: 'the deb package (apt)', pipx: 'pipx', pip: 'pip' }[App.cfg.install] || unset('unknown')],
    ['update check', !cfg.check_updates ? unset('off')
      : App.cfg.install === 'apt' ? 'every hour, from the apt package lists' : 'once a day, from PyPI'],
  ];
  $('#setServer').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
}

export function initSettings() {
  const overlay = $('#settings');
  mountScanRoots($('#setRoots'));
  const close = () => { overlay.hidden = true; };
  $('#settingsBtn').onclick = () => {
    if (overlay.hidden) render();
    overlay.hidden = !overlay.hidden;
  };
  overlay.querySelector('.sclose').onclick = close;
  initPanel(overlay, $('#settingsBtn'), { side: true });
  overlay.addEventListener('click', ev => {
    const copy = ev.target.closest('button.copy');
    if (copy) copyText(copy.dataset.copy);
  });
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && !overlay.hidden && $('#confirm').hidden) close();
  });
  $('#setTheme').onclick = ev => {
    const b = ev.target.closest('button');
    if (b) { setTheme(b.dataset.v); render(); }
  };
  $('#setNotify').onclick = ev => {
    const b = ev.target.closest('button');
    if (b) { setNotifyMode(b.dataset.v); render(); }
  };
  $('#setNotifyTest').onclick = testNotify;
  $('#setLogin').onchange = ev => setSwitch('login', ev.target.checked);
  $('#setTray').onchange = ev => setSwitch('tray', ev.target.checked);
  $('#restartBtn').onclick = restartFromSettings;
  $('#setCheck').onclick = checkUpdate;
  // a log choice holds for the open panes too: their own buttons flip it,
  // and those buttons keep the choice for the next panes
  const logChoice = (id, btn) => {
    $(id).onchange = ev => {
      for (const b of document.querySelectorAll(`#panes .pane ${btn}`)) {
        if (!b.closest('.pane').querySelector('.tsbtn')) continue;  // prose panes keep their wrap
        if (b.classList.contains('on') !== ev.target.checked) b.click();
      }
      const key = { '.tsbtn': 'cmc-ts', '.wrapbtn': 'cmc-wrap', '.rawbtn': 'cmc-raw' }[btn];
      localStorage.setItem(key, ev.target.checked ? '1' : '0');
    };
  };
  logChoice('#setTs', '.tsbtn');
  logChoice('#setWrap', '.wrapbtn');
  logChoice('#setRaw', '.rawbtn');
  $('#setReset').onclick = () => {
    for (const k of LAYOUT_KEYS) localStorage.removeItem(k);
    location.reload();
  };
  $('#stopBtn').addEventListener('click', close);  // the confirmation takes over
}
