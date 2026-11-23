
import requests
import random
import time

# ATMOS Flask server
URL = "https://aqi-1-1l2h.onrender.com/update"

while True:

    # Generate simulated sensor values
    data = {
        "node_id": "ATMOS_TEST",
        "pm25": random.randint(10, 80),
        "mq135": random.randint(900, 1500)
    }

    try:
        response = requests.post(
            URL,
            json=data,
            timeout=15
        )

        print("Sent:", data)
        print("HTTP Status:", response.status_code)
        print("Server Response:", response.text)

        if response.status_code == 200:
            print("Data successfully received")
        else:
            print("Server rejected the data")

    except requests.exceptions.RequestException as e:
        print("Connection error:", e)

    print("--------------------------")

    time.sleep(10)
