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
        try {
            return JSON.stringify(d);
        } catch {
            return "Something went wrong.";
        }
    }

    async function apiCall(path, {method = "GET", body} = {}) {
        const headers = {"Content-Type": "application/json"};
        const {access} = Auth.getTokens();
        if (access) headers["Authorization"] = `Bearer ${access}`;

        const res = await fetch(`${API}${path}`, {
            method,
            headers,
            body: body ? JSON.stringify(body) : undefined,
        });

        if (res.status === 204) return {};

        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (res.status === 401) {
                Auth.clearTokens();
                window.location.href = "/login/";
                return;
            }
            throw {status: res.status, detail: extractDetail(data)};
        }
        return data;
    }

    return {
        list: (orgId) => apiCall(`/${orgId}/documents`),
        create: (orgId, data) => apiCall(`/${orgId}/documents`, {method: "POST", body: data}),
        get: (orgId, docId) => apiCall(`/${orgId}/documents/${docId}`),
        updateDraft: (orgId, docId, data) => apiCall(`/${orgId}/documents/${docId}/draft`, {
            method: "PATCH",
            body: data
        }),
        addVM: (orgId, docId, data) => apiCall(`/${orgId}/documents/${docId}/verification-methods`, {
            method: "POST",
            body: data
        }),
        removeVM: (orgId, docId, vmId) => apiCall(`/${orgId}/documents/${docId}/verification-methods/${vmId}`, {method: "DELETE"}),
        submit: (orgId, docId) => apiCall(`/${orgId}/documents/${docId}/submit`, {method: "POST", body: {}}),
        approve: (orgId, docId, comment) => apiCall(`/${orgId}/documents/${docId}/approve`, {
            method: "POST",
            body: {comment}
        }),
        reject: (orgId, docId, comment) => apiCall(`/${orgId}/documents/${docId}/reject`, {
            method: "POST",
            body: {comment}
        }),
        publish: (orgId, docId) => apiCall(`/${orgId}/documents/${docId}/publish`, {method: "POST", body: {}}),
        deactivate: (orgId, docId, reason) => apiCall(`/${orgId}/documents/${docId}/deactivate`, {
            method: "POST",
            body: {reason}
        }),
        pendingReview: (orgId) => apiCall(`/${orgId}/documents/pending-review`),
        versions: (orgId, docId) => apiCall(`/${orgId}/documents/${docId}/versions`),
        didJson: (orgId, docId) => apiCall(`/${orgId}/documents/${docId}/did.json`),
        vcJson: (orgId, docId) => apiCall(`/${orgId}/documents/${docId}/vc.json`),
    };
})();


// ── Document-specific helpers ─────────────────────────────────────────

function docStatusBadge(status) {
    const map = {
        DRAFT: {cls: "member", label: "Draft"},
        PENDING_REVIEW: {cls: "invited", label: "Pending Review"},
        APPROVED: {cls: "active", label: "Approved"},
        REJECTED: {cls: "deactivated", label: "Rejected"},
        SIGNED: {cls: "active", label: "Signed"},
        PUBLISHED: {cls: "active", label: "Published"},
        DEACTIVATED: {cls: "deactivated", label: "Deactivated"},
    };
    const {cls, label} = map[status] || {cls: "", label: status};
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
 * Generate a QR code image URL.
 * Uses the free goqr.me API (Google Charts API was shut down).
 */
function generateQRCodeURL(text, size = 256) {
    return `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&data=${encodeURIComponent(text)}&format=png`;
}

function downloadQRCode(did_uri, label) {
    const url = generateQRCodeURL(did_uri, 512);
    // Fetch the image as a blob so the download works cross-origin
    fetch(url)
        .then(res => res.blob())
        .then(blob => {
            const blobUrl = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = blobUrl;
            link.download = `${label}-qrcode.png`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(blobUrl);
        })
        .catch(() => {
            // Fallback: open in new tab
            window.open(url, "_blank");
        });
}