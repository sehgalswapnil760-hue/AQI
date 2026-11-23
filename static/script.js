
"use strict";

// =============================================
// ATMOS AIR QUALITY DASHBOARD
// =============================================

const REFRESH_INTERVAL = 5000;
const MAX_CHART_POINTS = 15;

const LOCATION = {
  lat: 31.515355,
  lon: 76.878331
};

let pollutionChart = null;
let forecastChart = null;
let map = null;
let marker = null;

let errorComparisonChart = null;
let r2ComparisonChart = null;
let modelPredictionChart = null;
let historicalAqiForecastChart = null;

let lastChartTimestamp = null;
let isLoading = false;

// =============================================
// HELPER FUNCTIONS
// =============================================

function element(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const el = element(id);
  if (el) el.textContent = value;
}

function validNumber(value) {
  return value !== null &&
    value !== undefined &&
    value !== "" &&
    Number.isFinite(Number(value));
}

function displayNumber(value, decimals = 1) {
  if (!validNumber(value)) return "N/A";
  return Number(value).toFixed(decimals);
}

function chartNumber(value) {
  return validNumber(value) ? Number(value) : null;
}

function formatTime(value) {
  if (!value) return "--:--";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "--:--";
  }

  return date.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Asia/Kolkata"
  });
}

function updateClock() {
  setText(
    "nav-time",
    new Date().toLocaleTimeString("en-IN", {
      timeZone: "Asia/Kolkata"
    })
  );
}

// =============================================
// AQI STATUS
// =============================================

function getStatus(aqi) {
  if (!validNumber(aqi)) return "Unavailable";

  const value = Number(aqi);

  if (value <= 50) return "Good";
  if (value <= 100) return "Moderate";
  if (value <= 150) return "Unhealthy for Sensitive Groups";
  if (value <= 200) return "Unhealthy";
  if (value <= 300) return "Very Unhealthy";

  return "Hazardous";
}

// =============================================
// MAP INITIALIZATION
// =============================================

function initializeMap() {
  if (typeof L === "undefined" || !element("map")) {
    console.warn("Leaflet or map element unavailable");
    return;
  }

  map = L.map("map").setView(
    [LOCATION.lat, LOCATION.lon],
    13
  );

  L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
      attribution: "&copy; OpenStreetMap contributors"
    }
  ).addTo(map);

  marker = L.marker(
    [LOCATION.lat, LOCATION.lon]
  ).addTo(map);

  L.circle(
    [LOCATION.lat, LOCATION.lon],
    {
      radius: 250,
      color: "green",
      fillColor: "#00ff00",
      fillOpacity: 0.12
    }
  ).addTo(map);
}

// =============================================
// POLLUTION CHART
// =============================================

function initializePollutionChart() {
  if (typeof Chart === "undefined" || !element("chart")) {
    console.warn("Chart.js or pollution canvas unavailable");
    return;
  }

  pollutionChart = new Chart(element("chart"), {
    type: "line",

    data: {
      labels: [],

      datasets: [
        {
          label: "PM2.5 (µg/m³)",
          data: [],
          borderColor: "#3b82f6",
          backgroundColor: "rgba(59,130,246,0.1)",
          fill: true,
          tension: 0.4,
          spanGaps: false
        },
        {
          label: "MQ135 (ADC)",
          data: [],
          borderColor: "#ec4899",
          backgroundColor: "rgba(236,72,153,0.1)",
          fill: true,
          tension: 0.4,
          spanGaps: false
        }
      ]
    },

    options: {
      responsive: true,
      animation: false,
      plugins: {
        legend: {
          position: "top"
        }
      },
      scales: {
        y: {
          beginAtZero: true
        }
      }
    }
  });
}

function updatePollutionChart(data) {
  if (!pollutionChart || !data.last_update) return;

  // Do not duplicate the same server reading.
  if (data.last_update === lastChartTimestamp) return;

  lastChartTimestamp = data.last_update;

  pollutionChart.data.labels.push(
    formatTime(data.last_update)
  );

  pollutionChart.data.datasets[0].data.push(
    chartNumber(data.pm25)
  );

  pollutionChart.data.datasets[1].data.push(
    chartNumber(data.mq135)
  );

  while (
    pollutionChart.data.labels.length >
    MAX_CHART_POINTS
  ) {
    pollutionChart.data.labels.shift();

    pollutionChart.data.datasets.forEach(dataset => {
      dataset.data.shift();
    });
  }

  pollutionChart.update("none");
}

// =============================================
// FORECAST CHART
// =============================================

function initializeForecastChart() {
  if (typeof Chart === "undefined" ||
      !element("forecastChart")) {
    return;
  }

  forecastChart = new Chart(
    element("forecastChart"),
    {
      type: "line",

      data: {
        labels: [],

        datasets: [
          {
            label: "Illustrative AQI Trend",
            data: [],
            borderColor: "#3b82f6",
            backgroundColor: "rgba(59,130,246,0.1)",
            fill: true,
            tension: 0.4,
            pointRadius: 5
          }
        ]
      },

      options: {
        responsive: true,
        animation: false,
        plugins: {
          legend: {
            position: "top"
          }
        },
        scales: {
          x: {
            ticks: {
              maxRotation: 0
            }
          },
          y: {
            beginAtZero: true,
            suggestedMax: 150
          }
        }
      }
    }
  );
}

function updateForecastChart(data) {
  if (!forecastChart) return;

  forecastChart.data.labels =
    Array.isArray(data.forecast_time)
      ? data.forecast_time
      : [];

  forecastChart.data.datasets[0].data =
    Array.isArray(data.forecast)
      ? data.forecast.map(chartNumber)
      : [];

  forecastChart.update("none");
}

// =============================================
// LIVE DASHBOARD CARDS
// =============================================

function updateCards(data) {
  setText(
    "aqi-value",
    validNumber(data.predicted_aqi)
      ? Math.round(Number(data.predicted_aqi))
      : "N/A"
  );

  setText(
    "aqi-status",
    getStatus(data.predicted_aqi)
  );

  setText("pm25", displayNumber(data.pm25));
  setText("gas", displayNumber(data.mq135, 0));

  setText("temp", displayNumber(data.temp));
  setText("humidity", displayNumber(data.humidity, 0));
  setText("wind", displayNumber(data.wind));

  const scale = element("scale-indicator");

  if (scale) {
    if (validNumber(data.predicted_aqi)) {
      const position = Math.max(
        0,
        Math.min(Number(data.predicted_aqi), 300)
      ) / 3;

      scale.style.left = position + "%";
      scale.style.display = "";
    } else {
      scale.style.display = "none";
    }
  }

  const footerWeather =
    validNumber(data.temp) && validNumber(data.humidity)
      ? `${displayNumber(data.temp)}°C · ${displayNumber(data.humidity, 0)}% RH`
      : "Weather unavailable";

  setText("footer-weather", footerWeather);

  setText(
    "last-update",
    data.last_update
      ? formatTime(data.last_update)
      : "Waiting for ESP32"
  );

  setText(
    "calibrated-aqi",
    displayNumber(data.calibrated_aqi, 0)
  );
}

// =============================================
// UPDATE MAP
// =============================================

function updateMap(data) {
  if (!marker) return;

  if (
    validNumber(data.lat) &&
    validNumber(data.lon)
  ) {
    marker.setLatLng([
      Number(data.lat),
      Number(data.lon)
    ]);
  }

  // Do not reset map zoom on every refresh.
}

// =============================================
// FETCH LIVE SENSOR DATA
// =============================================

async function loadData() {
  if (isLoading) return;

  isLoading = true;

  try {
    const controller = new AbortController();

    const timeout = setTimeout(() => {
      controller.abort();
    }, 10000);

    let response;

    try {
      response = await fetch(
        "/data?t=" + Date.now(),
        {
          method: "GET",
          cache: "no-store",
          headers: {
            "Accept": "application/json"
          },
          signal: controller.signal
        }
      );
    } finally {
      clearTimeout(timeout);
    }

    if (!response.ok) {
      throw new Error(
        "Server returned HTTP " + response.status
      );
    }

    const data = await response.json();

    if (!data || typeof data !== "object") {
      throw new Error("Invalid server JSON");
    }

    updateCards(data);
    updatePollutionChart(data);
    updateForecastChart(data);
    updateMap(data);

    if (data.last_update) {
      console.log(
        "ATMOS: Latest reading:",
        data.last_update,
        "PM2.5:",
        data.pm25,
        "MQ135:",
        data.mq135
      );
    } else {
      console.warn(
        "ATMOS: No ESP32 readings stored on server"
      );
    }

  } catch (error) {
    console.error(
      "ATMOS live data update failed:",
      error
    );

    setText("connection-status", "Server error");

  } finally {
    isLoading = false;
  }
}

// =============================================
// HISTORICAL MODEL COMPARISON
// =============================================

async function fetchJSON(url) {
  const response = await fetch(
    url + "?t=" + Date.now(),
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw new Error(
      url + " returned HTTP " + response.status
    );
  }

  return response.json();
}

function createChart(canvasId, config) {
  if (
    typeof Chart === "undefined" ||
    !element(canvasId)
  ) {
    return null;
  }

  return new Chart(element(canvasId), config);
}

function metric(value, digits = 2) {
  return validNumber(value)
    ? Number(value).toFixed(digits)
    : "N/A";
}

async function loadModelComparison() {
  try {
    const result = await fetchJSON(
      "/model-comparison"
    );

    const models = Array.isArray(result.models)
      ? result.models
      : [];

    const improvement = result.improvement || {};

    const rmse = improvement.rmse_percent;
    const mae = improvement.mae_percent;
    const r2 = improvement.r2_absolute;

    setText(
      "rmse-improvement",
      validNumber(rmse) ? metric(rmse, 1) + "%" : "N/A"
    );

    setText(
      "mae-improvement",
      validNumber(mae) ? metric(mae, 1) + "%" : "N/A"
    );

    setText(
      "r2-improvement",
      validNumber(r2) ? metric(r2, 3) : "N/A"
    );

    const resultsBody = element("model-results-body");

    if (resultsBody) {
      resultsBody.replaceChildren();

      models.forEach(m => {
        const tr = document.createElement("tr");

        [
          m.name,
          metric(m.rmse),
          metric(m.mae),
          metric(m.r2, 3)
        ].forEach(value => {
          const td = document.createElement("td");
          td.textContent = value;
          tr.appendChild(td);
        });

        resultsBody.appendChild(tr);
      });
    }

    const labels = models.map(m => m.name);

    if (errorComparisonChart) {
      errorComparisonChart.destroy();
    }

    errorComparisonChart = createChart(
      "errorComparisonChart",
      {
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              label: "RMSE",
              data: models.map(m => chartNumber(m.rmse)),
              backgroundColor: "rgba(59,130,246,0.78)"
            },
            {
              label: "MAE",
              data: models.map(m => chartNumber(m.mae)),
              backgroundColor: "rgba(236,72,153,0.75)"
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: { beginAtZero: true }
          }
        }
      }
    );

    if (r2ComparisonChart) {
      r2ComparisonChart.destroy();
    }

    r2ComparisonChart = createChart(
      "r2ComparisonChart",
      {
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              label: "R²",
              data: models.map(m => chartNumber(m.r2)),
              backgroundColor: [
                "#16a34a",
                "#3b82f6",
                "#ea580c"
              ]
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              title: {
                display: true,
                text: "R² score"
              }
            }
          }
        }
      }
    );

  } catch (error) {
    console.error(
      "Model comparison failed:",
      error
    );
  }

  // Load the historical charts separately so that
  // a failure in one does not stop the others.

  try {
    const result = await fetchJSON(
      "/model-predictions"
    );

    const rows = Array.isArray(result.rows)
      ? result.rows
      : [];

    if (modelPredictionChart) {
      modelPredictionChart.destroy();
    }

    modelPredictionChart = createChart(
      "modelPredictionChart",
      {
        type: "line",
        data: {
          labels: rows.map(r => r.time),
          datasets: [
            {
              label: "Actual next-hour BAM PM2.5",
              data: rows.map(r => chartNumber(r.actual)),
              borderColor: "#111827",
              pointRadius: 0,
              tension: 0.15
            },
            {
              label: "Raw-input model",
              data: rows.map(r => chartNumber(r.raw)),
              borderColor: "#3b82f6",
              pointRadius: 0,
              tension: 0.15
            },
            {
              label: "Calibrated-input model",
              data: rows.map(r => chartNumber(r.calibrated)),
              borderColor: "#0d9488",
              pointRadius: 0,
              tension: 0.15
            },
            {
              label: "Persistence baseline",
              data: rows.map(r => chartNumber(r.persistence)),
              borderColor: "#a855f7",
              borderDash: [5, 4],
              pointRadius: 0
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            mode: "index",
            intersect: false
          },
          scales: {
            x: {
              ticks: {
                maxTicksLimit: 8,
                maxRotation: 0
              }
            }
          }
        }
      }
    );

  } catch (error) {
    console.error(
      "Historical PM2.5 chart failed:",
      error
    );
  }

  try {
    const result = await fetchJSON(
      "/historical-aqi-predictions"
    );

    const rows = Array.isArray(result.rows)
      ? result.rows
      : [];

    if (historicalAqiForecastChart) {
      historicalAqiForecastChart.destroy();
    }

    historicalAqiForecastChart = createChart(
      "historicalAqiForecastChart",
      {
        type: "line",
        data: {
          labels: rows.map(r => r.time),
          datasets: [
            {
              label: "Actual PM2.5-derived AQI",
              data: rows.map(r => chartNumber(r.actual_aqi)),
              borderColor: "#111827",
              pointRadius: 0,
              tension: 0.15
            },
            {
              label: "Raw-input AQI",
              data: rows.map(r => chartNumber(r.raw_aqi)),
              borderColor: "#3b82f6",
              pointRadius: 0,
              tension: 0.15
            },
            {
              label: "Calibrated-input AQI",
              data: rows.map(r => chartNumber(r.calibrated_aqi)),
              borderColor: "#0d9488",
              pointRadius: 0,
              tension: 0.15
            },
            {
              label: "Persistence AQI",
              data: rows.map(r => chartNumber(r.persistence_aqi)),
              borderColor: "#a855f7",
              borderDash: [5, 4],
              pointRadius: 0
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              ticks: {
                maxTicksLimit: 8,
                maxRotation: 0
              }
            },
            y: {
              beginAtZero: true
            }
          }
        }
      }
    );

  } catch (error) {
    console.error(
      "Historical AQI chart failed:",
      error
    );
  }
}

// =============================================
// INITIALIZE DASHBOARD
// =============================================

function initializeDashboard() {
  updateClock();

  setInterval(
    updateClock,
    1000
  );

  initializeMap();
  initializePollutionChart();
  initializeForecastChart();

  // Load sensor readings immediately.
  loadData();

  // Refresh every 5 seconds.
  setInterval(
    loadData,
    REFRESH_INTERVAL
  );

  // Historical model charts load once.
  loadModelComparison();

  console.log(
    "ATMOS dashboard initialized successfully"
  );
}

if (document.readyState === "loading") {
  document.addEventListener(
    "DOMContentLoaded",
    initializeDashboard
  );
} else {
  initializeDashboard();
}

