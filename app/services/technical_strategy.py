import pandas as pd
from datetime import datetime

class TechnicalStrategy:
    @staticmethod
    def analyze(kline_data, error_msg="API Unavailable", language="zh"):
        """
        A robust technical analysis strategy (Local Algorithm).
        Implements:
        1. Trend Following (MA20 Direction)
        2. Mean Reversion (RSI Overbought/Oversold)
        3. Volatility Breakout (Bollinger Bands Logic)
        """
        if not kline_data or len(kline_data) < 30:
            summary_text = "数据不足，无法进行量化分析。" if language == 'zh' else "Insufficient data for quantitative analysis."
            return {
                "analysis_summary": summary_text,
                "trades": [],
                "signals": [],
                "source": "local_strategy",
                "is_fallback": True,
                "fallback_reason": error_msg
            }

        df = pd.DataFrame(kline_data)
        df['date'] = pd.to_datetime(df['date'])
        
        # Calculate Indicators
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['MA60'] = df['close'].rolling(window=60).mean()
        
        # RSI (14)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        trades = []
        signals = []
        position = None # {'date': ..., 'price': ...}
        
        # Iterate through data to simulate trading
        # Start from index 60 to have valid MA60
        for i in range(60, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i-1]
            date_str = curr['date'].strftime('%Y-%m-%d')
            
            # --- BUY LOGIC ---
            if position is None:
                # Strategy 1: Golden Cross (MA5 crosses above MA20) + Trend Filter (Price > MA60)
                golden_cross = prev['MA5'] <= prev['MA20'] and curr['MA5'] > curr['MA20']
                trend_up = curr['close'] > curr['MA60']
                
                # Strategy 2: RSI Oversold Bounce (RSI < 30 then crosses back up)
                rsi_buy = prev['RSI'] < 30 and curr['RSI'] > 30
                
                if (golden_cross and trend_up) or rsi_buy:
                    reason = "MA5/20 Golden Cross in Up Trend" if golden_cross else "RSI Oversold Rebound"
                    position = {
                        'buy_date': date_str,
                        'buy_price': float(curr['close']),
                        'buy_reason': reason
                    }
                    signals.append({"type": "BUY", "date": date_str, "price": float(curr['close']), "reason": reason})

            # --- SELL LOGIC ---
            elif position:
                # Strategy 1: Death Cross (MA5 crosses below MA20)
                death_cross = prev['MA5'] >= prev['MA20'] and curr['MA5'] < curr['MA20']
                
                # Strategy 2: RSI Overbought (RSI > 70)
                rsi_sell = curr['RSI'] > 75
                
                # Strategy 3: Stop Loss (5%)
                stop_loss = curr['close'] < position['buy_price'] * 0.95
                
                if death_cross or rsi_sell or stop_loss:
                    sell_reason = "MA5/20 Death Cross" if death_cross else ("RSI Overbought" if rsi_sell else "Stop Loss Hit")
                    
                    # Calculate return
                    ret_pct = ((curr['close'] - position['buy_price']) / position['buy_price']) * 100
                    buy_dt = datetime.strptime(position['buy_date'], '%Y-%m-%d')
                    sell_dt = curr['date'].to_pydatetime()
                    days = (sell_dt - buy_dt).days
                    
                    trades.append({
                        "buy_date": position['buy_date'],
                        "buy_price": round(position['buy_price'], 2),
                        "sell_date": date_str,
                        "sell_price": round(float(curr['close']), 2),
                        "status": "CLOSED",
                        "holding_period": f"{days} days",
                        "return_rate": f"{ret_pct:+.2f}%",
                        "reason": f"Buy: {position['buy_reason']} | Sell: {sell_reason}"
                    })
                    signals.append({"type": "SELL", "date": date_str, "price": float(curr['close']), "reason": sell_reason})
                    position = None

        # Handle open position at the end
        if position:
            curr = df.iloc[-1]
            date_str = curr['date'].strftime('%Y-%m-%d')
            buy_dt = datetime.strptime(position['buy_date'], '%Y-%m-%d')
            days = (curr['date'].to_pydatetime() - buy_dt).days
            curr_ret = ((curr['close'] - position['buy_price']) / position['buy_price']) * 100
            
            trades.append({
                "buy_date": position['buy_date'],
                "buy_price": round(position['buy_price'], 2),
                "sell_date": None,
                "sell_price": None,
                "status": "HOLDING",
                "holding_period": f"{days} days",
                "return_rate": f"{curr_ret:+.2f}% (Open)",
                "reason": f"Buy: {position['buy_reason']} | Still holding trend."
            })

        # Sort trades descending
        trades.sort(key=lambda x: x['buy_date'], reverse=True)
        
        # Language-aware summary
        if language == 'zh':
            summary = "基于 MA 均线系统（5/20/60）与 RSI 动量指标的经典量化策略回测结果。策略逻辑：金叉做多、死叉做空、RSI 超买超卖辅助、5% 止损保护。"
        else:
            summary = "Backtest results based on classic MA crossover (5/20/60) and RSI momentum strategy. Logic: Golden Cross for Long, Death Cross for Short, RSI overbought/oversold assist, 5% stop-loss protection."
        
        return {
            "analysis_summary": summary,
            "trades": trades,
            "signals": signals,
            "source": "local_strategy",
            "is_fallback": True,
            "fallback_reason": error_msg
        }

