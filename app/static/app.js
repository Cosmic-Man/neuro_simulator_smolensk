const state = {
  metadata: null,
  history: null,
  evaluation: null,
  indices: null,
  scenarios: [],
  baseImpulses: {},
  graph: null,
  cy: null,
  user: null,
  csrfToken: null,
  budgetAnalysis: null,
  eventsBound: false,
};

const colors = {
  ink: "#112a2b", muted: "#647776", teal: "#0b6f68", bright: "#20a79b",
  coral: "#e2694f", gold: "#c9933b", blue: "#3a75a7", grid: "rgba(17,42,43,.10)",
};
const plotConfig = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] };
const baseLayout = {
  paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  margin: { l: 56, r: 24, t: 24, b: 52 },
  font: { family: "Segoe UI, Arial, sans-serif", color: colors.muted, size: 11 },
  hoverlabel: { bgcolor: colors.ink, bordercolor: colors.ink, font: { color: "#fff" } },
  xaxis: { gridcolor: colors.grid, zeroline: false }, yaxis: { gridcolor: colors.grid, zeroline: false },
  legend: { orientation: "h", y: 1.12, x: 0 },
};

const sectionGuide = [
  {
    id: "scenarios", index: "01", title: "Лаборатория FCM-сценариев", collapsible: true,
    explanation: "Позволяет сравнить управленческие варианты: изменить воздействия, увидеть ожидаемый результат в процентах, сохранить сценарий и показать его выбранным наблюдателям.",
  },
  {
    id: "sensitivity", index: "02", title: "Чувствительность", collapsible: true,
    explanation: "Ранжирует направления по силе влияния на выбранную цель. Чем заметнее изменение, тем больший модельный эффект ожидается от работы с этим фактором.",
  },
  {
    id: "overview", index: "03", title: "Текущее состояние", collapsible: true,
    explanation: "Краткая управленческая сводка последнего доступного периода: где транспортная система находится сейчас и какие значения используются как точка отсчёта.",
  },
  {
    id: "history", index: "04", title: "История и сезонность", collapsible: true,
    explanation: "Показывает устойчивость изменений во времени, сезонные колебания и периоды улучшения или ухудшения — чтобы не принять единичный всплеск за долгосрочный тренд.",
  },
  {
    id: "indices", index: "05", title: "Сводные индексы", collapsible: true,
    explanation: "Собирает множество разрозненных показателей в понятные оценки от 0 до 100 и показывает, из каких направлений складывается общая ситуация.",
  },
  {
    id: "models", index: "06", title: "Проверка моделей", collapsible: true,
    explanation: "Показывает, насколько прогнозы совпадали с уже известными данными. Заказчик видит, на какой метод можно опираться и где сохраняется неопределённость.",
  },
  {
    id: "map", index: "07", title: "Карта связей FCM", collapsible: true,
    explanation: "Объясняет, какие решения и городские факторы связаны с безопасностью, регулярностью и доступностью. Карта помогает проследить логику уже полученного сценарного результата.",
  },
];

function resizeSectionVisuals(section) {
  const resize = () => {
    section.querySelectorAll(".js-plotly-plot").forEach(plot => window.Plotly?.Plots?.resize(plot));
    if (section.id === "map" && state.cy) {
      state.cy.resize();
      state.cy.fit(undefined, 36);
    }
  };
  window.requestAnimationFrame(() => {
    resize();
    window.requestAnimationFrame(resize);
  });
  window.setTimeout(resize, 240);
}

function setAccordionExpanded(section, expanded) {
  const toggle = section.querySelector(":scope > .accordion-toggle");
  const content = section.querySelector(":scope > .accordion-content");
  if (!toggle || !content) return;
  toggle.setAttribute("aria-expanded", String(expanded));
  content.hidden = !expanded;
  section.classList.toggle("accordion-expanded", expanded);
  toggle.querySelector(".accordion-action").textContent = expanded ? "Свернуть раздел" : "Развернуть раздел";
  if (expanded) resizeSectionVisuals(section);
}

function initializePageStructure() {
  const main = document.querySelector("main.shell");
  const admin = document.getElementById("adminPanel");
  sectionGuide.forEach(item => main.insertBefore(document.getElementById(item.id), admin));

  sectionGuide.forEach(item => {
    const section = document.getElementById(item.id);
    const heading = section.querySelector(":scope > .section-heading");
    heading.querySelector(".section-index").textContent = item.index;
    heading.querySelector("h2").textContent = item.title;

    const help = document.createElement("span");
    help.className = "section-help";
    help.innerHTML = `<button class="section-help-trigger" type="button" aria-describedby="help-${item.id}">Что показывает?</button>
      <span id="help-${item.id}" class="section-help-tooltip" role="tooltip">${escapeHtml(item.explanation)}</span>`;
    heading.querySelector(":scope > div").appendChild(help);

    if (!item.collapsible) return;
    const content = document.createElement("div");
    content.id = `${item.id}Content`;
    content.className = "accordion-content";
    while (heading.nextSibling) content.appendChild(heading.nextSibling);

    const toggle = document.createElement("button");
    toggle.className = "accordion-toggle";
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", content.id);
    toggle.innerHTML = `<span><strong class="accordion-action">Развернуть раздел</strong><small>${escapeHtml(item.title)} · нажмите здесь, чтобы показать содержимое</small></span><b aria-hidden="true">⌄</b>`;
    toggle.addEventListener("click", () => setAccordionExpanded(section, toggle.getAttribute("aria-expanded") !== "true"));
    section.append(toggle, content);
    content.hidden = true;
  });

  document.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener("click", () => {
    const target = document.getElementById(link.getAttribute("href").slice(1));
    if (target) setAccordionExpanded(target, true);
  }));
  if (window.location.hash) {
    const target = document.getElementById(window.location.hash.slice(1));
    if (target) setAccordionExpanded(target, true);
  }
}

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (state.csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method)) headers["X-CSRF-Token"] = state.csrfToken;
  const response = await fetch(path, { ...options, method, headers, credentials: "same-origin" });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = (await response.json()).detail || message; } catch (_) { /* empty */ }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return null;
  return response.json();
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = `toast visible${isError ? " error" : ""}`;
  window.setTimeout(() => { toast.className = "toast"; }, 3500);
}

function formatNumber(value, digits = 1) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function fillSelect(select, items, valueKey = "id", labelKey = "label") {
  select.innerHTML = "";
  items.forEach(item => {
    const option = document.createElement("option");
    option.value = item[valueKey];
    option.textContent = `${item.builtin === false ? "★ " : ""}${item[labelKey]}`;
    select.appendChild(option);
  });
}

function renderOverview() {
  const latest = state.history.latest;
  document.getElementById("latestPeriod").textContent = `Данные за ${latest.period}`;
  document.getElementById("nodeCount").textContent = state.metadata.fcm.nodes;
  document.getElementById("edgeCount").textContent = state.metadata.fcm.edges;
  document.getElementById("scenarioCount").textContent = state.scenarios.filter(item => item.builtin).length;
  const cards = [
    { label: "Безопасность", value: latest.traffic_safety, unit: "из 100", color: colors.coral },
    { label: "Рейсы по расписанию", value: latest.regularity, unit: "%", color: colors.teal },
    { label: "Доступность", value: latest.accessibility, unit: "из 100", color: colors.blue },
    { label: "Итоговая мобильность", value: latest.integrated_mobility, unit: "из 100", color: colors.gold },
  ];
  document.getElementById("kpiGrid").innerHTML = cards.map(card => `
    <article class="panel kpi-card" style="--accent:${card.color}">
      <span class="kpi-label">${card.label}</span><strong>${formatNumber(card.value)}</strong><small>${card.unit}</small>
    </article>`).join("");
  const groups = [...new Set(state.metadata.features.map(feature => feature.group))];
  document.getElementById("sheetTags").innerHTML = groups.map(group => `<span class="tag">${group}</span>`).join("");
  document.getElementById("proxyList").innerHTML = state.metadata.proxies.map(proxy =>
    `<div class="proxy-item"><strong>${proxy.id}</strong><span>${proxy.description}</span></div>`).join("");
}

function historySeries(id) { return state.history.series.find(item => item.id === id); }

function renderHistory() {
  const selected = historySeries(document.getElementById("historyMetric").value);
  document.getElementById("historyTitle").textContent = selected.label;
  const shapes = [
    { type: "rect", xref: "x", yref: "paper", x0: "2019Q1", x1: "2022Q4", y0: 0, y1: 1, fillcolor: "rgba(201,147,59,.09)", line: { width: 0 }, layer: "below" },
    { type: "rect", xref: "x", yref: "paper", x0: "2023Q1", x1: "2025Q4", y0: 0, y1: 1, fillcolor: "rgba(226,105,79,.08)", line: { width: 0 }, layer: "below" },
  ];
  Plotly.react("historyPlot", [{
    x: state.history.periods, y: selected.values, type: "scatter", mode: "lines+markers",
    line: { color: colors.teal, width: 2.5 }, marker: { size: 4 }, name: selected.label,
    hovertemplate: `%{x}<br>%{y:.2f} ${selected.unit}<extra></extra>`,
  }], { ...baseLayout, shapes, yaxis: { ...baseLayout.yaxis, title: selected.unit } }, plotConfig);
  const buckets = [[], [], [], []];
  selected.values.forEach((value, index) => buckets[Number(state.history.periods[index].slice(-1)) - 1].push(value));
  const quarterLabels = ["I", "II", "III", "IV"];
  const quarterAverages = buckets.map(values => values.reduce((a, b) => a + b, 0) / values.length);
  const bestQuarter = quarterAverages.indexOf(Math.max(...quarterAverages));
  const weakestQuarter = quarterAverages.indexOf(Math.min(...quarterAverages));
  const quarterMean = quarterAverages.reduce((sum, value) => sum + value, 0) / quarterAverages.length;
  const quarterSpread = Math.max(...quarterAverages) - Math.min(...quarterAverages);
  const quarterPadding = Math.max(quarterSpread * .65, Math.abs(quarterMean) * .025, .5);
  document.getElementById("seasonSummary").textContent = bestQuarter === weakestQuarter
    ? "Средние значения по кварталам практически совпадают"
    : `Максимум: ${quarterLabels[bestQuarter]} квартал — ${formatNumber(quarterAverages[bestQuarter], 1)}; минимум: ${quarterLabels[weakestQuarter]} квартал — ${formatNumber(quarterAverages[weakestQuarter], 1)}`;
  Plotly.react("seasonPlot", [{
    x: quarterLabels, y: quarterAverages,
    type: "scatter", mode: "lines+markers+text",
    line: { color: colors.teal, width: 3 },
    marker: {
      size: quarterAverages.map((_, index) => index === bestQuarter || index === weakestQuarter ? 14 : 11),
      color: quarterAverages.map((_, index) => index === bestQuarter ? colors.gold : index === weakestQuarter ? colors.coral : colors.teal),
      line: { color: "#fff", width: 2 },
    },
    text: quarterAverages.map(value => formatNumber(value, 1)), textposition: "top center", textfont: { size: 11 }, cliponaxis: false,
    hovertemplate: "%{x} квартал<br><b>%{y:.2f}</b><extra></extra>",
  }], {
    ...baseLayout, height: 165, showlegend: false,
    margin: { l: 40, r: 10, t: 25, b: 27 },
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: quarterMean, y1: quarterMean, line: { color: colors.muted, width: 1, dash: "dot" } }],
    annotations: [{ xref: "paper", x: 1, y: quarterMean, text: `среднее ${formatNumber(quarterMean, 1)}`, showarrow: false, xanchor: "right", yshift: 9, font: { size: 9, color: colors.muted } }],
    xaxis: { ...baseLayout.xaxis, title: "", showgrid: false },
    yaxis: { ...baseLayout.yaxis, title: selected.unit, range: [Math.min(...quarterAverages) - quarterPadding, Math.max(...quarterAverages) + quarterPadding], nticks: 4 },
  }, plotConfig);
}

function renderIndices() {
  const latestIndex = state.indices.fuzzy.map(item => ({ ...item, value: item.values[item.values.length - 1] }));
  document.getElementById("fuzzyIndexCards").innerHTML = latestIndex.map(item => `
    <article class="panel index-card"><strong>${formatNumber(item.value)}</strong><small>${item.label}</small></article>`).join("");
  const latestHierarchical = state.indices.hierarchical[state.indices.hierarchical.length - 1];
  document.getElementById("hierarchicalIndexCard").innerHTML = `
    <article class="panel expert-index-card"><div><span class="panel-kicker">8 нечётких индексов</span><small>Иерархический индекс Гульдар</small></div><strong>${formatNumber(latestHierarchical)}</strong></article>`;
  document.getElementById("fuzzySourceList").innerHTML = state.indices.fuzzy.map((item, index) => `
    <section class="fuzzy-source-item">
      <div class="fuzzy-source-heading"><span>${index + 1}</span><strong>${item.label}</strong></div>
      <ul>${item.features.map(feature => `<li><code>${feature}</code></li>`).join("")}</ul>
    </section>`).join("");
  fillSelect(document.getElementById("fuzzyIndexSelect"), state.indices.fuzzy);
  renderFuzzyIndexPlot();
  const contributionRows = items => {
    const max = Math.max(...items.map(item => Math.abs(item.value)), 0.001);
    return items.map(item => `
      <div class="contribution-row" title="${item.label}"><span>${item.label}</span><div class="contribution-track"><div class="contribution-fill" style="width:${Math.abs(item.value) / max * 100}%"></div></div><strong>${formatNumber(item.value, 3)}</strong></div>`).join("");
  };
  document.getElementById("hierarchicalContributions").innerHTML = contributionRows(state.indices.hierarchical_contributions);
  const stats = state.indices.hierarchical_stats;
  document.getElementById("hierarchicalStats").innerHTML = [
    ["Среднее", stats.mean], ["Медиана", stats.median], ["σ", stats.std],
    ["Минимум", stats.minimum], ["Максимум", stats.maximum], ["Последний", stats.latest],
  ].map(([label, value]) => `<div><span>${label}</span><strong>${formatNumber(value, 2)}</strong></div>`).join("");
}

function renderFuzzyIndexPlot() {
  const id = document.getElementById("fuzzyIndexSelect").value;
  const item = state.indices.fuzzy.find(index => index.id === id);
  Plotly.react("fuzzyIndexPlot", [
    { x: state.indices.periods, y: item.values, name: item.label, type: "scatter", mode: "lines", line: { color: colors.teal, width: 2.5 } },
    { x: state.indices.periods, y: state.indices.hierarchical, name: "Гульдар · 8 нечётких индексов", type: "scatter", mode: "lines", line: { color: colors.coral, width: 2, dash: "solid" } },
  ], { ...baseLayout, margin: { l: 50, r: 16, t: 24, b: 46 }, yaxis: { ...baseLayout.yaxis, range: [0, 100], title: "баллы" } }, plotConfig);
}

function selectedEvaluation() {
  return state.evaluation.targets.find(target => target.id === document.getElementById("evaluationTarget").value);
}

function renderEvaluation() {
  const target = selectedEvaluation();
  const split = document.getElementById("evaluationSplit").value;
  const rows = target.predictions[split];
  const palette = { seasonal_naive: colors.muted, ridge: colors.blue, fcm_expert: colors.gold, fcm_adapted: colors.coral, anfis: colors.teal };
  const traces = [{ x: rows.map(row => row.period), y: rows.map(row => row.actual), name: "Факт", type: "scatter", mode: "lines+markers", line: { color: colors.ink, width: 4 } }];
  Object.entries(state.evaluation.model_labels).forEach(([model, label]) => traces.push({
    x: rows.map(row => row.period), y: rows.map(row => row[model]), name: label, type: "scatter", mode: "lines", line: { color: palette[model], width: 2 },
  }));
  Plotly.react("evaluationPlot", traces, { ...baseLayout, yaxis: { ...baseLayout.yaxis, title: target.unit } }, plotConfig);
  const metrics = target.metrics.filter(row => row.split === split);
  const bestRmse = Math.min(...metrics.map(row => row.rmse));
  document.getElementById("metricsBody").innerHTML = metrics.map(row => `
    <tr><td>${row.model_label}</td><td>${formatNumber(row.mae, 3)}</td><td class="${row.rmse === bestRmse ? "best-metric" : ""}">${formatNumber(row.rmse, 3)}</td><td>${formatNumber(row.smape, 2)}%</td><td>${formatNumber(row.mase, 3)}</td><td>${formatNumber(row.directional_accuracy * 100, 1)}%</td></tr>`).join("");
}

function renderAnfisCards() {
  const labels = Object.fromEntries(state.metadata.targets.map(target => [target.id, target.label]));
  document.getElementById("anfisCards").innerHTML = state.metadata.anfis.map(model => `
    <article class="panel model-card"><span class="panel-kicker">ANFIS · ${model.rule_count} правил</span><h3>${labels[model.target]}</h3><ul>
      <li><span>Входы</span><strong>${model.inputs.length}</strong></li><li><span>σ</span><strong>${formatNumber(model.sigma, 2)}</strong></li>
      <li><span>Ridge</span><strong>${formatNumber(model.ridge, 3)}</strong></li><li><span>Validation RMSE</span><strong>${formatNumber(model.validation_rmse, 3)}</strong></li>
    </ul></article>`).join("");
}

async function renderFcm() {
  const mode = document.getElementById("fcmMode").value;
  state.graph = await api(`/api/fcm?mode=${mode}`);
  if (state.cy) state.cy.destroy();
  state.cy = cytoscape({
    container: document.getElementById("fcmGraph"), elements: [...state.graph.nodes, ...state.graph.edges],
    style: [
      { selector: "node", style: { "background-color": colors.blue, label: "data(label)", color: colors.ink, "font-size": 10, "text-wrap": "wrap", "text-max-width": 95, "text-valign": "bottom", "text-margin-y": 8, width: 32, height: 32 } },
      { selector: 'node[kind = "control"]', style: { "background-color": colors.gold, shape: "round-rectangle" } },
      { selector: 'node[kind = "target"]', style: { "background-color": colors.coral, width: 42, height: 42 } },
      { selector: "edge", style: { width: "mapData(weight, -1, 1, 1, 5)", "curve-style": "bezier", "target-arrow-shape": "triangle", "line-color": colors.teal, "target-arrow-color": colors.teal, opacity: .72, label: "data(label)", "font-size": 8, "text-background-opacity": .8, "text-background-color": "#f4f1e8" } },
      { selector: 'edge[sign = "negative"]', style: { "line-color": colors.coral, "target-arrow-color": colors.coral } },
    ],
    layout: { name: "cose", animate: false, padding: 38, nodeRepulsion: 520000, idealEdgeLength: 110 },
  });
  state.cy.on("tap", "edge", event => {
    const edge = event.target.data();
    const source = state.metadata.nodes.find(node => node.id === edge.source);
    const target = state.metadata.nodes.find(node => node.id === edge.target);
    document.getElementById("edgeInspector").innerHTML = `<span class="panel-kicker">Инспектор связи</span><h3>${source.label} → ${target.label}</h3><p>${edge.weight >= 0 ? "Положительное" : "Отрицательное"} влияние. Вес в режиме «${mode}»: ${edge.weight > 0 ? "+" : ""}${edge.weight.toFixed(3)}.</p>`;
  });
}

function scenarioReference(scenario) { return scenario.database_id || scenario.id; }
function scenarioByReference(reference) { return state.scenarios.find(item => scenarioReference(item) === reference); }

function fillScenarioSelect(select) {
  select.innerHTML = "";
  state.scenarios.forEach(item => {
    const option = document.createElement("option");
    option.value = scenarioReference(item);
    const owner = item.owner ? ` · ${item.owner.display_name}` : "";
    option.textContent = `${item.builtin ? "" : "★ "}${item.label}${owner}`;
    select.appendChild(option);
  });
}

function renderScenarioControls(selectedReference = null) {
  const select = document.getElementById("scenarioPreset");
  fillScenarioSelect(select);
  if (selectedReference && state.scenarios.some(item => scenarioReference(item) === selectedReference)) select.value = selectedReference;
  const adjustable = state.metadata.nodes.filter(node => node.adjustable);
  const primaryIds = new Set(["road_budget_execution", "transit_budget_execution", "safety_budget_execution", "road_repair", "crossings"]);
  const renderSlider = node => `<div class="slider-item"><div class="slider-meta"><span>${node.label}</span><span id="value-${node.id}" class="slider-value">0.00</span></div><input type="range" min="-1" max="1" step="0.01" value="0" data-node="${node.id}" aria-label="${node.label}: от -1 до +1"></div>`;
  const primary = adjustable.filter(node => primaryIds.has(node.id));
  const advanced = adjustable.filter(node => !primaryIds.has(node.id));
  document.getElementById("scenarioSliders").innerHTML = `${primary.map(renderSlider).join("")}<details><summary>Дополнительные узлы</summary>${advanced.map(renderSlider).join("")}</details>`;
  document.querySelectorAll("#scenarioSliders input").forEach(input => input.addEventListener("input", () => {
    document.getElementById(`value-${input.dataset.node}`).textContent = Number(input.value).toFixed(2);
  }));
  applySelectedScenario();
}

function applySelectedScenario() {
  const scenario = scenarioByReference(document.getElementById("scenarioPreset").value);
  if (!scenario) return;
  document.getElementById("scenarioDescription").textContent = scenario.description;
  document.getElementById("scenarioOwner").textContent = scenario.builtin
    ? "Общий встроенный сценарий"
    : scenario.owner
      ? `Владелец: ${scenario.owner.display_name} (@${scenario.owner.username})`
      : "Ваш личный сценарий";
  document.getElementById("scenarioMode").value = scenario.mode;
  const horizon = document.getElementById("scenarioHorizon");
  if (![...horizon.options].some(option => Number(option.value) === Number(scenario.horizon))) {
    const option = document.createElement("option"); option.value = scenario.horizon; option.textContent = `${scenario.horizon} кварталов`; horizon.appendChild(option);
  }
  horizon.value = scenario.horizon;
  state.baseImpulses = { ...scenario.impulses };
  document.querySelectorAll("#scenarioSliders input").forEach(input => {
    input.value = state.baseImpulses[input.dataset.node] || 0;
    input.dispatchEvent(new Event("input"));
  });
  const canWrite = ["user", "admin"].includes(state.user.role);
  document.getElementById("saveScenario").textContent = scenario.builtin ? "Сохранить копию" : "Сохранить изменения";
  document.getElementById("deleteScenario").hidden = !canWrite || scenario.builtin;
  const sharing = document.getElementById("scenarioSharing");
  sharing.hidden = !canWrite || scenario.builtin;
  if (!sharing.hidden) {
    document.getElementById("observerShareList").innerHTML = '<span class="quiet-note">Загрузка наблюдателей…</span>';
    loadScenarioSharing(scenario).catch(error => showToast(error.message, true));
  }
}

function resetSliders() { applySelectedScenario(); }

function scenarioImpulsesFromControls() {
  const impulses = {};
  document.querySelectorAll("#scenarioSliders input").forEach(input => {
    const value = Number(input.value);
    if (Math.abs(value) > .0001) impulses[input.dataset.node] = Number(value.toFixed(4));
  });
  return impulses;
}

function scenarioPayloadFromControls(scenario, overrides = {}) {
  return {
    version: 1,
    id: overrides.id ?? scenario.id,
    label: overrides.label ?? scenario.label,
    description: overrides.description ?? scenario.description,
    mode: document.getElementById("scenarioMode").value,
    horizon: Number(document.getElementById("scenarioHorizon").value),
    impulses: scenarioImpulsesFromControls(),
  };
}

async function saveCurrentScenario() {
  const scenario = scenarioByReference(document.getElementById("scenarioPreset").value);
  if (!scenario || !["user", "admin"].includes(state.user.role)) return;

  try {
    let saved;
    if (scenario.builtin) {
      const id = window.prompt("Идентификатор нового сценария (латиница, цифры, '-' или '_'):", `my-${scenario.id}`);
      if (id == null) return;
      const label = window.prompt("Название сценария:", `${scenario.label} — пользовательский`);
      if (label == null) return;
      const description = window.prompt("Описание сценария:", scenario.description || "Пользовательская копия встроенного сценария");
      if (description == null) return;
      const payload = scenarioPayloadFromControls(scenario, {
        id: id.trim().toLowerCase(),
        label: label.trim(),
        description: description.trim(),
      });
      saved = await api("/api/scenarios", { method: "POST", body: JSON.stringify(payload) });
    } else {
      const payload = scenarioPayloadFromControls(scenario);
      saved = await api(`/api/scenarios/${encodeURIComponent(scenarioReference(scenario))}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    }

    const response = await api("/api/scenarios");
    state.scenarios = response.scenarios;
    renderScenarioControls(scenarioReference(saved));
    showToast(`Сценарий «${saved.label}» сохранён в базе данных`);
  } catch (error) { showToast(error.message, true); }
}

async function loadScenarioSharing(scenario) {
  const reference = scenarioReference(scenario);
  const sharing = await api(`/api/scenarios/${encodeURIComponent(reference)}/shares`);
  if (document.getElementById("scenarioPreset").value !== reference) return;
  document.getElementById("observerShareList").innerHTML = sharing.observers.length
    ? sharing.observers.map(observer => `<label class="observer-share-item">
        <input type="checkbox" value="${escapeHtml(observer.id)}" ${observer.selected ? "checked" : ""}>
        <span>${escapeHtml(observer.display_name)}<small>@${escapeHtml(observer.username)}</small></span>
      </label>`).join("")
    : '<span class="quiet-note">Активных наблюдателей пока нет.</span>';
}

async function saveScenarioSharing() {
  const scenario = scenarioByReference(document.getElementById("scenarioPreset").value);
  if (!scenario || scenario.builtin) return;
  const observerIds = [...document.querySelectorAll("#observerShareList input:checked")]
    .map(input => input.value);
  try {
    await api(`/api/scenarios/${encodeURIComponent(scenarioReference(scenario))}/shares`, {
      method: "PUT",
      body: JSON.stringify({ observer_ids: observerIds }),
    });
    showToast(observerIds.length
      ? `Доступ сохранён для наблюдателей: ${observerIds.length}`
      : "Доступ наблюдателей закрыт");
  } catch (error) { showToast(error.message, true); }
}

async function uploadScenario() {
  const input = document.getElementById("scenarioFile");
  const file = input.files[0];
  if (!file) { showToast("Выберите JSON-файл", true); return; }
  if (file.size > 65536) { showToast("JSON-файл превышает 64 КБ", true); return; }
  try {
    const payload = JSON.parse(await file.text());
    let saved;
    try {
      saved = await api("/api/scenarios", { method: "POST", body: JSON.stringify(payload) });
    } catch (error) {
      const existing = state.scenarios.find(item => !item.builtin && item.id === String(payload.id || "").toLowerCase());
      if (error.status !== 409 || !existing || !window.confirm(`Сценарий «${existing.label}» уже существует. Обновить его?`)) throw error;
      saved = await api(`/api/scenarios/${encodeURIComponent(scenarioReference(existing))}`, { method: "PUT", body: JSON.stringify(payload) });
    }
    const response = await api("/api/scenarios");
    state.scenarios = response.scenarios;
    renderScenarioControls(scenarioReference(saved));
    input.value = "";
    showToast(`Сценарий «${saved.label}» сохранён`);
  } catch (error) { showToast(error.message, true); }
}

async function deleteSelectedScenario() {
  const scenario = scenarioByReference(document.getElementById("scenarioPreset").value);
  if (!scenario || scenario.builtin) return;
  if (!window.confirm(`Удалить сценарий «${scenario.label}»?`)) return;
  try {
    await api(`/api/scenarios/${encodeURIComponent(scenarioReference(scenario))}`, { method: "DELETE" });
    const response = await api("/api/scenarios");
    state.scenarios = response.scenarios;
    renderScenarioControls();
    showToast("Сценарий удалён");
  } catch (error) { showToast(error.message, true); }
}

async function exportSelectedScenario() {
  const scenario = scenarioByReference(document.getElementById("scenarioPreset").value);
  if (!scenario) return;
  try {
    const payload = await api(`/api/scenarios/${encodeURIComponent(scenarioReference(scenario))}/export`);
    const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob); link.download = `${payload.id}.json`; link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) { showToast(error.message, true); }
}

async function plotScenario(div, baseline, scenario, key, unit, customDataKey = null) {
  const plot = document.getElementById(div);
  const customBaseline = customDataKey ? baseline.map(row => row[customDataKey]) : null;
  const customScenario = customDataKey ? scenario.map(row => row[customDataKey]) : null;
  const hoverExtra = customDataKey ? "<br>ДТП: %{customdata:.2f}" : "";
  await Plotly.react(plot, [
    { x: baseline.map(row => row.period), y: baseline.map(row => row[key]), customdata: customBaseline, name: "Инерционный", type: "scatter", mode: "lines", line: { color: "#a4afae", width: 2, dash: "dot" }, hovertemplate: `%{x}<br>%{y:.2f} ${unit}${hoverExtra}<extra></extra>` },
    { x: scenario.map(row => row.period), y: scenario.map(row => row[key]), customdata: customScenario, name: "Сценарий", type: "scatter", mode: "lines+markers", line: { color: colors.teal, width: 3 }, marker: { size: 6 }, hovertemplate: `%{x}<br>%{y:.2f} ${unit}${hoverExtra}<extra></extra>` },
  ], {
    ...baseLayout, autosize: true, margin: { l: 48, r: 12, t: 36, b: 48 },
    xaxis: { ...baseLayout.xaxis, autorange: true },
    yaxis: { ...baseLayout.yaxis, title: unit, autorange: true },
    legend: { ...baseLayout.legend, y: 1.18 },
  }, plotConfig);
  await Plotly.Plots.resize(plot);
  await Plotly.relayout(plot, { "xaxis.autorange": true, "yaxis.autorange": true });
}

function signed(value, digits = 1) {
  if (value == null) return "н/д";
  return `${value > 0 ? "+" : ""}${formatNumber(value, digits)}`;
}

function renderBusinessSummary(result) {
  const metrics = [
    ["safety", "Безопасность движения", colors.coral],
    ["regularity", "Регулярность транспорта", colors.teal],
    ["accessibility", "Транспортная доступность", colors.blue],
    ["integrated_mobility", "Итоговый индекс", colors.gold],
  ];
  document.getElementById("businessHorizon").textContent = `Горизонт: ${result.horizon} кварталов`;
  document.getElementById("businessKpis").innerHTML = metrics.map(([key, label, color]) => {
    const metric = result.summary[key];
    const trend = metric.delta_points > 0 ? "positive" : metric.delta_points < 0 ? "negative" : "neutral";
    const accident = key === "safety" && result.summary.accidents.improvement_percent != null
      ? `<span>Расчётное снижение ДТП: ${signed(result.summary.accidents.improvement_percent)}%</span>` : "";
    return `<article class="panel business-kpi ${trend}" style="--accent:${color}">
      <span>${label}</span><strong>${signed(metric.relative_change_percent)}%</strong>
      <small>${signed(metric.delta_points)} ${metric.delta_unit}<br>${formatNumber(metric.baseline)} → ${formatNumber(metric.scenario)}</small>${accident}
    </article>`;
  }).join("");
}

function budgetMetricCell(metric) {
  return `<strong>${signed(metric.relative_change_percent)}%</strong><small>${signed(metric.delta_points)} п.</small>`;
}

function renderBudgetAnalysis() {
  if (!state.budgetAnalysis) return;
  const objective = document.getElementById("budgetObjective").value;
  const programs = [...state.budgetAnalysis.programs].sort((a, b) =>
    (b.metrics[objective].relative_change_percent ?? -Infinity) - (a.metrics[objective].relative_change_percent ?? -Infinity));
  const names = { safety: "безопасности", regularity: "регулярности", accessibility: "доступности", integrated_mobility: "сбалансированного индекса" };
  const best = programs[0];
  document.getElementById("budgetRecommendation").textContent = best
    ? `Модельный приоритет для роста ${names[objective]}: «${best.label}» (${signed(best.metrics[objective].relative_change_percent)}%).`
    : "Недостаточно данных для ранжирования.";
  document.getElementById("budgetBody").innerHTML = programs.map((program, index) => `<tr class="${index === 0 ? "budget-best" : ""}">
    <td>${index === 0 ? "★ " : ""}${escapeHtml(program.label)}</td>
    <td>${budgetMetricCell(program.metrics.safety)}</td>
    <td>${budgetMetricCell(program.metrics.regularity)}</td>
    <td>${budgetMetricCell(program.metrics.accessibility)}</td>
    <td>${budgetMetricCell(program.metrics.integrated_mobility)}</td>
  </tr>`).join("");
  document.getElementById("budgetMethodology").textContent = state.budgetAnalysis.methodology_note;
}

async function runScenario() {
  const button = document.getElementById("runScenario");
  button.disabled = true; button.textContent = "Расчёт…";
  const impulses = {};
  document.querySelectorAll("#scenarioSliders input").forEach(input => {
    const delta = Number(input.value) - Number(state.baseImpulses[input.dataset.node] || 0);
    if (Math.abs(delta) > .0001) impulses[input.dataset.node] = delta;
  });
  try {
    const result = await api("/api/simulate", { method: "POST", body: JSON.stringify({
      scenario: document.getElementById("scenarioPreset").value,
      mode: document.getElementById("scenarioMode").value,
      horizon: Number(document.getElementById("scenarioHorizon").value), impulses,
    }) });
    if (state.user.role !== "observer") {
      await Promise.all([
        plotScenario("safetyPlot", result.baseline, result.scenario_result, "safety_index", "баллы", "accidents"),
        plotScenario("regularityPlot", result.baseline, result.scenario_result, "regularity", "%"),
        plotScenario("accessibilityPlot", result.baseline, result.scenario_result, "accessibility", "баллы"),
        plotScenario("integratedPlot", result.baseline, result.scenario_result, "integrated_mobility", "баллы"),
      ]);
    }
    renderBusinessSummary(result);
    state.budgetAnalysis = result.budget_analysis;
    renderBudgetAnalysis();
    document.getElementById("scenarioResultTitle").textContent = result.scenario.label;
    document.getElementById("scenarioExplanation").innerHTML = result.explanation.map(item => `<li>${item}</li>`).join("");
    document.getElementById("appliedImpulses").innerHTML = result.applied_impulses.length
      ? result.applied_impulses.map(item => `<span class="tag">${item.label}: ${item.value > 0 ? "+" : ""}${item.value.toFixed(2)}</span>`).join("")
      : '<span class="tag">Без внешних импульсов</span>';
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = state.user.role === "observer" ? "Показать результат" : "Запустить прогноз"; }
}

function renderSensitivity() {
  const targetId = document.getElementById("sensitivityTarget").value;
  const items = state.evaluation.sensitivity[targetId].slice(0, 10).reverse();
  const maxEffect = Math.max(...items.map(item => Math.abs(item.delta_index_points)), 0.01);
  Plotly.react("sensitivityPlot", [{
    x: items.map(item => item.delta_index_points), y: items.map(item => item.label), type: "bar", orientation: "h",
    marker: { color: items.map(item => item.delta_index_points >= 0 ? colors.teal : colors.coral) },
    text: items.map(item => `${item.delta_index_points >= 0 ? "+" : ""}${item.delta_index_points.toFixed(3)}`),
    textposition: "outside", cliponaxis: false,
    hovertemplate: "%{y}<br>%{x:+.3f} п.п.<extra></extra>",
  }], {
    ...baseLayout,
    height: 430,
    showlegend: false,
    margin: { l: 235, r: 62, t: 12, b: 52 },
    xaxis: {
      type: "linear", range: [-maxEffect * 1.25, maxEffect * 1.25],
      title: "Изменение целевого индекса, п.п.", gridcolor: colors.grid,
      zeroline: true, zerolinecolor: colors.ink, zerolinewidth: 1,
    },
    yaxis: {
      type: "category", categoryorder: "array", categoryarray: items.map(item => item.label),
      automargin: true, gridcolor: "rgba(0,0,0,0)", zeroline: false,
    },
  }, plotConfig);
}

function showLogin(message = "") {
  document.getElementById("appShell").hidden = true;
  document.getElementById("loginView").hidden = false;
  document.getElementById("loginError").textContent = message;
  document.getElementById("loginPassword").value = "";
  document.getElementById("loginUsername").focus();
}

function showApplication() {
  document.getElementById("loginView").hidden = true;
  document.getElementById("appShell").hidden = false;
}

function applyUserInterface() {
  const labels = { observer: "Наблюдатель", user: "Пользователь", admin: "Администратор" };
  const isObserver = state.user.role === "observer";
  const appShell = document.getElementById("appShell");
  appShell.classList.toggle("observer-mode", isObserver);
  document.getElementById("currentUserName").textContent = state.user.display_name;
  document.getElementById("currentUserRole").textContent = labels[state.user.role] || state.user.role;
  const canWrite = ["user", "admin"].includes(state.user.role);
  document.querySelectorAll(".role-editor").forEach(element => { element.hidden = !canWrite; });
  document.getElementById("adminPanel").hidden = state.user.role !== "admin";
  document.getElementById("heroEyebrow").textContent = isObserver ? "Режим наблюдателя" : "Аналитический прототип · 2006–2025";
  document.getElementById("heroTitle").innerHTML = isObserver
    ? "Доступные транспортные<br><em>сценарии и результаты</em>"
    : "Транспортная доступность<br><em>и безопасность города</em>";
  document.getElementById("heroCopy").textContent = isObserver
    ? "Вам доступны все 7 разделов системы: лаборатория сценариев, чувствительность, текущее состояние, история, индексы, модели и карта связей. Данные открыты для просмотра без сложных настроек и редактирования."
    : "Объяснимая модель объединяет квартальные данные, нечёткую когнитивную карту и ANFIS. Меняйте управляемые факторы и смотрите, как сценарий влияет на ДТП, регулярность транспорта и доступность.";
  document.getElementById("heroPrimaryAction").textContent = isObserver ? "Открыть доступные сценарии" : "Запустить сценарий";
  document.getElementById("scenarioControlKicker").textContent = isObserver ? "Доступные материалы" : "Настройки";
  document.getElementById("scenarioControlTitle").textContent = isObserver ? "Выберите сценарий" : "Управляющие воздействия";
  document.getElementById("runScenario").textContent = isObserver ? "Показать результат" : "Запустить прогноз";
  sectionGuide.forEach(item => {
    const section = document.getElementById(item.id);
    section.hidden = false;
    section.removeAttribute("aria-hidden");
    section.querySelector(":scope > .section-heading .section-index").textContent = item.index;
    setAccordionExpanded(section, isObserver && item.id === "scenarios");
  });
  if (state.user.must_change_password) showToast("Администратор потребовал сменить временный пароль", true);
}

async function login(event) {
  event.preventDefault();
  const button = document.getElementById("loginButton");
  button.disabled = true; button.textContent = "Вход…";
  document.getElementById("loginError").textContent = "";
  try {
    const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify({
      username: document.getElementById("loginUsername").value,
      password: document.getElementById("loginPassword").value,
    }) });
    state.user = result.user; state.csrfToken = result.csrf_token;
    showApplication(); applyUserInterface();
    await initializeApplication();
  } catch (error) {
    document.getElementById("loginError").textContent = error.message;
  } finally {
    button.disabled = false; button.textContent = "Войти";
  }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* session may already be gone */ }
  state.user = null; state.csrfToken = null; state.budgetAnalysis = null;
  showLogin("Вы вышли из системы");
}

async function changePassword() {
  const currentPassword = window.prompt("Текущий пароль:");
  if (currentPassword == null) return;
  const newPassword = window.prompt("Новый пароль (не менее 10 символов):");
  if (newPassword == null) return;
  try {
    await api("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) });
    state.user.must_change_password = false;
    showToast("Пароль изменён; другие сессии завершены");
  } catch (error) { showToast(error.message, true); }
}

async function loadAdminPanel() {
  if (state.user.role !== "admin") return;
  const [usersResult, auditResult] = await Promise.all([api("/api/admin/users"), api("/api/admin/audit?limit=50")]);
  document.getElementById("usersBody").innerHTML = usersResult.users.map(user => `<tr data-user-id="${user.id}">
    <td><strong>${escapeHtml(user.display_name)}</strong><small class="table-subline">${escapeHtml(user.username)}</small></td>
    <td><select class="admin-role"><option value="observer" ${user.role === "observer" ? "selected" : ""}>Наблюдатель</option><option value="user" ${user.role === "user" ? "selected" : ""}>Пользователь</option><option value="admin" ${user.role === "admin" ? "selected" : ""}>Администратор</option></select></td>
    <td><input class="admin-active" type="checkbox" ${user.is_active ? "checked" : ""} aria-label="Активен"></td>
    <td><div class="table-actions"><button class="mini-button save-user" type="button">Сохранить</button><button class="mini-button reset-user" type="button">Пароль</button></div></td>
  </tr>`).join("");
  document.querySelectorAll(".save-user").forEach(button => button.addEventListener("click", () => updateAdminUser(button.closest("tr"))));
  document.querySelectorAll(".reset-user").forEach(button => button.addEventListener("click", () => resetAdminPassword(button.closest("tr"))));
  document.getElementById("auditList").innerHTML = auditResult.events.length ? auditResult.events.map(event => `<div class="audit-row">
    <time>${new Date(`${event.created_at}Z`).toLocaleString("ru-RU")}</time><strong>${escapeHtml(event.action)}</strong><span>${escapeHtml(event.user?.username || "system")}</span>
  </div>`).join("") : '<p class="quiet-note">Событий пока нет.</p>';
}

async function createAdminUser(event) {
  event.preventDefault();
  try {
    await api("/api/admin/users", { method: "POST", body: JSON.stringify({
      username: document.getElementById("newUsername").value,
      display_name: document.getElementById("newDisplayName").value,
      password: document.getElementById("newPassword").value,
      role: document.getElementById("newRole").value,
      must_change_password: true,
    }) });
    event.target.reset();
    await loadAdminPanel();
    showToast("Пользователь создан");
  } catch (error) { showToast(error.message, true); }
}

async function updateAdminUser(row) {
  try {
    await api(`/api/admin/users/${row.dataset.userId}`, { method: "PATCH", body: JSON.stringify({
      role: row.querySelector(".admin-role").value,
      is_active: row.querySelector(".admin-active").checked,
    }) });
    await loadAdminPanel(); showToast("Права пользователя обновлены");
  } catch (error) { showToast(error.message, true); }
}

async function resetAdminPassword(row) {
  const password = window.prompt("Новый временный пароль (не менее 10 символов):");
  if (password == null) return;
  try {
    await api(`/api/admin/users/${row.dataset.userId}/reset-password`, { method: "POST", body: JSON.stringify({ password, must_change_password: true }) });
    showToast("Пароль сброшен, активные сессии завершены");
    await loadAdminPanel();
  } catch (error) { showToast(error.message, true); }
}

function bindEvents() {
  if (state.eventsBound) return;
  state.eventsBound = true;
  document.getElementById("historyMetric").addEventListener("change", renderHistory);
  document.getElementById("fuzzyIndexSelect").addEventListener("change", renderFuzzyIndexPlot);
  document.getElementById("evaluationTarget").addEventListener("change", renderEvaluation);
  document.getElementById("evaluationSplit").addEventListener("change", renderEvaluation);
  document.getElementById("fcmMode").addEventListener("change", () => renderFcm().catch(error => showToast(error.message, true)));
  document.getElementById("scenarioPreset").addEventListener("change", applySelectedScenario);
  document.getElementById("resetSliders").addEventListener("click", resetSliders);
  document.getElementById("saveScenario").addEventListener("click", saveCurrentScenario);
  document.getElementById("saveScenarioShares").addEventListener("click", saveScenarioSharing);
  document.getElementById("uploadScenario").addEventListener("click", uploadScenario);
  document.getElementById("deleteScenario").addEventListener("click", deleteSelectedScenario);
  document.getElementById("exportScenario").addEventListener("click", exportSelectedScenario);
  document.getElementById("runScenario").addEventListener("click", runScenario);
  document.getElementById("sensitivityTarget").addEventListener("change", renderSensitivity);
  document.getElementById("budgetObjective").addEventListener("change", renderBudgetAnalysis);
  document.getElementById("logoutButton").addEventListener("click", logout);
  document.getElementById("changePassword").addEventListener("click", changePassword);
  document.getElementById("createUserForm").addEventListener("submit", createAdminUser);
}

async function initializeApplication() {
  const status = document.getElementById("apiStatus");
  try {
    const isObserver = state.user.role === "observer";
    const [health, metadata, history, indices, evaluation, scenarios] = await Promise.all([
      api("/api/health"), api("/api/metadata"), api("/api/history"), api("/api/indices"), api("/api/evaluation"), api("/api/scenarios"),
    ]);
    Object.assign(state, { metadata, history, indices, evaluation, scenarios: scenarios.scenarios });
    status.className = "status-pill ready"; status.innerHTML = isObserver
      ? "<span></span>Доступны 7 разделов"
      : `<span></span>Готово · ${health.periods} кварталов`;
    renderOverview();
    renderScenarioControls(); bindEvents();
    fillSelect(document.getElementById("historyMetric"), state.history.series); document.getElementById("historyMetric").value = "integrated_mobility";
    fillSelect(document.getElementById("evaluationTarget"), state.evaluation.targets);
    fillSelect(document.getElementById("sensitivityTarget"), state.evaluation.targets);
    renderHistory(); renderIndices(); renderEvaluation(); renderAnfisCards(); renderSensitivity();
    await renderFcm();
    await runScenario();
    await loadAdminPanel();
  } catch (error) {
    if (error.status === 401) { showLogin("Сессия истекла. Войдите снова."); return; }
    status.className = "status-pill error"; status.innerHTML = "<span></span>Ошибка запуска";
    showToast(`Не удалось запустить интерфейс: ${error.message}`, true); console.error(error);
  }
}

async function bootstrap() {
  initializePageStructure();
  document.getElementById("loginForm").addEventListener("submit", login);
  try {
    const result = await api("/api/auth/me");
    state.user = result.user; state.csrfToken = result.csrf_token;
    showApplication(); applyUserInterface();
    await initializeApplication();
  } catch (error) {
    showLogin(error.status === 401 ? "" : `Не удалось проверить сессию: ${error.message}`);
  }
}

window.addEventListener("DOMContentLoaded", bootstrap);
