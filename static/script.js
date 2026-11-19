// ================= CLOCK =================

function updateClock(){

let now =
new Date();

document.getElementById(
"nav-time"
).innerText =

now.toLocaleTimeString();

}

setInterval(
updateClock,
1000
);

updateClock();




// ================= MAP =================

let map =

L.map("map")

.setView(

[31.515355,76.878331],

13

);


L.tileLayer(

'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'

).addTo(map);



let marker =

L.marker(

[31.515355,76.878331]

).addTo(map);




// smaller highlighted zone

L.circle(

[31.515355,76.878331],

{

radius:250,

color:"green",

fillColor:"#00ff00",

fillOpacity:0.12

}

).addTo(map);






// ================= POLLUTION CHART =================

let pollutionChart =

new Chart(

document.getElementById(
"chart"
),

{

type:"line",

data:{

labels:[],

datasets:[

{

label:"PM2.5",

data:[],

borderColor:"#3b82f6",

backgroundColor:
"rgba(59,130,246,.1)",

fill:true,

tension:.4

},

{

label:"MQ135",

data:[],

borderColor:"#ec4899",

backgroundColor:
"rgba(236,72,153,.1)",

fill:true,

tension:.4

}

]

},

options:{

responsive:true,

plugins:{

legend:{

position:"top"

}

},

scales:{

y:{

beginAtZero:true

}

}

}

}

);







// ================= FORECAST CHART =================

let forecastChart =

new Chart(

document.getElementById(

"forecastChart"

),

{

type:"line",

data:{

labels:[],

datasets:[

{

label:"AQI Forecast",

data:[],

borderColor:"#3b82f6",

backgroundColor:

"rgba(59,130,246,.1)",

fill:true,

tension:.4,

pointRadius:5

}

]

},

options:{

responsive:true,

plugins:{

legend:{

position:"top"

}

},

scales:{

x:{

ticks:{

maxRotation:0

}

},

y:{

beginAtZero:true,

suggestedMax:150

}

}

}

}

);








// ================= AQI STATUS =================

function getStatus(aqi){

if(aqi<=50)
return "Good";

if(aqi<=100)
return "Moderate";

if(aqi<=150)
return "Unhealthy";

return "Hazardous";

}







// ================= LOAD DATA =================

async function loadData(){

try{

let res =

await fetch(

"/data?t="

+

Date.now()

);


let d =
await res.json();




// cards

document.getElementById(
"aqi-value"
).innerText =

d.predicted_aqi;



document.getElementById(
"aqi-status"
).innerText =

getStatus(

d.predicted_aqi

);



document.getElementById(
"pm25"
).innerText =

d.pm25;



document.getElementById(
"gas"
).innerText =

d.mq135;



document.getElementById(
"temp"
).innerText =

d.temp;



document.getElementById(
"humidity"
).innerText =

d.humidity;



document.getElementById(
"wind"
).innerText =

d.wind;







// ================= AQI SCALE =================

let pos =

Math.min(

d.predicted_aqi,

300

)

/

3;



document.getElementById(

"scale-indicator"

).style.left =

pos+"%";








// ================= POLLUTION GRAPH =================

let t =

new Date()

.toLocaleTimeString(

[],

{

hour:"2-digit",

minute:"2-digit"

}

);



pollutionChart.data.labels.push(

t

);


pollutionChart.data.datasets[0]
.data.push(

d.pm25

);


pollutionChart.data.datasets[1]
.data.push(

d.mq135

);



if(

pollutionChart.data.labels.length

>

15

){

pollutionChart.data.labels.shift();

pollutionChart.data.datasets[0]
.data.shift();

pollutionChart.data.datasets[1]
.data.shift();

}


pollutionChart.update();








// ================= FORECAST GRAPH =================

forecastChart.data.labels =

d.forecast_time;


forecastChart.data.datasets[0]
.data =

d.forecast;


forecastChart.update();








// ================= MAP =================

// update marker only

marker.setLatLng(

[d.lat,d.lon]

);


// removed map.setView()
// prevents jumping







// ================= FOOTER =================

document.getElementById(

"footer-weather"

).innerText =

`${d.temp}°C · ${d.humidity}% RH`;



}

catch(e){

console.log(e);

}

}








// ================= AUTO REFRESH =================

loadData();

setInterval(

loadData,

5000

);

// ================= HISTORICAL MODEL COMPARISON =================
let errorComparisonChart = null;
let r2ComparisonChart = null;
let modelPredictionChart = null;
let historicalAqiForecastChart = null;

async function loadModelComparison() {
  try {
    const response = await fetch("/model-comparison?t=" + Date.now());
    if (!response.ok) throw new Error("Could not load model comparison");
    const result = await response.json();
    const models = result.models;
    const raw = models.find(m => m.name === "Raw-input model");
    const calibrated = models.find(m => m.name === "Calibrated-input model");

    document.getElementById("rmse-improvement").textContent = result.improvement.rmse_percent.toFixed(1) + "%";
    document.getElementById("mae-improvement").textContent = result.improvement.mae_percent.toFixed(1) + "%";
    document.getElementById("r2-improvement").textContent = "+" + result.improvement.r2_absolute.toFixed(3);

    document.getElementById("model-results-body").innerHTML = models.map(m =>
      `<tr><td>${m.name}</td><td>${m.rmse.toFixed(2)}</td><td>${m.mae.toFixed(2)}</td><td>${m.r2.toFixed(3)}</td></tr>`
    ).join("");

    const labels = models.map(m => m.name);
    if (errorComparisonChart) errorComparisonChart.destroy();
    errorComparisonChart = new Chart(document.getElementById("errorComparisonChart"), {
      type: "bar",
      data: { labels, datasets: [
        { label: "RMSE", data: models.map(m => m.rmse), backgroundColor: "rgba(59,130,246,.78)" },
        { label: "MAE", data: models.map(m => m.mae), backgroundColor: "rgba(236,72,153,.75)" }
      ]},
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "top" } }, scales: { y: { beginAtZero: true, title: { display: true, text: "Error (µg/m³)" } }, x: { ticks: { maxRotation: 0, minRotation: 0 } } } }
    });

    if (r2ComparisonChart) r2ComparisonChart.destroy();
    r2ComparisonChart = new Chart(document.getElementById("r2ComparisonChart"), {
      type: "bar",
      data: { labels, datasets: [{ label: "R²", data: models.map(m => m.r2), backgroundColor: ["rgba(22,163,74,.78)", "rgba(59,130,246,.78)", "rgba(234,88,12,.78)"] }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "top" } }, scales: { y: { beginAtZero: true, max: 1, title: { display: true, text: "R² score" } }, x: { ticks: { maxRotation: 0, minRotation: 0 } } } }
    });

    const predictionResponse = await fetch("/model-predictions?t=" + Date.now());
    if (!predictionResponse.ok) throw new Error("Could not load historical predictions");
    const predictionResult = await predictionResponse.json();
    const rows = predictionResult.rows || [];
    if (modelPredictionChart) modelPredictionChart.destroy();
    modelPredictionChart = new Chart(document.getElementById("modelPredictionChart"), {
      type: "line",
      data: {
        labels: rows.map(row => row.time),
        datasets: [
          { label: "Actual next-hour BAM PM2.5", data: rows.map(row => row.actual), borderColor: "#111827", borderWidth: 2, pointRadius: 0, tension: 0.15 },
          { label: "Raw-input model", data: rows.map(row => row.raw), borderColor: "#3b82f6", borderWidth: 1.5, pointRadius: 0, tension: 0.15 },
          { label: "Calibrated-input model", data: rows.map(row => row.calibrated), borderColor: "#0d9488", borderWidth: 1.5, pointRadius: 0, tension: 0.15 },
          { label: "Persistence baseline", data: rows.map(row => row.persistence), borderColor: "#a855f7", borderWidth: 1, borderDash: [5, 4], pointRadius: 0, tension: 0.15 }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { legend: { position: "top" } }, scales: { x: { ticks: { maxTicksLimit: 8, maxRotation: 0 }, title: { display: true, text: "Historical test time" } }, y: { title: { display: true, text: "PM2.5 (µg/m³)" } } } }
    });

    // AQI series are derived from the same historical PM2.5 values returned above.
    const aqiResponse = await fetch("/historical-aqi-predictions?t=" + Date.now());
    if (!aqiResponse.ok) throw new Error("Could not load historical AQI forecasts");
    const aqiResult = await aqiResponse.json();
    const aqiRows = aqiResult.rows || [];
    if (historicalAqiForecastChart) historicalAqiForecastChart.destroy();
    historicalAqiForecastChart = new Chart(document.getElementById("historicalAqiForecastChart"), {
      type: "line",
      data: {
        labels: aqiRows.map(row => row.time),
        datasets: [
          { label: "Actual next-hour PM2.5-derived AQI", data: aqiRows.map(row => row.actual_aqi), borderColor: "#111827", borderWidth: 2, pointRadius: 0, tension: 0.15 },
          { label: "Raw-input model AQI estimate", data: aqiRows.map(row => row.raw_aqi), borderColor: "#3b82f6", borderWidth: 1.5, pointRadius: 0, tension: 0.15 },
          { label: "Calibrated-input model AQI estimate", data: aqiRows.map(row => row.calibrated_aqi), borderColor: "#0d9488", borderWidth: 1.5, pointRadius: 0, tension: 0.15 },
          { label: "Persistence baseline AQI", data: aqiRows.map(row => row.persistence_aqi), borderColor: "#a855f7", borderWidth: 1, borderDash: [5, 4], pointRadius: 0, tension: 0.15 }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { legend: { position: "top" } }, scales: { x: { ticks: { maxTicksLimit: 8, maxRotation: 0 }, title: { display: true, text: "Historical test time" } }, y: { beginAtZero: true, suggestedMax: 150, title: { display: true, text: "PM2.5-derived AQI estimate" } } } }
    });
  } catch (error) {
    console.error("Model comparison could not be loaded:", error);
  }
}

loadModelComparison();
