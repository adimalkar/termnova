/**
 * Termnova — Main Application Orchestrator & State Store
 */

const AppState = {
  activeView: 'chat',
  documents: [],
  activeDrawerCitation: null,
  activeDocumentId: null,
  activeDocumentName: null,
};
window.AppState = AppState;

// ──── Formatting Utilities ────
function formatContractTitle(filename) {
  if (!filename) return "Untitled Agreement";
  let clean = String(filename);
  // Strip 8-char hex prefix e.g. 486a120c_ or uuid prefixes
  clean = clean.replace(/^[0-9a-fA-F]{8}_/, '');
  clean = clean.replace(/^[0-9a-fA-F-]{36}_/, '');
  // Strip file extension
  clean = clean.replace(/\.[^/.]+$/, '');
  // Strip SEC EDGAR exhibit tags e.g. 2013_EX_10.34_DEVELOPMENT_AGREEMENT
  clean = clean.replace(/_\d{4}_EX_\d+[\.\d]*_/i, ' ');
  // Clean double/triple underscores
  clean = clean.replace(/_+/g, ' ');
  // Insert space before camelCase capitals e.g. AlliedEsportsEntertainmentInc -> Allied Esports Entertainment Inc
  clean = clean.replace(/([a-z])([A-Z])/g, '$1 $2');
  clean = clean.replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2');
  // Format common suffixes
  clean = clean.replace(/\bInc\b/g, 'Inc.').replace(/\bCorp\b/g, 'Corp.').replace(/\bLtd\b/g, 'Ltd.').replace(/\bLlc\b/g, 'LLC');
  clean = clean.replace(/\s+/g, ' ').trim();
  return clean || filename;
}
window.formatContractTitle = formatContractTitle;

function formatMarkdownText(text) {
  if (!text) return "";
  let s = String(text);
  // Remove raw hex prefixes inside parenthetical filename references e.g. (486a120c_AlliedEsports...)
  s = s.replace(/\([0-9a-fA-F]{8}_([^)]+)\)/g, '($1)');
  // Clean double underscores
  s = s.replace(/__+/g, ' ');
  // Convert markdown **bold** to <strong>
  s = s.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Highlight dollar amounts
  s = s.replace(/(\$[\d,]+(?:\.\d{2})?(?:\s*(?:USD|million|k))?)/gi, '<span class="value-highlight">$1</span>');
  return s;
}
window.formatMarkdownText = formatMarkdownText;

// ──── API Fetch Wrapper ────
const DESK_ACTOR_KEY = 'termnova.actor';

function getDeskActor() {
  try {
    const stored = localStorage.getItem(DESK_ACTOR_KEY);
    if (stored && stored.trim()) return stored.trim().slice(0, 100);
  } catch (e) {
    /* private mode */
  }
  return 'Counsel';
}

function setDeskActor(name) {
  const clean = String(name || 'Counsel').trim().slice(0, 100) || 'Counsel';
  try {
    localStorage.setItem(DESK_ACTOR_KEY, clean);
  } catch (e) {
    /* ignore */
  }
  return clean;
}

async function apiRequest(endpoint, options = {}) {
  const defaultHeaders = {
    'Content-Type': 'application/json',
    'X-Termnova-Actor': getDeskActor(),
  };

  if (options.body instanceof FormData) {
    delete defaultHeaders['Content-Type'];
  }

  const config = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  };

  try {
    const res = await fetch(endpoint, config);
    if (!res.ok) {
      const errJson = await res.json().catch(() => ({}));
      const detail = errJson.detail;
      const message = typeof detail === 'string'
        ? detail
        : (Array.isArray(detail) ? detail.map((d) => d.msg || d).join('; ') : `HTTP ${res.status}: ${res.statusText}`);
      throw new Error(message);
    }
    if (res.status === 204) return null;
    return await res.json();
  } catch (err) {
    console.error(`API error on ${endpoint}:`, err);
    throw err;
  }
}
window.apiRequest = apiRequest;
window.getDeskActor = getDeskActor;
window.setDeskActor = setDeskActor;

// ──── Toast Notifications ────
function showToast(message, type = 'info', duration = 3500) {
  const hub = document.getElementById('toast-hub');
  if (!hub) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${message}</span>`;

  hub.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 200ms ease';
    setTimeout(() => toast.remove(), 200);
  }, duration);
}
window.showToast = showToast;

// ──── Source Drawer Management ────
function openSourceDrawer(citation) {
  const drawer = document.getElementById('source-drawer');
  const badge = document.getElementById('drawer-source-badge');
  const docTitle = document.getElementById('drawer-doc-title');
  const pageNum = document.getElementById('drawer-page-num');
  const secHeader = document.getElementById('drawer-section-header');
  const excerptText = document.getElementById('drawer-excerpt-text');

  if (!drawer) return;

  badge.textContent = `Passage ${citation.source_number || 1}`;
  docTitle.textContent = citation.document_filename || 'Contract Document';
  pageNum.textContent = citation.page_number ? `Page ${citation.page_number}` : 'Page N/A';
  secHeader.textContent = citation.section_header || 'General Section';
  excerptText.textContent = citation.excerpt || 'No chunk text snippet available.';

  drawer.classList.add('open');
}

function closeSourceDrawer() {
  const drawer = document.getElementById('source-drawer');
  if (drawer) {
    drawer.classList.remove('open');
  }
}

// ──── Mobile Off-Canvas Sidebar Management ────
function openMobileSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const backdrop = document.getElementById('mobile-sidebar-backdrop');
  if (sidebar) sidebar.classList.add('open');
  if (backdrop) backdrop.classList.add('open');
}

function closeMobileSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const backdrop = document.getElementById('mobile-sidebar-backdrop');
  if (sidebar) sidebar.classList.remove('open');
  if (backdrop) backdrop.classList.remove('open');
}

window.openMobileSidebar = openMobileSidebar;
window.closeMobileSidebar = closeMobileSidebar;

// ──── Navigation & View Switching ────
function switchView(viewName) {
  AppState.activeView = viewName;

  // Auto-close mobile sidebar if open
  closeMobileSidebar();

  // Update nav buttons
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.view === viewName);
  });

  // Update view panels
  document.querySelectorAll('.view-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id === `view-${viewName}`);
  });

  // Update breadcrumb and header title
  const titleMap = {
    chat: {
      breadcrumb: 'Ask',
      title: 'Ask the contracts',
      purpose: 'Every answer names the page it came from. Click a yellow mark to read the clause.',
    },
    workspace: {
      breadcrumb: 'Room',
      title: 'Deal room',
      purpose: 'Talk with the team, or ask only the contracts attached to this room.',
    },
    inbox: {
      breadcrumb: 'Inbox',
      title: 'What needs a person',
      purpose: 'New agreements land here, scored by how soon someone should look.',
    },
    graph: {
      breadcrumb: 'Family',
      title: 'How the papers relate',
      purpose: 'An MSA, its SOWs, amendments, and the parties on the signature block.',
    },
    compare: {
      breadcrumb: 'Redline',
      title: 'What changed',
      purpose: 'Red left the page. Blue was added. Yellow is a cited passage.',
    },
    negotiations: {
      breadcrumb: 'Rounds',
      title: 'This deal, round by round',
      purpose: 'Each upload is a round. See what you gave, and whether risk went up.',
    },
    intelligence: {
      breadcrumb: 'Portfolio',
      title: 'The book at a glance',
      purpose: 'Where the same clause is harsh across vendors, and where the playbook is missing.',
    },
    documents: {
      breadcrumb: 'Library',
      title: 'Agreements on the desk',
      purpose: 'Add a file, then ask it, redline it, or send it to Inbox.',
    },
    analytics: {
      breadcrumb: 'Reliability',
      title: 'Can you trust this answer?',
      purpose: 'How often answers stay on the page, and how long they take. For counsel, not for the cluster.',
    },
  };

  const info = titleMap[viewName] || titleMap.chat;
  const breadcrumbEl = document.getElementById('view-breadcrumb');
  const titleEl = document.getElementById('view-title');
  const purposeEl = document.getElementById('view-purpose');
  const mobilePill = document.getElementById('mobile-view-pill');
  if (breadcrumbEl) breadcrumbEl.textContent = info.breadcrumb;
  if (titleEl) titleEl.textContent = info.title;
  if (purposeEl) purposeEl.textContent = info.purpose;
  if (mobilePill) mobilePill.textContent = info.breadcrumb;

  document.querySelectorAll('.nav-item').forEach((btn) => {
    if (btn.dataset.view === viewName) {
      btn.setAttribute('aria-current', 'page');
    } else {
      btn.removeAttribute('aria-current');
    }
  });

  const hashMap = {
    chat: 'ask',
    inbox: 'inbox',
    compare: 'redline',
    graph: 'family',
    negotiations: 'rounds',
    workspace: 'room',
    documents: 'library',
    intelligence: 'portfolio',
    analytics: 'reliability',
  };
  const nextHash = hashMap[viewName] || viewName;
  if (window.location.hash.replace('#', '') !== nextHash) {
    history.replaceState(null, '', `#${nextHash}`);
  }

  const loaders = {
    workspace: () => {
      if (!window.WorkspaceApp) throw new Error('Room is not loaded yet. Refresh the page.');
      return window.WorkspaceApp.init();
    },
    inbox: () => {
      if (!window.inboxApp) throw new Error('Inbox is not loaded yet. Refresh the page.');
      return window.inboxApp.loadData();
    },
    negotiations: () => {
      if (!window.NegotiationModule) throw new Error('Rounds is not loaded yet. Refresh the page.');
      return window.NegotiationModule.loadTracks();
    },
    intelligence: () => {
      if (!window.IntelligenceApp) throw new Error('Portfolio is not loaded yet. Refresh the page.');
      return window.IntelligenceApp.init();
    },
    graph: () => {
      if (!window.initGraphView) throw new Error('Family is not loaded yet. Refresh the page.');
      return window.initGraphView();
    },
    documents: () => {
      if (!window.loadDocumentsList) throw new Error('Library is not loaded yet. Refresh the page.');
      return window.loadDocumentsList();
    },
    analytics: () => {
      if (!window.loadAnalyticsData) throw new Error('Reliability is not loaded yet. Refresh the page.');
      return window.loadAnalyticsData();
    },
    compare: () => {
      if (!window.initCompareDropdowns) throw new Error('Redline is not loaded yet. Refresh the page.');
      return window.initCompareDropdowns();
    },
  };

  const loader = loaders[viewName];
  if (loader) {
    Promise.resolve()
      .then(loader)
      .catch((err) => {
        console.error(`Module "${viewName}" failed`, err);
        showModuleFault(viewName, err);
      });
  }
}

window.switchView = switchView;

function askAboutDocument(docName, docId) {
  AppState.activeDocumentId = docId || null;
  AppState.activeDocumentName = docName || null;
  switchView('chat');
  updateAskScopeNote();
  const queryInput = document.getElementById('query-input');
  if (!queryInput) return;
  const title = window.formatContractTitle(docName);
  queryInput.value = `What should I watch in ${title}? Liability caps, termination, and who pays.`;
  queryInput.dispatchEvent(new Event('input'));
  queryInput.focus();
}
window.askAboutDocument = askAboutDocument;
window.AppState = AppState;

function updateAskScopeNote() {
  const note = document.getElementById('ask-scope-note');
  if (!note) return;
  if (AppState.activeDocumentId && AppState.activeDocumentName) {
    const title = window.formatContractTitle(AppState.activeDocumentName);
    note.hidden = false;
    note.innerHTML = `Asking <strong>${title}</strong> only. <button type="button" id="btn-clear-ask-scope">Search the whole book</button>`;
    const clearBtn = document.getElementById('btn-clear-ask-scope');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        AppState.activeDocumentId = null;
        AppState.activeDocumentName = null;
        updateAskScopeNote();
      });
    }
  } else {
    note.hidden = true;
    note.innerHTML = '';
  }
}
window.updateAskScopeNote = updateAskScopeNote;

function showModuleFault(viewName, err) {
  const panel = document.getElementById(`view-${viewName}`);
  if (!panel) return;
  let host = panel.querySelector('[data-module-body]') || panel.querySelector('.inbox-list-feed, .intelligence-container, .neg-view-container, .documents-container, .analytics-container, .graph-view-panel, .workspace-view-container, .compare-container');
  if (!host) host = panel;
  const existing = panel.querySelector('.module-fault');
  if (existing) existing.remove();
  const box = document.createElement('div');
  box.className = 'module-fault';
  box.innerHTML = `<h3>This tab could not load</h3><p>${String(err.message || err)}. The rest of the desk is still available.</p>`;
  host.prepend(box);
}

// ──── System Status Check ────
async function checkSystemHealth() {
  const label = document.getElementById('system-status-label');
  try {
    const desk = await apiRequest('/api/v1/desk/status');
    const down = (desk.modules || []).filter((m) => !m.ready);
    if (desk.overall === 'healthy') {
      if (label) label.textContent = 'Desk is ready';
    } else if (down.length) {
      if (label) label.textContent = `${down.map((m) => m.label).join(', ')} needs a look`;
    } else {
      if (label) label.textContent = 'Desk is slow — try again in a moment';
    }
  } catch (e) {
    try {
      const health = await apiRequest('/health');
      if (label) {
        label.textContent = health.status === 'healthy' ? 'Desk is ready' : 'Desk is slow — try again in a moment';
      }
    } catch (ignored) {
      if (label) label.textContent = 'Working from cached papers';
    }
  }
}

// ──── Fetch Initial Vault Stats ────
async function updateVaultStats() {
  try {
    const data = await apiRequest('/api/v1/documents');
    const totalDocs = data.total_count || data.total || (data.documents ? data.documents.length : 0);
    const sidebarPill = document.getElementById('sidebar-doc-count');
    const headerScope = document.getElementById('header-scope-label');
    const studioDocs = document.getElementById('studio-stat-docs');
    const studioChunks = document.getElementById('studio-stat-chunks');

    if (sidebarPill) sidebarPill.textContent = totalDocs;
    if (headerScope) {
      const n = Number(totalDocs) || 0;
      headerScope.textContent = n === 1 ? '1 agreement in the book' : `${n} agreements in the book`;
    }
    if (studioDocs) studioDocs.textContent = totalDocs;

    let totalChunks = 0;
    if (data.documents) {
      data.documents.forEach((d) => {
        totalChunks += d.chunk_count || 0;
      });
    }
    if (studioChunks && totalChunks > 0) studioChunks.textContent = totalChunks;
  } catch (e) {
    console.debug('Vault stats fetch deferred');
  }
}

// ──── Initialization ────
document.addEventListener('DOMContentLoaded', () => {
  // Nav clicks
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.addEventListener('click', (event) => {
      event.preventDefault();
      const view = btn.dataset.view;
      if (view) switchView(view);
    });
  });

  // Drawer close button
  const btnCloseDrawer = document.getElementById('btn-close-drawer');
  if (btnCloseDrawer) {
    btnCloseDrawer.addEventListener('click', closeSourceDrawer);
  }

  // Refresh status button
  const btnRefresh = document.getElementById('btn-refresh-status');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => {
      checkSystemHealth();
      updateVaultStats();
      showToast('Desk checked', 'info');
    });
  }

  const actorInput = document.getElementById('desk-actor-input');
  if (actorInput) {
    actorInput.value = getDeskActor();
    actorInput.addEventListener('change', () => {
      const name = setDeskActor(actorInput.value);
      actorInput.value = name;
      if (window.WorkspaceApp) window.WorkspaceApp.currentUserName = name;
      showToast(`Signing as ${name}`, 'info');
    });
  }

  const vaultList = document.getElementById('sidebar-vault-list');
  if (vaultList) {
    vaultList.addEventListener('click', (event) => {
      const item = event.target.closest('.vault-item');
      if (!item) return;
      event.preventDefault();
      askAboutDocument(item.dataset.doc, item.dataset.docId);
    });
  }

  // Connect WebSocket Push Notifications
  if (window.wsClient) {
    window.wsClient.connectNotifications((msg) => {
      if (msg.event === 'ingestion_progress') {
        const { filename, status } = msg.data || {};
        if (status === 'completed') {
          showToast(`${filename} is on the desk`, 'success');
          updateVaultStats();
          if (window.loadDocumentsList) window.loadDocumentsList();
        }
      }
    });
  }

  // Legal Modals handlers
  const btnDisclaimer = document.getElementById('btn-open-disclaimer');
  const btnTerms = document.getElementById('btn-open-terms');
  const btnPrivacy = document.getElementById('btn-open-privacy');

  if (btnDisclaimer) {
    btnDisclaimer.addEventListener('click', () => {
      const modal = document.getElementById('modal-disclaimer');
      if (modal) modal.style.display = 'flex';
    });
  }
  if (btnTerms) {
    btnTerms.addEventListener('click', () => {
      const modal = document.getElementById('modal-terms');
      if (modal) modal.style.display = 'flex';
    });
  }
  if (btnPrivacy) {
    btnPrivacy.addEventListener('click', () => {
      const modal = document.getElementById('modal-privacy');
      if (modal) modal.style.display = 'flex';
    });
  }

  // Close modals on clicking close buttons or backdrop
  document.querySelectorAll('.btn-close-modal').forEach((btn) => {
    btn.addEventListener('click', () => {
      const modalId = btn.dataset.close;
      if (modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'none';
      }
    });
  });

  document.querySelectorAll('.modal-backdrop').forEach((backdrop) => {
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) {
        backdrop.style.display = 'none';
      }
    });
  });

  // Mobile Menu & Backdrop listeners
  const btnMobileMenu = document.getElementById('btn-mobile-menu');
  const mobileBackdrop = document.getElementById('mobile-sidebar-backdrop');
  if (btnMobileMenu) {
    btnMobileMenu.addEventListener('click', (e) => {
      e.stopPropagation();
      const sidebar = document.querySelector('.sidebar');
      if (sidebar && sidebar.classList.contains('open')) {
        closeMobileSidebar();
      } else {
        openMobileSidebar();
      }
    });
  }
  if (mobileBackdrop) {
    mobileBackdrop.addEventListener('click', closeMobileSidebar);
  }

  // Initial health check & stats
  checkSystemHealth();
  updateVaultStats();

  // Support URL hash routing (e.g., #workspace, #graph, #compare, #documents, #analytics)
  const hash = window.location.hash.replace('#', '').toLowerCase();
  const hashViewMap = {
    workspace: 'workspace',
    team: 'workspace',
    map: 'graph',
    graph: 'graph',
    diff: 'compare',
    compare: 'compare',
    vault: 'documents',
    documents: 'documents',
    analytics: 'analytics',
    chat: 'chat',
    ask: 'chat',
    inbox: 'inbox',
    rooms: 'workspace',
    room: 'workspace',
    redline: 'compare',
    family: 'graph',
    rounds: 'negotiations',
    library: 'documents',
    portfolio: 'intelligence',
    reliability: 'analytics',
  };
  if (hash && hashViewMap[hash]) {
    switchView(hashViewMap[hash]);
  }

  window.addEventListener('hashchange', () => {
    const next = window.location.hash.replace('#', '').toLowerCase();
    const view = hashViewMap[next];
    if (view && AppState.activeView !== view) switchView(view);
  });
});
