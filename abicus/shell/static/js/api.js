(() => {
  async function wrap(p) {
    let r;
    try {
      r = await p;
    } catch (err) {
      toast(`Network error: ${err.message}`, "error");
      throw err;
    }
    if (!r.ok) {
      const text = await r.text();
      const msg = text || `${r.status} ${r.statusText}`;
      toast(msg, "error");
      throw new Error(msg);
    }
    return r;
  }

  function ensureJSON(r) {
    return r.json();
  }

  async function triggerSave(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "download";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function inferFilename(r, fallback) {
    const cd = r.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)/i);
    if (m) return decodeURIComponent(m[1]);
    return fallback || "download";
  }

  const api = {
    async get(url) {
      const r = await wrap(fetch(url));
      return ensureJSON(r);
    },
    async getRaw(url) {
      return wrap(fetch(url));
    },
    async postJson(url, body) {
      const r = await wrap(fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }));
      return ensureJSON(r);
    },
    async postForm(url, formData) {
      const r = await wrap(fetch(url, { method: "POST", body: formData }));
      return ensureJSON(r);
    },
    async putJson(url, body) {
      const r = await wrap(fetch(url, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }));
      return ensureJSON(r);
    },
    async putForm(url, formData) {
      const r = await wrap(fetch(url, { method: "PUT", body: formData }));
      return ensureJSON(r);
    },
    async del(url) {
      const r = await wrap(fetch(url, { method: "DELETE" }));
      if (r.status === 204) return null;
      const text = await r.text();
      return text ? JSON.parse(text) : null;
    },
    async download(url, { method = "POST", body, fallbackName } = {}) {
      const init = { method };
      if (body !== undefined) {
        if (body instanceof FormData) {
          init.body = body;
        } else {
          init.headers = { "Content-Type": "application/json" };
          init.body = JSON.stringify(body);
        }
      }
      const r = await wrap(fetch(url, init));
      const blob = await r.blob();
      await triggerSave(blob, inferFilename(r, fallbackName));
    },
  };

  function toast(message, kind = "info", ttl = 4000) {
    const root = document.getElementById("toasts");
    if (!root) return;
    const el = document.createElement("div");
    el.className = `toast toast--${kind}`;
    el.textContent = message;
    root.appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity 200ms";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 220);
    }, ttl);
  }

  window.api = api;
  window.toast = toast;
})();
