# Time frame: Daily
# Morning Positive Gap Scanner
# NSE Pre-Open + Daily Liquidity Filter

from flask import Flask, render_template_string
import requests
from datetime import datetime

app = Flask(__name__)

NSE_URL = "https://www.nseindia.com/api/market-data-pre-open?key=ALL"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/"
}

HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Morning Positive Gap Scanner</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: Arial; margin: 15px; background:#111; color:white; }
h2 { color:#00e5ff; }
button { padding:12px 18px; margin-bottom:15px; }
table { width:100%; border-collapse:collapse; }
th,td { padding:9px; border-bottom:1px solid #444; text-align:right; }
th { cursor:pointer; color:#00e5ff; }
td:first-child,td:nth-child(2) { text-align:left; }
.gap { color:#00ff88; font-weight:bold; }
</style>
</head>

<body>

<h2>🚀 MORNING POSITIVE GAP</h2>

<p>Time frame: Daily / NSE Pre-Open</p>

<button onclick="location.reload()">🔄 Refresh Scanner</button>

<table id="stocks">
<thead>
<tr>
<th>Stock</th>
<th>Symbol</th>
<th onclick="sortTable(2)">Gap % ↕</th>
<th>Open</th>
<th>Prev Close</th>
</tr>
</thead>

<tbody>
{% for s in stocks %}
<tr>
<td>{{ s.symbol }}</td>
<td>{{ s.symbol }}</td>
<td class="gap">{{ "%.2f"|format(s.gap) }}%</td>
<td>{{ s.open }}</td>
<td>{{ s.prev_close }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<script>
function sortTable(n) {
    let table = document.getElementById("stocks");
    let rows = Array.from(table.rows).slice(1);

    rows.sort(function(a,b) {
        return parseFloat(b.cells[n].innerText) -
               parseFloat(a.cells[n].innerText);
    });

    rows.forEach(row => table.tBodies[0].appendChild(row));
}
</script>

</body>
</html>
"""

def get_preopen_data():

    session = requests.Session()

    try:
        session.get(
            "https://www.nseindia.com/",
            headers=HEADERS,
            timeout=10
        )

        response = session.get(
            NSE_URL,
            headers=HEADERS,
            timeout=15
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:
        print("NSE ERROR:", e)
        return {"data": []}


@app.route("/")
def scanner():

    data = get_preopen_data()

    stocks = []

    for item in data.get("data", []):

        meta = item.get("metadata", {})
        price = item.get("priceInfo", {})

        symbol = meta.get("symbol")
        series = meta.get("series")

        open_price = price.get("open")
        prev_close = price.get("previousClose")

        if not symbol or not open_price or not prev_close:
            continue

        # NSE Equity only
        if series != "EQ":
            continue

        # Price filter
        if open_price <= 20:
            continue

        # Positive Gap %
        gap = ((open_price - prev_close) / prev_close) * 100

        # Minimum 1% gap-up
        if gap < 1:
            continue

        stocks.append({
            "symbol": symbol,
            "open": open_price,
            "prev_close": prev_close,
            "gap": gap
        })

    # Largest Gap first
    stocks.sort(key=lambda x: x["gap"], reverse=True)

    return render_template_string(
        HTML,
        stocks=stocks
    )


# Time frame: Daily / NSE Pre-Open

if __name__ == "__main__":
    import os
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
