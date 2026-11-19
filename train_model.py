import pandas as pd
from sklearn.linear_model import LinearRegression
import joblib


data = {

"pm25":[10,20,30,40,50,60,70,80],

"mq135":[100,120,140,160,180,200,220,240],

"voc":[5,10,15,20,25,30,35,40],

"aqi":[20,40,60,80,100,120,140,160]

}


df = pd.DataFrame(data)

X = df[[
"pm25",
"mq135",
"voc"
]]

y = df["aqi"]


model =LinearRegression()

model.fit(X,y)


joblib.dump(

model,

"aqi_model.pkl"

)

print(
"Model saved"
)