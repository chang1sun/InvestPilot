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

        last_portfolio_value = None  # For forward-filling gaps between snapshots

        for d in all_dates:
            dates.append(d)
            sp500_series.append(sp500_data.get(d))
            nasdaq_series.append(nasdaq_data.get(d))

            snap = snapshot_map.get(d)
            if snap:
                # Portfolio return aligned: actual return + spy_offset at inception
                val = round(snap.total_return_pct + spy_offset, 2)
                portfolio_series.append(val)
                last_portfolio_value = val
                if portfolio_start_index is None:
                    portfolio_start_index = len(dates) - 1
            elif last_portfolio_value is not None:
                # Forward-fill: carry the last known portfolio value for dates without a snapshot
                # This prevents null gaps that break the chart line
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
        """
        Take (or update) a daily portfolio value snapshot.
        If a snapshot already exists for the given date, it will be updated
        with the latest prices to ensure accuracy (e.g. post-market refresh).
        """
        if snapshot_date is None:
            snapshot_date = date.today()

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

        # Update existing snapshot or create a new one
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
    # AI Decision
    # ------------------------------------------------------------------

    def run_daily_decision(self, model_name: str = "gemini-3-flash-preview") -> Dict:
        """
        Run the AI daily deep-research decision to potentially update the tracking portfolio.
        Produces a structured daily research report with three-phase analysis.
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
- Per-Stock Allocation: ${PER_STOCK_ALLOCATION:,.0f} (fixed per position)

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
PHASE 1 — MARKET REGIME & MACRO ASSESSMENT (DO THIS FIRST)
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
PHASE 2 — HOLDINGS DEEP REVIEW (Score Card for EACH holding)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For EACH stock in current holdings, perform these steps:
1. `search_market_news` for the specific stock's recent news and catalysts
2. `batch_get_kline_data` (period="3mo") for all holdings — check price trends
3. `batch_calculate_technical_indicators` (period="3mo") for all holdings — MA, RSI, momentum
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
PHASE 3 — OPPORTUNITY SCAN & FINAL DECISION
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
- Do NOT churn — only trade when conviction is HIGH
- Each position is allocated exactly ${PER_STOCK_ALLOCATION:,.0f}
- Quality over quantity: you are NOT required to fill all {MAX_HOLDINGS} slots

**SYMBOL FORMAT**: US stocks only — use standard tickers like AAPL, TSLA, NVDA, etc.

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
- Execute ALL three phases before making decisions — do NOT skip Phase 1 or Phase 2
- The "holdings_review" array MUST contain an entry for EVERY current holding
- If no changes are needed, return an empty "actions" array: "actions": []
- The "summary" and "market_regime" fields are ALWAYS required
- Return ONLY valid JSON, no additional text
- NEVER exceed {MAX_HOLDINGS} total holdings after your actions
- Base ALL scores and assessments on REAL DATA from tool calls — never fabricate numbers
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
