
import pandas as pd
import numpy as np
import joblib

from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score
)

# =====================================
# LOAD TRAINING DATA
# =====================================

# CSV must contain:
# pm25, mq135, voc, aqi
df = pd.read_csv("aqi_training_data.csv")

features = ["pm25", "mq135", "voc"]
target = "aqi"

df = df.dropna(subset=features + [target])

if len(df) < 20:
    raise ValueError(
        "Insufficient training samples. "
        "Collect more real sensor data."
    )

X = df[features]
y = df[target]

# =====================================
# TRAIN / TEST SPLIT
# =====================================

X_train, X_test, y_train, y_test = (
    train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42
    )
)

# =====================================
# TRAIN MODEL
# =====================================

model = LinearRegression()

model.fit(X_train, y_train)

# =====================================
# EVALUATE MODEL
# =====================================

predictions = model.predict(X_test)

mae = mean_absolute_error(
    y_test, predictions
)

rmse = np.sqrt(
    mean_squared_error(
        y_test, predictions
    )
)

r2 = r2_score(
    y_test, predictions
)

print("MODEL PERFORMANCE")
print("MAE:", round(mae, 3))
print("RMSE:", round(rmse, 3))
print("R2:", round(r2, 3))

# =====================================
# SAVE MODEL
# =====================================

joblib.dump(
    model,
    "aqi_model.pkl"
)

print("Model saved successfully")

# =====================================
# TEST PREDICTION
# =====================================

sample = pd.DataFrame(
    [[35, 1105, 20]],
    columns=features
)

predicted_aqi = model.predict(sample)[0]

predicted_aqi = np.clip(
    predicted_aqi,
    0,
    500
)

print(
    "Predicted AQI:",
    round(predicted_aqi)
)
