/**
 * Org Admin API module.
 * Reuses Auth from auth.js for token management.
 */

const OA = (() => {
  const API = "/api/v2/org";

  async function apiCall(path, { method = "GET", body } = {}) {
    const headers = { "Content-Type": "application/json" };
    const { access } = Auth.getTokens();
    if (access) headers["Authorization"] = `Bearer ${access}`;

    const res = await fetch(`${API}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401) {
        Auth.clearTokens();
        window.location.href = "/login/";
        return;
      }
      throw { status: res.status, detail: data.detail || "Something went wrong." };
    }
    return data;
  }

  return {
    listOrgs: () => apiCall("/organizations"),
    getOrg: (id) => apiCall(`/organizations/${id}`),
    getStats: (id) => apiCall(`/organizations/${id}/stats`),
    listMembers: (id) => apiCall(`/organizations/${id}/members`),
    inviteMember: (orgId, data) => apiCall(`/organizations/${orgId}/members/invite`, { method: "POST", body: data }),
    changeRole: (orgId, memberId, role) => apiCall(`/organizations/${orgId}/members/${memberId}/role`, { method: "PUT", body: { role } }),
    deactivateMember: (orgId, memberId) => apiCall(`/organizations/${orgId}/members/${memberId}/deactivate`, { method: "POST" }),
  };
})();

// ── UI helpers ──────────────────────────────────────────────────────────

function oaAlert(containerId, msg, type = "error") {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = `<div class="oa-alert oa-alert-${type}">${msg}</div>`;
}

function oaClearAlert(id) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = "";
}

function oaFormatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function roleBadge(role) {
  const cls = { ORG_ADMIN: "admin", ORG_MEMBER: "member", AUDITOR: "auditor" }[role] || "member";
  const label = { ORG_ADMIN: "Admin", ORG_MEMBER: "Member", AUDITOR: "Auditor" }[role] || role;
  return `<span class="oa-badge ${cls}">${label}</span>`;
}

function statusBadge(status) {
  const cls = { ACTIVE: "active", INVITED: "invited", PENDING_ACTIVATION: "invited", DEACTIVATED: "deactivated" }[status] || "";
  const label = { ACTIVE: "Active", INVITED: "Invited", PENDING_ACTIVATION: "Pending", DEACTIVATED: "Deactivated" }[status] || status;
  return `<span class="oa-badge ${cls}">${label}</span>`;
}

// ── Org context (stored per session) ────────────────────────────────────

function setCurrentOrg(org) {
  sessionStorage.setItem("current_org", JSON.stringify(org));
}

function getCurrentOrg() {
  try { return JSON.parse(sessionStorage.getItem("current_org")); } catch { return null; }
}
