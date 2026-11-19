# Historical AQI forecast chart

The dashboard now includes a historical AQI-estimate comparison graph alongside the existing historical PM2.5 prediction graph and model-metric charts.

- The graph uses the saved raw-input and calibrated-input forecasting models on the held-out historical test period.
- Actual next-hour reference PM2.5 and persistence-baseline PM2.5 are converted using the dashboard's existing `calculate_aqi()` function.
- The result is a PM2.5-derived AQI estimate. It is not an official overall Indian AQI calculated from all required pollutants.
- Historical predictions are not live forecasts. The current sensor area and its existing short-term chart are separate from the historical model-evaluation graphs.
- The pickle models were saved with scikit-learn 1.6.1, so `requirements.txt` pins that version to avoid the version mismatch warning seen with newer scikit-learn versions.

## Run locally (Windows PowerShell)

```powershell
py -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000/` in your browser.
