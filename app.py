from flask import Flask, request, jsonify, render_template
import os
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import requests
from collections import deque
from datetime import datetime, timedelta
import pytz
import time

app = Flask(__name__)

API_KEY = "f2d1c136bcd2d349eb9c32d393fcbb76"

LAT = 31.515355
LON = 76.878331

WEATHER_CACHE_TIME = 600

weather_cache = {
    "data":None,
    "timestamp":0
}


data_store={

"pm25_buffer":
deque(maxlen=5),

"mq135_buffer":
deque(maxlen=5)

}



# ================= WEATHER =================

def weather():

    if (

        weather_cache["data"]

        and

        time.time()

        -

        weather_cache["timestamp"]

        <

        WEATHER_CACHE_TIME

    ):

        return weather_cache["data"]


    try:

        url=(

        "https://api.openweathermap.org/data/2.5/weather"

        f"?lat={LAT}"

        f"&lon={LON}"

        f"&appid={API_KEY}"

        "&units=metric"

        )

        r=requests.get(url)

        d=r.json()


        w={

        "temp":

        round(

        d["main"]["temp"],1

        ),

        "humidity":

        d["main"]["humidity"],

        "wind":

        round(

        d["wind"]["speed"],1

        )

        }


        weather_cache["data"]=w

        weather_cache["timestamp"]=time.time()

        return w


    except:

        return{

        "temp":0,

        "humidity":0,

        "wind":0

        }





# ================= SENSOR FILTER =================

def get_smoothed():

    valid_pm=[

    x for x in

    data_store["pm25_buffer"]

    if 0<=x<=500

    ]


    valid_mq=[

    x for x in

    data_store["mq135_buffer"]

    if 0<=x<=1000

    ]


    pm25 = (

    round(

    sum(valid_pm)

    /

    len(valid_pm),

    1

    )

    if valid_pm

    else 0

    )


    mq135 = (

    round(

    sum(valid_mq)

    /

    len(valid_mq),

    1

    )

    if valid_mq

    else 0

    )


    return pm25,mq135





# ================= AQI =================

def calculate_aqi(pm):

    if pm<=12:

        return round(

        (50/12)

        *

        pm

        )


    elif pm<=35.4:

        return round(

        ((100-51)

        /

        (35.4-12.1))

        *

        (pm-12.1)

        +

        51

        )


    elif pm<=55.4:

        return round(

        ((150-101)

        /

        (55.4-35.5))

        *

        (pm-35.5)

        +

        101

        )


    elif pm<=150:

        return round(

        ((200-151)

        /

        (150-55.5))

        *

        (pm-55.5)

        +

        151

        )


    elif pm<=250:

        return round(

        ((300-201)

        /

        (250-150.5))

        *

        (pm-150.5)

        +

        201

        )


    return 300





@app.route("/")

def home():

    return render_template(

    "index.html"

    )





@app.route("/data")

def data():

    pm25,mq135 = get_smoothed()

    aqi = calculate_aqi(

    pm25

    )

    w = weather()



    forecast=[

    max(aqi-2,0),

    max(aqi-1,0),

    aqi+1,

    aqi

    ]


    india = pytz.timezone(

    "Asia/Kolkata"

    )


    now = datetime.now(

    india

    )


    forecast_time=[

    (now+

    timedelta(minutes=5)

    ).strftime(

    "%I:%M %p"

    ),

    (now+

    timedelta(minutes=10)

    ).strftime(

    "%I:%M %p"

    ),

    (now+

    timedelta(minutes=15)

    ).strftime(

    "%I:%M %p"

    ),

    (now+

    timedelta(minutes=20)

    ).strftime(

    "%I:%M %p"

    )

    ]


    return jsonify({

    "pm25":

    pm25,

    "mq135":

    mq135,

    "predicted_aqi":

    aqi,

    "forecast":

    forecast,

    "forecast_time":

    forecast_time,

    "temp":

    w["temp"],

    "humidity":

    w["humidity"],

    "wind":

    w["wind"],

    "lat":

    LAT,

    "lon":

    LON

    })






@app.route(

"/update",

methods=["POST"]

)

def update():

    try:

        d=request.get_json()


        pm25=max(

        0,

        min(

        float(

        d["pm25"]

        ),

        500

        )

        )


        mq135=max(

        0,

        min(

        float(

        d["mq135"]

        ),

        1000

        )

        )


        data_store[

        "pm25_buffer"

        ].append(

        pm25

        )


        data_store[

        "mq135_buffer"

        ].append(

        mq135

        )


        return jsonify({

        "status":"ok"

        })


    except Exception as e:

        return jsonify({

        "error":

        str(e)

        }),400






# ================= HISTORICAL FORECAST MODEL COMPARISON =================
# These saved models are actually loaded and used to recreate held-out test predictions.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models")
model_A_raw = joblib.load(os.path.join(MODEL_DIR, "model_A_raw.pkl"))
model_B_calibrated = joblib.load(os.path.join(MODEL_DIR, "model_B_calibrated.pkl"))
calibration_model = joblib.load(os.path.join(MODEL_DIR, "calibration_model.pkl"))
model_history = pd.read_csv(os.path.join(BASE_DIR, "model_history.csv"), parse_dates=["time"])


def build_test_predictions():
    """Rebuild the notebook's time-ordered held-out test features and use the saved PKLs."""
    df = model_history.copy().sort_values("time").reset_index(drop=True)
    cal_features = ["raw_pm25", "temp", "rh"]
    df["calibrated_pm25"] = calibration_model.predict(df[cal_features])
    for lag in range(1, 25):
        df[f"raw_lag_{lag}"] = df["raw_pm25"].shift(lag)
        df[f"cal_lag_{lag}"] = df["calibrated_pm25"].shift(lag)
    df["hour_sin"] = np.sin(2 * np.pi * df["time"].dt.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["time"].dt.hour / 24)
    df["target"] = df["bam_pm25"].shift(-1)
    df["persistence_pred"] = df["bam_pm25"]
    df = df.dropna().reset_index(drop=True)
    test_start = int(len(df) * 0.85)
    test = df.iloc[test_start:].copy()
    raw_cols = [f"raw_lag_{i}" for i in range(1, 25)] + ["hour_sin", "hour_cos"]
    cal_cols = [f"cal_lag_{i}" for i in range(1, 25)] + ["hour_sin", "hour_cos"]
    test["raw_prediction"] = model_A_raw.predict(test[raw_cols])
    test["calibrated_prediction"] = model_B_calibrated.predict(test[cal_cols])
    return test


def regression_metrics(actual, predicted):
    return {
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "mae": float(mean_absolute_error(actual, predicted)),
        "r2": float(r2_score(actual, predicted)),
    }


@app.route("/model-comparison")
def model_comparison():
    try:
        test = build_test_predictions()
        actual = test["target"].to_numpy()
        metrics = [
            {"name": "Persistence baseline", **regression_metrics(actual, test["persistence_pred"].to_numpy())},
            {"name": "Raw-input model", **regression_metrics(actual, test["raw_prediction"].to_numpy())},
            {"name": "Calibrated-input model", **regression_metrics(actual, test["calibrated_prediction"].to_numpy())},
        ]
        raw = next(m for m in metrics if m["name"] == "Raw-input model")
        calibrated = next(m for m in metrics if m["name"] == "Calibrated-input model")
        return jsonify({
            "evaluation_type": "historical held-out test set",
            "target": "next-hour reference BAM PM2.5 (µg/m³)",
            "models": metrics,
            "improvement": {
                "rmse_percent": float((raw["rmse"] - calibrated["rmse"]) / raw["rmse"] * 100),
                "mae_percent": float((raw["mae"] - calibrated["mae"]) / raw["mae"] * 100),
                "r2_absolute": float(calibrated["r2"] - raw["r2"]),
            },
            "models_loaded": ["model_A_raw.pkl", "model_B_calibrated.pkl", "calibration_model.pkl"],
            "test_rows": int(len(test)),
            "note": "Saved pickle models were used to generate predictions. Calibration improves the forecast model versus raw input, but both models are compared against a persistence baseline. These are historical test results, not live readings."
        })
    except Exception as exc:
        app.logger.exception("Model comparison failed")
        return jsonify({"error": "Could not run saved forecasting models", "details": str(exc)}), 500


@app.route("/historical-aqi-predictions")
def historical_aqi_predictions():
    """Convert held-out historical PM2.5 actual/predictions to this app's AQI estimate."""
    try:
        test = build_test_predictions()
        step = max(1, int(np.ceil(len(test) / 300)))
        view = test.iloc[::step]
        rows = []
        for _, row in view.iterrows():
            rows.append({
                "time": row["time"].strftime("%Y-%m-%d %H:%M"),
                "actual_aqi": calculate_aqi(max(0.0, float(row["target"]))),
                "raw_aqi": calculate_aqi(max(0.0, float(row["raw_prediction"]))),
                "calibrated_aqi": calculate_aqi(max(0.0, float(row["calibrated_prediction"]))),
                "persistence_aqi": calculate_aqi(max(0.0, float(row["persistence_pred"]))),
            })
        return jsonify({
            "evaluation_type": "historical held-out test set",
            "aqi_type": "PM2.5-derived estimate using the dashboard's existing conversion function",
            "note": "This is a historical model comparison, not a live future forecast or an official overall AQI computed from all pollutants.",
            "rows": rows,
        })
    except Exception as exc:
        app.logger.exception("Historical AQI prediction chart failed")
        return jsonify({"error": "Could not build historical AQI predictions", "details": str(exc)}), 500


@app.route("/model-predictions")
def model_predictions():
    """Return a downsampled historical test period for the actual-vs-predicted chart."""
    try:
        test = build_test_predictions()
        # Limit response size while preserving the order across the full test period.
        step = max(1, int(np.ceil(len(test) / 300)))
        view = test.iloc[::step]
        rows = []
        for _, row in view.iterrows():
            rows.append({
                "time": row["time"].strftime("%Y-%m-%d %H:%M"),
                "actual": round(float(row["target"]), 2),
                "raw": round(float(row["raw_prediction"]), 2),
                "calibrated": round(float(row["calibrated_prediction"]), 2),
                "persistence": round(float(row["persistence_pred"]), 2),
            })
        return jsonify({"evaluation_type": "historical held-out test set", "rows": rows})
    except Exception as exc:
        app.logger.exception("Prediction chart data failed")
        return jsonify({"error": "Could not build prediction chart", "details": str(exc)}), 500


if __name__=="__main__":

    app.run(

    host="0.0.0.0",

    port=5000

    )