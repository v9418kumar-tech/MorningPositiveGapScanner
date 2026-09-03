# Time frame: Daily / Today's Opening Gap
# Test mode: Today's Open vs Previous Close
# Gap % = (Open - Previous Close) / Previous Close * 100

from flask import Flask, render_template_string
import requests
import csv
import io
from datetime import datetime

app = Flask(__name__)

MIN_PRICE = 20
MIN_GAP = 1.0

# NSE official daily Full Bhavcopy
BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/"
    "products/content/sec_bhavdata_full_{date}.csv"
)

# NSE official ETF list
ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Morning Positive Gap Scanner</title>
<style>
body {
    font-family: Arial;
    margin: 15px;
    background: #f5f5f5;
}
h2 { margin-bottom: 5px; }
.info {
    background: white;
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 12px;
}
button {
    padding: 10px 18px;
    font-size: 16px;
    border: 0;
    border-radius: 6px;
}
table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    margin-top: 12px;
}
th, td {
    border: 1px solid #ddd;
    padding: 8px;
    text-align: center;
    white-space: nowrap;
}
th { background: #eeeeee; }
.gap { font-weight: bold; }
</style>
</head>

<body>

<h2>Morning Positive Gap Scanner</h2>

<div class="info">
<b>Today's Opening Gap</b><br>
Gap % = (Open - Previous Close) / Previous Close × 100
<br><br>
<b>Filters:</b>
Price &gt; ₹20 | Positive Gap ≥ 1%
</div>

<form>
<button type="submit">Refresh Scanner</button>
</form>

<div class="info">
{{ message }}
</div>

{% if rows %}
<table>
<tr>
<th>Sr.</th>
<th>Stock Name</th>
<th>Symbol</th>
<th>Gap %</th>
<th>Open</th>
<th>Previous Close</th>
</tr>

{% for r in rows %}
<tr>
<td>{{ loop.index }}</td>
<td>{{ r.name }}</td>
<td>{{ r.symbol }}</td>
<td class="gap">+{{ "%.2f"|format(r.gap) }}%</td>
<td>₹{{ "%.2f"|format(r.open) }}</td>
<td>₹{{ "%.2f"|format(r.prev_close) }}</td>
</tr>
{% endfor %}

</table>
{% endif %}

</body>
</html>
"""


def download_text(url):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*"
    }

    r = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    r.raise_for_status()
    return r.text


def get_etfs():
    etfs = set()

    try:
        text = download_text(ETF_URL)

        reader = csv.reader(io.StringIO(text))

        for row in reader:
            for value in row:
                value = value.strip().upper()

                if value and value != "SYMBOL":
                    etfs.add(value)

    except Exception:
        pass

    return etfs


def get_today_bhavcopy():
    date_string = datetime.now().strftime("%d%m%Y")

    url = BHAVCOPY_URL.format(
        date=date_string
    )

    text = download_text(url)

    reader = csv.DictReader(
        io.StringIO(text)
    )

    rows = []

    for row in reader:

        clean = {}

        for key, value in row.items():

            if key is None:
                continue

            clean[
                key.strip().upper()
            ] = (
                value.strip()
                if value is not None
                else ""
            )

        rows.append(clean)

    return rows


def number(row, names):

    for name in names:

        value = row.get(name)

        if value is None:
            continue

        value = str(value).strip()

        if not value:
            continue

        try:
            return float(value.replace(",", ""))
        except:
            pass

    return None


def scan():

    try:
        data = get_today_bhavcopy()

    except Exception as e:

        return [], (
            "Today's NSE Bhavcopy could not be downloaded. "
            "Error: " + str(e)
        )

    etfs = get_etfs()

    results = []

    for row in data:

        symbol = (
            row.get("SYMBOL")
            or row.get("SYMBOL ")
            or ""
        ).strip().upper()

        series = (
            row.get("SERIES")
            or ""
        ).strip().upper()

        if not symbol:
            continue

        # Equity series only
        if series != "EQ":
            continue

        # ETF exclusion
        if symbol in etfs:
            continue

        open_price = number(
            row,
            ["OPEN_PRICE", "OPEN"]
        )

        prev_close = number(
            row,
            ["PREV_CLOSE", "PREVIOUS_CLOSE_PRICE"]
        )

        if open_price is None or prev_close is None:
            continue

        if open_price <= MIN_PRICE:
            continue

        if prev_close <= 0:
            continue

        gap = (
            (open_price - prev_close)
            / prev_close
        ) * 100

        if gap < MIN_GAP:
            continue

        name = (
            row.get("COMPANY_NAME")
            or row.get("NAME_OF_COMPANY")
            or symbol
        ).strip()

        results.append({
            "name": name,
            "symbol": symbol,
            "gap": gap,
            "open": open_price,
            "prev_close": prev_close
        })

    results.sort(
        key=lambda x: x["gap"],
        reverse=True
    )

    message = (
        "Today's Open vs Previous Close. "
        "Sorted by highest Positive Gap."
    )

    return results, message


@app.route("/")
def home():

    rows, message = scan()

    return render_template_string(
        HTML,
        rows=rows,
        message=message
    )


if __name__ == "__main__":

    port = int(
        __import__("os").environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
