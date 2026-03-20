"""Download historical OHLCV data from Binance.

Usage:
    python -m scripts.download_historical
    python -m scripts.download_historical --symbols BTCUSDT ETHUSDT --interval 1h
"""
import argparse
import asyncio
import time

from app.core.database import async_session_factory
from app.ml.config import SYMBOLS, PRIMARY_TIMEFRAME, SUPPORT_TIMEFRAMES
from app.ml.data.downloader import HistoricalDataDownloader


async def main(symbols: list[str], intervals: list[str], export: bool):
    start = time.time()

    async with async_session_factory() as session:
        downloader = HistoricalDataDownloader(session)

        print("=" * 60)
        print("  HISTORICAL DATA DOWNLOAD")
        print(f"  Symbols:    {', '.join(symbols)}")
        print(f"  Intervals:  {', '.join(intervals)}")
        print("=" * 60)
        print()

        for symbol in symbols:
            for interval in intervals:
                print(f"Downloading {symbol} {interval}...", end=" ", flush=True)
                count = await downloader.download_symbol(symbol, interval)
                print(f"{count:,} klines")

                if export and count > 0:
                    path = await downloader.export_to_parquet(symbol, interval)
                    print(f"  Exported to {path}")

        await downloader.disconnect()

        # Print stats
        print()
        print("=" * 60)
        print("  DOWNLOAD STATS")
        print("=" * 60)
        stats = await downloader.get_stats()
        for s in stats:
            print(f"  {s['symbol']:10s} {s['interval']:5s} | {s['count']:>8,} klines | {s['first'][:10]} to {s['last'][:10]}")

        elapsed = time.time() - start
        print()
        print(f"  Done in {elapsed:.1f}s")
        print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download historical kline data")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=SYMBOLS,
        help="Symbols to download",
    )
    parser.add_argument(
        "--interval",
        default=None,
        help="Single interval (default: all configured)",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export to Parquet after download",
    )
    args = parser.parse_args()

    intervals = [args.interval] if args.interval else [PRIMARY_TIMEFRAME] + SUPPORT_TIMEFRAMES

    asyncio.run(main(args.symbols, intervals, args.export))
