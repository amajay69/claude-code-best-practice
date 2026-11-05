[← Back to stock-desk](../README.md)

# Your data lives here — and is never committed

Everything in this folder except this README is git-ignored. It holds your
real portfolio and price history, which does not belong in a public
repository.

```
data/
  history/<SYMBOL>.csv   daily OHLC — date,open,high,low,close,volume
  history/.adjusted      marker written by --adjusted at import
  quotes.json            live NSE snapshots, written by the session
  fundamentals.json      optional: PE, ROE, debt, promoter holding
  sectors.json           optional: symbol → sector
```

## Getting history in

Export daily candles per stock, then:

```bash
python3 scripts/import_history.py ~/Downloads/*.csv --adjusted
```

The importer accepts TradingView, Zerodha, Groww and Investing.com column
spellings, normalises dates and thousands separators, removes duplicate
dates, sorts ascending, and **flags any single-day move beyond ±35%** —
almost always an unadjusted split, which would otherwise make the backtest
confidently wrong.

Pass `--adjusted` only if your export really is split- and bonus-adjusted.
TradingView's is. Without that declaration the backtest refuses to run,
which is the intended behaviour rather than an obstacle to work around.

**Export the index too.** Save NIFTY 50 as `NIFTY50.csv`. Without it, beta,
relative strength, sector ranking and the benchmark comparison are all
unavailable — the run still completes and says so, but you lose a lot.

## Quotes

`quotes.json` is written by the agent session from the NSE MCP server,
because a Python process cannot call an MCP tool. Shape:

```json
{
  "fetched_at": "2026-11-05T10:44:27Z",
  "source": "NSE_LiveCM_Data.cm_get_stock_quote",
  "quotes": {
    "HDFCBANK": {
      "lastTradedPrice": 760.0, "openPrice": 760.0, "highPrice": 762.7,
      "lowPrice": 749.1, "preClosePrice": 736.7, "perChange": 3.16,
      "volume": 65401905, "fiftyTwoWeekHigh": 1017.5,
      "fiftyTwoWeekLow": 669.2, "perChange30d": 7.83,
      "latestTimestamp": "2026-11-05 16:00:28"
    }
  }
}
```

A quote older than 24 hours is reported stale rather than used silently.

## Run it

```bash
python3 scripts/run_analysis.py --data data --holdings my-holdings.csv --excel
```
