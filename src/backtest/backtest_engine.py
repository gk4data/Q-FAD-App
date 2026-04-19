import pandas as pd
import numpy as np
import math


def calculate_manual_pnl(df, initial_cash=100000.0, commission=0.0, fractional_shares=True, stop_loss_pct=0.15):
    """
    Manual trade matching logic (same as fixed version before).
    """
    trades = []
    position = None
    current_cash = float(initial_cash)
    df_reset = df.reset_index(drop=False)

    def _get_datetime(row):
        for col in ('Date', 'date', 'Datetime', 'datetime', 'index'):
            if col in row.index:
                return row[col]
        return row.name

    for idx, row in df_reset.iterrows():
        date_time = _get_datetime(row)
        close = row.get('Close', row.get('close', None))
        if close is None or close == 0:
            continue

        buy_signal = (
            bool(row.get('Buy_Signal', False)) or
            bool(row.get('Mid_Buy_Signal', False)) or
            bool(row.get('Mid_Buy_Signal_2', False)) or
            bool(row.get('OverSold_Buy_Signal', False)) or
            bool(row.get('RSI_Range_Buy_Signal', False)) or
            bool(row.get('Super_Low_Buy_Signal', False)) or 
            bool(row.get('Super_Low_Buy_Signal_2', False)) or 
            bool(row.get('New_Uptrend_Buy_Signal', False)) or
            bool(row.get('Downtrend_Reverse_Buy_Signal', False)) or 
            bool(row.get('RSI_pct_buy', False)) or
            bool(row.get('condition_ema_bbu_crossover', False))
        )
        sell_signal = bool(row.get('Sell_Signal', False))

        stop_loss_hit = False
        if position is not None:
            stop_loss_price = position['entry_price'] * (1 - stop_loss_pct)
            stop_loss_hit = close <= stop_loss_price

        if buy_signal and position is None:
            available_for_buy = current_cash - commission
            if available_for_buy <= 0:
                continue
            shares = available_for_buy / close if fractional_shares else math.floor(available_for_buy / close)
            if shares <= 0:
                continue
            entry_price = close
            entry_cost = shares * entry_price
            entry_cash_used = entry_cost + commission
            remaining_cash = current_cash - entry_cash_used
            position = {
                'entry_idx': idx,
                'entry_time': date_time,
                'entry_price': entry_price,
                'shares': shares,
                'remaining_cash': remaining_cash,
                'entry_cash_used': entry_cash_used
            }
            current_cash = remaining_cash

        if (sell_signal or stop_loss_hit) and position is not None:
            exit_price = stop_loss_price if stop_loss_hit else close
            entry_price = position['entry_price']
            shares = position['shares']
            entry_cash_used = position['entry_cash_used']
            remaining_cash = position['remaining_cash']
            gross_pnl = (exit_price - entry_price) * shares
            total_commission = commission * 2
            net_pnl = gross_pnl - total_commission
            proceeds = shares * exit_price
            current_cash = remaining_cash + proceeds - commission
            invested = entry_cash_used if entry_cash_used != 0 else (entry_price * shares + commission)
            pnl_pct = (net_pnl / invested) * 100 if invested != 0 else 0.0
            duration = idx - position['entry_idx']
            trades.append({
                'Entry Time': position['entry_time'],
                'Exit Time': date_time,
                'Entry Price': round(entry_price, 6),
                'Exit Price': round(exit_price, 6),
                'Shares': round(shares, 6),
                'Duration (bars)': int(duration),
                'PnL': round(net_pnl, 2),
                'Return %': round(pnl_pct, 4),
                'Win': 1 if net_pnl > 0 else 0,
                'Equity': round(current_cash, 2)
            })
            position = None

    if position is not None and len(df_reset) > 0:
        last_row = df_reset.iloc[-1]
        last_dt = _get_datetime(last_row)
        exit_price = last_row.get('Close', last_row.get('close', position['entry_price']))
        shares = position['shares']
        entry_price = position['entry_price']
        entry_cash_used = position['entry_cash_used']
        remaining_cash = position['remaining_cash']
        gross_pnl = (exit_price - entry_price) * shares
        total_commission = commission * 2
        net_pnl = gross_pnl - total_commission
        proceeds = shares * exit_price
        current_cash = remaining_cash + proceeds - commission
        invested = entry_cash_used if entry_cash_used != 0 else (entry_price * shares + commission)
        pnl_pct = (net_pnl / invested) * 100 if invested != 0 else 0.0
        duration = df_reset.index[-1] - position['entry_idx']
        trades.append({
            'Entry Time': position['entry_time'],
            'Exit Time': last_dt,
            'Entry Price': round(entry_price, 6),
            'Exit Price': round(exit_price, 6),
            'Shares': round(shares, 6),
            'Duration (bars)': int(duration),
            'PnL': round(net_pnl, 2),
            'Return %': round(pnl_pct, 4),
            'Win': 1 if net_pnl > 0 else 0,
            'Equity': round(current_cash, 2)
        })

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    return trades_df


def get_summary_stats_manual(df, trades_df, initial_cash=100000.0, risk_free_rate=0.0):
    """
    Enhanced summary statistics with advanced trading ratios.
    """
    buy_hold = ((df['Close'].iloc[-1] / df['Close'].iloc[0]) - 1) * 100 if len(df) > 1 else 0

    if trades_df.empty:
        return {
            "Message": "No trades executed.",
            'Equity Final [$]': round(float(initial_cash), 2),
            'Return [%]': 0.0,
            'Buy & Hold Return [%]': round(buy_hold, 2),
            'Equity Peak [%]': 0.0,
            'CAGR [%]': np.nan,
            'Win Rate [%]': 0.0,
            '# Trades': 0,
            'Profit Factor': 0.0,
            'Expectancy per Trade [%]': 0.0,
            'Avg Win [%]': 0.0,
            'Avg Loss [%]': 0.0,
            'Payoff Ratio': 0.0,
            'Sharpe Ratio': 0.0,
            'Sortino Ratio': 0.0,
            'Calmar Ratio': 0.0,
            'Recovery Factor': 0.0,
            'Gain-to-Pain Ratio': 0.0,
            'Avg Holding (bars)': 0.0,
            'Max Drawdown [%]': 0.0,
            'Best Trade [%]': 0.0,
            'Worst Trade [%]': 0.0,
            'Total Profit [$]': 0.0,
            'Winning Trades': 0,
            'Losing Trades': 0,
        }

    equity_curve = trades_df['Equity'].astype(float)
    final_equity = equity_curve.iloc[-1]
    peak_equity = equity_curve.max()
    peak_equity_pct = (peak_equity / initial_cash - 1) * 100
    total_return = (final_equity / initial_cash - 1) * 100
    total_trades = len(trades_df)
    wins = trades_df['Win'].sum()
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    avg_return = trades_df['Return %'].mean()
    best_trade = trades_df['Return %'].max()
    worst_trade = trades_df['Return %'].min()
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max * 100
    max_drawdown = abs(drawdown.min())

    # Advanced metrics
    winning_returns = trades_df.loc[trades_df['Win'] == 1, 'Return %']
    losing_returns = trades_df.loc[trades_df['Win'] == 0, 'Return %']
    avg_win = winning_returns.mean() if len(winning_returns) > 0 else 0
    avg_loss = losing_returns.mean() if len(losing_returns) > 0 else 0
    profit_factor = (winning_returns.sum() / abs(losing_returns.sum())) if len(losing_returns) > 0 else np.inf

    # Expectancy per trade
    p_win = win_rate / 100
    p_loss = 1 - p_win
    expectancy = p_win * avg_win + p_loss * avg_loss

    # Sharpe & Sortino
    returns = trades_df['Return %']
    excess_returns = returns - risk_free_rate
    sharpe = (excess_returns.mean() / excess_returns.std()) if excess_returns.std() != 0 else 0
    downside = excess_returns[excess_returns < 0]
    sortino = (excess_returns.mean() / downside.std()) if downside.std() != 0 else 0

    # Calmar, Recovery, Gain-to-Pain
    calmar = (total_return / max_drawdown) if max_drawdown != 0 else np.inf
    recovery_factor = ((final_equity - initial_cash) / (abs(max_drawdown)/100 * initial_cash)) if max_drawdown != 0 else np.inf
    gain_to_pain = (returns[returns > 0].sum() / abs(returns[returns < 0].sum())) if any(returns < 0) else np.inf

    avg_holding = trades_df['Duration (bars)'].mean() if 'Duration (bars)' in trades_df else np.nan

    # CAGR estimate (if you have time data)
    if 'Entry Time' in trades_df and 'Exit Time' in trades_df:
        try:
            total_days = (pd.to_datetime(trades_df['Exit Time']).max() -
                          pd.to_datetime(trades_df['Entry Time']).min()).days
            years = max(total_days / 365, 1e-6)
            cagr = ((final_equity / initial_cash) ** (1 / years) - 1) * 100
        except Exception:
            cagr = np.nan
    else:
        cagr = np.nan

    return {
        'Equity Final [$]': round(final_equity, 2),
        'Return [%]': round(total_return, 2),
        'Buy & Hold Return [%]': round(buy_hold, 2),
        'Equity Peak [%]': round(peak_equity_pct, 2),
        'CAGR [%]': round(cagr, 2),
        'Win Rate [%]': round(win_rate, 2),
        '# Trades': int(total_trades),
        'Profit Factor': round(profit_factor, 3),
        'Expectancy per Trade [%]': round(expectancy, 3),
        'Avg Win [%]': round(avg_win, 3),
        'Avg Loss [%]': round(avg_loss, 3),
        'Payoff Ratio': round(abs(avg_win / avg_loss), 3) if avg_loss != 0 else np.inf,
        'Sharpe Ratio': round(sharpe, 3),
        'Sortino Ratio': round(sortino, 3),
        'Calmar Ratio': round(calmar, 3),
        'Recovery Factor': round(recovery_factor, 3),
        'Gain-to-Pain Ratio': round(gain_to_pain, 3),
        'Avg Holding (bars)': round(avg_holding, 2),
        'Max Drawdown [%]': round(max_drawdown, 2),
        'Best Trade [%]': round(best_trade, 2),
        'Worst Trade [%]': round(worst_trade, 2),
        'Total Profit [$]': round(final_equity - initial_cash, 2),
        'Winning Trades': int(wins),
        'Losing Trades': int(total_trades - wins),
    }
