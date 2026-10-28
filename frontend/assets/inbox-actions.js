/* Live Inbox actions: a request's tools open beside the message (inbox-workbench.js), so the
   person, health, performance, AD groups, deployment and articles never leave Live Inbox.
   Outside Live Inbox the normal Workspace tools are used. Every action needs a click. Reboots keep their
   confirmation, and nothing deploys until Install or Start queue is clicked. */
(() => {
  const openQueue = () => document.querySelector("#queueDrawer")?.classList.add("open");
  const work = (detail, tab, mode) => !!window.AtlasInboxWork?.open(detail, tab, mode);

  // Makes the request's person and machine Atlas's current selection, without changing page.
  async function focus({ user, machine }) {
    if (user?.id && S.user?.id !== user.id) await loadUser("id:" + user.id);
    if (machine) {
      setTarget(machine, "Live inbox request", false);
      if (S.target !== String(machine).toUpperCase())
        throw Error(`${machine} is inventory only; Windows tools need a PC.`);
    }
  }

  async function choosePackage(pkg, action) {
    const select = document.querySelector("#pkg");
    if (![...select.options].some((option) => option.value === pkg.folder))
      select.add(new Option(pkg.display_name || pkg.folder, pkg.folder));
    select.value = pkg.folder;
    commitPackageChoice();
    document.querySelector("#action").value = action || "Install";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await scripts();
    if (!document.querySelector("#script").value)
      throw Error(`No ${action || "Install"} script was found in ${pkg.display_name || pkg.folder}.`);
  }

  async function run(detail = {}) {
    if (window.AtlasReadOnly) throw Error("Live Inbox actions are available in Atlas Admin.");
    const { action, machine, user, pkg, deployAction = "Install" } = detail;
    switch (action) {
      case "target":
        await focus(detail);
        if (!work(detail, "health", "quick")) page("workspace");
        return toast(`${S.target} selected for ${user?.full_name || user?.name || "this request"}`);
      case "health":
        await focus(detail);
        if (work(detail, "health", "scan")) return;
        page("workspace");
        return refreshTargetHealth(true);
      case "performance":
        await focus(detail);
        if (!work(detail, "performance", "scan")) page("admin");
        return;
      case "person":
        if (!user?.id) throw Error("This person is not in the Atlas directory.");
        if (work({ user, ...(machine === undefined ? {} : { machine }) }, "person")) return;
        page("workspace");
        return loadUser("id:" + user.id);
      case "user-groups":
        if (!user?.user_name && !user?.email) throw Error("No AD account is known for this sender.");
        if (work({ user, ...(machine === undefined ? {} : { machine }) }, "user-groups", "scan")) return;
        return window.AtlasAD.show("user", user.user_name || user.email);
      case "machine-groups":
        await focus(detail);
        if (work(detail, "machine-groups", "scan")) return;
        return window.AtlasAD.show("computer", S.target);
      case "reboot":
        await focus(detail);
        if (!confirm("Reboot " + S.target + "?")) return;
        await window.AtlasReboots.start(S.target);
        return openQueue();
      case "deploy":
        await focus(detail);
        if (!work(detail, "deploy")) page("workspace");
        await choosePackage(pkg, deployAction);
        openDeploymentPanel();
        return toast(`${pkg.display_name || pkg.folder} ready for ${S.target}. Check the script, then click ${deployAction}.`);
      case "queue":
        await focus(detail);
        await choosePackage(pkg, deployAction);
        addQueue();
        return openQueue();
      case "search": {
        await focus(detail);
        if (!work(detail, "deploy")) page("workspace");
        openDeploymentPanel();
        document.querySelector("#pkgSearch").value = detail.term || "";
        document.querySelector("#packagePicker").open = true;
        return packages();
      }
      case "persona":
        await focus(detail);
        window.AtlasPersonas.addToQueue(detail.persona);
        return openQueue();
      case "knowledge":
        // Articles open beside the message; diagrams need the diagram viewer.
        if (String(detail.document).startsWith("article:") && work({ document: detail.document }, "knowledge", "scan")) return;
        return window.AtlasKnowledge.show(detail.document);
      default:
        throw Error("Unknown Live Inbox action.");
    }
  }

  window.AtlasInboxActions = { run };
  window.addEventListener("atlas:inbox-action", (event) => {
    run(event.detail).catch((error) => toast(error.message));
  });
})();
