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
