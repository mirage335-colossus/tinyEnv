/* Offline navigation for the generated atlas. No network or source checkout required. */
(() => {
  "use strict";
  const data = window.DOCMAP_DATA || {};
  const files = data.files || [];
  const fileById = new Map(files.map(f => [String(f.id), f]));
  const fileByPath = new Map(files.map(f => [normalizePath(f.path), f]));
  const symbols = files.flatMap(f => (f.symbols || []).map(s => ({...s, file: f})));
  const symbolById = new Map(symbols.map(s => [String(s.id), s]));
  const incoming = new Map();
  const categoryOrder = ["core", "gui", "tools", "tests", "build", "other"];
  const categories = {
    core: {label: "Core library", icon: "◇", description: "Foundations, algorithms, data structures, and shared behavior."},
    gui: {label: "GUI & applications", icon: "▣", description: "Application entry points, windows, widgets, and user interactions."},
    tools: {label: "Tools & utilities", icon: "⌘", description: "Standalone tools, developer utilities, and support scripts."},
    tests: {label: "Tests & examples", icon: "✓", description: "Examples of expected behavior and ways to exercise the code."},
    build: {label: "Build configuration", icon: "⚙", description: "Targets, source lists, options, and compiler configuration."},
    other: {label: "Other files", icon: "▤", description: "Supporting source and configuration outside the main modules."}
  };
  const state = {graphLimits: {}, categoryFilter: "all", symbolFilter: "all", searchTerm: "", selectedChangeNodes: {}, activeChangeMap: "widget", lastChangeMap: null, selectedFlowNodes: {}, activeFlowMap: "startup", lastFlowMap: null, codeOrigins: {}, selectedCodeNodes: {}, navigationContext: null};
  const parameterById = new Map();
  const parameterContexts = new Map();
  [...(data.change_maps || []), ...(data.flow_maps || [])].forEach(map => (map.nodes || []).forEach(node => (node.parameter_guides || []).forEach(guide => {
    const id = String(guide.id);
    if (!parameterById.has(id) || (parameterById.get(id).status === "missing" && guide.status === "verified")) parameterById.set(id, guide);
    if (!parameterContexts.has(id)) parameterContexts.set(id, []);
    if (!parameterContexts.get(id).some(context => context.map.id === map.id && context.node.id === node.id)) parameterContexts.get(id).push({map, node});
  })));
  const main = document.getElementById("main");
  const search = document.getElementById("global-search");
  const preview = document.getElementById("search-preview");
  let currentRoute = "home";
  let graphSequence = 0;

  symbols.forEach(s => (s.calls || []).forEach(call => (call.targets || []).forEach(id => {
    const key = String(id);
    if (!incoming.has(key)) incoming.set(key, []);
    incoming.get(key).push({symbol: s, call});
  })));

  function normalizePath(value) { return String(value || "").replace(/\\/g, "/").replace(/^\.\//, ""); }
  function esc(value) { return String(value == null ? "" : value).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c])); }
  function encode(value) { return encodeURIComponent(String(value)); }
  function routeFile(f) { return "#file/" + encode(f.id); }
  function routeSymbol(s) { return "#symbol/" + encode(s.id); }
  function routeSource(f, line = 1) { return "#source/" + encode(f.id) + "/" + Math.max(1, Number(line) || 1); }
  function safePrintReference(reference) {
    if (!reference) return null;
    const filename = String(reference.pdf || "");
    if ((typeof reference.page !== "number" && typeof reference.page !== "string") || (typeof reference.page === "string" && !/^[1-9]\d*$/.test(reference.page))) return null;
    const page = Number(reference.page);
    if (!/^[A-Za-z0-9][A-Za-z0-9._ -]*\.pdf$/i.test(filename) || !Number.isSafeInteger(page) || page < 1) return null;
    return {href: "pdf/" + encode(filename) + "#page=" + page, page};
  }
  function printLink(symbolId, fileId, line, className = "", label = "Read in PDF") {
    const references = data.print_references || {};
    const reference = safePrintReference((references.symbols || {})[String(symbolId || "")]) || safePrintReference((references.locations || {})[String(fileId || "") + ":" + String(line || 1)]);
    return reference ? `<a${className ? ` class="${esc(className)}"` : ""} href="${reference.href}" title="Open printed chapter at page ${reference.page}">${esc(label)}</a>` : "";
  }
  function printTargetLink(index) {
    const reference = safePrintReference((data.print_references?.build_targets || {})[String(index)]);
    return reference ? `<a class="button" href="${reference.href}" title="Open compiler reference at page ${reference.page}">Read target in PDF</a>` : "";
  }
  function printFlowLink(map, node, className = "button") {
    const references = data.print_references || {};
    const reference = safePrintReference(node ? (references.flow_nodes || {})[map.id + "/" + node.id] : (references.flow_maps || {})[map.id]);
    return reference ? `<a class="${esc(className)}" href="${reference.href}" title="Open execution-flow handbook at page ${reference.page}">${node ? "Read step in PDF" : "Read scenario in PDF"}</a>` : "";
  }
  function codePrintReference(map, node) {
    const references = data.print_references || {};
    return safePrintReference(node ? (references.code_nodes || {})[map.id + "/" + node.id] : (references.code_maps || {})[map.id]);
  }
  function printCodeLink(map) {
    const reference = codePrintReference(map);
    return reference ? `<a class="button" href="${reference.href}" title="Open code-flowchart handbook at page ${reference.page}">Read code diagram in PDF</a>` : "";
  }
  function sourceFile(path, declaredIn) {
    const normalized = normalizePath(path);
    if (declaredIn && !/[${}<>]/.test(normalized)) {
      const parent = normalizePath(declaredIn).split("/").slice(0, -1);
      const joined = [...parent, ...normalized.split("/")].reduce((parts, part) => {if (part === "..") parts.pop(); else if (part && part !== ".") parts.push(part); return parts;}, []).join("/");
      const local = fileByPath.get(joined);
      if (local) return local;
    }
    return fileByPath.get(normalized);
  }
  function fileLink(path, line, label, declaredIn) {
    const f = sourceFile(path, declaredIn);
    return f ? `<a href="${routeSource(f, line)}">${esc(label || path)}${line && !label ? ":" + esc(line) : ""}</a>` : `<span class="mono">${esc(label || path)}${line && !label ? ":" + esc(line) : ""}</span>`;
  }
  function kindBadge(s) { const kind = s.kind || "symbol"; return `<span class="badge ${esc(kind)}">${esc(kind)}</span>`; }
  function categoryInfo(cat) { return categories[cat] || {label: cat || "Other files", icon: "▤", description: "Source files and configuration."}; }
  function countCategory(cat) { return files.filter(f => (f.category || "other") === cat).length; }
  function categoryFor(f) { return categoryInfo(f.category || "other"); }
  function crumbs(items) { return `<div class="breadcrumbs"><a href="#home">Atlas</a>${items.map(item => `<span aria-hidden="true">/</span>${item.href ? `<a href="${item.href}">${esc(item.label)}</a>` : `<span>${esc(item.label)}</span>`}`).join("")}</div>`; }
  function pageHeading(eyebrow, title, description, actions = "") { return `<div class="page-heading"><div><div class="eyebrow">${esc(eyebrow)}</div><h1>${esc(title)}</h1>${description ? `<p class="lead">${esc(description)}</p>` : ""}</div>${actions ? `<div class="heading-actions">${actions}</div>` : ""}</div>`; }
  function section(title, body, link = "") { return `<section class="section"><div class="section-heading"><h2>${esc(title)}</h2>${link}</div>${body}</section>`; }
  function empty(text) { return `<div class="empty">${esc(text)}</div>`; }
  function panel(body, title = "", note = "") { return `<div class="panel">${title ? `<div class="panel-head"><div><h3>${esc(title)}</h3>${note ? `<p>${esc(note)}</p>` : ""}</div></div>` : ""}${body}</div>`; }
  function niceDate() { const value = data.generated_at || ""; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"}); }
  function unique(items, key) { const found = new Set(); return items.filter(item => { const value = key(item); if (found.has(value)) return false; found.add(value); return true; }); }
  function short(text, count = 26) { const value = String(text || ""); return value.length <= count ? value : value.slice(0, count - 1) + "…"; }
  function fileName(f) { return String(f.path).split("/").pop(); }
  function isClass(s) { return /class|struct|interface|enum|type|record/i.test(s.kind || ""); }
  function isFunction(s) { return /function|method|constructor|destructor|procedure|lambda/i.test(s.kind || ""); }
  function contexts(items) { return items && items.length ? `<div class="declaration-context"><span class="muted">Lexical context:</span> ${items.map(item => `<code>${esc(item)}</code>`).join(" · ")}</div>` : ""; }
  function prioritizeEntries(entries) {
    const score = s => (/^(main|wmain|WinMain|wWinMain|DllMain|_start)$/.test(s.name) ? 0 : 10) + ({core: 0, gui: 1, tools: 2, tests: 4, build: 5, other: 6}[s.file.category] || 0) + (/lambda/i.test(s.kind) ? 40 : 0) + (s.kind === "module" ? 20 : 0);
    return [...entries].sort((a, b) => score(a) - score(b) || a.file.path.localeCompare(b.file.path) || a.line - b.line);
  }

  function renderNavigation() {
    const list = [
      `<a class="nav-link" data-nav="home" href="#home"><span class="nav-icon">◈</span>Edit task maps</a>`,
      ...(hasConceptGuide() ? ['<a class="nav-link concept-nav" href="AI-AUTHORED__GUI-MENTAL-MODEL.html"><span class="nav-icon">AI</span>AI-authored GUI guide</a>'] : []),
      ...((data.flow_maps || []).length ? ['<a class="nav-link" data-nav="flows" href="#flows"><span class="nav-icon">⇢</span>What runs when…</a>'] : []),
      `<a class="nav-link" data-nav="inventory" href="#inventory"><span class="nav-icon">▤</span>Code inventory<span class="count">${files.length}</span></a>`,
      `<a class="nav-link" data-nav="build" href="#build"><span class="nav-icon">⚙</span>Compiler & toolchain</a>`,
      `<a class="nav-link" data-nav="symbols" href="#symbols"><span class="nav-icon">ƒ</span>Functions & classes<span class="count">${symbols.length}</span></a>`,
      ...(parameterById.size ? [`<a class="nav-link" data-nav="parameters" href="#parameters"><span class="nav-icon">≡</span>Parameter guides<span class="count">${parameterById.size}</span></a>`] : []),
      `<hr class="nav-rule">`,
      ...categoryOrder.filter(cat => countCategory(cat)).map(cat => `<a class="nav-link" data-nav="category/${cat}" href="#category/${cat}"><span class="nav-icon">${categories[cat].icon}</span>${esc(categories[cat].label)}<span class="count">${countCategory(cat)}</span></a>`),
      `<hr class="nav-rule"><a class="nav-link" data-nav="pdfs" href="#pdfs"><span class="nav-icon">▧</span>Printable chapters</a>`
    ];
    document.getElementById("navigation").innerHTML = list.join("");
    document.getElementById("brand-title").textContent = data.title || "Software foundation";
    document.getElementById("snapshot-date").textContent = niceDate();
    document.getElementById("footer-title").textContent = data.title || "Code atlas";
  }

  function symbolTable(items, includeReason = false) {
    if (!items.length) return empty("No matching symbols in this snapshot.");
    return `<div class="table-wrap"><table><thead><tr><th>SYMBOL</th><th>KIND</th><th>${includeReason ? "ENTRY POINT" : "LOCATION"}</th><th>CALLS</th></tr></thead><tbody>${items.map(s => `<tr><td class="name"><a href="${routeSymbol(s)}">${esc(s.qualified_name || s.name)}</a><span class="path">${esc(s.file.path)}</span></td><td>${kindBadge(s)}</td><td>${includeReason ? `<span class="small">${esc(s.entry_reason || "")}</span>` : `<a href="${routeSource(s.file, s.line)}">Line ${esc(s.line)}</a>${s.owner ? `<span class="path">${esc(s.owner)}</span>` : ""}`}</td><td>${(s.calls || []).length}<span class="path">${(incoming.get(String(s.id)) || []).length} incoming sites</span></td></tr>`).join("")}</tbody></table></div>`;
  }

  function fileTable(items) {
    if (!items.length) return empty("No matching files in this snapshot.");
    return `<div class="table-wrap"><table><thead><tr><th>FILE</th><th>LANGUAGE</th><th>SYMBOLS</th><th>LINES</th><th>SOURCE</th></tr></thead><tbody>${items.map(f => `<tr><td class="name"><a class="file-name" href="${routeFile(f)}">${esc(f.path)}</a></td><td><span class="badge">${esc(f.language || "text")}</span></td><td>${(f.symbols || []).length}</td><td>${esc(f.line_count || String(f.text || "").split("\n").length)}</td><td><a href="${routeSource(f)}">View snapshot ↗</a></td></tr>`).join("")}</tbody></table></div>`;
  }

  function pdfLinks(category) {
    const pdfs = (data.pdfs || []).filter(p => !category || p.category === category || (category === "home" && /overview|home/i.test(p.category || "")));
    if (!pdfs.length) return "";
    return `<div class="pdf-grid">${pdfs.map(p => {
      const name = String(p.name || "");
      const href = name.startsWith("pdf/") || name.startsWith("pdfs/") ? name.split("/").map(encode).join("/") : "pdf/" + encode(name);
      return `<a class="pdf-link" href="${esc(href)}"><span class="pdf-icon">PDF</span><span>${esc(p.title || p.name)}<small>Open printable chapter ↗</small></span></a>`;
    }).join("")}</div>`;
  }

  function guideCards() {
    return (data.guide || []).map(g => `<article class="guide-card"><h3>${esc(g.title)}</h3><p>${esc(g.body)}</p><div class="guide-links">${(g.links || []).map(link => fileLink(link.path, link.line, link.label)).join("")}</div></article>`).join("");
  }

  function changeMap(id) { return (data.change_maps || []).find(map => String(map.id) === String(id)); }
  function changeRoute(map, node) { return "#change/" + encode(map.id) + (node ? "/" + encode(node.id) : ""); }
  function flowMap(id) { return (data.flow_maps || []).find(map => String(map.id) === String(id)); }
  function flowRoute(map, node) { return "#flow/" + encode(map.id) + (node ? "/" + encode(node.id) : ""); }
  function codeMap(id) { return (data.code_maps || []).find(map => String(map.id) === String(id)); }
  function codeRoute(map, node) { return "#code/" + encode(typeof map === "object" ? map.id : map) + (node ? "/" + encode(typeof node === "object" ? node.id : node) : ""); }
  function childCode(node) { return node?.child && codeMap(node.child.map) ? {map: codeMap(node.child.map), node: node.child.node} : null; }
  function chartRoute(map, node) {
    const child = executionMap(map) && childCode(node);
    return child ? codeRoute(child.map, child.node) : map.kind === "code" ? codeRoute(map, node) : executionMap(map) ? flowRoute(map, node) : changeRoute(map, node);
  }
  function executionMap(map) { return map.kind === "execution"; }
  function hasConceptGuide() { return data.conceptual_guide?.html_file === "AI-AUTHORED__GUI-MENTAL-MODEL.html"; }
  function conceptGuideLink() {
    return hasConceptGuide() ? `<a class="concept-guide-button" href="AI-AUTHORED__GUI-MENTAL-MODEL.html" title="${esc(data.conceptual_guide.title || "AI-authored GUI mental model")}"><strong>AI-AUTHORED · GUI mental model</strong><span>Simple diagrams, linked to code →</span></a>` : "";
  }
  function codeEntryLinks() {
    const entry = codeMap("main-to-widgets"), definitions = codeMap("widget-definitions");
    const concept = conceptGuideLink();
    if (!entry) return concept ? `<nav class="concept-guide-entry" aria-label="AI-authored conceptual guide">${concept}</nav>` : "";
    const node = (entry.nodes || []).find(item => String(item.id) === "entry");
    return `<nav class="code-entry-start" aria-label="Start at the application entry point"><a class="code-entry-main" href="${codeRoute(entry, node)}"><span class="code-entry-icon" aria-hidden="true">↳</span><span><small>Start with the actual code</small><strong>main() → widget definitions</strong><span>Follow the entry point through the diagrams into widget construction.</span></span><span class="code-entry-arrow" aria-hidden="true">→</span></a><span class="code-entry-related">${definitions ? `<a class="code-entry-definitions" href="${codeRoute(definitions)}">Widget declarations diagram ↗</a>` : ""}${concept}</span></nav>`;
  }
  function wrappedText(value, width = 24, maxLines = 3) {
    const words = String(value || "").split(/\s+/);
    const lines = [];
    let line = "";
    words.forEach(word => {
      if (line && (line + " " + word).length > width) {lines.push(line); line = word;}
      else line = line ? line + " " + word : word;
    });
    if (line) lines.push(line);
    if (lines.length > maxLines) {lines[maxLines - 1] = short(lines.slice(maxLines - 1).join(" "), width); return lines.slice(0, maxLines);}
    return lines;
  }
  function taskChoices(activeId, home) {
    const structure = [
      {id: "widget", title: "Add a widget & click handler", subtitle: "Widget → event → handler → helper", icon: "▣"},
      {id: "widget-placement", title: "Place a widget", subtitle: "Order, bounds & future page membership", icon: "⊞"},
      {id: "tabs", title: "Add a tab", subtitle: "Declare pages, ownership & tab switching", icon: "▱"},
      {id: "source-files", title: "Add a source file to the compiler", subtitle: "Owner target → source list → compiler", icon: "＋"}
    ].map(choice => ({...choice, map: changeMap(choice.id)})).filter(choice => choice.map);
    const behavior = [
      {id: "validation", title: "Change validation rules"},
      {id: "core-operation", title: "Edit a selected entry"},
      {id: "commands", title: "Add menu/shortcut commands"},
      {id: "background-task", title: "Run cancellable background work"},
      {id: "import-export", title: "Change import/export format"}
    ].map(choice => ({...choice, map: changeMap(choice.id)})).filter(choice => choice.map);
    const behaviorActive = behavior.some(choice => String(choice.id) === String(activeId));
    const structureHtml = structure.length && (home || !behaviorActive) ? `<div class="task-choice-group"><div class="task-group-label">Structure & widgets</div><nav class="task-choices" aria-label="Structure and widget edit tasks">${structure.map(choice => `<a href="${home ? "#home/" + encode(choice.id) : changeRoute(choice.map)}" class="task-choice${String(choice.id) === String(activeId) ? " active" : ""}"${String(choice.id) === String(activeId) ? ' aria-current="page"' : ""}><span class="task-choice-icon" aria-hidden="true">${choice.icon}</span><span><strong>${esc(choice.title)}</strong><small>${esc(choice.subtitle)}</small></span><span class="task-choice-arrow" aria-hidden="true">→</span></a>`).join("")}</nav></div>` : "";
    const behaviorHtml = behavior.length && (home || behaviorActive) ? `<div class="task-choice-group behavior-task-group"><div class="task-group-label">Behavior workflows <span>Follow the change through the application</span></div><nav class="behavior-task-choices" aria-label="Behavior workflow edit tasks">${behavior.map(choice => `<a href="${home ? "#home/" + encode(choice.id) : changeRoute(choice.map)}" class="behavior-task-choice${String(choice.id) === String(activeId) ? " active" : ""}"${String(choice.id) === String(activeId) ? ' aria-current="page"' : ""}><strong>${esc(choice.title)}</strong><span aria-hidden="true">→</span></a>`).join("")}</nav></div>` : "";
    return `<div class="task-discovery">${structureHtml}${behaviorHtml}${home ? scenarioChoices(null, true) : ""}</div>`;
  }
  function scenarioChoices(activeId, embedded = false) {
    const maps = data.flow_maps || [];
    if (!maps.length) return "";
    const labels = {compile: "Compile", test: "Test", release: "Release", startup: "Startup", "button-click": "Button click", import: "Import", export: "Export"};
    return `<section class="flow-discovery${embedded ? " embedded" : ""}"><div class="task-group-label">What runs when… ${embedded ? '<a href="#flows">Explore execution scenarios →</a>' : '<span>Named calls, events, returns & process boundaries</span>'}</div><nav class="scenario-choices" aria-label="Execution scenarios">${maps.map(map => `<a class="scenario-choice${String(map.id) === String(activeId) ? " active" : ""}" href="${flowRoute(map)}" title="${esc(map.question || map.title)}"${String(map.id) === String(activeId) ? ' aria-current="page"' : ""}>${esc(labels[map.id] || map.title)}<span aria-hidden="true">⇢</span></a>`).join("")}</nav></section>`;
  }
  function anchorData(anchor) {
    const file = fileById.get(String(anchor.file_id || "")) || sourceFile(anchor.path);
    const symbol = symbolById.get(String(anchor.symbol_id || ""));
    return {file, symbol, usable: anchor.status === "verified" && !!file};
  }
  function anchorControls(anchor, compact = false) {
    const resolved = anchorData(anchor);
    const path = anchor.path || resolved.file?.path || "";
    if (!path && !anchor.file_id && !anchor.symbol_id && anchor.status !== "missing") return "";
    if (anchor.status === "missing" || (anchor.status === "verified" && !resolved.usable)) return `<div class="anchor-missing"><strong>Source anchor changed; review required</strong>${path ? `<span class="mono">${esc(path)}${anchor.line ? ":" + esc(anchor.line) : ""}</span>` : ""}</div>`;
    if (!resolved.usable) return path ? `<span class="small muted mono">${esc(path)}${anchor.line ? ":" + esc(anchor.line) : ""} · proposed location</span>` : "";
    return `<div class="change-location"><a class="mono" href="${routeSource(resolved.file, anchor.line || 1)}">${esc(path)}:${esc(anchor.line || 1)}</a></div><div class="change-source-links"><a class="${compact ? "" : "button primary"}" href="${routeSource(resolved.file, anchor.line || 1)}">${compact ? "Source ↗" : "Open source at L" + esc(anchor.line || 1)}</a>${resolved.symbol ? `<a class="${compact ? "" : "button"}" href="${routeSymbol(resolved.symbol)}">${compact ? "Function details ↗" : "Explore " + esc(short(resolved.symbol.name, 24))}</a>` : ""}${!compact ? `<a class="button" href="${routeFile(resolved.file)}">File overview</a>` : ""}${printLink(resolved.symbol?.id, resolved.file.id, anchor.line || 1, compact ? "" : "button")}</div>`;
  }
  function parameterRoute(guide, map, node) { return "#parameters/" + encode(guide.id) + (map && node ? "/" + encode(map.id) + "/" + encode(node.id) : ""); }
  function parameterValue(value, absent = "Not specified") { return value == null ? absent : typeof value === "object" ? JSON.stringify(value) : String(value) === "" ? '""' : String(value); }
  function parameterGuide(guide, map, node, compact = false) {
    const example = guide.example || {};
    return `<section class="parameter-guide${compact ? " compact" : " full"}" data-parameter-guide="${esc(guide.id)}"><div class="parameter-guide-heading"><div><div class="parameter-eyebrow">PARAMETER GUIDE</div><h3>${esc(guide.title)}</h3></div>${compact ? `<a class="parameter-open" href="${parameterRoute(guide, map, node)}">Read full guide ↗</a>` : ""}</div>${guide.summary ? `<p class="parameter-summary">${esc(guide.summary)}</p>` : ""}${guide.status === "missing" ? '<div class="anchor-missing"><strong>Source anchor changed; review required</strong><span>Check the linked declarations before relying on this parameter guide.</span></div>' : ""}<div class="parameter-synopsis-wrap"><h4>Synopsis</h4><pre class="parameter-synopsis"><code>${esc(guide.syntax || "")}</code></pre><p class="parameter-syntax-note">${esc(guide.syntax_note || "This synopsis names the parameters for reading. Use the filled example for the source syntax.")}</p></div><div class="parameter-guide-body"><div class="parameter-definition-list"><h4>Parameters, in order</h4><dl class="parameter-list">${(guide.parameters || []).map((parameter, i) => `<div class="parameter-item"><dt><span class="parameter-number">${esc(parameter.position == null ? i + 1 : parameter.position)}</span><code class="parameter-name">${esc(parameter.name)}</code>${parameter.type ? `<span class="parameter-type">${esc(parameter.type)}</span>` : ""}</dt><dd><p class="parameter-description">${esc(parameter.description || "")}</p><div class="parameter-values"><div><span class="parameter-value-label">Default</span><code>${esc(parameterValue(parameter.default))}</code></div><div><span class="parameter-value-label">Example value</span><code>${esc(parameterValue(parameter.example_value))}</code></div></div></dd></div>`).join("")}</dl></div><div class="parameter-example"><h4>${esc(example.label || "Filled, labeled example")}</h4><pre class="parameter-example-code"><code>${esc(example.code || "")}</code></pre>${example.notes && example.notes.length ? `<ul class="parameter-example-notes">${example.notes.map(note => `<li>${esc(note)}</li>`).join("")}</ul>` : ""}</div></div>${!compact && (guide.references || []).length ? `<div class="parameter-source-references"><h4>Source declarations behind this guide</h4>${(guide.references || []).map(reference => `<div class="change-reference"><strong>${esc(reference.label || reference.path || "Source declaration")}</strong>${anchorControls(reference, true)}</div>`).join("")}</div>` : ""}</section>`;
  }
  function nodeParameterGuides(node, map, forPrint) {
    const guides = unique((node.parameter_guides || []).filter(guide => guide && guide.id), guide => String(guide.id));
    if (!guides.length) return "";
    if (forPrint) return `<div class="parameter-print-links"><strong>Parameter references:</strong> ${guides.map(guide => `<a href="${parameterRoute(guide, map, node)}">${esc(guide.title)}</a>`).join(" · ")}</div>`;
    return `<div class="node-parameter-guides">${guides.map(guide => parameterGuide(parameterById.get(String(guide.id)) || guide, map, node, true)).join("")}</div>`;
  }
  function mapParameterGuides(map) {
    const guides = unique((map.nodes || []).flatMap(node => node.parameter_guides || []), guide => String(guide.id));
    return guides.length ? `<div class="map-parameter-print"><h2>${executionMap(map) ? "Parameter reference for this scenario" : "Parameter reference for this edit path"}</h2>${guides.map(guide => parameterGuide(parameterById.get(String(guide.id)) || guide, null, null, false)).join("")}</div>` : "";
  }
  function renderParameters(id, mapId, nodeId) {
    const guide = parameterById.get(String(id));
    if (id && !guide) return renderMissing("Parameter guide");
    if (!guide) {
      const guides = [...parameterById.values()];
      main.innerHTML = `${crumbs([{label: "Parameter guides"}])}${pageHeading("Reference", "Parameter guides", "Read positional fields in plain language, then use a filled example with every value labeled.", '<a class="button" href="#home">↑ Edit task overview</a>')}<div class="parameter-library">${guides.map(item => `<a class="parameter-library-card" href="${parameterRoute(item)}"><div class="parameter-eyebrow">PARAMETER GUIDE</div><h2>${esc(item.title)}</h2><p>${esc(item.summary || "")}</p><span>Read parameters & example →</span></a>`).join("") || empty("This snapshot has no parameter guides.")}</div>`;
      return;
    }
    const contexts = parameterContexts.get(String(id)) || [];
    const context = contexts.find(item => String(item.map.id) === String(mapId) && String(item.node.id) === String(nodeId)) || contexts.find(item => item.map.id === state.navigationContext?.mapId && item.node.id === state.navigationContext?.nodeId) || contexts[0];
    if (context) {
      if (executionMap(context.map)) {state.lastFlowMap = context.map.id; state.selectedFlowNodes[context.map.id] = context.node.id;}
      else {state.lastChangeMap = context.map.id; state.selectedChangeNodes[context.map.id] = context.node.id;}
      state.navigationContext = {kind: executionMap(context.map) ? "execution" : "edit", mapId: context.map.id, nodeId: context.node.id};
    }
    const up = context ? `<a class="button" href="${chartRoute(context.map, context.node)}">↑ ${esc(short(context.node.title, 40))}</a>` : '<a class="button" href="#home">↑ Edit task overview</a>';
    main.innerHTML = `${crumbs([{label: "Parameter guides", href: "#parameters"}, {label: guide.title}])}${pageHeading("Readable code reference", guide.title, "Read the named fields before looking at the positional source syntax.", up)}${context ? `<div class="parameter-context">Used in <a href="${chartRoute(context.map, context.node)}">${esc(context.node.title)}</a> · ${esc(context.map.title)}</div>` : ""}${parameterGuide(guide, context?.map, context?.node, false)}${contexts.length > 1 ? section("Steps that use this guide", `<div class="guide-links">${contexts.map(item => `<a href="${chartRoute(item.map, item.node)}">${esc(item.node.title)} <span class="muted">(${esc(item.map.title)})</span></a>`).join("")}</div>`) : ""}`;
  }
  function actionDetails(map, node, forPrint = false) {
    if (!node) return empty("Choose a node to see the exact edit location and its source context.");
    const references = node.references || [];
    const running = executionMap(map);
    const roles = running ? ["ENTRY", "CALL", "PROCESS", "DECISION", "EVENT", "OUTPUT"] : ["EDIT", "REUSE", "DECISION", "NEW", "JUMP"];
    const role = roles.includes(node.role) ? node.role : running ? "CALL" : "EDIT";
    const linkedMap = node.link_map ? (running ? flowMap(node.link_map) || changeMap(node.link_map) : changeMap(node.link_map) || flowMap(node.link_map)) : null;
    return `<article class="change-action${running ? " execution-action" : ""}${forPrint ? " change-print-action" : ""}"><div class="change-action-heading"><span class="change-role role-${role.toLowerCase()}">${role}</span>${node.optional ? '<span class="badge unresolved">Optional branch</span>' : ""}${node.status === "proposed" ? `<span class="badge entry">${running ? "Illustrative step" : "Proposed addition"}</span>` : ""}</div><h2>${esc(node.title)}</h2>${node.summary ? `<p class="change-action-summary">${esc(node.summary)}</p>` : ""}<div class="change-instruction"><h3>${running ? "What runs" : role === "REUSE" ? "Follow or reuse" : role === "DECISION" ? "Decide this first" : role === "JUMP" ? "Follow this path" : "What to change"}</h3><p>${esc(node.action || node.summary || (running ? "Inspect the linked source to follow this step." : "Inspect the linked source before editing."))}</p></div>${node.why ? `<p class="change-why"><strong>Why here:</strong> ${esc(node.why)}</p>` : ""}${node.status === "proposed" && references.some(reference => reference.status === "verified" && reference.file_id === node.file_id && reference.line === node.line) ? `<p class="small muted">${running ? "Existing source context for this illustrative scenario step." : "Existing edit context below; the proposed addition is not implemented here."}</p>${anchorControls({...node, status: "verified"})}` : anchorControls(node)}${running ? printFlowLink(map, node) : ""}${nodeParameterGuides(node, map, forPrint)}${node.snippet ? `<div class="change-snippet-label">${!running && node.status === "proposed" ? "Existing pattern in captured source" : "Captured source context"}</div><pre class="change-snippet">${esc(node.snippet)}</pre>` : ""}${references.length ? `<div class="change-references"><h3>${running ? "Source & call context" : "Related edit locations"}</h3>${references.map(reference => `<div class="change-reference"><strong>${esc(reference.label || reference.path || "Source context")}</strong>${anchorControls(reference, true)}${reference.snippet && (!forPrint || reference.snippet !== node.snippet) ? `<details class="change-reference-snippet"${forPrint ? " open" : ""}><summary>Show source context</summary><pre class="change-snippet">${esc(reference.snippet)}</pre></details>` : ""}</div>`).join("")}</div>` : ""}${linkedMap ? `<a class="change-drilldown" href="${chartRoute(linkedMap)}">Open ${esc(linkedMap.title)} →</a>` : ""}</article>`;
  }
  function taskPath(from, to, boxes, boxWidth, boxHeight, columnPitch, rowPitch, width, height) {
    const sameRow = Math.abs(from.y - to.y) < 8;
    const right = to.x > from.x, down = to.y > from.y;
    const start = sameRow ? {x: from.x + (right ? boxWidth : 0), y: from.y + boxHeight / 2} : {x: from.x + boxWidth / 2, y: from.y + (down ? boxHeight : 0)};
    const finish = sameRow ? {x: to.x + (right ? 0 : boxWidth), y: to.y + boxHeight / 2} : {x: to.x + boxWidth / 2, y: to.y + (down ? 0 : boxHeight)};
    const entry = sameRow ? {x: start.x + (right ? 1 : -1) * (columnPitch - boxWidth) / 2, y: start.y} : {x: start.x, y: start.y + (down ? 1 : -1) * (rowPitch - boxHeight) / 2};
    const exit = sameRow ? {x: finish.x - (right ? 1 : -1) * (columnPitch - boxWidth) / 2, y: finish.y} : {x: finish.x, y: finish.y - (down ? 1 : -1) * (rowPitch - boxHeight) / 2};
    const xs = [...new Set([16, width - 16, entry.x, exit.x, ...boxes.flatMap(box => [box.x + boxWidth / 2, box.x + boxWidth + (columnPitch - boxWidth) / 2])])].filter(x => x >= 0 && x <= width).sort((a, b) => a - b);
    const ys = [...new Set([16, height - 16, entry.y, exit.y, ...boxes.flatMap(box => [box.y + boxHeight / 2, box.y + boxHeight + (rowPitch - boxHeight) / 2])])].filter(y => y >= 0 && y <= height).sort((a, b) => a - b);
    const clear = (a, b) => !boxes.some(box => {
      const left = box.x - 6, rightEdge = box.x + boxWidth + 6, top = box.y - 6, bottom = box.y + boxHeight + 6;
      return a.x === b.x ? a.x > left && a.x < rightEdge && Math.max(a.y, b.y) > top && Math.min(a.y, b.y) < bottom : a.y > top && a.y < bottom && Math.max(a.x, b.x) > left && Math.min(a.x, b.x) < rightEdge;
    });
    const begin = {xi: xs.indexOf(entry.x), yi: ys.indexOf(entry.y), direction: "", cost: 0, previous: null};
    const queue = [begin], best = new Map();
    let found = null;
    while (queue.length) {
      queue.sort((a, b) => a.cost - b.cost);
      const current = queue.shift();
      const key = `${current.xi}/${current.yi}/${current.direction}`;
      if (best.has(key) && best.get(key) < current.cost) continue;
      const point = {x: xs[current.xi], y: ys[current.yi]};
      if (point.x === exit.x && point.y === exit.y) {found = current; break;}
      [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => {
        const xi = current.xi + dx, yi = current.yi + dy;
        if (xi < 0 || yi < 0 || xi >= xs.length || yi >= ys.length) return;
        const next = {x: xs[xi], y: ys[yi]};
        if (!clear(point, next)) return;
        const direction = dx ? "x" : "y";
        const cost = current.cost + Math.abs(next.x - point.x) + Math.abs(next.y - point.y) + (current.direction && current.direction !== direction ? 15 : 0);
        const nextKey = `${xi}/${yi}/${direction}`;
        if (best.has(nextKey) && best.get(nextKey) <= cost) return;
        best.set(nextKey, cost); queue.push({xi, yi, direction, cost, previous: current});
      });
    }
    let points = [];
    for (let cursor = found; cursor; cursor = cursor.previous) points.unshift({x: xs[cursor.xi], y: ys[cursor.yi]});
    if (!points.length) points = [entry, exit];
    points = [start, ...points, finish].filter((point, i, all) => !i || point.x !== all[i - 1].x || point.y !== all[i - 1].y);
    points = points.filter((point, i, all) => !i || i === all.length - 1 || !((point.x === all[i - 1].x && point.x === all[i + 1].x) || (point.y === all[i - 1].y && point.y === all[i + 1].y)));
    const segments = points.slice(1).map((point, i) => ({a: points[i], b: point, length: Math.abs(point.x - points[i].x) + Math.abs(point.y - points[i].y)}));
    const labelSegment = [...segments].reverse().sort((a, b) => b.length - a.length)[0];
    const vertical = labelSegment && labelSegment.a.x === labelSegment.b.x;
    return {path: points.map((point, i) => `${i ? "L" : "M"} ${point.x} ${point.y}`).join(" "), labelX: labelSegment ? (labelSegment.a.x + labelSegment.b.x) / 2 : start.x, labelY: labelSegment ? (labelSegment.a.y + labelSegment.b.y) / 2 : start.y, narrow: sameRow || vertical};
  }
  function taskDiagram(map, selected) {
    const nodes = map.nodes || [];
    const running = executionMap(map);
    const edgeKinds = running ? ["call", "process", "conditional", "return", "event", "step"] : ["edit-dependency", "runtime", "conditional"];
    const roles = running ? ["ENTRY", "CALL", "PROCESS", "DECISION", "EVENT", "OUTPUT"] : ["EDIT", "REUSE", "DECISION", "NEW", "JUMP"];
    if (!nodes.length) return empty(running ? "No execution steps were generated for this scenario." : "No edit steps were generated for this task.");
    const boxWidth = 190, boxHeight = 106, columnPitch = 270, rowPitch = 160;
    const columns = Math.max(...nodes.map(node => Number(node.column) || 0)) + 1;
    const rows = Math.max(...nodes.map(node => Number(node.row) || 0)) + 1;
    const width = columns * columnPitch - (columnPitch - boxWidth) + 64;
    const height = rows * rowPitch - (rowPitch - boxHeight) + 70;
    const positions = new Map(nodes.map(node => [String(node.id), {x: 32 + (Number(node.column) || 0) * columnPitch, y: 36 + (Number(node.row) || 0) * rowPitch}]));
    const marker = "task-arrow-" + (++graphSequence);
    const edgeSvg = (map.edges || []).map(edge => {
      const from = positions.get(String(edge.from)), to = positions.get(String(edge.to));
      if (!from || !to) return "";
      const {path, labelX, labelY, narrow} = taskPath(from, to, [...positions.values()], boxWidth, boxHeight, columnPitch, rowPitch, width, height);
      const kind = edgeKinds.includes(edge.kind) ? edge.kind : running ? "call" : "edit-dependency";
      const labels = wrappedText(edge.label || "", narrow ? 13 : 23, 2);
      const labelWidth = Math.min(narrow ? 72 : 150, Math.max(36, Math.max(...labels.map(line => line.length), 1) * 5.2 + 10));
      return `<g class="task-edge edge-${kind}"><path d="${path}" marker-end="url(#${marker}-${kind})"><title>${esc(edge.label || "")}</title></path>${labels.length ? `<g class="task-edge-label"><rect x="${labelX - labelWidth / 2}" y="${labelY - 10}" width="${labelWidth}" height="${labels.length * 13 + 5}" rx="4"></rect>${labels.map((label, i) => `<text x="${labelX}" y="${labelY + 1 + i * 13}" text-anchor="middle">${esc(label)}</text>`).join("")}</g>` : ""}</g>`;
    }).join("");
    const nodeSvg = nodes.map(node => {
      const pos = positions.get(String(node.id));
      const role = roles.includes(node.role) ? node.role : running ? "CALL" : "EDIT";
      const titleLines = wrappedText(node.title, 24, 3);
      const child = running && childCode(node);
      const origin = child ? ` data-code-parent-kind="flow" data-code-parent-map="${esc(map.id)}" data-code-parent-node="${esc(node.id)}" data-code-child="${esc(child.map.id)}"` : "";
      return `<a href="${chartRoute(map, node)}" class="task-node role-${role.toLowerCase()}${selected && String(selected.id) === String(node.id) ? " selected" : ""}${node.optional ? " optional" : ""}" data-task-node="${esc(node.id)}"${origin} aria-label="${esc(role + ": " + node.title + (child ? ". Open code diagram" : ""))}"><title>${esc(node.title)} · ${esc(node.summary || node.action || "Click to inspect this step")}</title><rect class="task-node-box" x="${pos.x}" y="${pos.y}" width="${boxWidth}" height="${boxHeight}" rx="8"></rect><rect class="task-role-chip" x="${pos.x + 12}" y="${pos.y + 11}" width="${role.length * 6 + 15}" height="17" rx="4"></rect><text class="task-node-role" x="${pos.x + 19}" y="${pos.y + 23}">${role}</text>${node.optional ? `<text class="task-optional-label" x="${pos.x + boxWidth - 12}" y="${pos.y + 22}" text-anchor="end">optional</text>` : ""}${titleLines.map((line, i) => `<text class="task-node-title" x="${pos.x + 12}" y="${pos.y + 47 + i * 15}">${esc(line)}</text>`).join("")}<text class="task-node-hint" x="${pos.x + 12}" y="${pos.y + boxHeight - 11}">${child ? "Open code diagram →" : node.status === "missing" ? "Anchor needs review" : node.status === "proposed" ? (running ? "Illustrative step · click for context" : "Proposed addition · click for context") : node.path ? esc(short(String(node.path).split("/").pop(), 26)) + (node.line ? " · L" + esc(node.line) : "") : running ? "Click for source & call context" : "Click for the edit guidance"}</text></a>`;
    }).join("");
    const legend = running ? `<span><i class="task-key call"></i>Direct call</span><span><i class="task-key process"></i>Process boundary</span><span><i class="task-key conditional"></i>Conditional branch</span><span><i class="task-key event"></i>Event / dispatch</span><span><i class="task-key return"></i>Return / resume caller</span><span><i class="task-key step"></i>Local step / sequence</span>` : `<span><i class="task-key edit-dependency"></i>Edit dependency / next edit</span><span><i class="task-key runtime"></i>Runtime call / event</span><span><i class="task-key conditional"></i>Conditional or optional branch</span>`;
    return `<div class="task-diagram-canvas"><svg class="task-diagram${running ? " execution-diagram" : ""} graph-svg" id="task-diagram" role="group" aria-label="${esc(map.title + (running ? ": graphical execution scenario" : ": graphical edit path"))}" viewBox="0 0 ${width} ${height}" data-width="${width}" data-height="${height}"><defs>${edgeKinds.map(kind => `<marker id="${marker}-${kind}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M 0 0 L 8 4 L 0 8 z" class="marker-${kind}"></path></marker>`).join("")}</defs>${edgeSvg}${nodeSvg}</svg></div><div class="task-diagram-controls"><span>${running ? (nodes.some(childCode) ? "Click a step to open its code diagram. Follow calls into deeper diagrams." : "Click a step to inspect its calls, events, process boundary, and source.") : "Click an edit step for its exact location and source context."}</span><div class="graph-buttons"><button type="button" data-graph="task-diagram" data-zoom="in" aria-label="${running ? "Zoom execution diagram in" : "Zoom edit diagram in"}">+</button><button type="button" data-graph="task-diagram" data-zoom="out" aria-label="${running ? "Zoom execution diagram out" : "Zoom edit diagram out"}">−</button><button type="button" data-graph="task-diagram" data-zoom="reset">Fit</button></div></div><div class="task-diagram-legend">${legend}</div>`;
  }
  function renderChange(mapId, nodeId, home = false) {
    const map = changeMap(mapId) || changeMap("widget") || (data.change_maps || [])[0];
    if (!map) return renderInventory();
    state.activeChangeMap = map.id;
    state.lastChangeMap = map.id;
    const nodes = map.nodes || [];
    const selected = nodes.find(node => String(node.id) === String(nodeId || state.selectedChangeNodes[map.id] || "")) || nodes[0];
    if (selected) state.selectedChangeNodes[map.id] = selected.id;
    state.navigationContext = {kind: "edit", mapId: map.id, nodeId: selected?.id};
    const runtime = changeMap("widget-runtime");
    main.innerHTML = `${home ? crumbs([]) : crumbs([{label: "Edit task maps", href: "#home"}, {label: map.title}])}${pageHeading(home ? "Edit the foundation" : "Edit task map", home ? "Where should I edit?" : map.title, home ? "Choose a change. Follow the chart, then click a step to see the file, line, and code to edit." : map.summary, home ? '<a class="button" href="#inventory">Browse code inventory →</a>' : '<a class="button" href="#home">↑ Edit task overview</a>')}${home ? codeEntryLinks() : ""}${taskChoices(map.id, home)}<section class="change-map-section"><div class="change-map-heading"><div><h2>${esc(map.question || map.title)}</h2><p>${esc(map.edge_meaning || "Arrows show the next edit dependency; they do not imply execution order.")}</p></div>${map.id === "widget" && runtime ? `<a class="button" href="${changeRoute(runtime)}">Trace existing Add click →</a>` : home ? `<a class="button" href="${changeRoute(map)}">Open this task map ↗</a>` : ""}</div><div class="change-layout"><div class="change-chart panel">${taskDiagram(map, selected)}</div><aside class="change-detail-panel panel" id="change-detail" aria-label="Selected edit step">${actionDetails(map, selected)}</aside></div><div class="change-snapshot"><span>Source snapshot · ${esc(niceDate())} · code may have changed since.</span><a href="#inventory">Find another function or file →</a></div></section><section class="change-print-details print-only">${mapParameterGuides(map)}<h2>All edit steps & source anchors</h2>${nodes.map(node => actionDetails(map, node, true)).join("")}</section>${pdfLinks("changes") || pdfLinks("change-maps") || pdfLinks("edit-paths") ? section("Print these edit paths", pdfLinks("changes") || pdfLinks("change-maps") || pdfLinks("edit-paths")) : ""}`;
  }
  function renderHome(mapId) { renderChange(mapId || state.activeChangeMap, null, true); }
  function renderFlow(mapId, nodeId, overview = false) {
    const maps = data.flow_maps || [];
    if (!maps.length) {
      main.innerHTML = `${crumbs([{label: "Execution scenarios"}])}${pageHeading("Execution", "What runs when…", "This snapshot does not include execution scenarios.", '<a class="button" href="#home">↑ Edit task overview</a>')}`;
      return;
    }
    const map = flowMap(mapId || state.activeFlowMap) || flowMap("startup") || maps[0];
    if (mapId && !flowMap(mapId)) return renderMissing("Execution scenario");
    const explicitNode = (map.nodes || []).find(node => String(node.id) === String(nodeId));
    const explicitChild = explicitNode && childCode(explicitNode);
    if (explicitChild) return renderCode(explicitChild.map.id, explicitChild.node, {kind: "flow", map: map.id, node: explicitNode.id});
    state.activeFlowMap = map.id;
    state.lastFlowMap = map.id;
    const nodes = map.nodes || [];
    const selected = nodes.find(node => String(node.id) === String(nodeId || state.selectedFlowNodes[map.id] || "")) || nodes[0];
    const hierarchy = nodes.some(childCode);
    if (selected) state.selectedFlowNodes[map.id] = selected.id;
    state.navigationContext = {kind: "execution", mapId: map.id, nodeId: selected?.id};
    main.innerHTML = `${overview ? crumbs([{label: "Execution scenarios"}]) : crumbs([{label: "Execution scenarios", href: "#flows"}, {label: map.title}])}${pageHeading("Existing execution scenarios", overview ? "What runs when…" : map.title, overview ? (hierarchy ? "Choose a scenario, then click a step to open a diagram containing its actual source lines." : "Choose a scenario. Follow its named calls, events, returns, and process boundaries, then inspect the captured source.") : map.summary, overview ? '<a class="button" href="#home">↑ Edit task overview</a>' : '<a class="button" href="#flows">↑ Execution scenarios</a>')}${overview || map.id === "startup" ? codeEntryLinks() : ""}${scenarioChoices(map.id)}<section class="change-map-section execution-map-section"><div class="change-map-heading"><div><h2>${esc(map.question || map.title)}</h2><p>${esc(map.edge_meaning || "Arrows identify source-curated calls and ordering in this scenario. They are not a complete execution trace.")}</p></div>${printFlowLink(map)}</div><div class="change-layout${hierarchy ? " hierarchical-flow-layout" : ""}"><div class="change-chart panel">${taskDiagram(map, selected)}</div>${hierarchy ? "" : `<aside class="change-detail-panel panel" id="change-detail" aria-label="Selected execution step">${actionDetails(map, selected)}</aside>`}</div><div class="change-snapshot"><span>Source-curated scenario · ${esc(niceDate())} · code may have changed since.</span><a href="#home">Find an edit task →</a></div></section>${hierarchy ? "" : `<section class="change-print-details print-only">${mapParameterGuides(map)}<h2>All execution steps & source anchors</h2>${nodes.map(node => actionDetails(map, node, true)).join("")}</section>`}${pdfLinks("flows") ? section("Print execution scenarios", pdfLinks("flows")) : ""}`;
  }

  function validCodeParent(parent) {
    return parent && (parent.kind === "flow" ? !!flowMap(parent.map) : parent.kind === "code" ? !!codeMap(parent.map) : false);
  }
  function codeParent(map, explicit) {
    if (validCodeParent(explicit)) state.codeOrigins[map.id] = explicit;
    if (validCodeParent(state.codeOrigins[map.id])) return state.codeOrigins[map.id];
    const previous = state.navigationContext;
    const parents = (map.parents || []).filter(validCodeParent);
    const matching = parents.find(parent => parent.map === previous?.mapId && parent.kind === (previous?.kind === "execution" ? "flow" : previous?.kind));
    const parent = matching || parents[0] || null;
    if (parent) state.codeOrigins[map.id] = parent;
    return parent;
  }
  function codeParentLink(parent) {
    return parent?.kind === "flow" ? flowRoute(flowMap(parent.map)) : parent?.kind === "code" ? codeRoute(codeMap(parent.map), parent.node) : "#flows";
  }
  function codeBreadcrumbs(map, parent) {
    const path = [], visited = new Set([String(map.id)]);
    let current = parent;
    while (validCodeParent(current)) {
      const entry = current.kind === "flow" ? flowMap(current.map) : codeMap(current.map);
      if (current.kind === "code" && visited.has(String(entry.id))) break;
      path.unshift({label: entry.title, href: codeParentLink(current)});
      if (current.kind === "flow") break;
      visited.add(String(entry.id));
      current = state.codeOrigins[entry.id] || (entry.parents || []).find(validCodeParent);
    }
    return crumbs([{label: "Execution scenarios", href: "#flows"}, ...path, {label: map.title}]);
  }
  function expandedCodeText(value) {
    let result = "";
    for (const character of String(value == null ? "" : value)) result += character === "\t" ? " ".repeat(4 - result.length % 4) : character;
    return result;
  }
  function completeWrappedText(value, width) {
    const pieces = String(value || "").split(/\s+/).flatMap(word => word.length > width ? Array.from({length: Math.ceil(word.length / width)}, (_, i) => word.slice(i * width, (i + 1) * width)) : [word]);
    return wrappedText(pieces.join(" "), width, Infinity);
  }
  function codeRows(node) {
    const rows = [];
    (node.code_lines || []).forEach(source => {
      const characters = Array.from(expandedCodeText(source.text));
      const chunks = characters.length ? Array.from({length: Math.ceil(characters.length / 63)}, (_, i) => characters.slice(i * 63, (i + 1) * 63).join("")) : [""];
      chunks.forEach((text, i) => rows.push({line: source.line, text, original: source.text, first: i === 0}));
    });
    return rows;
  }
  function codeDiagram(map, selected) {
    const nodes = map.nodes || [];
    if (!nodes.length) return empty("No captured code blocks were generated for this diagram.");
    const edgeKinds = ["call", "process", "conditional", "return", "event", "step", "dependency"];
    const rowsById = new Map(nodes.map(node => [String(node.id), codeRows(node)]));
    const notesById = new Map(nodes.map(node => [String(node.id), completeWrappedText(node.note || "", 77)]));
    const codeHeight = Math.max(1, ...[...rowsById.values()].map(rows => rows.length)) * 18;
    const noteHeight = Math.max(1, ...[...notesById.values()].map(rows => rows.length)) * 13;
    const edgeLabels = (map.edges || []).map(edge => completeWrappedText(edge.label || "", 20));
    const edgeLabelHeight = Math.max(1, ...edgeLabels.map(lines => lines.length)) * 13 + 6;
    const boxWidth = 560, boxHeight = 154 + codeHeight + noteHeight, columnPitch = 710, rowPitch = boxHeight + Math.max(100, edgeLabelHeight * 2 + 32);
    const columns = Math.max(...nodes.map(node => Number(node.column) || 0)) + 1, rows = Math.max(...nodes.map(node => Number(node.row) || 0)) + 1;
    const width = columns * columnPitch - (columnPitch - boxWidth) + 72, height = rows * rowPitch - (rowPitch - boxHeight) + 80;
    const positions = new Map(nodes.map(node => [String(node.id), {x: 36 + (Number(node.column) || 0) * columnPitch, y: 40 + (Number(node.row) || 0) * rowPitch}]));
    const marker = "code-arrow-" + (++graphSequence);
    const edges = (map.edges || []).map(edge => {
      const from = positions.get(String(edge.from)), to = positions.get(String(edge.to));
      if (!from || !to) return "";
      const routed = taskPath(from, to, [...positions.values()], boxWidth, boxHeight, columnPitch, rowPitch, width, height);
      const kind = edgeKinds.includes(edge.kind) ? edge.kind : "step";
      const labels = completeWrappedText(edge.label || "", routed.narrow ? 20 : 42);
      const labelWidth = Math.max(42, Math.max(...labels.map(label => label.length), 1) * 5.6 + 14);
      return `<g class="task-edge code-edge edge-${kind} emphasis-${edge.emphasis === "supporting" ? "supporting" : "primary"}"><path d="${routed.path}" marker-end="url(#${marker}-${kind})"><title>${esc(edge.label || "")}</title></path>${labels.length ? `<g class="task-edge-label"><rect x="${routed.labelX - labelWidth / 2}" y="${routed.labelY - 10}" width="${labelWidth}" height="${labels.length * 13 + 6}" rx="4"></rect>${labels.map((label, i) => `<text x="${routed.labelX}" y="${routed.labelY + 1 + i * 13}" text-anchor="middle">${esc(label)}</text>`).join("")}</g>` : ""}</g>`;
    }).join("");
    const nodeSvg = nodes.map(node => {
      const pos = positions.get(String(node.id)), code = rowsById.get(String(node.id));
      const child = childCode(node), primary = node.emphasis !== "supporting";
      const role = String(node.role || "CODE"), roleClass = role.toLowerCase().replace(/[^a-z0-9]+/g, "-");
      const source = anchorData(node), pdf = codePrintReference(map, node);
      const titles = wrappedText(node.title, 55, 2);
      const origin = child ? ` data-code-parent-kind="code" data-code-parent-map="${esc(map.id)}" data-code-parent-node="${esc(node.id)}" data-code-child="${esc(child.map.id)}"` : "";
      const tag = child ? "a" : "g";
      const opening = child ? `<a href="${codeRoute(child.map, child.node)}"${origin} class="code-node-body" aria-label="${esc(node.title + ". Open deeper code diagram")}">` : '<g class="code-node-body">';
      const noteLines = notesById.get(String(node.id));
      const body = `${opening}<title>${esc(node.title)}${child ? " · open deeper code diagram" : ""}</title><rect class="code-node-box" x="${pos.x}" y="${pos.y}" width="${boxWidth}" height="${boxHeight}" rx="9"></rect><text class="code-role" x="${pos.x + 16}" y="${pos.y + 24}">${esc(role)}</text><text class="code-emphasis" x="${pos.x + boxWidth - 16}" y="${pos.y + 24}" text-anchor="end">${primary ? "PRIMARY PATH" : "SUPPORTING"}</text>${titles.map((title, i) => `<text class="code-node-title" x="${pos.x + 16}" y="${pos.y + 47 + i * 17}">${esc(title)}</text>`).join("")}<text class="code-source-path" x="${pos.x + 16}" y="${pos.y + 82}">${esc(short(node.path || "Captured source", 78))}${node.line ? ":" + esc(node.line) + (node.end_line && node.end_line !== node.line ? "–" + esc(node.end_line) : "") : ""}</text><rect class="code-code-background" x="${pos.x + 12}" y="${pos.y + 94}" width="${boxWidth - 24}" height="${Math.max(1, code.length) * 18 + 18}" rx="5"></rect>${code.length ? code.map((row, i) => `<g class="code-line" data-source-line="${esc(row.line)}"${row.first ? ` data-code-text="${esc(row.original)}"` : ""}><text class="code-line-number" x="${pos.x + 49}" y="${pos.y + 115 + i * 18}" text-anchor="end">${row.first ? esc(row.line) : "↳"}</text><text class="code-line-text" x="${pos.x + 60}" y="${pos.y + 115 + i * 18}" xml:space="preserve">${esc(row.text)}</text></g>`).join("") : `<text class="code-line-text code-missing" x="${pos.x + 24}" y="${pos.y + 115}">Source anchor changed; review required</text>`}${node.status === "missing" ? `<text class="code-missing" x="${pos.x + 16}" y="${pos.y + 128 + codeHeight}">Source anchor changed; review required</text>` : noteLines.map((line, i) => `<text class="code-note" x="${pos.x + 16}" y="${pos.y + 128 + codeHeight + i * 13}">${esc(line)}</text>`).join("")}${child ? `<rect class="code-deeper-button" x="${pos.x + 16}" y="${pos.y + boxHeight - 30}" width="184" height="21" rx="4"></rect><text class="code-deeper-label" x="${pos.x + 25}" y="${pos.y + boxHeight - 16}">Open deeper code diagram →</text>` : `<text class="code-leaf-label" x="${pos.x + 16}" y="${pos.y + boxHeight - 16}">Captured code at this level</text>`}</${tag}>`;
      const sourceLink = source.usable ? `<a class="code-source-link" href="${routeSource(source.file, node.line || 1)}" data-code-source-map="${esc(map.id)}" data-code-source-node="${esc(node.id)}" aria-label="${esc("Open captured source " + (node.path || source.file.path) + " line " + (node.line || 1))}"><rect x="${pos.x + boxWidth - 153}" y="${pos.y + boxHeight - 30}" width="${pdf ? 82 : 137}" height="21" rx="4"></rect><text x="${pos.x + boxWidth - 143}" y="${pos.y + boxHeight - 16}">Source L${esc(node.line || 1)} ↗</text></a>` : "";
      const pdfLink = pdf ? `<a class="code-pdf-link" href="${pdf.href}" aria-label="Code block in PDF page ${pdf.page}"><rect x="${pos.x + boxWidth - 66}" y="${pos.y + boxHeight - 30}" width="50" height="21" rx="4"></rect><text x="${pos.x + boxWidth - 60}" y="${pos.y + boxHeight - 16}">PDF ${pdf.page}</text></a>` : "";
      return `<g class="code-node role-${roleClass} emphasis-${primary ? "primary" : "supporting"}${selected && String(selected.id) === String(node.id) ? " selected" : ""}" data-code-node="${esc(node.id)}">${body}${sourceLink}${pdfLink}</g>`;
    }).join("");
    return `<div class="code-chart-canvas" style="--code-min-width:${Math.min(width, 1140)}px"><svg class="code-diagram execution-diagram graph-svg" id="code-diagram" role="group" aria-label="${esc(map.title + ": actual code flowchart")}" viewBox="0 0 ${width} ${height}" data-width="${width}" data-height="${height}"><defs>${edgeKinds.map(kind => `<marker id="${marker}-${kind}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M 0 0 L 8 4 L 0 8 z" class="marker-${kind}"></path></marker>`).join("")}</defs>${edges}${nodeSvg}</svg></div><div class="code-chart-controls"><span>Click a call card to open its next diagram. Source is secondary. Long lines wrap at ↳; all captured text is shown.</span><div class="graph-buttons"><button type="button" data-graph="code-diagram" data-zoom="in" aria-label="Zoom code diagram in">+</button><button type="button" data-graph="code-diagram" data-zoom="out" aria-label="Zoom code diagram out">−</button><button type="button" data-graph="code-diagram" data-zoom="reset">Fit</button></div></div><div class="task-diagram-legend code-diagram-legend"><span><i class="code-primary-key"></i>Primary path</span><span><i class="code-support-key"></i>Supporting code / context</span><span><i class="task-key call"></i>Direct call</span><span><i class="task-key step"></i>Local step / sequence</span><span><i class="task-key return"></i>Return / resume caller</span><span><i class="task-key conditional"></i>Conditional branch</span><span><i class="task-key process"></i>Process boundary</span><span><i class="task-key event"></i>Event / dispatch</span><span><i class="task-key dependency"></i>Build / data dependency</span></div>`;
  }
  function renderCode(mapId, nodeId, explicitParent) {
    const map = codeMap(mapId);
    if (!map) return renderMissing("Code diagram");
    const parent = codeParent(map, explicitParent);
    if (parent?.kind === "flow" && parent.node) {state.selectedFlowNodes[parent.map] = parent.node; state.activeFlowMap = parent.map;}
    const nodes = map.nodes || [];
    const selected = nodes.find(node => String(node.id) === String(nodeId || state.selectedCodeNodes[map.id] || "")) || nodes.find(node => node.emphasis === "primary") || nodes[0];
    if (selected) state.selectedCodeNodes[map.id] = selected.id;
    state.navigationContext = {kind: "code", mapId: map.id, nodeId: selected?.id};
    const parentTitle = parent ? (parent.kind === "flow" ? flowMap(parent.map) : codeMap(parent.map)).title : "Execution scenarios";
    const otherParents = unique((map.parents || []).filter(validCodeParent), item => item.kind + "/" + item.map);
    main.innerHTML = `${codeBreadcrumbs(map, parent)}${pageHeading("Code diagram", map.title, "", `<a class="button" href="${codeParentLink(parent)}">↑ ${esc(short(parentTitle, 55))}</a>${printCodeLink(map)}`)}<div class="code-map-meta">${map.scope ? `<span>${esc(map.scope)}</span>` : ""}<span>Captured code · ${esc(niceDate())}</span><span>Source-curated paths; code may have changed since.</span></div>${map.summary ? `<p class="code-map-summary">${esc(map.summary)}</p>` : ""}<section class="code-chart panel">${codeDiagram(map, selected)}</section>${otherParents.length > 1 ? `<nav class="code-other-parents" aria-label="Other parent diagrams"><span>Also reached from:</span>${otherParents.map(item => `<a href="${codeParentLink(item)}">${esc((item.kind === "flow" ? flowMap(item.map) : codeMap(item.map)).title)}</a>`).join("")}</nav>` : ""}${pdfLinks("code") || pdfLinks("code-flows") ? section("Print code flowcharts", pdfLinks("code") || pdfLinks("code-flows")) : ""}`;
  }

  function renderInventory() {
    const entries = prioritizeEntries(symbols.filter(s => s.entry_reason));
    const calls = symbols.reduce((n, s) => n + (s.calls || []).length, 0);
    const classes = symbols.filter(isClass).length;
    const cards = categoryOrder.filter(cat => countCategory(cat)).map(cat => {
      const fs = files.filter(f => (f.category || "other") === cat);
      const symbolCount = fs.reduce((n, f) => n + (f.symbols || []).length, 0);
      return `<article class="card"><a class="card-title" href="#category/${cat}"><span class="card-icon" aria-hidden="true">${categories[cat].icon}</span>${esc(categories[cat].label)}</a><p>${esc(categories[cat].description)}</p><div class="card-footer"><span class="muted">${fs.length} files · ${symbolCount} symbols</span><a href="#category/${cat}" aria-label="Explore ${esc(categories[cat].label)}">Explore →</a></div></article>`;
    }).join("");
    const warnings = data.warnings || [];
    const skipped = data.skipped || [];
    const caveat = `<div class="notice"><strong>A navigation snapshot.</strong> Generated ${esc(niceDate())}. The code may have changed since. Relationships come from static analysis; uncertain call targets are labeled. Control diagrams show source structure, not a verified execution graph.${warnings.length || skipped.length ? `<details><summary>${warnings.length} analysis notes · ${skipped.length} skipped files</summary><ul class="warning-list">${warnings.map(w => `<li>${esc(w)}</li>`).join("")}${skipped.map(s => `<li><code>${esc(s.path)}</code>: ${esc(s.reason)}</li>`).join("")}</ul></details>` : ""}</div>`;
    main.innerHTML = `${crumbs([])}${pageHeading("Developer orientation", data.title || "Software foundation", "Find an entry point, follow a function’s relationships, and locate the source you need to change.")}${caveat}<div class="stats"><div class="stat"><strong>${files.length}</strong><span>Source & configuration files</span><span class="detail">BROWSE BY MODULE</span></div><div class="stat"><strong>${symbols.filter(isFunction).length}</strong><span>Functions & methods</span><span class="detail">FOLLOW CALL RELATIONSHIPS</span></div><div class="stat"><strong>${classes}</strong><span>Classes & types</span><span class="detail">EXPLORE OBJECT STRUCTURE</span></div><div class="stat"><strong>${entries.length}</strong><span>Detected entry points</span><span class="detail">START READING HERE</span></div></div>${section("Explore the foundation", `<div class="cards">${cards}</div>`)}${section("Start at an entry point", panel(symbolTable(entries.slice(0, 12), true)) + (entries.length > 12 ? `<p class="pagination-note">Showing 12 of ${entries.length} detected entry points, ordered toward program and module APIs. <a href="#symbols/entry">Browse all entry points →</a></p>` : ""), '<a href="#symbols/entry">View all entry points →</a>')}${data.guide && data.guide.length ? section("Where to make a change", guideCards()) : ""}${section("Printable chapters", pdfLinks() || empty("PDF chapters were not included in this generation."), '<a href="#pdfs">View print guidance →</a>')}<p class="small muted">${calls} call sites indexed. Snapshot fingerprint <code>${esc(short(data.fingerprint || "unavailable", 20))}</code>.</p>`;
  }

  function moduleRelationships(fs) {
    const ids = new Set(fs.map(f => String(f.id)));
    const links = new Map();
    symbols.forEach(s => {
      if (!ids.has(String(s.file.id))) return;
      (s.calls || []).forEach(call => (call.targets || []).forEach(id => {
        const target = symbolById.get(String(id));
        if (!target || target.file.id === s.file.id || !ids.has(String(target.file.id))) return;
        const key = String(s.file.id) + "|" + String(target.file.id);
        if (!links.has(key)) links.set(key, {from: String(s.file.id), to: String(target.file.id), count: 0, candidate: false});
        const edge = links.get(key); edge.count++; edge.candidate = edge.candidate || isCandidate(call);
      }));
    });
    return Array.from(links.values());
  }

  function renderCategory(cat) {
    const info = categoryInfo(cat);
    const fs = files.filter(f => (f.category || "other") === cat);
    const ss = symbols.filter(s => (s.file.category || "other") === cat);
    const entries = prioritizeEntries(ss.filter(s => s.entry_reason));
    const nodes = fs.map(f => ({id: String(f.id), label: fileName(f), subtitle: `${(f.symbols || []).length} symbols · ${f.language || "text"}`, href: routeFile(f)}));
    const edges = moduleRelationships(fs);
    main.innerHTML = `${crumbs([{label: info.label}])}${pageHeading("Module", info.label, info.description, '<a class="button" href="#home">↑ Overview</a>')}<div class="meta-row"><span><strong>${fs.length}</strong> files</span><span><strong>${ss.filter(isFunction).length}</strong> functions & methods</span><span><strong>${ss.filter(isClass).length}</strong> classes & types</span><span><strong>${entries.length}</strong> entry points</span></div>${section("Module map", renderGraph(nodes, edges, "module-" + cat, {note: "Connections aggregate indexed candidate call links between files in this module. Files without connections remain visible.", layout: "grid"}))}${section("Files in this module", `<div class="filters"><label class="sr-only" for="file-filter">Filter module files</label><input id="file-filter" placeholder="Filter by filename or path…" data-filter="files"></div><div id="filtered-files">${panel(fileTable(fs))}</div>`)}${entries.length ? section("Entry points", panel(symbolTable(entries, true))) : ""}${ss.filter(isClass).length ? section("Classes & types", panel(symbolTable(ss.filter(isClass)))) : ""}${pdfLinks(cat) ? section("Print this module", pdfLinks(cat)) : ""}`;
    attachTextFilter("file-filter", "filtered-files", fs, f => f.path, items => panel(fileTable(items)));
  }

  function ownerSymbols(s) {
    const owner = s.qualified_name || s.name;
    return symbols.filter(m => m.id !== s.id && ((m.owner === owner && (/[.:]/.test(owner) || m.file.id === s.file.id)) || (m.file.id === s.file.id && (m.owner === s.name || (m.owner && owner.endsWith("::" + m.owner))))));
  }

  function renderFile(id) {
    const f = fileById.get(id);
    if (!f) return renderMissing("File");
    const ss = symbols.filter(s => s.file.id === f.id);
    const entries = ss.filter(s => s.entry_reason);
    const classes = ss.filter(isClass);
    const freeFunctions = ss.filter(s => isFunction(s) && s.kind !== "method");
    const methods = ss.filter(s => s.kind === "method");
    const other = ss.filter(s => !isFunction(s) && !isClass(s));
    const neighborIds = new Set([String(f.id)]);
    const relationMap = new Map();
    symbols.forEach(s => (s.calls || []).forEach(call => (call.targets || []).forEach(targetId => {
      const target = symbolById.get(String(targetId));
      if (!target || target.file.id === s.file.id || (s.file.id !== f.id && target.file.id !== f.id)) return;
      neighborIds.add(String(s.file.id)); neighborIds.add(String(target.file.id));
      const key = String(s.file.id) + "|" + String(target.file.id);
      if (!relationMap.has(key)) relationMap.set(key, {from: String(s.file.id), to: String(target.file.id), count: 0, candidate: false});
      const edge = relationMap.get(key); edge.count++; edge.candidate = edge.candidate || isCandidate(call);
    })));
    const neighbors = Array.from(neighborIds).map(fileId => fileById.get(fileId)).filter(Boolean);
    const nodes = neighbors.map(file => ({id: String(file.id), label: fileName(file), subtitle: file.path, href: routeFile(file), focus: file.id === f.id, column: file.id === f.id ? "center" : Array.from(relationMap.values()).some(edge => edge.from === String(file.id) && edge.to === String(f.id)) ? "left" : "right"}));
    const edges = Array.from(relationMap.values());
    const symbolsPanel = title => section(title, panel(symbolTable(title === "Functions & callbacks" ? freeFunctions : title === "Methods" ? methods : other)));
    main.innerHTML = `${crumbs([{label: categoryFor(f).label, href: "#category/" + encode(f.category || "other")}, {label: f.path}])}${pageHeading("Source file", fileName(f), f.path, `<a class="button" href="#category/${encode(f.category || "other")}">↑ Module</a><a class="button primary" href="${routeSource(f)}">View source</a>`)}<div class="meta-row"><span><strong>${esc(f.language || "text")}</strong></span><span><strong>${esc(f.line_count || 0)}</strong> lines</span><span><strong>${ss.length}</strong> symbols</span><span><strong>${entries.length}</strong> entry points</span><span>SHA-256 <code>${esc(short(f.sha256 || "", 17))}</code></span></div>${entries.length ? section("Entry points", panel(symbolTable(entries, true))) : ""}${classes.length ? section("Classes & types", `<div class="cards">${classes.map(s => `<article class="card"><h3><a href="${routeSymbol(s)}">${esc(s.qualified_name || s.name)}</a> ${kindBadge(s)}</h3><p>${s.bases && s.bases.length ? "Bases: " + esc(s.bases.join(", ")) : "Declared at line " + esc(s.line)} · ${ownerSymbols(s).length} indexed members</p><div class="card-footer"><a href="${routeSymbol(s)}">Explore members →</a><a href="${routeSource(f, s.line)}">Source ↗</a></div></article>`).join("")}</div>`) : ""}${freeFunctions.length ? symbolsPanel("Functions & callbacks") : ""}${methods.length ? symbolsPanel("Methods") : ""}${other.length ? symbolsPanel("Other symbols") : ""}${!ss.length ? `<div class="notice">No functions or classes were indexed in this file. <a href="${routeSource(f)}">Read its source snapshot</a> to inspect configuration or declarations.</div>` : ""}${section("File relationships", renderGraph(nodes, edges, "file-" + f.id, {note: "Incoming and outgoing candidate call links across files. Unresolved calls are listed with their individual functions.", layout: "columns"}))}${edges.length ? section("All file connections", panel(`<div class="table-wrap"><table><thead><tr><th>FROM</th><th>TO</th><th>CALL SITES</th><th>RESOLUTION</th></tr></thead><tbody>${edges.map(edge => `<tr><td><a href="${routeFile(fileById.get(edge.from))}">${esc(fileById.get(edge.from).path)}</a></td><td><a href="${routeFile(fileById.get(edge.to))}">${esc(fileById.get(edge.to).path)}</a></td><td>${edge.count}</td><td>${edge.candidate ? '<span class="badge heuristic">Includes candidates</span>' : '<span class="badge">Resolved</span>'}</td></tr>`).join("")}</tbody></table></div>`)) : ""}`;
  }

  function isCandidate(call) { return /heuristic|candidate|ambiguous|approx/i.test(call.resolution || "") || (call.targets || []).length > 1; }
  function resolutionBadge(call) {
    const hasTargets = (call.targets || []).some(id => symbolById.has(String(id)));
    return !hasTargets ? '<span class="badge unresolved">Unresolved / external</span>' : isCandidate(call) ? `<span class="badge heuristic">${(call.targets || []).length > 1 ? "Candidate targets" : "Heuristic target"}</span>` : '<span class="badge">Resolved target</span>';
  }

  function callGraph(s) {
    const nodes = new Map([[String(s.id), {id: String(s.id), label: s.name, subtitle: s.file.path + ":" + s.line, href: routeSymbol(s), focus: true, column: "center"}]]);
    const edges = [];
    const put = (symbol, column) => {
      const id = String(symbol.id);
      if (!nodes.has(id)) nodes.set(id, {id, label: symbol.name, subtitle: symbol.file.path + ":" + symbol.line, href: routeSymbol(symbol), column});
    };
    (incoming.get(String(s.id)) || []).forEach(({symbol, call}) => {
      put(symbol, "left"); edges.push({from: String(symbol.id), to: String(s.id), candidate: isCandidate(call), label: "L" + call.line});
    });
    (s.calls || []).forEach((call, i) => {
      const targets = (call.targets || []).map(id => symbolById.get(String(id))).filter(Boolean);
      if (targets.length) targets.forEach(target => {put(target, "right"); edges.push({from: String(s.id), to: String(target.id), candidate: isCandidate(call), label: "L" + call.line});});
      else {
        const id = "external-" + i;
        nodes.set(id, {id, label: call.name, subtitle: "unresolved / external · line " + call.line, href: routeSource(s.file, call.line), external: true, column: "right"});
        edges.push({from: String(s.id), to: id, candidate: true, label: "L" + call.line});
      }
    });
    return {nodes: Array.from(nodes.values()), edges};
  }

  function outgoingList(s) {
    const calls = s.calls || [];
    return calls.length ? `<div class="panel-pad">${calls.map(call => {
      const targets = (call.targets || []).map(id => symbolById.get(String(id))).filter(Boolean);
      return `<div class="relation"><div><div class="relation-name">${esc(call.name)}</div><small><a href="${routeSource(s.file, call.line)}">Call site · line ${esc(call.line)}</a></small>${targets.length ? `<p>${targets.map(target => `<a href="${routeSymbol(target)}">${esc(target.qualified_name || target.name)}</a> <span class="muted">(${esc(target.file.path)})</span>`).join("<br>")}</p>` : '<p>No target in the indexed snapshot; this may be an external, dynamic, macro, or unresolved call.</p>'}${call.resolution ? `<p>Analysis: ${esc(call.resolution)}</p>` : ""}</div>${resolutionBadge(call)}</div>`;
    }).join("")}</div>` : empty("No call sites were detected in this symbol.");
  }

  function incomingList(s) {
    const sites = incoming.get(String(s.id)) || [];
    const grouped = new Map();
    sites.forEach(site => {const id = String(site.symbol.id); if (!grouped.has(id)) grouped.set(id, {symbol: site.symbol, calls: []}); grouped.get(id).calls.push(site.call);});
    return sites.length ? `<div class="panel-pad">${Array.from(grouped.values()).map(item => `<div class="relation"><div><a class="relation-name" href="${routeSymbol(item.symbol)}">${esc(item.symbol.qualified_name || item.symbol.name)}</a><small>${esc(item.symbol.file.path)}</small><div class="call-site-list">Call sites: ${item.calls.map(call => `<a href="${routeSource(item.symbol.file, call.line)}">line ${esc(call.line)}</a>`).join("")}</div></div>${item.calls.some(isCandidate) ? '<span class="badge heuristic">Includes candidates</span>' : '<span class="badge">Resolved</span>'}</div>`).join("")}</div>` : empty("No indexed incoming call sites. Entry points and callbacks may be invoked indirectly.");
  }

  function flowTree(nodes, file) {
    return `<ol class="flow-tree">${(nodes || []).map(node => `<li class="flow-node"><div class="flow-box"><span class="flow-kind">${esc(node.kind || "statement")}</span><span class="flow-label">${esc(node.label || node.kind || "statement")}</span>${node.line ? `<a class="flow-line" href="${routeSource(file, node.line)}">L${esc(node.line)}</a>` : ""}</div>${node.children && node.children.length ? flowTree(node.children, file) : ""}</li>`).join("")}</ol>`;
  }

  function renderSymbol(id) {
    const s = symbolById.get(id);
    if (!s) return renderMissing("Symbol");
    const classView = isClass(s);
    const members = classView ? ownerSymbols(s) : [];
    const owner = s.owner ? symbols.find(candidate => isClass(candidate) && ((candidate.qualified_name === s.owner && (/[.:]/.test(s.owner) || candidate.file.id === s.file.id)) || (candidate.file.id === s.file.id && candidate.name === s.owner))) : null;
    const graph = callGraph(s);
    const bases = s.bases || [];
    main.innerHTML = `${crumbs([{label: categoryFor(s.file).label, href: "#category/" + encode(s.file.category || "other")}, {label: s.file.path, href: routeFile(s.file)}, {label: s.qualified_name || s.name}])}${pageHeading(s.kind || "Symbol", s.qualified_name || s.name, "", `<a class="button" href="${owner ? routeSymbol(owner) : routeFile(s.file)}">↑ ${owner ? "Owning type" : "Source file"}</a><a class="button primary" href="${routeSource(s.file, s.line)}">View source · L${esc(s.line)}</a>${printLink(s.id, s.file.id, s.line, "button")}`)}<div class="meta-row"><span>${kindBadge(s)}</span><span><a href="${routeFile(s.file)}">${esc(s.file.path)}</a></span><span>Lines <strong>${esc(s.line)}–${esc(s.end_line || s.line)}</strong></span>${s.owner ? `<span>Owner <strong>${owner ? `<a href="${routeSymbol(owner)}">${esc(s.owner)}</a>` : esc(s.owner)}</strong></span>` : ""}</div>${s.entry_reason ? `<div class="notice"><span class="badge entry">Entry point</span> ${esc(s.entry_reason)}</div>` : ""}${s.signature ? `<pre class="signature">${esc(s.signature)}</pre>` : ""}${bases.length ? `<div class="owner-panel"><strong>Inheritance / bases</strong>${bases.map(base => {
      const found = symbols.filter(c => isClass(c) && (c.name === base || c.qualified_name === base));
      return found.length === 1 ? `<a href="${routeSymbol(found[0])}">${esc(base)}</a>` : `<span>${esc(base)}${found.length > 1 ? " (ambiguous)" : " (not resolved)"}</span>`;
    }).join("")}</div>` : ""}${classView ? section("Members", panel(symbolTable(members))) : ""}${section("Call neighborhood", renderGraph(graph.nodes, graph.edges, "symbol-" + s.id, {note: "Callers on the left, this symbol in the center, callees on the right. Each detected call site appears in the complete lists below.", layout: "columns"}))}${section("All call relationships", `<div class="two-columns">${panel(incomingList(s), "Called by", `${(incoming.get(String(s.id)) || []).length} indexed incoming call sites`)}${panel(outgoingList(s), "Calls from this symbol", `${(s.calls || []).length} detected call sites`)}</div>`)}${section("Control structure", panel(`<div class="flow"><p class="flow-intro">Read top to bottom. Indentation follows lexical nesting in the source; branches, loops, and exits are structural landmarks. This is not an exact execution control-flow graph.</p>${s.flow && s.flow.length ? flowTree(s.flow, s.file) : `<div class="empty">No control structures were indexed here. <a href="${routeSource(s.file, s.line)}">Inspect the source</a> for the complete body.</div>`}</div>`))}`;
  }

  function renderSource(id, requestedLine) {
    const f = fileById.get(id);
    if (!f) return renderMissing("Source file");
    const lines = String(f.text || "").replace(/\r\n/g, "\n").split("\n");
    if (lines[lines.length - 1] === "" && lines.length > 1) lines.pop();
    const line = Math.max(1, Math.min(lines.length, Number(requestedLine) || 1));
    const nearby = symbols.filter(s => s.file.id === f.id && s.line <= line && (s.end_line || s.line) >= line).sort((a, b) => b.line - a.line)[0];
    main.innerHTML = `${crumbs([{label: categoryFor(f).label, href: "#category/" + encode(f.category || "other")}, {label: f.path, href: routeFile(f)}, {label: "Source · line " + line}])}${pageHeading("Source snapshot", fileName(f), f.path, `<a class="button" href="${nearby ? routeSymbol(nearby) : routeFile(f)}">↑ ${nearby ? esc(short(nearby.name, 24)) : "File overview"}</a>${printLink(nearby?.id, f.id, line, "button")}`)}<div class="meta-row"><span>Line <strong>${line}</strong> of ${lines.length}</span><span><strong>${esc(f.language || "text")}</strong></span>${nearby ? `<span>Inside <a href="${routeSymbol(nearby)}">${esc(nearby.qualified_name || nearby.name)}</a></span>` : ""}<span class="muted">Captured ${esc(niceDate())}</span></div><div class="filters"><form class="jump-form" id="source-jump"><label for="line-input" class="small">Go to line</label><input id="line-input" type="number" min="1" max="${lines.length}" value="${line}"><button class="button" type="submit">Go</button></form><span class="small muted">Line numbers are shareable links within this atlas.</span></div><div class="source-panel" id="source-panel"><div class="source-note"><span>${esc(f.path)}</span><span>Snapshot · SHA-256 ${esc(short(f.sha256 || "", 16))}</span></div><div class="source-lines">${lines.map((text, i) => `<div class="source-line${i + 1 === line ? " selected" : ""}" id="L${i + 1}"><a href="${routeSource(f, i + 1)}" aria-label="Line ${i + 1}">${i + 1}</a><code>${esc(text) || " "}</code></div>`).join("")}</div></div>`;
    document.getElementById("source-jump").addEventListener("submit", event => { event.preventDefault(); location.hash = routeSource(f, document.getElementById("line-input").value); });
    requestAnimationFrame(() => {
      const container = document.getElementById("source-panel");
      const target = document.getElementById("L" + line);
      if (container && target) container.scrollTop = Math.max(0, target.offsetTop - container.offsetTop - 90);
    });
  }

  function buildGraph() {
    const build = data.build || {};
    const nodes = [{id: "configuration", label: "Build declarations", subtitle: `${(build.options || []).length} options · ${(build.commands || []).length} commands`, href: "#build", focus: true, column: "left"}];
    const edges = [];
    (build.targets || []).forEach((target, i) => {
      const id = "target-" + i;
      nodes.push({id, label: target.name, subtitle: (target.context && target.context.length ? "Context-dependent · " : "") + (target.kind || "target"), href: "#build/target/" + i, column: "center"});
      edges.push({from: "configuration", to: id});
      const sources = target.sources || [];
      if (sources.length) {
        const sourceId = "source-group-" + i;
        nodes.push({id: sourceId, label: sources.length + " source entries", subtitle: "Expand target to inspect source list", href: "#build/target/" + i, column: "right"});
        edges.push({from: id, to: sourceId});
      }
      (target.links || []).forEach(name => {
        const other = (build.targets || []).findIndex(t => t.name === name);
        if (other >= 0) edges.push({from: id, to: "target-" + other, candidate: true});
      });
    });
    return {nodes, edges};
  }

  function declarationTable(statements, title) {
    return statements && statements.length ? `<details class="target-card"><summary>${esc(title)}<small>${statements.length} declarations</small></summary><div class="target-details table-wrap"><table><thead><tr><th>COMMAND</th><th>ARGUMENTS & CONTEXT</th><th>LOCATION</th></tr></thead><tbody>${statements.map(statement => `<tr><td class="mono">${esc(statement.command || "")}</td><td><code>${esc((statement.args || []).join(" "))}</code>${contexts(statement.context)}</td><td>${fileLink(statement.path, statement.line)}</td></tr>`).join("")}</tbody></table></div></details>` : "";
  }

  function renderBuild(targetIndex) {
    const build = data.build || {};
    const commands = build.commands || [];
    const targets = build.targets || [];
    const options = build.options || [];
    const graph = buildGraph();
    const configurationGuides = (data.guide || []).filter(g => /build|compil|source file|target|configuration/i.test(g.title + " " + g.body));
    const targetCards = targets.map((target, i) => `<details class="target-card" id="target-${i}"${String(i) === String(targetIndex) ? " open" : ""}><summary><span class="badge">${esc(target.kind || "target")}</span><span>${esc(target.name)}</span>${target.context && target.context.length ? '<span class="badge unresolved">Context-dependent</span>' : ""}${target.symbolic ? '<span class="badge heuristic">Symbolic name</span>' : ""}<small>${(target.sources || []).length} source entries · ${esc(target.path || "")}:${esc(target.line || "")}</small></summary><div class="target-details"><div class="small">Declared in ${fileLink(target.path, target.line)}</div>${printTargetLink(i)}${contexts(target.context)}<h3 class="small" style="margin-top:14px">Source entries</h3><div class="file-pills">${(target.sources || []).map(path => `<span class="file-pill">${fileLink(path, null, null, target.path)}</span>`).join("") || '<span class="muted small">No source entries were extracted for this target.</span>'}</div><p class="small muted">Literal paths resolve relative to the declaring file. Variables and generated entries are shown as written.</p><h3 class="small" style="margin-top:14px">Linked dependencies</h3><div class="file-pills">${(target.links || []).map(link => `<span class="file-pill">${esc(link)}</span>`).join("") || '<span class="muted small">No link entries were extracted.</span>'}</div>${declarationTable(target.source_statements, "Source-list declarations")}${declarationTable(target.link_statements, "Link declarations")}</div></details>`).join("");
    const toolchain = build.toolchain || [];
    const cargo = build.cargo || {};
    const toolchainSection = toolchain.length ? section("Compiler & toolchain settings", panel(`<div class="table-wrap"><table><thead><tr><th>SETTING</th><th>VALUES & CONTEXT</th><th>LOCATION</th></tr></thead><tbody>${toolchain.map(setting => `<tr><td class="name mono">${esc(setting.name)}</td><td><code>${esc((setting.values || []).join(" "))}</code>${contexts(setting.context)}</td><td>${fileLink(setting.path, setting.line)}</td></tr>`).join("")}</tbody></table></div>`)) : "";
    const cargoSection = Object.keys(cargo).length ? section("Rust / Cargo manifests", Object.entries(cargo).map(([path, manifest]) => `<details class="target-card"><summary><span class="badge">Cargo</span>${esc(path)}</summary><div class="target-details"><p class="small">${fileLink(path, 1, "View source manifest →")}</p><pre class="code-block">${esc(JSON.stringify(manifest, null, 2))}</pre></div></details>`).join("")) : "";
    main.innerHTML = `${crumbs([{label: "Compiler & toolchain"}])}${pageHeading("Build architecture", "Compiler & toolchain", "Read the detected configuration, locate target source lists, and follow the files that define how the project is compiled.", '<a class="button" href="#home">↑ Overview</a>')}<div class="notice">This is an inventory of source declarations, including conditional and template targets. Lexical context is shown without evaluating CMake. Variables, generated sources, and platform choices may require following the linked configuration. The atlas does not execute the application build.</div>${section("Target declaration map", renderGraph(graph.nodes, graph.edges, "build", {note: "Nodes represent declarations, not an active configured build. Source entries are grouped by target. Dashed target links are textual dependency matches. Full target lists and their lexical contexts appear below.", layout: "columns"}))}${configurationGuides.length ? section("Adding or locating code", configurationGuides.map(g => `<article class="guide-card"><h3>${esc(g.title)}</h3><p>${esc(g.body)}</p><div class="guide-links">${(g.links || []).map(link => fileLink(link.path, link.line, link.label)).join("")}</div></article>`).join("")) : ""}${toolchainSection}${section("Targets & source lists", targetCards || empty("No build targets were extracted from this snapshot."))}${options.length ? section("Configuration options", panel(`<div class="table-wrap"><table><thead><tr><th>OPTION</th><th>DEFAULT</th><th>DESCRIPTION & CONTEXT</th><th>LOCATION</th></tr></thead><tbody>${options.map(option => `<tr><td class="name mono">${esc(option.name)}</td><td><span class="badge">${esc(option.default)}</span></td><td>${esc(option.description)}${contexts(option.context)}</td><td>${fileLink(option.path, option.line)}</td></tr>`).join("")}</tbody></table></div>`)) : ""}${cargoSection}${build.presets && Object.keys(build.presets).length ? section("Configuration presets", `<details class="target-card"><summary>Preset data<small>Source-derived configuration</small></summary><div class="target-details"><pre class="code-block">${esc(JSON.stringify(build.presets, null, 2))}</pre></div></details>`) : ""}${commands.length ? section("Configuration command inventory", declarationTable(commands, "All detected configuration commands")) : ""}${section("Build configuration files", panel(fileTable(files.filter(f => f.category === "build"))))}${pdfLinks("build") ? section("Print the toolchain", pdfLinks("build")) : ""}`;
    if (targetIndex != null) requestAnimationFrame(() => { const target = document.getElementById("target-" + targetIndex); if (target) target.scrollIntoView({block: "center"}); });
  }

  function renderSymbols(filter, module) {
    state.symbolFilter = filter || "all";
    main.innerHTML = `${crumbs([{label: "Functions & classes"}])}${pageHeading("Symbol directory", "Functions & classes", "Find a likely place for your change. Search names and paths, then inspect callers, callees, control structure, and the captured source.", '<a class="button" href="#home">↑ Overview</a>')}<div class="filters"><label class="sr-only" for="symbol-search">Filter symbols</label><input id="symbol-search" placeholder="Filter symbol names, signatures, and file paths…"><label class="sr-only" for="symbol-category">Filter module</label><select id="symbol-category"><option value="all">All modules</option>${categoryOrder.filter(cat => countCategory(cat)).map(cat => `<option value="${cat}">${esc(categories[cat].label)}</option>`).join("")}</select></div><div class="filters" id="symbol-kind">${[["all", "All symbols"], ["entry", "Entry points"], ["function", "Functions & methods"], ["class", "Classes & types"]].map(([key, label]) => `<button class="filter-chip${state.symbolFilter === key ? " active" : ""}" data-kind="${key}" type="button">${label}</button>`).join("")}</div><div class="pagination-note" id="symbol-count"></div><div id="symbol-results"></div>`;
    let page = 0;
    const pageSize = 100;
    if (module && [...document.getElementById("symbol-category").options].some(option => option.value === module)) document.getElementById("symbol-category").value = module;
    const refresh = (resetPage = true) => {
      if (resetPage) page = 0;
      const query = document.getElementById("symbol-search").value.toLowerCase().trim();
      const cat = document.getElementById("symbol-category").value;
      let result = symbols.filter(s => (!query || `${s.qualified_name || s.name} ${s.signature || ""} ${s.file.path} ${s.entry_reason || ""}`.toLowerCase().includes(query)) && (cat === "all" || (s.file.category || "other") === cat) && (state.symbolFilter === "all" || (state.symbolFilter === "entry" && s.entry_reason) || (state.symbolFilter === "function" && isFunction(s)) || (state.symbolFilter === "class" && isClass(s))));
      if (state.symbolFilter === "entry") result = prioritizeEntries(result);
      const pages = Math.max(1, Math.ceil(result.length / pageSize));
      page = Math.min(page, pages - 1);
      const from = page * pageSize;
      document.getElementById("symbol-count").textContent = result.length ? `${from + 1}–${Math.min(from + pageSize, result.length)} of ${result.length} matching symbols · ${symbols.length} total indexed` : `0 matching symbols · ${symbols.length} total indexed`;
      document.getElementById("symbol-results").innerHTML = panel(symbolTable(result.slice(from, from + pageSize), state.symbolFilter === "entry")) + (pages > 1 ? `<div class="filters"><button class="button" type="button" id="symbols-prev" ${page === 0 ? "disabled" : ""}>← Previous</button><span class="small muted">Page ${page + 1} of ${pages}</span><button class="button" type="button" id="symbols-next" ${page === pages - 1 ? "disabled" : ""}>Next →</button><span class="small muted">Filters search the full symbol directory.</span></div>` : "");
      document.getElementById("symbols-prev")?.addEventListener("click", () => {page--; refresh(false);});
      document.getElementById("symbols-next")?.addEventListener("click", () => {page++; refresh(false);});
    };
    document.getElementById("symbol-search").addEventListener("input", () => refresh());
    document.getElementById("symbol-category").addEventListener("change", () => refresh());
    document.getElementById("symbol-kind").addEventListener("click", event => { const button = event.target.closest("[data-kind]"); if (button) { state.symbolFilter = button.dataset.kind; document.querySelectorAll("[data-kind]").forEach(item => item.classList.toggle("active", item === button)); refresh(); } });
    refresh();
  }

  function searchItems(query) {
    const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    if (!terms.length) return [];
    const matches = [];
    const score = (name, full) => terms.every(term => full.includes(term)) ? terms.reduce((n, term) => n + (name === term ? 30 : name.startsWith(term) ? 15 : name.includes(term) ? 8 : 1), 0) : 0;
    symbols.forEach(s => { const name = (s.qualified_name || s.name).toLowerCase(); const rank = score(name, `${name} ${s.file.path} ${s.signature || ""} ${s.entry_reason || ""} ${s.kind || ""}`.toLowerCase()); if (rank) matches.push({type: "symbol", symbol: s, rank, name: s.qualified_name || s.name, path: s.file.path + ":" + s.line, href: routeSymbol(s)}); });
    files.forEach(f => { const rank = score(fileName(f).toLowerCase(), `${f.path} ${f.language || ""}`.toLowerCase()); if (rank) matches.push({type: "file", file: f, rank, name: fileName(f), path: f.path, href: routeFile(f)}); });
    return matches.sort((a, b) => b.rank - a.rank || a.name.localeCompare(b.name));
  }

  function renderSearch(query) {
    const results = searchItems(query);
    search.value = query;
    main.innerHTML = `${crumbs([{label: "Search"}])}${pageHeading("Search the atlas", query ? `Results for “${query}”` : "Search files & symbols", `${results.length} matching results across the captured source.`, '<a class="button" href="#home">↑ Overview</a>')}<div class="filters"><button class="filter-chip active" data-search-type="all" type="button">All results</button><button class="filter-chip" data-search-type="symbol" type="button">Symbols</button><button class="filter-chip" data-search-type="file" type="button">Files</button></div><div id="search-results"></div>`;
    const refresh = type => document.getElementById("search-results").innerHTML = panel(results.filter(result => type === "all" || result.type === type).map(result => `<a class="search-result" href="${result.href}"><span>${result.type === "symbol" ? kindBadge(result.symbol) : '<span class="badge">file</span>'}</span><span><strong>${esc(result.name)}</strong><small>${esc(result.path)}</small>${result.symbol && result.symbol.entry_reason ? `<small><span class="badge entry">Entry point</span> ${esc(result.symbol.entry_reason)}</small>` : ""}</span></a>`).join("") || empty("No matches. Try a shorter function name, a class, or part of a file path."));
    document.querySelectorAll("[data-search-type]").forEach(button => button.addEventListener("click", () => { document.querySelectorAll("[data-search-type]").forEach(item => item.classList.toggle("active", item === button)); refresh(button.dataset.searchType); }));
    refresh("all");
  }

  function renderPdfs() {
    main.innerHTML = `${crumbs([{label: "Printable chapters"}])}${pageHeading("Read away from the screen", "Printable chapters", "The PDF collection follows the same hierarchy as the explorer. Keep the PDF files together so relative chapter links continue to work.", '<a class="button" href="#home">↑ Overview</a>')}<div class="notice">Each browser view also has a print layout. Use “Print this view” for the current file, symbol, source snapshot, or configuration page. In PDF viewers, relative file links depend on the viewer’s local-file support.</div>${section("Chapter collection", pdfLinks() || empty("PDF chapters were not included in this generation."))}${section("Choose a reading path", `<div class="cards"><article class="card"><h3>1 · Orient</h3><p>Start with the overview to find major modules, entry points, and the guide to adding code.</p><a href="#home">Open overview →</a></article><article class="card"><h3>2 · Follow the build</h3><p>Find target declarations, source lists, compiler configuration, and feature options.</p><a href="#build">Open toolchain →</a></article><article class="card"><h3>3 · Inspect behavior</h3><p>Choose a function or type, follow its calls, and inspect the nested control structures.</p><a href="#symbols">Open symbol directory →</a></article></div>`)}`;
  }

  function renderMissing(kind) {
    main.innerHTML = `${crumbs([{label: "Not found"}])}${pageHeading("Navigation", kind + " not found", "This link does not match the current snapshot. Use the search field or return to the overview.", '<a class="button primary" href="#home">Open overview</a>')}`;
  }

  function attachTextFilter(inputId, outputId, items, haystack, render) {
    document.getElementById(inputId).addEventListener("input", event => {
      const value = event.target.value.trim().toLowerCase();
      document.getElementById(outputId).innerHTML = render(items.filter(item => haystack(item).toLowerCase().includes(value)));
    });
  }

  function renderGraph(allNodes, allEdges, key, options = {}) {
    const expanded = state.graphLimits[key] === "all";
    const limit = expanded ? Math.max(allNodes.length, 1) : 24;
    const focusNodes = allNodes.filter(n => n.focus);
    const ordered = [...focusNodes, ...allNodes.filter(n => !n.focus)];
    const nodes = ordered.slice(0, limit);
    const shownIds = new Set(nodes.map(n => n.id));
    const eligibleEdges = allEdges.filter(edge => shownIds.has(edge.from) && shownIds.has(edge.to));
    const edgeLimit = expanded ? allEdges.length : limit * 4;
    const edges = eligibleEdges.slice(0, edgeLimit);
    const omittedNodes = allNodes.length - nodes.length;
    const omittedEdges = allEdges.length - edges.length;
    const positions = new Map();
    let width = 950;
    let height = 340;
    const boxWidth = 218;
    const boxHeight = 54;
    if (options.layout === "columns") {
      const columns = ["left", "center", "right"];
      const counts = columns.map(col => nodes.filter(n => (n.column || "center") === col).length);
      height = Math.max(340, Math.max(...counts, 1) * 78 + 60);
      columns.forEach((col, colIndex) => {
        const group = nodes.filter(n => (n.column || "center") === col);
        group.forEach((node, i) => positions.set(node.id, {x: 36 + colIndex * 328, y: 30 + (height - 60 - group.length * 78) / 2 + i * 78}));
      });
    } else {
      const columns = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(nodes.length || 1))));
      const rows = Math.ceil(nodes.length / columns);
      width = Math.max(640, columns * (boxWidth + 62) + 42);
      height = Math.max(330, rows * 104 + 50);
      nodes.forEach((node, i) => positions.set(node.id, {x: 30 + (i % columns) * (boxWidth + 62), y: 35 + Math.floor(i / columns) * 104}));
    }
    const svgId = "graph-" + (++graphSequence);
    const markerId = svgId + "-arrow";
    const edgeSvg = edges.map(edge => {
      const from = positions.get(edge.from), to = positions.get(edge.to);
      if (!from || !to) return "";
      const fromRight = to.x >= from.x;
      const sx = from.x + (fromRight ? boxWidth : 0), sy = from.y + boxHeight / 2;
      const ex = to.x + (fromRight ? 0 : boxWidth), ey = to.y + boxHeight / 2;
      let path;
      if (edge.from === edge.to) path = `M ${sx} ${sy} C ${sx + 55} ${sy - 80}, ${sx - 70} ${sy - 80}, ${sx - 35} ${from.y}`;
      else if (Math.abs(to.x - from.x) < 20) path = `M ${from.x + boxWidth} ${sy} C ${from.x + boxWidth + 45} ${sy}, ${to.x + boxWidth + 45} ${ey}, ${to.x + boxWidth} ${ey}`;
      else { const delta = Math.max(40, Math.abs(ex - sx) * .5); path = `M ${sx} ${sy} C ${sx + (fromRight ? delta : -delta)} ${sy}, ${ex - (fromRight ? delta : -delta)} ${ey}, ${ex} ${ey}`; }
      return `<path class="edge${edge.candidate ? " candidate-edge" : ""}" d="${path}" marker-end="url(#${markerId})"><title>${esc(edge.label || "")}${edge.count ? " · " + edge.count + " call sites" : ""}${edge.candidate ? " · heuristic/candidate relation" : ""}</title></path>`;
    }).join("");
    const nodeSvg = nodes.map(node => {
      const pos = positions.get(node.id);
      return `<a href="${esc(node.href || "#home")}" class="${node.focus ? "focus " : ""}${node.external ? "external" : ""}" aria-label="${esc(node.label)}"><title>${esc(node.label)}${node.subtitle ? " · " + esc(node.subtitle) : ""}</title><rect x="${pos.x}" y="${pos.y}" width="${boxWidth}" height="${boxHeight}" rx="7"></rect><text x="${pos.x + 13}" y="${pos.y + 22}">${esc(short(node.label, 29))}</text><text class="subtext" x="${pos.x + 13}" y="${pos.y + 40}">${esc(short(node.subtitle || "", 41))}</text></a>`;
    }).join("");
    return `<div class="panel"><div class="graph-wrap">${!nodes.length ? empty("No graph nodes were detected.") : `<svg class="graph-svg" id="${svgId}" role="group" aria-label="Clickable relationship graph" viewBox="0 0 ${width} ${height}" data-width="${width}" data-height="${height}"><defs><marker id="${markerId}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M 0 0 L 8 4 L 0 8 z" fill="#9aafbf"></path></marker></defs><g>${edgeSvg}${nodeSvg}</g></svg>`}</div><div class="graph-toolbar"><span>${nodes.length} of ${allNodes.length} nodes · ${edges.length} of ${allEdges.length} relationships · click a node to explore</span><div class="graph-buttons"><button data-graph="${svgId}" data-zoom="in" aria-label="Zoom in" type="button">+</button><button data-graph="${svgId}" data-zoom="out" aria-label="Zoom out" type="button">−</button><button data-graph="${svgId}" data-zoom="reset" type="button">Fit</button></div></div><div class="graph-key"><span><span class="key-line"></span>Indexed relation</span><span><span class="key-line dashed"></span>Candidate / unresolved relation</span></div>${omittedNodes || omittedEdges ? `<div class="graph-limits">${omittedNodes} nodes and ${omittedEdges} relationships are outside this graph’s current display. <button type="button" data-expand-graph="${esc(key)}" data-total="${allNodes.length}">Show the complete graph</button>. Complete ${options.layout === "columns" ? "relationship/source" : "file"} lists remain below.</div>` : ""}${options.note ? `<div class="panel-pad small muted">${esc(options.note)}</div>` : ""}</div>`;
  }

  function attachGraphs() {
    document.querySelectorAll(".graph-svg").forEach(svg => {
      const base = {x: 0, y: 0, width: Number(svg.dataset.width), height: Number(svg.dataset.height)};
      let view = {...base};
      const update = () => svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.width} ${view.height}`);
      svg._zoom = action => {
        if (action === "reset") view = {...base};
        else { const factor = action === "in" ? .8 : 1.25; const width = Math.min(base.width * 4, Math.max(base.width * .15, view.width * factor)); const height = width * base.height / base.width; view = {x: view.x + (view.width - width) / 2, y: view.y + (view.height - height) / 2, width, height}; }
        update();
      };
      let drag = null;
      svg.addEventListener("pointerdown", event => {
        if (event.target.closest("a") || event.button !== 0) return;
        drag = {x: event.clientX, y: event.clientY, vx: view.x, vy: view.y};
        svg.setPointerCapture(event.pointerId); svg.classList.add("dragging");
      });
      svg.addEventListener("pointermove", event => {
        if (!drag) return;
        const rect = svg.getBoundingClientRect();
        const scale = Math.max(view.width / rect.width, view.height / rect.height);
        view.x = drag.vx - (event.clientX - drag.x) * scale; view.y = drag.vy - (event.clientY - drag.y) * scale; update();
      });
      const endDrag = () => {drag = null; svg.classList.remove("dragging");};
      svg.addEventListener("pointerup", endDrag); svg.addEventListener("pointercancel", endDrag);
    });
    document.querySelectorAll("[data-zoom]").forEach(button => button.addEventListener("click", () => {const svg = document.getElementById(button.dataset.graph); if (svg && svg._zoom) svg._zoom(button.dataset.zoom);}));
    document.querySelectorAll("[data-code-parent-kind]").forEach(link => link.addEventListener("click", () => {
      const parent = {kind: link.dataset.codeParentKind, map: link.dataset.codeParentMap, node: link.dataset.codeParentNode};
      if (validCodeParent(parent) && codeMap(link.dataset.codeChild)) state.codeOrigins[link.dataset.codeChild] = parent;
    }));
    document.querySelectorAll("[data-code-source-map]").forEach(link => link.addEventListener("click", () => {
      const map = codeMap(link.dataset.codeSourceMap);
      const node = (map?.nodes || []).find(item => String(item.id) === String(link.dataset.codeSourceNode));
      if (node) {state.selectedCodeNodes[map.id] = node.id; state.navigationContext = {kind: "code", mapId: map.id, nodeId: node.id};}
    }));
    document.querySelectorAll("[data-expand-graph]").forEach(button => button.addEventListener("click", () => {
      const key = button.dataset.expandGraph; state.graphLimits[key] = "all"; renderRoute(false);
    }));
  }

  function renderRoute(scroll = true) {
    preview.hidden = true;
    graphSequence = 0;
    const raw = location.hash.replace(/^#/, "") || "home";
    let parts;
    try { parts = raw.split("/").map(decodeURIComponent); } catch (_) {parts = ["home"];}
    currentRoute = raw;
    switch (parts[0]) {
      case "home": renderHome(parts[1]); break;
      case "change": renderChange(parts[1], parts[2]); break;
      case "flows": renderFlow(null, null, true); break;
      case "flow": renderFlow(parts[1], parts[2]); break;
      case "code": renderCode(parts[1], parts[2]); break;
      case "inventory": renderInventory(); break;
      case "parameters": renderParameters(parts[1], parts[2], parts[3]); break;
      case "category": renderCategory(parts[1] || "core"); break;
      case "file": renderFile(parts[1]); break;
      case "symbol": renderSymbol(parts[1]); break;
      case "source": renderSource(parts[1], parts[2]); break;
      case "build": renderBuild(parts[1] === "target" ? parts[2] : null); break;
      case "symbols": renderSymbols(parts[1], parts[2]); break;
      case "search": renderSearch(parts.slice(1).join("/")); break;
      case "pdfs": renderPdfs(); break;
      default: renderMissing("Page");
    }
    document.title = `${main.querySelector("h1")?.textContent || "Overview"} · ${data.title || "Code atlas"}`;
    let active = parts[0] === "category" ? "category/" + parts[1] : parts[0] === "change" ? "home" : parts[0] === "flow" || parts[0] === "code" ? "flows" : parts[0];
    const file = parts[0] === "file" || parts[0] === "source" ? fileById.get(parts[1]) : parts[0] === "symbol" ? symbolById.get(parts[1])?.file : null;
    if (file) active = "category/" + (file.category || "other");
    if (file?.origin === "supplier-reference") {
      const provenance = file.provenance || {};
      main.insertAdjacentHTML("afterbegin", `<div class="notice supplier-notice"><strong>Read-only supplier reference</strong><p>Pinned upstream source captured from the retained archive. Use this reference to understand the supplier contract; follow the task map for application edit locations.</p><div class="supplier-provenance"><span>Archive: <code>${esc(provenance.archive || "retained supplier archive")}</code></span><span>Member: <code>${esc(provenance.member || file.path)}</code></span>${provenance.revision ? `<span>Pinned revision: <code>${esc(short(provenance.revision, 16))}</code></span>` : ""}${provenance.patches_applied === false ? '<span>No patches applied to this captured member.</span>' : ""}</div></div>`);
    }
    if (file && state.navigationContext?.kind === "code" && codeMap(state.navigationContext.mapId)) {
      const map = codeMap(state.navigationContext.mapId);
      const node = (map.nodes || []).find(item => String(item.id) === String(state.navigationContext.nodeId));
      main.insertAdjacentHTML("afterbegin", `<div class="return-to-change return-to-code"><a href="${codeRoute(map, node)}">↑ Back to code diagram: ${esc(map.title)}</a><span>${node ? esc(node.title) : "Captured code"}</span></div>`);
    } else if (file && state.navigationContext?.kind === "execution" && flowMap(state.navigationContext.mapId)) {
      const map = flowMap(state.navigationContext.mapId);
      const node = (map.nodes || []).find(item => item.id === state.navigationContext.nodeId);
      main.insertAdjacentHTML("afterbegin", `<div class="return-to-change return-to-flow"><a href="${flowRoute(map, node)}">↑ Back to ${esc(node ? node.title : map.title)}</a><span>Execution scenario · ${esc(map.title)}</span></div>`);
    } else if (file && state.lastChangeMap && changeMap(state.lastChangeMap)) {
      const map = changeMap(state.lastChangeMap);
      const node = (map.nodes || []).find(item => item.id === state.selectedChangeNodes[map.id]);
      main.insertAdjacentHTML("afterbegin", `<div class="return-to-change"><a href="${changeRoute(map, node)}">↑ Back to ${esc(node ? node.title : map.title)}</a><span>in ${esc(map.title)}</span></div>`);
    }
    document.querySelectorAll("[data-nav]").forEach(item => { const selected = item.dataset.nav === active; item.classList.toggle("active", selected); if (selected) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current"); });
    document.querySelector(".sidebar").classList.remove("open");
    document.getElementById("menu-button").setAttribute("aria-expanded", "false");
    attachGraphs();
    if ((parts[0] === "change" || parts[0] === "flow") && parts[2] && window.innerWidth < 1600) requestAnimationFrame(() => document.getElementById("change-detail")?.scrollIntoView({block: "start"}));
    if (scroll && !(parts[0] === "build" && parts[1] === "target")) window.scrollTo(0, 0);
  }

  search.addEventListener("input", () => {
    const query = search.value.trim();
    if (!query) {preview.hidden = true; return;}
    const items = searchItems(query);
    preview.innerHTML = items.slice(0, 8).map(item => `<a class="search-result" href="${item.href}"><span>${item.type === "symbol" ? kindBadge(item.symbol) : '<span class="badge">file</span>'}</span><span>${esc(item.name)}<small>${esc(item.path)}</small></span></a>`).join("") + `<a class="search-result" href="#search/${encode(query)}"><span>⌕</span><span>${items.length ? "View all " + items.length + " results" : "No direct matches · open search"} →</span></a>`;
    preview.hidden = false;
  });
  search.addEventListener("keydown", event => {
    if (event.key === "Enter") {location.hash = "#search/" + encode(search.value.trim()); preview.hidden = true; search.blur();}
    if (event.key === "Escape") {preview.hidden = true; search.blur();}
    if (event.key === "ArrowDown" && !preview.hidden) {event.preventDefault(); preview.querySelector("a")?.focus();}
  });
  document.addEventListener("click", event => {if (!event.target.closest(".search-wrap")) preview.hidden = true;});
  document.addEventListener("keydown", event => {
    if (event.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) {event.preventDefault(); search.focus();}
    if (event.key === "Escape") {preview.hidden = true; document.querySelector(".sidebar").classList.remove("open"); document.getElementById("menu-button").setAttribute("aria-expanded", "false");}
  });
  document.getElementById("print-button").addEventListener("click", () => window.print());
  document.querySelector(".skip-link").addEventListener("click", event => {event.preventDefault(); main.focus(); main.scrollIntoView({block: "start"});});
  document.getElementById("menu-button").addEventListener("click", () => {const open = document.querySelector(".sidebar").classList.toggle("open"); document.getElementById("menu-button").setAttribute("aria-expanded", String(open));});
  // Make collapsed target/source details visible in print; restore the screen state.
  let closedBeforePrint = [];
  window.addEventListener("beforeprint", () => { closedBeforePrint = [...main.querySelectorAll("details:not([open])")]; closedBeforePrint.forEach(details => details.open = true); document.querySelectorAll(".graph-svg").forEach(svg => {if (svg._zoom) svg._zoom("reset");}); });
  window.addEventListener("afterprint", () => {closedBeforePrint.forEach(details => details.open = false); closedBeforePrint = [];});
  window.addEventListener("hashchange", () => renderRoute());
  renderNavigation();
  renderRoute();
})();
