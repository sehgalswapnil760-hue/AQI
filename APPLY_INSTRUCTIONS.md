# ATMOS integration patch for sehgalswapnil760-hue/AQI

This is a patch bundle, not a complete repository export.

## Apply the changes

1. Replace the repository root `app.py` with this bundle's `app.py`.
2. Add `models/historical_reference_forecaster.joblib` and `models/station_dataset_calibrators.joblib` to the existing `models/` directory. KEEP the existing `model_A_raw.pkl`, `model_B_calibrated.pkl`, and `calibration_model.pkl`.
3. Add the entire `results/` directory.
4. Add `BAM_PM25_Dataset.csv` and `train_models.py` at the repository root if you want reproducible retraining.
5. Open the existing `templates/index.html` and paste the complete contents of `templates/atmos_calibrated_cards_snippet.html` immediately before `</body>`. Do not replace the existing index.html.
6. Keep the repository's existing `requirements.txt`; it already includes Flask, joblib, numpy, pandas, scikit-learn, pytz, and requests.
7. Set `OPENWEATHER_API_KEY` in Render Environment if weather data is required.
8. Set `ATMOS_DB_PATH` to a file path on a Render persistent disk if readings must survive redeploys.

## Model-safety note

The BAM dataset's paired optical sensor is not proven to be the ATMOS ZPH02. Its calibration model is used only for historical dataset demonstrations and is NOT applied to live ZPH02 readings. Live calibrated AQI remains N/A until real co-located ZPH02/reference measurements are collected and an independently validated `models/atmos_zph02_calibration.joblib` is supplied.

The historical forecast is based on BAM reference-station observations ending in January 2021. It is a historical model demonstration, not a current live forecast.

## Compatibility

The replacement backend retains `/update`, `/data`, `/health`, `/model-comparison`, `/historical-aqi-predictions`, and `/model-predictions`. Keep the existing legacy `.pkl` model files and `model_history.csv` so the old model-evaluation routes continue to work.

## Validation

`app.py` passed Python syntax compilation while this patch bundle was prepared. This is not a live Render deployment test. After applying, check `/health`, `/data`, `/dataset-calibration-evaluation`, `/historical-dataset-calibration?site=Hamirpur`, `/reference-forecast-evaluation`, and `/historical-reference-forecast?site=Hamirpur`.
