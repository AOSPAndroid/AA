/* Local command templates. Building or copying a command never executes it. */
(() => {
  const commands = window.AtlasPsExecCatalogue.map((item) => ({
    ...item,
    fields: (item.fields || []).map((f) => ({
      ...f,
      pattern: new RegExp(f.pattern),
    })),
  }));
  function build(
    id,
    { target, path, shell = "powershell", elevated = false, values = {} },
  ) {
    const item = commands.find((c) => c.id === id);
    if (!item) throw Error("Choose a command.");
    target = String(target || "")
      .trim()
      .toUpperCase();
    if (!/^(?![-.])(?!.*\.\.)[A-Z0-9_.-]{1,64}$/.test(target))
      throw Error("Enter one valid hostname or IPv4 address.");
    path = String(path || "").trim();
    if (!/^[A-Za-z]:\\(?:[A-Za-z0-9 _.-]+\\)*PsExec(?:64)?\.exe$/i.test(path))
      throw Error(
        "Use a full local path ending in PsExec.exe or PsExec64.exe (for example C:\\Data\\PsExec.exe).",
      );
    if (!["powershell", "cmd"].includes(shell))
      throw Error("Choose PowerShell or Command Prompt.");
    const clean = {};
    for (const field of item.fields || []) {
      clean[field.key] = String(values[field.key] || "").trim();
      if (!field.pattern.test(clean[field.key]))
        throw Error("Enter a valid " + field.label.toLowerCase() + ".");
    }
    if (clean.port && (Number(clean.port) < 1 || Number(clean.port) > 65535))
      throw Error("TCP port must be between 1 and 65535.");
    if (clean.pid && Number(clean.pid) > 4294967295)
      throw Error("Enter a valid Windows process ID.");
    if (clean.session && Number(clean.session) > 65535)
      throw Error("Enter a valid Windows session ID.");
    clean.target = target;
    clean.unc = "\\\\" + target;
    if (item.direct && item.change && clean.pid && Number(clean.pid) <= 4)
      throw Error("System process IDs cannot be changed.");
    let script = item.script?.replace(
      /\{(service|destination|port|pid|account|fileid|target|unc)\}/g,
      (_, key) => clean[key],
    );
    if (script) script = "$ErrorActionPreference='Stop'; " + script;
    const args = item.args?.map((arg) =>
      arg.replace(
        /\{(service|destination|port|pid|account|fileid|target|unc)\}/g,
        (_, key) => clean[key],
      ),
    );
    // UTF-16LE avoids two shells reinterpreting pipes, quotes or dollar signs.
    const encoded = script
      ? btoa(
          Array.from(script, (c) =>
            String.fromCharCode(c.charCodeAt(0) & 255, c.charCodeAt(0) >> 8),
          ).join(""),
        )
      : null;
    const remote = script
      ? [
          "powershell.exe",
          "-NoProfile",
          ...(item.interactive ? [] : ["-NonInteractive"]),
          "-EncodedCommand",
          encoded,
        ]
      : args;
    const executable = item.direct
      ? path.replace(
          /PsExec(64)?\.exe$/i,
          (_, arch) => item.tool + (arch || "") + ".exe",
        )
      : path;
    const tokens = item.direct
      ? [executable, "-accepteula", ...args]
      : [
          path,
          "\\\\" + target,
          "-accepteula",
          "-n",
          "10",
          "-nobanner",
          ...(item.system ? ["-s"] : elevated ? ["-h"] : []),
          ...(item.interactive ? ["-i", clean.session] : []),
          ...remote,
        ];
    const quote = (s) =>
      shell === "powershell"
        ? "'" + s.replace(/'/g, "''") + "'"
        : '"' + s + '"';
    return {
      command:
        (shell === "powershell" ? "& " : "") + tokens.map(quote).join(" "),
      readable: item.direct
        ? [executable, ...args].join(" ")
        : script || args.join(" "),
      encoded: !!script,
      target,
    };
  }
  window.AtlasPsExecCommands = Object.freeze({ commands, build });
})();
