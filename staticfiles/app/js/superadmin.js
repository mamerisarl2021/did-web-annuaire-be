/**
 * Superadmin API module.
 * Reuses Auth from auth.js for token management.
 */

const SA = (() => {
  const API = "/superadmin/api/v2";

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
      if (res.status === 403) {
        window.location.href = "/dashboard/";
        return;
      }
      throw { status: res.status, detail: data.detail || "Something went wrong." };
    }
    return data;
  }

  return {
    dashboard: () => apiCall("/dashboard"),
    listOrgs: (status) => apiCall(`/organizations${status ? `?status=${status}` : ""}`),
    getOrg: (id) => apiCall(`/organizations/${id}`),
    approveOrg: (id) => apiCall(`/organizations/${id}/approve`, { method: "POST" }),
    rejectOrg: (id, reason) => apiCall(`/organizations/${id}/reject`, { method: "POST", body: { reason } }),
    suspendOrg: (id, reason) => apiCall(`/organizations/${id}/suspend`, { method: "POST", body: { reason } }),
  };
})();

// ── UI helpers ──────────────────────────────────────────────────────────

function saShowAlert(containerId, message, type = "error") {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = `<div class="sa-alert sa-alert-${type}">${message}</div>`;
}

function saClearAlert(containerId) {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = "";
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function formatFileSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function badgeClass(status) {
  return {
    PENDING_REVIEW: "pending",
    APPROVED: "approved",
    REJECTED: "rejected",
    SUSPENDED: "suspended",
  }[status] || "";
}

function badgeLabel(status) {
  return {
    PENDING_REVIEW: "Pending",
    APPROVED: "Approved",
    REJECTED: "Rejected",
    SUSPENDED: "Suspended",
  }[status] || status;
}