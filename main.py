# Time frame: Daily / Opening Gap + 20-Day Liquidity

from flask import Flask, jsonify, render_template_string
import requests
import csv
import io
import os
from datetime import datetime, timedelta

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/"
}

HOME = "https://www.nseindia.com/"
BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv"
ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"

# Result cache
CACHE = None
CACHE_TIME = None


def session_start():
    s = requests.Session()
    s.headers.update(HEADERS)

    try:
        s.get(HOME, timeout=8)
    except:
        pass

    return s


def get_csv(s, url):
    try:
        r = s.get(url, timeout=12)

        if r.status_code != 200:
            return []

        if len(r.text) < 100:
            return []

        reader = csv.DictReader(io.StringIO(r.text))

        data = []

        for row in reader:
            clean = {}

            for k, v in row.items():
                if k:
                    clean[k.strip().upper()] = (
                        v.strip() if v else ""
                    )

            data.append(clean)

        return data

    except:
        return []


def num(x):
    try:
        return float(
            str(x).replace(",", "").strip()
        )
    except:
        return 0.0


def bhav(s, date):

    url = BHAV_URL.format(
        date.strftime("%d%m%Y")
    )

    rows = get_csv(s, url)

    return [
        r for r in rows
        if r.get("SERIES", "").upper() == "EQ"
    ]


def get_etfs(s):

    rows = get_csv(s, ETF_URL)

    result = set()

    for r in rows:

        symbol = (
            r.get("SYMBOL")
            or r.get("SCRIP CODE")
            or ""
        ).strip().upper()

        if symbol:
            result.add(symbol)

    return result


def run_scan():

    global CACHE
    global CACHE_TIME

    # Use cached result for 5 minutes
    if CACHE is not None and CACHE_TIME is not None:

        if (
            datetime.now() - CACHE_TIME
        ).total_seconds() < 300:

            return CACHE

    s = session_start()

    today = datetime.now()

    # ------------------------------------------------
    # STEP 1
    # Get latest trading-day data
    # ------------------------------------------------

    current = []
    trading_date = today

    for _ in range(7):

        current = bhav(
            s,
            trading_date
        )

        if len(current) > 50:
            break

        trading_date -= timedelta(days=1)

    if not current:
        return []

    # ------------------------------------------------
    # STEP 2
    # Remove ETFs
    # ------------------------------------------------

    etfs = get_etfs(s)

    candidates = []

    # ------------------------------------------------
    # STEP 3
    # Chartink conditions 1 + 2
    # ------------------------------------------------

    for r in current:

        symbol = r.get(
            "SYMBOL", ""
        ).strip().upper()

        if not symbol:
            continue

        if symbol in etfs:
            continue

        open_price = num(
            r.get("OPEN_PRICE")
        )

        prev_close = num(
            r.get("PREV_CLOSE")
        )

        close_price = num(
            r.get("CLOSE_PRICE")
        )

        # Condition 1
        if close_price <= 20:
            continue

        if open_price <= 0:
            continue

        if prev_close <= 0:
            continue

        # Opening Gap %
        gap = (
            (open_price - prev_close)
            / prev_close
        ) * 100

        # Condition 2
        if gap < 1:
            continue

        candidates.append({
            "name": (
                r.get("SECURITY")
                or symbol
            ).strip(),

            "symbol": symbol,

            "gap": gap,

            "open": open_price,

            "prev": prev_close,

            "close": close_price
        })

    if not candidates:
        return []

    # ------------------------------------------------
    # STEP 4
    # Sort gap first
    # ------------------------------------------------

    candidates.sort(
        key=lambda x: x["gap"],
        reverse=True
    )

    symbols = {
        x["symbol"]
        for x in candidates
    }

    # ------------------------------------------------
    # STEP 5
    # 20 trading-day volume
    #
    # Only gap candidates are checked.
    # ------------------------------------------------

    history = {
        x: []
        for x in symbols
    }

    check_date = trading_date
    days = 0

    while days < 20:

        rows = bhav(
            s,
            check_date
        )

        if rows:

            for r in rows:

                symbol = r.get(
                    "SYMBOL", ""
                ).strip().upper()

                if symbol not in history:
                    continue

                volume = num(
                    r.get("TTL_TRD_QNTY")
                )

                if volume > 0:

                    history[
                        symbol
                    ].append(volume)

            days += 1

        check_date -= timedelta(days=1)

        if (
            trading_date - check_date
        ).days > 45:

            break

    # ------------------------------------------------
    # STEP 6
    # EXACT Chartink liquidity condition
    #
    # Daily Close × SMA(Daily Volume,20)
    # > ₹100,000,000
    # ------------------------------------------------

    results = []

    for x in candidates:

        volumes = history.get(
            x["symbol"],
            []
        )

        if len(volumes) < 20:
            continue

        sma_volume = (
            sum(volumes[:20]) / 20
        )

        turnover = (
            x["close"] * sma_volume
        )

        if turnover <= 100000000:
            continue

        results.append({
            **x,
            "avg_volume": sma_volume,
            "turnover": turnover
        })

    # Highest gap first
    results.sort(
        key=lambda x: x["gap"],
        reverse=True
    )

    CACHE = results
    CACHE_TIME = datetime.now()

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
    font-family: Arial;
    background: #f5f5f5;
    padding: 12px;
}

h1 {
    font-size: 24px;
}

.info {
    background: white;
    padding: 15px;
    border-radius: 10px;
    margin-bottom: 12px;
}

button {
    padding: 13px 20px;
    font-size: 17px;
    border: 0;
    border-radius: 8px;
}

#status {
    margin: 15px 0;
    font-weight: bold;
}

.box {
    overflow-x: auto;
}

table {
    width: 100%;
    background: white;
    border-collapse: collapse;
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

<b>Opening Gap Scanner</b>

<br><br>

Gap % =
(Open - Previous Close) /
Previous Close × 100

<br><br>

<b>Conditions:</b>

<br>
Price > ₹20

<br>
Positive Gap ≥ 1%

<br>
Close × 20-Day Average Volume > ₹10 Crore

<br>
ETF excluded

</div>

<button onclick="runScanner()">
Run Scanner
</button>

<div id="status">
Scanner ready.
</div>

<div class="box">

<table id="result">

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

</table>

</div>

<script>

async function runScanner() {

    document.getElementById(
        "status"
    ).innerText =
        "Scanning... Please wait.";

    try {

        const response =
            await fetch("/scan");

        const data =
            await response.json();

        const table =
            document.getElementById(
                "result"
            );

        table.innerHTML = `
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
        `;

        data.forEach(
            (x, i) => {

            table.innerHTML += `
            <tr>

            <td>${i + 1}</td>

            <td>${x.name}</td>

            <td>${x.symbol}</td>

            <td class="gap">
            +${x.gap.toFixed(2)}%
            </td>

            <td>
            ₹${x.open.toFixed(2)}
            </td>

            <td>
            ₹${x.prev.toFixed(2)}
            </td>

            <td>
            ₹${x.close.toFixed(2)}
            </td>

            <td>
            ${Math.round(
                x.avg_volume
            ).toLocaleString()}
            </td>

            <td>
            ₹${Math.round(
                x.turnover
            ).toLocaleString()}
            </td>

            </tr>
            `;
        });

        document.getElementById(
            "status"
        ).innerText =
            "Scan complete. " +
            data.length +
            " stocks found.";

    }

    catch (error) {

        document.getElementById(
            "status"
        ).innerText =
            "Scanner error. Please try again.";

    }

}

</script>

</body>

</html>
"""


@app.route("/")
def home():

    # IMPORTANT:
    # No NSE scanning here.
    # Page opens immediately.

    return render_template_string(
        HTML
    )


@app.route("/scan")
def scan_api():

    return jsonify(
        run_scan()
    )


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
