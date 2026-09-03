# Time frame: Daily / Full Day Opening Gap Scanner

from flask import Flask, render_template_string
import yfinance as yf
import os

app = Flask(__name__)

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
    <b>Time frame:</b> Daily / Full Day Opening Gap
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
<table>
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
            <td class="gap">
                {{ "%.2f"|format(stock.gap) }}%
            </td>
            <td>{{ "%.2f"|format(stock.open) }}</td>
            <td>{{ "%.2f"|format(stock.prev_close) }}</td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% endif %}

</body>
</html>
"""


def get_indian_equities():
    """
    Time frame: Daily / India Equity
    Yahoo Finance India equity screener.
    """

    query = yf.EquityQuery(
        "and",
        [
            yf.EquityQuery("eq", ["region", "in"]),
            yf.EquityQuery("eq", ["exchange", "NSI"]),
            yf.EquityQuery("gt", ["intradayprice", 20])
        ]
    )

    result = yf.screen(
        query,
        offset=0,
        size=250,
        sortField="dayvolume",
        sortAsc=False
    )

    return result.get("quotes", [])


def build_scanner():
    """
    Time frame: Daily / Full Day Opening Gap
    """

    quotes = get_indian_equities()

    stocks = []

    for q in quotes:

        symbol = q.get("symbol")

        if not symbol:
            continue

        # Equity only
        if q.get("quoteType", "").upper() != "EQUITY":
            continue

        open_price = q.get("regularMarketOpen")
        prev_close = q.get("regularMarketPreviousClose")

        if open_price is None or prev_close is None:
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

        gap = (
            (open_price - prev_close)
            / prev_close
        ) * 100

        # Positive gap only
        if gap < 1:
            continue

        stocks.append({
            "name": (
                q.get("longName")
                or q.get("shortName")
                or symbol
            ),
            "symbol": symbol.replace(".NS", ""),
            "gap": gap,
            "open": open_price,
            "prev_close": prev_close
        })

    # Gap % descending
    stocks.sort(
        key=lambda x: x["gap"],
        reverse=True
    )

    return stocks


@app.route("/")
def scanner():

    try:
        stocks = build_scanner()

        if stocks:
            message = (
                f"Yahoo Finance India Equity data received. "
                f"{len(stocks)} positive Gap-Up stocks found. "
                f"Gap % घटते क्रम में है."
            )

            return render_template_string(
                HTML,
                stocks=stocks,
                error=None,
                message=message
            )

        return render_template_string(
            HTML,
            stocks=[],
            error=None,
            message=(
                "Data received, लेकिन 1% या उससे अधिक "
                "positive Gap-Up वाला stock नहीं मिला."
            )
        )

    except Exception as e:

        return render_template_string(
            HTML,
            stocks=[],
            error=str(e),
            message=None
        )


if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
