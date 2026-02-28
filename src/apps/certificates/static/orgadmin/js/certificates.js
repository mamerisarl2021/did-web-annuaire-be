/**
 * Certificate API module.
 * Appended to the orgadmin.js loaded in the workspace.
 */

const CertAPI = (() => {
  const API = "/api/v2/org/organizations";

  /**
   * Extract a human-readable error message from a Ninja API error response.
   *
   * Ninja validation errors (422) return detail as an array:
   *   [{"loc": ["path","org_id"], "msg": "...", "type": "..."}]
   *
   * Normal errors return detail as a string:
   *   {"detail": "Not found."}
   */
  function extractDetail(data) {
    const d = data?.detail;
    if (!d) return data?.message || "Something went wrong.";
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      // Ninja validation error — join the messages
      return d.map(e => {
        const loc = e.loc ? e.loc.filter(l => l !== "body").join(" → ") : "";
        const msg = e.msg || "Validation error";
        return loc ? `${loc}: ${msg}` : msg;
      }).join("; ");
    }
    // Fallback for unexpected shapes
    try { return JSON.stringify(d); } catch { return "Something went wrong."; }
  }

  async function apiCall(path, { method = "GET", body, isForm = false } = {}) {
    const headers = {};
    const { access } = Auth.getTokens();
    if (access) headers["Authorization"] = `Bearer ${access}`;

    let fetchBody;
    if (isForm && body instanceof FormData) {
      fetchBody = body;
      // Don't set Content-Type — browser sets it with boundary
    } else if (body) {
      headers["Content-Type"] = "application/json";
      fetchBody = JSON.stringify(body);
    }

    const res = await fetch(`${API}${path}`, {
      method,
      headers,
      body: fetchBody,
    });

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
    list: (orgId) => apiCall(`/${orgId}/certificates`),
    get: (orgId, certId) => apiCall(`/${orgId}/certificates/${certId}`),
    upload: (orgId, formData) => apiCall(`/${orgId}/certificates/upload`, {
      method: "POST", body: formData, isForm: true,
    }),
    rotate: (orgId, certId, formData) => apiCall(`/${orgId}/certificates/${certId}/rotate`, {
      method: "POST", body: formData, isForm: true,
    }),
    revoke: (orgId, certId, reason) => apiCall(`/${orgId}/certificates/${certId}/revoke`, {
      method: "POST", body: { reason },
    }),
    versions: (orgId, certId) => apiCall(`/${orgId}/certificates/${certId}/versions`),
    version: (orgId, certId, verId) => apiCall(`/${orgId}/certificates/${certId}/versions/${verId}`),
  };
})();

// ── Certificate-specific helpers ────────────────────────────────────────

function certStatusBadge(status) {
  const cls = { ACTIVE: "active", REVOKED: "deactivated", EXPIRED: "invited" }[status] || "";
  return `<span class="oa-badge ${cls}">${status}</span>`;
}

function keyLabel(type, curve, size) {
  if (type === "EC") return `${type} ${curve || ""}`.trim();
  if (type === "RSA") return `${type}-${size || "?"}`;
  return type || "—";
}

function truncateDN(dn, maxLen = 40) {
  if (!dn) return "—";
  // Extract CN if present
  const cnMatch = dn.match(/CN=([^,]+)/);
  if (cnMatch) return cnMatch[1].length > maxLen ? cnMatch[1].substring(0, maxLen) + "…" : cnMatch[1];
  return dn.length > maxLen ? dn.substring(0, maxLen) + "…" : dn;
}

function formatFingerprint(fp) {
  if (!fp) return "—";
  // Show first 16 chars with colons
  return fp.substring(0, 16).match(/.{2}/g)?.join(":") + "…" || fp;
}

function isExpired(notValidAfter) {
  if (!notValidAfter) return false;
  return new Date(notValidAfter) < new Date();
}

function daysUntilExpiry(notValidAfter) {
  if (!notValidAfter) return null;
  const diff = new Date(notValidAfter) - new Date();
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}