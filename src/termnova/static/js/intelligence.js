/**
 * ═══════════════════════════════════════════════════════════════════════════════
 * Termnova — Cross-Contract Intelligence, Clause Heatmap & Portfolio Analytics
 * ═══════════════════════════════════════════════════════════════════════════════
 */

const IntelligenceApp = (function () {
    const state = {
        activeTab: 'heatmap',
        heatmapData: null,
        scorecardData: null,
        benchmarkData: null,
        trendData: null,
        gapData: null,
        summaryData: null,
        documentsList: [],
        selectedDocId: null,
        selectedVendor: '',
        trendMetric: 'risk',
        trendPeriod: 'monthly',
        heatmapFilterType: 'all',
    };

    // ─────────────────────────────────────────────────────────────────────────────
    // Initializer
    // ─────────────────────────────────────────────────────────────────────────────

    let eventsBound = false;

    async function init() {
        if (!eventsBound) {
            bindTabs();
            bindFilters();
            eventsBound = true;
        }
        await loadSummary();
        await loadDocumentsDropdown();
        await switchTab(state.activeTab);
    }

    function bindTabs() {
        const tabBtns = document.querySelectorAll('.intel-tab-btn');
        tabBtns.forEach((btn) => {
            btn.addEventListener('click', (e) => {
                const targetTab = e.currentTarget.getAttribute('data-tab');
                if (targetTab) {
                    switchTab(targetTab);
                }
            });
        });
    }

    function bindFilters() {
        const typeSelect = document.getElementById('intel-filter-type');
        if (typeSelect) {
            typeSelect.addEventListener('change', (e) => {
                state.heatmapFilterType = e.target.value;
                if (state.activeTab === 'heatmap') loadHeatmap();
                if (state.activeTab === 'gaps') loadGaps();
            });
        }

        const vendorSearch = document.getElementById('intel-search-vendor');
        if (vendorSearch) {
            vendorSearch.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    state.selectedVendor = e.target.value.trim();
                    if (state.activeTab === 'heatmap') loadHeatmap();
                    if (state.activeTab === 'scorecard') loadScorecard(state.selectedVendor);
                }
            });
        }
    }

    async function switchTab(tabName) {
        state.activeTab = tabName;

        document.querySelectorAll('.intel-tab-btn').forEach((btn) => {
            btn.classList.toggle('active', btn.getAttribute('data-tab') === tabName);
        });

        document.querySelectorAll('.intel-tab-pane').forEach((pane) => {
            pane.style.display = pane.id === `intel-pane-${tabName}` ? 'block' : 'none';
        });

        if (tabName === 'heatmap') await loadHeatmap();
        if (tabName === 'scorecard') await loadScorecard(state.selectedVendor || 'OmniCloud');
        if (tabName === 'benchmark') await loadBenchmark(state.selectedDocId);
        if (tabName === 'trends') await loadTrends(state.trendMetric, state.trendPeriod);
        if (tabName === 'gaps') await loadGaps();
    }

    // ─────────────────────────────────────────────────────────────────────────────
    // 1. Executive Summary
    // ─────────────────────────────────────────────────────────────────────────────

    async function loadSummary() {
        try {
            const resp = await fetch('/api/v1/intelligence/summary');
            if (resp.ok) {
                state.summaryData = await resp.json();
                renderSummary(state.summaryData);
            }
        } catch (err) {
            console.warn('Could not load portfolio summary:', err);
        }
    }

    function renderSummary(summary) {
        const cntEl = document.getElementById('intel-stat-contracts');
        if (cntEl) cntEl.textContent = summary.total_contracts || '0';

        const valEl = document.getElementById('intel-stat-val');
        if (valEl) {
            valEl.textContent = summary.total_portfolio_value
                ? `$${(summary.total_portfolio_value / 1000).toFixed(0)}k`
                : '$0';
        }

        const riskEl = document.getElementById('intel-stat-risk');
        if (riskEl) {
            const pct = Math.round((summary.avg_risk_score || 0.25) * 100);
            riskEl.textContent = `${pct}%`;
        }

        const compEl = document.getElementById('intel-stat-compliance');
        if (compEl) {
            compEl.textContent = `${summary.compliance_score || 95}%`;
        }
    }

    async function loadDocumentsDropdown() {
        try {
            const resp = await fetch('/api/v1/documents');
            if (resp.ok) {
                const data = await resp.json();
                state.documentsList = data.items || [];
                if (state.documentsList.length > 0 && !state.selectedDocId) {
                    state.selectedDocId = state.documentsList[0].id;
                }
                populateBenchmarkDropdown();
            }
        } catch (err) {
            console.warn('Could not load document list for benchmark:', err);
        }
    }

    function populateBenchmarkDropdown() {
        const select = document.getElementById('benchmark-doc-select');
        if (!select) return;

        const formatTitle = window.formatContractTitle || ((t) => t);
        select.innerHTML = state.documentsList
            .map((d) => `<option value="${d.id}">${formatTitle(d.filename)}</option>`)
            .join('');

        select.value = state.selectedDocId;
        select.addEventListener('change', (e) => {
            state.selectedDocId = e.target.value;
            loadBenchmark(state.selectedDocId);
        });
    }

    // ─────────────────────────────────────────────────────────────────────────────
    // 2. Clause Heatmap Matrix
    // ─────────────────────────────────────────────────────────────────────────────

    async function loadHeatmap() {
        const container = document.getElementById('heatmap-container');
        if (!container) return;
        container.innerHTML = '<div style="padding: 2rem; text-align: center; color: #94a3b8;">Computing portfolio heatmap matrix...</div>';

        try {
            let url = '/api/v1/intelligence/clause-heatmap';
            const params = new URLSearchParams();
            if (state.heatmapFilterType && state.heatmapFilterType !== 'all') {
                params.append('contract_type', state.heatmapFilterType);
            }
            if (state.selectedVendor) {
                params.append('counterparty', state.selectedVendor);
            }
            if (params.toString()) {
                url += `?${params.toString()}`;
            }

            const resp = await fetch(url);
            if (resp.ok) {
                state.heatmapData = await resp.json();
                renderHeatmap(state.heatmapData);
            }
        } catch (err) {
            container.innerHTML = `<div style="padding: 2rem; text-align: center; color: #ef4444;">Failed to load clause heatmap: ${err.message}</div>`;
        }
    }

    function renderHeatmap(data) {
        const container = document.getElementById('heatmap-container');
        if (!container) return;

        if (!data.rows || data.rows.length === 0) {
            container.innerHTML = '<div style="padding: 3rem; text-align: center; color: #94a3b8;">No contracts match the current filter criteria.</div>';
            return;
        }

        const cols = data.columns || [];
        const summaries = data.column_summaries || [];

        let tableHtml = `
            <div class="heatmap-wrapper">
                <table class="heatmap-table">
                    <thead>
                        <tr>
                            <th class="doc-header-col">Contract Document</th>
                            ${cols.map(c => `
                                <th>
                                    <div class="category-header-wrap">
                                        ${formatCategoryName(c)}
                                    </div>
                                </th>
                            `).join('')}
                        </tr>
                    </thead>
                    <tbody>
        `;

        const formatTitle = window.formatContractTitle || ((t) => t);

        data.rows.forEach(row => {
            const cleanTitle = formatTitle(row.filename);
            tableHtml += `
                <tr>
                    <td class="doc-cell">
                        <div class="doc-cell-content">
                            <span class="doc-name" title="${row.filename}">${cleanTitle}</span>
                            <div class="doc-meta">
                                <span>${(row.contract_type || 'msa').toUpperCase()}</span>
                                <span>•</span>
                                <span style="font-family: var(--font-mono); font-size: 0.7rem; color: #64748b;">${row.filename}</span>
                            </div>
                        </div>
                    </td>
                    ${cols.map(c => {
                        const cell = row.cells[c] || { present: false };
                        if (!cell.present) {
                            return `<td class="heatmap-cell absent" title="Absent: ${formatCategoryName(c)}">—</td>`;
                        }
                        const riskClass = `risk-${cell.risk_level || 'low'}`;
                        const icon = cell.risk_level === 'critical' ? 'C' : cell.risk_level === 'high' ? 'H' : cell.risk_level === 'medium' ? 'M' : 'L';
                        const safeExcerpt = (cell.excerpt || '').replace(/"/g, '&quot;');
                        return `
                            <td class="heatmap-cell ${riskClass}"
                                data-cat="${c}"
                                data-risk="${cell.risk_level || 'low'}"
                                data-excerpt="${safeExcerpt}"
                                onclick="IntelligenceApp.showClausePreview('${c}', '${safeExcerpt}', '${cell.risk_level || 'low'}')">
                                ${icon}
                            </td>
                        `;
                    }).join('')}
                </tr>
            `;
        });

        // Add Footer with Column Summaries
        tableHtml += `
                    </tbody>
                    <tfoot>
                        <tr>
                            <td class="doc-cell">Portfolio Coverage</td>
                            ${summaries.map(s => `
                                <td>
                                    <div class="column-coverage-bar-wrap">
                                        <span class="coverage-pct-label">${s.coverage_pct}%</span>
                                        <div class="mini-cov-bar">
                                            <div class="mini-cov-fill" style="width: ${s.coverage_pct}%"></div>
                                        </div>
                                    </div>
                                </td>
                            `).join('')}
                        </tr>
                    </tfoot>
                </table>
            </div>
        `;

        container.innerHTML = tableHtml;
    }

    // ─────────────────────────────────────────────────────────────────────────────
    // 3. Vendor Scorecard
    // ─────────────────────────────────────────────────────────────────────────────

    async function loadScorecard(vendorName) {
        const container = document.getElementById('scorecard-container');
        if (!container) return;
        container.innerHTML = '<div style="padding: 2rem; text-align: center; color: #94a3b8;">Aggregating vendor metrics...</div>';

        try {
            const resp = await fetch(`/api/v1/intelligence/vendor-scorecard?vendor_name=${encodeURIComponent(vendorName)}`);
            if (resp.ok) {
                state.scorecardData = await resp.json();
                renderVendorScorecard(state.scorecardData);
            }
        } catch (err) {
            container.innerHTML = `<div style="padding: 2rem; text-align: center; color: #ef4444;">Failed to load vendor scorecard: ${err.message}</div>`;
        }
    }

    function renderVendorScorecard(data) {
        const container = document.getElementById('scorecard-container');
        if (!container) return;

        const valStr = data.total_value ? `$${(data.total_value / 1000).toFixed(0)}k` : '$0';
        const riskPct = Math.round((data.avg_risk_score || 0.25) * 100);

        container.innerHTML = `
            <div class="scorecard-grid">
                <!-- Left: Profile & Key Metrics -->
                <div class="vendor-profile-card">
                    <div class="vendor-title-row">
                        <div class="vendor-avatar">${(data.entity_name || 'V')[0].toUpperCase()}</div>
                        <div>
                            <h3 style="margin: 0; font-size: 1.15rem; color: #f8fafc;">${data.entity_name}</h3>
                            <span style="font-size: 0.75rem; color: #94a3b8;">${data.entity_type.toUpperCase()} • ${data.contract_count} Active Contracts</span>
                        </div>
                    </div>

                    <div class="vendor-kpis">
                        <div class="kpi-tile">
                            <span class="label">Total Value</span>
                            <span class="val">${valStr}</span>
                        </div>
                        <div class="kpi-tile">
                            <span class="label">Avg Risk</span>
                            <span class="val" style="color: ${riskPct > 50 ? '#f87171' : '#34d399'};">${riskPct}%</span>
                        </div>
                        <div class="kpi-tile">
                            <span class="label">Active / Expired</span>
                            <span class="val">${data.active_count} / ${data.expired_count}</span>
                        </div>
                        <div class="kpi-tile">
                            <span class="label">Fulfillment</span>
                            <span class="val" style="color: #38bdf8;">${data.obligation_fulfillment_rate || 96}%</span>
                        </div>
                    </div>

                    <div>
                        <span style="font-size: 0.75rem; color: #94a3b8; font-weight: 600; text-transform: uppercase;">Risk Distribution</span>
                        <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                            <span class="missing-pill" style="background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.4); color: #34d399;">Low: ${data.risk_distribution.low || 0}</span>
                            <span class="missing-pill" style="background: rgba(245, 158, 11, 0.15); border-color: rgba(245, 158, 11, 0.4); color: #fde68a;">Med: ${data.risk_distribution.medium || 0}</span>
                            <span class="missing-pill">High: ${data.risk_distribution.high || 0}</span>
                            <span class="missing-pill" style="background: rgba(225, 29, 72, 0.2); border-color: #f43f5e; color: #ffe4e6;">Crit: ${data.risk_distribution.critical || 0}</span>
                        </div>
                    </div>
                </div>

                <!-- Right: Standard Clause Coverage Breakdown -->
                <div class="coverage-breakdown-card">
                    <h4 style="margin: 0; font-size: 0.95rem; color: #f8fafc;">Standard Clause Coverage (% across contracts)</h4>
                    <div style="display: flex; flex-direction: column; gap: 0.6rem; max-height: 380px; overflow-y: auto; padding-right: 0.5rem;">
                        ${Object.entries(data.clause_coverage || {}).map(([cat, pct]) => `
                            <div class="coverage-row">
                                <span style="color: #cbd5e1; font-weight: 500;">${formatCategoryName(cat)}</span>
                                <div class="coverage-bar-track">
                                    <div class="coverage-bar-fill" style="width: ${pct}%;"></div>
                                </div>
                                <span style="text-align: right; color: #94a3b8; font-weight: 600;">${pct}%</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        `;
    }

    // ─────────────────────────────────────────────────────────────────────────────
    // 4. Benchmark Scoring
    // ─────────────────────────────────────────────────────────────────────────────

    async function loadBenchmark(docId) {
        const container = document.getElementById('benchmark-container');
        if (!container) return;
        if (!docId) {
            container.innerHTML = '<div style="padding: 2rem; text-align: center; color: #94a3b8;">Select a contract to benchmark.</div>';
            return;
        }

        container.innerHTML = '<div style="padding: 2rem; text-align: center; color: #94a3b8;">Evaluating contract against historical portfolio averages...</div>';

        try {
            const resp = await fetch(`/api/v1/intelligence/benchmark/${docId}`);
            if (resp.ok) {
                state.benchmarkData = await resp.json();
                renderBenchmark(state.benchmarkData);
            }
        } catch (err) {
            container.innerHTML = `<div style="padding: 2rem; text-align: center; color: #ef4444;">Failed to benchmark contract: ${err.message}</div>`;
        }
    }

    function renderBenchmark(data) {
        const container = document.getElementById('benchmark-container');
        if (!container) return;

        const p = data.overall_percentile || 50;
        const circumference = 2 * Math.PI * 70;
        const strokeOffset = circumference - (circumference * p) / 100;

        container.innerHTML = `
            <div class="benchmark-layout">
                <!-- Gauge Card -->
                <div class="benchmark-gauge-card">
                    <svg class="gauge-svg" viewBox="0 0 180 180">
                        <defs>
                            <linearGradient id="gauge-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                                <stop offset="0%" stop-color="#6366f1" />
                                <stop offset="100%" stop-color="#10b981" />
                            </linearGradient>
                        </defs>
                        <circle class="gauge-bg" cx="90" cy="90" r="70" />
                        <circle class="gauge-fill" cx="90" cy="90" r="70"
                            stroke-dasharray="${circumference}"
                            stroke-dashoffset="${strokeOffset}"
                            transform="rotate(-90 90 90)" />
                        <text x="90" y="85" text-anchor="middle" font-size="28" font-weight="800" fill="#f8fafc">${p}th</text>
                        <text x="90" y="105" text-anchor="middle" font-size="11" font-weight="600" fill="#94a3b8">PERCENTILE</text>
                    </svg>

                    <div>
                        <h4 style="margin: 0; color: #f8fafc; font-size: 1rem;">Safety & Protection Rank</h4>
                        <p style="margin: 0.25rem 0 0; font-size: 0.75rem; color: #94a3b8;">
                            Higher than ${p}% of comparable historical agreements.
                        </p>
                    </div>

                    <div style="display: flex; gap: 1rem; width: 100%; justify-content: center;">
                        <div class="kpi-tile" style="flex: 1;">
                            <span class="label">Risk Rank</span>
                            <span class="val" style="color: #34d399;">${data.risk_percentile}th</span>
                        </div>
                        <div class="kpi-tile" style="flex: 1;">
                            <span class="label">Coverage</span>
                            <span class="val" style="color: #a5b4fc;">${data.clause_coverage_percentile}th</span>
                        </div>
                    </div>
                </div>

                <!-- Narrative & Comparative Delta Breakdown -->
                <div class="benchmark-details-card">
                    <div class="benchmark-narrative">
                        ${data.comparison_summary}
                    </div>

                    <h4 style="margin: 0; font-size: 0.9rem; color: #f8fafc;">Standard Clause Variance vs. Historical Portfolio</h4>
                    <div style="max-height: 280px; overflow-y: auto;">
                        <table class="delta-table">
                            <thead>
                                <tr>
                                    <th>Clause Category</th>
                                    <th>This Contract</th>
                                    <th>Portfolio Coverage</th>
                                    <th>Assessment</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${Object.entries(data.category_breakdown || {}).map(([cat, delta]) => `
                                    <tr>
                                        <td style="font-weight: 600; color: #f1f5f9;">${formatCategoryName(cat)}</td>
                                        <td>
                                            ${delta.this_contract_present
                                                ? `<span style="color: #34d399; font-weight: 600;">Present (${delta.this_contract_risk || 'low'})</span>`
                                                : '<span style="color: #64748b;">Missing</span>'}
                                        </td>
                                        <td>${delta.portfolio_coverage_pct}%</td>
                                        <td>
                                            <span class="delta-badge ${delta.favorable_delta ? 'favorable' : 'unfavorable'}">
                                                ${delta.favorable_delta ? '✓ Favorable' : '⚠️ Gap vs Portfolio'}
                                            </span>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
    }

    // ─────────────────────────────────────────────────────────────────────────────
    // 5. Portfolio Trends
    // ─────────────────────────────────────────────────────────────────────────────

    async function loadTrends(metric = 'risk', period = 'monthly') {
        state.trendMetric = metric;
        state.trendPeriod = period;

        const container = document.getElementById('trends-container');
        if (!container) return;
        container.innerHTML = '<div style="padding: 2rem; text-align: center; color: #94a3b8;">Computing portfolio trend trajectory...</div>';

        try {
            const resp = await fetch(`/api/v1/intelligence/trends?metric=${metric}&period=${period}`);
            if (resp.ok) {
                state.trendData = await resp.json();
                renderTrends(state.trendData);
            }
        } catch (err) {
            container.innerHTML = `<div style="padding: 2rem; text-align: center; color: #ef4444;">Failed to load trends: ${err.message}</div>`;
        }
    }

    function renderTrends(data) {
        const container = document.getElementById('trends-container');
        if (!container) return;

        const pts = data.data_points || [];
        if (pts.length === 0) {
            container.innerHTML = '<div style="padding: 3rem; text-align: center; color: #94a3b8;">Not enough historical contract data to chart trends.</div>';
            return;
        }

        // Generate SVG polyline coordinates
        const width = 800;
        const height = 200;
        const padding = 40;

        const values = pts.map(p => p.value);
        const minVal = Math.min(...values) * 0.8;
        const maxVal = Math.max(...values) * 1.2 || 1;

        const coords = pts.map((p, idx) => {
            const x = padding + (idx / Math.max(1, pts.length - 1)) * (width - 2 * padding);
            const y = height - padding - ((p.value - minVal) / Math.max(0.001, maxVal - minVal)) * (height - 2 * padding);
            return `${x},${y}`;
        }).join(' ');

        container.innerHTML = `
            <div class="trend-chart-card">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h4 style="margin: 0; font-size: 1rem; color: #f8fafc;">
                            Portfolio ${data.metric.toUpperCase()} Trajectory
                        </h4>
                        <span style="font-size: 0.75rem; color: #94a3b8;">
                            Trend: <strong>${data.trend_direction.toUpperCase()}</strong> (${data.change_pct > 0 ? '+' : ''}${data.change_pct}% delta)
                        </span>
                    </div>

                    <div style="display: flex; gap: 0.5rem;">
                        <button class="intel-tab-btn ${data.metric === 'risk' ? 'active' : ''}" onclick="IntelligenceApp.loadTrends('risk', '${data.period}')">Risk</button>
                        <button class="intel-tab-btn ${data.metric === 'value' ? 'active' : ''}" onclick="IntelligenceApp.loadTrends('value', '${data.period}')">Value</button>
                        <button class="intel-tab-btn ${data.metric === 'compliance' ? 'active' : ''}" onclick="IntelligenceApp.loadTrends('compliance', '${data.period}')">Compliance</button>
                    </div>
                </div>

                <svg class="trend-svg" viewBox="0 0 ${width} ${height}">
                    <defs>
                        <linearGradient id="trend-grad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#6366f1" stop-opacity="0.4" />
                            <stop offset="100%" stop-color="#6366f1" stop-opacity="0.0" />
                        </linearGradient>
                    </defs>
                    <polyline fill="none" stroke="#6366f1" stroke-width="3" points="${coords}" />
                    ${pts.map((p, idx) => {
                        const x = padding + (idx / Math.max(1, pts.length - 1)) * (width - 2 * padding);
                        const y = height - padding - ((p.value - minVal) / Math.max(0.001, maxVal - minVal)) * (height - 2 * padding);
                        return `
                            <circle cx="${x}" cy="${y}" r="5" fill="#a5b4fc" stroke="#1e1b4b" stroke-width="2" />
                            <text x="${x}" y="${height - 10}" text-anchor="middle" font-size="11" fill="#94a3b8">${p.period}</text>
                            <text x="${x}" y="${y - 12}" text-anchor="middle" font-size="11" font-weight="700" fill="#f8fafc">${p.value}</text>
                        `;
                    }).join('')}
                </svg>
            </div>
        `;
    }

    // ─────────────────────────────────────────────────────────────────────────────
    // 6. Gap Detection
    // ─────────────────────────────────────────────────────────────────────────────

    async function loadGaps() {
        const container = document.getElementById('gaps-container');
        if (!container) return;
        container.innerHTML = '<div style="padding: 2rem; text-align: center; color: #94a3b8;">Scanning portfolio for playbook compliance gaps...</div>';

        try {
            let url = '/api/v1/intelligence/gaps';
            if (state.heatmapFilterType && state.heatmapFilterType !== 'all') {
                url += `?contract_type=${state.heatmapFilterType}`;
            }
            const resp = await fetch(url);
            if (resp.ok) {
                state.gapData = await resp.json();
                renderGaps(state.gapData);
            }
        } catch (err) {
            container.innerHTML = `<div style="padding: 2rem; text-align: center; color: #ef4444;">Failed to detect gaps: ${err.message}</div>`;
        }
    }

    function renderGaps(gaps) {
        const container = document.getElementById('gaps-container');
        if (!container) return;

        if (!gaps || gaps.length === 0) {
            container.innerHTML = `
                <div style="padding: 3rem; text-align: center; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 12px; color: #34d399;">
                    ✓ All contracts in the current scope satisfy organizational standard playbook requirements!
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="gap-card-list">
                ${gaps.map(g => `
                    <div class="gap-item-card">
                        <div>
                            <div style="display: flex; align-items: center; gap: 0.5rem;">
                                <span style="font-weight: 700; color: #f8fafc; font-size: 0.95rem;">${g.filename}</span>
                                <span class="missing-pill" style="text-transform: uppercase;">${g.contract_type}</span>
                                <span class="delta-badge unfavorable" style="text-transform: uppercase;">${g.severity} Priority</span>
                            </div>
                            <p style="margin: 0.35rem 0 0; font-size: 0.775rem; color: #94a3b8;">
                                ${g.recommendation}
                            </p>
                            <div class="gap-missing-pills">
                                <span style="font-size: 0.7rem; color: #64748b; margin-right: 0.25rem;">Missing:</span>
                                ${g.missing_clauses.map(c => `<span class="missing-pill">${formatCategoryName(c)}</span>`).join('')}
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    // ─────────────────────────────────────────────────────────────────────────────
    // Modal Helpers
    // ─────────────────────────────────────────────────────────────────────────────

    function showClausePreview(category, excerpt, riskLevel) {
        const modal = document.getElementById('modal-clause-preview');
        if (!modal) return;

        const titleEl = document.getElementById('modal-clause-title');
        const badgeEl = document.getElementById('modal-clause-risk');
        const bodyEl = document.getElementById('modal-clause-body');

        if (titleEl) titleEl.textContent = formatCategoryName(category);
        if (badgeEl) {
            badgeEl.className = `delta-badge ${riskLevel === 'low' ? 'favorable' : 'unfavorable'}`;
            badgeEl.textContent = `Risk: ${riskLevel.toUpperCase()}`;
        }
        if (bodyEl) bodyEl.textContent = excerpt || 'No clause text excerpt available.';

        modal.style.display = 'flex';
    }

    function closeClausePreview() {
        const modal = document.getElementById('modal-clause-preview');
        if (modal) modal.style.display = 'none';
    }

    function formatCategoryName(catKey) {
        if (!catKey) return '';
        return catKey
            .split('_')
            .map(w => w.charAt(0).toUpperCase() + w.slice(1))
            .join(' ');
    }

    return {
        init,
        loadTrends,
        loadScorecard,
        showClausePreview,
        closeClausePreview,
    };
})();

window.IntelligenceApp = IntelligenceApp;
