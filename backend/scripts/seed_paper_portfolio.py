"""Seed script: initialize paper trading portfolio with 10,000 USDT.

Usage:
    python -m scripts.seed_paper_portfolio
"""
import asyncio
from decimal import Decimal

from app.config import settings
from app.core.database import async_session_factory
from app.domain.enums import ExecutionMode
from app.models.risk_config import RiskConfig
from app.models.strategy_config import StrategyConfig
from app.services.portfolio_service import PortfolioService


async def seed():
    async with async_session_factory() as session:
        # Create paper portfolio
        svc = PortfolioService(session)
        portfolio = await svc.get_or_create(
            mode=ExecutionMode.PAPER,
            initial_balance=Decimal(str(settings.paper_initial_balance)),
        )
        print(f"Paper portfolio: {portfolio.total_balance} USDT")

        # Create default risk config
        from sqlalchemy import select
        stmt = select(RiskConfig).where(RiskConfig.name == "default")
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            risk = RiskConfig(name="default")
            session.add(risk)
            print("Default risk config created")
        else:
            print("Default risk config already exists")

        # Create default momentum strategy config
        stmt = select(StrategyConfig).where(StrategyConfig.name == "momentum_btc_eth")
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            strategy = StrategyConfig(
                name="momentum_btc_eth",
                description="Momentum strategy (RSI + SMA) for BTC and ETH",
                strategy_type="momentum",
                parameters={
                    "rsi_period": 14,
                    "sma_fast": 9,
                    "sma_slow": 21,
                    "rsi_weight": 0.4,
                    "sma_weight": 0.6,
                },
                symbols=["BTCUSDT", "ETHUSDT"],
                timeframe="1h",
                is_active=True,
            )
            session.add(strategy)
            print(f"Strategy 'momentum_btc_eth' created (ID: {strategy.id})")
        else:
            print("Strategy 'momentum_btc_eth' already exists")

        # Create stock momentum strategy config (if Alpaca enabled)
        if settings.alpaca_enabled:
            stmt = select(StrategyConfig).where(StrategyConfig.name == "stock_momentum_us")
            result = await session.execute(stmt)
            if result.scalar_one_or_none() is None:
                stock_strategy = StrategyConfig(
                    name="stock_momentum_us",
                    description="Stock momentum strategy (RSI 35/65 + SMA 10/30) for US equities",
                    strategy_type="stock_momentum",
                    parameters={
                        "rsi_period": 14,
                        "rsi_oversold": 35,
                        "rsi_overbought": 65,
                        "sma_fast": 10,
                        "sma_slow": 30,
                        "rsi_weight": 0.5,
                        "sma_weight": 0.5,
                    },
                    symbols=settings.stock_symbols,
                    timeframe="1d",
                    is_active=True,
                )
                session.add(stock_strategy)
                print(f"Strategy 'stock_momentum_us' created (ID: {stock_strategy.id})")
            else:
                print("Strategy 'stock_momentum_us' already exists")

        await session.commit()
        print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
