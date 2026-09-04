# Morning Positive Gap Scanner
# NSE EQ series only - BE and ETF excluded

from flask import Flask, render_template_string
import requests
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

app = Flask(__name__)

NSE_PREOPEN_URL = "https://www.nseindia.com/api/market-data-pre-open?key=ALL"
NSE_ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
NSE_BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv"

MIN_PRICE = 20
MIN_GAP = 1.0
MIN_AVG_TURNOVER = 100000000
LIQUIDITY_DAYS = 20

liquidity_cache = {}
liquidity_cache_date = None
cache_lock = threading.Lock()

HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Morning Positive Gap Scanner</title>
<meta name="viewport" content="width=device-width, initial-scale=1">

<style>
body{
    background:#121212;
    color:#eee;
    font-family:Arial,sans-serif;
    margin:0;
    padding:12px;
}

.container{
    max-width:1100px;
    margin:auto;
}

h1{
    font-size:22px;
    margin:5px 0 10px;
}

.info{
    background:#1e1e1e;
    padding:11px;
    border-radius:8px;
    margin-bottom:12px;
    line-height:1.45;
    font-size:14px;
}

button{
    background:#333;
    color:white;
    border:1px solid #555;
    padding:11px 20px;
    border-radius:7px;
    font-size:16px;
    margin-bottom:12px;
}

.status{
    margin-bottom:10px;
    font-size:14px;
}

.table-wrap{
    overflow-x:auto;
}

table{
    width:100%;
    border-collapse:collapse;
    background:#1a1a1a;
    font-size:13px;
}

th{
    background:#252525;
    padding:8px 5px;
    text-align:center;
    white-space:nowrap;
}

td{
    padding:8px 5px;
    border-bottom:1px solid #333;
    text-align:center;
    white-space:nowrap;
}

.gap{
    color:#00d26a;
    font-weight:bold;
}

.note{
    color:#aaa;
    font-size:12px;
    margin-top:12px;
    line-height:1.5;
}
</style>
</head>

<body>
<div class="container">

<h1>Morning Positive Gap Scanner</h1>

<div class="info">
<b>Conditions:</b><br>
NSE Equity only — EQ Series<br>
BE Series excluded<br>
ETF excluded<br>
Opening Price &gt; ₹20<br>
Opening Gap ≥ 1%<br>
Previous 20 valid trading days average real turnover &gt; ₹10 crore<br>
Results sorted by highest Gap %
</div>

<form action="/scan" method="get">
<button type="submit">RUN SCANNER</button>
</form>

{% if status %}
<div class="status">{{ status }}</div>
{% endif %}

{% if rows %}
<div class="table-wrap">
<table>

<tr>
<th>Rank</th>
<th>Symbol</th>
<th>Gap %</th>
<th>Open</th>
<th>Prev Close</th>
<th>20D Avg</th>
</tr>

{% for r in rows %}
<tr>

<td>{{ r.rank }}</td>

<td><b>{{ r.symbol }}</b></td>

<td class="gap">
{{ "%.2f"|format(r.gap) }}%
</td>

<td>
₹{{ "%.2f"|format(r.open) }}
</td>

<td>
₹{{ "%.2f"|format(r.prev_close) }}
</td>

<td>
₹{{ "{:,.0f}".format(r.avg_turnover) }}
</td>

</tr>
{% endfor %}

</table>
</div>
{% endif %}

<div class="note">
Opening Gap =
(Opening Price − Previous Close) ÷ Previous Close × 100.
<br>
Today's Close is NOT used for the Opening Gap calculation.
<br>
Historical liquidity uses previous completed trading days only.
<br>
Only NSE Series EQ is included. BE and ETF are excluded.
</div>

</div>
</body>
</html>
"""


def nse_session():
    session = requests.Session()

    session.headers.update({
        "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36",

        "Accept":
        "application/json,text/plain,*/*",

        "Accept-Language":
        "en-US,en;q=0.9",

        "Referer":
        "https://www.nseindia.com/",

        "Connection":
        "keep-alive"
    })

    try:
        session.get(
            "https://www.nseindia.com/",
            timeout=8
        )
    except Exception:
        pass

    return session


def find_column(df, names):
    lower_map = {
        str(c).strip().lower(): c
        for c in df.columns
    }

    for name in names:
        if name.lower() in lower_map:
            return lower_map[name.lower()]

    return None


def get_etf_symbols():
    try:
        s = nse_session()

        r = s.get(
            NSE_ETF_URL,
            timeout=15
        )

        if r.status_code != 200:
            return set()

        if not r.text.strip():
            return set()

        df = pd.read_csv(
            StringIO(r.text)
        )

        symbols = set()

        for col in df.columns:

            if "symbol" in str(col).lower():

                for value in df[col].dropna():

                    symbol = str(
                        value
                    ).strip().upper()

                    if symbol:
                        symbols.add(symbol)

        return symbols

    except Exception:
        return set()


def get_eq_symbols():

    today = datetime.now().date()

    for days_back in range(1, 11):

        date_obj = (
            today -
            timedelta(days=days_back)
        )

        if date_obj.weekday() >= 5:
            continue

        date_str = date_obj.strftime(
            "%d%m%Y"
        )

        url = NSE_BHAV_URL.format(
            date_str
        )

        try:

            s = nse_session()

            r = s.get(
                url,
                timeout=20
            )

            if r.status_code != 200:
                continue

            if not r.text.strip():
                continue

            df = pd.read_csv(
                StringIO(r.text)
            )

            df.columns = [
                str(c).strip().upper()
                for c in df.columns
            ]

            symbol_col = find_column(
                df,
                ["SYMBOL"]
            )

            series_col = find_column(
                df,
                ["SERIES"]
            )

            if (
                symbol_col is None
                or series_col is None
            ):
                continue

            df[symbol_col] = (
                df[symbol_col]
                .astype(str)
                .str.strip()
                .str.upper()
            )

            df[series_col] = (
                df[series_col]
                .astype(str)
                .str.strip()
                .str.upper()
            )

            eq_df = df[
                df[series_col] == "EQ"
            ]

            symbols = set(
                eq_df[symbol_col]
                .dropna()
                .astype(str)
                .str.strip()
                .str.upper()
            )

            symbols = {
                x for x in symbols
                if x and x != "NAN"
            }

            if symbols:
                return symbols

        except Exception:
            continue

    return set()


def get_preopen_data():

    last_error = None

    for attempt in range(3):

        try:

            s = nse_session()

            r = s.get(
                NSE_PREOPEN_URL,
                timeout=15
            )

            if r.status_code != 200:
                raise Exception(
                    f"NSE HTTP {r.status_code}"
                )

            data = r.json()

            if "data" not in data:
                raise Exception(
                    "NSE pre-open data missing"
                )

            return data["data"]

        except Exception as e:

            last_error = e
            time.sleep(1)

    raise Exception(
        f"NSE Pre-Open failed: {last_error}"
    )


def download_one_bhavcopy(
    date_obj,
    required_symbols=None
):

    date_str = date_obj.strftime(
        "%d%m%Y"
    )

    url = NSE_BHAV_URL.format(
        date_str
    )

    try:

        s = nse_session()

        r = s.get(
            url,
            timeout=20
        )

        if r.status_code != 200:
            return None

        if not r.text.strip():
            return None

        df = pd.read_csv(
            StringIO(r.text)
        )

        df.columns = [
            str(c).strip().upper()
            for c in df.columns
        ]

        symbol_col = find_column(
            df,
            ["SYMBOL"]
        )

        turnover_col = find_column(
            df,
            ["TOTTRDVAL"]
        )

        close_col = find_column(
            df,
            ["CLOSE_PRICE", "CLOSE"]
        )

        volume_col = find_column(
            df,
            ["TTL_TRD_QNTY", "TOTTRDQTY"]
        )

        if symbol_col is None:
            return None

        if (
            turnover_col is None
            and (
                close_col is None
                or volume_col is None
            )
        ):
            return None

        if required_symbols:

            df[symbol_col] = (
                df[symbol_col]
                .astype(str)
                .str.strip()
                .str.upper()
            )

            df = df[
                df[symbol_col].isin(
                    required_symbols
                )
            ]

        result = {}

        symbol_index = df.columns.get_loc(
            symbol_col
        )

        turnover_index = (
            df.columns.get_loc(
                turnover_col
            )
            if turnover_col is not None
            else None
        )

        close_index = (
            df.columns.get_loc(
                close_col
            )
            if close_col is not None
            else None
        )

        volume_index = (
            df.columns.get_loc(
                volume_col
            )
            if volume_col is not None
            else None
        )

        for row in df.itertuples(
            index=False,
            name=None
        ):

            try:

                symbol = str(
                    row[symbol_index]
                ).strip().upper()

                if not symbol:
                    continue

                if turnover_index is not None:

                    turnover = float(
                        str(
                            row[turnover_index]
                        ).replace(",", "")
                    )

                else:

                    close = float(
                        str(
                            row[close_index]
                        ).replace(",", "")
                    )

                    volume = float(
                        str(
                            row[volume_index]
                        ).replace(",", "")
                    )

                    turnover = (
                        close * volume
                    )

                if turnover > 0:
                    result[symbol] = turnover

            except Exception:
                continue

        if not result:
            return None

        return {
            "date":
            date_obj.strftime("%Y-%m-%d"),

            "data":
            result
        }

    except Exception:
        return None


def get_candidate_dates():

    dates = []

    d = (
        datetime.now().date()
        - timedelta(days=1)
    )

    while len(dates) < 30:

        if d.weekday() < 5:
            dates.append(d)

        d -= timedelta(days=1)

    return dates


def build_liquidity_cache(
    required_symbols
):

    global liquidity_cache
    global liquidity_cache_date

    today = datetime.now().date()

    with cache_lock:

        if (
            liquidity_cache_date == today
            and liquidity_cache
        ):
            return liquidity_cache

    dates = get_candidate_dates()
    daily_data = []

    with ThreadPoolExecutor(
        max_workers=4
    ) as executor:

        futures = {
            executor.submit(
                download_one_bhavcopy,
                d,
                required_symbols
            ): d
            for d in dates
        }

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result is not None:
                    daily_data.append(result)

            except Exception:
                pass

    daily_data.sort(
        key=lambda x: x["date"],
        reverse=True
    )

    daily_data = daily_data[
        :LIQUIDITY_DAYS
    ]

    if len(daily_data) < LIQUIDITY_DAYS:

        raise Exception(
            f"Only {len(daily_data)} valid "
            f"trading days available. "
            f"Need {LIQUIDITY_DAYS}."
        )

    turnover_sum = {}
    turnover_count = {}

    for day in daily_data:

        for symbol, turnover in (
            day["data"].items()
        ):

            turnover_sum[symbol] = (
                turnover_sum.get(
                    symbol,
                    0
                ) + turnover
            )

            turnover_count[symbol] = (
                turnover_count.get(
                    symbol,
                    0
                ) + 1
            )

    avg_turnover = {}

    for symbol in turnover_sum:

        count = turnover_count[symbol]

        if count == LIQUIDITY_DAYS:

            avg_turnover[symbol] = (
                turnover_sum[symbol]
                / count
            )

    with cache_lock:

        liquidity_cache = avg_turnover
        liquidity_cache_date = today

    return avg_turnover


def parse_preopen(data):

    rows = []

    for item in data:

        meta = item.get(
            "metadata",
            {}
        )

        trade = item.get(
            "detail",
            {}
        ).get(
            "preOpenMarket",
            {}
        )

        symbol = (
            meta.get("symbol")
            or item.get("symbol")
        )

        if not symbol:
            continue

        symbol = str(
            symbol
        ).strip().upper()

        previous_close = (
            meta.get("previousClose")
            or meta.get("prevClose")
            or item.get("previousClose")
        )

        opening_price = (
            meta.get("finalPrice")
            or meta.get("iep")
            or meta.get(
                "indicativeEquilibriumPrice"
            )
            or trade.get("finalPrice")
            or trade.get("iep")
        )

        try:

            previous_close = float(
                str(
                    previous_close
                ).replace(",", "")
            )

            opening_price = float(
                str(
                    opening_price
                ).replace(",", "")
            )

        except Exception:
            continue

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
        ) * 100

        rows.append({
            "symbol": symbol,
            "open": opening_price,
            "prev_close": previous_close,
            "gap": gap
        })

    return rows


def run_scanner():

    preopen = get_preopen_data()
    parsed = parse_preopen(preopen)

    eq_symbols = get_eq_symbols()

    if not eq_symbols:
        raise Exception(
            "NSE EQ Series list could not be loaded."
        )

    candidate_rows = []

    for row in parsed:

        if row["symbol"] not in eq_symbols:
            continue

        if row["open"] <= MIN_PRICE:
            continue

        if row["gap"] < MIN_GAP:
            continue

        candidate_rows.append(row)

    if not candidate_rows:
        return []

    etfs = get_etf_symbols()

    candidate_rows = [
        row
        for row in candidate_rows
        if row["symbol"] not in etfs
    ]

    if not candidate_rows:
        return []

    required_symbols = {
        row["symbol"]
        for row in candidate_rows
    }

    avg_turnover = build_liquidity_cache(
        required_symbols
    )

    results = []

    for row in candidate_rows:

        symbol = row["symbol"]

        if symbol not in avg_turnover:
            continue

        if (
            avg_turnover[symbol]
            <= MIN_AVG_TURNOVER
        ):
            continue

        results.append({
            "symbol": symbol,
            "gap": row["gap"],
            "open": row["open"],
            "prev_close": row["prev_close"],
            "avg_turnover":
                avg_turnover[symbol]
        })

    results.sort(
        key=lambda x: x["gap"],
        reverse=True
    )

    for i, row in enumerate(
        results,
        start=1
    ):
        row["rank"] = i

    return results


@app.route("/")
def home():

    return render_template_string(
        HTML,
        rows=None,
        status=None
    )


@app.route("/scan")
def scan():

    start = time.time()

    try:

        rows = run_scanner()

        elapsed = (
            time.time() - start
        )

        status = (
            f"Scan complete. "
            f"{len(rows)} stocks found. "
            f"Time: {elapsed:.1f} seconds."
        )

        return render_template_string(
            HTML,
            rows=rows,
            status=status
        )

    except Exception as e:

        return render_template_string(
            HTML,
            rows=None,
            status=f"Scanner error: {e}"
        )


@app.route("/health")
def health():
    return "OK", 200


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
