/* Shared transport, immutable selections, and one polling owner per resource. */
(() => {
  let session;
  let loadingCount = 0,
    loadingTimer,
    loadingBadge;
  function beginLoading() {
    loadingCount++;
    if (loadingCount === 1)
      loadingTimer = setTimeout(() => {
        if (!loadingCount || !document.body) return;
        if (!loadingBadge) {
          loadingBadge = document.createElement("div");
          loadingBadge.className = "atlas-request-loading atlas-loading-inline";
          loadingBadge.setAttribute("role", "status");
          loadingBadge.textContent = "Loading…";
          document.body.append(loadingBadge);
        }
        loadingBadge.hidden = false;
      }, 180);
    let ended = false;
    return () => {
      if (ended) return;
      ended = true;
      loadingCount = Math.max(0, loadingCount - 1);
      if (!loadingCount) {
        clearTimeout(loadingTimer);
        if (loadingBadge) loadingBadge.hidden = true;
      }
    };
  }
  async function sessionToken() {
    if (!session)
      session = fetch("/api/session", { cache: "no-store" })
        .then(async (response) => {
          if (!response.ok) throw Error("Reload Atlas to establish a session.");
          return (await response.json()).token;
        })
        .catch((error) => {
          session = null;
          throw error;
        });
    return session;
  }
  async function rawRequest(url, options = {}) {
    const local = window.AtlasReadOnly?.read(url, options);
    if (local) return local.data;
    const headers = new Headers(options.headers || {});
    const method = (options.method || "GET").toUpperCase();
    if (!["GET", "HEAD"].includes(method) && !headers.has("X-Atlas-Token"))
      headers.set("X-Atlas-Token", await sessionToken());
    const response = await fetch(url, { ...options, headers });
    let data;
    try {
      data = await response.json();
    } catch {
      throw Error(`Request failed (${response.status}).`);
    }
    if (!response.ok) {
      if (response.status === 403) session = null;
      // Form checks (422) list each refused field; name it instead of a bare status code.
      const fields = Array.isArray(data.detail)
        ? data.detail.map((item) => `${(item.loc || []).slice(1).join(".") || "value"}: ${item.msg}`).join("; ")
        : "";
      throw Error(
        typeof data.detail === "string"
          ? data.detail
          : fields ? `Atlas could not accept this value. ${fields}` : data.error || `Request failed (${response.status}).`,
      );
    }
    return data;
  }
  async function request(url, options = {}) {
    const { atlasSilent = false, ...transport } = options;
    const endLoading = atlasSilent ? () => {} : beginLoading();
    const tracked =
      /^\/api\/(deploy$|bulk\/deploy$|queue$|(?:personas|joiners)\/[a-f0-9]+\/install$|psexec\/run$|terminal\/run$|software-tools\/(inventory|uninstall)$|performance\/|processes\/|services(?:\/stop)?$|remote-registry\/enable$|kill$|cleanup-packages\/|ping\/|disk\/|overview\/|access\/|preflight\/|open-tool\/)/.test(
        url,
      );
    if (tracked)
      window.dispatchEvent(
        new CustomEvent("atlas:activity", { detail: { open: false } }),
      );
    try {
      return await rawRequest(url, transport);
    } finally {
      endLoading();
      if (tracked)
        window.dispatchEvent(
          new CustomEvent("atlas:activity", {
            detail: {
              open:
                options.method === "POST" &&
                /^\/api\/(deploy$|bulk\/deploy$|queue$|(?:personas|joiners)\/[a-f0-9]+\/install$|psexec\/run$|terminal\/run$|software-tools\/uninstall$)/.test(
                  url,
                ),
            },
          }),
        );
    }
  }
  const watchers = new Map();
  const terminal = new Set([
    "launched",
    "complete",
    "failed",
    "cancelled",
    "interrupted",
    "unknown",
  ]);
  function watch(
    key,
    url,
    onData,
    {
      done = (data) => terminal.has(data.state),
      interval = 1500,
      onError = () => {},
    } = {},
  ) {
    watchers.get(key)?.();
    let timer,
      controller,
      stopped = false,
      failures = 0;
    function stop() {
      stopped = true;
      clearTimeout(timer);
      controller?.abort();
      if (watchers.get(key) === stop) watchers.delete(key);
    }
    async function tick() {
      controller = new AbortController();
      try {
        const data = await request(url, {
          signal: controller.signal,
          atlasSilent: true,
        });
        if (stopped) return;
        failures = 0;
        await onData(data);
        if (done(data)) {
          stop();
          return;
        }
      } catch (error) {
        if (stopped) return;
        failures++;
        onError(error);
        if (failures >= 8) {
          stop();
          return;
        }
      }
      if (!stopped)
        timer = setTimeout(tick, Math.min(30000, interval * 2 ** failures));
    }
    watchers.set(key, stop);
    tick();
    return stop;
  }
  function latest() {
    let version = 0,
      controller;
    return () => {
      controller?.abort();
      controller = new AbortController();
      const current = ++version;
      return { signal: controller.signal, current: () => current === version };
    };
  }
  let deskEtag,
    desks = [],
    deskRequest;
  async function deskIndex() {
    if (deskRequest) return deskRequest;
    deskRequest = (async () => {
      const response = await fetch("/api/palette/desks", {
        headers: deskEtag ? { "If-None-Match": deskEtag } : {},
        cache: "no-cache",
      });
      if (response.status === 304) return desks;
      if (!response.ok) throw Error("Map records unavailable.");
      desks = (await response.json()).records;
      deskEtag = response.headers.get("etag");
      return desks;
    })().finally(() => {
      deskRequest = null;
    });
    return deskRequest;
  }
  window.addEventListener("pagehide", () => {
    for (const stop of [...watchers.values()]) stop();
  });
  window.AtlasClient = {
    request,
    sessionToken,
    watch,
    latest,
    deskIndex,
    snapshot: (value) => Object.freeze({ ...value }),
    terminal,
  };
})();
