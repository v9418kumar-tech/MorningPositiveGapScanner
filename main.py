# Time frame: Daily / NSE Pre-Open

from flask import Flask, render_template_string
import requests
import os
from datetime import datetime

app = Flask(__name__)

NSE_HOME = "https://www.nseindia.com/"
NSE_API = "https://www.nseindia.com/api/market-data-pre-open?key=ALL"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive"
}


def get_gap_data():
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # First visit NSE homepage to obtain cookies
        home = session.get(NSE_HOME, timeout=15)

        # Then request pre-open data
        response = session.get(NSE_API, timeout=20)

        if response.status_code != 200:
            return [], f"NSE returned HTTP {response.status_code}"

        data = response.json()

        if "data" not in data:
            return [], "NSE response does not contain data"

        results = []

        for item in data["data"]:
            meta = item.get("metadata", {})
            price = item.get("detail", {}).get("preOpenMarket", {})

            symbol = meta.get("symbol", "")
            series = meta.get("series", "")

            previous_close = price.get("prevClose")
            open_price = price.get("iep")

            # NSE Equity only
            if series != "EQ":
                continue

            if not symbol or not previous_close or not open_price:
                continue

            try:
                previous_close = float(previous_close)
                open_price = float(open_price)
            except:
                continue

            # Price > Rs 20
            if open_price <= 20:
                continue

            # Positive gap-up >= 1%
            gap = ((open_price - previous_close) / previous_close) * 100

            if gap < 1:
                continue

            results.append({
                "symbol": symbol,
                "gap": gap,
                "open": open_price,
                "previous_close": previous_close
            })

        # Highest Gap % first
        results.sort(key=lambda x: x["gap"], reverse=True)

        return results, None

    except requests.exceptions.RequestException as e:
        return [], f"NSE connection error: {str(e)}"

    except Exception as e:
        return [], f"Scanner error: {str(e)}"


HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <title>Morning Positive Gap</title>

    <style>
        body {
            background: #111;
            color: white;
            font-family: Arial, sans-serif;
            margin: 20px;
        }

        h1 {
            color: #00d9ff;
            font-size: 30px;
        }

        .timeframe {
            font-size: 18px;
            margin-bottom: 20px;
        }

        button {
            padding: 12px 20px;
            font-size: 17px;
            cursor: pointer;
            margin-bottom: 20px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th {
            color: #00d9ff;
            font-size: 18px;
            padding: 12px 8px;
            border-bottom: 1px solid #555;
            cursor: pointer;
        }

        td {
            padding: 12px 8px;
            border-bottom: 1px solid #333;
            font-size: 16px;
        }

        .gap {
            color: #00ff66;
            font-weight: bold;
        }

        .error {
            color: #ff5555;
            font-size: 17px;
            margin-top: 20px;
        }

        .info {
            color: #aaa;
            margin-top: 15px;
        }
    </style>
</head>

<body>

<h1>🚀 MORNING POSITIVE GAP</h1>

<div class="timeframe">
    Time frame: Daily / NSE Pre-Open
</div>

<form method="get">
    <button type="submit">🔄 Refresh Scanner</button>
</form>

{% if error %}
    <div class="error">
        ⚠️ {{ error }}
    </div>
{% endif %}

{% if stocks %}

<table id="gapTable">

    <thead>
        <tr>
            <th>Stock</th>
            <th>Symbol</th>
            <th onclick="sortTable(2)">
                Gap % ↕
            </th>
            <th>Open</th>
            <th>Prev Close</th>
        </tr>
    </thead>

    <tbody>

    {% for stock in stocks %}

        <tr>
            <td>{{ stock.symbol }}</td>

            <td>{{ stock.symbol }}</td>

            <td class="gap">
                {{ "%.2f"|format(stock.gap) }}%
            </td>

            <td>
                ₹{{ "%.2f"|format(stock.open) }}
            </td>

            <td>
                ₹{{ "%.2f"|format(stock.previous_close) }}
            </td>
        </tr>

    {% endfor %}

    </tbody>

</table>

<div class="info">
    Total stocks found: {{ stocks|length }}
</div>

{% else %}

    {% if not error %}
        <div class="info">
            अभी कोई qualifying stock नहीं मिला।
        </div>
    {% endif %}

{% endif %}


<script>

function sortTable(column) {

    let table = document.getElementById("gapTable");

    let rows = Array.from(
        table.rows
    ).slice(1);

    rows.sort(function(a, b) {

        let A = parseFloat(
            a.cells[column].innerText.replace("%", "")
        );

        let B = parseFloat(
            b.cells[column].innerText.replace("%", "")
        );

        return B - A;
    });

    let tbody = table.tBodies[0];

    rows.forEach(function(row) {
        tbody.appendChild(row);
    });
}

</script>

</body>
</html>
"""


@app.route("/")
def home():

    stocks, error = get_gap_data()

    return render_template_string(
        HTML,
        stocks=stocks,
        error=error
    )


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
