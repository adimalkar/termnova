/**
 * Termnova Collaborative Workspace & Shared Team Chat Client
 */

(function () {
  "use strict";

  const WorkspaceApp = {
    currentWorkspaceId: null,
    workspaces: [],
    currentMessages: [],
    pinnedMessages: [],
    scopedDocs: [],
    members: [],
    currentUserName: (window.getDeskActor && window.getDeskActor()) || "Counsel",
    inputMode: "ai", // 'ai' or 'team'
    typingTimer: null,
    availableDocs: [],
    eventsBound: false,

    init() {
      this.currentUserName = (window.getDeskActor && window.getDeskActor()) || this.currentUserName;
      this.bindEvents();
      this.fetchAvailableDocuments();
      this.fetchWorkspaces();
      this.setupWebSocketListener();
    },

    bindEvents() {
      if (this.eventsBound) return;
      this.eventsBound = true;
      // Room Search Filter
      const searchInput = document.getElementById("ws-search-input");
      if (searchInput) {
        searchInput.addEventListener("input", (e) => this.filterRooms(e.target.value));
      }

      // Create Room Modal
      const openCreateBtn = document.getElementById("btn-open-create-room");
      const closeCreateBtn = document.getElementById("btn-close-create-modal");
      const modalCreate = document.getElementById("modal-create-workspace");
      const createForm = document.getElementById("form-create-workspace");

      if (openCreateBtn && modalCreate) {
        openCreateBtn.addEventListener("click", () => {
          this.populateDocChecklist();
          modalCreate.style.display = "flex";
        });
      }

      if (closeCreateBtn && modalCreate) {
        closeCreateBtn.addEventListener("click", () => {
          modalCreate.style.display = "none";
        });
      }

      if (createForm) {
        createForm.addEventListener("submit", (e) => this.handleCreateWorkspace(e));
      }

      // Input Mode Toggle
      const modeTeamBtn = document.getElementById("ws-mode-team");
      const modeAiBtn = document.getElementById("ws-mode-ai");

      if (modeTeamBtn && modeAiBtn) {
        modeTeamBtn.addEventListener("click", () => this.setInputMode("team"));
        modeAiBtn.addEventListener("click", () => this.setInputMode("ai"));
      }

      // Message Input Form
      const chatForm = document.getElementById("ws-chat-form");
      const chatTextarea = document.getElementById("ws-chat-input");

      if (chatForm) {
        chatForm.addEventListener("submit", (e) => this.handleSendMessage(e));
      }

      if (chatTextarea) {
        chatTextarea.addEventListener("keydown", (e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event("submit"));
          } else {
            this.handleTyping();
          }
        });
      }

      // Invite Member Modal
      const inviteBtn = document.getElementById("btn-invite-member");
      const modalInvite = document.getElementById("modal-invite-member");
      const closeInviteBtn = document.getElementById("btn-close-invite-modal");
      const inviteForm = document.getElementById("form-invite-member");

      if (inviteBtn && modalInvite) {
        inviteBtn.addEventListener("click", () => {
          modalInvite.style.display = "flex";
        });
      }

      if (closeInviteBtn && modalInvite) {
        closeInviteBtn.addEventListener("click", () => {
          modalInvite.style.display = "none";
        });
      }

      if (inviteForm) {
        inviteForm.addEventListener("submit", (e) => this.handleInviteMember(e));
      }
    },

    setupWebSocketListener() {
      // Connect or reuse notification WebSocket
      if (window.notificationsWs && window.notificationsWs.readyState === WebSocket.OPEN) {
        this.attachWsHandler(window.notificationsWs);
      } else {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws/notifications`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log("Workspace WebSocket connected");
          if (this.currentWorkspaceId) {
            ws.send(JSON.stringify({ action: "join_workspace", workspace_id: this.currentWorkspaceId }));
          }
        };

        this.attachWsHandler(ws);
        window.notificationsWs = ws;
      }
    },

    attachWsHandler(ws) {
      ws.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(event.data);
          this.handleRealtimeEvent(payload);
        } catch (e) {
          // Plain text messages like pong
        }
      });
    },

    handleRealtimeEvent(event) {
      if (!event || !event.event) return;

      switch (event.event) {
        case "workspace_message":
          if (event.data && event.data.workspace_id === this.currentWorkspaceId) {
            this.appendMessage(event.data);
          }
          break;

        case "workspace_ai_thinking":
          if (event.data && event.data.workspace_id === this.currentWorkspaceId) {
            this.showAiThinking(event.data.user_name);
          }
          break;

        case "workspace_query_completed":
          if (event.data) {
            this.removeAiThinking();
            if (event.data.human_message && event.data.human_message.workspace_id === this.currentWorkspaceId) {
              // Ensure not duplicated
              if (!this.currentMessages.some((m) => m.id === event.data.human_message.id)) {
                this.appendMessage(event.data.human_message);
              }
            }
            if (event.data.ai_response && event.data.ai_response.workspace_id === this.currentWorkspaceId) {
              if (!this.currentMessages.some((m) => m.id === event.data.ai_response.id)) {
                this.appendMessage(event.data.ai_response);
              }
            }
          }
          break;

        case "message_updated":
          if (event.data && event.data.workspace_id === this.currentWorkspaceId) {
            this.updateMessageInFeed(event.data);
            this.fetchPinnedFindings();
          }
          break;

        case "user_typing":
          if (event.data && event.data.workspace_id === this.currentWorkspaceId) {
            if (event.data.user_name !== this.currentUserName) {
              this.showUserTyping(event.data.user_name);
            }
          }
          break;

        case "member_joined":
          if (event.data && event.data.workspace_id === this.currentWorkspaceId) {
            this.fetchWorkspaceDetail(this.currentWorkspaceId);
          }
          break;
      }
    },

    setInputMode(mode) {
      this.inputMode = mode;
      const modeTeamBtn = document.getElementById("ws-mode-team");
      const modeAiBtn = document.getElementById("ws-mode-ai");
      const placeholder = document.getElementById("ws-chat-input");

      if (mode === "ai") {
        modeAiBtn?.classList.add("active");
        modeTeamBtn?.classList.remove("active");
        if (placeholder) placeholder.placeholder = "Ask only about the contracts in this room";
      } else {
        modeTeamBtn?.classList.add("active");
        modeAiBtn?.classList.remove("active");
        if (placeholder) placeholder.placeholder = "Write to the people in this room";
      }
    },

    async fetchAvailableDocuments() {
      try {
        const res = await fetch("/api/v1/documents/");
        if (res.ok) {
          const data = await res.json();
          this.availableDocs = Array.isArray(data) ? data : data.documents || [];
        }
      } catch (err) {
        console.warn("Could not load documents for workspace scope:", err);
      }
    },

    populateDocChecklist() {
      const container = document.getElementById("ws-doc-checklist-container");
      if (!container) return;

      if (!this.availableDocs || this.availableDocs.length === 0) {
        container.innerHTML = `<div style="font-size:0.8rem; color:#64748b; padding:0.5rem;">No documents in vault yet. Upload contracts in Document Vault.</div>`;
        return;
      }

      container.innerHTML = this.availableDocs
        .map(
          (doc) => `
        <label class="ws-doc-check-item">
          <input type="checkbox" name="doc_scope" value="${doc.id}">
          <span>${this.escapeHtml(doc.filename)} <small style="color:#64748b;">(${doc.page_count || 1} pages)</small></span>
        </label>
      `
        )
        .join("");
    },

    async fetchWorkspaces() {
      try {
        const actor = encodeURIComponent(this.currentUserName);
        this.workspaces = await apiRequest(`/api/v1/workspaces/?user_name=${actor}`);
        this.renderRoomsList();

        if (this.workspaces.length > 0) {
          if (!this.currentWorkspaceId || !this.workspaces.some((w) => w.id === this.currentWorkspaceId)) {
            this.selectWorkspace(this.workspaces[0].id);
          }
        } else {
          this.createDefaultWorkspace();
        }
      } catch (err) {
        console.error("Error fetching workspaces:", err);
      }
    },

    async createDefaultWorkspace() {
      try {
        const docIds = this.availableDocs.slice(0, 3).map((d) => d.id);
        const newWs = await apiRequest("/api/v1/workspaces/", {
          method: "POST",
          body: JSON.stringify({
            name: "General Deal Room",
            description: "Questions here only search the contracts attached to this room",
            document_scope: docIds,
            created_by: this.currentUserName,
          }),
        });
        this.workspaces = [newWs];
        this.renderRoomsList();
        this.selectWorkspace(newWs.id);
      } catch (e) {
        console.error("Failed creating default workspace:", e);
      }
    },

    renderRoomsList(filteredRooms = null) {
      const container = document.getElementById("ws-rooms-list");
      if (!container) return;

      const list = filteredRooms || this.workspaces;

      if (!list || list.length === 0) {
        container.innerHTML = `
          <div style="padding: 1.5rem 1rem; text-align: center; color: #64748b; font-size: 0.85rem;">
            No workspaces found.<br>Click <strong>+ Room</strong> to start.
          </div>
        `;
        return;
      }

      container.innerHTML = list
        .map(
          (ws) => `
        <div class="ws-room-card ${ws.id === this.currentWorkspaceId ? "active" : ""}" data-id="${ws.id}">
          <div class="ws-room-top">
            <span class="ws-room-name">${this.escapeHtml(ws.name)}</span>
            <span class="ws-meta-pill" title="Documents attached">📄 ${ws.document_count || (ws.document_scope || []).length}</span>
          </div>
          <div class="ws-room-desc">${this.escapeHtml(ws.description || "Shared deal room")}</div>
          <div class="ws-room-meta">
            <span>👥 ${ws.member_count || 1} members</span>
            <span>💬 ${ws.message_count || 0} msgs</span>
          </div>
        </div>
      `
        )
        .join("");

      // Bind click on room cards
      container.querySelectorAll(".ws-room-card").forEach((card) => {
        card.addEventListener("click", () => {
          const wsId = card.getAttribute("data-id");
          this.selectWorkspace(wsId);
        });
      });
    },

    filterRooms(query) {
      if (!query || !query.trim()) {
        this.renderRoomsList();
        return;
      }
      const q = query.toLowerCase().trim();
      const filtered = this.workspaces.filter(
        (w) => w.name.toLowerCase().includes(q) || (w.description && w.description.toLowerCase().includes(q))
      );
      this.renderRoomsList(filtered);
    },

    async selectWorkspace(workspaceId) {
      if (this.currentWorkspaceId === workspaceId && this.currentMessages.length > 0) return;

      // Leave previous channel
      if (window.notificationsWs && window.notificationsWs.readyState === WebSocket.OPEN) {
        if (this.currentWorkspaceId) {
          window.notificationsWs.send(
            JSON.stringify({ action: "leave_workspace", workspace_id: this.currentWorkspaceId })
          );
        }
        window.notificationsWs.send(JSON.stringify({ action: "join_workspace", workspace_id: workspaceId }));
      }

      this.currentWorkspaceId = workspaceId;
      this.renderRoomsList();

      await Promise.all([
        this.fetchWorkspaceDetail(workspaceId),
        this.fetchMessages(workspaceId),
        this.fetchPinnedFindings(workspaceId),
      ]);
    },

    async fetchWorkspaceDetail(workspaceId) {
      try {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}`);
        if (res.ok) {
          const detail = await res.json();
          this.scopedDocs = detail.scoped_documents || [];
          this.members = detail.members || [];
          this.renderHeader(detail);
          this.renderScopedDocsSidebar();
        }
      } catch (e) {
        console.error("Error fetching workspace details:", e);
      }
    },

    renderHeader(ws) {
      const titleEl = document.getElementById("ws-active-title");
      const descEl = document.getElementById("ws-active-desc");
      const avatarStack = document.getElementById("ws-members-stack");

      if (titleEl) titleEl.textContent = ws.name;
      if (descEl) descEl.textContent = ws.description || "Multi-party contract Q&A";

      if (avatarStack) {
        const memberList = this.members || [{ user_name: ws.created_by }];
        avatarStack.innerHTML = memberList
          .slice(0, 4)
          .map((m) => {
            const initial = (m.user_name || "U").charAt(0).toUpperCase();
            return `<div class="ws-avatar-pill" title="${this.escapeHtml(m.user_name)} (${m.role || "member"})">${initial}</div>`;
          })
          .join("");

        if (memberList.length > 4) {
          avatarStack.innerHTML += `<div class="ws-avatar-pill ws-avatar-more">+${memberList.length - 4}</div>`;
        }
      }
    },

    renderScopedDocsSidebar() {
      const container = document.getElementById("ws-scoped-docs-list");
      if (!container) return;

      if (!this.scopedDocs || this.scopedDocs.length === 0) {
        container.innerHTML = `<div style="font-size:0.75rem; color:#64748b;">No documents assigned to this scope.</div>`;
        return;
      }

      container.innerHTML = this.scopedDocs
        .map(
          (doc) => `
        <div class="ws-scoped-doc-item">
          <span style="font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:180px;">
            📄 ${this.escapeHtml(doc.filename)}
          </span>
          <span class="badge" style="font-size:0.65rem;">${doc.contract_type || "Contract"}</span>
        </div>
      `
        )
        .join("");
    },

    async fetchMessages(workspaceId) {
      const feed = document.getElementById("ws-chat-feed");
      if (feed) {
        feed.innerHTML = `<div class="empty-state" style="text-align:center; padding:2rem;">Loading this room…</div>`;
      }

      try {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}/messages`);
        if (res.ok) {
          this.currentMessages = await res.json();
          this.renderMessagesFeed();
        }
      } catch (e) {
        console.error("Error fetching messages:", e);
      }
    },

    renderMessagesFeed() {
      const feed = document.getElementById("ws-chat-feed");
      if (!feed) return;

      if (!this.currentMessages || this.currentMessages.length === 0) {
        feed.innerHTML = `
          <div class="empty-state" style="text-align: center; padding: 3rem 1rem;">
            <h4 style="font-family: var(--font-display); color: var(--on-paper); margin: 0 0 0.5rem 0;">Nothing in this room yet</h4>
            <p style="font-size: 0.9rem; max-width: 360px; margin: 0 auto; color: var(--on-paper-muted);">
              Write to the people here, or switch to <strong>Ask the contracts</strong> to search only the files attached to this room.
            </p>
          </div>
        `;
        return;
      }

      feed.innerHTML = this.currentMessages.map((m) => this.renderSingleMessageHtml(m)).join("");
      this.bindMessageActionEvents();
      this.scrollToBottom();
    },

    renderSingleMessageHtml(msg) {
      const isAi = msg.message_type === "ai_response";
      const author = isAi ? "Termnova AI" : msg.user_name || "Team Member";
      const initial = isAi ? "AI" : author.charAt(0).toUpperCase();
      const timeStr = msg.created_at ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";

      // Citations HTML
      let citationsHtml = "";
      if (msg.citations && msg.citations.length > 0) {
        citationsHtml = `
          <div class="ws-citation-chips">
            ${msg.citations
              .map(
                (c) => `
              <div class="ws-citation-chip" data-doc="${this.escapeHtml(c.document_name)}" data-page="${c.page_number || 1}" title="${this.escapeHtml(c.snippet || '')}">
                <span>📎 [Src ${c.source_id}]</span>
                <span>${this.escapeHtml(c.document_name)} (p.${c.page_number || 1})</span>
              </div>
            `
              )
              .join("")}
          </div>
        `;
      }

      // Reactions HTML
      let reactionsHtml = "";
      const reactions = msg.reactions || {};
      for (const [emoji, users] of Object.entries(reactions)) {
        if (users && users.length > 0) {
          const isUserReacted = users.includes(this.currentUserName);
          reactionsHtml += `
            <button class="ws-reaction-pill ${isUserReacted ? "reacted" : ""}" data-msg-id="${msg.id}" data-emoji="${emoji}" title="${this.escapeHtml(users.join(", "))}">
              <span>${emoji}</span>
              <span>${users.length}</span>
            </button>
          `;
        }
      }

      return `
        <div class="ws-msg-row ${isAi ? "ai-msg" : "human-msg"}" id="msg-${msg.id}">
          <div class="ws-msg-avatar ${isAi ? "ai" : "human"}">${initial}</div>
          <div class="ws-msg-body">
            <div class="ws-msg-meta">
              <span class="ws-msg-author">${this.escapeHtml(author)}</span>
              ${isAi ? `<span class="ws-ai-badge">From the contracts</span>` : ""}
              <span class="ws-msg-time">${timeStr}</span>
            </div>
            <div class="ws-msg-bubble">
              ${this.formatMarkdown(msg.content)}
              ${citationsHtml}
            </div>
            <div class="ws-msg-footer">
              ${reactionsHtml}
              <button class="ws-btn-icon-action btn-add-reaction" data-msg-id="${msg.id}" title="Add reaction">😀+</button>
              <button class="ws-btn-icon-action btn-toggle-pin ${msg.is_pinned ? "pinned" : ""}" data-msg-id="${msg.id}" data-pinned="${msg.is_pinned}">
                ${msg.is_pinned ? "Pinned" : "Pin"}
              </button>
            </div>
          </div>
        </div>
      `;
    },

    bindMessageActionEvents() {
      const feed = document.getElementById("ws-chat-feed");
      if (!feed) return;

      // Pin toggles
      feed.querySelectorAll(".btn-toggle-pin").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const msgId = btn.getAttribute("data-msg-id");
          const currentlyPinned = btn.getAttribute("data-pinned") === "true";
          await this.togglePinMessage(msgId, !currentlyPinned);
        });
      });

      // Reaction pills
      feed.querySelectorAll(".ws-reaction-pill").forEach((pill) => {
        pill.addEventListener("click", async (e) => {
          e.stopPropagation();
          const msgId = pill.getAttribute("data-msg-id");
          const emoji = pill.getAttribute("data-emoji");
          await this.toggleReaction(msgId, emoji);
        });
      });

      // Add reaction button (+)
      feed.querySelectorAll(".btn-add-reaction").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const msgId = btn.getAttribute("data-msg-id");
          const emojis = ["👍", "⚠️", "❤️", "💡", "🎯"];
          const selected = prompt("Enter reaction emoji (e.g. 👍, ⚠️, ❤️, 💡):", "👍");
          if (selected) {
            await this.toggleReaction(msgId, selected.trim());
          }
        });
      });
    },

    appendMessage(msg) {
      this.currentMessages.push(msg);
      const feed = document.getElementById("ws-chat-feed");
      if (!feed) return;

      // If feed was empty state, clear placeholder
      if (this.currentMessages.length === 1) {
        feed.innerHTML = "";
      }

      feed.insertAdjacentHTML("beforeend", this.renderSingleMessageHtml(msg));
      this.bindMessageActionEvents();
      this.scrollToBottom();
    },

    updateMessageInFeed(updatedMsg) {
      const idx = this.currentMessages.findIndex((m) => m.id === updatedMsg.id);
      if (idx !== -1) {
        this.currentMessages[idx] = updatedMsg;
      }
      const existingEl = document.getElementById(`msg-${updatedMsg.id}`);
      if (existingEl) {
        existingEl.outerHTML = this.renderSingleMessageHtml(updatedMsg);
        this.bindMessageActionEvents();
      }
    },

    async togglePinMessage(messageId, isPinned) {
      try {
        const res = await fetch(`/api/v1/workspaces/${this.currentWorkspaceId}/messages/${messageId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-Termnova-Actor": this.currentUserName },
          body: JSON.stringify({ is_pinned: isPinned }),
        });
        if (res.ok) {
          const updated = await res.json();
          this.updateMessageInFeed(updated);
          this.fetchPinnedFindings();
        }
      } catch (e) {
        console.error("Failed toggling pin:", e);
      }
    },

    async toggleReaction(messageId, emoji) {
      try {
        const res = await fetch(`/api/v1/workspaces/${this.currentWorkspaceId}/messages/${messageId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-Termnova-Actor": this.currentUserName },
          body: JSON.stringify({ reaction: emoji, user_name: this.currentUserName }),
        });
        if (res.ok) {
          const updated = await res.json();
          this.updateMessageInFeed(updated);
        }
      } catch (e) {
        console.error("Failed toggling reaction:", e);
      }
    },

    async fetchPinnedFindings(workspaceId = null) {
      const wsId = workspaceId || this.currentWorkspaceId;
      if (!wsId) return;

      try {
        const res = await fetch(`/api/v1/workspaces/${wsId}/pinned`);
        if (res.ok) {
          this.pinnedMessages = await res.json();
          this.renderPinnedFindings();
        }
      } catch (e) {
        console.error("Error fetching pinned findings:", e);
      }
    },

    renderPinnedFindings() {
      const container = document.getElementById("ws-pinned-list");
      if (!container) return;

      if (!this.pinnedMessages || this.pinnedMessages.length === 0) {
        container.innerHTML = `
          <div style="padding: 1.5rem 0.5rem; text-align: center; color: #64748b; font-size: 0.8rem;">
            No pinned clauses yet. Pin a passage from the thread so the room does not lose it.
          </div>
        `;
        return;
      }

      container.innerHTML = this.pinnedMessages
        .map(
          (p) => `
        <div class="ws-pinned-card" id="pinned-${p.id}">
          <div class="ws-pinned-card-top">
            <span>${p.message_type === "ai_response" ? "From the contracts" : this.escapeHtml(p.user_name || "Note")}</span>
            <button class="ws-btn-icon-action" onclick="window.WorkspaceApp.togglePinMessage('${p.id}', false)" title="Unpin">✕</button>
          </div>
          <div class="ws-pinned-snippet">${this.escapeHtml(p.content)}</div>
          <div class="ws-pinned-actions">
            <button class="ws-btn-icon-action" onclick="window.WorkspaceApp.jumpToMessage('${p.id}')">Jump to chat ↑</button>
            <button class="ws-btn-icon-action" onclick="window.WorkspaceApp.copySnippet('${this.escapeQuotes(p.content)}')">Copy</button>
          </div>
        </div>
      `
        )
        .join("");
    },

    jumpToMessage(msgId) {
      const el = document.getElementById(`msg-${msgId}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("highlight");
        setTimeout(() => el.classList.remove("highlight"), 2000);
      }
    },

    copySnippet(text) {
      navigator.clipboard.writeText(text);
      alert("Finding copied to clipboard!");
    },

    async handleSendMessage(e) {
      e.preventDefault();
      const input = document.getElementById("ws-chat-input");
      if (!input) return;

      const content = input.value.trim();
      if (!content || !this.currentWorkspaceId) return;

      input.value = "";

      if (this.inputMode === "ai") {
        // Execute Scoped RAG AI Query
        this.showAiThinking(this.currentUserName);
        try {
          const res = await fetch(`/api/v1/workspaces/${this.currentWorkspaceId}/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Termnova-Actor": this.currentUserName },
            body: JSON.stringify({
              query: content,
              user_name: this.currentUserName,
            }),
          });
          this.removeAiThinking();
          if (res.ok) {
            const data = await res.json();
            if (!this.currentMessages.some((m) => m.id === data.human_message.id)) {
              this.appendMessage(data.human_message);
            }
            if (!this.currentMessages.some((m) => m.id === data.ai_response.id)) {
              this.appendMessage(data.ai_response);
            }
          }
        } catch (err) {
          this.removeAiThinking();
          console.error("Scoped AI query failed:", err);
        }
      } else {
        // Human Team Message
        try {
          const res = await fetch(`/api/v1/workspaces/${this.currentWorkspaceId}/messages`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Termnova-Actor": this.currentUserName },
            body: JSON.stringify({
              content: content,
              user_name: this.currentUserName,
            }),
          });
          if (res.ok) {
            const msg = await res.json();
            if (!this.currentMessages.some((m) => m.id === msg.id)) {
              this.appendMessage(msg);
            }
          }
        } catch (err) {
          console.error("Send message failed:", err);
        }
      }
    },

    handleTyping() {
      if (window.notificationsWs && window.notificationsWs.readyState === WebSocket.OPEN) {
        if (!this.typingDebounce) {
          this.typingDebounce = true;
          window.notificationsWs.send(
            JSON.stringify({
              action: "typing",
              workspace_id: this.currentWorkspaceId,
              user_name: this.currentUserName,
            })
          );
          setTimeout(() => {
            this.typingDebounce = false;
          }, 2500);
        }
      }
    },

    showUserTyping(userName) {
      const el = document.getElementById("ws-typing-indicator");
      if (!el) return;

      el.textContent = `✍️ ${userName} is typing...`;
      clearTimeout(this.typingTimer);
      this.typingTimer = setTimeout(() => {
        el.textContent = "";
      }, 3000);
    },

    showAiThinking(userName) {
      const feed = document.getElementById("ws-chat-feed");
      if (!feed || document.getElementById("ws-ai-thinking-indicator")) return;

      feed.insertAdjacentHTML(
        "beforeend",
        `
        <div class="ws-msg-row ai-msg" id="ws-ai-thinking-indicator">
          <div class="ws-msg-avatar ai">AI</div>
          <div class="ws-msg-body">
            <div class="ws-msg-meta"><span class="ws-msg-author">Termnova Legal AI</span></div>
            <div class="ws-msg-bubble" style="display:flex; align-items:center; gap:0.5rem; color:#a78bfa;">
              <span class="spinner" style="width:14px; height:14px; border-width:2px;"></span>
              <span>Analyzing scoped contract context for ${this.escapeHtml(userName)}...</span>
            </div>
          </div>
        </div>
      `
      );
      this.scrollToBottom();
    },

    removeAiThinking() {
      const indicator = document.getElementById("ws-ai-thinking-indicator");
      if (indicator) indicator.remove();
    },

    async handleCreateWorkspace(e) {
      e.preventDefault();
      const form = e.target;
      const name = form.ws_name.value.trim();
      const desc = form.ws_desc.value.trim();
      const selectedDocs = Array.from(form.querySelectorAll('input[name="doc_scope"]:checked')).map((cb) => cb.value);

      if (!name) return;

      try {
        const res = await fetch("/api/v1/workspaces/", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Termnova-Actor": this.currentUserName },
          body: JSON.stringify({
            name: name,
            description: desc,
            document_scope: selectedDocs,
            created_by: this.currentUserName,
          }),
        });

        if (res.ok) {
          const newWs = await res.json();
          this.workspaces.unshift(newWs);
          this.renderRoomsList();
          this.selectWorkspace(newWs.id);
          document.getElementById("modal-create-workspace").style.display = "none";
          form.reset();
        }
      } catch (err) {
        console.error("Create workspace failed:", err);
      }
    },

    async handleInviteMember(e) {
      e.preventDefault();
      const form = e.target;
      const userName = form.member_name.value.trim();
      const role = form.member_role.value;

      if (!userName || !this.currentWorkspaceId) return;

      try {
        const res = await fetch(`/api/v1/workspaces/${this.currentWorkspaceId}/members`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Termnova-Actor": this.currentUserName },
          body: JSON.stringify({ user_name: userName, role: role }),
        });

        if (res.ok) {
          await this.fetchWorkspaceDetail(this.currentWorkspaceId);
          document.getElementById("modal-invite-member").style.display = "none";
          form.reset();
          alert(`Invited ${userName} as ${role}!`);
        }
      } catch (err) {
        console.error("Invite member failed:", err);
      }
    },

    scrollToBottom() {
      const feed = document.getElementById("ws-chat-feed");
      if (feed) {
        feed.scrollTop = feed.scrollHeight;
      }
    },

    formatMarkdown(text) {
      if (!text) return "";
      let html = this.escapeHtml(text);
      // Bold
      html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
      // Citations [Source N]
      html = html.replace(
        /\[Source\s+(\d+)\]/gi,
        '<span class="badge" style="background:#3b82f6; color:#fff; font-size:0.7rem; padding:0.1rem 0.35rem; margin:0 0.2rem; cursor:pointer;">[Source $1]</span>'
      );
      // Linebreaks
      html = html.replace(/\n/g, "<br>");
      return html;
    },

    escapeHtml(str) {
      if (!str) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    },

    escapeQuotes(str) {
      if (!str) return "";
      return String(str).replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, " ");
    },
  };

  window.WorkspaceApp = WorkspaceApp;
})();
