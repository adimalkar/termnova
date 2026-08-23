/**
 * Termnova - Negotiation Playbook & Version Redline Diff Tracker
 * Interactive client module managing tracks, vertical timelines,
 * two-column concession ledgers, SVG risk trajectory charts, and AI summaries.
 */

window.NegotiationModule = (function () {
  'use strict';

  // Module State
  const state = {
    tracks: [],
    activeTrackId: null,
    activeTrack: null,
    activeTab: 'timeline', // 'timeline', 'concessions', 'risk', 'diff', 'summary'
    diffFromVersion: 1,
    diffToVersion: 2,
    isLoading: false,
    eventsBound: false,
  };

  /**
   * Initialize module on application startup.
   */
  function init() {
    bindEvents();
    loadTracks();
  }

  /**
   * Bind event listeners for controls, tabs, and modals.
   */
  function bindEvents() {
    if (state.eventsBound) return;
    state.eventsBound = true;
    // Track selector dropdown
    const trackSelect = document.getElementById('neg-track-select');
    if (trackSelect) {
      trackSelect.addEventListener('change', (e) => {
        if (e.target.value) {
          selectTrack(e.target.value);
        }
      });
    }

    // New Track Button
    const newTrackBtn = document.getElementById('btn-neg-new-track');
    if (newTrackBtn) {
      newTrackBtn.addEventListener('click', openCreateTrackModal);
    }

    // Upload Version Button
    const uploadVerBtn = document.getElementById('btn-neg-upload-version');
    if (uploadVerBtn) {
      uploadVerBtn.addEventListener('click', openUploadVersionModal);
    }

    // Refresh Button
    const refreshBtn = document.getElementById('btn-neg-refresh');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        if (state.activeTrackId) {
          selectTrack(state.activeTrackId);
        } else {
          loadTracks();
        }
      });
    }

    // Tab buttons
    const tabBtns = document.querySelectorAll('.neg-tab-btn');
    tabBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        switchTab(tab);
      });
    });

    // Create Track Form
    const createTrackForm = document.getElementById('neg-create-track-form');
    if (createTrackForm) {
      createTrackForm.addEventListener('submit', handleCreateTrackSubmit);
    }

    // Upload Version Form
    const uploadVerForm = document.getElementById('neg-upload-version-form');
    if (uploadVerForm) {
      uploadVerForm.addEventListener('submit', handleUploadVersionSubmit);
    }

    // Modal Close Buttons
    const closeBtns = document.querySelectorAll('.neg-modal-close');
    closeBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        closeCreateTrackModal();
        closeUploadVersionModal();
      });
    });
  }

  /**
   * Fetch all negotiation tracks and populate select dropdown.
   */
  async function loadTracks() {
    try {
      const resp = await fetch('/api/v1/negotiations/');
      if (!resp.ok) throw new Error('Failed to load tracks');
      const tracks = await resp.json();
      state.tracks = tracks;

      renderTrackSelectDropdown(tracks);

      if (tracks.length > 0) {
        // Select first track if none active
        if (!state.activeTrackId || !tracks.some((t) => t.id === state.activeTrackId)) {
          selectTrack(tracks[0].id);
        }
      } else {
        renderEmptyState();
      }
    } catch (err) {
      console.error('Error loading negotiation tracks:', err);
    }
  }

  /**
   * Populate the track selector select element.
   */
  function renderTrackSelectDropdown(tracks) {
    const trackSelect = document.getElementById('neg-track-select');
    if (!trackSelect) return;

    trackSelect.innerHTML = '';
    if (tracks.length === 0) {
      trackSelect.innerHTML = '<option value="">No negotiation tracks available</option>';
      return;
    }

    tracks.forEach((t) => {
      const opt = document.createElement('option');
      opt.value = t.id;
      opt.textContent = `${t.name} (${t.counterparty}) • ${t.status.toUpperCase()}`;
      if (t.id === state.activeTrackId) {
        opt.selected = true;
      }
      trackSelect.appendChild(opt);
    });
  }

  /**
   * Select a specific negotiation track and load its subviews.
   */
  async function selectTrack(trackId) {
    state.activeTrackId = trackId;
    const trackSelect = document.getElementById('neg-track-select');
    if (trackSelect && trackSelect.value !== trackId) {
      trackSelect.value = trackId;
    }

    try {
      const resp = await fetch(`/api/v1/negotiations/${trackId}`);
      if (!resp.ok) throw new Error('Failed to load track details');
      const track = await resp.json();
      state.activeTrack = track;

      renderTrackHeader(track);
      loadActiveTabView();
    } catch (err) {
      console.error('Error selecting track:', err);
    }
  }

  /**
   * Render top summary banner for the active negotiation track.
   */
  function renderTrackHeader(track) {
    const banner = document.getElementById('neg-track-header');
    if (!banner) return;

    const statusClass = `status-${track.status}`;
    const startedDate = new Date(track.started_at).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });

    banner.innerHTML = `
      <div class="neg-header-top">
        <div class="neg-track-title-row">
          <h2>${escapeHtml(track.name)}</h2>
          <span class="neg-status-pill ${statusClass}">${escapeHtml(track.status)}</span>
        </div>
        <div class="neg-header-actions">
          <select id="neg-status-changer" class="neg-select" style="min-width: 140px; padding: 0.35rem 0.6rem; font-size: 0.8rem;">
            <option value="active" ${track.status === 'active' ? 'selected' : ''}>Active</option>
            <option value="agreed" ${track.status === 'agreed' ? 'selected' : ''}>Agreed / Signed</option>
            <option value="paused" ${track.status === 'paused' ? 'selected' : ''}>Paused</option>
            <option value="abandoned" ${track.status === 'abandoned' ? 'selected' : ''}>Abandoned</option>
          </select>
        </div>
      </div>
      <div class="neg-meta-pills">
        <div class="neg-meta-item"><span>Counterparty:</span> <strong>${escapeHtml(track.counterparty)}</strong></div>
        <div class="neg-meta-item"><span>Contract Type:</span> <strong>${escapeHtml(track.contract_type.toUpperCase())}</strong></div>
        <div class="neg-meta-item"><span>Rounds:</span> <strong>${track.versions ? track.versions.length : 0}</strong></div>
        <div class="neg-meta-item"><span>Lead Counsel:</span> <strong>${escapeHtml(track.started_by)}</strong></div>
        <div class="neg-meta-item"><span>Initiated:</span> <strong>${startedDate}</strong></div>
      </div>
    `;

    // Bind status change listener
    const statusChanger = document.getElementById('neg-status-changer');
    if (statusChanger) {
      statusChanger.addEventListener('change', async (e) => {
        await updateTrackStatus(track.id, e.target.value);
      });
    }
  }

  /**
   * Switch active subview tab.
   */
  function switchTab(tabName) {
    state.activeTab = tabName;

    // Update tab buttons
    document.querySelectorAll('.neg-tab-btn').forEach((btn) => {
      if (btn.dataset.tab === tabName) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Update tab contents
    document.querySelectorAll('.neg-tab-pane').forEach((pane) => {
      if (pane.id === `neg-tab-${tabName}`) {
        pane.style.display = 'block';
      } else {
        pane.style.display = 'none';
      }
    });

    loadActiveTabView();
  }

  /**
   * Load data for the active tab view.
   */
  function loadActiveTabView() {
    if (!state.activeTrackId) return;

    switch (state.activeTab) {
      case 'timeline':
        loadTimelineView(state.activeTrackId);
        break;
      case 'concessions':
        loadConcessionLedgerView(state.activeTrackId);
        break;
      case 'risk':
        loadRiskTrajectoryView(state.activeTrackId);
        break;
      case 'diff':
        loadDiffView(state.activeTrackId);
        break;
      case 'summary':
        loadSummaryView(state.activeTrackId);
        break;
    }
  }

  /**
   * ──── TAB 1: Vertical Timeline View ────
   */
  async function loadTimelineView(trackId) {
    const container = document.getElementById('neg-tab-timeline');
    if (!container) return;

    container.innerHTML = '<div class="loading-spinner">Loading timeline rounds...</div>';

    try {
      const resp = await fetch(`/api/v1/negotiations/${trackId}/timeline`);
      if (!resp.ok) throw new Error('Failed to load timeline');
      const data = await resp.json();

      if (!data.events || data.events.length === 0) {
        container.innerHTML = `
          <div class="empty-state" style="padding: 3rem 1rem; text-align: center;">
            <p style="color: #94a3b8; font-size: 0.95rem;">No version rounds recorded yet.</p>
            <button class="btn-neg-primary" onclick="NegotiationModule.openUploadVersionModal()" style="margin: 1rem auto 0;">
              + Upload Version 1
            </button>
          </div>
        `;
        return;
      }

      let timelineHtml = '<div class="timeline-container">';
      data.events.forEach((ev) => {
        const isCounterparty = ev.source === 'counterparty';
        const markerClass = isCounterparty ? 'marker-counterparty' : '';
        const sourceBadgeClass = isCounterparty ? 'source-counterparty' : 'source-internal';
        const sourceLabel = isCounterparty ? `${data.counterparty} Redline` : 'Our Proposal / Draft';

        const riskDeltaBadge =
          ev.risk_delta !== null && ev.risk_delta !== undefined
            ? `<span class="timeline-risk-chip" style="color: ${
                ev.risk_delta > 0 ? '#f87171' : ev.risk_delta < 0 ? '#34d399' : '#94a3b8'
              };">
                Risk: ${(ev.risk_score * 100).toFixed(0)}% (${ev.risk_delta >= 0 ? '+' : ''}${(
                ev.risk_delta * 100
              ).toFixed(0)}%)
              </span>`
            : '';

        let changesListHtml = '';
        if (ev.key_changes && ev.key_changes.length > 0) {
          changesListHtml = `
            <div class="timeline-key-changes">
              ${ev.key_changes
                .map((ch) => `<div class="timeline-change-bullet"><span>•</span> <span>${escapeHtml(ch)}</span></div>`)
                .join('')}
            </div>
          `;
        }

        timelineHtml += `
          <div class="timeline-node">
            <div class="timeline-marker ${markerClass}">v${ev.version_number}</div>
            <div class="timeline-card">
              <div class="timeline-card-header">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                  <span class="version-source-badge ${sourceBadgeClass}">${sourceLabel}</span>
                  <strong style="font-size: 0.95rem; color: #fff;">Version ${ev.version_number}</strong>
                </div>
                <div>${riskDeltaBadge}</div>
              </div>
              <div style="font-size: 0.85rem; color: #94a3b8;">
                File: <code style="color: #60a5fa; background: rgba(59,130,246,0.1); padding: 0.1rem 0.4rem; border-radius: 4px;">${escapeHtml(
                  ev.document_filename
                )}</code>
              </div>
              ${ev.notes ? `<div style="font-size: 0.85rem; color: #cbd5e1; font-style: italic;">"${escapeHtml(ev.notes)}"</div>` : ''}
              ${changesListHtml}
              <div class="timeline-card-footer">
                <span>By: ${escapeHtml(ev.uploaded_by)}</span>
                <span>${escapeHtml(ev.date)}</span>
              </div>
            </div>
          </div>
        `;
      });
      timelineHtml += '</div>';

      container.innerHTML = timelineHtml;
    } catch (err) {
      container.innerHTML = `<div class="error-msg">Error loading timeline: ${err.message}</div>`;
    }
  }

  /**
   * ──── TAB 2: Two-Column Concession Ledger View ────
   */
  async function loadConcessionLedgerView(trackId) {
    const container = document.getElementById('neg-tab-concessions');
    if (!container) return;

    container.innerHTML = '<div class="loading-spinner">Analyzing concessions balance...</div>';

    try {
      const resp = await fetch(`/api/v1/negotiations/${trackId}/concessions`);
      if (!resp.ok) throw new Error('Failed to load concessions');
      const data = await resp.json();

      const balanceClass = `balance-${data.balance}`;
      const balanceLabel =
        data.balance === 'favorable'
          ? 'Favorable Balance (Counterparty Conceded More)'
          : data.balance === 'unfavorable'
          ? 'Unfavorable Balance (We Conceded More)'
          : 'Balanced Negotiation';

      function renderConcessionList(items, partyClass) {
        if (!items || items.length === 0) {
          return '<p style="color: #64748b; font-size: 0.85rem; padding: 0.5rem 0;">No concessions recorded.</p>';
        }

        return items
          .map(
            (item) => `
          <div class="concession-card">
            <div class="concession-card-top">
              <span class="concession-category-tag">${escapeHtml(item.clause_category)}</span>
              <span class="concession-significance sig-${item.significance}">${item.significance}</span>
            </div>
            <div class="concession-summary-text">${escapeHtml(item.summary)}</div>
            <div style="font-size: 0.76rem; color: #94a3b8; display: flex; justify-content: space-between;">
              <span>Round: v${item.from_version} → v${item.to_version}</span>
              <span style="color: ${item.risk_impact === 'increased_risk' ? '#f87171' : item.risk_impact === 'decreased_risk' ? '#34d399' : '#94a3b8'}">
                ${item.risk_impact.replace('_', ' ').toUpperCase()}
              </span>
            </div>
          </div>
        `
          )
          .join('');
      }

      container.innerHTML = `
        <div class="neg-ledger-view">
          <div class="ledger-balance-banner">
            <div class="balance-status-box">
              <span style="font-size: 0.88rem; color: #94a3b8;">Negotiation Ledger Balance:</span>
              <span class="balance-tag ${balanceClass}">${balanceLabel}</span>
            </div>
            <div style="font-size: 0.85rem; color: #cbd5e1;">
              <strong>${data.our_concessions.length}</strong> our concessions vs <strong>${data.their_concessions.length}</strong> their concessions
            </div>
          </div>

          <div class="ledger-columns-grid">
            <!-- Left: We Gave -->
            <div class="ledger-column">
              <div class="ledger-col-header">
                <div class="ledger-col-title col-we-gave">
                  <span>← We Conceded (${data.our_concessions.length})</span>
                </div>
              </div>
              <div class="ledger-cards-list">
                ${renderConcessionList(data.our_concessions, 'us')}
              </div>
            </div>

            <!-- Right: They Gave -->
            <div class="ledger-column">
              <div class="ledger-col-header">
                <div class="ledger-col-title col-they-gave">
                  <span>They Conceded (${data.their_concessions.length}) →</span>
                </div>
              </div>
              <div class="ledger-cards-list">
                ${renderConcessionList(data.their_concessions, 'counterparty')}
              </div>
            </div>
          </div>
        </div>
      `;
    } catch (err) {
      container.innerHTML = `<div class="error-msg">Error loading concessions: ${err.message}</div>`;
    }
  }

  /**
   * ──── TAB 3: Risk Trajectory SVG Chart View ────
   */
  async function loadRiskTrajectoryView(trackId) {
    const container = document.getElementById('neg-tab-risk');
    if (!container) return;

    container.innerHTML = '<div class="loading-spinner">Computing risk trajectory...</div>';

    try {
      const resp = await fetch(`/api/v1/negotiations/${trackId}/risk-trajectory`);
      if (!resp.ok) throw new Error('Failed to load risk trajectory');
      const data = await resp.json();

      if (!data.versions || data.versions.length === 0) {
        container.innerHTML = '<div class="empty-state"><p>No risk trajectory data available.</p></div>';
        return;
      }

      const points = data.versions;
      const trendColor =
        data.overall_trend === 'improving' ? '#34d399' : data.overall_trend === 'deteriorating' ? '#f87171' : '#60a5fa';

      // SVG Chart generation
      const width = 600;
      const height = 200;
      const padding = 40;

      const maxRisk = 1.0;
      const minRisk = 0.0;

      const coords = points.map((p, idx) => {
        const x = points.length === 1 ? width / 2 : padding + (idx / (points.length - 1)) * (width - 2 * padding);
        const y = height - padding - (p.risk_score / maxRisk) * (height - 2 * padding);
        return { x, y, p };
      });

      let pathD = '';
      coords.forEach((pt, i) => {
        if (i === 0) {
          pathD += `M ${pt.x} ${pt.y}`;
        } else {
          pathD += ` L ${pt.x} ${pt.y}`;
        }
      });

      const circlesSvg = coords
        .map(
          (pt) => `
        <circle cx="${pt.x}" cy="${pt.y}" r="6" fill="#0f172a" stroke="${trendColor}" stroke-width="3" />
        <text x="${pt.x}" y="${pt.y - 12}" fill="#fff" font-size="11" font-weight="700" text-anchor="middle">v${
            pt.p.version_number
          } (${(pt.p.risk_score * 100).toFixed(0)}%)</text>
        <text x="${pt.x}" y="${height - 15}" fill="#94a3b8" font-size="10" text-anchor="middle">${escapeHtml(
            pt.p.source.toUpperCase()
          )}</text>
      `
        )
        .join('');

      container.innerHTML = `
        <div class="neg-risk-view">
          <div class="risk-chart-card">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
              <h3 style="font-size: 1.05rem; font-weight: 700; color: #fff; margin: 0;">Contract Risk Score Trajectory</h3>
              <span class="neg-status-pill" style="background: rgba(255,255,255,0.06); color: ${trendColor}; border: 1px solid ${trendColor};">
                Trend: ${data.overall_trend.toUpperCase()}
              </span>
            </div>

            <div class="risk-chart-container">
              <svg class="risk-svg-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
                <!-- Grid Lines -->
                <line x1="${padding}" y1="${padding}" x2="${width - padding}" y2="${padding}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="4" />
                <line x1="${padding}" y1="${height / 2}" x2="${width - padding}" y2="${height / 2}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="4" />
                <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="rgba(255,255,255,0.15)" />

                <!-- Trendline -->
                <path d="${pathD}" fill="none" stroke="${trendColor}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />

                <!-- Data Points & Labels -->
                ${circlesSvg}
              </svg>
            </div>

            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; padding-top: 0.5rem;">
              ${points
                .map(
                  (pt) => `
                <div style="background: rgba(15,23,42,0.5); padding: 0.75rem; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06);">
                  <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #94a3b8;">
                    <span>Round v${pt.version_number}</span>
                    <strong style="color: #fff;">${(pt.risk_score * 100).toFixed(0)}%</strong>
                  </div>
                  <div style="font-size: 0.75rem; color: #cbd5e1; margin-top: 0.25rem;">${escapeHtml(pt.date)}</div>
                </div>
              `
                )
                .join('')}
            </div>
          </div>
        </div>
      `;
    } catch (err) {
      container.innerHTML = `<div class="error-msg">Error loading risk trajectory: ${err.message}</div>`;
    }
  }

  /**
   * ──── TAB 4: Clause-by-Clause Diff View ────
   */
  async function loadDiffView(trackId) {
    const container = document.getElementById('neg-tab-diff');
    if (!container) return;

    if (!state.activeTrack || !state.activeTrack.versions || state.activeTrack.versions.length < 2) {
      container.innerHTML = `
        <div class="empty-state" style="padding: 3rem 1rem; text-align: center;">
          <p style="color: #94a3b8;">At least 2 versions are needed to perform a redline diff comparison.</p>
        </div>
      `;
      return;
    }

    const versions = state.activeTrack.versions;
    let fromV = state.diffFromVersion || 1;
    let toV = state.diffToVersion || (versions.length > 1 ? versions[versions.length - 1].version_number : 2);

    container.innerHTML = `
      <div class="neg-diff-view">
        <div class="diff-controls-bar">
          <label style="font-size: 0.85rem; font-weight: 600; color: #94a3b8;">Compare Version:</label>
          <select id="diff-from-select" class="neg-select" style="min-width: 120px;">
            ${versions.map((v) => `<option value="${v.version_number}" ${v.version_number === fromV ? 'selected' : ''}>v${v.version_number}</option>`).join('')}
          </select>
          <span style="color: #94a3b8; font-weight: 700;">to</span>
          <select id="diff-to-select" class="neg-select" style="min-width: 120px;">
            ${versions.map((v) => `<option value="${v.version_number}" ${v.version_number === toV ? 'selected' : ''}>v${v.version_number}</option>`).join('')}
          </select>
          <button id="btn-run-diff" class="btn-neg-primary" style="padding: 0.45rem 0.85rem;">Run Comparison</button>
        </div>
        <div id="diff-results-feed">
          <div class="loading-spinner">Fetching redline diff...</div>
        </div>
      </div>
    `;

    document.getElementById('btn-run-diff').addEventListener('click', () => {
      const f = parseInt(document.getElementById('diff-from-select').value, 10);
      const t = parseInt(document.getElementById('diff-to-select').value, 10);
      state.diffFromVersion = f;
      state.diffToVersion = t;
      fetchAndRenderDiff(trackId, f, t);
    });

    fetchAndRenderDiff(trackId, fromV, toV);
  }

  async function fetchAndRenderDiff(trackId, fromV, toV) {
    const feed = document.getElementById('diff-results-feed');
    if (!feed) return;

    if (fromV === toV) {
      feed.innerHTML = '<p style="color: #f87171; padding: 1rem;">Please select two distinct versions to compare.</p>';
      return;
    }

    feed.innerHTML = '<div class="loading-spinner">Generating redline diff...</div>';

    try {
      const resp = await fetch(`/api/v1/negotiations/${trackId}/diff?from_version=${fromV}&to_version=${toV}`);
      if (!resp.ok) throw new Error('Failed to generate diff');
      const data = await resp.json();

      if (!data.changes || data.changes.length === 0) {
        feed.innerHTML = '<div class="empty-state"><p>No clause changes found between these versions.</p></div>';
        return;
      }

      feed.innerHTML = `
        <div style="margin-bottom: 0.75rem; font-size: 0.9rem; color: #94a3b8;">
          ${escapeHtml(data.summary)}
        </div>
        <div style="display: flex; flex-direction: column; gap: 1rem;">
          ${data.changes
            .map(
              (c) => `
            <div class="diff-clause-card">
              <div class="diff-clause-header">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                  <span class="concession-category-tag">${escapeHtml(c.clause_category)}</span>
                  <span style="font-size: 0.78rem; text-transform: uppercase; color: #94a3b8; font-weight: 600;">${c.change_type}</span>
                </div>
                <div>
                  <span class="concession-significance sig-${c.significance}">${c.significance}</span>
                </div>
              </div>
              <div class="diff-content-box">
                ${c.diff_html || escapeHtml(c.modified_text)}
              </div>
              ${c.concession_summary ? `<div style="font-size: 0.82rem; color: #cbd5e1; font-style: italic;">Assessment: ${escapeHtml(c.concession_summary)}</div>` : ''}
            </div>
          `
            )
            .join('')}
        </div>
      `;
    } catch (err) {
      feed.innerHTML = `<div class="error-msg">Error generating diff: ${err.message}</div>`;
    }
  }

  /**
   * ──── TAB 5: AI Negotiation Summary View ────
   */
  async function loadSummaryView(trackId) {
    const container = document.getElementById('neg-tab-summary');
    if (!container) return;

    container.innerHTML = '<div class="loading-spinner">Generating AI negotiation summary...</div>';

    try {
      const resp = await fetch(`/api/v1/negotiations/${trackId}/summary`);
      if (!resp.ok) throw new Error('Failed to generate summary');
      const data = await resp.json();

      container.innerHTML = `
        <div class="neg-summary-view">
          <div class="summary-card">
            <div class="summary-section-title">Executive Summary</div>
            <p style="font-size: 0.92rem; line-height: 1.6; color: #f1f5f9; margin: 0;">
              ${escapeHtml(data.executive_summary)}
            </p>
          </div>

          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem;">
            <div class="summary-card">
              <div class="summary-section-title" style="color: #f87171;">Key Concessions We Made</div>
              <ul class="summary-bullet-list">
                ${data.key_concessions_us.map((c) => `<li><span>•</span> <span>${escapeHtml(c)}</span></li>`).join('')}
              </ul>
            </div>

            <div class="summary-card">
              <div class="summary-section-title" style="color: #34d399;">Key Concessions They Made</div>
              <ul class="summary-bullet-list">
                ${data.key_concessions_them.map((c) => `<li><span>•</span> <span>${escapeHtml(c)}</span></li>`).join('')}
              </ul>
            </div>
          </div>

          <div class="summary-card">
            <div class="summary-section-title" style="color: #fbbf24;">Risk Assessment & Outstanding Gaps</div>
            <p style="font-size: 0.88rem; color: #cbd5e1; margin-bottom: 0.5rem;">${escapeHtml(data.risk_assessment)}</p>
            <ul class="summary-bullet-list">
              ${data.remaining_gaps.map((g) => `<li><span>⚠️</span> <span>${escapeHtml(g)}</span></li>`).join('')}
            </ul>
          </div>
        </div>
      `;
    } catch (err) {
      container.innerHTML = `<div class="error-msg">Error loading summary: ${err.message}</div>`;
    }
  }

  /**
   * ──── Form Handlers & Modal Functions ────
   */
  function openCreateTrackModal() {
    const modal = document.getElementById('neg-create-track-modal');
    if (modal) modal.style.display = 'flex';
  }

  function closeCreateTrackModal() {
    const modal = document.getElementById('neg-create-track-modal');
    if (modal) modal.style.display = 'none';
  }

  function openUploadVersionModal() {
    const modal = document.getElementById('neg-upload-version-modal');
    if (modal) modal.style.display = 'flex';
  }

  function closeUploadVersionModal() {
    const modal = document.getElementById('neg-upload-version-modal');
    if (modal) modal.style.display = 'none';
  }

  async function handleCreateTrackSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const name = form.querySelector('[name="name"]').value.trim();
    const counterparty = form.querySelector('[name="counterparty"]').value.trim();
    const contract_type = form.querySelector('[name="contract_type"]').value;
    const notes = form.querySelector('[name="notes"]').value.trim();
    const started_by = form.querySelector('[name="started_by"]').value.trim() || 'Legal Counsel';

    if (!name || !counterparty) return;

    try {
      const resp = await fetch('/api/v1/negotiations/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, counterparty, contract_type, notes, started_by }),
      });

      if (!resp.ok) throw new Error('Failed to create negotiation track');
      const newTrack = await resp.json();
      closeCreateTrackModal();
      form.reset();
      await loadTracks();
      selectTrack(newTrack.id);
    } catch (err) {
      alert(`Error creating track: ${err.message}`);
    }
  }

  async function handleUploadVersionSubmit(e) {
    e.preventDefault();
    if (!state.activeTrackId) {
      alert('Please select or create a negotiation track first.');
      return;
    }

    const form = e.target;
    const fileInput = form.querySelector('[name="file"]');
    const source = form.querySelector('[name="source"]').value;
    const notes = form.querySelector('[name="notes"]').value.trim();
    const uploaded_by = form.querySelector('[name="uploaded_by"]').value.trim() || 'Legal Counsel';

    if (!fileInput.files || fileInput.files.length === 0) {
      alert('Please choose a contract document file.');
      return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('source', source);
    if (notes) formData.append('notes', notes);
    formData.append('uploaded_by', uploaded_by);

    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Processing & Diffing...';
    }

    try {
      const resp = await fetch(`/api/v1/negotiations/${state.activeTrackId}/versions`, {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        const errJson = await resp.json();
        throw new Error(errJson.detail || 'Failed to upload version');
      }

      closeUploadVersionModal();
      form.reset();
      await selectTrack(state.activeTrackId);
    } catch (err) {
      alert(`Error uploading version: ${err.message}`);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Upload & Process Round';
      }
    }
  }

  async function updateTrackStatus(trackId, status) {
    try {
      const resp = await fetch(`/api/v1/negotiations/${trackId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      if (!resp.ok) throw new Error('Failed to update track status');
      await selectTrack(trackId);
    } catch (err) {
      console.error('Error updating status:', err);
    }
  }

  function renderEmptyState() {
    const container = document.getElementById('neg-tab-timeline');
    if (container) {
      container.innerHTML = `
        <div class="empty-state" style="padding: 3rem 1rem; text-align: center;">
          <h3 style="color: #fff; margin-bottom: 0.5rem;">No Negotiation Tracks</h3>
          <p style="color: #94a3b8; margin-bottom: 1.5rem;">Start tracking redline rounds and concessions across contract versions.</p>
          <button class="btn-neg-primary" onclick="NegotiationModule.openCreateTrackModal()" style="margin: 0 auto;">
            + Create First Negotiation Track
          </button>
        </div>
      `;
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Public API
  return {
    init,
    loadTracks,
    selectTrack,
    openCreateTrackModal,
    closeCreateTrackModal,
    openUploadVersionModal,
    closeUploadVersionModal,
  };
})();

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => window.NegotiationModule.init());
} else {
  window.NegotiationModule.init();
}
