"""
Stock Tracking Service
Manages the curated stock tracking portfolio with AI-driven daily decisions.
"""

import json
import os
import time
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas as pd

from app import db
from app.models.analysis import (
    TrackingStock, TrackingTransaction, TrackingDailySnapshot, TrackingDecisionLog
)
from app.services.data_provider import DataProvider
from app.services.ai_analyzer import AIAnalyzer

# Initial virtual capital
INITIAL_CAPITAL = 100_000.0
# Max number of stocks in the tracking list
MAX_HOLDINGS = 10
# Per-stock allocation = INITIAL_CAPITAL / MAX_HOLDINGS
PER_STOCK_ALLOCATION = INITIAL_CAPITAL / MAX_HOLDINGS
# Benchmark tickers (use ETFs instead of index symbols for better yfinance compatibility)
BENCHMARK_SP500 = "SPY"
BENCHMARK_NASDAQ100 = "QQQ"
# Inception date for performance comparison
INCEPTION_DATE = "2026-02-09"

# US Eastern timezone for consistent date handling with US stock markets
_US_EASTERN = ZoneInfo("America/New_York")


def _us_eastern_today() -> date:
    """Return today's date in US Eastern time (EST/EDT)."""
    return datetime.now(_US_EASTERN).date()


class TrackingService:
    """Service for managing curated stock tracking portfolio."""

    def __init__(self):
        self.ai_analyzer = AIAnalyzer()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_current_holdings(self) -> List[Dict]:
        """Get all currently tracked stocks with latest prices and allocation percentages."""
        stocks = TrackingStock.query.order_by(TrackingStock.buy_date.asc()).all()
        if not stocks:
            return []

        # Calculate total portfolio value (holdings + cash) for allocation %
        cash, _, _ = self._calculate_cash()

        # Compute each holding's current market value
        holdings_data = []
        total_holdings_value = 0.0
        for s in stocks:
            price = s.current_price or s.buy_price
            cost = s.get_cost_amount()
            shares = cost / s.buy_price
            market_value = shares * price
            total_holdings_value += market_value
            holdings_data.append((s, shares, market_value))

        portfolio_value = cash + total_holdings_value

        # Build result with allocation_pct
        result = []
        for s, shares, market_value in holdings_data:
            d = s.to_dict()
            d['shares'] = round(shares, 4)
            d['market_value'] = round(market_value, 2)
            d['allocation_pct'] = round((market_value / portfolio_value) * 100, 2) if portfolio_value > 0 else 0
            result.append(d)

        return result

    def get_transaction_history(self, limit: int = 50) -> List[Dict]:
        """Get recent transaction history."""
        txns = TrackingTransaction.query.order_by(
            TrackingTransaction.date.desc()
        ).limit(limit).all()
        return [t.to_dict() for t in txns]

    def get_decision_logs(self, limit: int = 30) -> List[Dict]:
        """Get recent AI decision logs."""
        logs = TrackingDecisionLog.query.order_by(
            TrackingDecisionLog.date.desc()
        ).limit(limit).all()
        return [l.to_dict() for l in logs]

    def get_daily_snapshots(self, start_date: str = None) -> List[Dict]:
        """Get daily portfolio value snapshots."""
        query = TrackingDailySnapshot.query
        if start_date:
            query = query.filter(TrackingDailySnapshot.date >= start_date)
        snapshots = query.order_by(TrackingDailySnapshot.date.asc()).all()
        return [s.to_dict() for s in snapshots]

    def get_portfolio_summary(self) -> Dict:
        """Get portfolio summary including performance metrics."""
        holdings = TrackingStock.query.all()

        total_holdings_value = 0.0
        total_cost = 0.0
        for h in holdings:
            price = h.current_price or h.buy_price
            cost = h.get_cost_amount()
            total_holdings_value += price * (cost / h.buy_price)
            total_cost += cost

        # Calculate cash using flow-based method (replay all transactions)
        num_current = len(holdings)
        cash, total_sell_returns, total_realized_pnl = self._calculate_cash()
        portfolio_value = cash + total_holdings_value
        total_return_pct = ((portfolio_value - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100

        # Latest snapshot
        latest_snapshot = TrackingDailySnapshot.query.order_by(
            TrackingDailySnapshot.date.desc()
        ).first()

        # Latest decision
        latest_decision = TrackingDecisionLog.query.order_by(
            TrackingDecisionLog.date.desc()
        ).first()

        return {
            'initial_capital': INITIAL_CAPITAL,
            'portfolio_value': round(portfolio_value, 2),
            'cash': round(cash, 2),
            'holdings_value': round(total_holdings_value, 2),
            'total_return_pct': round(total_return_pct, 2),
            'realized_pnl': round(total_realized_pnl, 2),
            'unrealized_pnl': round(total_holdings_value - total_cost, 2) if holdings else 0,
            'num_holdings': num_current,
            'max_holdings': MAX_HOLDINGS,
            'per_stock_allocation': PER_STOCK_ALLOCATION,
            'inception_date': INCEPTION_DATE,
            'last_snapshot_date': latest_snapshot.date.strftime('%Y-%m-%d') if latest_snapshot else None,
            'last_decision_date': latest_decision.date.strftime('%Y-%m-%d') if latest_decision else None,
            'last_decision_has_changes': latest_decision.has_changes if latest_decision else None,
        }

    def get_benchmark_comparison(self, start_date: str = None) -> Dict:
        """
        Get portfolio performance vs benchmarks (S&P 500 and NASDAQ 100).
        Returns aligned date series for charting.
        All three curves start from 0% at INCEPTION_DATE (the origin).
        Benchmark returns are rebased so that their value on inception date = 0.
        """
        if not start_date:
            start_date = INCEPTION_DATE

        snapshots = TrackingDailySnapshot.query.filter(
            TrackingDailySnapshot.date >= start_date
        ).order_by(TrackingDailySnapshot.date.asc()).all()

        # Determine date range: always start from inception, end at today or last snapshot
        today_str = _us_eastern_today().strftime('%Y-%m-%d')
        if snapshots:
            last_date = max(snapshots[-1].date.strftime('%Y-%m-%d'), today_str)
        else:
            last_date = today_str

        # Fetch benchmark data from inception to present
        sp500_data = self._get_benchmark_series(BENCHMARK_SP500, start_date, last_date)
        nasdaq_data = self._get_benchmark_series(BENCHMARK_NASDAQ100, start_date, last_date)

        if not sp500_data and not nasdaq_data:
            return {'portfolio': [], 'sp500': [], 'nasdaq100': [], 'dates': [], 'portfolio_start_index': None}

        # Build snapshot lookup
        snapshot_map = {}
        for snap in snapshots:
            snapshot_map[snap.date.strftime('%Y-%m-%d')] = snap

        # Build date list: include inception, all benchmark dates, AND all snapshot dates
        benchmark_dates = set(list(sp500_data.keys()) + list(nasdaq_data.keys()))
        all_dates_set = set(benchmark_dates)
        # Always include inception date as the first point (even if it's a weekend)
        all_dates_set.add(start_date)
        # Include snapshot dates, but cap at the latest benchmark date to avoid
        # timezone mismatch (e.g. local date is 2/12 but US markets haven't opened yet,
        # so benchmark data only goes to 2/11).
        latest_benchmark_date = max(benchmark_dates) if benchmark_dates else today_str
        for snap_date_str in snapshot_map.keys():
            if snap_date_str <= latest_benchmark_date:
                all_dates_set.add(snap_date_str)
        all_dates = sorted(all_dates_set)

        # Rebase benchmarks: find the first available benchmark value and subtract it
        # so the curve starts at 0% on (or near) inception date.
        first_sp500_val = None
        first_nasdaq_val = None
        for d in all_dates:
            if first_sp500_val is None and d in sp500_data:
                first_sp500_val = sp500_data[d]
            if first_nasdaq_val is None and d in nasdaq_data:
                first_nasdaq_val = nasdaq_data[d]
            if first_sp500_val is not None and first_nasdaq_val is not None:
                break
        if first_sp500_val is None:
            first_sp500_val = 0.0
        if first_nasdaq_val is None:
            first_nasdaq_val = 0.0

        # Find where portfolio data begins
        first_snapshot_date = snapshots[0].date.strftime('%Y-%m-%d') if snapshots else None
        portfolio_start_index = None

        dates = []
        portfolio_series = []
        sp500_series = []
        nasdaq_series = []

        last_portfolio_value = None  # For forward-filling gaps between snapshots

        for d in all_dates:
            dates.append(d)

            # Benchmark values rebased to 0 at inception
            sp_val = sp500_data.get(d)
            nq_val = nasdaq_data.get(d)
            if d == start_date:
                # Force 0 at inception, even if benchmark has no data for this date
                sp500_series.append(0.0)
                nasdaq_series.append(0.0)
            else:
                sp500_series.append(round(sp_val - first_sp500_val, 2) if sp_val is not None else None)
                nasdaq_series.append(round(nq_val - first_nasdaq_val, 2) if nq_val is not None else None)

            # Portfolio series: use actual total_return_pct (already 0 at inception)
            snap = snapshot_map.get(d)
            if snap:
                val = round(snap.total_return_pct, 2)
                portfolio_series.append(val)
                last_portfolio_value = val
                if portfolio_start_index is None:
                    portfolio_start_index = len(dates) - 1
            elif last_portfolio_value is not None:
                # Forward-fill for dates without a snapshot (e.g. weekends in between)
                portfolio_series.append(last_portfolio_value)
            else:
                # Before the first snapshot, no data
                portfolio_series.append(None)

        return {
            'dates': dates,
            'portfolio': portfolio_series,
            'sp500': sp500_series,
            'nasdaq100': nasdaq_series,
            'portfolio_start_index': portfolio_start_index
        }

    def _get_benchmark_series(self, ticker: str, start_date: str, end_date: str) -> Dict[str, float]:
        """Fetch benchmark return series as {date_str: return_pct}."""
        try:
            # Add buffer days for the end date
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=3)
            hist = yf.Ticker(ticker).history(
                start=start_date,
                end=end_dt.strftime('%Y-%m-%d'),
                auto_adjust=True
            )
            if hist is None or hist.empty:
                return {}

            base_price = float(hist['Close'].iloc[0])
            result = {}
            for idx, row in hist.iterrows():
                d = idx.strftime('%Y-%m-%d')
                ret = ((float(row['Close']) - base_price) / base_price) * 100
                result[d] = round(ret, 2)
            return result
        except Exception as e:
            print(f"Error fetching benchmark {ticker}: {e}")
            return {}

    # ------------------------------------------------------------------
    # Price refresh
    # ------------------------------------------------------------------

    def refresh_prices(self) -> Dict:
        """Update current prices for all tracked stocks using batch download to avoid rate limits."""
        stocks = TrackingStock.query.all()
        if not stocks:
            return {'updated': 0, 'total': 0}

        symbols = [s.symbol for s in stocks]
        updated = 0
        stock_map = {s.symbol: s for s in stocks}

        try:
            # Batch download: single API call for all symbols
            data = yf.download(symbols, period='1d', auto_adjust=True, progress=False)
            if data is not None and not data.empty:
                close = data['Close']
                if isinstance(close, pd.Series):
                    # Single symbol case
                    price = float(close.iloc[-1]) if not pd.isna(close.iloc[-1]) else None
                    if price is not None:
                        stocks[0].current_price = round(price, 2)
                        updated = 1
                else:
                    # Multiple symbols
                    for sym in symbols:
                        if sym in close.columns:
                            val = close[sym].iloc[-1]
                            if not pd.isna(val):
                                stock_map[sym].current_price = round(float(val), 2)
                                updated += 1

            # Retry failed symbols individually after a short delay
            if updated < len(stocks):
                failed_symbols = [s for s in symbols if stock_map[s].current_price is None or
                                  s not in (close.columns if not isinstance(close, pd.Series) else [symbols[0]])]
                # Also catch symbols whose batch value was NaN
                failed_symbols = [s for s in symbols
                                  if stock_map[s].current_price == stock_map[s].buy_price and
                                  stock_map[s].current_price is not None]
                # Simpler: just retry any stock that wasn't updated
                updated_syms = set()
                if isinstance(close, pd.Series):
                    if not pd.isna(close.iloc[-1]):
                        updated_syms.add(symbols[0])
                else:
                    for sym in symbols:
                        if sym in close.columns and not pd.isna(close[sym].iloc[-1]):
                            updated_syms.add(sym)

                failed_symbols = [s for s in symbols if s not in updated_syms]
                if failed_symbols:
                    print(f"[Tracking] Retrying {len(failed_symbols)} failed symbols after delay: {failed_symbols}")
                    time.sleep(5)
                    for sym in failed_symbols:
                        try:
                            price = DataProvider.get_current_price(sym)
                            if price is not None:
                                stock_map[sym].current_price = price
                                updated += 1
                            time.sleep(2)
                        except Exception as ex:
                            print(f"  Retry failed for {sym}: {ex}")

        except Exception as e:
            print(f"[Tracking] Batch price download failed: {e}, falling back to individual fetch")
            # Fallback: fetch individually with a small delay to reduce rate limit risk
            for stock in stocks:
                try:
                    price = DataProvider.get_current_price(stock.symbol)
                    if price is not None:
                        stock.current_price = price
                        updated += 1
                    time.sleep(2)
                except Exception as ex:
                    print(f"  Error refreshing price for {stock.symbol}: {ex}")

        db.session.commit()
        return {'updated': updated, 'total': len(stocks)}

    # ------------------------------------------------------------------
    # Daily snapshot
    # ------------------------------------------------------------------

    def take_daily_snapshot(self, snapshot_date: date = None,
                            price_cache: Dict[str, Dict[str, float]] = None) -> Optional[Dict]:
        """
        Take (or update) a daily portfolio value snapshot.
        Correctly reconstructs the portfolio state *as of snapshot_date* by
        replaying BUY/SELL transactions up to (and including) that date.

        Args:
            snapshot_date: The date to snapshot. Defaults to today.
            price_cache: Optional pre-fetched historical prices
                         {symbol: {date_str: close_price}} to avoid
                         redundant yfinance calls during bulk backfill.
        """
        if snapshot_date is None:
            snapshot_date = _us_eastern_today()

        is_today = (snapshot_date == _us_eastern_today())

        # --- Step 1: Reconstruct holdings as of snapshot_date ---
        holdings_at_date, sell_txns_at_date = self._reconstruct_holdings_at_date(snapshot_date)

        # --- Step 2: Get prices for each holding ---
        # For today, prefer live DB prices; for historical dates, use cache or yfinance
        symbols_needing_price = [h['symbol'] for h in holdings_at_date]

        if is_today:
            # Use current DB prices (already refreshed by refresh_prices)
            current_stocks = {s.symbol: s for s in TrackingStock.query.all()}
            for h in holdings_at_date:
                stock = current_stocks.get(h['symbol'])
                if stock and stock.current_price:
                    h['current_price'] = stock.current_price
                else:
                    h['current_price'] = h['buy_price']
        else:
            # Historical date: use price_cache or fetch from yfinance
            date_str = snapshot_date.strftime('%Y-%m-%d')
            historical_prices = {}
            if price_cache:
                for sym in symbols_needing_price:
                    if sym in price_cache and date_str in price_cache[sym]:
                        historical_prices[sym] = price_cache[sym][date_str]

            # Fetch missing prices
            missing = [s for s in symbols_needing_price if s not in historical_prices]
            if missing:
                fetched = self._get_historical_prices(missing, snapshot_date)
                historical_prices.update(fetched)

            for h in holdings_at_date:
                h['current_price'] = historical_prices.get(h['symbol'], h['buy_price'])

        # --- Step 3: Calculate portfolio values ---
        total_holdings_value = 0.0
        holdings_snapshot = []
        for h in holdings_at_date:
            price = h['current_price']
            buy_price = h['buy_price']
            cost = h.get('cost_amount', PER_STOCK_ALLOCATION)
            shares = cost / buy_price
            value = shares * price
            total_holdings_value += value
            holdings_snapshot.append({
                'symbol': h['symbol'],
                'name': h['name'],
                'buy_price': buy_price,
                'current_price': price,
                'cost_amount': round(cost, 2),
                'shares': round(shares, 4),
                'value': round(value, 2),
                'return_pct': round(((price - buy_price) / buy_price) * 100, 2)
            })

        # Calculate cash using flow-based method (replay all transactions up to snapshot_date)
        cash, total_sell_returns, total_realized_pnl = self._calculate_cash(as_of_date=snapshot_date)
        portfolio_value = cash + total_holdings_value
        total_return_pct = ((portfolio_value - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100

        # --- Step 4: Upsert snapshot ---
        existing = TrackingDailySnapshot.query.filter_by(date=snapshot_date).first()
        if existing:
            existing.portfolio_value = round(portfolio_value, 2)
            existing.cash = round(cash, 2)
            existing.holdings_value = round(total_holdings_value, 2)
            existing.total_return_pct = round(total_return_pct, 4)
            existing.realized_pnl = round(total_realized_pnl, 2)
            existing.holdings_json = json.dumps(holdings_snapshot)
            db.session.commit()
            return existing.to_dict()

        snapshot = TrackingDailySnapshot(
            date=snapshot_date,
            portfolio_value=round(portfolio_value, 2),
            cash=round(cash, 2),
            holdings_value=round(total_holdings_value, 2),
            total_return_pct=round(total_return_pct, 4),
            realized_pnl=round(total_realized_pnl, 2),
            holdings_json=json.dumps(holdings_snapshot)
        )
        db.session.add(snapshot)
        db.session.commit()
        return snapshot.to_dict()

    # ------------------------------------------------------------------
    # Helpers for time-aware snapshot reconstruction
    # ------------------------------------------------------------------

    def _reconstruct_holdings_at_date(self, as_of_date: date):
        """
        Replay BUY/SELL transactions up to *as_of_date* (inclusive) to
        determine which stocks were held on that date.

        Returns:
            (holdings_list, sell_txns_list)
            holdings_list: [{symbol, name, buy_price, buy_date}, ...]
            sell_txns_list: list of TrackingTransaction SELL objects up to as_of_date
        """
        # All transactions up to and including as_of_date, ordered chronologically
        txns = TrackingTransaction.query.filter(
            TrackingTransaction.date <= as_of_date
        ).order_by(TrackingTransaction.date.asc(), TrackingTransaction.id.asc()).all()

        # Reconstruct holdings by replaying transactions
        holdings_map = {}  # symbol -> {symbol, name, buy_price, buy_date, cost_amount}
        sell_txns = []

        for tx in txns:
            if tx.action == 'BUY':
                holdings_map[tx.symbol] = {
                    'symbol': tx.symbol,
                    'name': tx.name or tx.symbol,
                    'buy_price': tx.price,
                    'buy_date': tx.date.strftime('%Y-%m-%d'),
                    'cost_amount': tx.get_cost_amount(),
                }
            elif tx.action == 'SELL':
                holdings_map.pop(tx.symbol, None)
                sell_txns.append(tx)

        return list(holdings_map.values()), sell_txns

    def _calculate_cash(self, as_of_date: date = None) -> tuple:
        """
        Calculate cash balance by replaying BUY/SELL transactions (flow-based).
        This avoids the bug where `num_holdings * PER_STOCK_ALLOCATION` assumes
        every position costs exactly PER_STOCK_ALLOCATION, ignoring that a
        replacement stock is funded from the actual sell proceeds (which may
        differ from PER_STOCK_ALLOCATION if the sold stock had gains/losses).

        Args:
            as_of_date: Only consider transactions up to this date (inclusive).
                        None means all transactions.

        Returns:
            (cash, total_sell_returns, total_realized_pnl)
        """
        query = TrackingTransaction.query
        if as_of_date is not None:
            query = query.filter(TrackingTransaction.date <= as_of_date)
        txns = query.order_by(TrackingTransaction.date.asc(), TrackingTransaction.id.asc()).all()

        cash = INITIAL_CAPITAL
        total_sell_returns = 0.0
        total_realized_pnl = 0.0

        for tx in txns:
            if tx.action == 'BUY':
                cost = tx.get_cost_amount()
                cash -= cost
            elif tx.action == 'SELL':
                if tx.buy_price and tx.buy_price > 0:
                    # The cost_amount on a SELL tx records the original cost of the position
                    original_cost = tx.get_cost_amount()
                    shares = original_cost / tx.buy_price
                    sell_value = shares * tx.price
                    cash += sell_value
                    total_sell_returns += sell_value
                    total_realized_pnl += sell_value - original_cost

        return cash, total_sell_returns, total_realized_pnl

    def _get_historical_prices(self, symbols: List[str], target_date: date) -> Dict[str, float]:
        """
        Fetch the closing price for each symbol on *target_date*.
        Falls back to the nearest prior trading day if target_date has no data
        (e.g. weekend, holiday).

        Returns: {symbol: close_price}
        """
        result = {}
        # Fetch a small window around target_date to handle weekends/holidays
        start = target_date - timedelta(days=5)
        end = target_date + timedelta(days=1)
        target_str = target_date.strftime('%Y-%m-%d')

        for sym in symbols:
            try:
                hist = yf.Ticker(sym).history(
                    start=start.strftime('%Y-%m-%d'),
                    end=end.strftime('%Y-%m-%d'),
                    auto_adjust=True
                )
                if hist is not None and not hist.empty:
                    # Try exact date first, then fall back to last available
                    if target_str in hist.index.strftime('%Y-%m-%d'):
                        idx = list(hist.index.strftime('%Y-%m-%d')).index(target_str)
                        result[sym] = float(hist['Close'].iloc[idx])
                    else:
                        # Use the last available close before or on target_date
                        result[sym] = float(hist['Close'].iloc[-1])
                else:
                    print(f"[Snapshot] No price data for {sym} around {target_str}")
            except Exception as e:
                print(f"[Snapshot] Error fetching price for {sym} on {target_str}: {e}")
        return result

    def _bulk_fetch_historical_prices(self, symbols: List[str],
                                       start_date: date, end_date: date
                                       ) -> Dict[str, Dict[str, float]]:
        """
        Bulk-fetch daily close prices for multiple symbols over a date range.
        Much more efficient than per-date fetching for backfill.

        Returns: {symbol: {date_str: close_price, ...}, ...}
        """
        result = {sym: {} for sym in symbols}
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = (end_date + timedelta(days=3)).strftime('%Y-%m-%d')

        for sym in symbols:
            try:
                hist = yf.Ticker(sym).history(
                    start=start_str, end=end_str, auto_adjust=True
                )
                if hist is not None and not hist.empty:
                    for idx, row in hist.iterrows():
                        d = idx.strftime('%Y-%m-%d')
                        result[sym][d] = float(row['Close'])
            except Exception as e:
                print(f"[Backfill] Error fetching history for {sym}: {e}")
        return result

    # ------------------------------------------------------------------
    # AI Decision
    # ------------------------------------------------------------------

    def run_daily_decision(self, model_name: str = "gemini-3-flash-preview") -> Dict:
        """
        Run the AI daily deep-research decision to potentially update the tracking portfolio.
        Produces a structured daily research report with three-phase analysis.
        Returns the decision log entry.
        """
        today = _us_eastern_today()

        # Get current portfolio state
        holdings = TrackingStock.query.all()
        holdings_info = []
        for h in holdings:
            price = h.current_price or h.buy_price
            cost = h.get_cost_amount()
            shares = cost / h.buy_price
            ret_pct = ((price - h.buy_price) / h.buy_price) * 100
            holdings_info.append({
                'symbol': h.symbol,
                'name': h.name or h.symbol,
                'buy_price': h.buy_price,
                'buy_date': h.buy_date.strftime('%Y-%m-%d'),
                'current_price': price,
                'cost_amount': round(cost, 2),
                'return_pct': round(ret_pct, 2),
                'shares': round(shares, 4),
                'value': round(shares * price, 2)
            })

        # Get recent transaction history
        recent_txns = TrackingTransaction.query.order_by(
            TrackingTransaction.date.desc()
        ).limit(20).all()
        txn_history = [t.to_dict() for t in recent_txns]

        # Calculate portfolio state using flow-based cash method
        cash, total_sell_returns, total_realized_pnl = self._calculate_cash()
        num_current = len(holdings)
        available_slots = MAX_HOLDINGS - num_current
        holdings_value = sum(
            (h.get_cost_amount() / h.buy_price) * (h.current_price or h.buy_price)
            for h in holdings
        )
        portfolio_value = cash + holdings_value

        # Build decision retrospective from recent decision logs
        decision_retrospective = self._build_decision_retrospective()

        # Build the AI prompt
        prompt_result = self._build_decision_prompt(
            holdings_info=holdings_info,
            txn_history=txn_history,
            portfolio_value=portfolio_value,
            cash=cash,
            total_realized_pnl=total_realized_pnl,
            available_slots=available_slots,
            num_current=num_current,
            today=today,
            decision_retrospective=decision_retrospective
        )

        # Run AI agent with higher iteration limit for deep analysis
        start_time = time.time()
        try:
            supports, config, adapter = self.ai_analyzer._check_agent_support(model_name)
            if not supports:
                raise ValueError(f"Model {model_name} does not support tool calling")

            tool_executor = self.ai_analyzer._create_tool_executor(
                asset_type='STOCK',
                provider=config.get('provider')
            )

            text, usage, elapsed = self.ai_analyzer._run_agent(
                adapter, prompt_result, tool_executor,
                label="TrackingDecisionAgent",
                max_iterations=45,
                Model=model_name
            )

            result = self.ai_analyzer._parse_json_response(text)
            elapsed_seconds = time.time() - start_time

        except Exception as e:
            print(f"[TrackingDecision] ❌ Failed: {e}")
            # Log the failure
            log = TrackingDecisionLog(
                date=today,
                model_name=model_name,
                has_changes=False,
                summary=f"AI decision failed: {str(e)}",
                actions_json="[]",
                raw_response=str(e),
                elapsed_seconds=time.time() - start_time
            )
            db.session.add(log)
            db.session.commit()
            return log.to_dict()

        # Process the AI's decisions
        # First pass: execute all SELLs and collect proceeds for replacement BUYs
        actions = result.get('actions', [])
        summary = result.get('summary', '')
        has_changes = len(actions) > 0
        executed_actions = []
        sell_proceeds_pool = 0.0  # Accumulated cash from sells, used for replacement buys

        # Execute SELLs first to free up cash
        for action in actions:
            act_type = action.get('action', '').upper()
            if act_type != 'SELL':
                continue
            symbol = action.get('symbol', '').upper()
            reason = action.get('reason', '')
            name = action.get('name', symbol)

            sell_value = self._execute_sell(symbol, reason, today)
            if sell_value is not None:
                sell_proceeds_pool += sell_value
                executed_actions.append({
                    'action': 'SELL', 'symbol': symbol, 'name': name,
                    'reason': reason, 'success': True,
                    'proceeds': round(sell_value, 2)
                })

        # Now execute BUYs: use sell proceeds for replacement, or cash for new slots
        # Recalculate available cash after sells
        current_cash, _, _ = self._calculate_cash()
        for action in actions:
            act_type = action.get('action', '').upper()
            if act_type != 'BUY':
                continue
            symbol = action.get('symbol', '').upper()
            reason = action.get('reason', '')
            name = action.get('name', symbol)

            # Determine cost_amount: use sell proceeds if available, otherwise use PER_STOCK_ALLOCATION from cash
            if sell_proceeds_pool > 0:
                # Use sell proceeds for this replacement buy
                buy_cost = sell_proceeds_pool
                sell_proceeds_pool = 0.0  # Consume the proceeds
            else:
                # Fresh buy from remaining cash
                buy_cost = min(PER_STOCK_ALLOCATION, current_cash)
                if buy_cost <= 0:
                    print(f"[Tracking] No cash available for BUY {symbol}, skipping")
                    continue

            success = self._execute_buy(symbol, name, reason, today, cost_amount=buy_cost)
            if success:
                current_cash -= buy_cost
                executed_actions.append({
                    'action': 'BUY', 'symbol': symbol, 'name': name,
                    'reason': reason, 'success': True,
                    'cost_amount': round(buy_cost, 2)
                })

        # Extract structured report fields
        market_regime_data = result.get('market_regime', {})
        market_regime = market_regime_data.get('assessment', 'UNKNOWN') if isinstance(market_regime_data, dict) else str(market_regime_data)
        confidence_level = result.get('confidence_level', 'UNKNOWN')

        # Build the full report JSON (exclude raw actions/summary to avoid duplication)
        report_data = {}
        for key in ['market_regime', 'holdings_review', 'opportunity_scan',
                     'portfolio_risk_assessment', 'confidence_level']:
            if key in result:
                report_data[key] = result[key]

        # Log the decision with full report
        log = TrackingDecisionLog(
            date=today,
            model_name=model_name,
            has_changes=len(executed_actions) > 0,
            summary=summary,
            actions_json=json.dumps(executed_actions),
            raw_response=text[:10000] if text else None,
            elapsed_seconds=elapsed_seconds,
            report_json=json.dumps(report_data, ensure_ascii=False) if report_data else None,
            market_regime=market_regime[:20] if market_regime else None,
            confidence_level=confidence_level[:20] if confidence_level else None
        )
        db.session.add(log)

        # Refresh all prices before snapshot (decision may have triggered rate limits)
        db.session.commit()
        print("[Tracking] Refreshing all stock prices before snapshot...")
        refresh_result = self.refresh_prices()
        print(f"[Tracking] Price refresh: updated {refresh_result['updated']}/{refresh_result['total']} stocks")
        self.take_daily_snapshot(today)

        return log.to_dict()

    def _execute_buy(self, symbol: str, name: str, reason: str, trade_date: date,
                     cost_amount: float = None) -> bool:
        """
        Execute a BUY action.

        Args:
            cost_amount: Actual capital to invest. Defaults to PER_STOCK_ALLOCATION
                         for fresh buys. For replacement buys (after a SELL), this
                         should be the actual sell proceeds so cash never goes negative.
        """
        if cost_amount is None:
            cost_amount = PER_STOCK_ALLOCATION

        # Check if already holding
        existing = TrackingStock.query.filter_by(symbol=symbol).first()
        if existing:
            print(f"[Tracking] Already holding {symbol}, skipping BUY")
            return False

        # Check max holdings
        current_count = TrackingStock.query.count()
        if current_count >= MAX_HOLDINGS:
            print(f"[Tracking] Max holdings ({MAX_HOLDINGS}) reached, skipping BUY {symbol}")
            return False

        # Get current price
        price = DataProvider.get_current_price(symbol)
        if price is None:
            print(f"[Tracking] Cannot get price for {symbol}, skipping BUY")
            return False

        # Add to tracking list
        stock = TrackingStock(
            symbol=symbol,
            name=name,
            buy_price=price,
            buy_date=trade_date,
            current_price=price,
            cost_amount=round(cost_amount, 2),
            reason=reason
        )
        db.session.add(stock)

        # Record transaction with actual cost_amount
        txn = TrackingTransaction(
            symbol=symbol,
            name=name,
            action='BUY',
            price=price,
            date=trade_date,
            reason=reason,
            cost_amount=round(cost_amount, 2)
        )
        db.session.add(txn)
        db.session.flush()

        print(f"[Tracking] ✅ BUY {symbol} @ ${price:.2f} (invested: ${cost_amount:,.2f})")
        return True

    def _execute_sell(self, symbol: str, reason: str, trade_date: date) -> Optional[float]:
        """
        Execute a SELL action.

        Returns:
            The actual cash proceeds from selling (shares * sell_price),
            or None if the sell failed.
        """
        stock = TrackingStock.query.filter_by(symbol=symbol).first()
        if not stock:
            print(f"[Tracking] Not holding {symbol}, skipping SELL")
            return None

        # Get current price for sell
        price = DataProvider.get_current_price(symbol)
        if price is None:
            price = stock.current_price or stock.buy_price

        # Calculate realized return and actual proceeds
        original_cost = stock.get_cost_amount()
        shares = original_cost / stock.buy_price
        sell_value = shares * price
        realized_pct = ((price - stock.buy_price) / stock.buy_price) * 100

        # Record transaction (cost_amount records the original investment cost)
        txn = TrackingTransaction(
            symbol=symbol,
            name=stock.name,
            action='SELL',
            price=price,
            date=trade_date,
            reason=reason,
            buy_price=stock.buy_price,
            realized_pct=round(realized_pct, 2),
            cost_amount=round(original_cost, 2)
        )
        db.session.add(txn)

        # Remove from tracking list
        db.session.delete(stock)
        db.session.flush()

        print(f"[Tracking] ✅ SELL {symbol} @ ${price:.2f} (return: {realized_pct:+.2f}%, proceeds: ${sell_value:,.2f})")
        return sell_value

    def _build_decision_retrospective(self) -> str:
        """
        Build a retrospective of recent decisions to provide feedback loop.
        Shows what was decided and what actually happened afterwards,
        so the AI can learn from past accuracy.
        """
        recent_logs = TrackingDecisionLog.query.order_by(
            TrackingDecisionLog.date.desc()
        ).limit(5).all()

        if not recent_logs:
            return ""

        # Get current holdings for price comparison
        current_holdings = {s.symbol: s for s in TrackingStock.query.all()}

        # Get recent sell transactions for outcome tracking
        recent_sells = TrackingTransaction.query.filter_by(action='SELL').order_by(
            TrackingTransaction.date.desc()
        ).limit(10).all()
        sell_outcomes = {}
        for tx in recent_sells:
            sell_outcomes[tx.symbol] = {
                'sell_date': tx.date.strftime('%Y-%m-%d'),
                'sell_price': tx.price,
                'buy_price': tx.buy_price,
                'realized_pct': tx.realized_pct
            }

        lines = []
        for log in recent_logs:
            entry = f"- **{log.date.strftime('%Y-%m-%d')}** (regime: {log.market_regime or 'N/A'}, confidence: {log.confidence_level or 'N/A'}):"
            if log.has_changes:
                actions = []
                if log.actions_json:
                    try:
                        actions = json.loads(log.actions_json)
                    except Exception:
                        pass
                for act in actions:
                    symbol = act.get('symbol', '?')
                    action_type = act.get('action', '?')
                    if action_type == 'BUY' and symbol in current_holdings:
                        stock = current_holdings[symbol]
                        current_ret = round(((stock.current_price - stock.buy_price) / stock.buy_price) * 100, 2) if stock.current_price and stock.buy_price else 0
                        entry += f"\n    {action_type} {symbol} → Currently {current_ret:+.2f}% since buy"
                    elif action_type == 'SELL' and symbol in sell_outcomes:
                        outcome = sell_outcomes[symbol]
                        entry += f"\n    {action_type} {symbol} → Realized {outcome['realized_pct']:+.2f}%"
                    else:
                        entry += f"\n    {action_type} {symbol}"
            else:
                entry += "\n    No changes made"
            lines.append(entry)

        return "Recent decision history and outcomes:\n" + "\n".join(lines)

    def _build_decision_prompt(self, holdings_info, txn_history, portfolio_value,
                                cash, total_realized_pnl, available_slots,
                                num_current, today, decision_retrospective="") -> str:
        """Build the AI prompt for daily deep-research decision making."""
        current_date = today.strftime('%Y-%m-%d')

        holdings_text = "No current holdings." if not holdings_info else json.dumps(holdings_info, indent=2)
        txn_text = "No recent transactions." if not txn_history else json.dumps(txn_history[:10], indent=2)

        from app.services.ai_analyzer import INVESTMENT_PHILOSOPHY

        tool_descriptions = self.ai_analyzer._get_tool_descriptions_text()

        # Build sector distribution text for concentration awareness
        sector_symbols = {}
        if holdings_info:
            for h in holdings_info:
                sym = h.get('symbol', 'UNKNOWN')
                sector_symbols.setdefault('holdings', []).append(sym)

        return f"""You are a **senior US equity portfolio strategist** producing a comprehensive Daily Research Report.
You have access to real-time market data tools AND web search. Your report must be thorough, data-driven, and actionable.

{INVESTMENT_PHILOSOPHY}

**DATE**: {current_date}

**TASK**: Produce a structured Daily Research Report for the curated US stock tracking portfolio.
The report follows a THREE-PHASE deep analysis pipeline. Execute ALL phases in order.

**PORTFOLIO STATE**:
- Initial Capital: ${INITIAL_CAPITAL:,.0f}
- Current Portfolio Value: ${portfolio_value:,.2f}
- Cash Available: ${cash:,.2f}
- Realized P&L: ${total_realized_pnl:,.2f}
- Current Holdings: {num_current}/{MAX_HOLDINGS}
- Available Slots for New Buys: {available_slots}
- Per-Stock Allocation: ${PER_STOCK_ALLOCATION:,.0f} (for fresh buys; replacement buys use actual sell proceeds)

**CURRENT HOLDINGS**:
{holdings_text}

**RECENT TRANSACTION HISTORY** (last 10):
{txn_text}

{f'''**DECISION RETROSPECTIVE** (review of recent past decisions):
{decision_retrospective}
''' if decision_retrospective else ''}

**YOUR AVAILABLE TOOLS**:
{tool_descriptions}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 1 -- MARKET REGIME & MACRO ASSESSMENT (DO THIS FIRST)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. `search_market_news` with query: "US stock market macro outlook Fed policy {current_date}"
2. `search_market_news` with query: "US stock market sector rotation hot sectors {current_date}"
3. `search_market_news` with query: "VIX market volatility risk sentiment {current_date}"
4. Synthesize findings into a **Market Regime Assessment**:
   - Classify regime: **RISK-ON** (broad risk appetite, uptrend) / **NEUTRAL** (mixed signals) / **RISK-OFF** (defensive, downtrend)
   - Identify **Sector Leadership**: which sectors are leading vs lagging
   - Note key macro events upcoming (FOMC, CPI, earnings season, etc.)
5. THIS REGIME ASSESSMENT GATES ALL SUBSEQUENT DECISIONS:
   - RISK-OFF → bias toward SELL/REDUCE, raise stop-loss levels, NO new BUY unless extreme conviction
   - NEUTRAL → selective, only high-conviction changes
   - RISK-ON → more open to new opportunities, consider adding to winners

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 2 -- HOLDINGS DEEP REVIEW (Score Card for EACH holding)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For EACH stock in current holdings, perform these steps:
1. `search_market_news` for the specific stock's recent news and catalysts
2. `batch_get_kline_data` (period="3mo") for all holdings -- check price trends
3. `batch_calculate_technical_indicators` (period="3mo") for all holdings -- MA, RSI, momentum
4. Score each holding on THREE dimensions (1-5 scale):

   **Catalyst Score** (Weight: 40%):
   - 5 = Strong new positive catalyst (earnings beat, major contract, sector tailwind)
   - 4 = Moderate positive catalyst or thesis intact
   - 3 = No significant news, thesis unchanged
   - 2 = Minor negative news or headwinds emerging
   - 1 = Thesis broken (earnings miss, regulatory risk, competitive loss)

   **Technical Score** (Weight: 35%):
   - 5 = Strong uptrend, MA5 > MA20 > MA60, RSI 50-65, volume confirming
   - 4 = Uptrend intact, minor pullback to support
   - 3 = Consolidation, no clear direction
   - 2 = Breaking below key moving averages, weakening momentum
   - 1 = Breakdown confirmed, death cross, RSI < 30 on high volume

   **Valuation Score** (Weight: 25%):
   - 5 = Near 6-month low, deeply attractive vs peers
   - 4 = Below average valuation, reasonable entry
   - 3 = Fair value, in-line with historical range
   - 2 = Stretched, near top of range
   - 1 = Extremely overvalued, speculative premium

5. Calculate **Composite Score** = Catalyst × 0.40 + Technical × 0.35 + Valuation × 0.25
6. Flag holdings with Composite < 2.5 as **SELL CANDIDATES**
7. Flag holdings with Composite > 4.0 as **STRONG HOLD / ADD candidates**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 3 -- OPPORTUNITY SCAN & FINAL DECISION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. If there are available slots ({available_slots} open) AND market regime is NOT RISK-OFF:
   a. `search_market_news` for "US stock market best opportunities strong momentum catalysts {current_date}"
   b. For any promising candidates, verify with `get_kline_data` and `calculate_technical_indicators`
   c. Only recommend BUY with **triple confirmation**: catalyst + technical setup + reasonable valuation
2. Cross-validate: Compare any BUY candidate against worst-performing current holding
   - If new candidate scores higher → consider SELL weakest + BUY new (rotation)
3. Portfolio Risk Check:
   - Sector concentration: are too many holdings in the same sector?
   - Correlation risk: would adding this stock increase portfolio correlation?
   - Overall exposure level appropriate for current market regime?

**DECISION RULES**:
- SELL: Composite Score < 2.5 OR thesis broken OR technical breakdown confirmed
- BUY: Triple confirmation (catalyst + technicals + valuation), Composite Score > 3.5, AND available slot
- HOLD: Composite Score 2.5-4.0 with no urgent action needed
- Do NOT churn -- only trade when conviction is HIGH
- Fresh positions are allocated ${PER_STOCK_ALLOCATION:,.0f}; replacement buys (after selling) use actual sell proceeds
- Quality over quantity: you are NOT required to fill all {MAX_HOLDINGS} slots

**SYMBOL FORMAT**: US stocks only -- use standard tickers like AAPL, TSLA, NVDA, etc.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT (JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return a SINGLE valid JSON object with this structure:
{{
    "market_regime": {{
        "assessment": "RISK-ON" or "NEUTRAL" or "RISK-OFF",
        "reasoning": "2-3 sentences explaining the regime classification based on macro data",
        "key_events": ["event1", "event2", "..."],
        "sector_leaders": ["Sector1", "Sector2"],
        "sector_laggards": ["Sector3", "Sector4"]
    }},
    "holdings_review": [
        {{
            "symbol": "TICKER",
            "catalyst_score": 4,
            "catalyst_notes": "Brief explanation of catalyst assessment",
            "technical_score": 3,
            "technical_notes": "Brief explanation of technical assessment",
            "valuation_score": 3,
            "valuation_notes": "Brief explanation of valuation assessment",
            "composite_score": 3.45,
            "recommendation": "HOLD" or "SELL" or "STRONG_HOLD",
            "key_levels": {{
                "support": 150.0,
                "resistance": 180.0
            }}
        }}
    ],
    "opportunity_scan": [
        {{
            "symbol": "TICKER",
            "name": "Company Name",
            "catalyst": "Description of the catalyst",
            "technical_setup": "Description of technical setup",
            "valuation": "Description of valuation",
            "composite_score": 4.1,
            "conviction": "HIGH" or "MEDIUM"
        }}
    ],
    "portfolio_risk_assessment": {{
        "sector_concentration": "Description of sector exposure",
        "correlation_risk": "LOW" or "MODERATE" or "HIGH",
        "regime_alignment": "Description of how portfolio aligns with current market regime",
        "overall_health": 7
    }},
    "confidence_level": "HIGH" or "MEDIUM" or "LOW",
    "summary": "3-5 paragraph comprehensive daily research report covering market conditions, portfolio health, and rationale for all decisions. This should read like a professional research note.",
    "actions": [
        {{
            "action": "BUY" or "SELL",
            "symbol": "TICKER",
            "name": "Company Name",
            "reason": "Detailed reasoning (80+ words) citing specific catalysts, technical levels, valuation metrics, and composite score."
        }}
    ]
}}

**CRITICAL RULES**:
- Execute ALL three phases before making decisions -- do NOT skip Phase 1 or Phase 2
- The "holdings_review" array MUST contain an entry for EVERY current holding
- If no changes are needed, return an empty "actions" array: "actions": []
- The "summary" and "market_regime" fields are ALWAYS required
- Return ONLY valid JSON, no additional text
- NEVER exceed {MAX_HOLDINGS} total holdings after your actions
- Base ALL scores and assessments on REAL DATA from tool calls -- never fabricate numbers
"""

    # ------------------------------------------------------------------
    # Backfill snapshots for missing dates
    # ------------------------------------------------------------------

    def backfill_snapshots(self, start_date_str: str = None) -> int:
        """
        Backfill daily snapshots for dates where we have holdings but no snapshot.
        Correctly reconstructs the portfolio state for each historical date
        using the transaction log and historical prices.

        Will NOT insert snapshots before the earliest existing transaction.
        Returns the number of snapshots created / updated.
        """
        # Determine the earliest meaningful date from existing data
        earliest_txn = TrackingTransaction.query.order_by(TrackingTransaction.date.asc()).first()
        if not earliest_txn:
            print("No transactions found. Nothing to backfill.")
            return 0
        earliest_data_date = earliest_txn.date

        if start_date_str:
            start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            start = earliest_data_date

        # Never backfill before the earliest transaction
        if start < earliest_data_date:
            print(f"Clamping backfill start from {start} to {earliest_data_date} (earliest transaction)")
            start = earliest_data_date

        end = _us_eastern_today()

        # Collect ALL symbols that appear in any transaction so we can bulk-fetch prices
        all_txns = TrackingTransaction.query.all()
        all_symbols = list({tx.symbol for tx in all_txns})
        # Also include currently held stocks (in case they have no sell txn yet)
        for s in TrackingStock.query.all():
            if s.symbol not in all_symbols:
                all_symbols.append(s.symbol)

        print(f"[Backfill] Fetching historical prices for {len(all_symbols)} symbols "
              f"from {start} to {end} ...")
        price_cache = self._bulk_fetch_historical_prices(all_symbols, start, end)

        current = start
        count = 0
        while current <= end:
            # Skip weekends
            if current.weekday() < 5:
                try:
                    self.take_daily_snapshot(current, price_cache=price_cache)
                    count += 1
                except Exception as e:
                    print(f"Error backfilling snapshot for {current}: {e}")
            current += timedelta(days=1)

        print(f"[Backfill] Done. Processed {count} trading days.")
        return count


# Global instance
tracking_service = TrackingService()
