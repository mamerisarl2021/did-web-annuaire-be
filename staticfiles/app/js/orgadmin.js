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
    getStats: (orgOrId, scope) => apiCall(`/organizations/${orgOrId?.id || orgOrId}/stats${scope ? `?scope=${scope}` : ""}`),
    listMembers: (orgOrId) => apiCall(`/organizations/${orgOrId?.id || orgOrId}/members`),
    listAudits: (orgOrId, page = 1) => apiCall(`/organizations/${orgOrId?.id || orgOrId}/audits?page=${page}`),
    inviteMember: (orgId, data) => apiCall(`/organizations/${orgId}/members/invite`, { method: "POST", body: data }),
    changeRole: (orgId, memberId, role) => apiCall(`/organizations/${orgId}/members/${memberId}/role`, { method: "PUT", body: { role } }),
    updateMember: (orgId, memberId, data) => apiCall(`/organizations/${orgId}/members/${memberId}`, { method: "PATCH", body: data }),
    deactivateMember: (orgId, memberId) => apiCall(`/organizations/${orgId}/members/${memberId}/deactivate`, { method: "POST" }),
    cancelInvitation: (orgId, memberId) => apiCall(`/organizations/${orgId}/members/${memberId}/cancel`, { method: "POST" }),
    reactivateMember: (orgId, memberId) => apiCall(`/organizations/${orgId}/members/${memberId}/reactivate`, { method: "POST" }),
    updateOrg: (id, data) => apiCall(`/organizations/${id}`, { method: "PATCH", body: data }),
  };
})();

// ── User profile update (PATCH /api/v2/auth/me) ─────────────────────────

async function oaUpdateMe(data) {
  const { access } = Auth.getTokens();
  const res = await fetch("/api/v2/auth/me", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${access}`,
    },
    body: JSON.stringify(data),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw { status: res.status, detail: json.detail || "Update failed." };
  return json;
}

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