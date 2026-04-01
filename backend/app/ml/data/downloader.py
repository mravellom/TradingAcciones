"""Historical OHLCV data downloader from Binance.

Downloads kline data in chunks and stores in PostgreSQL + Parquet files.
Handles rate limiting and resume from last downloaded timestamp.
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pandas as pd
from binance import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.ml.config import (
    DOWNLOAD_START, ML_DATA_DIR, RAW_DIR, SYMBOLS, PRIMARY_TIMEFRAME,
    SUPPORT_TIMEFRAMES, STOCK_SYMBOLS, STOCK_PRIMARY_TIMEFRAME, STOCK_SUPPORT_TIMEFRAMES,
)
from app.models.kline_history import KlineHistory

logger = get_logger(__name__)

# Binance returns max 1000 klines per request
BATCH_SIZE = 1000

# Delay between requests to respect rate limits
REQUEST_DELAY = 0.2  # seconds

# Timeframe to milliseconds
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class HistoricalDataDownloader:
    """Downloads and stores historical kline data from Binance."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._client: AsyncClient | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = await AsyncClient.create()
            logger.info("binance_downloader_connected")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close_connection()
            self._client = None

    async def download_symbol(
        self,
        symbol: str,
        interval: str = "1h",
        start_date: str = DOWNLOAD_START,
    ) -> int:
        """Download all historical klines for a symbol.

        Returns the number of new klines inserted.
        """
        await self.connect()

        # Check last downloaded timestamp
        last_ts = await self._get_last_timestamp(symbol, interval)
        if last_ts:
            start_ms = int(last_ts.timestamp() * 1000) + INTERVAL_MS[interval]
            logger.info(
                "download_resuming",
                symbol=symbol,
                interval=interval,
                from_date=last_ts.isoformat(),
            )
        else:
            start_ms = int(
                datetime.strptime(start_date, "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .timestamp() * 1000
            )
            logger.info(
                "download_starting",
                symbol=symbol,
                interval=interval,
                from_date=start_date,
            )

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        total_inserted = 0
        current_ms = start_ms

        while current_ms < now_ms:
            try:
                raw_klines = await self._client.get_klines(
                    symbol=symbol,
                    interval=interval,
                    startTime=current_ms,
                    limit=BATCH_SIZE,
                )
            except Exception as e:
                logger.error(
                    "download_batch_error",
                    symbol=symbol,
                    error=str(e),
                )
                await asyncio.sleep(5)
                continue

            if not raw_klines:
                break

            # Insert batch
            count = await self._insert_batch(symbol, interval, raw_klines)
            total_inserted += count

            # Move to next batch
            last_close_time = raw_klines[-1][6]  # close_time in ms
            current_ms = last_close_time + 1

            if len(raw_klines) < BATCH_SIZE:
                break  # No more data

            await asyncio.sleep(REQUEST_DELAY)

            if total_inserted % 5000 == 0 and total_inserted > 0:
                logger.info(
                    "download_progress",
                    symbol=symbol,
                    interval=interval,
                    klines=total_inserted,
                )

        await self._session.commit()

        logger.info(
            "download_complete",
            symbol=symbol,
            interval=interval,
            new_klines=total_inserted,
        )
        return total_inserted

    async def download_all(
        self,
        symbols: list[str] | None = None,
        intervals: list[str] | None = None,
    ) -> dict[str, int]:
        """Download data for all configured symbols and intervals."""
        symbols = symbols or SYMBOLS
        intervals = intervals or [PRIMARY_TIMEFRAME] + SUPPORT_TIMEFRAMES

        results = {}
        for symbol in symbols:
            for interval in intervals:
                key = f"{symbol}_{interval}"
                count = await self.download_symbol(symbol, interval)
                results[key] = count
                logger.info("download_symbol_done", symbol=symbol, interval=interval, count=count)

        return results

    async def export_to_parquet(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> Path:
        """Export kline data to a Parquet file for fast ML access."""
        stmt = (
            select(KlineHistory)
            .where(
                KlineHistory.symbol == symbol,
                KlineHistory.interval == interval,
            )
            .order_by(KlineHistory.open_time)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            raise ValueError(f"No data for {symbol} {interval}")

        data = [
            {
                "open_time": r.open_time,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
                "close_time": r.close_time,
            }
            for r in rows
        ]

        df = pd.DataFrame(data)
        df.set_index("open_time", inplace=True)

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path = RAW_DIR / f"{symbol}_{interval}.parquet"
        df.to_parquet(path, engine="pyarrow")

        logger.info(
            "exported_parquet",
            symbol=symbol,
            interval=interval,
            rows=len(df),
            path=str(path),
        )
        return path

    async def get_dataframe(
        self,
        symbol: str,
        interval: str = "1h",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Load kline data as a pandas DataFrame."""
        stmt = (
            select(KlineHistory)
            .where(
                KlineHistory.symbol == symbol,
                KlineHistory.interval == interval,
            )
        )
        if start:
            stmt = stmt.where(KlineHistory.open_time >= start)
        if end:
            stmt = stmt.where(KlineHistory.open_time <= end)

        stmt = stmt.order_by(KlineHistory.open_time)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        data = [
            {
                "open_time": r.open_time,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
            }
            for r in rows
        ]

        df = pd.DataFrame(data)
        if not df.empty:
            df.set_index("open_time", inplace=True)
        return df

    async def download_stock_symbol(
        self,
        symbol: str,
        interval: str = "1d",
        start_date: str = DOWNLOAD_START,
    ) -> int:
        """Download historical bars from Alpaca for a stock symbol.

        Returns the number of new klines inserted.
        """
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        from app.config import settings

        timeframe_map = {
            "1h": TimeFrame(1, TimeFrameUnit.Hour),
            "4h": TimeFrame(4, TimeFrameUnit.Hour),
            "1d": TimeFrame(1, TimeFrameUnit.Day),
        }
        tf = timeframe_map.get(interval)
        if tf is None:
            raise ValueError(f"Unsupported interval for stocks: {interval}")

        client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
        )

        # Check last downloaded timestamp
        last_ts = await self._get_last_timestamp(symbol, interval)
        if last_ts:
            interval_ms = INTERVAL_MS.get(interval, 86_400_000)
            start_dt = last_ts + pd.Timedelta(milliseconds=interval_ms)
            logger.info("download_stock_resuming", symbol=symbol, from_date=start_dt.isoformat())
        else:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            logger.info("download_stock_starting", symbol=symbol, from_date=start_date)

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start_dt,
        )
        bars_response = client.get_stock_bars(request)
        bars = bars_response[symbol] if symbol in bars_response else []

        if not bars:
            logger.info("download_stock_no_data", symbol=symbol)
            return 0

        # Convert to kline rows and insert
        rows = []
        for bar in bars:
            duration_ms = INTERVAL_MS.get(interval, 86_400_000)
            rows.append({
                "id": uuid4(),
                "symbol": symbol,
                "interval": interval,
                "open_time": bar.timestamp,
                "open": Decimal(str(bar.open)),
                "high": Decimal(str(bar.high)),
                "low": Decimal(str(bar.low)),
                "close": Decimal(str(bar.close)),
                "volume": Decimal(str(bar.volume)),
                "close_time": bar.timestamp + pd.Timedelta(milliseconds=duration_ms),
            })

        if not rows:
            return 0

        stmt = pg_insert(KlineHistory).values(rows)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["symbol", "interval", "open_time"]
        )
        result = await self._session.execute(stmt)
        await self._session.commit()

        total = result.rowcount or 0
        logger.info("download_stock_complete", symbol=symbol, interval=interval, new_klines=total)
        return total

    async def download_all_stocks(
        self,
        symbols: list[str] | None = None,
        intervals: list[str] | None = None,
    ) -> dict[str, int]:
        """Download data for all configured stock symbols."""
        symbols = symbols or STOCK_SYMBOLS
        intervals = intervals or [STOCK_PRIMARY_TIMEFRAME] + STOCK_SUPPORT_TIMEFRAMES

        results = {}
        for symbol in symbols:
            for interval in intervals:
                key = f"{symbol}_{interval}"
                count = await self.download_stock_symbol(symbol, interval)
                results[key] = count
        return results

    async def get_stats(self) -> list[dict]:
        """Get download stats per symbol/interval."""
        stmt = select(
            KlineHistory.symbol,
            KlineHistory.interval,
            func.count(KlineHistory.id).label("count"),
            func.min(KlineHistory.open_time).label("first"),
            func.max(KlineHistory.open_time).label("last"),
        ).group_by(KlineHistory.symbol, KlineHistory.interval)

        result = await self._session.execute(stmt)
        return [
            {
                "symbol": r.symbol,
                "interval": r.interval,
                "count": r.count,
                "first": r.first.isoformat() if r.first else None,
                "last": r.last.isoformat() if r.last else None,
            }
            for r in result.all()
        ]

    async def _get_last_timestamp(self, symbol: str, interval: str) -> datetime | None:
        stmt = select(func.max(KlineHistory.open_time)).where(
            KlineHistory.symbol == symbol,
            KlineHistory.interval == interval,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _insert_batch(
        self, symbol: str, interval: str, raw_klines: list
    ) -> int:
        """Insert klines using upsert (ON CONFLICT DO NOTHING)."""
        rows = []
        for k in raw_klines:
            rows.append({
                "id": uuid4(),
                "symbol": symbol,
                "interval": interval,
                "open_time": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                "open": Decimal(str(k[1])),
                "high": Decimal(str(k[2])),
                "low": Decimal(str(k[3])),
                "close": Decimal(str(k[4])),
                "volume": Decimal(str(k[5])),
                "close_time": datetime.fromtimestamp(k[6] / 1000, tz=timezone.utc),
            })

        if not rows:
            return 0

        stmt = pg_insert(KlineHistory).values(rows)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["symbol", "interval", "open_time"]
        )
        result = await self._session.execute(stmt)
        await self._session.flush()

        return result.rowcount or 0
