/**
 * Contract comparison controller handling clause alignment rendering and diffing.
 */

document.addEventListener("DOMContentLoaded", () => {
  const docASelect = document.getElementById("compare-doc-a");
  const docBSelect = document.getElementById("compare-doc-b");
  const btnRunCompare = document.getElementById("btn-run-compare");
  const compareResults = document.getElementById("compare-results-container");
  const alignmentsList = document.getElementById("alignments-list");
  const keyDiffsList = document.getElementById("key-diffs-list");
  const statSimilarity = document.getElementById("stat-overall-similarity");
  const statIdentical = document.getElementById("stat-identical-clauses");
  const statModified = document.getElementById("stat-modified-clauses");
  const statAdded = document.getElementById("stat-added-clauses");
  const statRemoved = document.getElementById("stat-removed-clauses");

  // Populate document selectors
  async function loadDocumentSelectors() {
    try {
      const resp = await fetch("/api/v1/documents?limit=100");
      if (!resp.ok) return;
      const data = await resp.json();
      const docs = data.documents || [];

      if (docASelect && docBSelect) {
        const formatTitle = window.formatContractTitle || ((t) => t);
        const optionsHtml = docs
          .map((d) => `<option value="${d.id}">${formatTitle(d.filename)} (${d.page_count || 1} pages)</option>`)
          .join("");

        docASelect.innerHTML = `<option value="">-- Select Base Contract A --</option>${optionsHtml}`;
        docBSelect.innerHTML = `<option value="">-- Select Target Contract B --</option>${optionsHtml}`;

        if (docs.length >= 2) {
          docASelect.selectedIndex = 1;
          docBSelect.selectedIndex = 2;
        }
      }
    } catch (err) {
      console.error("Failed to load document selectors for comparison", err);
    }
  }

  // Handle comparison trigger
  if (btnRunCompare) {
    btnRunCompare.addEventListener("click", async () => {
      const docAId = docASelect.value;
      const docBId = docBSelect.value;

      if (!docAId || !docBId) {
        if (window.showToast) window.showToast("Please select two distinct contracts to compare", "error");
        return;
      }

      if (docAId === docBId) {
        if (window.showToast) window.showToast("Cannot compare a document with itself", "error");
        return;
      }

      btnRunCompare.disabled = true;
      btnRunCompare.innerHTML = "<span>Analyzing & Aligning Clauses...</span>";

      try {
        const resp = await fetch("/api/v1/compare", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            document_a_id: docAId,
            document_b_id: docBId,
          }),
        });

        if (!resp.ok) {
          const err = await resp.json();
          throw new Error(err.detail || "Comparison failed");
        }

        const report = await resp.json();
        renderComparisonReport(report);
        if (window.showToast) window.showToast("Contract comparison completed", "success");
      } catch (e) {
        if (window.showToast) window.showToast(e.message, "error");
      } finally {
        btnRunCompare.disabled = false;
        btnRunCompare.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="16 3 21 3 21 8"></polyline>
            <line x1="4" y1="20" x2="21" y2="3"></line>
            <polyline points="21 16 21 21 16 21"></polyline>
            <line x1="15" y1="15" x2="21" y2="21"></line>
            <line x1="4" y1="4" x2="9" y2="9"></line>
          </svg>
          <span>Run Side-by-Side Comparison</span>
        `;
      }
    });
  }

  function renderComparisonReport(report) {
    if (!compareResults) return;
    compareResults.style.display = "block";

    // Summary KPIs
    if (statSimilarity) statSimilarity.textContent = `${Math.round(report.overall_similarity * 100)}%`;
    if (statIdentical) statIdentical.textContent = report.identical_clauses;
    if (statModified) statModified.textContent = report.modified_clauses;
    if (statAdded) statAdded.textContent = report.added_clauses;
    if (statRemoved) statRemoved.textContent = report.removed_clauses;

    // Key Differences List
    if (keyDiffsList) {
      if (report.key_differences && report.key_differences.length > 0) {
        keyDiffsList.innerHTML = report.key_differences
          .map((kd) => `<li class="diff-bullet">⚠️ ${kd}</li>`)
          .join("");
      } else {
        keyDiffsList.innerHTML = `<li class="diff-bullet text-muted">No material financial or deadline discrepancies detected.</li>`;
      }
    }

    // Alignments Table
    if (alignmentsList) {
      if (!report.alignments || report.alignments.length === 0) {
        alignmentsList.innerHTML = `<div class="empty-state">No clause alignments generated.</div>`;
        return;
      }

      alignmentsList.innerHTML = report.alignments
        .map((al, idx) => {
          const badgeClass =
            al.diff_type === "identical"
              ? "badge-green"
              : al.diff_type === "modified"
              ? "badge-amber"
              : al.diff_type === "added"
              ? "badge-blue"
              : "badge-red";

          return `
            <div class="alignment-card glass-card">
              <div class="alignment-header">
                <div class="alignment-title">
                  <span class="badge ${badgeClass}">${al.diff_type.toUpperCase()}</span>
                  <span class="alignment-sections">
                    <strong>Doc A:</strong> ${al.section_a || "N/A"} ⟷ <strong>Doc B:</strong> ${al.section_b || "N/A"}
                  </span>
                </div>
                <div class="alignment-score">
                  <span>Match Score: <strong>${Math.round(al.similarity_score * 100)}%</strong></span>
                </div>
              </div>
              <div class="alignment-body">
                <div class="diff-content">${al.diff_html}</div>
              </div>
            </div>
          `;
        })
        .join("");
    }
  }

  // Hook navigation switch to refresh document lists
  const navCompare = document.getElementById("nav-compare");
  if (navCompare) {
    navCompare.addEventListener("click", loadDocumentSelectors);
  }

  // Initial load — also used when Redline is opened from the sidebar
  window.initCompareDropdowns = loadDocumentSelectors;
  loadDocumentSelectors();
});
