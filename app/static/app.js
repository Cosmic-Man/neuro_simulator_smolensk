const state = {
  metadata: null,
  history: null,
  evaluation: null,
  graph: null,
  cy: null,
};

const colors = {
  ink: "#112a2b",
  muted: "#647776",
  teal: "#0b6f68",
  bright: "#20a79b",
  coral: "#e2694f",
  gold: "#c9933b",
  blue: "#3a75a7",
  grid: "rgba(17,42,43,.10)",
};

const plotConfig = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] };
const baseLayout = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  margin: { l: 56, r: 24, t: 24, b: 52 },
  font: { family: "Segoe UI, Arial, sans-serif", color: colors.muted, size: 11 },
  hoverlabel: { bgcolor: colors.ink, bordercolor: colors.ink, font: { color: "#fff" } },
  xaxis: { gridcolor: colors.grid, zeroline: false },
  yaxis: { gridcolor: colors.grid, zeroline: false },
  legend: { orientation: "h", y: 1.12, x: 0 },
};

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = (await response.json()).detail || message; } catch (_) { /* noop */ }
    throw new Error(message);
  }
  return response.json();
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = `toast visible${isError ? " error" : ""}`;
  window.setTimeout(() => { toast.className = "toast"; }, 3200);
}

function formatNumber(value, digits = 1) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
}

function fillSelect(select, items, valueKey = "id", labelKey = "label") {
  select.innerHTML = "";
  items.forEach(item => {
    const option = document.createElement("option");
    option.value = item[valueKey];
    option.textContent = item[labelKey];
    select.appendChild(option);
  });
}

function renderOverview() {
  const latest = state.history.latest;
  document.getElementById("latestPeriod").textContent = `Данные за ${latest.period}`;
  document.getElementById("nodeCount").textContent = state.metadata.fcm.nodes;
  document.getElementById("edgeCount").textContent = state.metadata.fcm.edges;

  const cards = [
    { label: "ДТП на 10 тыс.", value: latest.accidents, unit: "случая", color: colors.coral },
    { label: "Рейсы по расписанию", value: latest.regularity, unit: "%", color: colors.teal },
    { label: "Доступность", value: latest.accessibility, unit: "из 100", color: colors.blue },
    { label: "Средняя скорость", value: latest.avg_speed, unit: "км/ч", color: colors.gold },
  ];
  document.getElementById("kpiGrid").innerHTML = cards.map(card => `
    <article class="panel kpi-card" style="--accent:${card.color}">
      <span class="kpi-label">${card.label}</span>
      <strong>${formatNumber(card.value)}</strong>
      <small>${card.unit}</small>
    </article>`).join("");

  document.getElementById("sheetTags").innerHTML = state.metadata.sheets
    .map(sheet => `<span class="tag">${sheet.id.toUpperCase()}</span>`).join("");
  document.getElementById("proxyList").innerHTML = state.metadata.proxies
    .map(proxy => `<div class="proxy-item"><strong>${proxy.label}</strong><span>${proxy.formula}</span></div>`).join("");
}

function historySeries(id) {
  return state.history.series.find(item => item.id === id);
}

function renderHistory() {
  const selected = historySeries(document.getElementById("historyMetric").value);
  document.getElementById("historyTitle").textContent = selected.label;
  const splitShapes = [
    { type: "rect", xref: "x", yref: "paper", x0: "2019Q1", x1: "2022Q4", y0: 0, y1: 1, fillcolor: "rgba(201,147,59,.08)", line: { width: 0 }, layer: "below" },
    { type: "rect", xref: "x", yref: "paper", x0: "2023Q1", x1: "2025Q4", y0: 0, y1: 1, fillcolor: "rgba(226,105,79,.07)", line: { width: 0 }, layer: "below" },
  ];
  Plotly.react("historyPlot", [{
    x: state.history.periods,
    y: selected.values,
    type: "scatter",
    mode: "lines",
    name: selected.label,
    line: { color: colors.teal, width: 3 },
    fill: "tozeroy",
    fillcolor: "rgba(32,167,155,.08)",
    hovertemplate: "%{x}<br>%{y:.2f} " + selected.unit + "<extra></extra>",
  }], { ...baseLayout, shapes: splitShapes, yaxis: { ...baseLayout.yaxis, title: selected.unit } }, plotConfig);

  const buckets = [[], [], [], []];
  selected.values.forEach((value, index) => buckets[Number(state.history.periods[index].slice(-1)) - 1].push(value));
  const averages = buckets.map(bucket => bucket.reduce((sum, value) => sum + value, 0) / bucket.length);
  Plotly.react("seasonPlot", [{
    x: ["I квартал", "II квартал", "III квартал", "IV квартал"],
    y: averages,
    type: "bar",
    marker: { color: [colors.teal, colors.bright, colors.gold, colors.coral], line: { width: 0 } },
    hovertemplate: "%{x}<br>%{y:.2f} " + selected.unit + "<extra></extra>",
  }], { ...baseLayout, showlegend: false, margin: { ...baseLayout.margin, t: 8 } }, plotConfig);
}

function selectedEvaluationTarget() {
  return state.evaluation.targets.find(target => target.id === document.getElementById("evaluationTarget").value);
}

function renderEvaluation() {
  const target = selectedEvaluationTarget();
  const split = document.getElementById("evaluationSplit").value;
  const rows = target.predictions[split];
  const modelColors = {
    seasonal_naive: "#9aa6a5",
    ridge: colors.blue,
    fcm_expert: colors.gold,
    fcm_adapted: colors.coral,
    anfis: colors.teal,
  };
  const traces = [{
    x: rows.map(row => row.period), y: rows.map(row => row.actual), name: "Факт",
    type: "scatter", mode: "lines+markers", line: { color: colors.ink, width: 4 }, marker: { size: 7 },
  }];
  Object.entries(state.evaluation.model_labels).forEach(([model, label]) => {
    traces.push({
      x: rows.map(row => row.period), y: rows.map(row => row[model]), name: label,
      type: "scatter", mode: "lines", line: { color: modelColors[model], width: 2, dash: model === "seasonal_naive" ? "dot" : "solid" },
    });
  });
  Plotly.react("evaluationPlot", traces, { ...baseLayout, yaxis: { ...baseLayout.yaxis, title: target.unit } }, plotConfig);

  const metrics = target.metrics.filter(row => row.split === split);
  const lowerKeys = ["mae", "rmse", "smape", "mase"];
  const best = Object.fromEntries(lowerKeys.map(key => [key, Math.min(...metrics.map(row => row[key]))]));
  best.directional_accuracy = Math.max(...metrics.map(row => row.directional_accuracy));
  document.getElementById("metricsBody").innerHTML = metrics.map(row => {
    const cell = (key, value, suffix = "", displayValue = value) => `<td class="${Math.abs(value - best[key]) < 1e-9 ? "best-metric" : ""}">${formatNumber(displayValue, key === "directional_accuracy" ? 2 : 3)}${suffix}</td>`;
    return `<tr><td>${row.model_label}</td>${cell("mae", row.mae)}${cell("rmse", row.rmse)}${cell("smape", row.smape, "%")}${cell("mase", row.mase)}${cell("directional_accuracy", row.directional_accuracy, "%", row.directional_accuracy * 100)}</tr>`;
  }).join("");
}

function renderAnfisCards() {
  const labels = Object.fromEntries(state.history.series.map(item => [item.id, item.label]));
  Object.assign(labels, {
    transit_budget: "Финансирование транспорта",
    road_condition: "Состояние дорог",
    crossings: "Регулируемые переходы",
    accidents: "Лаг ДТП",
    regularity: "Лаг регулярности",
    avg_speed: "Средняя скорость",
    accessibility: "Лаг доступности",
  });
  document.getElementById("anfisCards").innerHTML = state.metadata.anfis.map(model => `
    <article class="panel model-card">
      <span class="panel-kicker">ANFIS · ${model.rule_count} правил</span>
      <h3>${model.target_label}</h3>
      <ul>
        ${model.inputs.map(input => `<li><span>Вход</span><strong>${labels[input] || input}</strong></li>`).join("")}
        <li><span>σ</span><strong>${formatNumber(model.sigma, 2)}</strong></li>
        <li><span>Validation RMSE</span><strong>${formatNumber(model.validation_rmse, 3)}</strong></li>
      </ul>
    </article>`).join("");
}

async function renderFcm() {
  const mode = document.getElementById("fcmMode").value;
  state.graph = await api(`/api/fcm?mode=${mode}`);
  const elements = [
    ...state.graph.nodes.map(node => ({ data: node })),
    ...state.graph.edges.map(edge => ({ data: edge })),
  ];
  if (state.cy) state.cy.destroy();
  state.cy = cytoscape({
    container: document.getElementById("fcmGraph"),
    elements,
    style: [
      { selector: "node", style: { "label": "data(label)", "text-wrap": "wrap", "text-max-width": 120, "font-size": 10, "font-weight": 700, "color": colors.ink, "background-color": "#d8e8e4", "border-color": "#fff", "border-width": 3, "width": 66, "height": 66, "text-valign": "center", "text-halign": "center" } },
      { selector: 'node[kind = "controllable"]', style: { "background-color": "#b9dfd8" } },
      { selector: 'node[kind = "external"]', style: { "background-color": "#f1d9a8" } },
      { selector: 'node[kind = "target"]', style: { "background-color": "#f0aa98", "width": 82, "height": 82 } },
      { selector: "edge", style: { "curve-style": "bezier", "target-arrow-shape": "triangle", "width": "mapData(weight, -1, 1, 1, 5)", "line-color": colors.teal, "target-arrow-color": colors.teal, "opacity": .72 } },
      { selector: 'edge[sign = "negative"]', style: { "line-color": colors.coral, "target-arrow-color": colors.coral, "line-style": "dashed" } },
      { selector: ":selected", style: { "border-color": colors.ink, "border-width": 5, "opacity": 1 } },
    ],
    layout: { name: "cose", animate: false, randomize: true, nodeRepulsion: 7600, idealEdgeLength: 115, edgeElasticity: 80, gravity: .6, numIter: 1000 },
    minZoom: .45,
    maxZoom: 2.2,
  });
  state.cy.on("tap", "edge", event => renderEdgeInspector(event.target.data()));
}

function renderEdgeInspector(edge) {
  const nodeLabels = Object.fromEntries(state.graph.nodes.map(node => [node.id, node.label]));
  const weights = [
    ["Эксперт", edge.expert_weight],
    ["Из данных", edge.data_weight],
    ["Адаптированный", edge.adapted_weight],
  ];
  document.getElementById("edgeInspector").innerHTML = `
    <span class="panel-kicker">Инспектор связи</span>
    <h3>${nodeLabels[edge.source]} → ${nodeLabels[edge.target]}</h3>
    <p>${edge.sign === "positive" ? "Положительное влияние: рост источника усиливает целевой фактор." : "Отрицательное влияние: рост источника ослабляет целевой фактор."}</p>
    <div class="weight-stack">${weights.map(([label, value]) => `
      <div class="weight-line"><div><span>${label}</span><strong>${value > 0 ? "+" : ""}${formatNumber(value, 3)}</strong></div>
      <div class="weight-track"><div class="weight-fill" style="width:${Math.max(5, Math.abs(value) * 100)}%;background:${value >= 0 ? "#72d4ca" : "#f08f79"}"></div></div></div>`).join("")}</div>`;
}

function renderScenarioControls() {
  fillSelect(document.getElementById("scenarioPreset"), state.metadata.scenarios);
  const adjustable = state.metadata.nodes.filter(node => node.kind !== "target");
  document.getElementById("scenarioSliders").innerHTML = adjustable.map(node => `
    <div class="slider-item">
      <div class="slider-meta"><span>${node.label}</span><span id="value-${node.id}" class="slider-value">0.00</span></div>
      <input type="range" min="-0.20" max="0.20" step="0.01" value="0" data-node="${node.id}" aria-label="${node.label}">
    </div>`).join("");
  document.querySelectorAll("#scenarioSliders input").forEach(input => {
    input.addEventListener("input", () => { document.getElementById(`value-${input.dataset.node}`).textContent = Number(input.value).toFixed(2); });
  });
  updateScenarioDescription();
}

function updateScenarioDescription() {
  const scenario = state.metadata.scenarios.find(item => item.id === document.getElementById("scenarioPreset").value);
  document.getElementById("scenarioDescription").textContent = scenario.description;
}

function resetSliders() {
  document.querySelectorAll("#scenarioSliders input").forEach(input => {
    input.value = 0;
    input.dispatchEvent(new Event("input"));
  });
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
  button.disabled = true;
  button.textContent = "Расчёт…";
  const impulses = {};
  document.querySelectorAll("#scenarioSliders input").forEach(input => {
    const value = Number(input.value);
    if (Math.abs(value) > .0001) impulses[input.dataset.node] = value;
  });
  try {
    const result = await api("/api/simulate", {
      method: "POST",
      body: JSON.stringify({
        scenario: document.getElementById("scenarioPreset").value,
        mode: document.getElementById("scenarioMode").value,
        horizon: Number(document.getElementById("scenarioHorizon").value),
        impulses,
      }),
    });
    plotScenario("safetyPlot", result.baseline, result.scenario_result, "safety_index", "индекс", "accidents");
    plotScenario("regularityPlot", result.baseline, result.scenario_result, "regularity", "%");
    plotScenario("accessibilityPlot", result.baseline, result.scenario_result, "accessibility", "баллы");
    document.getElementById("scenarioResultTitle").textContent = result.scenario.label;
    document.getElementById("scenarioExplanation").innerHTML = result.explanation.map(item => `<li>${item}</li>`).join("");
    document.getElementById("appliedImpulses").innerHTML = result.applied_impulses.length
      ? result.applied_impulses.map(item => `<span class="tag">${item.label}: ${item.value > 0 ? "+" : ""}${item.value.toFixed(2)}</span>`).join("")
      : '<span class="tag">Без внешних импульсов</span>';
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Рассчитать сценарий";
  }
}

function renderSensitivity() {
  const targetId = document.getElementById("sensitivityTarget").value;
  const items = state.evaluation.sensitivity[targetId].slice(0, 10).reverse();
  Plotly.react("sensitivityPlot", [{
    x: items.map(item => item.delta_index_points),
    y: items.map(item => item.label),
    type: "bar",
    orientation: "h",
    marker: { color: items.map(item => item.delta_index_points >= 0 ? colors.teal : colors.coral) },
    customdata: items.map(item => item.delta_raw),
    hovertemplate: "%{y}<br>Индекс: %{x:+.3f} п.п.<br>Сырая шкала: %{customdata:+.3f}<extra></extra>",
  }], { ...baseLayout, showlegend: false, margin: { l: 220, r: 28, t: 12, b: 48 }, xaxis: { ...baseLayout.xaxis, title: "Изменение целевого индекса, п.п." } }, plotConfig);
}

function bindEvents() {
  document.getElementById("historyMetric").addEventListener("change", renderHistory);
  document.getElementById("evaluationTarget").addEventListener("change", renderEvaluation);
  document.getElementById("evaluationSplit").addEventListener("change", renderEvaluation);
  document.getElementById("fcmMode").addEventListener("change", () => renderFcm().catch(error => showToast(error.message, true)));
  document.getElementById("scenarioPreset").addEventListener("change", updateScenarioDescription);
  document.getElementById("resetSliders").addEventListener("click", resetSliders);
  document.getElementById("runScenario").addEventListener("click", runScenario);
  document.getElementById("sensitivityTarget").addEventListener("change", renderSensitivity);
}

async function initialize() {
  const status = document.getElementById("apiStatus");
  try {
    const [health, metadata, history, evaluation] = await Promise.all([
      api("/api/health"), api("/api/metadata"), api("/api/history"), api("/api/evaluation"),
    ]);
    state.metadata = metadata;
    state.history = history;
    state.evaluation = evaluation;
    status.className = "status-pill ready";
    status.innerHTML = `<span></span>Готово · ${health.periods} кварталов`;

    renderOverview();
    fillSelect(document.getElementById("historyMetric"), state.history.series);
    document.getElementById("historyMetric").value = "accidents";
    fillSelect(document.getElementById("evaluationTarget"), state.evaluation.targets);
    fillSelect(document.getElementById("sensitivityTarget"), state.evaluation.targets);
    renderHistory();
    renderEvaluation();
    renderAnfisCards();
    renderScenarioControls();
    renderSensitivity();
    bindEvents();
    await renderFcm();
    await runScenario();
  } catch (error) {
    status.className = "status-pill error";
    status.innerHTML = "<span></span>Ошибка запуска";
    showToast(`Не удалось запустить интерфейс: ${error.message}`, true);
    console.error(error);
  }
}

window.addEventListener("DOMContentLoaded", initialize);

