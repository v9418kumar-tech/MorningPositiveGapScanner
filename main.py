# Time frame: NSE Pre-Open / 9:08-9:09 AM
# Scanner: Positive Opening Gap + Previous 20-Day Real Turnover
# Today Close is NOT used anywhere.

from flask import Flask, render_template_string
import requests
import csv
import io
import os
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# ---------------------------------------------------------
# NSE URLs
# ---------------------------------------------------------

NSE_HOME = "https://www.nseindia.com/"
NSE_PREOPEN = "https://www.nseindia.com/api/market-data-pre-open?key=ALL"

NSE_BHAV = (
    "https://nsearchives.nseindia.com/"
    "products/content/sec_bhavdata_full_{}.csv"
)

NSE_ETF = (
    "https://nsearchives.nseindia.com/"
    "content/equities/eq_etfseclist.csv"
)

# ---------------------------------------------------------
# Scanner Conditions
# ---------------------------------------------------------

MIN_PRICE = 20.0
MIN_GAP = 1.0

# ₹10 Crore
MIN_AVG_TURNOVER = 100000000

HISTORICAL_DAYS_REQUIRED = 20

# ---------------------------------------------------------
# NSE Session
# ---------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "application/json,text/plain,*/*"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Origin": "https://www.nseindia.com",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

session = requests.Session()
session.headers.update(HEADERS)


# ---------------------------------------------------------
# Utility
# ---------------------------------------------------------

def clean_number(value):
    try:
        if value is None:
            return 0.0

        text = str(value).strip()
        text = text.replace(",", "")
        text = text.replace("₹", "")

        if text in ("", "-", "None", "nan", "NaN"):
            return 0.0

        return float(text)

    except Exception:
        return 0.0


def clean_key(key):
    if key is None:
        return ""

    return str(key).strip().upper()


# ---------------------------------------------------------
# NSE Session Warm-up
# ---------------------------------------------------------

def warm_nse_session():

    try:
        session.get(
            NSE_HOME,
            timeout=20
        )

        time.sleep(0.5)

        return True

    except Exception:
        return False


# ---------------------------------------------------------
# ETF Symbols
# ---------------------------------------------------------

def get_etf_symbols():

    try:

        response = session.get(
            NSE_ETF,
            timeout=30
        )

        response.raise_for_status()

        reader = csv.DictReader(
            io.StringIO(response.text)
        )

        etf_symbols = set()

        for row in reader:

            for key, value in row.items():

                if not value:
                    continue

                if "SYMBOL" in clean_key(key):

                    symbol = value.strip().upper()

                    if symbol:
                        etf_symbols.add(symbol)

        return etf_symbols

    except Exception:

        return set()


# ---------------------------------------------------------
# Find value from row using possible column names
# ---------------------------------------------------------

def get_row_value(row, possible_names):

    normalized = {}

    for key, value in row.items():

        normalized[
            clean_key(key).replace(" ", "")
        ] = value

    for name in possible_names:

        normalized_name = (
            name.upper()
            .replace(" ", "")
        )

        if normalized_name in normalized:
            return normalized[normalized_name]

    return ""


# ---------------------------------------------------------
# Previous 20 completed trading days
#
# REAL TURNOVER:
# Prefer NSE TOTTRDVAL.
#
# If unavailable, fallback:
# CLOSE PRICE × TOTAL TRADED QUANTITY
# ---------------------------------------------------------

def get_previous_20_day_turnover():

    today = datetime.now().date()

    candidate_dates = []

    # Search enough calendar days to find
    # 20 completed trading days.
    for i in range(1, 60):

        d = today - timedelta(days=i)

        if d.weekday() < 5:
            candidate_dates.append(d)

        if len(candidate_dates) >= 30:
            break

    # We need only the most recent 20 completed days.
    target_dates = candidate_dates[:20]

    turnover_by_symbol = {}

    def download_one_day(day):

        date_text = day.strftime("%d%m%Y")

        url = NSE_BHAV.format(date_text)

        try:

            response = session.get(
                url,
                timeout=30
            )

            if response.status_code != 200:
                return day, []

            text = response.text

            if not text.strip():
                return day, []

            reader = csv.DictReader(
                io.StringIO(text)
            )

            day_data = []

            for row in reader:

                symbol = get_row_value(
                    row,
                    [
                        "SYMBOL"
                    ]
                ).strip().upper()

                series = get_row_value(
                    row,
                    [
                        "SERIES"
                    ]
                ).strip().upper()

                if not symbol:
                    continue

                # NSE Equity only
                if series != "EQ":
                    continue

                # Actual traded value
                actual_turnover = clean_number(
                    get_row_value(
                        row,
                        [
                            "TOTTRDVAL",
                            "TOTALTRADEDVALUE",
                            "TRADEDVALUE"
                        ]
                    )
                )

                # Fallback if actual turnover column
                # is not available.
                if actual_turnover <= 0:

                    close_price = clean_number(
                        get_row_value(
                            row,
                            [
                                "CLOSE_PRICE",
                                "CLOSE"
                            ]
                        )
                    )

                    quantity = clean_number(
                        get_row_value(
                            row,
                            [
                                "TTL_TRD_QNTY",
                                "TOTALTRADEDQUANTITY",
                                "TOTTRDQTY"
                            ]
                        )
                    )

                    if (
                        close_price > 0
                        and quantity > 0
                    ):
                        actual_turnover = (
                            close_price * quantity
                        )

                if actual_turnover > 0:

                    day_data.append(
                        (
                            symbol,
                            actual_turnover
                        )
                    )

            return day, day_data

        except Exception:

            return day, []

    # Download the 20 dates.
    with ThreadPoolExecutor(
        max_workers=5
    ) as executor:

        futures = [
            executor.submit(
                download_one_day,
                day
            )
            for day in target_dates
        ]

        for future in as_completed(futures):

            day, rows = future.result()

            for symbol, turnover in rows:

                if symbol not in turnover_by_symbol:

                    turnover_by_symbol[symbol] = []

                turnover_by_symbol[symbol].append(
                    (
                        day,
                        turnover
                    )
                )

    # -----------------------------------------------------
    # Calculate exact average over 20 completed days.
    # -----------------------------------------------------

    average_turnover = {}

    for symbol, values in turnover_by_symbol.items():

        # Sort newest completed day first
        values.sort(
            key=lambda x: x[0],
            reverse=True
        )

        # Exactly the 20 requested days
        last_20 = values[:20]

        if len(last_20) == 20:

            total = sum(
                turnover
                for _, turnover in last_20
            )

            average_turnover[symbol] = (
                total / 20.0
            )

    return average_turnover


# ---------------------------------------------------------
# NSE Pre-Open Data
# ---------------------------------------------------------

def get_preopen_data():

    warm_nse_session()

    last_error = ""

    for attempt in range(3):

        try:

            response = session.get(
                NSE_PREOPEN,
                timeout=30
            )

            if response.status_code == 200:

                return response.json()

            last_error = (
                "NSE HTTP "
                + str(response.status_code)
            )

        except Exception as e:

            last_error = str(e)

        time.sleep(2)

        warm_nse_session()

    raise Exception(
        "NSE Pre-Open data unavailable. "
        + last_error
    )


# ---------------------------------------------------------
# Extract symbol / price fields from NSE response
# ---------------------------------------------------------

def extract_possible_value(
    dictionaries,
    possible_keys
):

    for data in dictionaries:

        if not isinstance(data, dict):
            continue

        for key in possible_keys:

            if key in data:

                value = data.get(key)

                if value not in (
                    None,
                    "",
                    "-"
                ):

                    return value

    return None


def extract_preopen_rows(data):

    results = []

    raw_rows = data.get(
        "data",
        []
    )

    for item in raw_rows:

        if not isinstance(item, dict):
            continue

        metadata = item.get(
            "metadata",
            {}
        )

        detail = item.get(
            "detail",
            {}
        )

        preopen = detail.get(
            "preOpenMarket",
            {}
        )

        if not isinstance(metadata, dict):
            metadata = {}

        if not isinstance(detail, dict):
            detail = {}

        if not isinstance(preopen, dict):
            preopen = {}

        sources = [
            preopen,
            detail,
            metadata,
            item
        ]

        symbol = extract_possible_value(
            sources,
            [
                "symbol",
                "SYMBOL"
            ]
        )

        previous_close = extract_possible_value(
            sources,
            [
                "previousClose",
                "prevClose",
                "previous_close",
                "PREVIOUSCLOSE"
            ]
        )

        opening_price = extract_possible_value(
            sources,
            [
                "finalPrice",
                "iep",
                "IEP",
                "indicativeEquilibriumPrice",
                "indicativeEquilibrium",
                "open",
                "OPEN"
            ]
        )

        if not symbol:
            continue

        symbol = str(
            symbol
        ).strip().upper()

        previous_close = clean_number(
            previous_close
        )

        opening_price = clean_number(
            opening_price
        )

        if (
            previous_close <= 0
            or opening_price <= 0
        ):
            continue

        gap = (
            (
                opening_price
                - previous_close
            )
            / previous_close
        ) * 100.0

        results.append(
            {
                "symbol": symbol,
                "open": opening_price,
                "previous_close": previous_close,
                "gap": gap
            }
        )

    return results


# ---------------------------------------------------------
# Main Scanner
# ---------------------------------------------------------

def run_scanner():

    # Historical liquidity data.
    average_turnover = (
        get_previous_20_day_turnover()
    )

    # ETF symbols.
    etf_symbols = get_etf_symbols()

    # Current pre-open data.
    preopen_data = get_preopen_data()

    preopen_rows = extract_preopen_rows(
        preopen_data
    )

    results = []

    for stock in preopen_rows:

        symbol = stock["symbol"]

        # ---------------------------------------------
        # ETF EXCLUSION
        # ---------------------------------------------

        if symbol in etf_symbols:
            continue

        # ---------------------------------------------
        # OPENING PRICE > ₹20
        # ---------------------------------------------

        if stock["open"] <= MIN_PRICE:
            continue

        # ---------------------------------------------
        # POSITIVE GAP >= 1%
        # ---------------------------------------------

        if stock["gap"] < MIN_GAP:
            continue

        # ---------------------------------------------
        # PREVIOUS 20 COMPLETED DAYS
        # AVERAGE REAL TURNOVER > ₹10 CRORE
        # ---------------------------------------------

        avg_turnover = average_turnover.get(
            symbol,
            0
        )

        if avg_turnover <= MIN_AVG_TURNOVER:
            continue

        # ---------------------------------------------
        # FINAL RESULT
        # ---------------------------------------------

        results.append(
            {
                "symbol": symbol,
                "gap": stock["gap"],
                "open": stock["open"],
                "previous_close": stock[
                    "previous_close"
                ],
                "avg_turnover": avg_turnover
            }
        )

    # Biggest Opening Gap first.
    results.sort(
        key=lambda x: x["gap"],
        reverse=True
    )

    return results


# ---------------------------------------------------------
# HTML
# ---------------------------------------------------------

HTML = """
<!DOCTYPE html>

<html>

<head>

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>
Morning Positive Gap Scanner
</title>

<style>

body {
    background: #121212;
    color: #eeeeee;
    font-family: Arial, sans-serif;
    margin: 0;
    padding: 15px;
}

h1 {
    font-size: 25px;
    margin-bottom: 10px;
}

.info {
    background: #1e1e1e;
    border: 1px solid #333333;
    padding: 13px;
    border-radius: 8px;
    margin-bottom: 15px;
    line-height: 1.65;
}

.condition {
    color: #dddddd;
}

button {
    background: #00d26a;
    color: #000000;
    border: none;
    padding: 13px 22px;
    border-radius: 7px;
    font-size: 16px;
    font-weight: bold;
    cursor: pointer;
    margin-bottom: 15px;
}

button:active {
    transform: scale(0.98);
}

.status {
    background: #1e1e1e;
    padding: 10px;
    border-radius: 7px;
    margin-bottom: 12px;
    color: #bbbbbb;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    background: #1a1a1a;
}

th {
    background: #252525;
    color: #ffffff;
    padding: 10px;
    border: 1px solid #383838;
    white-space: nowrap;
    position: sticky;
    top: 0;
}

td {
    padding: 10px;
    border: 1px solid #333333;
    white-space: nowrap;
}

.gap {
    color: #00d26a;
    font-weight: bold;
}

.rank {
    font-weight: bold;
}

.note {
    color: #999999;
    font-size: 13px;
    margin-top: 12px;
}

.error {
    color: #ff7777;
    font-weight: bold;
}

</style>

</head>

<body>

<h1>
Morning Positive Gap Scanner
</h1>

<div class="info">

<b>Time Frame:</b>
NSE Pre-Open / 9:08-9:09 AM

<br><br>

<b>Conditions:</b>

<div class="condition">
1. NSE Equity only<br>
2. ETF excluded<br>
3. Opening Price &gt; ₹20<br>
4. Opening Gap ≥ +1%<br>
5. Previous 20 completed trading days
   Average Real Turnover &gt; ₹10 Crore<br>
6. Highest Opening Gap % first
</div>

<br>

<b>Important:</b>
Today's Close is NOT used.

</div>

<form action="/scan" method="get">

<button type="submit">
Run Scanner
</button>

</form>

{% if message %}

<div class="status">

{{ message }}

</div>

{% endif %}

{% if results %}

<div class="status">

<b>
{{ results|length }} stocks found
</b>

</div>

<div class="table-wrap">

<table>

<tr>

<th>Rank</th>

<th>Stock</th>

<th>Gap %</th>

<th>Opening Price</th>

<th>Previous Close</th>

<th>20D Avg Turnover</th>

</tr>

{% for r in results %}

<tr>

<td class="rank">
{{ loop.index }}
</td>

<td>
<b>{{ r.symbol }}</b>
</td>

<td class="gap">
+{{ "%.2f"|format(r.gap) }}%
</td>

<td>
₹{{ "%.2f"|format(r.open) }}
</td>

<td>
₹{{ "%.2f"|format(r.previous_close) }}
</td>

<td>
₹{{ "{:,.0f}".format(r.avg_turnover) }}
</td>

</tr>

{% endfor %}

</table>

</div>

<div class="note">

20D Avg Turnover = previous 20 completed
trading days का average actual traded value.

</div>

{% endif %}

</body>

</html>
"""


# ---------------------------------------------------------
# Home Page
# ---------------------------------------------------------

@app.route("/")
def home():

    return render_template_string(
        HTML,
        results=[],
        message=(
            "Scanner ready. "
            "9:08-9:09 AM पर Run Scanner दबाएँ।"
        )
    )


# ---------------------------------------------------------
# Scan
# ---------------------------------------------------------

@app.route("/scan")
def scan():

    try:

        results = run_scanner()

        return render_template_string(
            HTML,
            results=results,
            message=(
                "Scan complete. "
                + str(len(results))
                + " stocks found."
            )
        )

    except Exception as e:

        return render_template_string(
            HTML,
            results=[],
            message=(
                "Scanner error: "
                + str(e)
            )
        )


# ---------------------------------------------------------
# Render / Local Server
# ---------------------------------------------------------

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
