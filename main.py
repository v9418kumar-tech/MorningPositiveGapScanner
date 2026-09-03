# Time frame: Daily / NSE Pre-Open + Full Day Gap Scanner

from flask import Flask, render_template_string
import requests
import os
from datetime import datetime, time

app = Flask(__name__)

NSE_HOME = "https://www.nseindia.com/"
PREOPEN_URL = "https://www.nseindia.com/api/market-data-pre-open?key=ALL"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Morning Positive Gap Scanner</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background: #f5f5f5;
        }

        h1 {
            margin-bottom: 5px;
        }

        .info {
            margin-bottom: 15px;
            font-size: 16px;
        }

        .error {
            background: #ffe0e0;
            border: 1px solid #cc0000;
            padding: 12px;
            margin: 15px 0;
            color: #900;
            border-radius: 6px;
        }

        .success {
            background: #e2f5e2;
            border: 1px solid #339933;
            padding: 10px;
            margin: 15px 0;
            border-radius: 6px;
        }

        button {
            padding: 10px 18px;
            font-size: 16px;
            cursor: pointer;
            margin-bottom: 15px;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            background: white;
        }

        th, td {
            border: 1px solid #ccc;
            padding: 8px;
            text-align: center;
        }

        th {
            background: #eeeeee;
            cursor: pointer;
        }

        tr:nth-child(even) {
            background: #fafafa;
        }

        .gap {
            font-weight: bold;
        }
    </style>
</head>

<body>

<h1>🚀 MORNING POSITIVE GAP</h1>

<div class="info">
    <b>Time frame:</b> Daily / NSE Pre-Open + Full Day
</div>

<form>
    <button type="submit">🔄 Refresh Scanner</button>
</form>

{% if error %}
<div class="error">
    <b>Scanner Error:</b><br>
    {{ error }}
</div>
{% endif %}

{% if message %}
<div class="success">
    {{ message }}
</div>
{% endif %}

{% if stocks %}
<table id="gapTable">
    <thead>
        <tr>
            <th>Sr.</th>
            <th>Stock Name</th>
            <th>Symbol</th>
            <th>Gap %</th>
            <th>Open</th>
            <th>Prev Close</th>
        </tr>
    </thead>

    <tbody>
    {% for stock in stocks %}
        <tr>
            <td>{{ loop.index }}</td>
            <td>{{ stock.name }}</td>
            <td>{{ stock.symbol }}</td>
            <td class="gap">{{ "%.2f"|format(stock.gap) }}%</td>
            <td>{{ stock.open }}</td>
            <td>{{ stock.prev_close }}</td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% endif %}

<script>
function sortGapDescending() {
    const table = document.getElementById("gapTable");
    if (!table) return;

    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));

    rows.sort(function(a, b) {
        const gapA = parseFloat(
            a.cells[3].innerText.replace("%", "")
        );
        const gapB = parseFloat(
            b.cells[3].innerText.replace("%", "")
        );

        return gapB - gapA;
    });

    rows.forEach(function(row) {
        tbody.appendChild(row);
    });

    rows.forEach(function(row, index) {
        row.cells[0].innerText = index + 1;
    });
}

sortGapDescending();
</script>

</body>
</html>
"""


def get_nse_preopen():
    """
    Time frame: Daily / NSE Pre-Open

    NSE Pre-Open data fetch.
    """

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        home = session.get(
            NSE_HOME,
            timeout=15
        )

        if home.status_code != 200:
            return None, f"NSE homepage HTTP status: {home.status_code}"

        response = session.get(
            PREOPEN_URL,
            timeout=20
        )

        if response.status_code != 200:
            return None, (
                f"NSE Pre-Open HTTP status: "
                f"{response.status_code}"
            )

        try:
            data = response.json()
        except Exception:
            return None, (
                "NSE ने JSON data नहीं भेजा। "
                f"Response शुरू होता है: {response.text[:200]}"
            )

        return data, None

    except requests.exceptions.RequestException as e:
        return None, f"NSE connection error: {str(e)}"


def parse_preopen(data):
    """
    Time frame: Daily / NSE Pre-Open
    """

    stocks = []

    if not data:
        return stocks

    records = data.get("data", [])

    if not isinstance(records, list):
        return stocks

    for item in records:

        metadata = item.get("metadata", {})
        price = item.get("priceInfo", {})

        symbol = metadata.get("symbol", "")
        series = metadata.get("series", "")

        open_price = price.get("open")
        prev_close = price.get("previousClose")

        if not symbol:
            continue

        if series != "EQ":
            continue

        try:
            open_price = float(open_price)
            prev_close = float(prev_close)
        except (TypeError, ValueError):
            continue

        if open_price <= 20:
            continue

        if prev_close <= 0:
            continue

        gap = ((open_price - prev_close) / prev_close) * 100

        if gap < 1:
            continue

        stocks.append({
            "name": metadata.get("companyName", symbol),
            "symbol": symbol,
            "gap": gap,
            "open": open_price,
            "prev_close": prev_close
        })

    stocks.sort(
        key=lambda x: x["gap"],
        reverse=True
    )

    return stocks


@app.route("/")
def scanner():

    now = datetime.now()
    current_time = now.time()

    data, error = get_nse_preopen()

    if error:
        return render_template_string(
            HTML,
            stocks=[],
            error=error,
            message=None
        )

    stocks = parse_preopen(data)

    if stocks:
        message = (
            f"NSE data received. "
            f"{len(stocks)} qualifying stocks found. "
            f"Gap % घटते क्रम में है."
        )
    else:
        message = (
            "NSE response मिला, लेकिन इस समय "
            "Pre-Open qualifying data उपलब्ध नहीं है. "
            "Pre-Open session 9:00–9:15 AM में होती है."
        )

    return render_template_string(
        HTML,
        stocks=stocks,
        error=None,
        message=message
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
