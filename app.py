from flask import Flask, request, jsonify, render_template
import os
import time
import sqlite3
import math
import threading
from datetime import datetime, timedelta, timezone

import joblib
import numpy as np
import pandas as pd
import pytz
import requests
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, 'models')
DB_PATH = os.getenv('ATMOS_DB_PATH', os.path.join(BASE_DIR, 'atmos.db'))
API_KEY = os.getenv('OPENWEATHER_API_KEY', '')
LAT, LON = 31.515355, 76.878331
weather_cache = {'data': None, 'at': 0}
weather_lock = threading.Lock()


def connect_db():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect_db() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            node_id TEXT,
            pm25 REAL,
            mq135 REAL,
            zph02_lpr_pct REAL,
            mq135_volts REAL,
            gas_ratio REAL
        )''')


def parse_number(payload, key, minimum, maximum):
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f'{key} must be numeric')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{key} must be numeric')
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f'{key} must be between {minimum} and {maximum}')
    return number


def weather():
    with weather_lock:
        if weather_cache['data'] is not None and time.time() - weather_cache['at'] < 600:
            return weather_cache['data']
    fallback = weather_cache['data'] or {'temp': None, 'humidity': None, 'wind': None}
    if not API_KEY:
        return fallback
    try:
        response = requests.get('https://api.openweathermap.org/data/2.5/weather',
            params={'lat': LAT, 'lon': LON, 'appid': API_KEY, 'units': 'metric'}, timeout=8)
        response.raise_for_status()
        obj = response.json()
        result = {'temp': round(float(obj['main']['temp']), 1),
                  'humidity': int(obj['main']['humidity']),
                  'wind': round(float(obj['wind']['speed']) * 3.6, 1)}
        with weather_lock:
            weather_cache.update(data=result, at=time.time())
        return result
    except (requests.RequestException, ValueError, KeyError, TypeError):
        app.logger.exception('Weather lookup failed')
        return fallback


def calculate_aqi(pm):
    if pm is None:
        return None
    pm = float(pm)
    # PM2.5-derived US AQI estimate; not a full multi-pollutant AQI.
    bands = [(0, 12, 0, 50), (12.1, 35.4, 51, 100),
             (35.5, 55.4, 101, 150), (55.5, 150.4, 151, 200),
             (150.5, 250.4, 201, 300), (250.5, 350.4, 301, 400),
             (350.5, 500.4, 401, 500)]
    pm = max(0, min(pm, 500.4))
    for low, high, aqi_low, aqi_high in bands:
        if pm <= high:
            pm = max(pm, low)
            return round((aqi_high - aqi_low) * (pm - low) / (high - low) + aqi_low)
    return 500


def last_reading():
    with connect_db() as con:
        row = con.execute('SELECT * FROM readings ORDER BY id DESC LIMIT 1').fetchone()
    return dict(row) if row else None


def smoothed(field):
    if field not in ('pm25', 'mq135', 'zph02_lpr_pct'):
        raise ValueError('Invalid field')
    with connect_db() as con:
        rows = con.execute(
            f'SELECT {field} FROM readings WHERE {field} IS NOT NULL ORDER BY id DESC LIMIT 5'
        ).fetchall()
    values = [float(r[0]) for r in rows]
    return round(sum(values) / len(values), 1) if values else None


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/health')
def health():
    return jsonify(status='ok', service='ATMOS')


@app.route('/update', methods=['POST'])
def update():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='Expected JSON object'), 400
    try:
        pm25 = parse_number(payload, 'pm25', 0, 500)
        mq135 = parse_number(payload, 'mq135', 0, 4095)
        if mq135 is None:
            mq135 = parse_number(payload, 'mq135_adc', 0, 4095)
        lpr = parse_number(payload, 'zph02_lpr_pct', 0, 100)
        volts = parse_number(payload, 'mq135_volts', 0, 5.5)
        ratio = parse_number(payload, 'gas_ratio', 0, 1e9)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if pm25 is None and mq135 is None and lpr is None:
        return jsonify(error='No sensor readings provided'), 400
    timestamp = datetime.now(timezone.utc).isoformat()
    node_id = str(payload.get('node_id') or 'ATMOS_ESP32')[:100]
    try:
        with connect_db() as con:
            con.execute('''INSERT INTO readings
                (timestamp, node_id, pm25, mq135, zph02_lpr_pct, mq135_volts, gas_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (timestamp, node_id, pm25, mq135, lpr, volts, ratio))
    except sqlite3.Error:
        app.logger.exception('Database insert failed')
        return jsonify(error='Could not store reading'), 500
    return jsonify(status='ok', last_update=timestamp,
                   received={'pm25': pm25, 'mq135': mq135, 'zph02_lpr_pct': lpr}), 200


@app.route('/data')
def data():
    pm25, mq135, lpr = smoothed('pm25'), smoothed('mq135'), smoothed('zph02_lpr_pct')
    aqi = calculate_aqi(pm25)
    latest = last_reading()
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    forecast_time = [(now + timedelta(minutes=m)).strftime('%I:%M %p') for m in (5, 10, 15, 20)]
    # Illustrative only; actual ML model comparison is available on separate endpoints.
    forecast = [max(aqi - 2, 0), max(aqi - 1, 0), aqi + 1, aqi] if aqi is not None else []
    w = weather()
    return jsonify(pm25=pm25, mq135=mq135, zph02_lpr_pct=lpr,
                   predicted_aqi=aqi, calibrated_aqi=None,
                   forecast=forecast, forecast_time=forecast_time,
                   forecast_type='illustrative, not ML prediction',
                   temp=w['temp'], humidity=w['humidity'], wind=w['wind'],
                   lat=LAT, lon=LON,
                   last_update=latest['timestamp'] if latest else None,
                   node_id=latest['node_id'] if latest else None,
                   pm25_available=pm25 is not None,
                   mq135_available=mq135 is not None)


# ================= HISTORICAL ML MODEL COMPARISON =================
# These endpoints evaluate saved models on historical held-out data.
# Missing model files must not stop live ESP32 uploads.

def build_test_predictions():
    model_A_raw = joblib.load(os.path.join(MODEL_DIR, 'model_A_raw.pkl'))
    model_B_calibrated = joblib.load(os.path.join(MODEL_DIR, 'model_B_calibrated.pkl'))
    calibration_model = joblib.load(os.path.join(MODEL_DIR, 'calibration_model.pkl'))
    model_history = pd.read_csv(os.path.join(BASE_DIR, 'model_history.csv'), parse_dates=['time'])
    df = model_history.copy().sort_values('time').reset_index(drop=True)
    df['calibrated_pm25'] = calibration_model.predict(df[['raw_pm25', 'temp', 'rh']])
    for lag in range(1, 25):
        df[f'raw_lag_{lag}'] = df['raw_pm25'].shift(lag)
        df[f'cal_lag_{lag}'] = df['calibrated_pm25'].shift(lag)
    df['hour_sin'] = np.sin(2 * np.pi * df['time'].dt.hour / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['time'].dt.hour / 24)
    df['target'] = df['bam_pm25'].shift(-1)
    df['persistence_pred'] = df['bam_pm25']
    df = df.dropna().reset_index(drop=True)
    test = df.iloc[int(len(df) * 0.85):].copy()
    if len(test) < 2:
        raise ValueError('Not enough historical test data')
    raw_cols = [f'raw_lag_{i}' for i in range(1, 25)] + ['hour_sin', 'hour_cos']
    cal_cols = [f'cal_lag_{i}' for i in range(1, 25)] + ['hour_sin', 'hour_cos']
    test['raw_prediction'] = model_A_raw.predict(test[raw_cols])
    test['calibrated_prediction'] = model_B_calibrated.predict(test[cal_cols])
    return test


def regression_metrics(actual, predicted):
    return {'rmse': float(np.sqrt(mean_squared_error(actual, predicted))),
            'mae': float(mean_absolute_error(actual, predicted)),
            'r2': float(r2_score(actual, predicted))}


@app.route('/model-comparison')
def model_comparison():
    try:
        test = build_test_predictions()
        actual = test['target'].to_numpy()
        metrics = [
            {'name': 'Persistence baseline', **regression_metrics(actual, test['persistence_pred'].to_numpy())},
            {'name': 'Raw-input model', **regression_metrics(actual, test['raw_prediction'].to_numpy())},
            {'name': 'Calibrated-input model', **regression_metrics(actual, test['calibrated_prediction'].to_numpy())}
        ]
        raw, calibrated = metrics[1], metrics[2]
        return jsonify(evaluation_type='historical held-out test set',
            target='next-hour reference BAM PM2.5 (µg/m³)', models=metrics,
            improvement={
                'rmse_percent': (raw['rmse'] - calibrated['rmse']) / raw['rmse'] * 100 if raw['rmse'] else None,
                'mae_percent': (raw['mae'] - calibrated['mae']) / raw['mae'] * 100 if raw['mae'] else None,
                'r2_absolute': calibrated['r2'] - raw['r2']
            }, models_loaded=['model_A_raw.pkl', 'model_B_calibrated.pkl', 'calibration_model.pkl'],
            test_rows=len(test), note='Historical test results, not live sensor predictions')
    except Exception as exc:
        app.logger.exception('Model comparison failed')
        return jsonify(error='Could not run saved forecasting models', details=str(exc)), 500


@app.route('/historical-aqi-predictions')
def historical_aqi_predictions():
    try:
        test = build_test_predictions()
        step = max(1, int(np.ceil(len(test) / 300)))
        rows = []
        for _, row in test.iloc[::step].iterrows():
            rows.append({
                'time': row['time'].strftime('%Y-%m-%d %H:%M'),
                'actual_aqi': calculate_aqi(max(0.0, float(row['target']))),
                'raw_aqi': calculate_aqi(max(0.0, float(row['raw_prediction']))),
                'calibrated_aqi': calculate_aqi(max(0.0, float(row['calibrated_prediction']))),
                'persistence_aqi': calculate_aqi(max(0.0, float(row['persistence_pred'])))
            })
        return jsonify(evaluation_type='historical held-out test set', rows=rows,
            note='Historical AQI estimates, not live future forecasts')
    except Exception as exc:
        app.logger.exception('Historical AQI predictions failed')
        return jsonify(error='Could not build historical AQI predictions', details=str(exc)), 500


@app.route('/model-predictions')
def model_predictions():
    try:
        test = build_test_predictions()
        step = max(1, int(np.ceil(len(test) / 300)))
        rows = []
        for _, row in test.iloc[::step].iterrows():
            rows.append({
                'time': row['time'].strftime('%Y-%m-%d %H:%M'),
                'actual': round(float(row['target']), 2),
                'raw': round(float(row['raw_prediction']), 2),
                'calibrated': round(float(row['calibrated_prediction']), 2),
                'persistence': round(float(row['persistence_pred']), 2)
            })
        return jsonify(evaluation_type='historical held-out test set', rows=rows)
    except Exception as exc:
        app.logger.exception('Model predictions failed')
        return jsonify(error='Could not build model predictions', details=str(exc)), 500


init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')))
