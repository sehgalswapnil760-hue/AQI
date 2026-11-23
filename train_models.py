"""ATMOS educational dataset models.

Train calibration from PAIRS of raw optical PM2.5 and BAM reference PM2.5,
within each dataset site, then train an historical next-hour BAM forecaster.
These are NOT calibration or operational predictions for an actual ATMOS ZPH02.

Usage:
    python train_models.py --csv BAM_PM25_Dataset.csv --output .
"""
import argparse
import copy
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def metrics(y, pred):
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    return {
        "mae": round(float(mean_absolute_error(y, pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y, pred))), 4),
        "r2": round(float(r2_score(y, pred)), 4),
        "bias_pred_minus_ref": round(float(np.mean(pred - y)), 4),
    }


def split_indices(n):
    # Chronological 70/15/15. No random shuffle or leakage from test data.
    a, b = int(n * 0.70), int(n * 0.85)
    return slice(0, a), slice(a, b), slice(b, n)


def calibration_candidates():
    return {
        "linear": LinearRegression(),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            max_iter=160, max_leaf_nodes=15, max_depth=4,
            learning_rate=0.055, min_samples_leaf=35,
            l2_regularization=1.0, random_state=42,
        ),
    }


def load_paired_csv(path):
    df = pd.read_csv(path)
    cols = ["Timestamp", "BAM_PM2.5_ug_m3", "Raw_PM2.5_ug_m3", "Site"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(missing))
    df = df[cols].copy()
    df["time"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    for col in ["BAM_PM2.5_ug_m3", "Raw_PM2.5_ug_m3"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time", "Site", "BAM_PM2.5_ug_m3", "Raw_PM2.5_ug_m3"])
    df = df.loc[
        np.isfinite(df["Raw_PM2.5_ug_m3"])
        & np.isfinite(df["BAM_PM2.5_ug_m3"])
        & df["Raw_PM2.5_ug_m3"].between(0, 2000)
        & df["BAM_PM2.5_ug_m3"].between(0, 2000)
    ]
    df["Site"] = df["Site"].astype(str).str.strip()
    df = df.sort_values(["Site", "time"]).drop_duplicates(["Site", "time"], keep="last")
    return df.reset_index(drop=True)


def train_calibrators(df, output):
    results = {}
    saved = {}
    prediction_rows = []
    for site, g in df.groupby("Site", sort=True):
        g = g.sort_values("time").reset_index(drop=True)
        if len(g) < 100:
            continue
        x = g[["Raw_PM2.5_ug_m3"]].to_numpy(dtype=float)
        y = g["BAM_PM2.5_ug_m3"].to_numpy(dtype=float)
        tr, va, te = split_indices(len(g))
        scores = {}
        for name, candidate in calibration_candidates().items():
            model = clone(candidate)
            model.fit(x[tr], y[tr])
            scores[name] = mean_absolute_error(y[va], np.clip(model.predict(x[va]), 0, None))
        selected_name = min(scores, key=scores.get)
        model = clone(calibration_candidates()[selected_name])
        model.fit(x[:va.stop], y[:va.stop])
        pred = np.clip(model.predict(x[te]), 0, None)
        raw = x[te, 0]
        actual = y[te]
        saved[site] = model
        results[site] = {
            "rows": int(len(g)),
            "train_and_validation_rows": int(va.stop),
            "held_out_test_rows": int(len(actual)),
            "test_range": [g.iloc[te.start]["time"].isoformat(), g.iloc[-1]["time"].isoformat()],
            "selected_model": selected_name,
            "validation_mae_candidates": {k: round(float(v), 4) for k, v in scores.items()},
            "raw_unadjusted_test": metrics(actual, raw),
            "dataset_calibrated_test": metrics(actual, pred),
        }
        for row, prediction in zip(g.iloc[te].itertuples(index=False), pred):
            prediction_rows.append({
                "site": site,
                "time": row.time.isoformat(),
                "raw_pm25": round(float(row[2]), 3),
                "bam_reference_pm25": round(float(row[1]), 3),
                "dataset_calibrated_pm25": round(float(prediction), 3),
                "raw_minus_reference": round(float(row[2] - row[1]), 3),
                "calibrated_minus_reference": round(float(prediction - row[1]), 3),
            })
    joblib.dump({
        "scope": "dataset-paired-optical-sensor-only; NOT ATMOS-ZPH02",
        "feature": "Raw_PM2.5_ug_m3",
        "models_by_site": saved,
    }, output / "models" / "station_dataset_calibrators.joblib")
    pd.DataFrame(prediction_rows).to_csv(output / "results" / "historical_calibration_test.csv", index=False)
    return results


def build_forecast_frame(df):
    parts = []
    for site, g in df.groupby("Site", sort=True):
        g = g.sort_values("time").reset_index(drop=True).copy()
        g["bam"] = g["BAM_PM2.5_ug_m3"].astype(float)
        gap_ok = g["time"].diff().eq(pd.Timedelta(hours=1))
        # Current+23 prior hours, plus the subsequent hour for target.
        contiguous = (gap_ok.rolling(window=23, min_periods=23).sum() == 23) & (gap_ok.shift(-1) == True)
        for lag in range(24):
            g[f"lag{lag}"] = g["bam"].shift(lag)
        g["target"] = g["bam"].shift(-1)
        next_time = g["time"] + pd.Timedelta(hours=1)
        g["hour_sin"] = np.sin(2 * np.pi * next_time.dt.hour / 24)
        g["hour_cos"] = np.cos(2 * np.pi * next_time.dt.hour / 24)
        g["year_sin"] = np.sin(2 * np.pi * next_time.dt.dayofyear / 365.25)
        g["year_cos"] = np.cos(2 * np.pi * next_time.dt.dayofyear / 365.25)
        g["target_time"] = next_time
        # Make station a categorical fixed dummy, to avoid mixing station baselines.
        for station_name in sorted(df["Site"].unique()):
            g[f"site_{station_name}"] = int(site == station_name)
        g = g.loc[contiguous].dropna(subset=["target"] + [f"lag{x}" for x in range(24)])
        if len(g) > 30:
            parts.append(g)
    if not parts:
        raise ValueError("Not enough uninterrupted 25-hour sequences to train a forecaster")
    return pd.concat(parts, ignore_index=True)


def train_forecaster(df, output):
    feature_names = [f"lag{i}" for i in range(24)] + ["hour_sin", "hour_cos", "year_sin", "year_cos"] + [f"site_{n}" for n in sorted(df["Site"].unique())]
    frame = build_forecast_frame(df)
    trn, val, tes = [], [], []
    site_counts = {}
    for site, g in frame.groupby("Site"):
        g = g.sort_values("target_time")
        tr, va, te = split_indices(len(g))
        trn.append(g.iloc[tr]); val.append(g.iloc[va]); tes.append(g.iloc[te])
        site_counts[site] = {"total_sequences": int(len(g)), "held_out_test": int(len(g.iloc[te]))}
    train = pd.concat(trn, ignore_index=True)
    valid = pd.concat(val, ignore_index=True)
    test = pd.concat(tes, ignore_index=True)
    candidates = {
        "ridge": Ridge(alpha=800.0),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            max_iter=140, max_depth=4, max_leaf_nodes=17,
            learning_rate=0.05, min_samples_leaf=30,
            l2_regularization=2.0, random_state=42,
        ),
    }
    scores = {}
    xtr, ytr = train[feature_names].to_numpy(dtype=float), train["target"].to_numpy(dtype=float)
    xv, yv = valid[feature_names].to_numpy(dtype=float), valid["target"].to_numpy(dtype=float)
    for name, candidate in candidates.items():
        model = clone(candidate).fit(xtr, ytr)
        scores[name] = float(mean_absolute_error(yv, np.clip(model.predict(xv), 0, None)))
    selected = min(scores, key=scores.get)
    combined = pd.concat([train, valid], ignore_index=True)
    final_model = clone(candidates[selected]).fit(combined[feature_names].to_numpy(dtype=float), combined["target"].to_numpy(dtype=float))
    pred = np.clip(final_model.predict(test[feature_names].to_numpy(dtype=float)), 0, None)
    actual = test["target"].to_numpy(dtype=float)
    baseline = test["lag0"].to_numpy(dtype=float)
    output_frame = pd.DataFrame({
        "site": test["Site"].tolist(),
        "time": test["target_time"].dt.strftime("%Y-%m-%dT%H:%M:%S").tolist(),
        "bam_reference_pm25": np.round(actual, 3),
        "previous_hour_bam_pm25": np.round(baseline, 3),
        "forecast_pm25": np.round(pred, 3),
    }).sort_values(["site", "time"])
    output_frame.to_csv(output / "results" / "historical_reference_forecast_test.csv", index=False)
    joblib.dump({
        "scope": "HISTORICAL NEXT HOUR BAM FORECAST (not live prediction)",
        "features": feature_names,
        "stations": sorted(df["Site"].unique()),
        "model": final_model,
    }, output / "models" / "historical_reference_forecaster.joblib")
    return {
        "selected_model": selected,
        "validation_mae_candidates": {k: round(v, 4) for k, v in scores.items()},
        "available_sequences_by_site": site_counts,
        "held_out_test_rows": int(len(test)),
        "persistence_test": metrics(actual, baseline),
        "forecast_test": metrics(actual, pred),
        "note": "Only historical forecasting performance. No station data after 2021; cannot generate a current forecast from these files alone.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="BAM_PM25_Dataset.csv")
    parser.add_argument("--output", default=".")
    args = parser.parse_args()
    out = Path(args.output)
    (out / "models").mkdir(parents=True, exist_ok=True)
    (out / "results").mkdir(parents=True, exist_ok=True)
    df = load_paired_csv(args.csv)
    calibration = train_calibrators(df, out)
    forecasting = train_forecaster(df, out)
    report = {
        "dataset": str(Path(args.csv).name),
        "total_valid_paired_rows": int(len(df)),
        "time_min": df["time"].min().isoformat(),
        "time_max": df["time"].max().isoformat(),
        "calibration": calibration,
        "reference_forecasting": forecasting,
        "important": [
            "Calibration models refer only to the dataset's paired optical sensor and BAM monitor by site.",
            "Do not apply these models directly to ATMOS ZPH02 without its own paired reference evaluation.",
            "Source contains historical observations, not live air quality or a validated current forecast.",
            "PM2.5-only AQI estimates are not official overall air quality indices.",
        ]
    }
    (out / "results" / "model_metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
