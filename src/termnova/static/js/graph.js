/**
 * Termnova — Interactive Contract Knowledge Graph & D3.js Topology Engine
 */

let graphState = {
  rawGraphData: null,
  activeFilters: {
    types: new Set(['msa', 'sow', 'nda', 'amendment', 'lease', 'vendor', 'other', 'company', 'jurisdiction', 'person']),
    showEntities: true,
    searchQuery: '',
  },
  currentViewMode: 'graph', // 'graph' or 'stack'
  selectedNode: null,
  simulation: null,
  svg: null,
  g: null,
  zoom: null,
};

// ──── Utility: HTML Escaping for XSS Prevention ────
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ──── Initialize Graph Component ────
let isToolbarInitialized = false;

async function initGraphView() {
  const container = document.getElementById('graph-canvas-container');
  if (!container) return;

  if (!isToolbarInitialized) {
    setupGraphToolbar();
    isToolbarInitialized = true;
  }
  await loadGraphData();
}

// ──── Persistent Toolbar & Filter Event Listeners ────
function setupGraphToolbar() {
  // View mode switcher
  const btnGraphMode = document.getElementById('btn-mode-graph');
  const btnStackMode = document.getElementById('btn-mode-stack');
  const graphCanvas = document.getElementById('graph-canvas-container');
  const stackContainer = document.getElementById('stack-container');

  if (btnGraphMode && btnStackMode) {
    btnGraphMode.addEventListener('click', () => {
      btnGraphMode.classList.add('active');
      btnStackMode.classList.remove('active');
      graphState.currentViewMode = 'graph';
      if (graphCanvas) graphCanvas.style.display = 'block';
      if (stackContainer) stackContainer.style.display = 'none';
      if (graphState.rawGraphData) renderD3ForceGraph(graphState.rawGraphData);
    });

    btnStackMode.addEventListener('click', async () => {
      btnStackMode.classList.add('active');
      btnGraphMode.classList.remove('active');
      graphState.currentViewMode = 'stack';
      if (graphCanvas) graphCanvas.style.display = 'none';
      if (stackContainer) stackContainer.style.display = 'block';
      await loadFirstAvailableStack();
    });
  }

  // Type filter pills
  document.querySelectorAll('.filter-pill[data-type]').forEach((pill) => {
    pill.addEventListener('click', () => {
      const type = pill.dataset.type;
      if (type === 'entity') {
        graphState.activeFilters.showEntities = !graphState.activeFilters.showEntities;
        pill.classList.toggle('active', graphState.activeFilters.showEntities);
      } else {
        if (graphState.activeFilters.types.has(type)) {
          graphState.activeFilters.types.delete(type);
          pill.classList.remove('active');
        } else {
          graphState.activeFilters.types.add(type);
          pill.classList.add('active');
        }
      }
      applyFilters();
    });
  });

  // Search input filter
  const searchInput = document.getElementById('graph-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      graphState.activeFilters.searchQuery = e.target.value.toLowerCase().trim();
      applyFilters();
    });
  }

  // Export SVG
  const btnExport = document.getElementById('btn-export-graph-svg');
  if (btnExport) {
    btnExport.addEventListener('click', exportGraphSVG);
  }

  // Close drawer
  const btnCloseDrawer = document.getElementById('btn-close-graph-drawer');
  if (btnCloseDrawer) {
    btnCloseDrawer.addEventListener('click', closeGraphDrawer);
  }
}

// ──── Floating Canvas Zoom Controls (Rebound on Canvas Re-render) ────
function setupFloatingControls() {
  const btnZoomIn = document.getElementById('btn-graph-zoom-in');
  const btnZoomOut = document.getElementById('btn-graph-zoom-out');
  const btnZoomReset = document.getElementById('btn-graph-zoom-reset');

  if (btnZoomIn) {
    btnZoomIn.addEventListener('click', () => {
      if (graphState.svg && graphState.zoom) {
        graphState.svg.transition().duration(250).call(graphState.zoom.scaleBy, 1.3);
      }
    });
  }

  if (btnZoomOut) {
    btnZoomOut.addEventListener('click', () => {
      if (graphState.svg && graphState.zoom) {
        graphState.svg.transition().duration(250).call(graphState.zoom.scaleBy, 0.7);
      }
    });
  }

  if (btnZoomReset) {
    btnZoomReset.addEventListener('click', () => {
      if (graphState.svg && graphState.zoom) {
        graphState.svg.transition().duration(400).call(graphState.zoom.transform, d3.zoomIdentity);
      }
    });
  }
}

// ──── Fetch Graph Data from API ────
async function loadGraphData(rootDocId = null, depth = 3) {
  try {
    let url = `/api/v1/graph/visualize?depth=${depth}&include_entities=true`;
    if (rootDocId) url += `&root=${rootDocId}`;

    const data = await apiRequest(url);
    graphState.rawGraphData = data;

    const countPill = document.getElementById('graph-node-count-badge');
    if (countPill) {
      countPill.textContent = `${data.total_contracts} Contracts • ${data.total_relationships} Links`;
    }

    if (graphState.currentViewMode === 'graph') {
      renderD3ForceGraph(data);
    }
  } catch (err) {
    console.error('Failed to fetch graph data:', err);
    if (window.showToast) window.showToast('Could not load contract knowledge graph', 'error');
  }
}

// ──── D3 Force-Directed Graph Rendering ────
function renderD3ForceGraph(data) {
  if (typeof d3 === 'undefined') {
    console.warn('D3.js library not loaded yet');
    return;
  }

  const container = document.getElementById('graph-canvas-container');
  if (!container) return;

  const width = container.clientWidth || 800;
  const height = container.clientHeight || 600;

  // Clear previous SVG
  container.innerHTML = `
    <svg id="graph-svg"></svg>
    <div class="graph-floating-controls">
      <button class="graph-ctrl-btn" id="btn-graph-zoom-in" title="Zoom In">+</button>
      <button class="graph-ctrl-btn" id="btn-graph-zoom-out" title="Zoom Out">&minus;</button>
      <button class="graph-ctrl-btn" id="btn-graph-zoom-reset" title="Reset View">&#x21bb;</button>
    </div>
  `;

  // Re-bind only floating controls
  setupFloatingControls();

  const svg = d3.select('#graph-svg')
    .attr('width', '100%')
    .attr('height', '100%')
    .attr('viewBox', [-width / 2, -height / 2, width, height]);

  graphState.svg = svg;

  // Defs for arrowheads
  const defs = svg.append('defs');
  defs.append('marker')
    .attr('id', 'arrow-head')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 22)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', 'rgba(148, 163, 184, 0.4)');

  const g = svg.append('g').attr('class', 'graph-viewport');
  graphState.g = g;

  // Zoom behavior
  const zoom = d3.zoom()
    .scaleExtent([0.15, 4])
    .on('zoom', (event) => {
      g.attr('transform', event.transform);
    });

  svg.call(zoom);
  graphState.zoom = zoom;

  // Filter nodes based on active state
  let visibleNodes = [...data.nodes];
  if (graphState.activeFilters.showEntities && data.entity_nodes) {
    visibleNodes = visibleNodes.concat(data.entity_nodes);
  }

  // Filter by category
  visibleNodes = visibleNodes.filter((n) => graphState.activeFilters.types.has(n.node_type));

  const visibleNodeIds = new Set(visibleNodes.map((n) => n.id));
  const visibleEdges = data.edges.filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target));

  // Clone objects so D3 mutation doesn't taint store
  const nodes = visibleNodes.map((d) => ({ ...d }));
  const links = visibleEdges.map((d) => ({ ...d }));

  // Force simulation
  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id((d) => d.id).distance(120))
    .force('charge', d3.forceManyBody().strength(-380))
    .force('collide', d3.forceCollide().radius(35))
    .force('center', d3.forceCenter(0, 0));

  graphState.simulation = simulation;

  // Draw Edges
  const linkGroup = g.append('g').attr('class', 'links');
  const link = linkGroup.selectAll('line')
    .data(links)
    .join('line')
    .attr('class', 'graph-link')
    .attr('marker-end', 'url(#arrow-head)');

  // Draw Edge Labels
  const linkLabel = linkGroup.selectAll('.graph-link-label')
    .data(links)
    .join('text')
    .attr('class', 'graph-link-label')
    .text((d) => d.label || '');

  // Draw Nodes
  const nodeGroup = g.append('g').attr('class', 'nodes');
  const node = nodeGroup.selectAll('.graph-node')
    .data(nodes)
    .join('g')
    .attr('class', (d) => `graph-node node-type-${d.node_type}`)
    .call(drag(simulation))
    .on('click', (event, d) => {
      event.stopPropagation();
      selectNode(d);
    });

  // Circle base
  node.append('circle')
    .attr('class', (d) => `node-base node-type-${d.node_type}`)
    .attr('r', (d) => (d.node_type === 'company' || d.node_type === 'jurisdiction' ? 12 : 18));

  // Label text
  const formatTitle = window.formatContractTitle || ((t) => t);
  node.append('text')
    .attr('class', 'graph-node-label')
    .attr('dy', 30)
    .text((d) => {
      const lbl = (d.node_type === 'company' || d.node_type === 'jurisdiction') ? d.label : formatTitle(d.label);
      return lbl.length > 24 ? `${lbl.slice(0, 22)}…` : lbl;
    });

  // Tick update
  simulation.on('tick', () => {
    link
      .attr('x1', (d) => d.source.x)
      .attr('y1', (d) => d.source.y)
      .attr('x2', (d) => d.target.x)
      .attr('y2', (d) => d.target.y);

    linkLabel
      .attr('x', (d) => (d.source.x + d.target.x) / 2)
      .attr('y', (d) => (d.source.y + d.target.y) / 2 - 4);

    node.attr('transform', (d) => `translate(${d.x},${d.y})`);
  });

  // Deselect on clicking empty canvas
  svg.on('click', () => {
    closeGraphDrawer();
  });
}

// ──── Drag Behavior ────
function drag(simulation) {
  function dragstarted(event) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    event.subject.fx = event.subject.x;
    event.subject.fy = event.subject.y;
  }

  function dragged(event) {
    event.subject.fx = event.x;
    event.subject.fy = event.y;
  }

  function dragended(event) {
    if (!event.active) simulation.alphaTarget(0);
    event.subject.fx = null;
    event.subject.fy = null;
  }

  return d3.drag()
    .on('start', dragstarted)
    .on('drag', dragged)
    .on('end', dragended);
}

// ──── Filter Application ────
function applyFilters() {
  if (!graphState.rawGraphData) return;
  if (graphState.currentViewMode === 'graph') {
    renderD3ForceGraph(graphState.rawGraphData);

    // Apply search highlighting
    if (graphState.activeFilters.searchQuery) {
      const q = graphState.activeFilters.searchQuery;
      d3.selectAll('.graph-node').each(function (d) {
        const matches = d.label.toLowerCase().includes(q) || (d.metadata && JSON.stringify(d.metadata).toLowerCase().includes(q));
        d3.select(this).style('opacity', matches ? '1.0' : '0.2');
      });
    }
  }
}

// ──── Node Selection & Detail Drawer ────
function selectNode(nodeData) {
  graphState.selectedNode = nodeData;

  // Highlight in SVG
  d3.selectAll('.graph-node').classed('selected', (d) => d.id === nodeData.id);

  const drawer = document.getElementById('graph-node-drawer');
  if (!drawer) return;

  const typeBadge = document.getElementById('graph-drawer-type-badge');
  const title = document.getElementById('graph-drawer-title');
  const effDate = document.getElementById('graph-drawer-eff-date');
  const expDate = document.getElementById('graph-drawer-exp-date');
  const govLaw = document.getElementById('graph-drawer-gov-law');
  const valueUsd = document.getElementById('graph-drawer-value');
  const partiesContainer = document.getElementById('graph-drawer-parties');
  const btnQueryContract = document.getElementById('btn-graph-query-contract');

  if (typeBadge) {
    typeBadge.textContent = (nodeData.node_type || 'Contract').toUpperCase();
    typeBadge.className = `badge badge-${nodeData.node_type || 'accent'}`;
  }
  if (title) title.textContent = nodeData.label;
  if (effDate) effDate.textContent = nodeData.metadata?.effective_date || 'N/A';
  if (expDate) expDate.textContent = nodeData.metadata?.expiration_date || 'N/A';
  if (govLaw) govLaw.textContent = nodeData.metadata?.governing_law || 'N/A';
  if (valueUsd) {
    valueUsd.textContent = nodeData.metadata?.total_value_usd
      ? `$${Number(nodeData.metadata.total_value_usd).toLocaleString()}`
      : 'N/A';
  }

  // Render parties
  if (partiesContainer) {
    partiesContainer.innerHTML = '';
    const parties = nodeData.metadata?.extracted_parties || [];
    if (parties.length > 0) {
      parties.forEach((p) => {
        const span = document.createElement('span');
        span.className = 'party-badge';
        span.textContent = `${p.name} (${p.role || 'Party'})`;
        partiesContainer.appendChild(span);
      });
    } else {
      partiesContainer.innerHTML = '<span class="text-muted" style="font-size:0.75rem">No parties extracted</span>';
    }
  }

  // Wire query in studio button
  if (btnQueryContract) {
    btnQueryContract.onclick = () => {
      if (window.askAboutDocument) {
        window.askAboutDocument(nodeData.label, nodeData.document_id || nodeData.id);
      } else if (window.switchView) {
        window.switchView('chat');
      }
    };
  }

  drawer.classList.add('open');
}

function closeGraphDrawer() {
  const drawer = document.getElementById('graph-node-drawer');
  if (drawer) drawer.classList.remove('open');
  d3.selectAll('.graph-node').classed('selected', false);
}

// ──── Document Stack View (Hierarchical Cards) ────
async function loadFirstAvailableStack() {
  const stackContainer = document.getElementById('stack-container');
  if (!stackContainer) return;

  if (!graphState.rawGraphData || graphState.rawGraphData.nodes.length === 0) {
    stackContainer.innerHTML = `
      <div class="empty-state" style="padding: 40px; text-align: center;">
        <p>No indexed contracts available. Upload a Master Services Agreement to view the hierarchical stack.</p>
      </div>
    `;
    return;
  }

  // Find first MSA or first document
  const msaNode = graphState.rawGraphData.nodes.find((n) => n.node_type === 'msa') || graphState.rawGraphData.nodes[0];
  if (msaNode && msaNode.document_id) {
    await loadDocumentStack(msaNode.document_id);
  }
}

async function loadDocumentStack(documentId) {
  const container = document.getElementById('stack-container');
  if (!container) return;

  container.innerHTML = '<div style="padding:24px; text-align:center;">Resolving contract family...</div>';

  try {
    const familyData = await apiRequest(`/api/v1/graph/families/by-document/${documentId}`);
    renderContractFamilyView(familyData, container);
  } catch (err) {
    if (String(err.message || '').includes('No active contract family')) {
      try {
        const stackData = await apiRequest(`/api/v1/graph/stack/${documentId}`);
        renderDocumentStackView(stackData, container, documentId);
      } catch (stackErr) {
        console.error('Failed to load document stack:', stackErr);
        container.innerHTML = `<div class="empty-state" style="padding: 30px; text-align: center;">Failed to load stack: ${escapeHtml(stackErr.message)}</div>`;
      }
      return;
    }
    console.error('Failed to load contract family:', err);
    container.innerHTML = `<div class="empty-state" style="padding: 30px; text-align: center;">Failed to load family intelligence: ${escapeHtml(err.message)}</div>`;
  }
}

function renderDocumentStackView(stackData, container, documentId) {
  const root = stackData.stack;
  if (!root) return;

  const rootFilenameEsc = escapeHtml(root.filename);
  const rootTitleEsc = escapeHtml(root.title || root.filename);
  const rootContractTypeEsc = escapeHtml((root.contract_type || 'msa').toLowerCase());
  const rootEffDateEsc = escapeHtml(root.effective_date || 'N/A');
  const rootExpDateEsc = escapeHtml(root.expiration_date || 'N/A');
  const rootPartiesEsc = escapeHtml((root.parties || []).join(', ') || 'N/A');

  container.innerHTML = `
    <div class="stack-view-container">
      <div class="stack-tree-wrapper">
        <div class="family-setup-banner">
          <div>
            <strong>This is an ungoverned document stack.</strong>
            <span>Create a stable family to resolve amendments, controlling terms, and conflicts across future versions.</span>
          </div>
          <button class="btn btn-primary btn-sm" onclick="createContractFamily('${encodeURIComponent(documentId)}')">Create governed family</button>
        </div>
        <div style="margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
          <div>
            <h3 style="font-size: 1.1rem; font-weight: 700; color: var(--on-paper);">Stack: ${rootFilenameEsc}</h3>
            <p style="font-size: 0.8rem; color: var(--text-muted);">${stackData.total_descendants} Linked Agreements • Total Value: ${stackData.total_value_usd ? `$${stackData.total_value_usd.toLocaleString()}` : 'N/A'}</p>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="loadGraphData('${encodeURIComponent(root.document_id)}')">
            <span>Center Force Graph</span>
          </button>
        </div>

        <!-- Root Card -->
        <div class="stack-card root-card">
          <div class="stack-card-header">
            <span class="type-tag tag-${rootContractTypeEsc}">${rootContractTypeEsc.toUpperCase()}</span>
            <span class="stack-card-title">${rootTitleEsc}</span>
          </div>
          <div class="stack-card-meta">
            <span>Effective: ${rootEffDateEsc}</span>
            <span>Expiration: ${rootExpDateEsc}</span>
            <span>Parties: ${rootPartiesEsc}</span>
          </div>
        </div>

        <!-- Children Cards -->
        <div class="stack-children-list">
          ${
            root.children && root.children.length > 0
              ? root.children
                  .map(
                    (child) => {
                      const childTitleEsc = escapeHtml(child.title || child.filename);
                      const childTypeEsc = escapeHtml((child.contract_type || 'sow').toLowerCase());
                      const childEffEsc = escapeHtml(child.effective_date || 'N/A');
                      const childExpEsc = escapeHtml(child.expiration_date || 'N/A');
                      const childPartiesEsc = escapeHtml((child.parties || []).join(', ') || 'N/A');
                      return `
                <div class="stack-card child-card">
                  <div class="stack-card-header">
                    <span class="type-tag tag-${childTypeEsc}">${childTypeEsc.toUpperCase()}</span>
                    <span class="stack-card-title">${childTitleEsc}</span>
                  </div>
                  <div class="stack-card-meta">
                    <span>Effective: ${childEffEsc}</span>
                    <span>Expiration: ${childExpEsc}</span>
                    <span>Parties: ${childPartiesEsc}</span>
                  </div>
                </div>
              `;
                    }
                  )
                  .join('')
              : '<div class="text-muted" style="margin-left: 36px; font-size: 0.82rem;">No child SOWs or Amendments linked to this agreement yet.</div>'
          }
        </div>
      </div>
    </div>
  `;
}

async function createContractFamily(documentId) {
  try {
    const familyData = await apiRequest('/api/v1/graph/families', {
      method: 'POST',
      body: JSON.stringify({ root_document_id: documentId }),
    });
    renderContractFamilyView(familyData, document.getElementById('stack-container'));
    if (window.showToast) window.showToast('Governed contract family created', 'success');
  } catch (err) {
    if (window.showToast) window.showToast(`Could not create family: ${err.message}`, 'error');
  }
}

function renderContractFamilyView(familyData, container) {
  if (!container) return;
  const members = familyData.members || [];
  const effectiveTerms = familyData.effective_terms || [];
  const conflicts = familyData.conflicts || [];
  const memberOptions = (graphState.rawGraphData?.nodes || [])
    .filter((node) => node.document_id && !members.some((member) => member.document_id === node.document_id))
    .map((node) => `<option value="${escapeHtml(node.document_id)}">${escapeHtml(node.label)}</option>`)
    .join('');

  container.innerHTML = `
    <div class="family-control-view">
      <header class="family-control-header">
        <div>
          <span class="family-eyebrow">Effective agreement control</span>
          <h3>${escapeHtml(familyData.name)}</h3>
          <p>As of ${escapeHtml(familyData.as_of)} · only approved or corrected facts determine effective terms.</p>
        </div>
        <div class="family-metrics">
          <span><strong>${members.length}</strong> agreements</span>
          <span><strong>${effectiveTerms.length}</strong> terms</span>
          <span class="${conflicts.length ? 'family-metric-danger' : ''}"><strong>${conflicts.length}</strong> conflicts</span>
        </div>
      </header>

      <section class="family-panel">
        <div class="family-section-heading">
          <div><h4>Agreement hierarchy</h4><p>Membership survives uploads of new document versions.</p></div>
        </div>
        <div class="family-member-grid">
          ${members.map(renderFamilyMember).join('') || '<p class="text-muted">No active agreements.</p>'}
        </div>
        ${memberOptions ? `
          <form class="family-add-form" id="family-add-member-form">
            <select id="family-member-document" required><option value="">Select a linked agreement</option>${memberOptions}</select>
            <select id="family-member-role" required>
              <option value="sow">SOW</option><option value="order_form">Order form</option>
              <option value="dpa">DPA</option><option value="amendment">Amendment</option>
              <option value="addendum">Addendum</option><option value="other">Other</option>
            </select>
            <select id="family-member-relationship" required>
              <option value="governed_by">Governed by</option><option value="amends">Amends</option>
              <option value="supersedes">Supersedes</option><option value="addendum_to">Addendum to</option>
              <option value="annex_to">Annex to</option><option value="renewal_of">Renewal of</option>
            </select>
            <button class="btn btn-secondary btn-sm" type="submit">Add agreement</button>
          </form>` : ''}
      </section>

      <section class="family-panel ${conflicts.length ? 'family-panel-alert' : ''}">
        <div class="family-section-heading">
          <div><h4>Conflict desk</h4><p>Equal-precedence verified provisions that need a controlling decision.</p></div>
          <span class="badge ${conflicts.length ? 'badge-danger' : 'badge-subtle'}">${conflicts.length} open</span>
        </div>
        ${conflicts.length ? conflicts.map((conflict) => renderFamilyConflict(conflict, familyData.family_id)).join('') : '<div class="family-clear-state">No unresolved controlling-term conflicts.</div>'}
      </section>

      <section class="family-panel">
        <div class="family-section-heading"><div><h4>Effective terms</h4><p>Current answer, precedence path, and exact source evidence.</p></div></div>
        <div class="family-term-list">
          ${effectiveTerms.map(renderEffectiveTerm).join('') || '<div class="family-clear-state">Approve extracted facts to populate effective terms.</div>'}
        </div>
      </section>
    </div>`;

  document.getElementById('family-add-member-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const documentId = document.getElementById('family-member-document').value;
    const role = document.getElementById('family-member-role').value;
    const relationshipType = document.getElementById('family-member-relationship').value;
    try {
      const updated = await apiRequest(`/api/v1/graph/families/${familyData.family_id}/members`, {
        method: 'POST',
        body: JSON.stringify({
          document_id: documentId,
          role,
          relationship_type: relationshipType,
        }),
      });
      renderContractFamilyView(updated, container);
      if (window.showToast) window.showToast('Agreement added to family', 'success');
    } catch (err) {
      if (window.showToast) window.showToast(`Could not add agreement: ${err.message}`, 'error');
    }
  });

  container.querySelectorAll('.family-control-choice').forEach((button) => {
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const updated = await apiRequest(
          `/api/v1/graph/families/${familyData.family_id}/members/${button.dataset.membershipId}`,
          {
            method: 'PATCH',
            body: JSON.stringify({ precedence: Number(button.dataset.precedence) + 1 }),
          }
        );
        renderContractFamilyView(updated, container);
        if (window.showToast) window.showToast('Controlling provision selected', 'success');
      } catch (err) {
        button.disabled = false;
        if (window.showToast) window.showToast(`Could not resolve conflict: ${err.message}`, 'error');
      }
    });
  });
}

function renderFamilyMember(member) {
  const scope = member.applies_to?.length ? member.applies_to.join(', ') : 'All extracted terms';
  return `<article class="family-member-card">
    <div><span class="type-tag tag-${escapeHtml(member.role)}">${escapeHtml(member.role).toUpperCase()}</span><strong>${escapeHtml(member.title)}</strong></div>
    <p>${escapeHtml(member.relationship_type.replaceAll('_', ' '))} · v${member.version_number} · precedence ${member.precedence}</p>
    <small>${escapeHtml(scope)}</small>
  </article>`;
}

function renderEffectiveTerm(term) {
  if (!term.effective) {
    return `<article class="family-term-card family-term-conflict"><div><strong>${escapeHtml(term.fact_type)}</strong><span>Conflict</span></div><p>Resolve the conflict above before relying on this term.</p></article>`;
  }
  const candidate = term.effective;
  const evidence = candidate.evidence;
  const page = evidence.page_number ? `page ${evidence.page_number}` : 'page unavailable';
  return `<article class="family-term-card">
    <div class="family-term-title"><strong>${escapeHtml(term.fact_type.replaceAll('_', ' '))}</strong><span>${escapeHtml(term.status.replaceAll('_', ' '))}</span></div>
    <div class="family-term-value">${escapeHtml(candidate.display_value)}</div>
    <p class="family-source-line">${escapeHtml(evidence.filename)} · ${escapeHtml(page)} · precedence ${candidate.precedence}${term.alternatives.length ? ` · overrides ${term.alternatives.length}` : ''}</p>
    <blockquote>${escapeHtml(evidence.source_text)}</blockquote>
  </article>`;
}

function renderFamilyConflict(conflict, familyId) {
  return `<article class="family-conflict-card">
    <strong>${escapeHtml(conflict.fact_type.replaceAll('_', ' '))}</strong>
    <p>${escapeHtml(conflict.reason)}</p>
    <div>${conflict.candidates.map((candidate) => `<span>
      <span>${escapeHtml(candidate.display_value)} · ${escapeHtml(candidate.evidence.filename)} p.${escapeHtml(candidate.evidence.page_number || '—')}</span>
      <button class="btn btn-secondary btn-sm family-control-choice" type="button" data-family-id="${escapeHtml(familyId)}" data-membership-id="${escapeHtml(candidate.membership_id)}" data-precedence="${candidate.precedence}">Set as controlling</button>
    </span>`).join('')}</div>
  </article>`;
}

// ──── Export Graph as SVG ────
function exportGraphSVG() {
  const svgEl = document.getElementById('graph-svg');
  if (!svgEl) return;

  const serializer = new XMLSerializer();
  let source = serializer.serializeToString(svgEl);

  if (!source.match(/^<svg[^>]+xmlns="http\:\/\/www\.w3\.org\/2000\/svg"/)) {
    source = source.replace(/^<svg/, '<svg xmlns="http://www.w3.org/2000/svg"');
  }

  const blob = new Blob([source], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `termnova_contract_graph_${Date.now()}.svg`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  if (window.showToast) window.showToast('Graph exported as SVG', 'success');
}

// Export for global access
window.initGraphView = initGraphView;
window.loadGraphData = loadGraphData;
