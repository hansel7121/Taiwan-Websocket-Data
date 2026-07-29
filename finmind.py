import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ["FINMIND_TOKEN"]

url = "https://api.finmindtrade.com/api/v4/data"
headers = {"Authorization": f"Bearer {TOKEN}"}

params = {
    "dataset": "TaiwanStockPriceTick",
    "data_id": "2330",
    "start_date": "2021-05-02",
}

resp = requests.get(url, headers=headers, params=params)
data = resp.json()
print(data)

df = pd.DataFrame(data["data"])
print(df.head(20))
print(f"\nTotal ticks: {len(df)}")