const naira = new Intl.NumberFormat("en-NG", {
  style: "currency",
  currency: "NGN",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const compactNaira = new Intl.NumberFormat("en-NG", {
  style: "currency",
  currency: "NGN",
  notation: "compact",
  maximumFractionDigits: 1,
});
const charts = {};
let selectedRestaurant = "";

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("loginForm")?.addEventListener("submit", handleLogin);
  document.getElementById("registerForm")?.addEventListener("submit", handleRegister);
  document.getElementById("dashboardContent") && initializeDashboard();
});

async function requestJson(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  const csrfToken = getCookie("csrf_access_token");
  if (method !== "GET" && csrfToken) headers.set("X-CSRF-TOKEN", csrfToken);
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Please sign in to continue.");
  }
  if (!response.ok) {
    throw new Error(data.message || `Request failed (${response.status}).`);
  }
  return data;
}

function showAuthError(message) {
  const error = document.getElementById("errorMessage");
  if (!error) return;
  error.textContent = message;
  error.hidden = false;
}

async function handleLogin(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await requestJson("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value,
      }),
    });
    window.location.assign("/dashboard");
  } catch (error) {
    showAuthError(error.message);
  } finally {
    button.disabled = false;
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await requestJson("/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: document.getElementById("regUsername").value,
        email: document.getElementById("regEmail").value,
        password: document.getElementById("regPassword").value,
      }),
    });
    window.location.assign("/login");
  } catch (error) {
    showAuthError(error.message);
  } finally {
    button.disabled = false;
  }
}

async function initializeDashboard() {
  try {
    await requestJson("/api/verify-auth");
    await loadRestaurants();
    document.getElementById("restaurantSelect").addEventListener("change", async (event) => {
      selectedRestaurant = event.target.value;
      await loadAnalysis();
    });
    document.getElementById("restaurantForm").addEventListener("submit", addRestaurant);
    document.getElementById("uploadForm").addEventListener("submit", handleFileUpload);
    document.getElementById("downloadReport").addEventListener("click", downloadReport);
    document.getElementById("exportTransactions").addEventListener("click", exportTransactions);
    document.getElementById("logoutButton").addEventListener("click", logout);
  } catch (error) {
    showDashboardMessage(error.message, "error");
  }
}

async function loadRestaurants() {
  let restaurants = await requestJson("/api/restaurants");
  if (!restaurants.length) {
    await requestJson("/api/restaurants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "My Restaurant" }),
    });
    restaurants = await requestJson("/api/restaurants");
  }

  const select = document.getElementById("restaurantSelect");
  select.replaceChildren();
  restaurants.forEach((restaurant) => {
    const option = document.createElement("option");
    option.value = restaurant.id;
    option.textContent = restaurant.name;
    select.append(option);
  });
  selectedRestaurant = restaurants[0].id;
  select.value = selectedRestaurant;
  await loadAnalysis();
}

async function addRestaurant(event) {
  event.preventDefault();
  const input = document.getElementById("restaurantName");
  try {
    const restaurant = await requestJson("/api/restaurants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: input.value }),
    });
    input.value = "";
    await loadRestaurants();
    document.getElementById("restaurantSelect").value = restaurant.id;
    selectedRestaurant = restaurant.id;
    await loadAnalysis();
    showDashboardMessage("Restaurant added.", "success");
  } catch (error) {
    showDashboardMessage(error.message, "error");
  }
}

async function loadAnalysis() {
  if (!selectedRestaurant) return;
  try {
    const data = await requestJson(
      `/api/visualizations?restaurant_id=${encodeURIComponent(selectedRestaurant)}`,
    );
    renderAnalysis(data);
    showDashboardMessage("", "");
  } catch (error) {
    showDashboardMessage(error.message, "error");
    renderAnalysis(null);
  }
}

function renderAnalysis(data) {
  const waterfall = data?.waterfall || { revenue: 0, expenses: 0, net_cash: 0 };
  const summary = data?.statistical_summary || {};
  const revenue = waterfall.revenue || 0;
  const netCash = waterfall.net_cash || 0;
  document.getElementById("totalRevenue").textContent = naira.format(revenue);
  document.getElementById("totalExpenses").textContent = naira.format(waterfall.expenses || 0);
  document.getElementById("netIncome").textContent = naira.format(netCash);
  document.getElementById("profitMargin").textContent =
    `${revenue ? ((netCash / revenue) * 100).toFixed(2) : "0.00"}%`;
  document.getElementById("avgMonthlyRevenue").textContent =
    naira.format(summary.avg_monthly_revenue || 0);
  document.getElementById("revenueGrowthRate").textContent =
    summary.revenue_growth_rate == null ? "Not available" : `${summary.revenue_growth_rate.toFixed(2)}%`;
  document.getElementById("expenseToRevenue").textContent =
    `${(summary.expense_to_revenue_ratio || 0).toFixed(2)}%`;
  document.getElementById("anomalyPercentage").textContent =
    `${summary.anomaly_count || 0} (${(summary.anomaly_percentage || 0).toFixed(2)}%)`;
  document.getElementById("anomalyFootnote").textContent =
    `${summary.transaction_count || 0} transactions analyzed`;
  document.getElementById("anomalyCount").textContent =
    `${summary.anomaly_count || 0} flagged`;

  renderCashFlowChart(data?.monthly_trends, data?.anomalies || []);
  renderCategoryChart("revenueChart", data?.revenue_breakdown || {}, "#21865b");
  renderCategoryChart("expenseChart", data?.expense_breakdown || {}, "#e28559");
  renderAnomalies(data?.anomalies || [], summary.transaction_count || 0);
}

function renderCashFlowChart(trends = {}, anomalies = []) {
  const labels = trends.months || [];
  const largestAnomalyByMonth = new Map();
  anomalies.forEach((anomaly) => {
    const month = anomaly.date.slice(0, 7);
    const amount = Number(anomaly.amount_ngn);
    largestAnomalyByMonth.set(month, Math.max(largestAnomalyByMonth.get(month) || 0, amount));
  });
  drawChart("cashFlowChart", {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Revenue",
          data: trends.revenue || [],
          borderColor: "#21865b",
          backgroundColor: "rgba(33, 134, 91, 0.12)",
          fill: true,
          tension: 0.32,
        },
        {
          label: "Expenses",
          data: trends.expense || [],
          borderColor: "#e28559",
          backgroundColor: "rgba(226, 133, 89, 0.10)",
          fill: true,
          tension: 0.32,
        },
        {
          label: "Net cash flow",
          data: trends.net_cash || [],
          borderColor: "#5076ad",
          borderDash: [5, 4],
          tension: 0.32,
        },
        {
          label: "Largest flagged transaction",
          data: labels.map((month) => largestAnomalyByMonth.get(month) || null),
          showLine: false,
          pointRadius: 7,
          pointHoverRadius: 9,
          pointBackgroundColor: "#bd5948",
          pointBorderColor: "#fff",
          pointBorderWidth: 2,
        },
      ],
    },
    options: chartOptions(true),
  });
}

function renderCategoryChart(canvasId, breakdown, color) {
  const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
  const options = chartOptions(false);
  options.indexAxis = "y";
  options.scales.x.beginAtZero = true;
  options.scales.x.ticks.callback = (value) => compactNaira.format(value);
  options.scales.y.beginAtZero = false;
  options.scales.y.ticks = { color: "#738078" };
  drawChart(canvasId, {
    type: "bar",
    data: {
      labels: entries.map(([label]) => label),
      datasets: [{
        label: "Amount",
        data: entries.map(([, amount]) => amount),
        backgroundColor: color,
        borderRadius: 5,
        maxBarThickness: 26,
      }],
    },
    options,
  });
}

function chartOptions(showLegend) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: showLegend, position: "bottom", labels: { usePointStyle: true, boxWidth: 7 } },
      tooltip: {
        callbacks: { label: (context) => `${context.dataset.label || ""} ${naira.format(context.raw)}` },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { color: "#738078" },
      },
      y: {
        beginAtZero: true,
        grid: { color: "rgba(28, 62, 45, 0.07)" },
        ticks: {
          color: "#738078",
          callback: (value) => compactNaira.format(value),
        },
      },
    },
  };
}

function drawChart(canvasId, configuration) {
  if (charts[canvasId]) charts[canvasId].destroy();
  const canvas = document.getElementById(canvasId);
  if (!canvas || typeof Chart === "undefined") return;
  charts[canvasId] = new Chart(canvas, configuration);
}

function renderAnomalies(anomalies, transactionCount) {
  const table = document.getElementById("anomaliesTable");
  table.replaceChildren();
  if (!anomalies.length) {
    const row = table.insertRow();
    const cell = row.insertCell();
    cell.colSpan = 6;
    cell.className = "empty-state";
    cell.textContent = transactionCount
      ? "No unusual transactions flagged. Keep reviewing as your data grows."
      : "Import transactions to see analysis.";
    return;
  }

  anomalies.forEach((anomaly) => {
    const row = table.insertRow();
    const values = [
      new Date(anomaly.date).toLocaleDateString("en-NG"),
      anomaly.category,
      anomaly.type,
      `${anomaly.currency} ${Number(anomaly.amount).toLocaleString("en-NG", { maximumFractionDigits: 2 })}`,
      naira.format(anomaly.amount_ngn),
      anomaly.reason,
    ];
    values.forEach((value) => {
      const cell = row.insertCell();
      cell.textContent = value;
    });
  });
}

async function handleFileUpload(event) {
  event.preventDefault();
  const fileInput = document.getElementById("fileInput");
  const button = document.getElementById("uploadButton");
  if (!fileInput.files.length) {
    showDashboardMessage("Choose a CSV or XLSX file first.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("restaurant_id", selectedRestaurant);
  button.disabled = true;
  button.textContent = "Analyzing...";
  try {
    const result = await requestJson("/api/upload", { method: "POST", body: formData });
    selectedRestaurant = result.restaurant_id;
    await loadAnalysis();
    showDashboardMessage(result.message, "success");
  } catch (error) {
    showDashboardMessage(error.message, "error");
  } finally {
    fileInput.value = "";
    button.disabled = false;
    button.textContent = "Analyze data";
  }
}

async function downloadReport() {
  const button = document.getElementById("downloadReport");
  button.disabled = true;
  button.textContent = "Preparing PDF...";
  try {
    const response = await fetch("/api/generate_report", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-TOKEN": getCookie("csrf_access_token"),
      },
      body: JSON.stringify({ restaurant_id: selectedRestaurant }),
    });
    if (response.status === 401) {
      window.location.assign("/login");
      return;
    }
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.message || `Report generation failed (${response.status}).`);
    }
    const pdf = await response.blob();
    const objectUrl = URL.createObjectURL(pdf);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `${(document.getElementById("restaurantSelect").selectedOptions[0]?.textContent || "restaurant")
      .toLowerCase().replace(/[^a-z0-9]+/g, "-")}-cash-flow-analysis.pdf`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
    showDashboardMessage("Your analysis PDF has been downloaded.", "success");
  } catch (error) {
    showDashboardMessage(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Download analysis PDF";
  }
}

async function exportTransactions() {
  const button = document.getElementById("exportTransactions");
  button.disabled = true;
  button.textContent = "Preparing CSV...";
  try {
    const response = await fetch(
      `/api/restaurants/${encodeURIComponent(selectedRestaurant)}/transactions.csv`,
      { credentials: "same-origin" },
    );
    if (response.status === 401) {
      window.location.assign("/login");
      return;
    }
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.message || `CSV export failed (${response.status}).`);
    }
    const file = await response.blob();
    const objectUrl = URL.createObjectURL(file);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `${(document.getElementById("restaurantSelect").selectedOptions[0]?.textContent || "restaurant")
      .toLowerCase().replace(/[^a-z0-9]+/g, "-")}-transactions.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
    showDashboardMessage("Your transaction backup has been downloaded.", "success");
  } catch (error) {
    showDashboardMessage(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Back up transactions CSV";
  }
}

async function logout() {
  try {
    await requestJson("/api/logout", { method: "POST" });
  } finally {
    window.location.assign("/login");
  }
}

function showDashboardMessage(message, kind) {
  const element = document.getElementById("dashboardMessage");
  if (!element) return;
  element.textContent = message;
  element.className = `status-message${kind ? ` status-${kind}` : ""}`;
}

function getCookie(name) {
  const cookie = document.cookie
    .split("; ")
    .find((item) => item.startsWith(`${name}=`));
  return cookie ? decodeURIComponent(cookie.slice(name.length + 1)) : "";
}
