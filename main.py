# Time frame: Daily / Full Day Opening Gap + 20-Day Liquidity

from flask import Flask, render_template_string
import requests
import pandas as pd
from datetime import datetime, timedelta
from io import StringIO

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/csv,application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/"
}

NSE_HOME = "https://www.nseindia.com/"
BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv"
ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"


def get_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(NSE_HOME, timeout=10)
    except:
        pass
    return s


def get_bhavcopy(session, date):
    date_text = date.strftime("%d%m%Y")
    url = BHAV_URL.format(date_text)

    try:
        r = session.get(url, timeout=15)

        if r.status_code != 200:
            return None

        if len(r.text) < 1000:
            return None

        df = pd.read_csv(StringIO(r.text))
        df.columns = [str(c).strip().upper() for c in df.columns]

        return df

    except:
        return None


def main_scan():
    session = get_session()

    today = datetime.now()

    # Current / latest available Bhavcopy
    current = None

    for i in range(7):
        d = today - timedelta(days=i)
        current = get_bhavcopy(session, d)

        if current is not None and len(current) > 50:
            break

    if current is None:
        return []

    # Clean column names
    current.columns = [str(c).strip().upper() for c in current.columns]

    # Only NSE Equity
    if "SERIES" in current.columns:
        current = current[current["SERIES"].astype(str).str.strip() == "EQ"]

    # Numeric conversion
    for col in ["OPEN_PRICE", "PREV_CLOSE", "CLOSE_PRICE", "TTL_TRD_QNTY"]:
        if col in current.columns:
            current[col] = pd.to_numeric(
                current[col], errors="coerce"
            )

    current = current.dropna(
        subset=["OPEN_PRICE", "PREV_CLOSE"]
    )

    # Positive opening gap
    current["GAP"] = (
        (current["OPEN_PRICE"] - current["PREV_CLOSE"])
        / current["PREV_CLOSE"]
    ) * 100

    current = current[
        (current["OPEN_PRICE"] > 20) &
        (current["GAP"] >= 1)
    ].copy()

    # ---------------------------------------------------------
    # 20-Day Average Volume
    # ---------------------------------------------------------

    symbols = set(
        current["SYMBOL"].astype(str).str.strip()
    )

    volume_history = {}

    # Search previous trading days
    found_days = 0

    for days_back in range(1, 35):

        if found_days >= 20:
            break

        d = today - timedelta(days=days_back)

        df = get_bhavcopy(session, d)

        if df is None:
            continue

        df.columns = [
            str(c).strip().upper()
            for c in df.columns
        ]

        if "SERIES" not in df.columns:
            continue

        df = df[
            df["SERIES"].astype(str).str.strip() == "EQ"
        ]

        if "SYMBOL" not in df.columns:
            continue

        if "TTL_TRD_QNTY" not in df.columns:
            continue

        df["SYMBOL"] = (
            df["SYMBOL"].astype(str).str.strip()
        )

        df = df[df["SYMBOL"].isin(symbols)].copy()

        df["TTL_TRD_QNTY"] = pd.to_numeric(
            df["TTL_TRD_QNTY"],
            errors="coerce"
        )

        for _, row in df.iterrows():

            symbol = row["SYMBOL"]
            volume = row["TTL_TRD_QNTY"]

            if pd.isna(volume):
                continue

            if symbol not in volume_history:
                volume_history[symbol] = []

            volume_history[symbol].append(float(volume))

        found_days += 1

    # ---------------------------------------------------------
    # Third Condition:
    # Price × 20-Day Average Volume > ₹10 Crore
    # ---------------------------------------------------------

    results = []

    for _, row in current.iterrows():

        symbol = str(row["SYMBOL"]).strip()

        volumes = volume_history.get(symbol, [])

        if len(volumes) < 10:
            continue

        avg_volume = sum(volumes) / len(volumes)

        open_price = float(row["OPEN_PRICE"])

        liquidity_value = open_price * avg_volume

        # ₹10 Crore = ₹100,000,000
        if liquidity_value <= 100000000:
            continue

        results.append({
            "Stock Name": str(
                row.get("SECURITY", symbol)
            ).strip(),
            "Symbol": symbol,
            "Gap %": float(row["GAP"]),
            "Open": open_price,
            "Previous Close": float(row["PREV_CLOSE"]),
            "20D Avg Volume": avg_volume,
            "Avg Turnover": liquidity_value
        })

    results.sort(
        key=lambda x: x["Gap %"],
        reverse=True
    )

    return results


HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>Morning Positive Gap Scanner</title>

<style>

body {
    font-family: Arial, sans-serif;
    background: #f5f5f5;
    margin: 0;
    padding: 12px;
}

h1 {
    font-size: 24px;
}

.info {
    background: white;
    padding: 14px;
    border-radius: 10px;
    margin-bottom: 12px;
}

button {
    padding: 12px 18px;
    font-size: 16px;
    border: 0;
    border-radius: 8px;
}

table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    font-size: 14px;
}

th, td {
    border: 1px solid #ddd;
    padding: 8px;
    text-align: center;
}

th {
    background: #eeeeee;
}

.gap {
    font-weight: bold;
}

</style>
</head>

<body>

<h1>Morning Positive Gap Scanner</h1>

<div class="info">

<b>Today's Opening Gap</b><br>

Gap % =
(Open - Previous Close) / Previous Close × 100

<br><br>

<b>Filters:</b><br>

Price > ₹20<br>
Positive Gap ≥ 1%<br>
20-Day Average Turnover > ₹10 Crore

</div>

<form>
<button type="submit">
Refresh Scanner
</button>
</form>

<br>

<div class="info">
<b>
Today's Open vs Previous Close.
Sorted by highest Positive Gap.
</b>
</div>

<table>

<tr>
<th>Sr.</th>
<th>Stock Name</th>
<th>Symbol</th>
<th>Gap %</th>
<th>Open</th>
<th>Previous Close</th>
<th>20D Avg Volume</th>
<th>Avg Turnover</th>
</tr>

{% for r in results %}

<tr>

<td>{{ loop.index }}</td>

<td>{{ r["Stock Name"] }}</td>

<td>{{ r["Symbol"] }}</td>

<td class="gap">
+{{ "%.2f"|format(r["Gap %"]) }}%
</td>

<td>
₹{{ "%.2f"|format(r["Open"]) }}
</td>

<td>
₹{{ "%.2f"|format(r["Previous Close"]) }}
</td>

<td>
{{ "{:,.0f}".format(r["20D Avg Volume"]) }}
</td>

<td>
₹{{ "{:,.0f}".format(r["Avg Turnover"]) }}
</td>

</tr>

{% endfor %}

</table>

</body>
</html>
"""


@app.route("/")
def home():

    results = main_scan()

    return render_template_string(
        HTML,
        results=results
    )


if __name__ == "__main__":

    import os

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
