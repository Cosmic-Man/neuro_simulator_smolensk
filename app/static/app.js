const state = {
  metadata: null,
  history: null,
  evaluation: null,
  indices: null,
  scenarios: [],
  baseImpulses: {},
  graph: null,
  cy: null,
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

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = (await response.json()).detail || message; } catch (_) { /* empty */ }
    throw new Error(message);
  }
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
  Plotly.react("seasonPlot", [{
    x: ["I", "II", "III", "IV"], y: buckets.map(values => values.reduce((a, b) => a + b, 0) / values.length),
    type: "bar", marker: { color: [colors.teal, colors.bright, colors.gold, colors.coral] }, hovertemplate: "%{x} квартал<br>%{y:.2f}<extra></extra>",
  }], { ...baseLayout, showlegend: false, margin: { l: 52, r: 18, t: 12, b: 42 } }, plotConfig);
}

function renderIndices() {
  const latestIndex = state.indices.fuzzy.map(item => ({ ...item, value: item.values[item.values.length - 1] }));
  document.getElementById("fuzzyIndexCards").innerHTML = latestIndex.map(item => `
    <article class="panel index-card"><strong>${formatNumber(item.value)}</strong><small>${item.label}</small></article>`).join("");
  const latestLinear = state.indices.linear[state.indices.linear.length - 1];
  const latestHierarchical = state.indices.hierarchical[state.indices.hierarchical.length - 1];
  document.getElementById("expertIndexCards").innerHTML = `
    <article class="panel expert-index-card"><div><span class="panel-kicker">31 исходный показатель</span><small>Линейный индекс Гульдар</small></div><strong>${formatNumber(latestLinear)}</strong></article>
    <article class="panel expert-index-card"><div><span class="panel-kicker">8 нечётких индексов</span><small>Иерархический индекс Гульдар</small></div><strong>${formatNumber(latestHierarchical)}</strong></article>`;
  fillSelect(document.getElementById("fuzzyIndexSelect"), state.indices.fuzzy);
  renderFuzzyIndexPlot();
  const contributionRows = items => {
    const max = Math.max(...items.map(item => Math.abs(item.value)), 0.001);
    return items.map(item => `
      <div class="contribution-row" title="${item.label}"><span>${item.label}</span><div class="contribution-track"><div class="contribution-fill" style="width:${Math.abs(item.value) / max * 100}%"></div></div><strong>${formatNumber(item.value, 3)}</strong></div>`).join("");
  };
  document.getElementById("linearContributions").innerHTML = contributionRows(state.indices.top_contributions);
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
    { x: state.indices.periods, y: state.indices.linear, name: "Гульдар · 31 показатель", type: "scatter", mode: "lines", line: { color: colors.gold, width: 2 } },
    { x: state.indices.periods, y: state.indices.hierarchical, name: "Гульдар · 8 нечётких индексов", type: "scatter", mode: "lines", line: { color: colors.coral, width: 2 } },
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

function scenarioById(id) { return state.scenarios.find(item => item.id === id); }

function renderScenarioControls(selectedId = null) {
  const select = document.getElementById("scenarioPreset");
  fillSelect(select, state.scenarios);
  if (selectedId && state.scenarios.some(item => item.id === selectedId)) select.value = selectedId;
  const adjustable = state.metadata.nodes.filter(node => node.adjustable);
  const primaryIds = new Set(["road_budget_execution", "transit_budget_execution", "safety_budget_execution", "road_repair", "crossings"]);
  const renderSlider = node => `<div class="slider-item"><div class="slider-meta"><span>${node.label}</span><span id="value-${node.id}" class="slider-value">0.00</span></div><input type="range" min="-0.30" max="0.30" step="0.01" value="0" data-node="${node.id}" aria-label="${node.label}"></div>`;
  const primary = adjustable.filter(node => primaryIds.has(node.id));
  const advanced = adjustable.filter(node => !primaryIds.has(node.id));
  document.getElementById("scenarioSliders").innerHTML = `${primary.map(renderSlider).join("")}<details><summary>Дополнительные узлы</summary>${advanced.map(renderSlider).join("")}</details>`;
  document.querySelectorAll("#scenarioSliders input").forEach(input => input.addEventListener("input", () => {
    document.getElementById(`value-${input.dataset.node}`).textContent = Number(input.value).toFixed(2);
  }));
  applySelectedScenario();
}

function applySelectedScenario() {
  const scenario = scenarioById(document.getElementById("scenarioPreset").value);
  if (!scenario) return;
  document.getElementById("scenarioDescription").textContent = scenario.description;
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
}

function resetSliders() { applySelectedScenario(); }

async function uploadScenario() {
  const input = document.getElementById("scenarioFile");
  const file = input.files[0];
  if (!file) { showToast("Выберите JSON-файл", true); return; }
  if (file.size > 65536) { showToast("JSON-файл превышает 64 КБ", true); return; }
  try {
    const payload = JSON.parse(await file.text());
    const saved = await api("/api/scenarios", { method: "POST", body: JSON.stringify(payload) });
    const response = await api("/api/scenarios");
    state.scenarios = response.scenarios;
    renderScenarioControls(saved.id);
    showToast(`Сценарий «${saved.label}» сохранён`);
  } catch (error) { showToast(error.message, true); }
}

function plotScenario(div, baseline, scenario, key, unit, customDataKey = null) {
  const customBaseline = customDataKey ? baseline.map(row => row[customDataKey]) : null;
  const customScenario = customDataKey ? scenario.map(row => row[customDataKey]) : null;
  const hoverExtra = customDataKey ? "<br>ДТП: %{customdata:.2f}" : "";
  Plotly.react(div, [
    { x: baseline.map(row => row.period), y: baseline.map(row => row[key]), customdata: customBaseline, name: "Инерционный", type: "scatter", mode: "lines", line: { color: "#a4afae", width: 2, dash: "dot" }, hovertemplate: `%{x}<br>%{y:.2f} ${unit}${hoverExtra}<extra></extra>` },
    { x: scenario.map(row => row.period), y: scenario.map(row => row[key]), customdata: customScenario, name: "Сценарий", type: "scatter", mode: "lines+markers", line: { color: colors.teal, width: 3 }, marker: { size: 6 }, hovertemplate: `%{x}<br>%{y:.2f} ${unit}${hoverExtra}<extra></extra>` },
  ], { ...baseLayout, margin: { l: 48, r: 12, t: 36, b: 48 }, yaxis: { ...baseLayout.yaxis, title: unit }, legend: { ...baseLayout.legend, y: 1.18 } }, plotConfig);
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
    plotScenario("safetyPlot", result.baseline, result.scenario_result, "safety_index", "баллы", "accidents");
    plotScenario("regularityPlot", result.baseline, result.scenario_result, "regularity", "%");
    plotScenario("accessibilityPlot", result.baseline, result.scenario_result, "accessibility", "баллы");
    plotScenario("integratedPlot", result.baseline, result.scenario_result, "integrated_mobility", "баллы");
    document.getElementById("scenarioResultTitle").textContent = result.scenario.label;
    document.getElementById("scenarioExplanation").innerHTML = result.explanation.map(item => `<li>${item}</li>`).join("");
    document.getElementById("appliedImpulses").innerHTML = result.applied_impulses.length
      ? result.applied_impulses.map(item => `<span class="tag">${item.label}: ${item.value > 0 ? "+" : ""}${item.value.toFixed(2)}</span>`).join("")
      : '<span class="tag">Без внешних импульсов</span>';
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Запустить прогноз"; }
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

function bindEvents() {
  document.getElementById("historyMetric").addEventListener("change", renderHistory);
  document.getElementById("fuzzyIndexSelect").addEventListener("change", renderFuzzyIndexPlot);
  document.getElementById("evaluationTarget").addEventListener("change", renderEvaluation);
  document.getElementById("evaluationSplit").addEventListener("change", renderEvaluation);
  document.getElementById("fcmMode").addEventListener("change", () => renderFcm().catch(error => showToast(error.message, true)));
  document.getElementById("scenarioPreset").addEventListener("change", applySelectedScenario);
  document.getElementById("resetSliders").addEventListener("click", resetSliders);
  document.getElementById("uploadScenario").addEventListener("click", uploadScenario);
  document.getElementById("runScenario").addEventListener("click", runScenario);
  document.getElementById("sensitivityTarget").addEventListener("change", renderSensitivity);
}

async function initialize() {
  const status = document.getElementById("apiStatus");
  try {
    const [health, metadata, history, indices, evaluation, scenarios] = await Promise.all([
      api("/api/health"), api("/api/metadata"), api("/api/history"), api("/api/indices"), api("/api/evaluation"), api("/api/scenarios"),
    ]);
    Object.assign(state, { metadata, history, indices, evaluation, scenarios: scenarios.scenarios });
    status.className = "status-pill ready"; status.innerHTML = `<span></span>Готово · ${health.periods} кварталов`;
    renderOverview();
    fillSelect(document.getElementById("historyMetric"), state.history.series); document.getElementById("historyMetric").value = "integrated_mobility";
    fillSelect(document.getElementById("evaluationTarget"), state.evaluation.targets);
    fillSelect(document.getElementById("sensitivityTarget"), state.evaluation.targets);
    renderHistory(); renderIndices(); renderEvaluation(); renderAnfisCards(); renderScenarioControls(); renderSensitivity(); bindEvents();
    await renderFcm(); await runScenario();
  } catch (error) {
    status.className = "status-pill error"; status.innerHTML = "<span></span>Ошибка запуска";
    showToast(`Не удалось запустить интерфейс: ${error.message}`, true); console.error(error);
  }
}

window.addEventListener("DOMContentLoaded", initialize);
