# Time frame: Daily / Opening Gap + 20-Day Liquidity

from flask import Flask, render_template_string
import requests
import csv
import io
import os
from datetime import datetime, timedelta

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/"
}

HOME = "https://www.nseindia.com/"
BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv"
ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"


def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        session.get(HOME, timeout=10)
    except Exception:
        pass

    return session


def get_csv(session, url):
    try:
        r = session.get(url, timeout=15)

        if r.status_code != 200:
            return []

        text = r.text.strip()

        if len(text) < 100:
            return []

        reader = csv.DictReader(io.StringIO(text))

        rows = []

        for row in reader:
            clean = {}

            for key, value in row.items():
                if key:
                    clean[key.strip().upper()] = (
                        value.strip() if value else ""
                    )

            rows.append(clean)

        return rows

    except Exception:
        return []


def number(value):
    try:
        return float(
            str(value)
            .replace(",", "")
            .strip()
        )
    except Exception:
        return 0.0


def get_bhavcopy(session, date):

    date_text = date.strftime("%d%m%Y")

    url = BHAV_URL.format(date_text)

    rows = get_csv(session, url)

    if not rows:
        return []

    # Only NSE Equity
    rows = [
        r for r in rows
        if r.get("SERIES", "").upper() == "EQ"
    ]

    return rows


def get_etf_symbols(session):

    rows = get_csv(session, ETF_URL)

    symbols = set()

    for row in rows:

        symbol = (
            row.get("SYMBOL")
            or row.get("SCRIP CODE")
            or ""
        )

        symbol = symbol.strip().upper()

        if symbol:
            symbols.add(symbol)

    return symbols


def scan():

    session = get_session()

    today = datetime.now()

    # --------------------------------------------------
    # 1. Get latest available trading-day Bhavcopy
    # --------------------------------------------------

    current = []

    current_date = today

    for _ in range(7):

        current = get_bhavcopy(
            session,
            current_date
        )

        if len(current) > 50:
            break

        current_date -= timedelta(days=1)

    if not current:
        return []

    # --------------------------------------------------
    # 2. ETF list
    # --------------------------------------------------

    etf_symbols = get_etf_symbols(session)

    # --------------------------------------------------
    # 3. First two Chartink conditions
    #
    # Close > 20
    # Open > Previous Close × 1.01
    # --------------------------------------------------

    candidates = []

    for row in current:

        symbol = row.get("SYMBOL", "").strip().upper()

        if not symbol:
            continue

        # Remove ETFs
        if symbol in etf_symbols:
            continue

        open_price = number(
            row.get("OPEN_PRICE")
        )

        previous_close = number(
            row.get("PREV_CLOSE")
        )

        close_price = number(
            row.get("CLOSE_PRICE")
        )

        if open_price <= 20:
            continue

        if previous_close <= 0:
            continue

        if close_price <= 20:
            continue

        gap = (
            (open_price - previous_close)
            / previous_close
        ) * 100

        if gap < 1:
            continue

        candidates.append({
            "symbol": symbol,
            "name": (
                row.get("SECURITY")
                or row.get("SECURITY_NAME")
                or symbol
            ).strip(),
            "open": open_price,
            "previous_close": previous_close,
            "close": close_price,
            "gap": gap
        })

    if not candidates:
        return []

    # --------------------------------------------------
    # 4. Collect 20 trading days of volume
    #
    # Only candidates are checked.
    # This keeps the scanner lighter.
    # --------------------------------------------------

    candidate_symbols = {
        x["symbol"] for x in candidates
    }

    volume_history = {
        symbol: []
        for symbol in candidate_symbols
    }

    days_found = 0
    check_date = current_date

    while days_found < 20:

        rows = get_bhavcopy(
            session,
            check_date
        )

        if rows:

            for row in rows:

                symbol = row.get(
                    "SYMBOL", ""
                ).strip().upper()

                if symbol not in candidate_symbols:
                    continue

                volume = number(
                    row.get("TTL_TRD_QNTY")
                )

                if volume > 0:

                    volume_history[
                        symbol
                    ].append(volume)

            days_found += 1

        check_date -= timedelta(days=1)

        # Safety limit
        if (current_date - check_date).days > 45:
            break

    # --------------------------------------------------
    # 5. EXACT Chartink-style liquidity condition
    #
    # Current Close × SMA(Volume,20)
    # > ₹100,000,000
    #
    # ₹10 Crore = ₹100,000,000
    # --------------------------------------------------

    results = []

    for stock in candidates:

        symbol = stock["symbol"]

        volumes = volume_history.get(
            symbol,
            []
        )

        if len(volumes) < 20:
            continue

        # 20-day SMA Volume
        avg_volume = sum(volumes[:20]) / 20

        # Chartink condition
        turnover = (
            stock["close"] * avg_volume
        )

        if turnover <= 100000000:
            continue

        results.append({
            "name": stock["name"],
            "symbol": symbol,
            "gap": stock["gap"],
            "open": stock["open"],
            "previous_close": stock["previous_close"],
            "close": stock["close"],
            "avg_volume": avg_volume,
            "turnover": turnover
        })

    # Highest Gap first
    results.sort(
        key=lambda x: x["gap"],
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
    border: none;
    border-radius: 8px;
}

.tablebox {
    overflow-x: auto;
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
    white-space: nowrap;
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

<b>Today's Opening Gap</b>

<br><br>

Gap % =
(Open - Previous Close) / Previous Close × 100

<br><br>

<b>Filters:</b>

<br>

Price > ₹20

<br>

Positive Gap ≥ 1%

<br>

Close × 20-Day Average Volume > ₹10 Crore

<br>

ETF excluded

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

<div class="tablebox">

<table>

<tr>

<th>Sr.</th>
<th>Stock Name</th>
<th>Symbol</th>
<th>Gap %</th>
<th>Open</th>
<th>Previous Close</th>
<th>Close</th>
<th>20D Avg Volume</th>
<th>Avg Turnover</th>

</tr>

{% for r in results %}

<tr>

<td>{{ loop.index }}</td>

<td>{{ r["name"] }}</td>

<td>{{ r["symbol"] }}</td>

<td class="gap">
+{{ "%.2f"|format(r["gap"]) }}%
</td>

<td>
₹{{ "%.2f"|format(r["open"]) }}
</td>

<td>
₹{{ "%.2f"|format(r["previous_close"]) }}
</td>

<td>
₹{{ "%.2f"|format(r["close"]) }}
</td>

<td>
{{ "{:,.0f}".format(r["avg_volume"]) }}
</td>

<td>
₹{{ "{:,.0f}".format(r["turnover"]) }}
</td>

</tr>

{% endfor %}

</table>

</div>

</body>

</html>
"""


@app.route("/")
def home():

    results = scan()

    return render_template_string(
        HTML,
        results=results
    )


if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
