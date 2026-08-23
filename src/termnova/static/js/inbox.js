/**
 * Termnova Contract Inbox & Smart Triage Frontend Application Controller
 */

class InboxApp {
    constructor() {
        this.currentStatus = "all";
        this.currentType = "all";
        this.currentSort = "urgency_desc";
        this.currentSearch = "";
        this.currentTag = "";
        this.currentPage = 1;
        this.selectedDocIds = new Set();
        this.items = [];
        this.stats = null;
        this.activeDetailDoc = null;
    }

    init() {
        console.log("Initializing Termnova InboxApp...");
        this.bindEvents();
        this.loadData();
        if (window.wsClient && typeof window.wsClient.connectNotifications === "function") {
            window.wsClient.connectNotifications((msg) => {
                if (!msg || !msg.event) return;
                const relevantEvents = [
                    "contract_triaged",
                    "contract_assigned",
                    "contract_acknowledged",
                    "contract_completed",
                    "contract_archived",
                    "contract_tags_updated",
                    "contracts_bulk_assigned",
                    "contracts_bulk_archived"
                ];
                if (relevantEvents.includes(msg.event)) {
                    this.loadData();
                }
            });
        }
    }

    bindEvents() {
        // Status tabs
        document.querySelectorAll(".inbox-tab-btn").forEach(btn => {
            btn.addEventListener("click", (e) => {
                document.querySelectorAll(".inbox-tab-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                this.currentStatus = btn.dataset.status;
                this.currentPage = 1;
                this.selectedDocIds.clear();
                this.updateBulkBar();
                this.fetchItems();
            });
        });

        // Type filter dropdown
        const typeSelect = document.getElementById("inbox-filter-type");
        if (typeSelect) {
            typeSelect.addEventListener("change", (e) => {
                this.currentType = e.target.value;
                this.currentPage = 1;
                this.fetchItems();
            });
        }

        // Sort dropdown
        const sortSelect = document.getElementById("inbox-sort-select");
        if (sortSelect) {
            sortSelect.addEventListener("change", (e) => {
                this.currentSort = e.target.value;
                this.fetchItems();
            });
        }

        // Search input
        const searchInput = document.getElementById("inbox-search-input");
        if (searchInput) {
            let debounceTimer;
            searchInput.addEventListener("input", (e) => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    this.currentSearch = e.target.value.trim();
                    this.currentPage = 1;
                    this.fetchItems();
                }, 300);
            });
        }

        // Rules modal trigger
        const rulesBtn = document.getElementById("btn-inbox-rules");
        if (rulesBtn) {
            rulesBtn.addEventListener("click", () => this.openRulesModal());
        }

        // Detail drawer close
        const drawerClose = document.getElementById("inbox-drawer-close");
        const drawerOverlay = document.getElementById("inbox-drawer-overlay");
        if (drawerClose) drawerClose.addEventListener("click", () => this.closeDetail());
        if (drawerOverlay) drawerOverlay.addEventListener("click", () => this.closeDetail());

        // Bulk action buttons
        const bulkAssignBtn = document.getElementById("btn-bulk-assign");
        if (bulkAssignBtn) {
            bulkAssignBtn.addEventListener("click", () => this.handleBulkAssign());
        }
        const bulkArchiveBtn = document.getElementById("btn-bulk-archive");
        if (bulkArchiveBtn) {
            bulkArchiveBtn.addEventListener("click", () => this.handleBulkArchive());
        }
    }

    async loadData() {
        await Promise.all([this.fetchStats(), this.fetchItems()]);
    }

    async fetchStats() {
        try {
            const res = await fetch("/api/v1/inbox/stats");
            if (!res.ok) return;
            this.stats = await res.json();
            this.renderStats(this.stats);
        } catch (err) {
            console.error("Failed to load inbox stats:", err);
        }
    }

    renderStats(stats) {
        if (!stats) return;
        const unreviewedEl = document.getElementById("stat-unreviewed-val");
        const progressEl = document.getElementById("stat-progress-val");
        const urgentEl = document.getElementById("stat-urgent-val");
        const completedEl = document.getElementById("stat-completed-val");
        const navBadgeEl = document.getElementById("inbox-nav-badge");

        if (unreviewedEl) unreviewedEl.textContent = stats.unreviewed_count || 0;
        if (progressEl) progressEl.textContent = stats.in_progress_count || 0;
        if (urgentEl) urgentEl.textContent = stats.high_urgency_count || 0;
        if (completedEl) completedEl.textContent = stats.completed_count || 0;

        if (navBadgeEl) {
            if (stats.unreviewed_count > 0) {
                navBadgeEl.textContent = stats.unreviewed_count;
                navBadgeEl.style.display = "inline-flex";
            } else {
                navBadgeEl.style.display = "none";
            }
        }

        // Update tab badge counts
        const allTabBadge = document.getElementById("tab-badge-all");
        const unrevTabBadge = document.getElementById("tab-badge-unreviewed");
        const progTabBadge = document.getElementById("tab-badge-progress");
        const compTabBadge = document.getElementById("tab-badge-completed");

        if (allTabBadge) allTabBadge.textContent = stats.total_count || 0;
        if (unrevTabBadge) unrevTabBadge.textContent = stats.unreviewed_count || 0;
        if (progTabBadge) progTabBadge.textContent = stats.in_progress_count || 0;
        if (compTabBadge) compTabBadge.textContent = stats.completed_count || 0;
    }

    async fetchItems() {
        const feedContainer = document.getElementById("inbox-list-feed");
        if (!feedContainer) return;

        feedContainer.innerHTML = `<div style="text-align:center; padding: 2rem; color: #94a3b8;"><div class="spinner"></div> Loading triage inbox...</div>`;

        try {
            const params = new URLSearchParams({
                status: this.currentStatus,
                type: this.currentType,
                sort: this.currentSort,
                page: this.currentPage,
                page_size: 25,
            });
            if (this.currentSearch) params.append("search", this.currentSearch);
            if (this.currentTag) params.append("tag", this.currentTag);

            const res = await fetch(`/api/v1/inbox/?${params.toString()}`);
            if (!res.ok) throw new Error("Failed to fetch inbox items");

            const data = await res.json();
            this.items = data.items || [];
            this.renderItems(this.items, data.total_count);
        } catch (err) {
            feedContainer.innerHTML = `<div style="text-align:center; padding: 2rem; color: #f43f5e;">⚠️ Error loading contracts: ${this.escapeHtml(err.message)}</div>`;
        }
    }

    renderItems(items, totalCount) {
        const feedContainer = document.getElementById("inbox-list-feed");
        if (!feedContainer) return;

        if (!items || items.length === 0) {
            feedContainer.innerHTML = `
                <div class="empty-state" style="text-align: center; padding: 3rem 1rem; border: 1px dashed var(--rule); background: var(--sheet);">
                    <h3 style="font-family: var(--font-display); color: var(--on-paper); margin-bottom: 0.35rem;">Nothing waiting</h3>
                    <p style="font-size: 0.9rem; color: var(--on-paper-muted);">Add a contract in Library, or widen the filters.</p>
                </div>
            `;
            return;
        }

        feedContainer.innerHTML = items.map(item => this.renderCardHtml(item)).join("");

        // Attach card interaction listeners
        items.forEach(item => {
            const card = document.getElementById(`inbox-card-${item.document_id}`);
            if (card) {
                card.addEventListener("click", (e) => {
                    if (e.target.closest("input[type='checkbox']") || e.target.closest("button")) return;
                    this.openDetail(item.document_id);
                });
            }

            const checkbox = document.getElementById(`inbox-chk-${item.document_id}`);
            if (checkbox) {
                checkbox.addEventListener("change", (e) => {
                    if (e.target.checked) {
                        this.selectedDocIds.add(item.document_id);
                    } else {
                        this.selectedDocIds.delete(item.document_id);
                    }
                    this.updateBulkBar();
                });
            }
        });
    }

    renderCardHtml(item) {
        const isSelected = this.selectedDocIds.has(item.document_id);
        const urgencyClass = item.urgency_score >= 75 ? "urgency-high" : (item.urgency_score >= 40 ? "urgency-med" : "urgency-low");
        const urgencyPillClass = item.urgency_score >= 75 ? "urgency-pill-high" : (item.urgency_score >= 40 ? "urgency-pill-med" : "urgency-pill-low");
        const typeBadgeClass = `badge-${item.contract_type || 'other'}`;

        const tagsHtml = (item.auto_tags || []).slice(0, 4).map(t => {
            const tagClass = t.includes("urgent") ? "urgent" : (t.includes("high-value") ? "high-value" : (t.includes("legal") ? "requires-legal" : ""));
            return `<span class="inbox-tag-pill ${tagClass}">#${this.escapeHtml(t)}</span>`;
        }).join("");

        const formatMd = window.formatMarkdownText || ((t) => this.escapeHtml(t));
        const formatTitle = window.formatContractTitle || ((t) => t);
        const cleanTitle = formatTitle(item.filename);

        const bulletsHtml = (item.summary_bullets || []).slice(0, 3).map(b => `<li>${formatMd(b)}</li>`).join("");

        const timeStr = this.formatDate(item.triaged_at);
        const assigneeStr = item.assigned_to ? this.escapeHtml(item.assigned_to) : "<span style='color:#64748b; font-style:italic;'>Unassigned</span>";

        return `
            <div class="inbox-card ${urgencyClass}" id="inbox-card-${item.document_id}">
                <div class="inbox-card-top">
                    <div class="inbox-card-left">
                        <input type="checkbox" class="inbox-card-select" id="inbox-chk-${item.document_id}" ${isSelected ? 'checked' : ''}>
                        <div class="inbox-card-title-group">
                            <div class="inbox-card-title">
                                <span>${this.escapeHtml(cleanTitle)}</span>
                                <span class="inbox-type-badge ${typeBadgeClass}">${this.escapeHtml(item.contract_type)}</span>
                            </div>
                            <div class="inbox-card-subtitle">${this.escapeHtml(item.filename)}</div>
                        </div>
                    </div>
                    <div class="inbox-card-right">
                        <span class="inbox-urgency-pill ${urgencyPillClass}">
                            ${item.urgency_score}/100 how soon
                        </span>
                        <span style="font-size: 0.75rem; color: #64748b;">${timeStr}</span>
                    </div>
                </div>

                <div class="inbox-card-body">
                    <div class="inbox-summary-preview">
                        <strong>Action:</strong> ${formatMd(item.action_required || "Review agreement terms")}
                    </div>
                    ${bulletsHtml ? `<ul class="inbox-summary-bullets">${bulletsHtml}</ul>` : ''}
                </div>

                <div class="inbox-card-bottom">
                    <div class="inbox-tags-list">
                        ${tagsHtml}
                        <span style="font-size: 0.75rem; color: #94a3b8; margin-left: 0.5rem;">👤 ${assigneeStr}</span>
                    </div>
                    <div class="inbox-card-actions">
                        ${item.inbox_status === 'unreviewed' ? `<button class="inbox-action-btn" onclick="window.inboxApp.acknowledge('${item.document_id}')">👁️ Acknowledge</button>` : ''}
                        <button class="inbox-action-btn" onclick="window.inboxApp.promptAssign('${item.document_id}')">👤 Assign</button>
                        ${item.inbox_status !== 'completed' ? `<button class="inbox-action-btn" onclick="window.inboxApp.complete('${item.document_id}')">✅ Complete</button>` : ''}
                        <button class="inbox-action-btn" onclick="window.inboxApp.openDetail('${item.document_id}')">Open</button>
                    </div>
                </div>
            </div>
        `;
    }

    updateBulkBar() {
        const bulkBar = document.getElementById("inbox-bulk-bar");
        const countEl = document.getElementById("bulk-selected-count");
        if (!bulkBar || !countEl) return;

        const count = this.selectedDocIds.size;
        if (count > 0) {
            bulkBar.classList.add("visible");
            countEl.textContent = count;
        } else {
            bulkBar.classList.remove("visible");
        }
    }

    async openDetail(docId) {
        const item = this.items.find(i => i.document_id === docId);
        if (!item) return;

        this.activeDetailDoc = item;
        const drawer = document.getElementById("inbox-drawer");
        const overlay = document.getElementById("inbox-drawer-overlay");
        const titleEl = document.getElementById("drawer-doc-title");
        const bodyEl = document.getElementById("drawer-content-body");

        const formatMd = window.formatMarkdownText || ((t) => this.escapeHtml(t));
        const formatTitle = window.formatContractTitle || ((t) => t);
        const cleanTitle = formatTitle(item.filename);

        if (titleEl) {
            titleEl.innerHTML = `
                <div>${this.escapeHtml(cleanTitle)}</div>
                <div style="font-size: 0.72rem; color: #64748b; font-family: var(--font-mono); font-weight: normal; margin-top: 2px;">${this.escapeHtml(item.filename)}</div>
            `;
        }

        if (bodyEl) {
            const bulletsHtml = (item.summary_bullets || []).map(b => `<li style="margin-bottom: 0.5rem; line-height: 1.5;">${formatMd(b)}</li>`).join("");
            const factors = item.urgency_factors || {};

            bodyEl.innerHTML = `
                <div class="drawer-section">
                    <div class="drawer-section-title">Classification & Status</div>
                    <div style="display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap;">
                        <span class="inbox-type-badge badge-${item.contract_type}">${item.contract_type.toUpperCase()}</span>
                        <span style="font-size: 0.8rem; color: #94a3b8;">Confidence: ${(item.type_confidence * 100).toFixed(0)}%</span>
                        <span style="font-size: 0.8rem; color: #60a5fa;">Status: <strong>${item.inbox_status}</strong></span>
                        <span style="font-size: 0.8rem; color: #cbd5e1;">Assignee: <strong>${item.assigned_to || 'None'}</strong></span>
                    </div>
                </div>

                <div class="drawer-section">
                    <div class="drawer-section-title">Urgency Score Breakdown (Score: ${item.urgency_score}/100)</div>
                    <div class="urgency-breakdown-card">
                        <div class="factor-row">
                            <span>📅 Deadline Proximity</span>
                            <span class="factor-pts">${factors.deadline_proximity ? factors.deadline_proximity.points : 0}/25 pts</span>
                        </div>
                        <div class="factor-row">
                            <span>💰 Contract Financial Value</span>
                            <span class="factor-pts">${factors.contract_value ? factors.contract_value.points : 0}/25 pts</span>
                        </div>
                        <div class="factor-row">
                            <span>⚠️ Risk Signals Severity</span>
                            <span class="factor-pts">${factors.risk_signals ? factors.risk_signals.points : 0}/25 pts</span>
                        </div>
                        <div class="factor-row">
                            <span>📑 Contract Type Complexity</span>
                            <span class="factor-pts">${factors.contract_type_weight ? factors.contract_type_weight.points : 0}/25 pts</span>
                        </div>
                    </div>
                </div>

                <div class="drawer-section">
                    <div class="drawer-section-title">Executive AI Summary</div>
                    <ul style="padding-left: 1.25rem; font-size: 0.85rem; color: #cbd5e1; line-height: 1.6;">
                        ${bulletsHtml}
                    </ul>
                </div>

                <div class="drawer-section">
                    <div class="drawer-section-title">Recommended Action</div>
                    <div style="background: rgba(99,102,241,0.1); border-left: 3px solid #6366f1; padding: 0.75rem; border-radius: 4px; font-size: 0.85rem; color: #e0e7ff; line-height: 1.5;">
                        💡 ${formatMd(item.action_required || "Standard Legal Review")}
                    </div>
                </div>

                <div class="drawer-section">
                    <div class="drawer-section-title">Tags & Routing Signals</div>
                    <div style="display: flex; gap: 0.4rem; flex-wrap: wrap;">
                        ${(item.auto_tags || []).map(t => `<span class="inbox-tag-pill">#${this.escapeHtml(t)}</span>`).join("")}
                    </div>
                </div>
            `;
        }

        if (drawer) drawer.classList.add("open");
        if (overlay) overlay.classList.add("open");
    }

    closeDetail() {
        const drawer = document.getElementById("inbox-drawer");
        const overlay = document.getElementById("inbox-drawer-overlay");
        if (drawer) drawer.classList.remove("open");
        if (overlay) overlay.classList.remove("open");
        this.activeDetailDoc = null;
    }

    async acknowledge(docId) {
        try {
            const res = await fetch(`/api/v1/inbox/${docId}/acknowledge`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ acknowledged_by: "Current User" }),
            });
            if (res.ok) {
                await this.loadData();
            }
        } catch (err) {
            console.error("Failed to acknowledge contract:", err);
        }
    }

    async promptAssign(docId) {
        const assignee = prompt("Enter reviewer name or email to assign:");
        if (!assignee || !assignee.trim()) return;

        try {
            const res = await fetch(`/api/v1/inbox/${docId}/assign`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ assigned_to: assignee.trim() }),
            });
            if (res.ok) {
                await this.loadData();
            }
        } catch (err) {
            console.error("Failed to assign contract:", err);
        }
    }

    async complete(docId) {
        try {
            const res = await fetch(`/api/v1/inbox/${docId}/complete`, { method: "POST" });
            if (res.ok) {
                await this.loadData();
            }
        } catch (err) {
            console.error("Failed to complete contract:", err);
        }
    }

    async archive(docId) {
        try {
            const res = await fetch(`/api/v1/inbox/${docId}/archive`, { method: "POST" });
            if (res.ok) {
                await this.loadData();
            }
        } catch (err) {
            console.error("Failed to archive contract:", err);
        }
    }

    async handleBulkAssign() {
        const docIds = Array.from(this.selectedDocIds);
        if (docIds.length === 0) return;

        const assignee = prompt(`Assign ${docIds.length} contracts to:`);
        if (!assignee || !assignee.trim()) return;

        try {
            const res = await fetch("/api/v1/inbox/bulk-assign", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ document_ids: docIds, assigned_to: assignee.trim() }),
            });
            if (res.ok) {
                this.selectedDocIds.clear();
                this.updateBulkBar();
                await this.loadData();
            }
        } catch (err) {
            console.error("Bulk assign failed:", err);
        }
    }

    async handleBulkArchive() {
        const docIds = Array.from(this.selectedDocIds);
        if (docIds.length === 0) return;

        if (!confirm(`Archive ${docIds.length} selected contracts?`)) return;

        try {
            const res = await fetch("/api/v1/inbox/bulk-archive", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ document_ids: docIds }),
            });
            if (res.ok) {
                this.selectedDocIds.clear();
                this.updateBulkBar();
                await this.loadData();
            }
        } catch (err) {
            console.error("Bulk archive failed:", err);
        }
    }

    openRulesModal() {
        const modal = document.getElementById("inbox-rules-modal");
        if (modal) {
            modal.style.display = "flex";
            this.loadRules();
        }
    }

    closeRulesModal() {
        const modal = document.getElementById("inbox-rules-modal");
        if (modal) modal.style.display = "none";
    }

    async loadRules() {
        const listEl = document.getElementById("rules-list-container");
        if (!listEl) return;

        listEl.innerHTML = `<div style="text-align: center; color: #94a3b8;">Loading routing rules...</div>`;
        try {
            const res = await fetch("/api/v1/triage/rules/");
            if (!res.ok) return;
            const rules = await res.json();
            if (rules.length === 0) {
                listEl.innerHTML = `<div style="color: #64748b; font-size: 0.85rem;">No routing rules configured. Create one below.</div>`;
                return;
            }

            listEl.innerHTML = rules.map(r => `
                <div style="background: rgba(15,23,42,0.6); padding: 0.75rem; border-radius: 8px; margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center; border: 1px solid rgba(255,255,255,0.08);">
                    <div>
                        <div style="font-weight: 600; color: #f8fafc; font-size: 0.88rem;">${this.escapeHtml(r.name)} <span style="font-size: 0.72rem; color: #818cf8;">(Priority ${r.priority})</span></div>
                        <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 0.2rem;">Condition: <code>${this.escapeHtml(JSON.stringify(r.condition))}</code> → Action: <code>${this.escapeHtml(JSON.stringify(r.action))}</code></div>
                    </div>
                    <button style="background: rgba(244,63,94,0.15); border: 1px solid rgba(244,63,94,0.3); color: #f43f5e; padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer;" onclick="window.inboxApp.deleteRule('${r.id}')">Delete</button>
                </div>
            `).join("");
        } catch (err) {
            listEl.innerHTML = `<div style="color: #f43f5e;">Error loading rules</div>`;
        }
    }

    async saveNewRule() {
        const nameInput = document.getElementById("new-rule-name");
        const typeInput = document.getElementById("new-rule-type");
        const urgencyInput = document.getElementById("new-rule-urgency");
        const assignInput = document.getElementById("new-rule-assign");
        const prioInput = document.getElementById("new-rule-priority");

        if (!nameInput || !nameInput.value.trim()) {
            alert("Please enter a rule name");
            return;
        }

        const condition = {};
        if (typeInput && typeInput.value) condition["contract_type"] = typeInput.value;
        if (urgencyInput && urgencyInput.value) condition["urgency_min"] = parseInt(urgencyInput.value, 10);

        const action = {};
        if (assignInput && assignInput.value.trim()) action["assign_to"] = assignInput.value.trim();

        try {
            const res = await fetch("/api/v1/triage/rules/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: nameInput.value.trim(),
                    condition: condition,
                    action: action,
                    priority: prioInput ? parseInt(prioInput.value, 10) : 100,
                    is_active: true,
                }),
            });
            if (res.ok) {
                nameInput.value = "";
                if (assignInput) assignInput.value = "";
                await this.loadRules();
            }
        } catch (err) {
            console.error("Failed to save rule:", err);
        }
    }

    async deleteRule(ruleId) {
        if (!confirm("Deactivate this rule?")) return;
        try {
            await fetch(`/api/v1/triage/rules/${ruleId}`, { method: "DELETE" });
            await this.loadRules();
        } catch (err) {
            console.error("Failed to delete rule:", err);
        }
    }

    formatDate(dateStr) {
        if (!dateStr) return "";
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
        } catch (e) {
            return dateStr;
        }
    }

    escapeHtml(text) {
        if (!text) return "";
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
}

// Global instance
window.inboxApp = new InboxApp();
document.addEventListener("DOMContentLoaded", () => {
    try {
        window.inboxApp.init();
    } catch (err) {
        console.error("Inbox module failed to start", err);
    }
});
