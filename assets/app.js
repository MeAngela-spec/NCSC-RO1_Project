'use strict';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c =>
  ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const state = {
  user: null, csrf: '', collections: [], rows: [], deleted: [], record: null, editing: false,
  page: new URLSearchParams(location.search).get('page') === 'documents' ? 'documents' : 'dashboard', settingsOpen: false, collection: '', query: '', status: '', draft: null, dirty: false,
  selected: new Set(), selecting: false
};
const departments = {ORD:'Office of the Regional Director', AFS:'Administrative and Finance Section', OPS:'Operations'};
const mappingLabels = {
  hard:'Hard copy routed', reference:'Reference no.', subject:'Subject',
  assigned:'Assigned to', action:'Requested actions', status:'Status'
};
const actions = [
  'Approved', 'Disapproved', 'Request Initial/Signature', 'Appropriate Staff Action',
  'Comment/Recommendation', 'Rewrite/Redraft', 'For Reference/Information', 'See Me / Call Me', 'File'
];
const standard = ['Hard Copy Routed', 'Ref. No.', 'Subject', 'Assigned to', 'Requested Actions',
  'Action Taken', 'MOV 1', 'MOV 2', 'Status'];
const actionTakenOptions = ['Acknowledged receipt', 'Under review', 'Coordinated with concerned office',
  'Prepared response', 'Submitted required document', 'Forwarded for approval', 'Filed', 'Completed'];
const shapes = {
  settings:'<path d="m9 3-.5 3-2 1-2.8-1-2 3 2.3 2v2L1.7 15l2 3 2.8-1 2 1 .5 3h4l.5-3 2-1 2.8 1 2-3-2.3-2v-2l2.3-2-2-3-2.8 1-2-1-.5-3z"/><circle cx="11" cy="12" r="3"/>',
  chevron:'<path d="m9 5 7 7-7 7"/>',
  grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  file:'<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6m-6 4h6"/>',
  upload:'<path d="M12 16V3m-4 4 4-4 4 4M4 16v5h16v-5"/>',
  download:'<path d="M12 3v13m-4-4 4 4 4-4M4 16v5h16v-5"/>',
  trash:'<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
  users:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2m1-17a3 3 0 0 1 0 6m3 11v-2a6 6 0 0 0-3-5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check:'<path d="m5 12 4 4 10-10"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  print:'<path d="M6 8V3h12v5M6 17H3V8h18v9h-3M6 14h12v7H6zM17 11h1"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5M5 7a8 8 0 0 1 13-2l2 2M4 17l2 2a8 8 0 0 0 13-2"/>',
  help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 8a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4m0 4h.01"/>',
  logout:'<path d="M9 3H4v18h5m0-9h12m-4-4 4 4-4 4"/>',
  lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 5v2"/>',
  eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  folder:'<path d="M3 6h7l2 3h9v12H3z"/>',
  edit:'<path d="m14 5 5 5M4 20l5-1L21 7l-5-5L4 14v6Z"/>'
};
const icon = name => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + shapes[name] + '</svg>';
const button = (label, action, variant = '', symbol = '') =>
  '<button type="button" class="btn ' + variant + '" data-action="' + action + '">' +
  (symbol ? icon(symbol) : '') + label + '</button>';
const opts = (values, selected = '') => values.map(item => {
  const [value, label] = Array.isArray(item) ? item : [item, item];
  return '<option value="' + esc(value) + '"' + (value === selected ? ' selected' : '') + '>' + esc(label) + '</option>';
}).join('');
const editor = () => ['admin', 'records'].includes(state.user?.role);
const mapped = (r, key) => String(r.cells[r.mappings[key]] || '').trim();
const statusOf = r => mapped(r, 'status') || (mapped(r, 'assigned') ? 'Routed' : 'For Routing');
const subjectOf = r => mapped(r, 'subject') || Object.values(r.cells).find(Boolean) || 'Untitled document';
const refOf = r => mapped(r, 'reference') || r.id.slice(0, 8).toUpperCase();
const normalize = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');
const pill = status => '<span class="pill ' + normalize(status) + '">' + esc(status) + '</span>';
function formatDate(value) {
  const date = new Date(value);
  return isNaN(date) ? value : new Intl.DateTimeFormat('en-PH', {dateStyle:'medium', timeStyle:'short'}).format(date);
}
function toast(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $('toast').hidden = true, 5000);
}
async function api(path, body) {
  const config = body === undefined ? {} : {
    method: 'POST', headers: {'X-CSRF-Token': state.csrf},
    body: body instanceof FormData ? body : JSON.stringify(body)
  };
  if (body !== undefined && !(body instanceof FormData)) config.headers['Content-Type'] = 'application/json';
  const response = await fetch(path, config);
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'The request could not be completed.');
  return result;
}
function modal(title, subtitle, content, footer = '', size = 'wide') {
  $('dialog').dataset.size = size;
  $('dialog').innerHTML = '<header><div><h2 id="modalTitle">' + esc(title) + '</h2>' +
    (subtitle ? '<p>' + esc(subtitle) + '</p>' : '') + '</div>' +
    '<button type="button" class="btn icon" data-action="close" aria-label="Close dialog">' + icon('close') + '</button></header>' +
    '<div class="dialog-body">' + content + '</div><footer><div id="modalError" class="error" role="alert" hidden></div>' +
    '<div class="footer-actions">' + footer + '</div></footer>';
  $('dialog').setAttribute('aria-labelledby', 'modalTitle');
  if (!$('dialog').open) $('dialog').showModal();
  $('dialog').scrollTop = 0;
}
function showError(error) {
  const el = $('modalError');
  if (el && $('dialog').open) {
    el.hidden = false;
    el.textContent = error.message;
  } else toast(error.message);
}
async function loadData() {
  [state.collections, state.rows] = await Promise.all([api('/api/collections'), api('/api/register')]);
  if (editor()) state.deleted = await api('/api/register?deleted=1');
  if (state.collection && !state.collections.some(c => c.id === state.collection)) state.collection = '';
}
async function start() {
  try {
    const me = await api('/api/me');
    state.user = me.user;
    state.csrf = me.csrf;
    if (!me.user) return login(me.setup);
    await loadData();
    render();
  } catch (err) { toast(err.message); }
}

/* Department login and offline recovery */
function passwordInput(name, label, autocomplete = 'current-password') {
  return '<label>' + label + '<span class="password-wrap"><input type="password" name="' + name +
    '" required minlength="8" autocomplete="' + autocomplete + '">' +
    '<button type="button" data-reveal="' + name + '" aria-label="Show ' + label.toLowerCase() + '">' + icon('eye') +
    '</button></span></label>';
}
function login(setup = false) {
  const form = setup
    ? '<form id="loginForm" class="stack"><label>Your full name<input name="name" required autocomplete="name"></label>' +
      '<label>Your username<input name="username" required autocomplete="username" placeholder="e.g. maria.santos"></label>' +
      passwordInput('password', 'Password', 'new-password') +
      '<div class="error" id="loginError" role="alert" hidden></div><button class="btn primary login-submit">Create administrator account</button></form>'
    : '<form id="loginForm" class="stack"><label>Username<input name="username" placeholder="Enter your username" required autocomplete="username" spellcheck="false" autocapitalize="none"></label>' +
      passwordInput('password', 'Password') +
      '<div class="login-links"><button type="button" class="btn link" data-action="forgot">Forgot password?</button></div>' +
      '<div class="error" id="loginError" role="alert" hidden></div><button class="btn primary login-submit">Sign in</button></form>';
  $('app').innerHTML = '<div class="login"><header class="login-header"><div class="login-brand">' +
    '<img src="/assets/logo.jpg" alt="NCSC seal" width="56" height="56"><div><span>Republic of the Philippines</span>' +
    '<strong>NATIONAL COMMISSION<br>OF SENIOR CITIZENS</strong></div></div>' +
    '<div class="login-office"><strong>Regional Office I</strong><span>Document services</span></div></header>' +
    '<main class="login-stage"><img class="login-background" src="/assets/login-background.jpg" alt="" width="2048" height="675" fetchpriority="high">' +
    '<section class="login-caption" aria-labelledby="loginTitle"><div class="eyebrow">NCSC RO1 · STAFF PORTAL</div>' +
    '<h1 id="loginTitle">Document Routing<br>&amp; Tracking System</h1>' +
    '<p>Organized correspondence.<br> Coordinated action. Better service.</p></section>' +
    '<section class="login-panel" aria-labelledby="loginHeading"><article class="login-card">' +
    '<h2 id="loginHeading">' + (setup ? 'Set up your workspace' : 'Welcome back') + '</h2><p class="intro">' +
    (setup ? 'Create your administrator account under ORD to get started.' : 'Sign in to your NCSC RO1 workspace.') +
    '</p>' + form + '<p class="login-foot">For authorized NCSC personnel only</p></article></section></main></div>';
  $('loginForm').onsubmit = async e => {
    e.preventDefault();
    e.submitter.disabled = true;
    try {
      const result = await api(setup ? '/api/setup' : '/api/login', Object.fromEntries(new FormData(e.target)));
      await start();
      if (result.recovery_codes) recoveryCodes(result.recovery_codes);
    } catch (err) {
      $('loginError').hidden = false;
      $('loginError').textContent = err.message;
    } finally { e.submitter.disabled = false; }
  };
}
function recoveryCodes(codes) {
  modal('Save your account recovery code', 'Store your recovery code securely.',
    '<p class="notice">Your recovery code lets you reset your password offline. Each successful reset replaces the code. Keep a copy in a secure place.</p>' +
    '<div class="recovery-grid">' + Object.entries(codes).map(([name, code]) =>
      '<div><label>' + esc(name) + '</label><div class="recovery-code">' + esc(code) + '</div></div>').join('') + '</div>',
    button('Download codes', 'downloadcodes', '', 'download') + button('Codes saved', 'close', 'primary'));
  $('dialog').dataset.codes = JSON.stringify(codes);
}
function forgotPassword() {
  modal('Reset your password', 'Use your saved recovery code or request a replacement from the account administrator.',
    '<form id="recoverForm" class="stack"><label>Username<input name="username" required placeholder="Your username" autocomplete="username"></label>' +
    '<label>Recovery code<input name="code" required autocomplete="off" spellcheck="false" placeholder="XXXXXX-XXXXXX-XXXXXX-XXXXXX"></label>' +
    passwordInput('password', 'New password', 'new-password') + '</form>',
    button('Cancel', 'close') + '<button form="recoverForm" class="btn primary">Reset password</button>');
  $('recoverForm').onsubmit = async e => {
    e.preventDefault();
    e.submitter.disabled = true;
    try {
      const body = Object.fromEntries(new FormData(e.target));
      const result = await api('/api/recover', body);
      recoveryCodes({[body.username.toUpperCase()]: result.recovery_code});
      toast('Password reset. Log in with the new password.');
    } catch (err) { showError(err); e.submitter.disabled = false; }
  };
}

/* Workspace navigation and document register */
function navItem(page, text, symbol, count) {
  return '<button type="button" class="nav-item ' + (state.page === page ? 'active' : '') +
    '" data-page="' + page + '"' + (state.page === page ? ' aria-current="page"' : '') + '>' +
    icon(symbol) + text + (count !== undefined ? '<span class="count">' + count + '</span>' : '') + '</button>';
}
function render() {
  const u = state.user;
  $('app').innerHTML = '<header class="app-header"><div class="brand"><img src="/assets/logo.jpg" alt="NCSC seal">' +
    '<div><small>Republic of the Philippines</small><strong>NATIONAL COMMISSION<br>OF SENIOR CITIZENS</strong></div></div>' +
    '<div class="header-right"><span>Document Routing &amp; Tracking · Region I</span><span class="department-chip">' + esc(u.department) + ' workspace</span></div></header>' +
    '<div class="workspace"><aside class="sidebar"><div class="sidebar-navigation"><p class="nav-label">WORKSPACE</p><nav aria-label="Main navigation">' +
    navItem('dashboard', 'Dashboard', 'grid') + navItem('documents', editor() ? 'Document register' : 'Assigned documents', 'file', state.rows.length) +
    (editor() ? navItem('imports', 'Imported files', 'upload') : '') +
    '<div class="settings-menu"><button type="button" class="nav-item settings-toggle '+(['accounts','deleted'].includes(state.page)?'active':'')+'" data-action="settings" aria-expanded="'+state.settingsOpen+'" aria-controls="settingsMenu">'+icon('settings')+'Settings<span class="nav-chevron">'+icon('chevron')+'</span></button>'+
    '<div id="settingsMenu" class="settings-items" '+(!state.settingsOpen?'hidden':'')+'>'+
    (u.role === 'admin' ? navItem('accounts', 'Account management', 'users') : '') +
    '<button class="nav-item" data-action="password">'+icon('lock')+'Change password</button>'+
    '<button class="nav-item" data-action="guide">'+icon('help')+'Quick guide</button>'+
    (editor() ? navItem('deleted', 'Deleted documents', 'trash',state.deleted.length || undefined) : '') +
    '</div></div></nav></div><div class="sidebar-bottom">'+
    '<div class="profile"><span class="avatar">'+esc(u.department)+'</span><div><strong title="'+esc(u.name)+'">'+esc(u.name)+'</strong><small>'+esc(u.username)+' · '+esc(u.department)+'</small></div></div>'+
    '<button class="nav-item logout-item" data-action="logout">'+icon('logout')+'Log out</button>'+
    '</div></aside><main class="content" id="content"></main></div>';
  if (state.page === 'dashboard') renderDashboard();
  else if (state.page === 'imports') renderImports();
  else if (state.page === 'accounts') renderAccounts();
  else renderDocuments();
}
function pageHeading(title, subtitle, actionsMarkup = '') {
  return '<p class="breadcrumb">NCSC RO1 / ' + esc(title) + '</p><div class="page-heading"><div><h1>' + esc(title) +
    '</h1><p>' + esc(subtitle) + '</p></div><div class="tools">' + actionsMarkup + '</div></div>';
}
function statsMarkup() {
  const stats = [
    ['All documents', state.rows.length, 'file', '', ''],
    ['For routing', state.rows.filter(r => statusOf(r) === 'For Routing').length, 'clock', 'orange', 'For Routing'],
    ['In progress', state.rows.filter(r => ['Routed', 'Received', 'Ongoing'].includes(statusOf(r))).length, 'refresh', '', 'active'],
    ['Completed', state.rows.filter(r => statusOf(r) === 'Completed').length, 'check', 'green', 'Completed']
  ];
  return '<section class="stats" aria-label="Document summary">' + stats.map(([label, count, symbol, color, filter]) =>
    '<button class="stat ' + (filter && state.status === filter ? 'active' : '') + '" data-status="' + filter + '">' +
    '<span><span class="label">' + label + '</span><strong>' + count + '</strong></span><span class="stat-icon ' + color + '">' + icon(symbol) + '</span></button>').join('') + '</section>';
}
function renderDashboard() {
  $('content').innerHTML = pageHeading('Dashboard', departments[state.user.department] || state.user.name,
    editor() ? button('New document', 'new', '', 'plus') + button('Import file', 'import', 'primary', 'upload') : button('Refresh', 'refresh', '', 'refresh')) +
    statsMarkup() + '<section class="card"><div class="card-head"><div><h2>Recent documents</h2><small>The latest correspondence in your workspace.</small></div>' +
    button('View register', 'register', 'link') + '</div>' +
    (state.rows.length ? '<div class="recent-list">' + state.rows.slice(0, 8).map(r =>
      '<button class="recent-item" data-record="' + r.id + '"><span class="stat-icon">' + icon('file') + '</span><span><strong>' +
      esc(subjectOf(r)) + '</strong><small>' + esc(refOf(r)) + ' · ' + esc(mapped(r, 'assigned') || 'Awaiting assignment') +
      '</small></span>' + pill(statusOf(r)) + '</button>').join('') + '</div>' : emptyMarkup()) + '</section>';
}
function emptyMarkup(deleted = false) {
  return '<div class="empty"><div class="empty-icon">' + icon(deleted ? 'trash' : 'folder') + '</div><h2>' +
    (deleted ? 'No deleted documents' : state.user.role === 'staff' ? 'No assigned documents yet' : 'Your register starts here') +
    '</h2><p>' + (deleted ? 'Documents moved here can be restored with their files and history.' :
      state.user.role === 'staff' ? 'Documents routed to your department will appear here. Use Refresh to load the latest assignments.' :
      'Import your existing Excel matrix or an incoming document. Review the rows, then start tracking and routing.') +
    '</p>' + (!deleted && editor() ? button('Import your first file', 'import', 'primary', 'upload') : '') + '</div>';
}
function filteredRows() {
  const rows = state.page === 'deleted' ? state.deleted : state.rows;
  const query = state.query.toLowerCase();
  return rows.filter(r => (!state.collection || r.collection_id === state.collection) &&
    (!query || [...Object.values(r.cells),r.source?.filename,r.source?.sender].some(v => String(v || '').toLowerCase().includes(query))) &&
    (!state.status || (state.status === 'active' ? ['Routed', 'Received', 'Ongoing'].includes(statusOf(r)) : statusOf(r) === state.status)));
}
function isRowNumber(column) { return ['no','rowno','rownumber','sourcerowno','sourcerownumber','serialno','serialnumber','sno'].includes(normalize(column)); }
function rowNumber(record,index = state.rows.findIndex(r=>r.id===record.id)) {
  const column = record.columns.find(c=>isRowNumber(c) && String(record.cells[c] || '').trim());
  return column ? record.cells[column] : String(Math.max(0,index)+1);
}
function shownColumns() {
  const collection = state.collections.find(c => c.id === state.collection);
  if (collection) return ['No.',...collection.columns.filter(c=>!isRowNumber(c))];
  const rows = state.page === 'deleted' ? state.deleted : state.rows;
  return ['No.',...standard,...[...new Set(rows.flatMap(r=>r.columns).filter(c=>!standard.includes(c) && !isRowNumber(c)))].sort((a,b)=>a.localeCompare(b))];
}
function renderDocuments() {
  const deleted = state.page === 'deleted';
  const title = deleted ? 'Deleted documents' : editor() ? 'Document register' : 'Assigned documents';
  const actionsMarkup = deleted ? '' : editor() ?
    button('New document', 'new', '', 'plus') + button('Import file', 'import', 'primary', 'upload') :
    button('Refresh', 'refresh', '', 'refresh');
  $('content').innerHTML = pageHeading(title, deleted ? 'Restore documents, or permanently delete them with administrator access.' :
    'Review, route, and track correspondence across the regional office.', actionsMarkup) +
    (!deleted ? statsMarkup() : '') + '<section class="card">' +
    '<div class="card-head"><div><h2>' + (deleted ? 'Recently deleted' : 'Tracking matrix') +
    '</h2><small>Standard tracking fields stay in a fixed order. Additional imported fields follow.</small></div><div class="tools">' +
    (!deleted && state.rows.length ? button(state.selecting ? 'Done selecting' : 'Select documents', 'selectmode', state.selecting ? 'primary' : '', 'file') + button('Print matrix', 'printmatrix', '', 'print') +
      button('Export file', 'export', '', 'download') : '') + '</div></div>' +
    ((deleted ? state.deleted : state.rows).length ? '<div class="filters"><label class="search">' + icon('search') +
      '<input id="search" type="search" aria-label="Search all columns" placeholder="Search reference, subject, or any detail…" value="' + esc(state.query) + '"></label>' +
      '<select id="collectionFilter" aria-label="Filter worksheet">' + opts([['', 'All worksheets'], ...state.collections.map(c => [c.id, c.name])], state.collection) + '</select>' +
      '<select id="statusFilter" aria-label="Filter status">' + opts([['', 'All statuses'], ...['For Routing', 'Routed', 'Received', 'Ongoing', 'Completed']], state.status) +
      '</select>' + button('Refresh', 'refresh', '', 'refresh') + button('Clear', 'clear', 'link') + '</div>' +
      '<div id="selectionBar"></div><div class="table-wrap"><table id="matrix"><thead id="matrixHead"></thead><tbody id="rows"></tbody></table></div>' +
      '<div class="table-foot"><span id="rowCount"></span><span>Scroll horizontally to view all columns</span></div>' : emptyMarkup(deleted)) + '</section>';
  if ($('search')) {
    drawRows();
    $('search').oninput = e => { state.query = e.target.value; drawRows(); };
    $('collectionFilter').onchange = e => { state.collection = e.target.value; renderDocuments(); };
    $('statusFilter').onchange = e => { state.status = e.target.value; renderDocuments(); };
  }
}
function selectedRows() {
  const available = new Map(state.rows.map(r=>[r.id,r]));
  return [...state.selected].map(id=>available.get(id)).filter(Boolean);
}
function toggleSelected(id) {
  if (state.selected.has(id)) state.selected.delete(id); else state.selected.add(id);
  drawRows();
  document.querySelector('[data-select-row="'+id+'"]')?.focus();
}
function drawRows() {
  const columns = shownColumns();
  const fields = columns.filter(c=>c!=='No.');
  const list = filteredRows();
  const deleted = state.page === 'deleted';
  const picking = state.selecting && !deleted;
  const available = new Set(state.rows.map(r=>r.id));
  for (const id of state.selected) if (!available.has(id)) state.selected.delete(id);
  $('matrix').classList.toggle('selection-mode',picking);
  $('matrix').classList.toggle('deleted-matrix',deleted);
  $('matrix').setAttribute('role',picking?'grid':'table');
  if (picking) $('matrix').setAttribute('aria-multiselectable','true'); else $('matrix').removeAttribute('aria-multiselectable');
  $('matrixHead').innerHTML = '<tr><th class="row-number-cell" scope="col">No.</th>'+fields.map(c=>'<th scope="col">'+esc(c)+'</th>').join('')+'<th class="action-cell" scope="col">'+(picking?'Selection':'Action')+'</th></tr>';
  $('rows').innerHTML = list.map((r,index) =>
    '<tr class="'+(state.selected.has(r.id)?'selected-row':'')+'" '+(picking?'data-select-row="'+r.id+'" tabindex="0" aria-selected="'+state.selected.has(r.id)+'"':'')+'>'+
    '<td class="row-number-cell"><span class="row-number '+(state.selected.has(r.id)?'picked':'')+'">'+esc(rowNumber(r,index))+'</span></td>'+
    fields.map(column => '<td'+(column===r.mappings.subject?' class="cell-subject"':column===r.mappings.reference?' class="ref"':'')+'>'+
      (column==='MOV 1'||column==='MOV 2'?movMarkup(r,column):column===r.mappings.status?pill(r.cells[column]||statusOf(r)):
       column===r.mappings.subject&&!deleted&&!picking?'<button class="subject-link" data-record="'+r.id+'">'+esc(r.cells[column]||'')+'</button>':esc(r.cells[column]||''))+'</td>').join('')+
    '<td class="action-cell">'+(deleted?'<div class="row-actions"><button class="btn edit-button" data-restore="'+r.id+'">Restore</button>'+(state.user.role==='admin'?'<button class="btn danger" data-purge-record="'+r.id+'" title="Delete permanently">Delete</button>':'')+'</div>':picking?'<span class="row-prompt">'+(state.selected.has(r.id)?'Selected':'Click row to select')+'</span>':
      '<div class="row-actions"><button class="btn view-button" data-record="'+r.id+'" aria-label="View '+esc(refOf(r))+'">View</button>'+(state.user.role!=='viewer'?'<button class="btn edit-button" data-edit-record="'+r.id+'" aria-label="Edit '+esc(refOf(r))+'">Edit</button>':'')+'</div>')+'</td></tr>').join('') ||
    '<tr><td colspan="'+(fields.length+2)+'"><div class="empty"><h2>No matching documents</h2><p>Try another search or clear the filters.</p></div></td></tr>';
  $('rowCount').textContent = list.length+' document'+(list.length===1?'':'s')+' · '+columns.length+' columns';
  if (deleted) { $('selectionBar').innerHTML=''; return; }
  const selected = selectedRows();
  $('selectionBar').innerHTML = (picking?'<div class="selection-instructions"><span>Click a row to add or remove a document. Press Enter or Space when a row is focused.</span>'+button('Add all shown','selectshown','link')+'</div>':'')+
    (selected.length?'<div class="print-tray"><div class="tray-summary"><strong>'+selected.length+' document'+(selected.length===1?'':'s')+' selected</strong><span>Each selected document prints as one row on a shared NCSC sheet.</span></div>'+
      '<div class="tray-documents">'+selected.slice(0,3).map(r=>'<span class="document-chip" title="'+esc(subjectOf(r))+'"><span>'+esc(refOf(r))+'</span><button type="button" data-remove-selected="'+r.id+'" aria-label="Remove '+esc(subjectOf(r))+' from selection">'+icon('close')+'</button></span>').join('')+(selected.length>3?'<small>+'+(selected.length-3)+' more</small>':'')+'</div>'+
      '<div class="tools">'+button('Print selected rows','printselected','primary','print')+button('Export selected','exportselected','','download')+(editor()?button('Delete selected','deleteselected','danger','trash'):'')+button('Clear selection','clearselection','link')+'</div></div>':
      '<p class="selection-hint">'+(picking?'Choose documents from the rows below. Your selection stays when you search or change filters.':'Use Select documents to prepare rows for printing, export'+(editor()?' or deletion.':'.'))+'</p>');
}
document.addEventListener('keydown', e => {
  const row=e.target.closest('[data-select-row]');
  if (state.selecting && row && e.target===row && ['Enter',' '].includes(e.key)) {e.preventDefault();toggleSelected(row.dataset.selectRow);}
});

function renderImports() {
  $('content').innerHTML = pageHeading('Imported files', 'Manage the worksheets and tables added to the register.',
    button('Import file', 'import', 'primary', 'upload')) + '<section class="card">' +
    (state.collections.length ? state.collections.map(c => '<div class="source-card"><div><strong>' + esc(c.name) +
      '</strong><p>' + c.count + ' records · ' + c.columns.length + ' columns · Imported ' + esc(formatDate(c.created)) +
      '</p></div><div class="tools"><button class="btn" data-source="' + c.id + '">View records</button><button class="btn" data-map="' +
      c.id + '">Worksheet settings</button></div></div>').join('') : emptyMarkup()) + '</section>';
}

/* File import uses a separate preview and confirmation stage. */
let importPreview = null;
let importSource = null;
function mappingUI(columns, mappings, prefix) {
  return '<div class="map">' + Object.entries(mappingLabels).map(([key, label]) =>
    '<label>' + label + '<select name="' + prefix + key + '">' +
    opts([['', 'Choose a column'], ...columns], mappings[key] || '') + '</select></label>').join('') + '</div>';
}
function readMapping(form, prefix) {
  return Object.fromEntries(Object.keys(mappingLabels).map(key => [key, form.elements[prefix + key]?.value || '']));
}
function importDialog() {
  importPreview = null;
  modal('Import a file', 'Add an existing matrix or incoming document to the register.',
    '<div class="steps"><span class="current">Choose file</span><span>Review content</span><span>Import</span></div>' +
    '<form id="uploadForm" class="stack"><div class="upload-zone">' + icon('upload') +
    '<strong>Choose the file you want to import</strong><p>Excel, CSV, PDF, Word, text, or a document attachment · Up to 25 MB</p>' +
    '<input name="file" type="file" aria-label="Choose file to import" required></div>' +
    '<details><summary>Header detection options</summary><div><label>Header row (optional)<input type="number" name="header" min="1" placeholder="Detect automatically"></label></div></details></form>',
    button('Cancel', 'close') + '<button class="btn primary" form="uploadForm">Preview file</button>');
  $('uploadForm').onsubmit = async e => {
    e.preventDefault();
    e.submitter.disabled = true;
    e.submitter.textContent = 'Reading file…';
    try {
      const fd = new FormData(e.target);
      importSource = fd.get('file');
      const filename = importSource.name;
      importPreview = await api('/api/preview', fd);
      importPreview.filename = filename;
      previewImport();
    } catch (err) {
      showError(err); e.submitter.disabled = false; e.submitter.textContent = 'Preview file';
    }
  };
}
function importTable(dataset) {
  const fields=dataset.columns.filter(c=>!isRowNumber(c));
  const numberIndex=dataset.columns.findIndex(isRowNumber);
  return '<div class="table-wrap"><table><thead><tr><th>No.</th>'+fields.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+
    dataset.rows.slice(0,10).map((row,index)=>'<tr><td>'+esc(numberIndex>=0 && row[numberIndex] ? row[numberIndex] : index+1)+'</td>'+
      fields.map(c=>'<td>'+esc(row[dataset.columns.indexOf(c)])+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
}
function previewImport() {
  const preview = importPreview;
  modal('Review imported content', preview.filename,
    '<div class="steps"><span class="done">File selected</span><span class="current">Review content</span><span>Import</span></div>' +
    preview.warnings.map(w => '<p class="notice">' + esc(w) + '</p>').join('') +
    '<form id="importReview" class="stack">' + preview.datasets.map((d, index) =>
      '<section class="section preview"><label class="check"><input type="checkbox" name="sheet' + index + '" checked>' +
      esc(d.name) + ' <span class="muted">· ' + d.rows.length + ' rows · ' + d.columns.length + ' columns</span></label>' +
      importTable(d) + '<small class="muted">Showing up to 10 preview rows. All ' + d.rows.length + ' rows will be imported.' +
      (d.header_row ? ' Header detected at row ' + d.header_row + '.' : '') + '</small>' +
      (d.header_row ? '<label>Header row for this worksheet<input type="number" min="1" name="header' + index + '" value="' + d.header_row + '"></label>' : '') +
      '<details' + (!d.mappings.subject ? ' open' : '') + '><summary>Check routing and print fields</summary><div>' +
      mappingUI(d.columns, d.mappings, 'map' + index + '_') +
      (!d.mappings.subject ? '<p class="notice" style="margin-top:12px">Choose a Subject column if the file contains one. Missing routing fields can be added later in Worksheet settings.</p>' : '') +
      '</div></details></section>').join('') + '</form>',
    button('Choose another file', 'import') + button('Re-read header rows', 'repreview') + '<button class="btn primary" id="importConfirm" data-action="confirmimport">Import selected content</button>');
}
async function confirmImport(buttonEl) {
  const form = $('importReview');
  const datasets = importPreview.datasets.map((d, index) => ({
    index, mappings: readMapping(form, 'map' + index + '_')
  })).filter(d => form.elements['sheet' + d.index].checked);
  if (!datasets.length) throw Error('Select at least one worksheet or table.');
  buttonEl.disabled = true;
  buttonEl.textContent = 'Importing…';
  try {
    const result = await api('/api/import', {token: importPreview.token, datasets});
    state.collection = result.collections[0];
    state.page = 'documents'; state.query = ''; state.status = '';
    $('dialog').close();
    await loadData(); render();
    toast('Import complete. Open a document to review or route it.');
  } catch (err) {
    buttonEl.disabled = false; buttonEl.textContent = 'Import selected content'; throw err;
  }
}
function mappingDialog(id) {
  const c = state.collections.find(item => item.id === id);
  modal('Worksheet settings', c.name,
    '<form id="mappingForm" class="stack"><h3 class="form-section-title">Routing and print fields</h3>' +
    mappingUI(c.columns, c.mappings, 'mapping_') +
    '<label class="check"><input name="standard" type="checkbox">Add any missing standard tracking columns</label>' +
    '<label>Additional column (optional)<input name="newColumn" placeholder="e.g. Deadline"></label>' +
    '<p class="notice">Equivalent tracking columns are merged into one field. After adding columns, reopen these settings to map them to routing fields.</p></form>',
    button('Cancel', 'close') + '<button form="mappingForm" class="btn primary">Save worksheet settings</button>');
  $('mappingForm').onsubmit = async e => {
    e.preventDefault();
    const form = e.target;
    try {
      await api('/api/columns', {id, add:[...(form.elements.standard.checked ? standard : []), form.elements.newColumn.value],
        mappings:readMapping(form, 'mapping_')});
      $('dialog').close(); await loadData(); render(); toast('Worksheet settings saved.');
    } catch (err) { showError(err); }
  };
}

function fileLink(file) {
  return '<a href="/api/file/'+file.id+'" data-file-id="'+file.id+'" data-file-name="'+esc(file.name)+'">'+esc(file.name)+'</a>';
}
function movMarkup(record,column,filesOnly=false) {
  const all = record.movs?.[column] || [];
  const entries = all.filter(entry => !filesOnly || entry.type === 'file');
  if (!entries.length) return filesOnly ? '' : '<span class="muted">—</span>';
  return '<div class="mov-items">' + entries.map(entry =>
    '<div class="mov-item">' + (entry.type === 'file' ? icon('file') : '') +
    (entry.url ? '<a href="'+esc(entry.url)+'" data-mov-record="'+record.id+'" data-mov-column="'+esc(column)+'" data-mov-index="'+all.indexOf(entry)+'">'+esc(entry.name)+'</a>' : '<span>'+esc(entry.name)+'</span>') +
    '</div>').join('') + '</div>';
}
function attachmentSummary(record) {
  const files = record.files.filter(file => file.kind !== 'MOV');
  if (!files.length) return '';
  return '<section class="section"><h3>Document attachments</h3>' + files.map(file =>
    '<div class="file-row">'+icon('file')+fileLink(file)+'<small>'+esc(file.kind)+'</small></div>').join('')+'</section>';
}
let evidenceReturn = false;
let evidenceUrl = null;
async function viewEvidence(entry) {
  evidenceReturn = Boolean($('dialog').open && ['View document','Edit document'].includes($('modalTitle')?.textContent));
  if ($('recordForm')) captureDraft();
  if (evidenceUrl) { URL.revokeObjectURL(evidenceUrl); evidenceUrl = null; }
  const back = button(evidenceReturn ? 'Back to document' : 'Close',evidenceReturn ? 'backrecord' : 'close');
  if (entry.type === 'link') {
    modal('View supporting link',entry.name,
      '<div class="evidence-link">'+icon('file')+'<h3>Supporting document at its source</h3><p>Open this link to view the document or use the source service’s download option.</p><p class="source-url">'+esc(entry.url)+'</p><p class="muted">External links need internet and permission from the source service.</p></div>',
      back+'<a class="btn primary" href="'+esc(entry.url)+'" target="_blank" rel="noopener">Open link to view or download</a>');
    return;
  }
  const id = entry.url.split('/').pop();
  const footer = back+'<a class="btn primary" href="/api/file/'+id+'">'+icon('download')+'Download original file</a>';
  modal('View supporting file',entry.name,'<div id="evidencePreview" class="evidence-loading">Preparing file preview…</div>',footer);
  const preview = $('evidencePreview');
  try {
    const response = await fetch('/api/file-preview/'+id);
    if (!response.ok) throw Error((await response.json()).error || 'Preview is unavailable for this file.');
    if (!preview.isConnected) return;
    const type = response.headers.get('Content-Type') || '';
    evidenceUrl = URL.createObjectURL(await response.blob());
    preview.className = 'evidence-preview';
    preview.innerHTML = type.startsWith('image/') ? '<img src="'+evidenceUrl+'" alt="Supporting image preview">' :
      '<iframe title="Supporting file preview" src="'+evidenceUrl+'" '+(type.includes('text/html')?'sandbox=""':'')+'></iframe>';
  } catch(error) {
    if (preview.isConnected) { preview.className='notice'; preview.textContent=error.message+' You can download the original file below.'; }
  }
}

function cellExport(record,column,index = 0) {
  if (column === 'No.') return rowNumber(record,index);
  if (['MOV 1','MOV 2'].includes(column)) return (record.movs?.[column] || []).map(entry=>entry.name).join('\n');
  return record.cells[column] || '';
}
/* Document details */
function safeLinks(text) {
  const urls = String(text || '').match(/https?:\/\/[^\s\]]+/g) || [];
  return urls.map(url => '<a href="' + esc(url) + '" target="_blank" rel="noopener">Open linked document</a>').join(' · ');
}
function fieldControl(column, value, index, record, writable) {
  const key = Object.keys(record.mappings).find(k => record.mappings[k] === column);
  const name = 'cell' + index;
  if (!writable) return '<textarea name="' + name + '" readonly>' + esc(value) + '</textarea>';
  if (column === 'Action Taken') {
    const choices = actions.map((a,i)=>(i+1)+' - '+a);
    const custom = Boolean(value && !choices.includes(value));
    const manual = custom && !actionTakenOptions.includes(value);
    return '<select name="'+name+'" aria-label="Action Taken" data-action-select="'+name+'">'+
      opts([['','Select an action'],...choices,['__custom__','Other / specify…']],custom?'__custom__':value)+'</select>'+
      '<div class="action-extra" data-action-extra="'+name+'" '+(!custom?'hidden':'')+'><span class="muted">Choose a progress action or enter your own.</span>'+
      '<select name="'+name+'Preset" aria-label="Other action taken" data-action-preset="'+name+'" '+(custom?'required':'')+'>'+opts([['','Select a progress action'],...actionTakenOptions,['__manual__','Enter custom text…']],manual?'__manual__':custom?value:'')+'</select>'+
      '<textarea name="'+name+'Custom" aria-label="Specify action taken" placeholder="Specify the action taken" '+(manual?'required':'hidden')+'>'+esc(manual?value:'')+'</textarea></div>';
  }
  if (['assigned', 'action', 'status'].includes(key)) {
    const choices = key === 'assigned' ? ['', 'ORD', 'AFS', 'OPS', 'AFS / OPS'] :
      key === 'action' ? ['', ...actions.map((a, i) => (i + 1) + ' - ' + a)] :
        ['', 'For Routing', 'Routed', 'Received', 'Ongoing', 'Completed'];
    if (value && !choices.includes(value)) choices.push(value);
    return '<select name="' + name + '" data-custom-select="' + name + '">' +
      opts([...choices.map(v => [v, v || 'Select an option']), ['__custom__', 'Other / specify…']], value || '') +
      '</select><input name="' + name + 'Custom" hidden placeholder="Enter the requested value">';
  }
  if ((key === 'hard' || /date|deadline/i.test(column)) && (!value || /^\d{4}-\d{2}-\d{2}$/.test(value))) {
    return '<input type="date" name="' + name + '" value="' + esc(value) + '">';
  }
  return '<textarea name="' + name + '">' + esc(value) + '</textarea>';
}
function formCell(form, index) {
  const name = 'cell'+index;
  const input = form.elements[name];
  if (input.value !== '__custom__') return input.value;
  const preset = form.elements[name+'Preset'];
  if (preset && preset.value !== '__manual__') return preset.value;
  return form.elements[name+'Custom'].value;
}
document.addEventListener('change', e => {
  const form = e.target.form;
  if (e.target.dataset.actionSelect || e.target.dataset.actionPreset) {
    const name = e.target.dataset.actionSelect || e.target.dataset.actionPreset;
    const active = form.elements[name].value === '__custom__';
    form.querySelector('[data-action-extra="'+name+'"]').hidden = !active;
    const preset = form.elements[name+'Preset'];
    preset.required = active;
    const manual = active && preset.value === '__manual__';
    form.elements[name+'Custom'].hidden = !manual;
    form.elements[name+'Custom'].required = manual;
    return;
  }
  if (!e.target.dataset.customSelect) return;
  const custom = form.elements[e.target.name + 'Custom'];
  custom.hidden = e.target.value !== '__custom__';
  custom.required = !custom.hidden;
});

async function openRecord(id, tab = 'details', editing = false) {
  state.editing = editing;
  state.record = await api('/api/record/' + id);
  state.draft = {...state.record.cells};
  state.dirty = false;
  renderRecord(tab);
}
function renderRecord(tab = 'details') {
  const r = state.record;
  const deleted = Boolean(r.deleted_at);
  const writable = new Set(deleted || !state.editing ? [] : r.editable_columns.filter(c=>!isRowNumber(c)));
  const tabs = [['details','Details & routing'], ['files','Files & MOVs'], ['history','Activity history']];
  const banner = '<div class="doc-banner"><span class="doc-symbol">' + icon('file') + '</span><div><strong>' +
    esc(subjectOf(r)) + '</strong><p>' + esc(refOf(r)) + ' · ' + esc(r.collection_name) + '</p></div>' + pill(statusOf(r)) + '</div>';
  const referenceNote = '<div class="reference-band"><span>Reference no.</span><strong>' + esc(refOf(r)) +
    '</strong><small>Automatically generated for new records. Existing imported references are retained.</small></div>';
  const fields = '<form id="recordForm" class="grid document-fields">' + referenceNote + [...r.columns.filter(isRowNumber),...r.columns.filter(c=>!isRowNumber(c))].map(column => {
    const index=r.columns.indexOf(column);
    if (column === r.mappings.reference) return '';
    const value = isRowNumber(column) ? rowNumber(r) : state.draft?.[column] || '';
    const evidence = ['MOV 1','MOV 2'].includes(column);
    if (!state.editing || !writable.has(column)) {
      return '<div class="display-field"><span class="field-label">' + esc(isRowNumber(column)?'No.':column) + '</span><div class="display-value">' +
        (evidence ? movMarkup(r,column) : esc(value || '—')) + '</div></div>';
    }
    return '<label>' + esc(column) +
      fieldControl(column,value,index,r,true) +
      (evidence ? '<small>Enter a link or note here. Use Files & MOVs to upload supporting files.</small>' + movMarkup(r,column,true) : '') +
      '</label>';
  }).join('') + '</form>';
  const files = '<section><div class="files">' +
    (r.files.length ? r.files.map(f => '<div class="file-row">' + icon('file') + fileLink(f) + '<small>' + esc(f.kind === 'MOV' ? 'MOV ' + f.slot : f.kind) + '</small></div>').join('') : '<p class="muted">No attachments yet.</p>') + '</div></section>' +
    (!deleted && r.editable_columns.length ? '<section class="section"><h3>Add a document or MOV</h3><form id="attachForm" class="grid">' +
      '<label>File<input name="file" type="file" required></label><label>Attachment type<select name="kind"><option>MOV</option><option>Document</option></select></label><label>MOV column<select name="slot"><option value="1">MOV 1</option><option value="2">MOV 2</option></select></label>' +
      '<div class="full"><button class="btn primary">Upload attachment</button></div></form></section>' : '');
  const history = '<ol class="timeline">' + r.events.slice().reverse().map(e =>
    '<li><strong>' + esc(e.message) + '</strong><small>' + esc(e.actor) + ' · ' + esc(formatDate(e.at)) + '</small></li>').join('') + '</ol>';
  modal(state.editing ? 'Edit document' : 'View document', refOf(r),
    banner + (deleted ? '<p class="notice">This document is in Deleted documents. Restore it to make changes.</p>' : '') +
    '<div class="doc-tabs" role="tablist">' + tabs.map(([key, label]) =>
      '<button type="button" role="tab" aria-selected="' + (tab === key) + '" class="doc-tab ' + (tab === key ? 'active' : '') +
      '" data-tab="' + key + '">' + label + (key === 'files' ? ' (' + r.files.length + ')' : '') + '</button>').join('') + '</div>' +
    (tab === 'details' ? fields + sourceRecordInfo(r) + attachmentSummary(r) : tab === 'files' ? files : history),
    (editor() && !deleted && state.editing ? button('Delete', 'delete', 'danger', 'trash') : '') +
    (!editor() && !deleted && statusOf(r) === 'Routed' && r.mappings.status ?
      button('Acknowledge receipt', 'acknowledge', 'primary', 'check') : '') +
    button('Print slip', 'printslip', '', 'print') +
    '<a class="btn" href="/api/docx/' + r.id + '">' + icon('download') + 'Word template</a>' +
    (!state.editing && !deleted && r.editable_columns.length ?
      button('Edit document', 'editrecord', 'primary', 'edit') : '') +
    (writable.size && tab === 'details' ? button('Cancel editing', 'canceledit') + '<button class="btn primary" form="recordForm">Save changes</button>' : button('Close', 'close')));
  if ($('recordForm')) $('recordForm').onsubmit = async e => {
    e.preventDefault();
    if (!state.editing || !e.submitter) return;
    e.submitter.disabled = true;
    try {
      const cells = {...r.cells, ...Object.fromEntries(r.columns.filter(column => column !== r.mappings.reference && writable.has(column)).map(column => [column, formCell(e.target,r.columns.indexOf(column))]))};
      await api('/api/save', {id:r.id, version:r.version, cells});
      await loadData(); render(); await openRecord(r.id);
      toast('Document updated.');
    } catch (err) { showError(err); e.submitter.disabled = false; }
  };
  if ($('attachForm')) $('attachForm').onsubmit = async e => {
    e.preventDefault(); e.submitter.disabled = true;
    try {
      if (state.dirty) throw Error('Save your document changes before uploading a file.');
      const fd = new FormData(e.target); fd.append('record', r.id); fd.append('version',r.version);
      await api('/api/attach', fd); await loadData(); render(); await openRecord(r.id, 'files'); toast('Attachment uploaded.');
    } catch (err) { showError(err); e.submitter.disabled = false; }
  };
}
/* Optional local source import, reviewed before registration. */
function newDocument() {
  state.dirty = false;
  const collection = state.collections.find(c => c.id === state.collection);
  const mappings = collection?.mappings || {hard:'Hard Copy Routed', reference:'Ref. No.', subject:'Subject', assigned:'Assigned to', action:'Requested Actions', status:'Status'};
  if (!mappings.subject) { toast('Map the Subject column in Worksheet settings before adding a document.'); return; }
  state.newDraft = {collection, mappings, baseColumns:[...(collection?.columns || standard)], columns:[...(collection?.columns || standard)], cells:{[mappings.status]:'For Routing'}, source:null, sourceRow:0, auto:{}};
  renderNewDocument();
}
function captureNewDocument() {
  const draft=state.newDraft, form=$('newForm');
  if (!draft || !form) return;
  draft.columns.forEach((column,index)=>{ if (form.elements['cell'+index]) draft.cells[column]=formCell(form,index); });
}
function sourceDetails(info) {
  return '<div class="source-meta">'+[['From',info.sender],['To',info.to],['Sent',info.sent],['Original reference',info.source_reference]].filter(([,v])=>v).map(([k,v])=>'<div><span>'+k+'</span><strong>'+esc(v)+'</strong></div>').join('')+'</div>'+
    (info.body?'<details class="source-message"><summary>'+ (info.type==='Email'?'Read email message':'Read extracted text')+'</summary><pre>'+esc(info.body)+'</pre></details>':'');
}
function sourceRecordInfo(record) {
  if (!record.source) return '';
  const source=record.source;
  return '<section class="section source-record"><h3>'+icon(source.type==='Email'?'file':'upload')+'Source '+(source.type==='Email'?'email':'file')+'</h3><p class="source-filename">'+esc(source.filename)+
    (source.sheet && source.sheet!==source.filename?' · '+esc(source.sheet):'')+(source.row?' · Row '+esc(source.row):'')+'</p>'+sourceDetails(source)+'</section>';
}
function renderNewDocument() {
  const draft=state.newDraft;
  const {collection,columns,mappings}=draft;
  const record={columns,mappings};
  const excluded=new Set([mappings.reference,'Action Taken','MOV 1','MOV 2',...columns.filter(isRowNumber)]);
  const fields=columns.filter(c=>!excluded.has(c));
  const ordered=[mappings.subject,mappings.hard,mappings.status,mappings.assigned,mappings.action,...fields.filter(c=>![mappings.subject,mappings.hard,mappings.status,mappings.assigned,mappings.action].includes(c))].filter(c=>fields.includes(c));
  const source=draft.source;
  const importPanel='<section class="source-intake"><div class="source-intake-head"><span class="source-intake-icon">'+icon('upload')+'</span><div><h3>'+ (source?'Source file ready for review':'Start from an email or file')+'</h3><p>'+ (source?esc(source.info.filename):'Optional: import a saved email, PDF, Word document, Excel, or another file to fill available details.')+'</p></div>'+button(source?'Replace file':'Import email or file','sourcefile',source?'':'primary','upload')+'</div>'+
    '<input id="newSourceFile" type="file" aria-label="Import email or document source" hidden>'+
    (source?'<div class="source-intake-body">'+source.warnings.map(w=>'<p class="notice">'+esc(w)+'</p>').join('')+
      (source.candidates.length>1?'<label>Source row to register<select id="sourceRow">'+opts(source.candidates.map((c,i)=>[String(i),c.label]),String(draft.sourceRow))+'</select></label>':'')+
      sourceDetails(source.info)+
      (source.info.attachments.length?'<div class="source-attachments"><span class="field-label">Email attachments ('+source.info.attachments.length+')</span>'+source.info.attachments.map((a,i)=>'<a href="/api/draft-file/'+source.token+'?attachment='+i+'">'+icon('file')+esc(a.name)+'</a>').join('')+'</div>':'')+
      '<div class="tools"><a class="btn" href="/api/draft-file/'+source.token+'">'+icon('download')+'Download original</a>'+button('Remove source','removesource','link')+'</div>'+ 
      '<p class="source-review-note">Review the subject and routing below. The original source and extracted attachments will be saved with this document.</p></div>':'')+'</section>';
  modal('New document',collection?collection.name:'Register correspondence for routing',importPanel+
    '<form id="newForm" class="grid document-fields new-document-form"><div class="reference-band"><span>Reference no.</span><strong>Generated automatically on save</strong><small>Action Taken and supporting MOVs can be added after registration.</small></div>'+
    ordered.map(c=>'<label '+(c===mappings.subject?'class="full"':'')+'>'+esc(c)+fieldControl(c,draft.cells[c]||'',columns.indexOf(c),record,true)+'</label>').join('')+'</form>',
    button('Cancel','close')+'<button form="newForm" class="btn primary">Register document</button>');
  $('newForm').elements['cell'+columns.indexOf(mappings.subject)].required=true;
  $('newSourceFile').onchange=async e=>{
    const file=e.target.files[0];if (!file) return;
    captureNewDocument();
    const control=$('dialog').querySelector('[data-action=sourcefile]');control.disabled=true;control.textContent='Reading file…';
    $('dialog').querySelector('[form=newForm]').disabled=true;
    try {
      if (file.size>25*1024*1024) throw Error('Choose a file up to 25 MB.');
      const data=new FormData();data.append('file',file);
      const result=await api('/api/document-draft',data);
      if (state.newDraft !== draft || !$('newForm')) return;
      draft.source=result;draft.sourceRow=0;applySourceRow(0);state.dirty=true;
      renderNewDocument();toast('Available details filled. Review them before registering.');
    } catch(error) {showError(error);control.disabled=false;control.textContent=source?'Replace file':'Import email or file';$('dialog').querySelector('[form=newForm]').disabled=false;e.target.value='';}
  };
  if ($('sourceRow')) $('sourceRow').onchange=e=>{captureNewDocument();applySourceRow(Number(e.target.value));state.dirty=true;renderNewDocument();};
  $('newForm').onsubmit=async e=>{
    e.preventDefault();e.submitter.disabled=true;
    try {
      captureNewDocument();
      const result=await api('/api/new',{collection:collection?.id,cells:draft.cells,source_token:draft.source?.token,source_row:draft.sourceRow});
      state.dirty=false;state.newDraft=null;state.page='documents';state.collection=result.collection;
      await loadData();render();await openRecord(result.id);toast('Document registered.');
    } catch(error) {showError(error);e.submitter.disabled=false;}
  };
}
function applySourceRow(index) {
  const draft=state.newDraft;
  const candidate=draft.source.candidates[index];
  const next={...candidate.cells};
  for (const column of ['Ref. No.','Action Taken','MOV 1','MOV 2']) delete next[column];
  for (const column of Object.keys(draft.auto)) {
    if (!(column in next) && draft.cells[column]===draft.auto[column]) delete draft.cells[column];
  }
  for (const [column,value] of Object.entries(next)) {
    if (!draft.cells[column] || draft.cells[column]===draft.auto[column]) draft.cells[column]=value;
  }
  draft.auto=next;draft.sourceRow=index;
  draft.columns=[...new Set([...draft.baseColumns,...Object.keys(next).filter(c=>!standard.includes(c) && !isRowNumber(c))])];
}

function deleteDocument() {
  const r = state.record;
  modal('Move document to Deleted?', refOf(r), '<p class="help"><strong>' + esc(subjectOf(r)) +
    '</strong></p><p class="notice">You can restore this document later. Its attachments and activity history will be kept.</p>',
    button('Cancel', 'backrecord') + button('Move to Deleted', 'confirmdelete', 'danger', 'trash'));
}
async function restoreDocument(id) {
  const r = state.deleted.find(item => item.id === id);
  await api('/api/restore', {id:r.id, version:r.version});
  await loadData(); render(); toast('Document restored to the register.');
}
function deleteSelectedDocuments() {
  const records = selectedRows();
  if (!records.length) { toast('Select documents to delete.'); return; }
  modal('Move selected documents to Deleted?', records.length + ' document(s) selected',
    '<ul class="confirmation-list">' + records.slice(0, 5).map(r=>'<li><strong>'+esc(refOf(r))+'</strong><span>'+esc(subjectOf(r))+'</span></li>').join('') +
    (records.length > 5 ? '<li>And '+(records.length-5)+' more selected documents</li>' : '') + '</ul>' +
    '<p class="notice">All selected documents will leave the active register. Their files and history stay available in Deleted documents, where you can restore them.</p>',
    button('Cancel', 'close') + button('Move '+records.length+' to Deleted', 'confirmbatchdelete', 'danger', 'trash'), 'compact');
  // Freeze the reviewable selection and versions while this confirmation is open.
  $('dialog').dataset.batch = JSON.stringify(records.map(r=>({id:r.id,version:r.version})));
}
function purgeDocument(id) {
  const r = state.deleted.find(item=>item.id===id);
  if (!r) throw Error('Refresh Deleted documents and try again.');
  modal('Delete document permanently?', refOf(r),
    '<p class="help"><strong>'+esc(subjectOf(r))+'</strong></p>' +
    '<p class="error">This removes the document, its own attachments and its activity history. It cannot be restored. Shared source workbooks remain while other documents use them. A minimal administrator deletion log is retained.</p>' +
    '<form id="purgeForm" class="stack"><label>Type '+esc(refOf(r))+' to confirm<input name="confirmation" required autocomplete="off" spellcheck="false" placeholder="Reference number"></label></form>',
    button('Cancel', 'close') + '<button form="purgeForm" class="btn danger">Delete permanently</button>', 'compact');
  $('purgeForm').onsubmit = async e => {
    e.preventDefault(); e.submitter.disabled = true;
    try {
      const result = await api('/api/purge', {id:r.id,version:r.version,confirmation:e.target.elements.confirmation.value});
      $('dialog').close(); await loadData(); render();
      toast(result.cleanup_pending ? 'Document deleted. Some file cleanup is pending; restart the host to retry.' : 'Document permanently deleted.');
    } catch(err) { showError(err); e.submitter.disabled = false; }
  };
}

function captureDraft() {
  const form = $('recordForm');
  if (!form || !state.record) return;
  state.draft = {...state.record.cells};
  for (let index=0; index<state.record.columns.length; index++) {
    if (form.elements['cell'+index]) state.draft[state.record.columns[index]] = formCell(form,index);
  }
  state.dirty = state.record.columns.some(column => state.draft[column] !== (state.record.cells[column] || ''));
}
document.addEventListener('input', e => {
  if (e.target.closest('#newForm')) {captureNewDocument();state.dirty=true;}
  if (e.target.closest('#recordForm')) captureDraft();
});
document.addEventListener('change', e => {
  if (e.target.closest('#newForm')) {captureNewDocument();state.dirty=true;}
  if (e.target.closest('#recordForm')) captureDraft();
});
$('dialog').addEventListener('cancel', e => {
  if (state.dirty && !window.confirm('Discard unsaved changes to this document?')) e.preventDefault();
  else state.dirty = false;
});

/* Print output */
function printHTML(content, landscape = false) {
  $('print').innerHTML = content;
  let style = $('pageStyle');
  if (!style) { style = document.createElement('style'); style.id = 'pageStyle'; document.head.append(style); }
  style.textContent = '@page{size:A4 ' + (landscape ? 'landscape' : 'portrait') + ';margin:12mm}';
  window.print();
}
const agency = () => '<div class="agency"><img src="/assets/logo.jpg" alt="">National Commission of Senior Citizens · Regional Office I</div>';
function printSlips(ids,mode = 'combined') {
  if (!ids.length) { toast('Select documents to print.'); return; }
  if (ids.length > 100) { toast('Print up to 100 routing slips in one batch.'); return; }
  window.open('/printing?ids='+encodeURIComponent(ids.join(','))+'&mode='+mode, '_blank', 'noopener');
}
function printSlip() { printSlips([state.record.id],'individual'); }
function printMatrix(rows = filteredRows()) {
  if (!rows.length) { toast('There are no documents to print.'); return; }
  // A normal form opens a print tab synchronously, without encoding full records
  // in the URL. The server rechecks access and reads authoritative saved values.
  const form = document.createElement('form');
  form.method = 'POST'; form.action = '/matrix-print'; form.target = '_blank'; form.rel = 'noopener'; form.hidden = true;
  const columns = shownColumns().filter(column=>column==='No.' || rows.some(r=>r.columns.includes(column)));
  for (const [name,value] of Object.entries({ids:JSON.stringify(rows.map(r=>r.id)),columns:JSON.stringify(columns),csrf:state.csrf})) {
    const input = document.createElement('input'); input.type='hidden'; input.name=name; input.value=value; form.append(input);
  }
  document.body.append(form); form.submit(); form.remove();
}
function exportDialog(selectedOnly = false) {
  const selected = selectedRows();
  const visible = filteredRows();
  if (!visible.length && !selected.length) { toast('There are no documents to export.'); return; }
  const scopes = [...(selected.length ? [['selected','Selected documents ('+selected.length+')']] : []),...(visible.length?[['filtered','Current filtered documents ('+visible.length+')']]:[])];
  modal('Export documents', 'Download an NCSC-branded tracking report.',
    '<form id="exportForm" class="stack"><label>Documents'+
    '<select name="scope">'+opts(scopes,(selectedOnly || !visible.length) && selected.length?'selected':'filtered')+'</select></label>'+
    '<label>File format<select name="format"><option value="xlsx">Excel workbook (.xlsx)</option><option value="pdf">PDF document (.pdf)</option><option value="docx">Word document (.docx)</option></select></label>'+
    '<label id="exportPaper" hidden>Page layout<select name="paper"><option value="compact">Fit short lists to content</option><option value="a4">A4 landscape</option></select></label>'+
    '<p class="notice">NCSC seal and header included. Additional fields stay in the report.</p>'+
    '<p class="muted">PDF export uses Microsoft Word or LibreOffice installed on the host.</p></form>',
    button('Cancel','close')+'<button class="btn primary" form="exportForm">Download export</button>','compact');
  $('exportForm').elements.format.onchange = e => { $('exportPaper').hidden = e.target.value === 'xlsx'; };
  $('exportForm').onsubmit = async e => {
    e.preventDefault(); const submit=e.submitter; submit.disabled=true; submit.textContent='Preparing export…';
    try {
      const rows = e.target.elements.scope.value==='selected'?selected:visible;
      const format = e.target.elements.format.value;
      const response = await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({ids:rows.map(r=>r.id),format,paper:e.target.elements.paper.value})});
      if (!response.ok) throw Error((await response.json()).error || 'Export failed.');
      const disposition = response.headers.get('Content-Disposition') || '';
      const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
      const name = match?decodeURIComponent(match[1]):'NCSC-Tracking-Matrix.'+format;
      const url=URL.createObjectURL(await response.blob());
      const link=document.createElement('a');link.href=url;link.download=name;link.click();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
      $('dialog').close();toast('NCSC report exported.');
    } catch(error) { showError(error); submit.disabled=false; submit.textContent='Download export'; }
  };
}


/* Department administration */
let accounts = [];
let accountScope = 'current';
async function renderAccounts() {
  accounts = await api('/api/users');
  const archived = accountScope === 'archived';
  const visible = accounts.filter(account=>Boolean(account.archived_at)===archived);
  const currentCount = accounts.filter(account=>!account.archived_at).length;
  $('content').innerHTML = pageHeading('Account management', 'Manage individual staff accounts, department membership, and access.',
    button('Add staff account', 'addaccount', 'primary', 'plus')) +
    '<section class="card"><div class="card-head"><div><h2>Office accounts</h2><small>Archive staff accounts to remove access while preserving document history.</small></div></div>' +
    '<div class="account-scopes" role="group" aria-label="Account list"><button type="button" data-account-scope="current" aria-pressed="'+!archived+'">Current accounts <span>'+currentCount+'</span></button>' +
    '<button type="button" data-account-scope="archived" aria-pressed="'+archived+'">Archived accounts <span>'+(accounts.length-currentCount)+'</span></button></div>' +
    '<div class="table-wrap"><table class="accounts-table"><thead><tr><th>Username</th><th>Name / department</th><th>Access / status</th><th>Actions</th></tr></thead><tbody>' +
    (visible.map(u => '<tr><td><strong class="ref">' + esc(u.username) + '</strong>'+(u.id===state.user.id?'<small class="account-you">Your account</small>':'')+'</td><td>' + esc(u.name) + '<small class="account-detail">' + esc(u.department) + ' · ' + esc(u.account_type) + '</small></td><td>' +
      esc(u.role === 'admin' ? 'ORD administration' : u.role === 'staff' ? 'Assigned documents' : u.role === 'records' ? 'Records administration' : 'Read only') +
      '<small class="account-detail">' + (archived ? 'Archived · '+esc(formatDate(u.archived_at)) : u.active ? 'Active' : 'Disabled') + '</small></td><td><div class="account-actions">'+
      (archived ? '<button class="btn view-button" data-restore-account="'+u.id+'">Restore account</button>' :
      '<button class="btn view-button" data-edit-account="' + u.id + '">Edit</button><button class="btn" data-recovery="' + u.id + '">Recovery code</button>'+
      (u.id!==state.user.id?'<button class="btn danger" data-archive-account="'+u.id+'">Archive</button>':''))+'</div></td></tr>').join('') ||
      '<tr><td colspan="4"><div class="empty"><h2>No archived accounts</h2><p>Accounts archived by an administrator will appear here.</p></div></td></tr>') +
    '</tbody></table></div></section><p class="account-note">Archived accounts cannot sign in. Their past activity and assignments remain identifiable. Restored accounts stay disabled until an administrator enables them. Keep at least one active administrator.</p>';
}
function archiveAccount(id) {
  const account = accounts.find(u=>u.id===Number(id));
  modal('Archive staff account?', account.username,
    '<p class="help"><strong>'+esc(account.name)+'</strong> · '+esc(account.department)+'</p>' +
    '<p class="notice">This account will lose access and its active sessions will end. Its document activity and assignments will remain identifiable. You can restore the account from Archived accounts later.</p>' +
    '<form id="archiveAccountForm"></form>',button('Cancel','close')+'<button form="archiveAccountForm" class="btn danger">Archive account</button>','compact');
  $('archiveAccountForm').onsubmit = async e=> {
    e.preventDefault();e.submitter.disabled=true;
    try {
      await api('/api/account-archive',{id:account.id});
      $('dialog').close();await renderAccounts();toast('Account archived. Access has been removed.');
    } catch(err) {showError(err);e.submitter.disabled=false;}
  };
}
async function restoreAccount(id) {
  await api('/api/account-restore',{id:Number(id)});
  accountScope='current';await renderAccounts();toast('Account restored as disabled. Choose Edit to review and enable access.');
}
function addAccount() {
  modal('Add staff account', 'Create a personal login and assign its department and access.',
    '<form id="accountForm" class="grid"><label>Username<input name="username" required placeholder="e.g. maria.santos"></label>' +
    '<label>Staff full name<input name="name" required placeholder="Full name"></label>' +
    '<label>Department code<input name="department" required list="departmentCodes" placeholder="ORD, AFS, OPS"><datalist id="departmentCodes"><option>ORD</option><option>AFS</option><option>OPS</option></datalist></label>' +
    '<label>Access<select name="role">' + opts([['staff','Department staff'], ['records','Records officer'], ['viewer','Office reviewer (read all)'], ['admin','Administrator']]) + '</select></label>' +
    '<div class="full">' + passwordInput('password', 'Initial password', 'new-password') + '</div></form>',
    button('Cancel', 'close') + '<button form="accountForm" class="btn primary">Create staff account</button>');
  $('accountForm').onsubmit = async e => {
    e.preventDefault();
    try {
      const body = Object.fromEntries(new FormData(e.target));
      const result = await api('/api/users', body);
      await renderAccounts(); recoveryCodes({[body.username.toUpperCase()]:result.recovery_code});
    } catch (err) { showError(err); }
  };
}
function editAccount(id) {
  const account = accounts.find(u => u.id === Number(id));
  modal('Edit staff account', account.username,
    '<form id="editAccountForm" class="grid"><label>Username<input name="username" required value="' + esc(account.username) +
    '"></label><label>Full name<input name="name" required value="' + esc(account.name) +
    '"></label><label>Department code<input name="department" required value="' + esc(account.department) +
    '"></label><label>Access<select name="role">' +
    opts([['admin','ORD administration'], ['records','Records administration'], ['staff','Assigned documents'], ['viewer','Read only']], account.role) +
    '</select></label><label>Account status<select name="active">' +
    opts([['1','Active'], ['0','Disabled']], account.active ? '1' : '0') +
    '</select></label><label>Account type<select name="account_type">' +
    opts([['individual','Individual staff'], ['department','Shared department (legacy)']], account.account_type) +
    '</select></label></form>', button('Cancel', 'close') + '<button form="editAccountForm" class="btn primary">Save account</button>');
  $('editAccountForm').onsubmit = async e => {
    e.preventDefault();
    try {
      await api('/api/account-update', {id:account.id, ...Object.fromEntries(new FormData(e.target)), active:e.target.elements.active.value === '1'});
      $('dialog').close(); await start(); toast('Staff account updated.');
    } catch (err) { showError(err); }
  };
}
function requestRecovery(id) {
  const account = accounts.find(u => u.id === Number(id));
  modal('Replace recovery code?', account.username,
    '<p class="notice">A new code will replace the current recovery code for ' + esc(account.username) +
    '. Save the new code and give it directly to the account owner.</p>',
    button('Cancel', 'close') + '<button class="btn primary" data-confirm-recovery="' + id + '">Generate new code</button>');
}
function changePassword() {
  modal('Change your password', state.user.username,
    '<form id="passwordForm" class="stack">' + passwordInput('current', 'Current password') +
    passwordInput('password', 'New password', 'new-password') + '</form>',
    button('Cancel', 'close') + '<button form="passwordForm" class="btn primary">Save password</button>');
  $('passwordForm').onsubmit = async e => {
    e.preventDefault();
    try {
      await api('/api/password', Object.fromEntries(new FormData(e.target)));
      $('dialog').close(); toast('Password updated.');
    } catch (err) { showError(err); }
  };
}
function guide() {
  modal('Quick guide', 'The daily document workflow',
    '<div class="help"><ol><li><strong>ORD logs in and imports a file.</strong> Choose the existing Excel matrix or incoming document. Check the preview and confirm the import.</li>' +
    '<li><strong>Start from an email or file.</strong> New document &gt; Import email or file fills available details from a saved EML/MSG, PDF, Word document, Excel/CSV or another source. Review the subject and routing before registering. Emails retain their message and attachments; Excel/CSV lets you choose one source row.</li>' +
    '<li><strong>Review and route.</strong> In Document register, choose View to read a record or Edit to update it. Check its subject and reference number, choose the responsible department and requested action, then save.</li>' +
    '<li><strong>The department acts.</strong> Each staff member logs in with their own username, opens Assigned documents, records its Action Taken using NCSC actions 1–9 or Other / specify, and adds MOV files or links.</li>' +
    '<li><strong>Settings.</strong> Expand Settings in the sidebar for account management, change password, Quick guide, and Deleted documents. Account management is available to administrators.</li>' +
    '<li><strong>Update and print.</strong> Save the status. Print slip automatically opens the browser print dialog using the supplied Word template. Use Select documents and click rows to print different documents on a shared NCSC routing sheet. The host needs Microsoft Word or LibreOffice.</li>' +
    '<li><strong>Delete and restore.</strong> Records officers can move individual or selected documents to Deleted documents. Restore returns them with their files and history. Only administrators can delete a document permanently; type its reference number to confirm.</li>' +
    '<li><strong>Retire staff access.</strong> Administrators can Archive an account in Account management. The account loses access while its past activity remains identifiable. Restore from Archived accounts, then Edit to enable it.</li>' +
    '<li><strong>Print a readable matrix.</strong> Print matrix opens the print dialog in A4 landscape. Routing and follow-up fields use separate sections with the same reference numbers. Extra imported columns continue in further sections. Table entries consistently use Arial 10 pt.</li></ol>' +
    '<p class="notice">Readable PDFs can produce tables or page text. Scanned pages require manual encoding. Review the preview for every new file layout.</p>' +
    '<p style="margin-top:15px">Tracking columns stay in the same order for every worksheet. Additional imported fields follow them. New reference numbers are automatic. Files &amp; MOVs lets you choose MOV 1 or MOV 2 for each upload.</p></div>',
    button('Got it', 'close', 'primary'));
}
function downloadText(name, text) {
  const url = URL.createObjectURL(new Blob([text], {type:'text/plain;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/* Interaction dispatch */
document.addEventListener('click', async e => {
  const row=e.target.closest('[data-select-row]');
  if (state.selecting && row && !e.target.closest('a,button,input,select,textarea')) {toggleSelected(row.dataset.selectRow);return;}
  const attachment = e.target.closest('a[data-file-id],a[data-mov-record]');
  if (attachment) {
    e.preventDefault();
    try {
      if (attachment.dataset.fileId) await viewEvidence({name:attachment.dataset.fileName,url:attachment.href,type:'file'});
      else {
        const record = state.rows.find(r=>r.id===attachment.dataset.movRecord) || state.record;
        const entry = record.movs[attachment.dataset.movColumn][Number(attachment.dataset.movIndex)];
        await viewEvidence(entry);
      }
    } catch(error) { toast(error.message); }
    return;
  }
  const target = e.target.closest('button');
  if (!target) return;
  try {
    if (target.dataset.removeSelected) {state.selected.delete(target.dataset.removeSelected);drawRows();return;}
    if (target.dataset.reveal) {
      const input = target.closest('form').elements[target.dataset.reveal];
      input.type = input.type === 'password' ? 'text' : 'password';
      target.setAttribute('aria-label', (input.type === 'password' ? 'Show' : 'Hide') + ' password');
      return;
    }
    if (target.dataset.page) {
      state.page = target.dataset.page; if (['accounts','deleted'].includes(state.page)) state.settingsOpen=true; state.query = ''; state.status = ''; state.collection = '';
      render(); return;
    }
    if (target.hasAttribute('data-status')) {
      state.status = target.dataset.status; state.page = 'documents'; state.collection = ''; render(); return;
    }
    if (target.dataset.record) return await openRecord(target.dataset.record);
    if (target.dataset.editRecord) return await openRecord(target.dataset.editRecord, 'details', true);
    if (target.dataset.restore) return await restoreDocument(target.dataset.restore);
    if (target.dataset.purgeRecord) return purgeDocument(target.dataset.purgeRecord);
    if (target.dataset.tab) {
      if ($('recordForm')) captureDraft();
      return renderRecord(target.dataset.tab);
    }
    if (target.dataset.source) {
      state.collection = target.dataset.source; state.page = 'documents'; state.query = ''; state.status = ''; render(); return;
    }
    if (target.dataset.map) return mappingDialog(target.dataset.map);
    if (target.dataset.editAccount) return editAccount(target.dataset.editAccount);
    if (target.dataset.accountScope) {accountScope=target.dataset.accountScope;return await renderAccounts();}
    if (target.dataset.archiveAccount) return archiveAccount(target.dataset.archiveAccount);
    if (target.dataset.restoreAccount) return await restoreAccount(target.dataset.restoreAccount);
    if (target.dataset.recovery) return requestRecovery(target.dataset.recovery);
    if (target.dataset.confirmRecovery) {
      const account = accounts.find(u => u.id === Number(target.dataset.confirmRecovery));
      const result = await api('/api/account-recovery', {id:account.id});
      return recoveryCodes({[account.username]:result.recovery_code});
    }
    switch (target.dataset.action) {
      case 'settings':
        state.settingsOpen = !state.settingsOpen;
        $('settingsMenu').hidden = !state.settingsOpen;
        target.setAttribute('aria-expanded',state.settingsOpen);
        break;
      case 'close':
        if (!state.dirty || window.confirm('Discard unsaved changes to this document?')) {
          state.dirty = false; $('dialog').close();
        }
        break;
      case 'logout':
        await api('/api/logout', {}); state.selected.clear(); state.selecting=false; state.collection = ''; state.page = 'dashboard'; state.settingsOpen = false;
        $('dialog').close(); await start(); break;
      case 'forgot': forgotPassword(); break;
      case 'downloadcodes': {
        const codes = JSON.parse($('dialog').dataset.codes);
        downloadText('NCSC-RO1-Recovery-Codes.txt', 'NCSC RO1 department recovery codes\nKeep these codes secure.\n\n' +
          Object.entries(codes).map(([name, code]) => name + '\n' + code).join('\n\n'));
        break;
      }
      case 'register': state.page = 'documents'; render(); break;
      case 'import': importDialog(); break;
      case 'repreview': {
        const form = $('importReview');
        const overrides = Object.fromEntries(importPreview.datasets.filter(d => d.header_row).map(d => {
          const index = importPreview.datasets.indexOf(d);
          return [d.name, Number(form.elements['header' + index].value)];
        }));
        const fd = new FormData(); fd.append('file', importSource);
        fd.append('header', importSource.name.toLowerCase().endsWith('.xlsx') ? JSON.stringify(overrides) :
          String(Object.values(overrides)[0] || ''));
        target.disabled = true;
        try {
          const result = await api('/api/preview', fd);
          importPreview = {...result, filename:importSource.name};
          previewImport();
        } finally { target.disabled = false; }
        break;
      }
      case 'confirmimport': await confirmImport(target); break;
      case 'new': newDocument(); break;
      case 'sourcefile': $('newSourceFile').click(); break;
      case 'removesource':
        captureNewDocument();state.newDraft.source=null;state.newDraft.auto={};state.newDraft.columns=[...state.newDraft.baseColumns];state.dirty=true;renderNewDocument();toast('Source removed. Review the remaining details.');break;
      case 'editrecord': state.editing = true; renderRecord(); break;
      case 'canceledit':
        if (!state.dirty || window.confirm('Discard unsaved changes to this document?')) {
          state.editing = false; state.draft = {...state.record.cells}; state.dirty = false; renderRecord();
        }
        break;
      case 'acknowledge': {
        const r = state.record;
        if (state.dirty) { toast('Save your changes before acknowledging receipt.'); break; }
        await api('/api/save', {id:r.id, version:r.version, cells:{...r.cells, [r.mappings.status]:'Received'}});
        await loadData(); render(); await openRecord(r.id); toast('Receipt acknowledged.');
        break;
      }
      case 'delete': deleteDocument(); break;
      case 'deleteselected': deleteSelectedDocuments(); break;
      case 'confirmbatchdelete': {
        target.disabled=true;
        try {
          const result=await api('/api/archive-batch',{items:JSON.parse($('dialog').dataset.batch)});
          state.selected.clear();state.selecting=false;$('dialog').close();await loadData();render();
          toast(result.count+' document(s) moved to Deleted documents.');
        } catch(err) {target.disabled=false;throw err;}
        break;
      }
      case 'backrecord': renderRecord(); break;
      case 'confirmdelete':
        await api('/api/archive', {id:state.record.id, version:state.record.version});
        $('dialog').close(); await loadData(); render(); toast('Document moved to Deleted.'); break;
      case 'password': changePassword(); break;
      case 'addaccount': addAccount(); break;
      case 'guide': guide(); break;
      case 'clear': state.collection = ''; state.query = ''; state.status = ''; renderDocuments(); break;
      case 'refresh': await loadData(); render(); toast('Register refreshed.'); break;
      case 'printselected': printSlips(selectedRows().map(r=>r.id)); break;
      case 'selectmode': state.selecting=!state.selecting; renderDocuments(); break;
      case 'selectshown': for (const row of filteredRows()) state.selected.add(row.id); drawRows(); break;
      case 'exportselected': exportDialog(true); break;
      case 'clearselection': state.selected.clear(); drawRows(); break;
      case 'printslip':
        if (state.dirty) toast('Save your changes before printing the routing slip.');
        else await printSlip();
        break;
      case 'printmatrix': printMatrix(); break;
      case 'export': exportDialog(); break;
    }
  } catch (err) { showError(err); }
});
start();
