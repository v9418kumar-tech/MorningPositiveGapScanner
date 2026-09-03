# Time frame: Daily / Pre-Open Opening Gap
# Test mode: Today's Open vs Previous Close
# Morning mode: Pre-open data after approximately 9:08 AM

from flask import Flask, render_template_string
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import os
import time

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/"
}

NSE_UNIVERSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"

MIN_PRICE = 20
MIN_GAP = 1.0
MIN_TURNOVER = 100000000

HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Morning Positive Gap Scanner</title>
<style>
body {
    font-family: Arial, sans-serif;
    margin: 15px;
    background: #f5f5f5;
}
h2 {
    margin-bottom: 5px;
}
.info {
    background: white;
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 12px;
}
button {
    padding: 10px 16px;
    font-size: 16px;
    border: 0;
    border-radius: 6px;
    cursor: pointer;
}
table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    margin-top: 12px;
}
th, td {
    padding: 8px;
    border: 1px solid #ddd;
    text-align: center;
    white-space: nowrap;
}
th {
    background: #eeeeee;
}
.gap {
    font-weight: bold;
}
.small {
    font-size: 13px;
    color: #555;
}
</style>
</head>
<body>

<h2>Morning Positive Gap Scanner</h2>

<div class="info">
<b>Calculation:</b>
(Open - Previous Close) / Previous Close × 100
<br>
<b>Filters:</b>
Price &gt; ₹20 | Gap-Up ≥ 1% | Approx. turnover &gt; ₹10 crore
<br>
<span class="small">
Scanner uses today's Open and Previous Close for historical testing.
</span>
</div>

<form method="get">
<button type="submit">Refresh Scanner</button>
</form>

{% if message %}
<div class="info">{{ message }}</div>
{% endif %}

{% if rows %}
<table>
<tr>
<th>Sr.</th>
<th>Stock Name</th>
<th>Symbol</th>
<th>Gap %</th>
<th>Open</th>
<th>Previous Close</th>
<th>20D Avg Volume</th>
<th>Turnover</th>
</tr>

{% for r in rows %}
<tr>
<td>{{ loop.index }}</td>
<td>{{ r.name }}</td>
<td>{{ r.symbol }}</td>
<td class="gap">+{{ "%.2f"|format(r.gap) }}%</td>
<td>₹{{ "%.2f"|format(r.open) }}</td>
<td>₹{{ "%.2f"|format(r.prev_close) }}</td>
<td>{{ "{:,.0f}".format(r.avg_volume) }}</td>
<td>₹{{ "{:,.0f}".format(r.turnover) }}</td>
</tr>
{% endfor %}
</table>
{% endif %}

</body>
</html>
"""


def get_universe():
    """
    NSE Equity universe.
    ETF symbols are excluded where possible using SERIES = EQ.
    """
    try:
        r = requests.get(
            NSE_UNIVERSE_URL,
            headers=HEADERS,
            timeout=20
        )
        r.raise_for_status()

        df = pd.read_csv(
            pd.io.common.StringIO(r.text)
        )

        df.columns = [str(c).strip().upper() for c in df.columns]

        symbol_col = None
        name_col = None
        series_col = None

        for c in df.columns:
            if c == "SYMBOL":
                symbol_col = c
            if c in ["NAME OF COMPANY", "NAME_OF_COMPANY"]:
                name_col = c
            if c == "SERIES":
                series_col = c

        if not symbol_col:
            return []

        if series_col:
            df = df[df[series_col].astype(str).str.upper() == "EQ"]

        result = []

        for _, row in df.iterrows():
            symbol = str(row[symbol_col]).strip().upper()

            if not symbol or symbol == "NAN":
                continue

            name = symbol
            if name_col:
                name = str(row[name_col]).strip()

            result.append({
                "symbol": symbol,
                "name": name
            })

        return result

    except Exception:
        return []


def get_yahoo_data(stock):
    symbol = stock["symbol"]
    yahoo_symbol = symbol + ".NS"

    try:
        url = YAHOO_URL + yahoo_symbol

        params = {
            "range": "1mo",
            "interval": "1d",
            "events": "history"
        }

        r = requests.get(
            url,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0"
            },
            timeout=12
        )

        if r.status_code != 200:
            return None

        data = r.json()

        result = data.get("chart", {}).get("result")

        if not result:
            return None

        result = result[0]
        quote = result.get("indicators", {}).get("quote", [{}])[0]

        opens = quote.get("open", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])

        clean = []

        for o, c, v in zip(opens, closes, volumes):
            if o is not None and c is not None:
                clean.append({
                    "open": float(o),
                    "close": float(c),
                    "volume": float(v or 0)
                })

        if len(clean) < 2:
            return None

        today = clean[-1]
        previous = clean[-2]

        open_price = today["open"]
        prev_close = previous["close"]

        if prev_close <= 0 or open_price <= 0:
            return None

        gap = ((open_price - prev_close) / prev_close) * 100

        volumes_only = [
            x["volume"] for x in clean[:-1]
            if x["volume"] is not None
        ]

        last_20 = volumes_only[-20:]

        if not last_20:
            avg_volume = 0
        else:
            avg_volume = sum(last_20) / len(last_20)

        turnover = open_price * avg_volume

        if open_price <= MIN_PRICE:
            return None

        if gap < MIN_GAP:
            return None

        if turnover < MIN_TURNOVER:
            return None

        return {
            "name": stock["name"],
            "symbol": symbol,
            "gap": gap,
            "open": open_price,
            "prev_close": prev_close,
            "avg_volume": avg_volume,
            "turnover": turnover
        }

    except Exception:
        return None


def scan():
    universe = get_universe()

    if not universe:
        return [], "NSE equity list could not be downloaded."

    rows = []

    # Moderate number of parallel requests to avoid excessive load.
    with ThreadPoolExecutor(max_workers=10) as executor:

        futures = [
            executor.submit(get_yahoo_data, stock)
            for stock in universe
        ]

        for future in as_completed(futures):
            try:
                result = future.result()

                if result:
                    rows.append(result)

            except Exception:
                pass

    rows.sort(
        key=lambda x: x["gap"],
        reverse=True
    )

    message = (
        "Historical test: today's Open vs Previous Close. "
        "Results sorted by highest Positive Gap."
    )

    return rows, message


@app.route("/")
def home():

    rows, message = scan()

    return render_template_string(
        HTML,
        rows=rows,
        message=message
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port
    )
