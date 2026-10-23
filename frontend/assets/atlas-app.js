/* Local app installation and opt-in, count-only alerts shared by Classic/Desktop. */
(() => {
  "use strict";
  if (window.parent !== window) {
    try { window.AtlasApp = window.parent.AtlasApp; } catch {}
    return;
  }
  const enabledKey = "atlas-desktop-alerts", cursorKey = "atlas-alert-cursor";
  const listeners = new Set();
  let installPrompt, registration, timer, initial = true, stopped = false, busy = false;
  const state = { available: false, supported: false, enabled: false, installed: false, error: "", status: "Checking app support…" };
  function emit() { for (const listener of listeners) listener({ ...state }); }
  function saved() { try { return localStorage.getItem(enabledKey) === "on"; } catch { return false; } }
  function refresh() {
    state.enabled = saved() && window.Notification?.permission === "granted";
    state.installed = window.matchMedia("(display-mode: standalone)").matches;
    emit();
  }
  function openInbox() {
    if (document.querySelector("#inbox"))
      window.dispatchEvent(new Event("atlas:open-inbox"));
    else location.assign("/installer?command=inbox");
  }
  window.AtlasApp = {
    snapshot: () => ({ ...state }),
    subscribe(listener) { listeners.add(listener); listener({ ...state }); return () => listeners.delete(listener); },
    async install() {
      if (!state.available) return;
      state.error = "";
      if (!installPrompt) { state.status = "In Edge, open the browser menu → More tools → Apps → Install this site as an app. Your browser or work policy may restrict installation."; emit(); return; }
      const prompt = installPrompt; installPrompt = null;
      try { await prompt.prompt(); await prompt.userChoice; }
      catch { state.error = "The browser could not open installation. Use its Apps menu."; }
      refresh();
    },
    async setAlerts(value) {
      if (busy) return;
      busy = true; state.error = "";
      try {
        if (value) {
          if (!state.supported) throw Error("Open local Atlas in Edge or Chrome to enable desktop alerts.");
          // This call runs directly from the switch gesture, including a same-origin Desktop frame.
          const permission = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
          if (permission !== "granted") throw Error("Notifications were not allowed. Enable them in this site's browser permissions, then try again.");
        }
        localStorage.setItem(enabledKey, value ? "on" : "off");
        initial = true;
        state.status = value ? "Alerts on while Atlas is open. Existing messages are skipped." : "Atlas desktop alerts off.";
        if (!value && registration) {
          const notes = await registration.getNotifications({ tag: "atlas-inbox-arrivals" });
          notes.forEach(note => note.close());
        }
      } catch (error) { state.error = error.message; }
      finally { busy = false; refresh(); }
    },
  };
  window.addEventListener("beforeinstallprompt", event => { event.preventDefault(); installPrompt = event; emit(); });
  window.addEventListener("appinstalled", () => { state.installed = true; installPrompt = null; state.status = "Atlas app installed."; emit(); });
  window.addEventListener("storage", event => { if (event.key === enabledKey || event.key === null) { initial = true; refresh(); } });
  window.addEventListener("focus", refresh);
  navigator.serviceWorker?.addEventListener("message", event => { if (event.data?.type === "atlas-open-inbox") openInbox(); });
  window.addEventListener("pagehide", () => { stopped = true; clearTimeout(timer); });
  window.addEventListener("pageshow", event => { if (event.persisted) { stopped = false; initial = true; poll(); } });

  async function poll() {
    try {
      if (state.available && state.supported && saved() && Notification.permission === "granted") {
        // One poll/alert across all Atlas windows in this browser profile.
        await navigator.locks.request("atlas-inbox-alerts", { ifAvailable: true }, async lock => {
          if (!lock || stopped) return;
          const stored = Number(localStorage.getItem(cursorKey)) || 0;
          const response = await fetch("/api/inbox/arrivals?after_id=" + stored, { cache: "no-store", signal: AbortSignal.timeout(10000) });
          if (!response.ok) throw Error("Atlas is unavailable. Desktop alerts will retry when it reconnects.");
          const data = await response.json();
          if (!Number.isSafeInteger(data.newest_id) || !Number.isSafeInteger(data.count) || data.newest_id < 0 || data.count < 0) throw Error("Atlas returned an invalid arrival count.");
          if (stopped || !saved() || Notification.permission !== "granted") return;
          if (!initial && data.newest_id > stored && data.count > 0) {
            await registration.showNotification("Atlas · " + data.count + " new " + (data.count === 1 ? "item" : "items"), {
              body: "Open Live Inbox to see the sender and linked machines.",
              tag: "atlas-inbox-arrivals", renotify: true, icon: "/assets/atlas-icon-192.png",
            });
          }
          localStorage.setItem(cursorKey, String(data.newest_id));
          initial = false;
          state.error = "";
          state.status = "Alerts on while Atlas is open. Mail content stays inside Atlas.";
          refresh();
        });
      }
    } catch (error) { state.error = error.message; emit(); }
    if (!stopped) timer = setTimeout(poll, 5000);
  }
  async function boot() {
    if (document.querySelector('meta[name="atlas-mode"]')?.content === "viewer") { state.status = "App controls are available in local Atlas Admin."; emit(); return; }
    try {
      const response = await fetch("/api/app", { cache: "no-store", signal: AbortSignal.timeout(10000) });
      if (!response.ok || (await response.json()).mode !== "admin") throw Error("Open local Atlas Admin for app controls.");
      if (!window.isSecureContext) throw Error("Use local Atlas at 127.0.0.1 or localhost, or an HTTPS address.");
      state.available = true;
      const manifest = document.createElement("link"); manifest.rel = "manifest"; manifest.href = "/atlas.webmanifest"; document.head.append(manifest);
      state.status = "Install Atlas for its own window and taskbar icon. Keep the Atlas server running.";
      if (navigator.serviceWorker) {
        await navigator.serviceWorker.register("/atlas-sw.js", { scope: "/", updateViaCache: "none" });
        registration = await navigator.serviceWorker.ready;
      }
      state.supported = !!(registration && window.Notification && navigator.locks);
      if (!state.supported) state.status = "Desktop alerts need Edge or Chrome with notifications and service workers enabled.";
      refresh();
      poll();
    } catch (error) { state.error = error.message; state.status = "Atlas app controls unavailable."; emit(); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true }); else boot();
})();
