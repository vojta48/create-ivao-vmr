/* IVAO VMR generator GUI. Talks to vmr_gui.py through the /api/... endpoints. */
(function () {
  "use strict";

  const state = {
    presets: [],
    selectedPresets: new Set(),
    rules: [],            // {callsign, type, models: [..]}
    selectedRule: -1,
    liveries: new Map(),  // mtl id -> livery
    mtlRules: { all: [], standard: [] },   // the rules create_vmr.py generates from the MTL
    mtl: { enabled: false, mode: "standard" },
    catalogSearch: "https://mtl.ivao.aero/catalog?textureName={name}",
    outputDir: "",
    modelsRoot: null,       // the MTL folder in use (null: no MTL found)
    mtlReason: null,        // why that folder: "command line", "chosen", "program folder" or the simulator it was found in
    mtlFolders: [],         // the simulators found on this computer: {sim, community, mtl (null: no MTL there)}
    presetsDir: "",
    communityFolder: "",    // the Community folder the user chose ("": the MTL is found automatically)
    updateIgnored: false,   // "Ignore" was clicked in the update prompt (for this run)
    checkForUpdates: true,
    settingsLoaded: false,  // the settings of the last run are applied; only then are changes sent back
    settingsSent: "",       // the settings last sent to the server, so that unchanged settings are not written again
    rulesLoaded: false,     // my rules came from the server; only then are changes sent back
    rulesSent: "",          // my rules last sent to the server
  };
  // vmr_gui.py keeps the settings in settings.json and my rules in my_rules.vmr (in AppData), because the
  // application window does not keep browser storage. Versions before 1.1.0 kept my rules in the browser under
  // this key; they are moved to the file once.
  const OLD_DRAFT_KEY = "ivao-vmr-generator-draft";

  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- helpers
  async function api(path, body) {
    const options = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || (response.status + " " + response.statusText));
    return data;
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "class") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value !== null && value !== undefined) node.setAttribute(key, value);
    }
    for (const child of children) {
      if (child === null || child === undefined) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function setStatus(text, isError) {
    $("status").textContent = text;
    $("status").className = "status" + (isError ? " error" : "");
  }

  // Called after every change: sends my rules and the settings to the server when they changed.
  function saveDraft() {
    saveMyRules();
    saveSettings();
  }

  // Sends what is still waiting for its timer at once (before the page reloads or the program restarts).
  function flushDraft() {
    clearTimeout(rulesTimer);
    clearTimeout(settingsTimer);
    return Promise.all([sendMyRules(), sendSettings()]);
  }

  // ---------------------------------------------------------------- my rules (my_rules.vmr)
  // Only complete rules are stored, like in every VMR (a rule still being typed is kept on the page).
  function completeRules() {
    return state.rules.map(normaliseRule).filter((r) => r.type && r.models.length);
  }

  function applyMyRules(rules) {
    if (Array.isArray(rules)) {
      state.rules = rules.map(normaliseRule);
      state.rulesSent = JSON.stringify(completeRules());
    } else {
      // no rules file yet: take over the rules an older version kept in the browser (sent by the next saveDraft)
      state.rules = oldDraftRules();
      state.rulesSent = "";
    }
    state.rulesLoaded = true;
  }

  function oldDraftRules() {
    try {
      const draft = JSON.parse(localStorage.getItem(OLD_DRAFT_KEY) || "null");
      return draft && Array.isArray(draft.rules) ? draft.rules.map(normaliseRule) : [];
    } catch (e) {
      return [];
    }
  }

  let rulesTimer = null;
  function saveMyRules() {
    if (!state.rulesLoaded) return;
    clearTimeout(rulesTimer);
    rulesTimer = setTimeout(sendMyRules, 400);
  }

  function sendMyRules() {
    if (!state.rulesLoaded) return Promise.resolve();
    const rules = completeRules();
    const text = JSON.stringify(rules);
    if (text === state.rulesSent) return Promise.resolve();
    state.rulesSent = text;
    return api("/api/my-rules", { rules: rules })
      .then(() => { try { localStorage.removeItem(OLD_DRAFT_KEY); } catch (e) { /* ignore */ } })
      .catch(() => { state.rulesSent = ""; });
  }

  // ---------------------------------------------------------------- settings of the last run
  function currentSettings() {
    return { fileName: $("fileName").value.trim(), selectedPresets: [...state.selectedPresets], mtlRules: { enabled: state.mtl.enabled, mode: state.mtl.mode }, checkForUpdates: state.checkForUpdates };
  }

  function applySettings(settings) {
    if (settings.fileName) $("fileName").value = settings.fileName;
    state.selectedPresets = new Set(settings.selectedPresets || []);
    if (settings.mtlRules) state.mtl = { enabled: Boolean(settings.mtlRules.enabled), mode: settings.mtlRules.mode === "all" ? "all" : "standard" };
    state.checkForUpdates = settings.checkForUpdates !== false;
    $("checkUpdates").checked = state.checkForUpdates;
    state.settingsSent = JSON.stringify(currentSettings());
    state.settingsLoaded = true;
  }

  // Sends changed settings to the server, a moment after the last change (not on every key press).
  let settingsTimer = null;
  function saveSettings() {
    if (!state.settingsLoaded) return;
    clearTimeout(settingsTimer);
    settingsTimer = setTimeout(sendSettings, 400);
  }

  function sendSettings() {
    if (!state.settingsLoaded) return Promise.resolve();
    const settings = currentSettings();
    const text = JSON.stringify(settings);
    if (text === state.settingsSent || !settings.fileName) return Promise.resolve();
    state.settingsSent = text;
    return api("/api/settings", { settings: settings }).catch(() => { state.settingsSent = ""; });
  }

  // The output folder is the IVAO_MTL folder until the user chooses another one (or saves somewhere else).
  function showOutputFolder() {
    const box = $("outputFolder");
    box.innerHTML = "";
    if (!state.outputDir) return;
    box.append("Output folder: " + state.outputDir + " ");
    if (inWindow()) box.append(el("button", { class: "small secondary", onclick: () => changeOutputFolder(() => window.pywebview.api.choose_output_folder()) }, "Change…"), " ");
    if (state.modelsRoot && state.outputDir !== state.modelsRoot) {
      box.append(el("button", { class: "small secondary", onclick: () => changeOutputFolder(() => api("/api/output-folder", { default: true })) }, "Use the IVAO_MTL folder"));
    }
  }

  async function changeOutputFolder(change) {
    try {
      const result = await change();
      if (result.error) $("saveResult").textContent = "Error: " + result.error;
      else if (result.outputDir) { state.outputDir = result.outputDir; showOutputFolder(); }
    } catch (err) {
      $("saveResult").textContent = "Error: " + (err.message || err);
    }
  }

  // ---------------------------------------------------------------- which MTL
  // vmr_gui.py finds the MTL in the Community folder of MSFS 2020/2024 by itself; that is the normal way. With more
  // than one simulator the user can switch between them, and in the application window choose the Community folder
  // when it is not found. "Find it automatically" goes back to the normal way.
  function mtlFolderText() {
    if (!state.modelsRoot) {
      const sims = state.mtlFolders.map((s) => s.sim + " (no IVAO MTL in " + s.community + ")");
      return "No IVAO MTL found. " + (sims.length ? "Found " + sims.join(", ") + ". " : "No MSFS 2020 or 2024 found. ") +
        "Install the MTL with the MTL Installer" + (inWindow() ? ", or choose the Community folder it is in." : ", or start the program with -c <Community folder>.");
    }
    const why = { "command line": "given with -d", "chosen": "in the Community folder you chose", "program folder": "the folder of the program" }[state.mtlReason] || ("found in " + state.mtlReason);
    return "MTL: " + state.modelsRoot + " (" + why + ")";
  }

  function renderMtlFolder() {
    const box = $("mtlFolder");
    box.innerHTML = "";
    box.append(mtlFolderText());
    const others = state.mtlFolders.filter((s) => s.mtl && s.mtl !== state.modelsRoot);
    if (others.length) {
      const select = el("select", { onchange: () => { if (select.value) switchMtl(() => api("/api/community", { community: select.value })); } },
        el("option", { value: "" }, "Use the MTL of another simulator…"),
        ...others.map((s) => el("option", { value: s.community }, s.sim)));
      box.append(el("div", { class: "row" }, select));
    }
    const buttons = el("div", { class: "row" });
    if (inWindow()) buttons.append(el("button", { class: "small secondary", onclick: () => switchMtl(() => window.pywebview.api.choose_community_folder()) }, "Choose the Community folder…"));
    if (state.communityFolder) buttons.append(el("button", { class: "small secondary", onclick: () => switchMtl(() => api("/api/community", { community: null })) }, "Find it automatically"));
    if (buttons.childNodes.length) box.append(buttons);
  }

  // Switches to another MTL: the server scans it, and the page starts again with its liveries.
  async function switchMtl(change) {
    try {
      const result = await change();
      if (result.cancelled) return;
      if (result.error) { setStatus(result.error, true); return; }
      await flushDraft();
      location.reload();
    } catch (err) {
      setStatus("Could not change the MTL folder: " + (err.message || err), true);
    }
  }

  // ---------------------------------------------------------------- updates
  // vmr_gui.py asks GitHub for the latest release. A newer release is offered in a prompt with "Update" and "Ignore":
  // "Update" installs it right away and restarts the program. Running from source (or a release without the exe)
  // the prompt links to the release page instead. A development version is never offered an update.
  async function checkForUpdate(now) {
    if (now) $("updateInfo").textContent = "Checking…";
    try {
      const status = now ? await api("/api/update", { action: "check" }) : await api("/api/update");
      $("updateInfo").textContent = updateInfoText(status);
      // "Ignore" keeps the prompt away for this run; "Check now" shows it again
      if (status.available && (now || !state.updateIgnored)) showUpdatePrompt(status);
    } catch (err) {
      $("updateInfo").textContent = "Could not check for a new version: " + err.message;
    }
  }

  function updateInfoText(status) {
    if (status.error) return status.error;
    if (!status.checked) return status.enabled ? "" : "The check at start is off.";
    if (!status.latest) return "Version " + status.current + " is a development version, so it is not checked for updates.";
    if (status.development) return "Version " + status.current + " is a development version, newer than the latest release (" + status.latest + ").";
    return status.available ? "Version " + status.latest + " is available." : "You have the newest version (" + status.current + ").";
  }

  function showUpdatePrompt(status) {
    const dialog = $("updateDialog");
    const update = el("button", {}, status.canInstall ? "Update" : "Open the release page");
    const ignore = el("button", { class: "secondary", onclick: () => { state.updateIgnored = true; closeDialog(dialog); } }, "Ignore");
    const text = el("p", {}, "You have version " + status.current + ". " + (status.canInstall
      ? "Update downloads the new version, installs it and restarts the program. Your settings and rules are kept."
      : "Download it from the release page and replace the program you have."));
    update.addEventListener("click", () => {
      if (status.canInstall) installUpdate(status, text, update, ignore);
      else { window.open(status.page, "_blank", "noreferrer"); closeDialog(dialog); }
    });
    dialog.innerHTML = "";
    dialog.append(el("h2", {}, "Version " + status.latest + " is available"), text,
      status.notes ? el("details", {}, el("summary", {}, "What's new"), el("pre", {}, status.notes)) : null,
      el("div", { class: "row" }, update, ignore));
    if (dialog.showModal) { if (!dialog.open) dialog.showModal(); } else dialog.setAttribute("open", "");
  }

  function closeDialog(dialog) {
    if (dialog.close) dialog.close(); else dialog.removeAttribute("open");
  }

  async function installUpdate(status, text, update, ignore) {
    update.disabled = ignore.disabled = true;
    text.textContent = "Downloading and checking version " + status.latest + "… The program restarts when it is done.";
    try {
      await flushDraft();
      await api("/api/update", { action: "install" });
      text.textContent = "Version " + status.latest + " is installed. The program restarts…";
    } catch (err) {
      text.textContent = "";
      text.append(err.message + " ", el("a", { href: status.page, target: "_blank", rel: "noreferrer" }, "Open the release page ↗"));
      ignore.disabled = false;
      ignore.textContent = "Close";
    }
  }

  // Messages about the last run that the user should read once (settings reset, rules changed by the MTL).
  function showNotice(...texts) {
    const text = texts.filter(Boolean).join("\n\n");
    $("notice").textContent = text;
    $("notice").hidden = !text;
  }

  // exactCallsign (vPilot's Callsign) and flightNumbers (FlightNumberRange) only come from imported VMR files.
  // They are kept as they are, so that a rule for one callsign does not turn into a rule for everybody.
  function normaliseRule(rule) {
    const out = {
      callsign: (rule.callsign || "").trim().toUpperCase(),
      type: (rule.type || "").trim().toUpperCase(),
      models: (rule.models || []).map((m) => m.trim()).filter(Boolean),
    };
    if (rule.exactCallsign) out.exactCallsign = rule.exactCallsign.trim().toUpperCase();
    if (rule.flightNumbers) out.flightNumbers = rule.flightNumbers.trim();
    return out;
  }

  // vPilot uses the first rule that matches, so a later rule with the same conditions is never used.
  function ruleKey(rule) {
    return [rule.callsign, rule.exactCallsign || "", rule.flightNumbers || "", rule.type].join("|");
  }

  function ruleConditions(rule) {
    return (rule.callsign || "*") + (rule.exactCallsign ? " =" + rule.exactCallsign : "") + (rule.flightNumbers ? " #" + rule.flightNumbers : "") + " " + rule.type;
  }

  function modelsFromText(text) {
    return text.split("//").map((m) => m.trim()).filter(Boolean);
  }

  // ---------------------------------------------------------------- models
  function catalogLink(mtlId, text) {
    return el("a", { href: state.catalogSearch.replace("{name}", encodeURIComponent(mtlId)), target: "_blank", rel: "noreferrer", title: "Open " + mtlId + " in the MTL catalog" }, text);
  }

  // The picture of a livery from the MTL catalog, served (and cached) by vmr_gui.py. Liveries that were
  // not installed by the MTL Installer have no catalog number, and without network there is no picture:
  // the <img> is simply removed then.
  function preview(livery, cls, fallback) {
    if (!livery || !livery.catalogId) return fallback || null;
    const img = el("img", { class: cls, src: "/api/preview/" + encodeURIComponent(livery.id), alt: "", loading: "lazy" });
    img.addEventListener("error", () => (fallback ? img.replaceWith(fallback) : img.remove()));
    return img;
  }

  // A small label for one model of a rule: its picture, its id (linked to the MTL catalog) and its livery name.
  function modelChip(mtlId) {
    const livery = state.liveries.get(mtlId);
    const missing = state.liveries.size > 0 && !livery;
    const chip = el("span", { class: "chip" + (missing ? " missing" : ""), title: missing ? "Not installed in your MTL" : (livery && livery.name) || mtlId }, catalogLink(mtlId, mtlId + " ↗"));
    const img = preview(livery, "thumb");
    if (img) chip.prepend(img);
    if (livery && livery.name) chip.append(" ", el("span", { class: "muted" }, livery.name));
    if (missing) chip.append(" ", el("span", { class: "muted" }, "(not installed)"));
    return chip;
  }

  // ---------------------------------------------------------------- presets
  function renderPresets() {
    const container = $("presets");
    container.innerHTML = "";
    if (state.presets.length === 0) {
      container.append(el("div", { class: "hint" }, "No presets found. Put .vmr files into " + (state.presetsDir || "the presets folder") + "."));
      return;
    }
    for (const preset of state.presets) {
      const checkbox = el("input", { type: "checkbox" });
      checkbox.checked = state.selectedPresets.has(preset.id);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.selectedPresets.add(preset.id); else state.selectedPresets.delete(preset.id);
        updateOutput();
      });
      const list = el("ul");
      for (const rule of preset.rules) {
        const line = el("li", {}, ruleConditions(rule) + " → ");
        rule.models.forEach((model, i) => {
          const known = state.liveries.size === 0 || state.liveries.has(model);
          line.append(el("span", { class: "model" + (known ? "" : " missing"), title: known ? "Show in the library" : "Not installed in your MTL", onclick: () => { $("search").value = model; renderLibrary(); } }, model));
          if (i < rule.models.length - 1) line.append(" // ");
        });
        list.append(line);
      }
      container.append(el("div", { class: "preset" },
        el("label", {}, checkbox, preset.name + " (" + preset.rules.length + " rules)"),
        preset.description ? el("div", { class: "desc" }, preset.description) : null,
        el("details", {}, el("summary", {}, "Rules"), list,
          el("button", { class: "small secondary", onclick: () => { state.rules.push(...preset.rules.map(normaliseRule)); renderRules(); } }, "Copy into my rules"))
      ));
    }
  }

  // ---------------------------------------------------------------- rules
  function renderRules() {
    const body = $("rulesBody");
    body.innerHTML = "";
    // The rules that come before each of my rules in the file: the ticked presets, then my earlier rules.
    const earlier = new Map();
    for (const preset of state.presets) {
      if (!state.selectedPresets.has(preset.id)) continue;
      for (const rule of preset.rules) if (!earlier.has(ruleKey(rule))) earlier.set(ruleKey(rule), "preset " + preset.name);
    }
    state.rules.forEach((rule, index) => {
      const row = el("tr", { class: index === state.selectedRule ? "selected" : "" });
      const select = () => { if (state.selectedRule !== index) { state.selectedRule = index; renderRules(); } };
      const callsign = el("input", { type: "text", value: rule.callsign, placeholder: "TVS", maxlength: 3, list: "airlines", onfocus: select, oninput: () => { rule.callsign = callsign.value.toUpperCase(); updateOutput(); } });
      const type = el("input", { type: "text", value: rule.type, placeholder: "B738", maxlength: 4, list: "types", onfocus: select, oninput: () => { rule.type = type.value.toUpperCase(); updateOutput(); } });
      const models = el("input", { type: "text", value: rule.models.join("//"), placeholder: "B738TVSWL//B738TVSWL3", list: "models", onfocus: select });
      models.addEventListener("change", () => { rule.models = modelsFromText(models.value); renderRules(); });
      models.addEventListener("input", () => { rule.models = modelsFromText(models.value); updateOutput(); });
      const chips = el("div", { class: "chips" }, ...rule.models.map((m) => modelChip(m)));
      const warnings = [];
      const key = ruleKey(normaliseRule(rule));
      if (rule.type && rule.models.length) {
        if (earlier.has(key)) warnings.push("Never used: " + earlier.get(key) + " already has a rule for " + ruleConditions(rule) + ", and vPilot takes the first one.");
        else earlier.set(key, "your rule " + (index + 1));
      }
      if (!rule.type) warnings.push("Type is required.");
      if (rule.models.length === 0) warnings.push("At least one model is required.");
      if (state.liveries.size > 0) {
        const missing = rule.models.filter((m) => !state.liveries.has(m));
        if (missing.length) warnings.push("Not installed: " + missing.join(", "));
      }
      row.append(
        el("td", { class: "callsign" }, callsign,
          rule.exactCallsign ? el("div", { class: "muted", title: "Callsign: only this exact callsign (from the imported file)" }, "= " + rule.exactCallsign) : null,
          rule.flightNumbers ? el("div", { class: "muted", title: "FlightNumberRange: only these flight numbers (from the imported file)" }, "# " + rule.flightNumbers) : null),
        el("td", { class: "type" }, type),
        el("td", { class: "models" }, models, chips, warnings.length ? el("div", { class: "warning" }, warnings.join(" ")) : null),
        el("td", {}, el("button", { class: "small danger", title: "Remove rule", onclick: () => { state.rules.splice(index, 1); if (state.selectedRule >= state.rules.length) state.selectedRule = state.rules.length - 1; renderRules(); } }, "✕"))
      );
      body.append(row);
    });
    updateOutput();
  }

  function addRule(rule) {
    state.rules.push(normaliseRule(rule || {}));
    state.selectedRule = state.rules.length - 1;
    renderRules();
    const inputs = $("rulesBody").querySelectorAll("tr:last-child input");
    if (inputs.length) inputs[0].focus();
  }

  function addModelToSelectedRule(livery) {
    if (state.selectedRule < 0 || state.selectedRule >= state.rules.length) {
      addRule({ callsign: livery.airline, type: livery.type, models: [livery.id] });
      return;
    }
    const rule = state.rules[state.selectedRule];
    if (!rule.type) rule.type = livery.type;
    if (!rule.callsign && rule.models.length === 0) rule.callsign = livery.airline;
    if (!rule.models.includes(livery.id)) rule.models.push(livery.id);
    renderRules();
  }

  // ---------------------------------------------------------------- IVAO MTL
  function mtlRulesSelected() {
    if (!state.mtl.enabled) return [];
    return state.mtlRules[state.mtl.mode] || [];
  }

  function renderMtl() {
    const have = state.liveries.size > 0;
    $("mtlEnabled").checked = state.mtl.enabled && have;
    $("mtlEnabled").disabled = !have;
    $("mtlLabel").textContent = have ? "Add the rules generated from my MTL" : "Add the rules generated from my MTL (no MTL found)";
    $("mtlStandard").checked = state.mtl.mode === "standard";
    $("mtlAll").checked = state.mtl.mode === "all";
    $("mtlStandardLabel").textContent = "standard liveries only (" + state.mtlRules.standard.length + " rules, like ivaomtl_standard.vmr)";
    $("mtlAllLabel").textContent = "all liveries (" + state.mtlRules.all.length + " rules, like ivaomtl.vmr)";
    for (const input of document.querySelectorAll("#mtl .indent input")) input.disabled = !(have && state.mtl.enabled);
  }

  // ---------------------------------------------------------------- output
  // Order in the file = priority in vPilot: presets, then my rules, then the rules generated from the MTL.
  function combinedRules() {
    const rules = [];
    for (const preset of state.presets) {
      if (state.selectedPresets.has(preset.id)) rules.push(...preset.rules);
    }
    rules.push(...state.rules.map(normaliseRule).filter((r) => r.type && r.models.length));
    rules.push(...mtlRulesSelected());
    return rules;
  }

  function outputComment() {
    const parts = [];
    if (state.selectedPresets.size) parts.push("Presets: " + [...state.selectedPresets].join(", "));
    if (state.mtl.enabled) parts.push("IVAO MTL: " + (state.mtl.mode === "standard" ? "standard liveries only" : "all liveries"));
    return parts.join("; ");
  }

  // The same as build_vmr in vmr_gui.py (used for "Save to output folder"); keep both alike.
  function buildVmr(rules, comment) {
    const escape = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const lines = ['<?xml version="1.0" encoding="utf-8"?>', "<ModelMatchRuleSet>"];
    for (const rule of rules) {
      if (!rule.type || !rule.models.length) continue;
      const attrs = (rule.callsign ? ' CallsignPrefix="' + escape(rule.callsign) + '"' : "") +
        (rule.exactCallsign ? ' Callsign="' + escape(rule.exactCallsign) + '"' : "") +
        (rule.flightNumbers ? ' FlightNumberRange="' + escape(rule.flightNumbers) + '"' : "") +
        ' TypeCode="' + escape(rule.type) + '" ModelName="' + escape(rule.models.join("//")) + '"';
      lines.push("<ModelMatchRule" + attrs + " />");
    }
    lines.push("</ModelMatchRuleSet>");
    if (comment) lines.push("<!-- " + comment.replace(/--/g, "- -") + " -->");
    lines.push("<!-- VMR created by create-ivao-vmr GUI https://github.com/vojta48/create-ivao-vmr -->");
    return lines.join("\r\n") + "\r\n";
  }

  function updateOutput() {
    const rules = combinedRules();
    const own = rules.length - mtlRulesSelected().length;
    $("vmrText").textContent = buildVmr(rules, outputComment());
    $("save").textContent = "Save to output folder (" + rules.length + " rules)";
    $("outputSummary").textContent = state.mtl.enabled
      ? own + " rules from presets and my rules, then " + mtlRulesSelected().length + " rules generated from the MTL. In vPilot this file replaces the MTL VMR."
      : own + " rules from presets and my rules. In vPilot put this file above the IVAO MTL VMR.";
    saveDraft();
  }

  function savedMessage(path) {
    const where = state.mtl.enabled ? "use this file in vPilot (Settings → Model Matching → Custom Rules) instead of the IVAO MTL VMR." : "add this file in vPilot (Settings → Model Matching → Custom Rules) above the IVAO MTL VMR.";
    return "Saved: " + path + " – " + where;
  }

  async function save() {
    const rules = combinedRules();
    if (rules.length === 0) { $("saveResult").textContent = "Nothing to save: tick a preset or add a rule."; return; }
    $("saveResult").textContent = "Saving…";
    try {
      const result = await api("/api/save", { fileName: $("fileName").value, rules: rules, comment: outputComment() });
      $("saveResult").textContent = savedMessage(result.path);
      savedTo(result);
    } catch (err) {
      $("saveResult").textContent = "Error: " + err.message;
    }
  }

  // After saving, the server remembers the folder and the name; the page shows them for the next save.
  function savedTo(result) {
    if (result.outputDir) { state.outputDir = result.outputDir; showOutputFolder(); }
    const name = (result.path || "").split(/[\\/]/).pop();
    if (name) { $("fileName").value = name; state.settingsSent = JSON.stringify(currentSettings()); }
  }

  const inWindow = () => Boolean(window.pywebview && window.pywebview.api);

  async function download() {
    const rules = combinedRules();
    if (inWindow()) {
      // Running in the application window: use the Windows "Save as" dialog instead of a browser download.
      try {
        const result = await window.pywebview.api.save_as($("fileName").value || "custom.vmr", buildVmr(rules, outputComment()));
        if (result.error) $("saveResult").textContent = "Error: " + result.error;
        else if (!result.cancelled) { $("saveResult").textContent = savedMessage(result.path); savedTo(result); }
      } catch (err) {
        $("saveResult").textContent = "Error: " + err;
      }
      return;
    }
    const blob = new Blob([buildVmr(rules, outputComment())], { type: "text/xml" });
    const link = el("a", { href: URL.createObjectURL(blob), download: $("fileName").value || "custom.vmr" });
    document.body.append(link);
    link.click();
    link.remove();
  }

  // ---------------------------------------------------------------- library
  function renderLibrary() {
    const grid = $("library");
    grid.innerHTML = "";
    const query = $("search").value.trim().toUpperCase();
    const terms = query.split(/\s+/).filter(Boolean);
    const all = [...state.liveries.values()];
    const matches = all.filter((l) => terms.every((t) => (l.id + " " + l.airline + " " + l.type + " " + l.name).toUpperCase().includes(t)));
    const limit = 120;
    $("libraryInfo").textContent = all.length === 0
      ? "No liveries found. " + mtlFolderText()
      : matches.length + " of " + all.length + " liveries" + (matches.length > limit ? " (showing the first " + limit + ", refine the search)" : "");
    for (const livery of matches.slice(0, limit)) {
      const card = el("div", { class: "card", title: "Add " + livery.id + " to the selected rule", onclick: () => addModelToSelectedRule(livery) });
      const link = catalogLink(livery.id, "↗");
      link.className = "catalog";
      link.addEventListener("click", (e) => e.stopPropagation());
      card.append(
        preview(livery, "picture", el("div", { class: "picture none" }, "no picture")),
        el("div", { class: "head" }, el("div", { class: "id" }, livery.id), link),
        el("div", { class: "name" + (livery.standard ? "" : " special") }, livery.name || livery.model),
        el("div", { class: "meta" }, livery.type + " · " +
          (!livery.inVmr ? "no airline code or invisible model, not in the MTL rules" : livery.airline || "any airline (type-only rule)") +
          (livery.standard ? "" : " · special livery"))
      );
      grid.append(card);
    }
  }

  function renderDatalists() {
    const airlines = new Set(), types = new Set();
    for (const l of state.liveries.values()) { if (l.airline) airlines.add(l.airline); if (l.type) types.add(l.type); }
    const make = (id, values) => {
      let list = $(id);
      if (!list) { list = el("datalist", { id: id }); document.body.append(list); }
      list.innerHTML = "";
      for (const v of [...values].sort()) list.append(el("option", { value: v }));
    };
    make("airlines", airlines);
    make("types", types);
    make("models", [...state.liveries.keys()]);
  }

  // aircraft.cfg files that could not be read and liveries that were skipped (no type, no title, a title used
  // twice): they are missing from the list and the MTL rules.
  function renderErrors(errors) {
    const box = $("errors");
    box.innerHTML = "";
    box.hidden = !errors.length;
    if (!errors.length) return;
    box.append(el("summary", {}, errors.length + " problem" + (errors.length > 1 ? "s" : "") + " in the aircraft.cfg files of your MTL: the liveries concerned are missing. Repair the MTL with the MTL Installer."),
      el("ul", {}, ...errors.map((e) => el("li", {}, e))));
  }

  // ---------------------------------------------------------------- import
  async function importText(text, name) {
    try {
      const result = await api("/api/parse-vmr", { text: text });
      state.rules.push(...result.rules.map(normaliseRule));
      renderRules();
      setStatus("Imported " + result.rules.length + " rules from " + name);
    } catch (err) {
      setStatus("Import failed: " + err.message, true);
    }
  }

  function importFile(file) {
    const reader = new FileReader();
    reader.onload = () => importText(reader.result, file.name);
    reader.readAsText(file);
  }

  async function importFromDialog() {
    const result = await window.pywebview.api.open_file();
    if (result.error) setStatus("Import failed: " + result.error, true);
    else if (!result.cancelled) importText(result.text, result.name);
  }

  // In the application window the file input is replaced by a button that opens the Windows "Open" dialog.
  window.addEventListener("pywebviewready", () => {
    const input = $("importFile");
    const button = el("button", { class: "secondary", onclick: importFromDialog }, "Open a VMR file…");
    input.replaceWith(button);
    $("download").textContent = "Save as…";
    renderMtlFolder();  // now with the buttons for the folder dialogs
    showOutputFolder();
  });

  // ---------------------------------------------------------------- init
  async function init() {
    try {
      const data = await api("/api/state");
      state.presets = data.presets;
      state.catalogSearch = data.catalogSearch;
      state.liveries = new Map(data.liveries.map((l) => [l.id, l]));
      state.mtlRules = data.mtlRules;
      state.outputDir = data.outputDir;
      state.modelsRoot = data.modelsRoot;
      state.mtlReason = data.mtlReason;
      state.mtlFolders = data.mtlFolders || [];
      state.presetsDir = data.presetsDir;
      state.communityFolder = data.communityFolder || "";
      if (data.version) $("version").textContent = data.version;
      if (data.settings) applySettings(data.settings);
      applyMyRules(data.myRules);
      showNotice(data.filesNotice, data.settingsNotice, data.myRulesNotice);
      showOutputFolder();
      $("dataDir").textContent = "Your settings and rules are kept in " + data.dataDir + ".";
      if (data.libraryFound) {
        setStatus(data.liveries.length + " liveries found in " + data.airplanesFolder);
      } else if (data.modelsRoot) {
        setStatus("No MTL in " + data.airplanesFolder + ". Presets and manual rules still work.", true);
      } else {
        setStatus("No IVAO MTL found. Presets and manual rules still work.", true);
      }
      renderErrors(data.errors);
      checkForUpdate(false);
    } catch (err) {
      setStatus("Could not load data from the server: " + err.message, true);
    }
    renderMtlFolder();
    renderPresets();
    renderDatalists();
    renderMtl();
    renderRules();
    renderLibrary();
  }

  $("mtlEnabled").addEventListener("change", () => { state.mtl.enabled = $("mtlEnabled").checked; renderMtl(); updateOutput(); });
  $("mtlStandard").addEventListener("change", () => { state.mtl.mode = "standard"; updateOutput(); });
  $("mtlAll").addEventListener("change", () => { state.mtl.mode = "all"; updateOutput(); });

  $("addRule").addEventListener("click", () => addRule());
  $("clearRules").addEventListener("click", () => { if (state.rules.length === 0 || confirm("Remove all your rules?")) { state.rules = []; state.selectedRule = -1; renderRules(); } });
  $("save").addEventListener("click", save);
  $("download").addEventListener("click", download);
  $("fileName").addEventListener("input", saveDraft);
  $("checkUpdates").addEventListener("change", () => { state.checkForUpdates = $("checkUpdates").checked; saveSettings(); });
  $("checkNow").addEventListener("click", () => checkForUpdate(true));
  $("search").addEventListener("input", renderLibrary);
  $("importFile").addEventListener("change", (e) => { if (e.target.files[0]) importFile(e.target.files[0]); e.target.value = ""; });
  init();
})();
