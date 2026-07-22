const state = {
  metadata: null,
  history: null,
  evaluation: null,
  indices: null,
  analysis: null,
  datasets: null,
  datasetDetail: null,
  modelStatus: null,
  scenarios: [],
  baseImpulses: {},
  baseIndexValues: {},
  graph: null,
  cy: null,
  budgetAnalysis: null,
  improvementRecommendations: null,
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

const customerGuide = [
  {
    id: "scenarios", index: "01", title: "Лаборатория решений",
    explanation: "Выберите проблемную цель, получите пять мер, задайте воздействия и сравните ожидаемый эффект с инерционным вариантом.",
  },
  {
    id: "overview", index: "02", title: "Текущее состояние",
    explanation: "Краткая управленческая сводка последнего доступного периода: где транспортная система находится сейчас и какие значения используются как точка отсчёта.",
  },
  {
    id: "datasets", index: "03", title: "Данные для расчёта",
    explanation: "Показывает активный XLSX. Пользователь может выбрать файл, проверить квартал, исправить 31 показатель или добавить новую строку.",
  },
];

const technicalGuide = [
  {
    id: "sensitivity", index: "A1", title: "Чувствительность",
    explanation: "Ранжирует направления по силе влияния на выбранную цель.",
  },
  {
    id: "history", index: "A2", title: "Динамика target и показателей",
    explanation: "Показывает устойчивость изменений во времени, сезонные колебания и периоды улучшения или ухудшения — чтобы не принять единичный всплеск за долгосрочный тренд.",
  },
  {
    id: "indices", index: "A3", title: "Сводные индексы",
    explanation: "Собирает множество разрозненных показателей в понятные оценки от 0 до 100 и показывает, из каких направлений складывается общая ситуация.",
  },
  {
    id: "models", index: "A4", title: "Проверка моделей",
    explanation: "Показывает, насколько прогнозы совпадали с уже известными данными. Заказчик видит, на какой метод можно опираться и где сохраняется неопределённость.",
  },
  {
    id: "map", index: "A5", title: "Карта связей FCM",
    explanation: "Объясняет, какие решения и городские факторы связаны с безопасностью, регулярностью и доступностью. Карта помогает проследить логику уже полученного сценарного результата.",
  },
  {
    id: "analysis", index: "A6", title: "Boxplot и функции принадлежности",
    explanation: "Показывает исходную проверку данных: типичные диапазоны, выбросы, нечёткие границы оценок и веса итогового индекса. Это делает расчёт из Pipeline.ipynb наглядным для заказчика.",
  },
];

const sectionGuide = [...customerGuide, ...technicalGuide];

function resizeSectionVisuals(section) {
  const resize = () => {
    section.querySelectorAll(".js-plotly-plot").forEach(plot => window.Plotly?.Plots?.resize(plot));
    if ((section.id === "map" || section.querySelector("#map")) && state.cy) {
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
  toggle.querySelector(".accordion-action").textContent = expanded ? "Свернуть графики" : "Развернуть графики";
  if (expanded) resizeSectionVisuals(section);
}

function initializePageStructure() {
  const main = document.querySelector("main.shell");
  const appendix = document.getElementById("technicalAppendix");
  const appendixContent = document.getElementById("technicalAppendixContent");
  customerGuide.forEach(item => main.insertBefore(document.getElementById(item.id), appendix));
  technicalGuide.forEach(item => appendixContent.appendChild(document.getElementById(item.id)));

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

  });

  appendix.querySelector(":scope > .accordion-toggle").addEventListener("click", event => {
    const toggle = event.currentTarget;
    setAccordionExpanded(appendix, toggle.getAttribute("aria-expanded") !== "true");
  });

  document.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener("click", () => {
    const target = document.getElementById(link.getAttribute("href").slice(1));
    if (target && (target === appendix || appendix.contains(target))) setAccordionExpanded(appendix, true);
  }));
  if (window.location.hash) {
    const target = document.getElementById(window.location.hash.slice(1));
    if (target && (target === appendix || appendix.contains(target))) setAccordionExpanded(appendix, true);
  }
}

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData) && !(options.body instanceof Blob)) headers["Content-Type"] = "application/json";
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
    `<div class="proxy-item"><strong>${escapeHtml(proxy.label || ({ digital_mobility: "Цифровая мобильность" }[proxy.id]) || proxy.id)}</strong><span>${escapeHtml(proxy.description)}</span></div>`).join("");
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
    <article class="panel expert-index-card"><div><span class="panel-kicker">8 нечётких индексов</span><small>Итоговая линейная свёртка Pipeline</small></div><strong>${formatNumber(latestHierarchical)}</strong></article>`;
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
    { x: state.indices.periods, y: state.indices.hierarchical, name: "Pipeline · итоговый индекс", type: "scatter", mode: "lines", line: { color: colors.coral, width: 2, dash: "solid" } },
  ], { ...baseLayout, margin: { l: 50, r: 16, t: 24, b: 46 }, yaxis: { ...baseLayout.yaxis, range: [0, 100], title: "баллы" } }, plotConfig);
}

function membershipValue(x, term) {
  const p = term.params;
  if (term.type === "trapmf") {
    const [a, b, c, d] = p;
    if (x <= a || x >= d) return 0;
    if (x >= b && x <= c) return 1;
    return x < b ? (b === a ? 1 : (x - a) / (b - a)) : (d === c ? 1 : (d - x) / (d - c));
  }
  const [a, b, c] = p;
  if (x <= a || x >= c) return 0;
  if (x === b) return 1;
  return x < b ? (b === a ? 1 : (x - a) / (b - a)) : (c === b ? 1 : (c - x) / (c - b));
}

function membershipTraces(variable) {
  const [minimum, maximum] = variable.universe;
  const x = Array.from({ length: 201 }, (_, index) => minimum + (maximum - minimum) * index / 200);
  return variable.terms.map((term, index) => ({
    x, y: x.map(value => membershipValue(value, term)), name: term.name,
    type: "scatter", mode: "lines", line: { width: 2.5, color: [colors.teal, colors.coral, colors.gold, colors.blue, colors.bright, colors.ink][index % 6] },
    hovertemplate: "%{x:.2f}<br>принадлежность %{y:.2f}<extra>" + escapeHtml(term.name) + "</extra>",
  }));
}

function renderBoxplots() {
  const group = document.getElementById("boxplotGroup").value;
  const items = state.analysis.boxplots.filter(item => item.group === group);
  const traces = items.map((item, index) => ({
    y: item.values, text: state.analysis.periods, name: item.label,
    type: "box", boxpoints: "outliers", jitter: .2, pointpos: 0,
    marker: { color: [colors.teal, colors.coral, colors.gold, colors.blue, colors.bright][index % 5], size: 6 },
    line: { width: 1.7 }, hovertemplate: "%{text}<br><b>%{y:.2f}</b><extra>" + escapeHtml(item.label) + "</extra>",
  }));
  Plotly.react("boxplotPlot", traces, {
    ...baseLayout, margin: { l: 58, r: 18, t: 20, b: 105 }, showlegend: false,
    xaxis: { ...baseLayout.xaxis, tickangle: -25, automargin: true },
    yaxis: { ...baseLayout.yaxis, title: "исходные значения" },
  }, plotConfig);
  const outliers = items.flatMap(item => item.outliers.map(value => ({ ...value, label: item.label })));
  document.getElementById("outlierSummary").innerHTML = outliers.length
    ? `<strong>Нетипичные наблюдения: ${outliers.length}.</strong> ${outliers.slice(0, 5).map(item => `${escapeHtml(item.label)} — ${escapeHtml(item.period)} (${formatNumber(item.value, 2)})`).join("; ")}${outliers.length > 5 ? "…" : ""}`
    : "<strong>Выбросов по правилу 1,5 IQR не найдено.</strong> Значения этой группы находятся внутри статистически ожидаемого диапазона.";
}

function renderMembershipVariableOptions() {
  const selected = state.analysis.memberships.find(item => item.id === document.getElementById("membershipIndex").value);
  fillSelect(document.getElementById("membershipVariable"), selected.variables);
  renderMembershipPlot();
}

function renderMembershipPlot() {
  const selected = state.analysis.memberships.find(item => item.id === document.getElementById("membershipIndex").value);
  const variable = selected.variables.find(item => item.id === document.getElementById("membershipVariable").value);
  const quantileColors = [colors.muted, colors.gold, colors.muted];
  const shapes = (variable.quantiles || []).map((value, index) => ({
    type: "line", x0: value, x1: value, y0: 0, y1: 1,
    line: { color: quantileColors[index], width: index === 1 ? 2 : 1, dash: "dash" },
  }));
  const annotations = (variable.quantiles || []).map((value, index) => ({
    x: value, y: 1.02, text: ["Q1", "Медиана", "Q3"][index], showarrow: false,
    font: { size: 10, color: quantileColors[index] }, yanchor: "bottom",
  }));
  Plotly.react("membershipPlot", membershipTraces(variable), {
    ...baseLayout, margin: { l: 55, r: 18, t: 24, b: 52 },
    xaxis: { ...baseLayout.xaxis, title: variable.label },
    yaxis: { ...baseLayout.yaxis, title: "степень принадлежности", range: [0, 1.05] },
    shapes, annotations,
  }, plotConfig);
}

function renderAnalysis() {
  const analysis = state.analysis;
  document.getElementById("pipelineStats").innerHTML = [
    ["Строк в источнике", analysis.source_rows],
    ["После очистки", analysis.processed_rows],
    ["Исключено выбросов", analysis.excluded_outliers.length],
    ["Нечётких индексов", analysis.memberships.length],
    ["Правил из JSON", analysis.applied_rules],
  ].map(([label, value]) => `<article class="analysis-stat-card"><span>${label}</span><strong>${value}</strong></article>`).join("");

  const groups = [...new Set(analysis.boxplots.map(item => item.group))].map(group => ({ id: group, label: group }));
  fillSelect(document.getElementById("boxplotGroup"), groups);
  fillSelect(document.getElementById("membershipIndex"), analysis.memberships);
  renderBoxplots();
  renderMembershipVariableOptions();

  const reference = analysis.reference_memberships;
  document.getElementById("membershipReferenceNote").textContent = reference.note;
  Plotly.react("membershipReferencePlot", membershipTraces({ universe: reference.universe, terms: reference.terms }), {
    ...baseLayout, height: 260, margin: { l: 46, r: 12, t: 24, b: 40 },
    xaxis: { ...baseLayout.xaxis, title: "нормированная шкала" },
    yaxis: { ...baseLayout.yaxis, range: [0, 1.05], title: "принадлежность" },
  }, plotConfig);

  Plotly.react("pipelineWeightsPlot", [{
    x: analysis.linear_weights.map(item => item.weight * 100),
    y: analysis.linear_weights.map(item => item.label),
    type: "bar", orientation: "h", marker: { color: colors.teal },
    text: analysis.linear_weights.map(item => `${formatNumber(item.weight * 100, 1)}%`), textposition: "outside",
    hovertemplate: "%{y}<br><b>%{x:.1f}%</b><extra></extra>",
  }], {
    ...baseLayout, height: 300, showlegend: false, margin: { l: 175, r: 48, t: 14, b: 38 },
    xaxis: { ...baseLayout.xaxis, title: "вес в итоговом индексе, %" },
    yaxis: { ...baseLayout.yaxis, autorange: "reversed", automargin: true },
  }, plotConfig);
}

function renderDatasetCatalog() {
  const select = document.getElementById("datasetSelect");
  const selected = select.value || state.datasets.active;
  select.innerHTML = state.datasets.datasets.map(item =>
    `<option value="${escapeHtml(item.name)}">${item.active ? "● " : ""}${escapeHtml(item.name)} · ${item.rows} строк</option>`).join("");
  select.value = state.datasets.datasets.some(item => item.name === selected) ? selected : state.datasets.active;
}

function datasetRowValues() {
  const values = {};
  document.querySelectorAll("#datasetFields input[data-feature]").forEach(input => {
    values[input.dataset.feature] = Number(input.value);
  });
  return values;
}

function populateDatasetRow(period) {
  const isNew = period === "__new__";
  const row = isNew
    ? state.datasetDetail.rows_data.at(-1)
    : state.datasetDetail.rows_data.find(item => item.period === period);
  document.querySelectorAll("#datasetFields input[data-feature]").forEach(input => {
    input.value = row?.values[input.dataset.feature] ?? 0;
  });
  const next = state.datasetDetail.next_period;
  document.getElementById("datasetEditorHint").textContent = isNew
    ? `Будет добавлен квартал ${next}. Для удобства скопированы прошлые значения — замените их фактическими данными.`
    : `Редактируется квартал ${period}. Сохранение проходит полную проверку Pipeline до замены XLSX.`;
}

function renderTrainingStatus() {
  if (!state.modelStatus) return;
  const card = document.querySelector(".retraining-card");
  const button = document.getElementById("retrainModels");
  card.classList.toggle("pending", state.modelStatus.pending_retrain);
  card.classList.toggle("ready", !state.modelStatus.pending_retrain);
  document.getElementById("modelTrainingStatus").textContent = state.modelStatus.pending_retrain
    ? `Новые данные сохранены, но рекомендации пока используют период по ${state.modelStatus.trained_through}. Нажмите переобучение.`
    : `Модель актуальна по ${state.modelStatus.trained_through}: ${state.modelStatus.source_rows} кварталов, ${state.modelStatus.models} рабочих ANFIS-модели.`;
  button.textContent = state.modelStatus.pending_retrain ? "Переобучить на новых данных" : "Переобучить заново";
}

function renderDatasetDetail() {
  const detail = state.datasetDetail;
  const dataset = state.datasets.datasets.find(item => item.name === detail.name);
  document.getElementById("datasetSummary").innerHTML = `<strong>${dataset?.active ? "Активный источник расчёта" : "Файл открыт только для просмотра"}</strong>
    <span>${detail.rows} строк · ${escapeHtml(detail.first_period)}–${escapeHtml(detail.last_period)}</span>
    <small>${dataset?.active ? "Все графики и рекомендации рассчитаны по этому файлу." : "Нажмите «Использовать для расчёта», чтобы переключить модель."}</small>`;

  const groups = [];
  detail.columns.forEach(column => {
    let group = groups.find(item => item.name === column.group);
    if (!group) { group = { name: column.group, columns: [] }; groups.push(group); }
    group.columns.push(column);
  });
  const readonly = "";
  document.getElementById("datasetFields").innerHTML = groups.map(group => `<fieldset>
    <legend>${escapeHtml(group.name)}</legend><div>${group.columns.map(column => `<label>${escapeHtml(column.label)}
      <input type="number" step="any" min="0" data-feature="${escapeHtml(column.id)}" ${readonly}></label>`).join("")}</div></fieldset>`).join("");

  const rowSelect = document.getElementById("datasetRowSelect");
  rowSelect.innerHTML = detail.rows_data.map(row => `<option value="${escapeHtml(row.period)}">${escapeHtml(row.period)}</option>`).join("")
    + `<option value="__new__">${escapeHtml(detail.next_period)} · новая строка</option>`;
  rowSelect.value = detail.rows_data.at(-1).period;
  populateDatasetRow(rowSelect.value);

  const previewIds = [
    "бюджет_дворы_pct", "дороги_норматив_pct_A", "рейсы_расписание_pct_B",
    "скорость_магистрали_B_кмч", "дтп_10тыс_B", "дороги_норматив_pct_C",
  ];
  const previewColumns = previewIds.map(id => detail.columns.find(column => column.id === id)).filter(Boolean);
  document.getElementById("datasetPreviewHead").innerHTML = `<tr><th>Квартал</th>${previewColumns.map(column => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr>`;
  document.getElementById("datasetPreviewBody").innerHTML = detail.rows_data.slice(-5).map(row => `<tr><td><strong>${escapeHtml(row.period)}</strong></td>${previewColumns.map(column => `<td>${formatNumber(row.values[column.id], 2)}</td>`).join("")}</tr>`).join("");
}

async function loadDatasetDetail(name) {
  state.datasetDetail = await api(`/api/datasets/${encodeURIComponent(name)}`);
  renderDatasetDetail();
}

async function uploadDataset() {
  const input = document.getElementById("datasetFile");
  const button = document.getElementById("uploadDataset");
  const file = input.files[0];
  if (!file) { showToast("Выберите XLSX-файл", true); return; }
  if (!file.name.toLowerCase().endsWith(".xlsx")) { showToast("Можно загрузить только XLSX-файл", true); return; }
  if (file.size > 20 * 1024 * 1024) { showToast("XLSX-файл превышает 20 МБ", true); return; }
  button.disabled = true; button.textContent = "Проверка и пересчёт…";
  try {
    await api(`/api/datasets/upload?name=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
      body: file,
    });
    input.value = "";
    showToast(`Файл ${file.name} загружен. Индексы и транспортная доступность пересчитаны.`);
    await initializeApplication();
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Загрузить XLSX и пересчитать"; }
}

async function activateDataset() {
  const button = document.getElementById("activateDataset");
  button.disabled = true; button.textContent = "Пересчёт…";
  try {
    const name = document.getElementById("datasetSelect").value;
    await api("/api/datasets/select", { method: "POST", body: JSON.stringify({ name }) });
    showToast(`Датасет ${name} выбран. Все разделы пересчитаны.`);
    await initializeApplication();
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Использовать для расчёта"; }
}

async function saveDatasetRow() {
  const button = document.getElementById("saveDatasetRow");
  const name = document.getElementById("datasetSelect").value;
  const period = document.getElementById("datasetRowSelect").value;
  const isNew = period === "__new__";
  button.disabled = true; button.textContent = "Проверка Pipeline…";
  try {
    const path = isNew
      ? `/api/datasets/${encodeURIComponent(name)}/rows`
      : `/api/datasets/${encodeURIComponent(name)}/rows/${encodeURIComponent(period)}`;
    const result = await api(path, { method: isNew ? "POST" : "PUT", body: JSON.stringify({ values: datasetRowValues() }) });
    state.datasetDetail = result.dataset;
    state.modelStatus = result.model_status;
    state.datasets = await api("/api/datasets");
    renderDatasetCatalog();
    renderDatasetDetail();
    renderTrainingStatus();
    showToast(result.active === name
      ? `${isNew ? "Добавлен" : "Обновлён"} квартал ${result.period}. Теперь переобучите модель.`
      : `${isNew ? "Добавлен" : "Обновлён"} квартал ${result.period} в резервном файле.`);
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Сохранить данные"; }
}

async function retrainModels() {
  const button = document.getElementById("retrainModels");
  button.disabled = true; button.textContent = "Переобучение…";
  try {
    state.modelStatus = await api("/api/models/retrain", { method: "POST" });
    showToast(`Модель обновлена по ${state.modelStatus.trained_through}. Рекомендации пересчитаны.`);
    await initializeApplication();
  } catch (error) {
    showToast(error.message, true);
    renderTrainingStatus();
  } finally {
    button.disabled = false;
    renderTrainingStatus();
  }
}

function selectedEvaluation() {
  return state.evaluation.targets.find(target => target.id === document.getElementById("evaluationTarget").value);
}

function renderModelGuide() {
  document.getElementById("modelGuide").innerHTML = state.evaluation.model_catalog.map(model => `
    <article class="model-guide-card">
      <span class="model-role">${escapeHtml(model.role)}</span>
      <h4>${escapeHtml(model.label)}</h4>
      <dl>
        <div><dt>Как считает</dt><dd>${escapeHtml(model.how)}</dd></div>
        <div><dt>Что использует</dt><dd>${escapeHtml(model.inputs)}</dd></div>
        <div><dt>Зачем сравниваем</dt><dd>${escapeHtml(model.purpose)}</dd></div>
      </dl>
    </article>`).join("");
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
  const catalog = Object.fromEntries(state.evaluation.model_catalog.map(model => [model.id, model]));
  document.getElementById("metricsBody").innerHTML = metrics.map(row => {
    const model = catalog[row.model];
    return `<tr><td><strong>${escapeHtml(row.model_label)}</strong><small class="model-table-role">${escapeHtml(model.role)}</small></td><td>${formatNumber(row.mae, 3)}</td><td class="${row.rmse === bestRmse ? "best-metric" : ""}">${formatNumber(row.rmse, 3)}</td><td>${formatNumber(row.smape, 2)}%</td><td>${formatNumber(row.mase, 3)}</td><td>${formatNumber(row.directional_accuracy * 100, 1)}%</td></tr>`;
  }).join("");
}

function renderNotebookPlots() {
  const targetSeries = state.history.series.find(item => item.id === "pipeline_target");
  Plotly.react("notebookTargetPlot", [{
    x: state.history.periods, y: targetSeries.values, name: "target", type: "scatter", mode: "lines+markers",
    line: { color: colors.blue, width: 2 }, marker: { size: 5 },
    hovertemplate: "%{x}<br>target: %{y:.3f}<extra></extra>",
  }], {
    ...baseLayout, showlegend: true, margin: { l: 52, r: 18, t: 26, b: 58 },
    xaxis: { ...baseLayout.xaxis, title: "Период", tickangle: -45 },
    yaxis: { ...baseLayout.yaxis, title: "Значение target" },
  }, plotConfig);

  const target = state.evaluation.targets.find(item => item.id === "pipeline_target");
  const validation = target.predictions.validation;
  Plotly.react("notebookValidationPlot", [
    { x: validation.map(row => row.period), y: validation.map(row => row.actual), name: "Факт (target, норм.)", type: "scatter", mode: "lines+markers", line: { color: colors.ink, width: 2 } },
    { x: validation.map(row => row.period), y: validation.map(row => row.anfis), name: "Прогноз ANFIS", type: "scatter", mode: "lines+markers", line: { color: colors.teal, width: 2, dash: "dash" } },
  ], {
    ...baseLayout, margin: { l: 52, r: 18, t: 26, b: 54 },
    xaxis: { ...baseLayout.xaxis, title: "Validation 2019–2022", tickangle: -45 },
    yaxis: { ...baseLayout.yaxis, title: "target (норм.)" },
  }, plotConfig);

  const test = target.predictions.test;
  const modelStyles = {
    seasonal_naive: { color: colors.muted, dash: "dot" },
    ridge: { color: colors.blue, dash: "dash" },
    anfis: { color: colors.teal, dash: "solid" },
  };
  const testTraces = [{
    x: test.map(row => row.period), y: test.map(row => row.actual), name: "Target (норм.)",
    type: "scatter", mode: "lines+markers", line: { color: colors.ink, width: 3 },
  }];
  Object.entries(state.evaluation.model_labels).forEach(([model, label]) => testTraces.push({
    x: test.map(row => row.period), y: test.map(row => row[model]), name: label,
    type: "scatter", mode: "lines+markers", line: { ...modelStyles[model], width: 2 },
  }));
  Plotly.react("notebookTestPlot", testTraces, {
    ...baseLayout, margin: { l: 52, r: 18, t: 26, b: 54 },
    xaxis: { ...baseLayout.xaxis, title: "Test 2023–2025", tickangle: -45 },
    yaxis: { ...baseLayout.yaxis, title: "target (норм.)" },
  }, plotConfig);
}

function renderAnfisCards() {
  const labels = Object.fromEntries(state.metadata.targets.map(target => [target.id, target.label]));
  document.getElementById("anfisCards").innerHTML = state.metadata.anfis.map(model => `
    <article class="panel model-card"><span class="panel-kicker">ANFIS · ${model.rule_count} правил</span><h3>${labels[model.target]}</h3><ul>
      <li><span>Входы</span><strong>${model.inputs.length}</strong></li><li><span>σ</span><strong>${formatNumber(model.sigma, 2)}</strong></li>
      <li><span>Эпохи</span><strong>${model.epochs}</strong></li><li><span>Validation RMSE</span><strong>${formatNumber(model.validation_rmse, 4)}</strong></li>
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

function scenarioReference(scenario) { return scenario.id; }
function scenarioByReference(reference) { return state.scenarios.find(item => scenarioReference(item) === reference); }

function fillScenarioSelect(select) {
  select.innerHTML = "";
  state.scenarios.forEach(item => {
    const option = document.createElement("option");
    option.value = scenarioReference(item);
    option.textContent = `${item.builtin ? "" : "★ "}${item.label}`;
    select.appendChild(option);
  });
}

const indexControls = [
  ["urban_environment", "Индекс качества современной городской среды"],
  ["road_quality_dtc", "Индекс качества ДТК"],
  ["accessible_environment", "Индекс удовлетворённости доступной среды"],
  ["public_spaces", "Индекс качества общественного благоустройства"],
  ["road_quality_transit", "Индекс качества ГОТ"],
  ["parking_safety", "Индекс качества парковок и безопасности движения"],
];

let indexRecalculationTimer = null;

function indexValuesFromControls() {
  return Object.fromEntries([...document.querySelectorAll("#scenarioSliders input[data-index]")]
    .map(input => [input.dataset.index, Number(input.value)]));
}

function renderScenarioControls(selectedReference = null) {
  const select = document.getElementById("scenarioPreset");
  fillScenarioSelect(select);
  if (!selectedReference && state.scenarios.some(item => item.id === "inertial")) select.value = "inertial";
  if (selectedReference && state.scenarios.some(item => scenarioReference(item) === selectedReference)) select.value = selectedReference;
  state.baseIndexValues = Object.fromEntries(indexControls.map(([id]) => {
    const item = state.indices.fuzzy.find(index => index.id === id);
    return [id, Number(item.values.at(-1))];
  }));
  const renderSlider = ([id, label]) => {
    const value = state.baseIndexValues[id];
    return `<div class="slider-item"><div class="slider-meta"><span>${escapeHtml(label)}</span><span id="value-${id}" class="slider-value">${formatNumber(value, 1)}</span></div><input type="range" min="0" max="100" step="0.1" value="${value}" data-index="${id}" aria-label="${escapeHtml(label)}: от 0 до 100"></div>`;
  };
  document.getElementById("scenarioSliders").innerHTML = indexControls.map(renderSlider).join("");
  document.querySelectorAll("#scenarioSliders input[data-index]").forEach(input => input.addEventListener("input", () => {
    document.getElementById(`value-${input.dataset.index}`).textContent = formatNumber(Number(input.value), 1);
    clearTimeout(indexRecalculationTimer);
    indexRecalculationTimer = setTimeout(() => runScenario(), 250);
  }));
  applySelectedScenario();
}

function applySelectedScenario() {
  const scenario = scenarioByReference(document.getElementById("scenarioPreset").value);
  if (!scenario) return;
  document.getElementById("scenarioDescription").textContent = scenario.description;
  document.getElementById("scenarioMode").value = scenario.mode;
  const horizon = document.getElementById("scenarioHorizon");
  if (![...horizon.options].some(option => Number(option.value) === Number(scenario.horizon))) {
    const option = document.createElement("option"); option.value = scenario.horizon; option.textContent = `${scenario.horizon} кварталов`; horizon.appendChild(option);
  }
  horizon.value = scenario.horizon;
  state.baseImpulses = { ...scenario.impulses };
  document.querySelectorAll("#scenarioSliders input[data-node]").forEach(input => {
    input.value = state.baseImpulses[input.dataset.node] || 0;
    input.dispatchEvent(new Event("input"));
  });
  document.querySelectorAll("#scenarioSliders input[data-index]").forEach(input => {
    input.value = scenario.index_values?.[input.dataset.index] ?? state.baseIndexValues[input.dataset.index];
    document.getElementById(`value-${input.dataset.index}`).textContent = formatNumber(Number(input.value), 1);
  });
}

function resetSliders() {
  document.querySelectorAll("#scenarioSliders input[data-index]").forEach(input => {
    input.value = state.baseIndexValues[input.dataset.index];
    document.getElementById(`value-${input.dataset.index}`).textContent = formatNumber(Number(input.value), 1);
  });
  runScenario();
}

function scenarioImpulsesFromControls() {
  const impulses = {};
  document.querySelectorAll("#scenarioSliders input[data-node]").forEach(input => {
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
    index_values: indexValuesFromControls(),
  };
}

async function saveScenario() {
  const selected = scenarioByReference(document.getElementById("scenarioPreset").value);
  if (!selected) return;
  const nameInput = document.getElementById("scenarioSaveName");
  const timestamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const isStored = !selected.builtin;
  const label = nameInput.value.trim() || (isStored ? selected.label : `Пользовательский сценарий ${new Date().toLocaleString("ru-RU")}`);
  const payload = scenarioPayloadFromControls(selected, {
    id: isStored ? selected.id : `scenario-${timestamp}`,
    label,
    description: isStored ? selected.description : "Сценарий сохранён пользователем из лаборатории индексов.",
  });
  try {
    const saved = await api("/api/scenarios", { method: "POST", body: JSON.stringify(payload) });
    const existingIndex = state.scenarios.findIndex(item => !item.builtin && item.id === saved.id);
    if (existingIndex >= 0) state.scenarios.splice(existingIndex, 1, saved);
    else state.scenarios.push(saved);
    nameInput.value = "";
    renderScenarioControls(saved.id);
    showToast(`Сценарий «${saved.label}» сохранён в runtime/scenarios/${saved.id}.json`);
  } catch (error) { showToast(error.message, true); }
}

async function uploadScenario() {
  const input = document.getElementById("scenarioFile");
  const file = input.files[0];
  if (!file) { showToast("Выберите JSON-файл", true); return; }
  if (file.size > 65536) { showToast("JSON-файл превышает 64 КБ", true); return; }
  try {
    const payload = JSON.parse(await file.text());
    const saved = await api("/api/scenarios/validate", { method: "POST", body: JSON.stringify(payload) });
    const existingIndex = state.scenarios.findIndex(item => !item.builtin && item.id === saved.id);
    if (existingIndex >= 0) state.scenarios.splice(existingIndex, 1, saved);
    else state.scenarios.push(saved);
    renderScenarioControls(scenarioReference(saved));
    input.value = "";
    showToast(`Сценарий «${saved.label}» загружен из JSON`);
  } catch (error) { showToast(error.message, true); }
}

async function exportSelectedScenario() {
  const scenario = scenarioByReference(document.getElementById("scenarioPreset").value);
  if (!scenario) return;
  try {
    const payload = scenarioPayloadFromControls(scenario);
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

function renderImprovementRecommendations() {
  const data = state.improvementRecommendations;
  if (!data) return;
  const objectiveId = document.getElementById("customerObjective").value;
  const objective = data.objectives.find(item => item.id === objectiveId) || data.objectives[0];
  const indicator = objective.indicator;
  const status = document.getElementById("recommendationStatus");
  status.className = `recommendation-status ${indicator?.tone || "neutral"}`;
  const change = indicator?.change_percent == null ? "без сравнения" : `${signed(indicator.change_percent)}% к прошлому кварталу`;
  status.innerHTML = indicator
    ? `<strong>${escapeHtml(indicator.label)}: ${formatNumber(indicator.value, 2)} ${escapeHtml(indicator.unit)}</strong>
       <span>${escapeHtml(indicator.trend)} · ${escapeHtml(change)} · индекс ${formatNumber(objective.current, 1)}/100 · ${escapeHtml(data.period)}</span>`
    : `<strong>${escapeHtml(objective.label)}: ${formatNumber(objective.current, 2)} из 100</strong><span>${escapeHtml(objective.status)}</span>`;
  document.getElementById("recommendationList").innerHTML = objective.items.map(item => {
    const effect = item.expected_effect_points == null
      ? "Прямой показатель канонических JSON-правил"
      : `Модельный ориентир: ${signed(item.expected_effect_points, 3)} п.п. при стандартном воздействии`;
    return `<li><span class="recommendation-rank">${item.rank}</span><div><strong>${escapeHtml(item.label)}</strong>
      <p>${escapeHtml(item.action)}</p><small>${escapeHtml(item.relation)} · ${escapeHtml(effect)}</small></div>
      <button class="mini-button recommendation-action" type="button" data-factor="${escapeHtml(item.factor)}">Проверить меру</button></li>`;
  }).join("");
  document.getElementById("recommendationMethodology").textContent = data.methodology_note;
}

function applyRecommendedMeasure(factor) {
  const input = document.querySelector(`#scenarioSliders input[data-node="${factor}"]`);
  if (!input) { showToast("Для этой меры нужен прямой ввод данных в разделе квартала", true); return; }
  input.value = Math.min(1, Number(input.value) + 0.10).toFixed(2);
  input.dispatchEvent(new Event("input"));
  showToast("Мера добавлена в сценарий с умеренным воздействием +0,10");
  runScenario();
}

function syncCustomerObjective() {
  const objective = document.getElementById("customerObjective").value;
  const messages = {
    traffic_safety: "Система оценивает динамику ДТП и ранжирует меры, которые сильнее всего повышают безопасность.",
    transport_regularity: "Система ищет меры для соблюдения расписания и устойчивых интервалов движения.",
    transport_accessibility: "Система показывает, какие связанные показатели сильнее всего улучшают доступность.",
    integrated_mobility: "Система балансирует безопасность, регулярность и доступность без перекоса в одну метрику.",
  };
  document.getElementById("problemFocusHint").textContent = messages[objective];
  if (state.improvementRecommendations) renderImprovementRecommendations();
  if (state.budgetAnalysis) renderBudgetAnalysis();
  const sensitivity = document.getElementById("sensitivityTarget");
  if ([...sensitivity.options].some(option => option.value === objective)) {
    sensitivity.value = objective;
    if (state.evaluation) renderSensitivity();
  }
}

async function recalculateForCustomerObjective() {
  syncCustomerObjective();
  await runScenario();
}

function budgetMetricCell(metric) {
  return `<strong>${signed(metric.relative_change_percent)}%</strong><small>${signed(metric.delta_points)} п.</small>`;
}

function renderBudgetAnalysis() {
  if (!state.budgetAnalysis) return;
  const objectiveMap = {
    traffic_safety: "safety",
    transport_regularity: "regularity",
    transport_accessibility: "accessibility",
    integrated_mobility: "integrated_mobility",
  };
  const objective = objectiveMap[document.getElementById("customerObjective").value];
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
  const selected = scenarioByReference(document.getElementById("scenarioPreset").value);
  const impulses = {};
  if (selected?.builtin) document.querySelectorAll("#scenarioSliders input[data-node]").forEach(input => {
    const delta = Number(input.value) - Number(state.baseImpulses[input.dataset.node] || 0);
    if (Math.abs(delta) > .0001) impulses[input.dataset.node] = delta;
  });
  try {
    const result = await api("/api/simulate", { method: "POST", body: JSON.stringify({
      scenario: document.getElementById("scenarioPreset").value,
      scenario_payload: selected?.builtin ? null : scenarioPayloadFromControls(selected),
      mode: document.getElementById("scenarioMode").value,
      horizon: Number(document.getElementById("scenarioHorizon").value), impulses,
      index_values: indexValuesFromControls(),
    }) });
    await Promise.all([
      plotScenario("safetyPlot", result.baseline, result.scenario_result, "safety_index", "баллы", "accidents"),
      plotScenario("regularityPlot", result.baseline, result.scenario_result, "regularity", "%"),
      plotScenario("accessibilityPlot", result.baseline, result.scenario_result, "accessibility", "баллы"),
      plotScenario("integratedPlot", result.baseline, result.scenario_result, "integrated_mobility", "баллы"),
    ]);
    renderBusinessSummary(result);
    state.budgetAnalysis = result.budget_analysis;
    state.improvementRecommendations = result.improvement_recommendations;
    renderBudgetAnalysis();
    renderImprovementRecommendations();
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
  if (state.eventsBound) return;
  state.eventsBound = true;
  document.getElementById("historyMetric").addEventListener("change", renderHistory);
  document.getElementById("fuzzyIndexSelect").addEventListener("change", renderFuzzyIndexPlot);
  document.getElementById("evaluationTarget").addEventListener("change", renderEvaluation);
  document.getElementById("evaluationSplit").addEventListener("change", renderEvaluation);
  document.getElementById("fcmMode").addEventListener("change", () => renderFcm().catch(error => showToast(error.message, true)));
  document.getElementById("scenarioPreset").addEventListener("change", applySelectedScenario);
  document.getElementById("resetSliders").addEventListener("click", resetSliders);
  document.getElementById("uploadScenario").addEventListener("click", uploadScenario);
  document.getElementById("saveScenario").addEventListener("click", saveScenario);
  document.getElementById("exportScenario").addEventListener("click", exportSelectedScenario);
  document.getElementById("runScenario").addEventListener("click", runScenario);
  document.getElementById("customerObjective").addEventListener("change", () => {
    recalculateForCustomerObjective().catch(error => showToast(error.message, true));
  });
  document.getElementById("recommendationList").addEventListener("click", event => {
    const button = event.target.closest(".recommendation-action");
    if (button) applyRecommendedMeasure(button.dataset.factor);
  });
  document.getElementById("sensitivityTarget").addEventListener("change", renderSensitivity);
  document.getElementById("boxplotGroup").addEventListener("change", renderBoxplots);
  document.getElementById("membershipIndex").addEventListener("change", renderMembershipVariableOptions);
  document.getElementById("membershipVariable").addEventListener("change", renderMembershipPlot);
  document.getElementById("datasetSelect").addEventListener("change", event => loadDatasetDetail(event.target.value).catch(error => showToast(error.message, true)));
  document.getElementById("uploadDataset").addEventListener("click", uploadDataset);
  document.getElementById("datasetRowSelect").addEventListener("change", event => populateDatasetRow(event.target.value));
  document.getElementById("activateDataset").addEventListener("click", activateDataset);
  document.getElementById("newDatasetRow").addEventListener("click", () => {
    document.getElementById("datasetRowSelect").value = "__new__";
    populateDatasetRow("__new__");
    document.querySelector(".dataset-field-details").open = true;
  });
  document.getElementById("saveDatasetRow").addEventListener("click", saveDatasetRow);
  document.getElementById("retrainModels").addEventListener("click", retrainModels);
}

async function initializeApplication() {
  const status = document.getElementById("apiStatus");
  try {
    const [health, metadata, history, indices, evaluation, analysis, scenarios, datasets, modelStatus] = await Promise.all([
      api("/api/health"), api("/api/metadata"), api("/api/history"), api("/api/indices"), api("/api/evaluation"), api("/api/analysis"), api("/api/scenarios"), api("/api/datasets"), api("/api/models/status"),
    ]);
    Object.assign(state, { metadata, history, indices, evaluation, analysis, datasets, modelStatus, scenarios: scenarios.scenarios });
    status.className = "status-pill ready"; status.innerHTML = `<span></span>Готово · ${health.periods} кварталов`;
    renderOverview();
    renderScenarioControls(); bindEvents();
    fillSelect(document.getElementById("historyMetric"), state.history.series); document.getElementById("historyMetric").value = "pipeline_target";
    fillSelect(document.getElementById("evaluationTarget"), state.evaluation.targets);
    fillSelect(document.getElementById("sensitivityTarget"), state.evaluation.sensitivity_targets);
    renderHistory(); renderIndices(); renderModelGuide(); renderEvaluation(); renderAnfisCards(); renderSensitivity(); renderAnalysis(); renderNotebookPlots(); renderDatasetCatalog(); renderTrainingStatus(); syncCustomerObjective();
    await loadDatasetDetail(state.datasets.active);
    await renderFcm();
    await runScenario();
  } catch (error) {
    status.className = "status-pill error"; status.innerHTML = "<span></span>Ошибка запуска";
    showToast(`Не удалось запустить интерфейс: ${error.message}`, true); console.error(error);
  }
}

async function bootstrap() {
  initializePageStructure();
  await initializeApplication();
}

window.addEventListener("DOMContentLoaded", bootstrap);
