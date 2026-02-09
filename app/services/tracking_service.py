"""
Stock Tracking Service
Manages the curated stock tracking portfolio with AI-driven daily decisions.
"""

import json
import os
import time
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List

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
INCEPTION_DATE = "2026-01-01"


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
        num_current = len(stocks)
        sell_txns = TrackingTransaction.query.filter_by(action='SELL').all()
        total_sell_returns = sum(
            (PER_STOCK_ALLOCATION / tx.buy_price) * tx.price
            for tx in sell_txns if tx.buy_price and tx.buy_price > 0
        )
        cash = INITIAL_CAPITAL - (num_current * PER_STOCK_ALLOCATION) + total_sell_returns

        # Compute each holding's current market value
        holdings_data = []
        total_holdings_value = 0.0
        for s in stocks:
            price = s.current_price or s.buy_price
            shares = PER_STOCK_ALLOCATION / s.buy_price
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
            total_holdings_value += price * (PER_STOCK_ALLOCATION / h.buy_price)
            total_cost += PER_STOCK_ALLOCATION

        # Calculate cash: start with INITIAL_CAPITAL, subtract allocations, add back sells
        num_current = len(holdings)
        # Get cumulative realized P&L from the latest snapshot or compute from transactions
        sell_txns = TrackingTransaction.query.filter_by(action='SELL').all()
        total_realized_pnl = 0.0
        total_sell_returns = 0.0
        for tx in sell_txns:
            if tx.buy_price and tx.buy_price > 0:
                shares = PER_STOCK_ALLOCATION / tx.buy_price
                sell_value = shares * tx.price
                total_sell_returns += sell_value
                total_realized_pnl += sell_value - PER_STOCK_ALLOCATION

        cash = INITIAL_CAPITAL - (num_current * PER_STOCK_ALLOCATION) + total_sell_returns
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
        Benchmark data starts from inception date; portfolio data is null
        before the first snapshot, and starts aligned with SPY at that point.
        """
        if not start_date:
            start_date = INCEPTION_DATE

        snapshots = TrackingDailySnapshot.query.filter(
            TrackingDailySnapshot.date >= start_date
        ).order_by(TrackingDailySnapshot.date.asc()).all()

        # Determine date range: always start from inception, end at today or last snapshot
        today_str = date.today().strftime('%Y-%m-%d')
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

        # Use the union of all benchmark dates as the x-axis
        all_dates = sorted(set(list(sp500_data.keys()) + list(nasdaq_data.keys())))

        # Find where portfolio data begins
        first_snapshot_date = snapshots[0].date.strftime('%Y-%m-%d') if snapshots else None
        portfolio_start_index = None

        # Get the SPY return on the first snapshot date so we can align the portfolio curve
        spy_offset = 0.0
        if first_snapshot_date and first_snapshot_date in sp500_data:
            spy_offset = sp500_data[first_snapshot_date]

        dates = []
        portfolio_series = []
        sp500_series = []
        nasdaq_series = []

        for d in all_dates:
            dates.append(d)
            sp500_series.append(sp500_data.get(d))
            nasdaq_series.append(nasdaq_data.get(d))

            snap = snapshot_map.get(d)
            if snap:
                # Portfolio return aligned: actual return + spy_offset at inception
                portfolio_series.append(round(snap.total_return_pct + spy_offset, 2))
                if portfolio_start_index is None:
                    portfolio_start_index = len(dates) - 1
            else:
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
        """Update current prices for all tracked stocks."""
        stocks = TrackingStock.query.all()
        updated = 0
        for stock in stocks:
            try:
                price = DataProvider.get_current_price(stock.symbol)
                if price is not None:
                    stock.current_price = price
                    updated += 1
            except Exception as e:
                print(f"Error refreshing price for {stock.symbol}: {e}")
        db.session.commit()
        return {'updated': updated, 'total': len(stocks)}

    # ------------------------------------------------------------------
    # Daily snapshot
    # ------------------------------------------------------------------

    def take_daily_snapshot(self, snapshot_date: date = None) -> Optional[Dict]:
        """Take a daily portfolio value snapshot."""
        if snapshot_date is None:
            snapshot_date = date.today()

        # Avoid duplicate snapshots
        existing = TrackingDailySnapshot.query.filter_by(date=snapshot_date).first()
        if existing:
            return existing.to_dict()

        # Refresh prices first
        self.refresh_prices()

        holdings = TrackingStock.query.all()

        total_holdings_value = 0.0
        holdings_snapshot = []
        for h in holdings:
            price = h.current_price or h.buy_price
            shares = PER_STOCK_ALLOCATION / h.buy_price
            value = shares * price
            total_holdings_value += value
            holdings_snapshot.append({
                'symbol': h.symbol,
                'name': h.name,
                'buy_price': h.buy_price,
                'current_price': price,
                'shares': round(shares, 4),
                'value': round(value, 2),
                'return_pct': round(((price - h.buy_price) / h.buy_price) * 100, 2)
            })

        # Calculate cash
        sell_txns = TrackingTransaction.query.filter_by(action='SELL').all()
        total_sell_returns = 0.0
        total_realized_pnl = 0.0
        for tx in sell_txns:
            if tx.buy_price and tx.buy_price > 0:
                shares = PER_STOCK_ALLOCATION / tx.buy_price
                sell_value = shares * tx.price
                total_sell_returns += sell_value
                total_realized_pnl += sell_value - PER_STOCK_ALLOCATION

        num_current = len(holdings)
        cash = INITIAL_CAPITAL - (num_current * PER_STOCK_ALLOCATION) + total_sell_returns
        portfolio_value = cash + total_holdings_value
        total_return_pct = ((portfolio_value - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100

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
    # AI Decision
    # ------------------------------------------------------------------

    def run_daily_decision(self, model_name: str = "gemini-3-flash-preview") -> Dict:
        """
        Run the AI daily decision to potentially update the tracking portfolio.
        Returns the decision log entry.
        """
        today = date.today()

        # Get current portfolio state
        holdings = TrackingStock.query.all()
        holdings_info = []
        for h in holdings:
            price = h.current_price or h.buy_price
            shares = PER_STOCK_ALLOCATION / h.buy_price
            ret_pct = ((price - h.buy_price) / h.buy_price) * 100
            holdings_info.append({
                'symbol': h.symbol,
                'name': h.name or h.symbol,
                'buy_price': h.buy_price,
                'buy_date': h.buy_date.strftime('%Y-%m-%d'),
                'current_price': price,
                'return_pct': round(ret_pct, 2),
                'shares': round(shares, 4),
                'value': round(shares * price, 2)
            })

        # Get recent transaction history
        recent_txns = TrackingTransaction.query.order_by(
            TrackingTransaction.date.desc()
        ).limit(20).all()
        txn_history = [t.to_dict() for t in recent_txns]

        # Calculate portfolio state
        sell_txns = TrackingTransaction.query.filter_by(action='SELL').all()
        total_sell_returns = 0.0
        total_realized_pnl = 0.0
        for tx in sell_txns:
            if tx.buy_price and tx.buy_price > 0:
                shares = PER_STOCK_ALLOCATION / tx.buy_price
                sell_value = shares * tx.price
                total_sell_returns += sell_value
                total_realized_pnl += sell_value - PER_STOCK_ALLOCATION

        num_current = len(holdings)
        available_slots = MAX_HOLDINGS - num_current
        holdings_value = sum(
            (PER_STOCK_ALLOCATION / h.buy_price) * (h.current_price or h.buy_price)
            for h in holdings
        )
        cash = INITIAL_CAPITAL - (num_current * PER_STOCK_ALLOCATION) + total_sell_returns
        portfolio_value = cash + holdings_value

        # Build the AI prompt
        prompt_result = self._build_decision_prompt(
            holdings_info=holdings_info,
            txn_history=txn_history,
            portfolio_value=portfolio_value,
            cash=cash,
            total_realized_pnl=total_realized_pnl,
            available_slots=available_slots,
            num_current=num_current,
            today=today
        )

        # Run AI agent
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
                max_iterations=25,
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
        actions = result.get('actions', [])
        summary = result.get('summary', '')
        has_changes = len(actions) > 0
        executed_actions = []

        for action in actions:
            act_type = action.get('action', '').upper()
            symbol = action.get('symbol', '').upper()
            reason = action.get('reason', '')
            name = action.get('name', symbol)

            if act_type == 'BUY':
                success = self._execute_buy(symbol, name, reason, today)
                if success:
                    executed_actions.append({
                        'action': 'BUY', 'symbol': symbol, 'name': name,
                        'reason': reason, 'success': True
                    })
            elif act_type == 'SELL':
                success = self._execute_sell(symbol, reason, today)
                if success:
                    executed_actions.append({
                        'action': 'SELL', 'symbol': symbol, 'name': name,
                        'reason': reason, 'success': True
                    })

        # Log the decision
        log = TrackingDecisionLog(
            date=today,
            model_name=model_name,
            has_changes=len(executed_actions) > 0,
            summary=summary,
            actions_json=json.dumps(executed_actions),
            raw_response=text[:10000] if text else None,
            elapsed_seconds=elapsed_seconds
        )
        db.session.add(log)

        # Take snapshot after changes
        db.session.commit()
        self.take_daily_snapshot(today)

        return log.to_dict()

    def _execute_buy(self, symbol: str, name: str, reason: str, trade_date: date) -> bool:
        """Execute a BUY action."""
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
            reason=reason
        )
        db.session.add(stock)

        # Record transaction
        txn = TrackingTransaction(
            symbol=symbol,
            name=name,
            action='BUY',
            price=price,
            date=trade_date,
            reason=reason
        )
        db.session.add(txn)
        db.session.flush()

        print(f"[Tracking] ✅ BUY {symbol} @ ${price:.2f}")
        return True

    def _execute_sell(self, symbol: str, reason: str, trade_date: date) -> bool:
        """Execute a SELL action."""
        stock = TrackingStock.query.filter_by(symbol=symbol).first()
        if not stock:
            print(f"[Tracking] Not holding {symbol}, skipping SELL")
            return False

        # Get current price for sell
        price = DataProvider.get_current_price(symbol)
        if price is None:
            price = stock.current_price or stock.buy_price

        # Calculate realized return
        realized_pct = ((price - stock.buy_price) / stock.buy_price) * 100

        # Record transaction
        txn = TrackingTransaction(
            symbol=symbol,
            name=stock.name,
            action='SELL',
            price=price,
            date=trade_date,
            reason=reason,
            buy_price=stock.buy_price,
            realized_pct=round(realized_pct, 2)
        )
        db.session.add(txn)

        # Remove from tracking list
        db.session.delete(stock)
        db.session.flush()

        print(f"[Tracking] ✅ SELL {symbol} @ ${price:.2f} (return: {realized_pct:+.2f}%)")
        return True

    def _build_decision_prompt(self, holdings_info, txn_history, portfolio_value,
                                cash, total_realized_pnl, available_slots,
                                num_current, today) -> str:
        """Build the AI prompt for daily decision making."""
        current_date = today.strftime('%Y-%m-%d')

        holdings_text = "No current holdings." if not holdings_info else json.dumps(holdings_info, indent=2)
        txn_text = "No recent transactions." if not txn_history else json.dumps(txn_history[:10], indent=2)

        from app.services.ai_analyzer import INVESTMENT_PHILOSOPHY

        tool_descriptions = self.ai_analyzer._get_tool_descriptions_text()

        return f"""You are a professional US stock portfolio manager with access to real-time market data tools AND web search.

{INVESTMENT_PHILOSOPHY}

**DATE**: {current_date}

**TASK**: You manage a curated US stock tracking portfolio. Review the current holdings and market conditions, then decide whether to make any changes (BUY new stocks or SELL existing ones).

**PORTFOLIO STATE**:
- Initial Capital: ${INITIAL_CAPITAL:,.0f}
- Current Portfolio Value: ${portfolio_value:,.2f}
- Cash Available: ${cash:,.2f}
- Realized P&L: ${total_realized_pnl:,.2f}
- Current Holdings: {num_current}/{MAX_HOLDINGS}
- Available Slots for New Buys: {available_slots}
- Per-Stock Allocation: ${PER_STOCK_ALLOCATION:,.0f} (fixed per position)

**CURRENT HOLDINGS**:
{holdings_text}

**RECENT TRANSACTION HISTORY** (last 10):
{txn_text}

**YOUR AVAILABLE TOOLS**:
{tool_descriptions}

**MANDATORY WORKFLOW**:
1. Use `search_market_news` to check latest market news, macro conditions, sector rotations
2. For each current holding, check if there are any negative catalysts or significant changes
3. Use `batch_get_realtime_prices` to update prices for all current holdings
4. Use `batch_get_kline_data` (period="3mo") for current holdings to check technical trends
5. If you see sell candidates, use `batch_calculate_technical_indicators` to confirm
6. If there are open slots and you find strong new opportunities, research them with tools
7. ONLY recommend changes when you have HIGH CONVICTION — it's perfectly fine to make NO changes

**DECISION RULES**:
- SELL a holding if: (a) negative catalyst / deteriorating fundamentals, (b) technical breakdown confirmed, (c) better opportunity available, or (d) target price reached
- BUY a new stock if: (a) strong catalyst not yet priced in, (b) favorable technical setup, (c) attractive valuation, AND (d) there is an available slot
- You are NOT required to fill all {MAX_HOLDINGS} slots. Quality over quantity.
- Do NOT churn the portfolio unnecessarily — trading costs matter
- Each position is allocated exactly ${PER_STOCK_ALLOCATION:,.0f}

**SYMBOL FORMAT**: US stocks only — use standard tickers like AAPL, TSLA, NVDA, etc.

**OUTPUT FORMAT** (JSON):
{{
    "summary": "2-3 paragraph market analysis and portfolio review. Explain your reasoning for any changes or why you chose not to make changes. Reference specific news and data.",
    "actions": [
        {{
            "action": "BUY" or "SELL",
            "symbol": "TICKER",
            "name": "Company Name",
            "reason": "Detailed reasoning (50+ words) citing specific catalysts, technical levels, and valuation."
        }}
    ]
}}

**IMPORTANT**:
- If no changes are needed, return an empty "actions" array: "actions": []
- The "summary" field is ALWAYS required even if no actions are taken
- Return ONLY valid JSON, no additional text
- NEVER exceed {MAX_HOLDINGS} total holdings after your actions
"""

    # ------------------------------------------------------------------
    # Backfill snapshots for missing dates
    # ------------------------------------------------------------------

    def backfill_snapshots(self, start_date_str: str = None) -> int:
        """
        Backfill daily snapshots for dates where we have holdings but no snapshot.
        Useful when the system was not running for some days.
        Returns the number of snapshots created.
        """
        if not start_date_str:
            start_date_str = INCEPTION_DATE

        start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end = date.today()
        current = start
        count = 0

        while current <= end:
            # Skip weekends
            if current.weekday() < 5:
                existing = TrackingDailySnapshot.query.filter_by(date=current).first()
                if not existing:
                    try:
                        self.take_daily_snapshot(current)
                        count += 1
                    except Exception as e:
                        print(f"Error backfilling snapshot for {current}: {e}")
            current += timedelta(days=1)

        return count


# Global instance
tracking_service = TrackingService()
