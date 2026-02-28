/**
 * DID Document API module + helpers.
 * Loaded after orgadmin.js (uses Auth, oaAlert, oaFormatDate, etc.)
 */

const DocAPI = (() => {
  const API = "/api/v2/org/organizations";

  function extractDetail(data) {
    const d = data?.detail;
    if (!d) return data?.message || "Something went wrong.";
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d.map(e => {
        const loc = e.loc ? e.loc.filter(l => l !== "body").join(" → ") : "";
        const msg = e.msg || "Validation error";
        return loc ? `${loc}: ${msg}` : msg;
      }).join("; ");
    }
    try { return JSON.stringify(d); } catch { return "Something went wrong."; }
  }

  async function apiCall(path, { method = "GET", body } = {}) {
    const headers = { "Content-Type": "application/json" };
    const { access } = Auth.getTokens();
    if (access) headers["Authorization"] = `Bearer ${access}`;

    const res = await fetch(`${API}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    // DELETE with 204 has no body
    if (res.status === 204) return {};

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401) {
        Auth.clearTokens();
        window.location.href = "/login/";
        return;
      }
      throw { status: res.status, detail: extractDetail(data) };
    }
    return data;
  }

  return {
    list:          (orgId) => apiCall(`/${orgId}/documents`),
    create:        (orgId, data) => apiCall(`/${orgId}/documents`, { method: "POST", body: data }),
    get:           (orgId, docId) => apiCall(`/${orgId}/documents/${docId}`),
    updateDraft:   (orgId, docId, data) => apiCall(`/${orgId}/documents/${docId}/draft`, { method: "PATCH", body: data }),
    addVM:         (orgId, docId, data) => apiCall(`/${orgId}/documents/${docId}/verification-methods`, { method: "POST", body: data }),
    removeVM:      (orgId, docId, vmId) => apiCall(`/${orgId}/documents/${docId}/verification-methods/${vmId}`, { method: "DELETE" }),
    submit:        (orgId, docId) => apiCall(`/${orgId}/documents/${docId}/submit`, { method: "POST", body: {} }),
    approve:       (orgId, docId, comment) => apiCall(`/${orgId}/documents/${docId}/approve`, { method: "POST", body: { comment } }),
    reject:        (orgId, docId, comment) => apiCall(`/${orgId}/documents/${docId}/reject`, { method: "POST", body: { comment } }),
    publish:       (orgId, docId) => apiCall(`/${orgId}/documents/${docId}/publish`, { method: "POST", body: {} }),
    deactivate:    (orgId, docId, reason) => apiCall(`/${orgId}/documents/${docId}/deactivate`, { method: "POST", body: { reason } }),
    pendingReview: (orgId) => apiCall(`/${orgId}/documents/pending-review`),
    versions:      (orgId, docId) => apiCall(`/${orgId}/documents/${docId}/versions`),
    didJson:       (orgId, docId) => apiCall(`/${orgId}/documents/${docId}/did.json`),
  };
})();


// ── Document-specific helpers ─────────────────────────────────────────

function docStatusBadge(status) {
  const map = {
    DRAFT:          { cls: "member",      label: "Draft" },
    PENDING_REVIEW: { cls: "invited",     label: "Pending Review" },
    APPROVED:       { cls: "active",      label: "Approved" },
    REJECTED:       { cls: "deactivated", label: "Rejected" },
    SIGNED:         { cls: "active",      label: "Signed" },
    PUBLISHED:      { cls: "active",      label: "Published" },
    DEACTIVATED:    { cls: "deactivated", label: "Deactivated" },
  };
  const { cls, label } = map[status] || { cls: "", label: status };
  return `<span class="oa-badge ${cls}">${label}</span>`;
}

function relBadges(relationships) {
  if (!relationships || !relationships.length) return "—";
  const short = {
    authentication: "Auth",
    assertionMethod: "Assert",
    keyAgreement: "KeyAgr",
    capabilityInvocation: "CapInv",
    capabilityDelegation: "CapDel",
  };
  return relationships.map(r =>
    `<span class="doc-rel-badge">${short[r] || r}</span>`
  ).join(" ");
}

function vmStatusDot(isActive) {
  return isActive
    ? '<span style="color:var(--oa-success);font-size:0.75rem;">● Active</span>'
    : '<span style="color:var(--oa-error);font-size:0.75rem;">● Revoked</span>';
}

/**
 * Generate a QR code as a canvas element using a minimal QR library.
 * Falls back to a Google Charts API URL if canvas is not available.
 */
function generateQRCodeURL(text, size = 256) {
  // Use Google Charts QR API as a simple, no-dependency solution
  return `https://chart.googleapis.com/chart?cht=qr&chs=${size}x${size}&chl=${encodeURIComponent(text)}&choe=UTF-8`;
}

function downloadQRCode(did_uri, label) {
  const url = generateQRCodeURL(did_uri, 512);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${label}-qrcode.png`;
  link.target = "_blank";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
