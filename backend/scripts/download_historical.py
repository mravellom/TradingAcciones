"""Download historical OHLCV data from Binance and/or Alpaca.

Usage:
    python -m scripts.download_historical
    python -m scripts.download_historical --symbols BTCUSDT ETHUSDT --interval 1h
    python -m scripts.download_historical --stocks
    python -m scripts.download_historical --stocks --symbols AAPL MSFT NVDA
"""
import argparse
import asyncio
import time

from app.core.database import async_session_factory
from app.ml.config import (
    SYMBOLS, PRIMARY_TIMEFRAME, SUPPORT_TIMEFRAMES,
    STOCK_SYMBOLS, STOCK_PRIMARY_TIMEFRAME, STOCK_SUPPORT_TIMEFRAMES,
)
from app.ml.data.downloader import HistoricalDataDownloader


async def main(symbols: list[str], intervals: list[str], export: bool, is_stocks: bool):
    start = time.time()

    async with async_session_factory() as session:
        downloader = HistoricalDataDownloader(session)

        source = "ALPACA (Stocks)" if is_stocks else "BINANCE (Crypto)"
        print("=" * 60)
        print(f"  HISTORICAL DATA DOWNLOAD — {source}")
        print(f"  Symbols:    {', '.join(symbols)}")
        print(f"  Intervals:  {', '.join(intervals)}")
        print("=" * 60)
        print()

        for symbol in symbols:
            for interval in intervals:
                print(f"Downloading {symbol} {interval}...", end=" ", flush=True)
                if is_stocks:
                    count = await downloader.download_stock_symbol(symbol, interval)
                else:
                    count = await downloader.download_symbol(symbol, interval)
                print(f"{count:,} bars")

                if export and count > 0:
                    path = await downloader.export_to_parquet(symbol, interval)
                    print(f"  Exported to {path}")

        if not is_stocks:
            await downloader.disconnect()

        # Print stats
        print()
        print("=" * 60)
        print("  DOWNLOAD STATS")
        print("=" * 60)
        stats = await downloader.get_stats()
        for s in stats:
            first = s['first'][:10] if s['first'] else 'N/A'
            last = s['last'][:10] if s['last'] else 'N/A'
            print(f"  {s['symbol']:10s} {s['interval']:5s} | {s['count']:>8,} bars | {first} to {last}")

        elapsed = time.time() - start
        print()
        print(f"  Done in {elapsed:.1f}s")
        print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download historical kline data")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Symbols to download (default: configured crypto or stock symbols)",
    )
    parser.add_argument(
        "--interval",
        default=None,
        help="Single interval (default: all configured)",
    )
    parser.add_argument(
        "--stocks",
        action="store_true",
        help="Download US stock data from Alpaca instead of crypto from Binance",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export to Parquet after download",
    )
    args = parser.parse_args()

    if args.stocks:
        symbols = args.symbols or STOCK_SYMBOLS
        intervals = [args.interval] if args.interval else [STOCK_PRIMARY_TIMEFRAME] + STOCK_SUPPORT_TIMEFRAMES
    else:
        symbols = args.symbols or SYMBOLS
        intervals = [args.interval] if args.interval else [PRIMARY_TIMEFRAME] + SUPPORT_TIMEFRAMES

    asyncio.run(main(symbols, intervals, args.export, args.stocks))
