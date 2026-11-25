from flask import Flask, request, jsonify, render_template, make_response
import os
import time
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from collections import deque

import joblib
import numpy as np
import pandas as pd
import pytz
import requests
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, 'models')
DB_PATH = os.environ.get('ATMOS_DB_PATH', os.path.join(BASE_DIR, 'atmos.db'))
API_KEY = os.environ.get('OPENWEATHER_API_KEY', '')
LAT, LON = 31.515355, 76.878331
WEATHER_CACHE_TIME = 600
weather_cache = {'data': None, 'timestamp': 0}
weather_lock = threading.Lock()
regional_air_lock = threading.Lock()
REGIONAL_AIR_CACHE_TIME = 600
regional_air_cache = {'data': None, 'timestamp': 0}
data_lock = threading.Lock()
data_store = {'pm25_buffer': deque(maxlen=5), 'mq135_buffer': deque(maxlen=5), 'lpr_buffer': deque(maxlen=5)}


def db_connect():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db_connect() as con:
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


def recent_values(field):
    # Only fixed internal identifiers, never user-supplied SQL column names.
    if field not in ('pm25', 'mq135', 'zph02_lpr_pct'):
        raise ValueError('Invalid field')
    with db_connect() as con:
        rows = con.execute(
            f'SELECT {field} FROM readings WHERE {field} IS NOT NULL ORDER BY id DESC LIMIT 5'
        ).fetchall()
    return [float(row[0]) for row in rows]


def latest_reading():
    with db_connect() as con:
        row = con.execute('SELECT * FROM readings ORDER BY id DESC LIMIT 1').fetchone()
    return dict(row) if row else None


def weather():
    with weather_lock:
        if weather_cache['data'] is not None and time.time() - weather_cache['timestamp'] < WEATHER_CACHE_TIME:
            return weather_cache['data']
    fallback = {'temp': None, 'humidity': None, 'wind': None}
    if not API_KEY:
        return weather_cache['data'] or fallback
    try:
        response = requests.get('https://api.openweathermap.org/data/2.5/weather', params={
            'lat': LAT, 'lon': LON, 'appid': API_KEY, 'units': 'metric'
        }, timeout=8)
        response.raise_for_status()
        d = response.json()
        result = {
            'temp': round(float(d['main']['temp']), 1),
            'humidity': int(d['main']['humidity']),
            'wind': round(float(d['wind']['speed']) * 3.6, 1),
        }
        with weather_lock:
            weather_cache.update(data=result, timestamp=time.time())
        return result
    except (requests.RequestException, KeyError, TypeError, ValueError):
        app.logger.exception('Weather request failed')
        return weather_cache['data'] or fallback


def regional_air_quality():
    """Independent modeled regional PM2.5 for context, not ZPH02 calibration.

    OpenWeather's main.aqi is a 1-5 category, not the dashboard's 0-300
    PM2.5-based index. We use the returned PM2.5 concentration instead.
    """
    with regional_air_lock:
        cached = regional_air_cache['data']
        if cached is not None and time.time() - regional_air_cache['timestamp'] < REGIONAL_AIR_CACHE_TIME:
            return dict(cached)

    fallback = {'pm25': None, 'aqi': None, 'observed_at': None, 'status': 'unavailable'}
    if not API_KEY:
        return dict(fallback, status='api_key_missing')

    try:
        response = requests.get(
            'https://api.openweathermap.org/data/2.5/air_pollution',
            params={'lat': LAT, 'lon': LON, 'appid': API_KEY},
            timeout=6,
        )
        response.raise_for_status()
        observation = response.json()['list'][0]
        concentration = float(observation['components']['pm2_5'])
        observed_epoch = int(observation['dt'])
        if not np.isfinite(concentration) or concentration < 0 or observed_epoch <= 0:
            raise ValueError('Invalid regional PM2.5 observation')
        result = {
            'pm25': round(concentration, 2),
            'aqi': calculate_aqi(concentration),
            'observed_at': datetime.fromtimestamp(observed_epoch, timezone.utc).isoformat(),
            'status': 'ok' if -900 <= time.time() - observed_epoch <= 10800 else 'stale',
        }
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, OverflowError, OSError):
        app.logger.warning('Regional air quality request unavailable', exc_info=True)
        with regional_air_lock:
            previous = regional_air_cache['data']
        result = dict(previous, status='stale') if previous and previous['pm25'] is not None else fallback

    with regional_air_lock:
        regional_air_cache.update(data=result, timestamp=time.time())
    return dict(result)


def optional_number(d, key, low, high):
    value = d.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f'{key} must be numeric')
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{key} must be numeric')
    if not np.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{key} must be finite and between {low} and {high}')
    return value


def get_smoothed():
    def avg(field):
        vals = recent_values(field)
        return round(sum(vals) / len(vals), 1) if vals else None
    return avg('pm25'), avg('mq135'), avg('zph02_lpr_pct')


def calculate_aqi(pm):
    # Preserves the project's original approximate PM2.5-to-AQI conversion.
    if pm is None or not np.isfinite(pm):
        return None
    pm = max(0.0, float(pm))
    if pm <= 12:
        return round(50 / 12 * pm)
    if pm <= 35.4:
        return round((100 - 51) / (35.4 - 12.1) * (pm - 12.1) + 51)
    if pm <= 55.4:
        return round((150 - 101) / (55.4 - 35.5) * (pm - 35.5) + 101)
    if pm <= 150:
        return round((200 - 151) / (150 - 55.5) * (pm - 55.5) + 151)
    if pm <= 250:
        return round((300 - 201) / (250 - 150.5) * (pm - 150.5) + 201)
    return 300


@app.route('/')
def home():
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/update', methods=['POST'])
def update():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify(error='Expected a JSON object'), 400
    try:
        pm25 = optional_number(d, 'pm25', 0, 500)
        mq135 = optional_number(d, 'mq135', 0, 4095)
        if mq135 is None:
            mq135 = optional_number(d, 'mq135_adc', 0, 4095)
        if mq135 is None:
            mq135 = optional_number(d, 'gas', 0, 4095)
        lpr = optional_number(d, 'zph02_lpr_pct', 0, 100)
        volts = optional_number(d, 'mq135_volts', 0, 5.5)
        gas_ratio = optional_number(d, 'gas_ratio', 0, 1e9)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if pm25 is None and mq135 is None and lpr is None:
        return jsonify(error='At least one sensor reading is required'), 400
    node_id = str(d.get('node_id') or 'ATMOS_ESP32')[:100]
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        with db_connect() as con:
            con.execute('''INSERT INTO readings
                (timestamp, node_id, pm25, mq135, zph02_lpr_pct, mq135_volts, gas_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (timestamp, node_id, pm25, mq135, lpr, volts, gas_ratio))
    except sqlite3.Error:
        app.logger.exception('Could not save sensor reading')
        return jsonify(error='Could not save sensor reading'), 500
    return jsonify(status='ok', message='Sensor data received', received={
        'pm25': pm25, 'mq135': mq135, 'zph02_lpr_pct': lpr
    }, pm25_available=pm25 is not None), 200


@app.route('/data')
def data():
    pm25, mq135, lpr = get_smoothed()
    aqi = calculate_aqi(pm25)
    w = weather()
    regional_air = regional_air_quality()
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    forecast_time = [(now + timedelta(minutes=m)).strftime('%I:%M %p') for m in (5, 10, 15, 20)]
    # Historical UI placeholder, NOT an actual ML forecast.
    forecast = [max(aqi - 2, 0), max(aqi - 1, 0), aqi + 1, aqi] if aqi is not None else []
    latest = latest_reading()
    calibrated_pm25, calibrated_aqi, calibration_status = live_calibrated_estimate(pm25)
    dataset_pm25 = None
    dataset_extrapolated = None
    if calibration_status not in ('waiting_for_zph02_pm25', 'stale_zph02_pm25') and pm25 is not None:
        # Hamirpur optical-to-BAM linear fit from train_models.py, first 3,093
        # chronological pairs. Transfer to the live ZPH02 is experimental.
        dataset_pm25 = round(0.4826716982549565 * pm25 + 6.554140236696278, 2)
        dataset_extrapolated = not 5.65 <= pm25 <= 210.95
    return jsonify(
        dataset_estimated_pm25=dataset_pm25, dataset_estimated_aqi=calculate_aqi(dataset_pm25),
        dataset_extrapolated=dataset_extrapolated,
        regional_pm25=regional_air['pm25'],
        regional_pm25_aqi=regional_air['aqi'],
        regional_air_observed_at=regional_air['observed_at'],
        regional_air_status=regional_air['status'],
        regional_air_source='OpenWeather modeled regional PM2.5; not official or ZPH02 calibration',
        pm25=pm25, mq135=mq135, zph02_lpr_pct=lpr,
        calibrated_pm25=calibrated_pm25, calibrated_aqi=calibrated_aqi,
        calibration_status=calibration_status,
        calibrated_aqi_basis='PM2.5-only indicative dashboard conversion; not official overall AQI',
        reference_predicted_aqi=None,
        reference_forecast_status='Historical model only; no live BAM station data',
        predicted_aqi=aqi, forecast=forecast, forecast_time=forecast_time,
        forecast_type='illustrative, not ML prediction',
        temp=w['temp'], humidity=w['humidity'], wind=w['wind'],
        lat=LAT, lon=LON, pm25_available=pm25 is not None,
        mq135_available=mq135 is not None,
        mq135_unit='raw ADC counts',
        last_update=latest['timestamp'] if latest else None,
        node_id=latest['node_id'] if latest else None
    )


@app.route('/health')
def health():
    return jsonify(status='ok', service='ATMOS')


# ============================================
# HISTORICAL MODEL COMPARISON (NOT LIVE AQI)
# ============================================
# Load on demand: missing model files must not stop live ESP32 ingestion.

def load_model_resources():
    a = joblib.load(os.path.join(MODEL_DIR, 'model_A_raw.pkl'))
    b = joblib.load(os.path.join(MODEL_DIR, 'model_B_calibrated.pkl'))
    calibration = joblib.load(os.path.join(MODEL_DIR, 'calibration_model.pkl'))
    history = pd.read_csv(os.path.join(BASE_DIR, 'model_history.csv'), parse_dates=['time'])
    return a, b, calibration, history


def build_test_predictions():
    model_A_raw, model_B_calibrated, calibration_model, model_history = load_model_resources()
    df = model_history.copy().sort_values('time').reset_index(drop=True)
    cal_features = ['raw_pm25', 'temp', 'rh']
    df['calibrated_pm25'] = calibration_model.predict(df[cal_features])
    for lag in range(1, 25):
        df[f'raw_lag_{lag}'] = df['raw_pm25'].shift(lag)
        df[f'cal_lag_{lag}'] = df['calibrated_pm25'].shift(lag)
    df['hour_sin'] = np.sin(2 * np.pi * df['time'].dt.hour / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['time'].dt.hour / 24)
    df['target'] = df['bam_pm25'].shift(-1)
    df['persistence_pred'] = df['bam_pm25']
    df = df.dropna().reset_index(drop=True)
    test_start = int(len(df) * 0.85)
    test = df.iloc[test_start:].copy()
    if len(test) < 2:
        raise ValueError('Insufficient held-out test rows')
    raw_cols = [f'raw_lag_{i}' for i in range(1, 25)] + ['hour_sin', 'hour_cos']
    cal_cols = [f'cal_lag_{i}' for i in range(1, 25)] + ['hour_sin', 'hour_cos']
    test['raw_prediction'] = model_A_raw.predict(test[raw_cols])
    test['calibrated_prediction'] = model_B_calibrated.predict(test[cal_cols])
    return test


def regression_metrics(actual, predicted):
    return {
        'rmse': float(np.sqrt(mean_squared_error(actual, predicted))),
        'mae': float(mean_absolute_error(actual, predicted)),
        'r2': float(r2_score(actual, predicted))
    }


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
        return jsonify(
            evaluation_type='historical held-out test set',
            target='next-hour reference BAM PM2.5 (µg/m³)',
            models=metrics,
            improvement={
                'rmse_percent': float((raw['rmse'] - calibrated['rmse']) / raw['rmse'] * 100) if raw['rmse'] else None,
                'mae_percent': float((raw['mae'] - calibrated['mae']) / raw['mae'] * 100) if raw['mae'] else None,
                'r2_absolute': float(calibrated['r2'] - raw['r2'])
            },
            models_loaded=['model_A_raw.pkl', 'model_B_calibrated.pkl', 'calibration_model.pkl'],
            test_rows=int(len(test)),
            note='Saved models were evaluated on historical held-out data, not live sensor readings.'
        )
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
        return jsonify(
            evaluation_type='historical held-out test set',
            aqi_type='PM2.5-derived estimate using the dashboard conversion function',
            note='Historical comparison, not a live future forecast or official overall AQI.',
            rows=rows
        )
    except Exception as exc:
        app.logger.exception('Historical AQI prediction chart failed')
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
        app.logger.exception('Prediction chart data failed')
        return jsonify(error='Could not build prediction chart', details=str(exc)), 500




# ============================================
# DATASET CALIBRATION & HISTORICAL REFERENCE MODEL
# ============================================
# Critical distinction:
#   station_dataset_calibrators.joblib represents the OTHER optical sensor
#   in BAM_PM25_Dataset.csv, NOT your ZPH02.
#   It is deliberately never applied in /data to your ESP32.

import csv
import json

DATASET_CALIBRATION_TEST_CSV = os.path.join(BASE_DIR, 'results', 'historical_calibration_test.csv')
REFERENCE_FORECAST_TEST_CSV = os.path.join(BASE_DIR, 'results', 'historical_reference_forecast_test.csv')
DATASET_MODEL_METRICS_JSON = os.path.join(BASE_DIR, 'results', 'model_metrics.json')
VALIDATED_ZPH02_MODEL = os.path.join(MODEL_DIR, 'atmos_zph02_calibration.joblib')


def latest_valid_pm25_age_seconds():
    with db_connect() as con:
        row = con.execute(
            'SELECT timestamp FROM readings WHERE pm25 IS NOT NULL ORDER BY id DESC LIMIT 1'
        ).fetchone()
    if not row:
        return None
    try:
        timestamp = datetime.fromisoformat(row[0])
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
    except (ValueError, TypeError):
        return None


def live_calibrated_estimate(raw_zph02_pm25):
    """Return None until REAL paired ZPH02/reference calibration has been validated.

    An explicitly device-specific, independently validated model may be added
    as models/atmos_zph02_calibration.joblib in a future deployment.
    The models trained from BAM_PM25_Dataset.csv DO NOT qualify.
    """
    if raw_zph02_pm25 is None:
        return None, None, 'waiting_for_zph02_pm25'
    age = latest_valid_pm25_age_seconds()
    if age is None or age > 300 or age < -60:
        return None, None, 'stale_zph02_pm25'
    if not os.path.exists(VALIDATED_ZPH02_MODEL):
        return None, None, 'awaiting_paired_zph02_reference_calibration'
    try:
        package = joblib.load(VALIDATED_ZPH02_MODEL)
        if (
            not isinstance(package, dict)
            or package.get('device') != 'ATMOS_ZPH02'
            or package.get('validated') is not True
        ):
            return None, None, 'zph02_model_not_verified'
        model = package['model']
        predicted_pm25 = float(model.predict(np.asarray([[raw_zph02_pm25]], dtype=float))[0])
        if not np.isfinite(predicted_pm25):
            return None, None, 'calibration_prediction_invalid'
        predicted_pm25 = round(max(0.0, predicted_pm25), 2)
        # Historical site's simplified PM2.5-derived AQI conversion is retained
        # for compatibility. Not an official Indian overall AQI calculation.
        return predicted_pm25, calculate_aqi(predicted_pm25), 'calibrated_with_zph02_model'
    except Exception:
        app.logger.exception('Live ZPH02 model inference failed')
        return None, None, 'calibration_model_error'


def read_historical_rows(csv_path, site, limit=300):
    if not os.path.isfile(csv_path):
        raise FileNotFoundError('Run train_models.py and deploy results/ CSV files first')
    with open(csv_path, encoding='utf-8', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r.get('site') == site]
    if not rows:
        raise ValueError(f'No held-out rows for site {site!r}. Choose Hamirpur, Delhi or Bangalore.')
    step = max(1, int(np.ceil(len(rows) / limit)))
    sample = rows[::step]
    if sample[-1] is not rows[-1]:
        if len(sample) == limit:
            sample[-1] = rows[-1]
        else:
            sample.append(rows[-1])
    return sample, len(rows)


@app.route('/dataset-calibration-evaluation')
def dataset_calibration_evaluation():
    """Quality metrics for the DATASET optical sensor, not live ATMOS."""
    try:
        with open(DATASET_MODEL_METRICS_JSON, encoding='utf-8') as f:
            metrics_doc = json.load(f)
        return jsonify(
            evaluation_type='historical held-out calibration test',
            scope='uploaded paired optical/BAM dataset; NOT ATMOS ZPH02',
            sites=metrics_doc['calibration'],
            sample_count=metrics_doc['total_valid_paired_rows'],
            caveat='Models cannot be assumed to calibrate an unmeasured ZPH02 device.'
        )
    except (OSError, KeyError, ValueError) as exc:
        return jsonify(error='Calibration evaluation unavailable', details=str(exc)), 503


@app.route('/historical-dataset-calibration')
def historical_dataset_calibration():
    """Show REAL historical example of raw vs dataset-calibrated BAM PM2.5."""
    site = request.args.get('site', 'Hamirpur')
    if site not in ('Hamirpur', 'Delhi', 'Bangalore'):
        return jsonify(error='Choose site Hamirpur, Delhi or Bangalore'), 400
    try:
        rows, count = read_historical_rows(DATASET_CALIBRATION_TEST_CSV, site)
        readings = []
        for r in rows:
            raw = float(r['raw_pm25'])
            calibrated = float(r['dataset_calibrated_pm25'])
            reference = float(r['bam_reference_pm25'])
            readings.append({
                'time': r['time'], 'site': site,
                'raw_pm25': raw,
                'dataset_calibrated_pm25': calibrated,
                'bam_reference_pm25': reference,
                'raw_aqi_estimate': calculate_aqi(raw),
                'dataset_calibrated_aqi_estimate': calculate_aqi(calibrated),
                'bam_reference_aqi_estimate': calculate_aqi(reference),
            })
        return jsonify(
            type='HISTORICAL DATASET CALIBRATION, NOT LIVE DEVICE',
            site=site, available_test_rows=count,
            aqi_note='Indicative PM2.5-based app index from 1-hour concentrations; not an official 24-hour overall CPCB AQI.',
            rows=readings,
            latest_example=readings[-1] if readings else None
        )
    except (OSError, ValueError, KeyError) as exc:
        return jsonify(error='Historical dataset results unavailable', details=str(exc)), 503


@app.route('/reference-forecast-evaluation')
def reference_forecast_evaluation():
    try:
        with open(DATASET_MODEL_METRICS_JSON, encoding='utf-8') as f:
            doc = json.load(f)
        return jsonify(
            evaluation_type='historical held-out next-hour BAM PM2.5 forecast',
            **doc['reference_forecasting']
        )
    except (OSError, KeyError, ValueError) as exc:
        return jsonify(error='Reference model evaluation unavailable', details=str(exc)), 503


@app.route('/historical-reference-forecast')
def historical_reference_forecast():
    site = request.args.get('site', 'Hamirpur')
    if site not in ('Hamirpur', 'Delhi', 'Bangalore'):
        return jsonify(error='Choose site Hamirpur, Delhi or Bangalore'), 400
    try:
        rows, count = read_historical_rows(REFERENCE_FORECAST_TEST_CSV, site)
        output = []
        for r in rows:
            actual = float(r['bam_reference_pm25'])
            forecast = float(r['forecast_pm25'])
            output.append({
                'time': r['time'], 'site': site,
                'reference_pm25': actual,
                'forecast_pm25': forecast,
                'reference_aqi_estimate': calculate_aqi(actual),
                'forecast_aqi_estimate': calculate_aqi(forecast),
            })
        return jsonify(
            type='HISTORICAL NEXT-HOUR FORECAST - NOT CURRENT',
            site=site, available_test_rows=count,
            aqi_note='Indicative PM2.5-only index from hourly concentration, not official overall AQI.',
            rows=output,
            latest_example=output[-1] if output else None
        )
    except (OSError, ValueError, KeyError) as exc:
        return jsonify(error='Historical forecasts unavailable', details=str(exc)), 503


# Gunicorn imports app without running __main__.
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
