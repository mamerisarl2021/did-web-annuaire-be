/**
 * Annuaire DID — Auth & API module.
 *
 * Stores JWT in localStorage. Injects Authorization header into every
 * HTMX request via the htmx:configRequest event. Provides helpers for
 * login, register, logout, password reset, and activation.
 */

const Auth = (() => {
  const API = "/api/v2";
  const STORAGE_KEY = "annuaire_tokens";

  // ── Token management ──────────────────────────────────────────────

  function getTokens() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    } catch {
      return {};
    }
  }

  function setTokens(access, refresh) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ access, refresh }));
  }

  function clearTokens() {
    localStorage.removeItem(STORAGE_KEY);
  }

  function isLoggedIn() {
    return !!getTokens().access;
  }

  // ── HTMX integration ─────────────────────────────────────────────
  // Inject Bearer token into every HTMX request targeting the API.

  document.addEventListener("htmx:configRequest", (e) => {
    const { access } = getTokens();
    if (access) {
      e.detail.headers["Authorization"] = `Bearer ${access}`;
    }
  });

  // On 401, redirect to login.
  document.addEventListener("htmx:responseError", (e) => {
    if (e.detail.xhr.status === 401) {
      clearTokens();
      window.location.href = "/login/";
    }
  });

  // ── API helper ────────────────────────────────────────────────────

  async function apiCall(path, { method = "GET", body, isForm = false } = {}) {
    const headers = {};
    const { access } = getTokens();
    if (access) headers["Authorization"] = `Bearer ${access}`;
    if (!isForm) headers["Content-Type"] = "application/json";

    const res = await fetch(`${API}${path}`, {
      method,
      headers,
      body: isForm ? body : body ? JSON.stringify(body) : undefined,
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw { status: res.status, detail: data.detail || "Something went wrong." };
    }
    return data;
  }

  // ── Auth actions ──────────────────────────────────────────────────

  async function login(email, password) {
    const data = await apiCall("/token/pair", {
      method: "POST",
      body: { email, password },
    });
    setTokens(data.access, data.refresh);
    return data;
  }

  async function register(formData) {
    return apiCall("/auth/register", {
      method: "POST",
      body: formData,
      isForm: true,
    });
  }

  async function logout() {
    const { refresh } = getTokens();
    if (refresh) {
      try {
        await apiCall("/auth/logout", {
          method: "POST",
          body: { refresh },
        });
      } catch {}
    }
    clearTokens();
  }

  async function me() {
    return apiCall("/auth/me");
  }

  async function activateSetup(token) {
    return apiCall(`/auth/activate/${token}`);
  }

  async function activateVerify(token, otpCode) {
    const data = await apiCall(`/auth/activate/${token}/verify`, {
      method: "POST",
      body: { otp_code: otpCode },
    });
    if (data.access && data.refresh) {
      setTokens(data.access, data.refresh);
    }
    return data;
  }

  async function passwordReset(email) {
    return apiCall("/auth/password-reset", {
      method: "POST",
      body: { email },
    });
  }

  async function passwordResetConfirm(token, newPassword) {
    return apiCall("/auth/password-reset/confirm", {
      method: "POST",
      body: { token, new_password: newPassword },
    });
  }

  async function passwordChange(oldPassword, newPassword) {
    return apiCall("/auth/password-change", {
      method: "POST",
      body: { old_password: oldPassword, new_password: newPassword },
    });
  }

  return {
    getTokens, setTokens, clearTokens, isLoggedIn,
    login, register, logout, me,
    activateSetup, activateVerify,
    passwordReset, passwordResetConfirm, passwordChange,
  };
})();


// ── UI Helpers ──────────────────────────────────────────────────────────

function showAlert(containerId, message, type = "error") {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = `<div class="alert alert-${type}">${message}</div>`;
}

function clearAlert(containerId) {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = "";
}

function setLoading(btn, loading) {
  btn.disabled = loading;
  const label = btn.querySelector(".btn-label");
  const spinner = btn.querySelector(".htmx-indicator");
  if (label) label.style.display = loading ? "none" : "inline";
  if (spinner) spinner.style.display = loading ? "inline-block" : "none";
}

function autoSlug(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}