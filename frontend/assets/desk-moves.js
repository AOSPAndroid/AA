(() => {
  const $ = (id) => document.getElementById(id);
  let stage = null,
    working = false;
  async function api(path, body, json = false) {
    const token = (await (await fetch("/api/session")).json()).token;
    const r = await fetch(path, {
      method: "POST",
      headers: {
        "X-Atlas-Token": token,
        ...(json ? { "Content-Type": "application/json" } : {}),
      },
      body: json ? JSON.stringify(body) : body,
    });
    const d = await r.json();
    if (!r.ok) throw Error(d.detail || "Request failed");
    return d;
  }
  function controls() {
    $("moves-preview").disabled = working;
    $("moves-file").disabled = working;
    $("moves-apply").disabled =
      working || !stage || $("moves-confirm").value !== "MOVE";
  }
  async function task(fn) {
    if (working) return;
    working = true;
    controls();
    try {
      await fn();
    } catch (e) {
      $("moves-message").textContent = e.message;
    } finally {
      working = false;
      controls();
    }
  }
  $("moves-preview").onclick = () =>
    task(async () => {
      const f = $("moves-file").files[0];
      if (!f) throw Error("Choose the edited desk workbook.");
      stage = null;
      $("moves-result").hidden = true;
      $("moves-message").textContent = "Checking moves…";
      const d = await api("/api/desk-moves/preview", f);
      stage = d.id;
      $("moves-summary").textContent = d.moves
        .map((m) => `${m.person}: ${m.from} → ${m.to}`)
        .join("\n");
      $("moves-result").hidden = false;
      $("moves-confirm").value = "";
      $("moves-message").textContent =
        `${d.moves.length} moves ready for review. Nothing has changed yet.`;
    });
  $("moves-confirm").oninput = controls;
  $("moves-file").onchange = () => {
    stage = null;
    $("moves-result").hidden = true;
    controls();
  };
  $("moves-apply").onclick = () =>
    task(async () => {
      $("moves-message").textContent = "Backing up and applying moves…";
      const d = await api(
        "/api/desk-moves/apply/" + stage,
        { confirmation: $("moves-confirm").value },
        true,
      );
      stage = null;
      $("moves-result").hidden = true;
      $("moves-message").textContent =
        `${d.moves} moves applied. Backup: ${d.backup}. Reload the Atlas to see the updated seating.`;
    });
})();
