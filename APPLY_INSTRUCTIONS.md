# Run the ATMOS dashboard

Extract the archive and open the directory containing app.py. Use Python 3.12 or 3.13.

```sh
python -m pip install -r requirements.txt
python app.py
```

Open the local URL printed by Flask. Send sensor readings as JSON to POST /update. GET /data returns the dashboard values. The models, historical results, and dashboard cards are already in place.

Set OPENWEATHER_API_KEY to enable weather. Set ATMOS_DB_PATH to a file on a persistent disk to retain new readings across deployments.

## Model-safety note

The BAM dataset's paired optical sensor is not proven to be the ATMOS ZPH02. Its calibration model is used only for historical dataset demonstrations and is NOT applied to live ZPH02 readings. Live calibrated AQI remains N/A until real co-located ZPH02/reference measurements are collected and an independently validated `models/atmos_zph02_calibration.joblib` is supplied.

The historical forecast is based on BAM reference-station observations ending in January 2021. It is a historical model demonstration, not a current live forecast.

