/**
 * Termnova — Chat & Grounded Studio Q&A Logic
 */

(function bootAsk() {
  let booted = false;

  function start() {
    if (booted) return;
    const chatForm = document.getElementById('chat-form');
    const queryInput = document.getElementById('query-input');
    const chatMessages = document.getElementById('chat-messages');
    const welcomeCard = document.getElementById('welcome-message');
    const charCounter = document.getElementById('char-counter');
    const btnClearChat = document.getElementById('btn-clear-chat');
    const btnSend = document.getElementById('btn-send-query');

    if (!chatForm || !queryInput || !chatMessages) return;
    booted = true;

    let isGenerating = false;

    queryInput.addEventListener('input', () => {
      queryInput.style.height = 'auto';
      queryInput.style.height = Math.min(queryInput.scrollHeight, 140) + 'px';
      if (charCounter) charCounter.textContent = `${queryInput.value.length} / 2000`;
    });

    async function submitDeskAsk() {
      const query = queryInput.value.trim();
      if (!query || isGenerating) return;
      if (typeof switchView === 'function') switchView('chat');

      if (welcomeCard && welcomeCard.parentElement === chatMessages) {
        welcomeCard.remove();
      }

      appendMessage('user', escapeHtml(query));
      queryInput.value = '';
      queryInput.style.height = 'auto';
      if (charCounter) charCounter.textContent = '0 / 2000';
      setGeneratingState(true);

      const assistantBubble = appendMessage(
        'assistant',
        '<div class="typing-indicator"><span></span><span></span><span></span></div>'
      );

      try {
        if (typeof apiRequest !== 'function') {
          throw new Error('The desk scripts did not finish loading. Hard-refresh the page.');
        }
        const payload = { query: query, stream: false };
        if (window.AppState && AppState.activeDocumentId) {
          payload.document_ids = [AppState.activeDocumentId];
        }
        const response = await apiRequest('/api/v1/query', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        renderAssistantResponse(assistantBubble, response);
      } catch (err) {
        assistantBubble.innerHTML = `
          <div style="color: var(--color-error);">
            <strong>Could not answer:</strong> ${escapeHtml(err.message || 'The desk could not read that question. Try again, or open the contract in Library.')}
          </div>
        `;
      } finally {
        setGeneratingState(false);
        chatMessages.scrollTop = chatMessages.scrollHeight;
      }
    }
    window.submitDeskAsk = submitDeskAsk;

    queryInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitDeskAsk();
      }
    });

    document.querySelectorAll('#view-chat .chip, #view-chat .deck-card').forEach((chip) => {
      chip.addEventListener('click', () => {
        const prompt = chip.dataset.prompt;
        if (!prompt) return;
        queryInput.value = prompt;
        queryInput.dispatchEvent(new Event('input'));
        submitDeskAsk();
      });
    });

    if (btnClearChat) {
      btnClearChat.addEventListener('click', () => {
        chatMessages.innerHTML = '';
        if (welcomeCard) {
          chatMessages.appendChild(welcomeCard);
        }
        if (window.showToast) showToast('Conversation cleared', 'info');
      });
    }

    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      e.stopPropagation();
      submitDeskAsk();
    });

    if (btnSend) {
      btnSend.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        submitDeskAsk();
      });
    }

  function setGeneratingState(generating) {
    isGenerating = generating;
    if (btnSend) {
      btnSend.disabled = generating;
      btnSend.style.opacity = generating ? '0.6' : '1';
    }
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function formatMarkdown(text) {
    let html = escapeHtml(text);

    // Bold **text** -> <strong>text</strong>
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Bullet lists
    html = html.replace(/^\s*[\-\*]\s+(.*)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');

    // Section headers
    html = html.replace(/^### (.*$)/gim, '<h4 style="margin: 10px 0 4px 0; color: var(--on-paper);">$1</h4>');
    html = html.replace(/^## (.*$)/gim, '<h3 style="margin: 12px 0 6px 0; color: var(--on-paper);">$1</h3>');

    // Line breaks
    html = html.replace(/\n\n/g, '<br><br>');

    // Replace [Source N] with clickable pills
    html = html.replace(/\[Source\s+(\d+)\]/gi, (match, p1) => {
      const sourceNum = parseInt(p1);
      return `<button class="citation-badge" data-source-num="${sourceNum}">[Source ${sourceNum}]</button>`;
    });

    return html;
  }

  function appendMessage(role, initialHtml) {
    const row = document.createElement('div');
    row.className = `message-row ${role}`;

    const avatarIcon = role === 'user' 
      ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`
      : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`;

    row.innerHTML = `
      <div class="message-avatar">${avatarIcon}</div>
      <div class="message-content">
        <div class="message-bubble">${initialHtml}</div>
      </div>
    `;

    chatMessages.appendChild(row);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return row.querySelector('.message-bubble');
  }

  function renderAssistantResponse(bubbleElement, data) {
    const formattedAnswer = formatMarkdown(data.answer);

    let citationsHtml = '';
    if (data.citations && data.citations.length > 0) {
      const cardsHtml = data.citations.map((c) => `
        <div class="citation-card" data-source-num="${c.source_number}">
          <span class="badge badge-subtle">Src ${c.source_number}</span>
          <span>${c.document_filename}</span>
          <span style="color: var(--text-subtle);">p.${c.page_number || '1'}</span>
        </div>
      `).join('');

      citationsHtml = `
        <div class="citations-panel">
          ${cardsHtml}
        </div>
      `;
    }

    const confScore = Math.round(data.confidence_score * 100);
    const faithScore = Math.round(data.faithfulness_score * 100);

    const auditHtml = `
      <div class="audit-meta-row">
        <span class="audit-tag success">${data.latency_ms} ms</span>
        <span class="audit-tag">${confScore}% sure</span>
        <span class="audit-tag">${faithScore}% on the page</span>
        ${data.pii_redacted ? '<span class="audit-tag warning">Personal data hidden</span>' : ''}
        <button class="btn-icon" style="margin-left: auto; width: 24px; height: 24px;" title="Copy Answer" onclick="navigator.clipboard.writeText(\`${data.answer.replace(/`/g, '\\`')}\`); showToast('Answer copied to clipboard', 'info');">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
        </button>
      </div>
    `;

    bubbleElement.innerHTML = `
      <div>${formattedAnswer}</div>
      ${citationsHtml}
      ${auditHtml}
    `;

    // Attach click listeners to all citation pills in this message
    const citationsMap = {};
    if (data.citations) {
      data.citations.forEach((c) => {
        citationsMap[c.source_number] = c;
      });
    }

    bubbleElement.querySelectorAll('.citation-badge, .citation-card').forEach((el) => {
      el.addEventListener('click', () => {
        const sNum = parseInt(el.dataset.sourceNum);
        const citation = citationsMap[sNum];
        if (citation) {
          openSourceDrawer(citation);
        } else {
          showToast(`Source ${sNum} details not available in payload`, 'info');
        }
      });
    });
  }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
