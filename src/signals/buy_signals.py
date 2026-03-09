import pandas as pd
import numpy as np
from typing import List


def _ensure_columns(df: pd.DataFrame, cols: List[str]):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for buy signals: {missing}")


def idx_at_or_before(df: pd.DataFrame, target_time_str: str) -> int:
    t = pd.to_datetime(target_time_str).time()
    eligible = df[df['Date'].dt.time <= t]
    if len(eligible) == 0:
        return 0
    return int(eligible.index.max())


def generate_buy_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Generate buy-related signal columns on a copy of `df` and return it.

    The implementation integrates time-checkpoint VWAP/back rules and produces
    several buy variants (Mid, Super Low, RSI range, etc.).
    """
    df = df.copy()

    if df.empty:
        return df

    required = [
        'RSI', 'STOCHRSIk', 'STOCHRSId', 'BBM_Angle', 'Volume', 'Date', 'High',
        'EMA9', 'MFI_pct', 'volume_profile', 'Low', 'EMA_Trend', 'Close', 'BBM',
        'BBL', 'BBU', 'RSI_lo', 'is_downtrend', 'BBM_Angle_pct', 'MFI', 'EMA_Angle',
        'VWAP', 'Open', 'Trend', 'BBU_Angle_Degree', 'BBM_Angle_Degree', 'EMA_Angle_Degree',
        'BBL_Angle_Degree', 'regime', 'BB_trend', 'RSI_pct', 'RSI_hi'
    ]
    _ensure_columns(df, required)
    
   # Find first candle of current trading day (9:15) instead of iloc[0]
   # This is important because df may include previous day data for indicator calculation
    first_915_rows = df[df['Date'].dt.time == pd.to_datetime('09:15:00').time()]
    if len(first_915_rows) == 0:
        # Fallback: use first candle of the most recent trading day in the data
        current_day = df['Date'].dt.date.max()
        day_rows = df[df['Date'].dt.date == current_day]
        if len(day_rows) == 0:
            # Final fallback: use very first row
            first_idx = df.index[0]
        else:
            first_idx = day_rows.index[0]
    else:
        first_idx = first_915_rows.index[0]
    first_volume_profile = df.loc[first_idx, 'volume_profile']
    first_close = df.loc[first_idx, 'Close']
    first_open  = df.loc[first_idx, 'Open']
    first_high  = df.loc[first_idx, 'High']
    first_low   = df.loc[first_idx, 'Low']
    first_bbl   = df.loc[first_idx, 'BBL']
    first_bbu   = df.loc[first_idx, 'BBU']
    first_bbm   = df.loc[first_idx, 'BBM']

   # --- find indices for the 3 checks (10:15, 12:00, 14:00) ---
    idx_t1 = idx_at_or_before(df, '10:15:00')   # check1
    idx_t2 = idx_at_or_before(df, '12:00:00')   # check2
    idx_t3 = idx_at_or_before(df, '14:00:00')   # check3

   # --- values at those checkpoints ---
    low_t1   = df['Low'].iloc[idx_t1]
    close_t1 = df['Close'].iloc[idx_t1]
    high_t1 = df['High'].iloc[idx_t1]

    low_t2   = df['Low'].iloc[idx_t2]
    close_t2 = df['Close'].iloc[idx_t2]
    high_t2 = df['High'].iloc[idx_t2]

 
    low_t3   = df['Low'].iloc[idx_t3]
    close_t3 = df['Close'].iloc[idx_t3]
    high_t3 = df['High'].iloc[idx_t3]

   # --- original simple checks you had for "no trade" based on first row ---
    no_trade_at_all_close = (
      ((((first_open - first_close) / first_open) * 100 <= 20)
      & (first_bbl < first_close) & (first_volume_profile == 0))
      | (first_volume_profile == 1)
    )

    no_trade_at_all_highlow = (
      ((((first_high - first_low) / first_high) * 100 <= 30)
      & (first_bbm < first_low) & (first_volume_profile == 0))
      | (first_volume_profile == 1)
    )

   # --- trade-if-vwap-back style overrides at checkpoint granularity ---
   # (kept same logic pattern you used: first_high < mid_low -> override)
    trade_if_vwap_back_t1 = (first_close < close_t1)
    trade_if_vwap_back_t2 = (first_high < high_t2) or (close_t1 < close_t2)
    trade_if_vwap_back_t3 = (first_high < high_t3) or (close_t2 < close_t3)
   # note: I used your 'last' rule for t3 to preserve previous 'last' logic; change if needed.

   # --- VWAP coming down checks (scalar per-check) ---
    vwap_coming_down_t1 = (first_close > low_t1)
    vwap_coming_down_t2 = (low_t1 > low_t2) and (first_high > high_t2)  # or other measure if you prefer
    vwap_coming_down_t3 = (low_t2 > low_t3) and (low_t1 > low_t3)  # or other measure if you prefer

   # --- Combine rules into per-row Series using time windows ---
    # Check if first candle is red but next 3 candles are green with rising closes
    green_continuation = (
        (first_volume_profile == 0) &  # First candle is red
        (df['volume_profile'].shift(-1) == 1) &  # 2nd candle is green (look ahead)
        (df['volume_profile'].shift(-2) == 1) &  # 3rd candle is green
        ((df['volume_profile'].shift(-3) == 1) | (df['volume_profile'].shift(-4) == 1)) &  # 4th candle is green
        (df['Close'].shift(-1) > df['Close']) &  # 2nd close > 1st close
        (df['Close'].shift(-2) > df['Close'].shift(-1)) &  # 3rd close > 2nd close
        ((df['Close'].shift(-3) > df['Close'].shift(-2)) | (df['Close'].shift(-4) > df['Close'].shift(-3)))  # 4th close > 3rd close
    )
    
    no_trade_gap_up_red = ((first_close > first_bbu) & (first_open > first_bbu)
                          & (first_volume_profile == 0)  # 1nd candle is red (look ahead)
                          &  (df['volume_profile'].shift(-1) == 0) # 2rd candle is red
                          &  (df['volume_profile'].shift(-2) == 0))
    # Hard blocker: if gap-up-red pattern is seen, do not trade at all.
    no_trade_gap_up_red_at_all = bool(no_trade_gap_up_red.any())

    allow_basic = (no_trade_at_all_close | no_trade_at_all_highlow | green_continuation)  # scalar

   # time windows for applying each checkpoint rule
    t0_window = (df['Date'].dt.time >= pd.to_datetime('09:15:00').time()) & (df['Date'].dt.time <= pd.to_datetime('10:14:00').time())
    t1_window = (df['Date'].dt.time > pd.to_datetime('10:14:00').time()) & (df['Date'].dt.time <= pd.to_datetime('11:59:00').time())
    t2_window = (df['Date'].dt.time > pd.to_datetime('11:59:00').time()) & (df['Date'].dt.time <= pd.to_datetime('13:59:00').time())
    t3_window = (df['Date'].dt.time > pd.to_datetime('13:59:00').time())

   # no-trade if vwap failing in respective windows (Series)
    no_trade_if_vwap_fail = (
      (vwap_coming_down_t1 & t1_window) |
      (vwap_coming_down_t2 & t2_window) |
      (vwap_coming_down_t3 & t3_window)
    )

   # trade-if-vwap-back series (overrides basic allow but not vwap-failing)
    trade_if_vwap_back_series = (
      (trade_if_vwap_back_t1 & t1_window) |
      (trade_if_vwap_back_t2 & t2_window) |
      (trade_if_vwap_back_t3 & t3_window)
    )

   # base per-row allowed signal (before last-leg prerequisite):
   # `allow_basic` should influence only the first leg (09:15-10:14).
    base_allowed_trade_series = (
      ((allow_basic & t0_window) | trade_if_vwap_back_series)
      & (~(no_trade_if_vwap_fail))
      & (~no_trade_gap_up_red_at_all)
    )

   # apply market-time window (same as you had)
    time_window = (df['Date'].dt.time > pd.to_datetime('09:36:00').time()) & (df['Date'].dt.time < pd.to_datetime('15:28:00').time())

   # Last-leg guard: each prior leg must have seen at least one tradable row.
    t0_had_trade = bool((base_allowed_trade_series & time_window & t0_window).any())
    t1_had_trade = bool((base_allowed_trade_series & time_window & t1_window).any())
    t2_had_trade = bool((base_allowed_trade_series & time_window & t2_window).any())
    allow_t3_from_prior_legs = t0_had_trade or t1_had_trade or t2_had_trade

   # final per-row allowed signal:
    allowed_trade_series = base_allowed_trade_series & ((~t3_window) | allow_t3_from_prior_legs)
    trade_allowed = time_window & allowed_trade_series

# trade_allowed is a boolean Series you can use to filter or trigger trades
    #trade_allowed = True
    
    # Use `trade_allowed` in your signals (replace previous `no_trade_time`)
    # e.g.
    # df['Buy_Signal'] = <your_big_boolean_expr> & trade_allowed


    condition_rsi = (df['RSI']< 75) 
    condition_stochrsi_crossover = df['STOCHRSIk'] > df['STOCHRSId']
    condition_stoch_band_diff = (df['STOCHRSIk'] - df['STOCHRSId']) >= 2
    angle_trend_condition = df['BBM_Angle'].shift(1).rolling(window=4).mean() < df['BBM_Angle']
    volume_trend_condition = df['Volume'].shift(1).rolling(window=6).mean() < df['Volume']
    condition_no_final_position = (df['Date'].dt.time != pd.to_datetime('15:29:00').time())
    breaking_resistance =  df['High'].shift(1).rolling(window=5).max() < df['High']
    breaking_resistance_1 =  df['High'].rolling(window=4).max() < df['High']
    volume_profile_green = (df['volume_profile'] == 1)
    volume_greater_than_prev = df['Volume'] > df['Volume'].shift(1)
    cond_low_lower_ema = (df['EMA9'] >= df['Low'])
    cond_limit_volume = (abs((df['Volume'].shift(1) - df['Volume']))/ df['Volume'].shift(1)) < 2.2
    cond_limit_volume_2 = (abs((df['Volume'].shift(2) - df['Volume']))/ df['Volume'].shift(2)) < 3.5
    cond_limit_volume_3 = (abs((df['Volume'].shift(2) - df['Volume']))/ df['Volume'].shift(2)) < 3.3
    cond_normal_trend = ((df['Trend'] == 'Downtrend') | ((df['Trend'].shift(1) == 'Downtrend') & (df['Trend'] == 'Flat')))
    round_ema_more_than_bbm = (round(df['EMA9'],1) >= round(df['BBM'],1))
    prev_close_less_ema_bbm =  (df['Close'].shift(1) < df['BBM'].shift(1))
    prev_close_less_ema_bbm_1 =  (df['Close'].shift(2) < df['BBM'].shift(2))
    prev_close_less_ema_bbm_2 =  (df['Close'].shift(3) < df['BBM'].shift(3))
    prev_close_less_ema_bbm_3 =  (df['Close'].shift(4) < df['BBM'].shift(4))
    prev_close_less_ema_bbm_4 =  (df['Close'].shift(5) < df['BBM'].shift(5))
    high_higher_than_bbu = (df['High'] > df['BBU'])
    bbu_rise_degree = (df['BBU_Angle_Degree'].shift(1) <= 178) & (df['BBU_Angle_Degree'] < df['BBU_Angle_Degree'].shift(1))
    bbm_rise_degree = (df['BBM_Angle_Degree'].shift(1) <= 180) & (df['BBM_Angle_Degree'] < df['BBM_Angle_Degree'].shift(1))
    ema_rise = (abs((df['EMA9'].shift(1) - df['EMA9']))/ df['EMA9'].shift(1))*100 > 0.55
    avoid_condition_sideway_rise = (((df['regime'] == 'sideways') & (df['EMA_Trend'] == 'Flat')) & ((df['Close'].shift(4) < df['Close'].shift(3)) & (df['Close'].shift(3) < df['Close'].shift(2))
                              & (df['Close'].shift(2) < df['Close'].shift(1)) & (df['Close'] > df['Close'].shift(1))) & (df['Close'] > df['EMA9']) & (df['Close'] > df['BBM']))
        
# Generate buy signal
    df['Buy_Signal'] = (
        (condition_stochrsi_crossover  & angle_trend_condition & condition_stoch_band_diff & cond_limit_volume_2 & 
        condition_rsi   & cond_low_lower_ema & volume_trend_condition & cond_normal_trend & ema_rise & 
        condition_no_final_position  & volume_profile_green
        & cond_limit_volume  & round_ema_more_than_bbm ) 
        |
        (angle_trend_condition & condition_stochrsi_crossover  & cond_limit_volume & cond_limit_volume_2  & breaking_resistance & volume_profile_green 
         & (prev_close_less_ema_bbm_1 | prev_close_less_ema_bbm_3 | prev_close_less_ema_bbm_2 | prev_close_less_ema_bbm_4) & (df['Volume'] > df['Volume'].shift(1))
         & high_higher_than_bbu & (bbu_rise_degree | bbm_rise_degree) & cond_normal_trend & ema_rise)
        |
        (condition_stochrsi_crossover & (df['Volume'] > df['Volume'].shift(1)) #& (df['Low'] < df['EMA9'])
         & (prev_close_less_ema_bbm_1 | prev_close_less_ema_bbm_3 | prev_close_less_ema_bbm_2 | prev_close_less_ema_bbm_4) & cond_limit_volume_3
         & high_higher_than_bbu & bbm_rise_degree & (df['Trend'] == 'Uptrend') & (df['EMA_Angle_Degree'] < 150) & (df['EMA_Angle_Degree'] < df['EMA_Angle_Degree'].shift(1))) 
         ) & (df['BBU_Angle_Degree'].shift(1) < 250) & trade_allowed & ~avoid_condition_sideway_rise
    
        
# Middle buy signal conditions
    condition_curr_ema_near_Low = (df['Close'] > df['EMA9'])
    condition_curr_bbm_near_Low = (df['Close'] > df['BBM'])
    condition_stoch_rsi_crossover = (df['STOCHRSIk'] >= df['STOCHRSId']) & (df['STOCHRSIk'] > 50)
    ema_rising_angle_degree = ((df['EMA_Angle_Degree'].shift(2) <= 172) & (df['EMA_Angle_Degree'].shift(1) <= 160) & (df['EMA_Angle_Degree'] <= 160))
    ema_bbm_gap_increase = (((df['EMA9'].shift(1) - df['BBM'].shift(1)) < (df['EMA9'] - df['BBM']))
                            & ((df['EMA9'].shift(2) - df['BBM'].shift(2)) <(df['EMA9'].shift(1) - df['BBM'].shift(1))))
    condition_mfi_more_rsi = ((df['MFI_pct']*100) > df['RSI'])
    condition_curr_ema_greater_than_bbm =  (df['BBM'] < df['EMA9'])
    volume_greater_than_prev_prev = df['Volume'] > df['Volume'].shift(2)
    BBL_angle_lower_condition = ((df['BBL_Angle_Degree'] >= df['BBL_Angle_Degree'].shift(1)) & (df['BBL_Angle_Degree'] >= df['BBL_Angle_Degree'].shift(2)))
    trend_condition_not_down = ((df['Trend'] != 'Downtrend') &  (df['EMA_Trend'] != 'Flat'))
       
# Final Mid BBM Bounce Buy Signal
    condition_bbm_bounce = (
    (df['Date'].dt.time < pd.to_datetime('15:28:00').time()) &
    (df['regime'] == 'other') & 
    condition_curr_ema_near_Low & condition_curr_bbm_near_Low & condition_stoch_rsi_crossover & ema_rising_angle_degree & ema_bbm_gap_increase & BBL_angle_lower_condition
    & (bbu_rise_degree | bbm_rise_degree)  & volume_profile_green & (volume_greater_than_prev |volume_greater_than_prev_prev) #& trend_condition_not_down
    & condition_mfi_more_rsi & cond_limit_volume & condition_curr_ema_greater_than_bbm )
    df['Mid_Buy_Signal'] = condition_bbm_bounce & (df['Date'].dt.time >= pd.to_datetime('09:18:00').time()) & (df['Date'].dt.time < pd.to_datetime('15:28:00').time()) & allowed_trade_series

## overslod condition
    condition_stoch_over_sold = ((df['STOCHRSIk'].shift(1) < 20) & (df['STOCHRSIk'] > df['STOCHRSId']))
    condition_mfi_over_sold = ((df['MFI_pct'].shift(1) <= 0.625) & (df['MFI_pct'].shift(1) <= df['MFI_pct']))
    condition_rsi_low_up = ((df['RSI'] > df['RSI_lo']) & (df['RSI'].shift(1) < df['RSI_lo'].shift(1)))
    condition_low_less_bbl = (df['Low'].shift(1) <= df['BBL'].shift(1))
    condition_bbm_ema_perc_diff =   ((df['BBM'] < df['EMA9']) | ((df['BBM'] > df['EMA9']) & (((df['BBM'] - df['EMA9']) / df['BBM'] * 100) < 3)))
    condition_xtreme_down_bbu = ((df['BBU_Angle_Degree'].shift(1) <= 245) & (df['BBM_Angle_Degree'].shift(1) <= 235) & (df['BBU_Angle_Degree'] < df['BBU_Angle_Degree'].shift(1)))
    df['OverSold_Buy_Signal'] = (condition_stoch_over_sold & condition_mfi_over_sold & volume_profile_green & condition_xtreme_down_bbu
                                 & condition_bbm_ema_perc_diff & condition_rsi_low_up & condition_low_less_bbl) & trade_allowed

# New RSI Range Buy Signal
    rsi_percent_diff_2= ((df['RSI'].shift(1) - df['RSI_lo'].shift(1)) / df['RSI'].shift(1)) * 100
    rsi_low_current_rangediff = (rsi_percent_diff_2 < 20.50)
    condition_rsi_lower_range =  ((df['RSI'].shift(1) < df['RSI_lo'].shift(1)) & (df['RSI'] > df['RSI_lo']))
    condition_rsi_lower_range_1 = (rsi_low_current_rangediff) & (df['RSI'].shift(1) > df['RSI_lo'].shift(1)) & (df['RSI'] > df['RSI_lo'])
    condition_close_up = (df['Close'].shift(1) < df['Close'])
    condition_curr_ema_greater_than_bbm =  ((df['BBM'].shift(1) - df['EMA9'].shift(1)) > (df['BBM'] - df['EMA9']))
    condition_stoch_rsi_crossover = (df['STOCHRSIk'] >= df['STOCHRSId'])
    cond_not_down_side = ((df['Trend'] == 'Downtrend') & ((df['regime'] == 'sideways') & (df['EMA_Trend'] == 'Flat')))
    extreme_bbm = (df['BBM_Angle_Degree'] <= 230)
    bbmm_angle_pct_100 = ((df['BBM_Angle_pct']* 100) == 100)
    not_extreme_bbu = ((df['BBU_Angle_Degree'].shift(1) < 240) & (df['BBU_Angle_Degree'].shift(1) > df['BBU_Angle_Degree']))

    df['RSI_Range_Buy_Signal'] = ((condition_rsi_lower_range | condition_rsi_lower_range_1) & (df['EMA_Angle_Degree'] <= 185) & (cond_not_down_side != 1) & (not_extreme_bbu)
                                  & condition_stoch_rsi_crossover & condition_close_up & condition_curr_ema_greater_than_bbm & extreme_bbm) & trade_allowed & bbmm_angle_pct_100
    
    RSI_pct_buy_signal  = ((((df['RSI_pct'].shift(1) <= df['MFI_pct'].shift(1)) & (df['RSI_pct'].shift(1)*100 < df['RSI_lo'].shift(1)) 
                          & (df['RSI_pct'].shift(1)*100 < df['RSI'].shift(1)))
                        |((df['RSI_pct'].shift(2) <= df['MFI_pct'].shift(2)) & ((df['RSI_pct'].shift(2)*100 < df['RSI_lo'].shift(2)))
                          & (df['RSI_pct'].shift(2)*100 < df['RSI'].shift(2)))
                        |((df['RSI_pct'].shift(3) <= df['MFI_pct'].shift(3)) & ((df['RSI_pct'].shift(3)*100 < df['RSI_lo'].shift(3)))
                          & (df['RSI_pct'].shift(3)*100 < df['RSI'].shift(3))))
                        & ((df['RSI_pct'] >= df['MFI_pct']) & (df['RSI_pct']*100 > df['RSI_hi']) & (df['RSI_pct']*100 > df['RSI']))
                        & (df['High'] > df['EMA9']) & (df['Low'] < df['EMA9']) & (df['Date'].dt.time > pd.to_datetime('09:45:00').time())
                        & (df['BBM_Angle_Degree'] < 225) & (df['BBU_Angle_Degree'] < 240)  & (df['High'] <= df['BBU'])
                        & cond_normal_trend &  (df['BB_trend'].shift(1) == 'bearish') & (df['EMA_Angle_Degree'] < 150))


    ## new super low buy condition
    round_ema_more_than_bbm = (round(df['EMA9'],1) >= round(df['BBM'],1))
    condtion_high_low_bbu = (df['High'] <= df['BBU'])
    cond_ema_angle_more_bbm = (df['BBM_Angle'] <= df['EMA_Angle'])
 
    trend_cond_super_low = ((((df['Trend'] == 'Uptrend') & (((df['RSI_pct'] >= df['MFI_pct']) & (df['MFI_pct'] >= df['MFI_pct'].shift(1)))| (df['RSI_pct']*100 >  df['RSI_hi']))))
                | (((df['Trend'] == 'Downtrend') | (df['Trend'] == 'Flat')) & ((df['BBU_Angle_Degree'].shift(1) < 240))
                   & ((df['Close'] < df['High'].shift(2)) & (df['Close'] > df['Close'].shift(1)) &
                       (((df['High'].shift(1) > df['High']) & (((df['High'].shift(1) - df['High']) / df['High'].shift(1) * 100) < 0.20)) 
                        | ((df['High'] > df['High'].shift(1)) & ((((df['High'] - df['High'].shift(1)) / df['High']) * 100) > 0.25))))))
                    

    condition_super_low_buy = ((prev_close_less_ema_bbm   &  round_ema_more_than_bbm  & volume_profile_green & not_extreme_bbu &  condtion_high_low_bbu)) & trend_cond_super_low
    
    trend_cond_super_low_2 = (((df['Trend'] == 'Uptrend') & (df['Low'] <= df['EMA9']))
                            | (((df['Trend'] == 'Downtrend')) 
                            & (((df['High'] > df['High'].shift(2)) | ((df['High'].shift(2) > df['High']) & (((df['High'].shift(2) - df['High']) / df['High'].shift(2) * 100) < 0.25)))
                            & ((df['High'] > df['High'].shift(1)) | ((df['High'].shift(1) > df['High']) & (((df['High'].shift(1) - df['High']) / df['High'].shift(1) * 100) < 0.25)))
                            & (df['Low'] < df['EMA9']) & (df['RSI_pct']*100 >= 50) & (df['High'] < df['BBU']) 
                            & ((df['High'] > df['EMA9']) | ((df['High'] < df['EMA9']) & ((((df['EMA9'] - df['High']) / df['EMA9']) * 100) < 3.4))))))
                   
    condtion_high_gret_close = (((df['High'] - df['BBU'])/(df['High']))*100) <= 3.5
    condtion_candle_height_ratio = (((df['Close'] - df['Open']) / df['Close'])*100) >= 1

    condition_super_low_buy_2 = ((prev_close_less_ema_bbm | prev_close_less_ema_bbm_1 
                                |prev_close_less_ema_bbm_2 | prev_close_less_ema_bbm_3 | prev_close_less_ema_bbm_4) & (df['Close'] <= df['BBU'])
                                & cond_ema_angle_more_bbm & (df['volume_profile'] == 1) & (df['EMA9'] >= df['BBM']) & (df['BBU_Angle_Degree'].shift(1) < 182)
                                & ((df['Low'] < df['BBM']) | (df['Low'] < df['EMA9']))
                                & ~ avoid_condition_sideway_rise) & trend_cond_super_low_2 
    
    candle_ratio_openclose = ((df['Close'] + df['Open']) / 2)

    trend_mid_buy2 = ((((df['Trend'] == 'Downtrend') & (df['regime'] == 'sideways')) & ((df['BBM'] > candle_ratio_openclose)))
                      | (((df['Trend'] == 'Downtrend') & (df['regime'] == 'other')) & ((df['BBM_Angle_Degree'] < 195) & (df['High'] <= df['BBU'])))
                      | (((df['Trend'] == 'Uptrend') & (df['regime'] == 'sideways')) & (df['Low'] <= df['BBM'])))
                     #((df['BBM'] < candle_ratio_lowhigh) & (df['High'] <= df['BBU']))))

    condition_mid_buy_2 = (((prev_close_less_ema_bbm | prev_close_less_ema_bbm_1 
                                             |prev_close_less_ema_bbm_2 | prev_close_less_ema_bbm_3 | prev_close_less_ema_bbm_4) 
                           & condtion_high_gret_close & condtion_candle_height_ratio
                           & ((((df['Close'] - df['BBU'])/(df['Close']))*100) <= 6) & (df['EMA_Angle_Degree'] <= 180)
                           & (df['volume_profile'].shift(1) == 1) & (df['volume_profile'] == 1) & (df['STOCHRSIk'] > 27)
                           & trend_mid_buy2
                           & ~((df['EMA_Trend'] == 'Downtrend') & (df['Trend'] == 'Downtrend'))
                           &  ~((df['EMA_Trend'] == 'Flat') & (df['Trend'] == 'Uptrend') & (df['regime'] == 'sideways') & (df['BB_trend'] == 'neutral')))
                           |
                           ((((df['BBU'].shift(3) > df['BBU'].shift(2)) & (df['BBL'].shift(3) < df['BBL'].shift(2)))
                            | ((df['BBU'].shift(4) > df['BBU'].shift(3)) & (df['BBL'].shift(4) < df['BBL'].shift(3))))
                            & ((df['BBU'].shift(1) > df['BBU'].shift(2)) & (df['BBL'].shift(1) < df['BBL'].shift(2)))
                            & (df['EMA_Trend'] == 'Uptrend') & (df['Trend'] == 'Uptrend') & ((df['regime'] == 'sideways') | (df['regime'] == 'other'))
                            & (df['High'] > df['BBU']) & (df['EMA9'] > df['BBM']) & ((df['volume_profile'] == 1)
                            | ((df['volume_profile'] == 0) & (df['Close'] > df['Open'].shift(1)) & (df['Close'] > df['EMA9']) & (df['Open'] > df['BBU'])))))
                            
    condtion_alt_prev_close = ((df['Close'] > df['Close'].shift(1)) & (df['Close'] > df['Close'].shift(2)) & (df['BBU_Angle_Degree'].shift(1) > 200)
                                     & (df['Close'] > df['EMA9']) & (df['Close'].shift(1) > df['EMA9'].shift(1)) & (df['EMA_Angle_Degree'] < 140))
    
    condition_new_uptrend_buy = (
                                ((((df['High'].shift(2) > df['BBU'].shift(2)) & ((df['volume_profile'].shift(2) == 1) | ((df['volume_profile'].shift(2) == 0) & (df['Close'].shift(2) > df['EMA9'].shift(2)))))
                                   | ((df['High'].shift(3) > df['BBU'].shift(3)) & ((df['volume_profile'].shift(3) == 1)| ((df['volume_profile'].shift(3) == 0) & (df['Close'].shift(3) > df['EMA9'].shift(3)))))
                                   | ((df['High'].shift(4) > df['BBU'].shift(4)) & ((df['volume_profile'].shift(4) == 1)| ((df['volume_profile'].shift(4) == 0) & (df['Close'].shift(4) > df['EMA9'].shift(4)))))
                                   | ((df['High'].shift(5) > df['BBU'].shift(5)) & ((df['volume_profile'].shift(5) == 1)| ((df['volume_profile'].shift(5) == 0) & (df['Close'].shift(5) > df['EMA9'].shift(5)))))
                                   | ((df['High'].shift(6) > df['BBU'].shift(6)) & ((df['volume_profile'].shift(6) == 1)| ((df['volume_profile'].shift(6) == 0) & (df['Close'].shift(6) > df['EMA9'].shift(6))))))
                                  #| ((df['High'].shift(7) > df['BBU'].shift(7)) & ((df['volume_profile'].shift(7) == 1)| ((df['volume_profile'].shift(7) == 0) & (df['Close'].shift(7) > df['EMA9'].shift(7))))))
                                  #| ((df['High'].shift(8) > df['BBU'].shift(8)) & ((df['volume_profile'].shift(8) == 1)| ((df['volume_profile'].shift(8) == 0) & (df['Close'].shift(8) > df['EMA9'].shift(8))))))
                                & (((df['Trend'] == 'Uptrend') & (df['EMA_Trend'] == 'Flat')) | ((df['Trend'] == 'Flat') & (df['EMA_Trend'] == 'Uptrend'))
                                   | ((df['Trend'] == 'Uptrend') & (df['EMA_Trend'] == 'Uptrend')))
                                & ((df['regime'] == 'other') | ((df['regime'] == 'sideways') & (df['Date'].dt.time < pd.to_datetime('09:35:00').time()))
                                   | ((df['regime'] == 'sideways') & condtion_alt_prev_close))
                                & (df['volume_profile'] == 1) & ((df['volume_profile'].shift(1) == 0) | (df['Close'].shift(1) < df['EMA9'].shift(1))| condtion_alt_prev_close)
                                & (df['Close'] > df['Close'].shift(1)) & (df['RSI_pct'].shift(1) <= (df['RSI_pct'])) & (df['BBU_Angle_Degree'] < 210)
                                & (df['High'] < df['BBU']) & (df['EMA_Angle_Degree'] < 178)
                                & (((df['Close'] - df['Open'])/df['Close'])*100 >= 1.50)
                                & (df['BBU_Angle_Degree'].shift(1).rolling(window=5).mean() < 150))
                                |
                                ((df['Trend'] == 'Uptrend') &  (df['EMA_Trend'] == 'Uptrend')
                                & ((df['EMA9'] < df['Close'].shift(2)) & (df['BBM'] < df['Close'].shift(2))) #& ((df['EMA9'] > df['Close'].shift(1)) & (df['BBM'] > df['Close'].shift(1)))
                                & (df['volume_profile'] == 1) & (df['volume_profile'].shift(1) == 0) #& (df['RSI_pct'].shift(1) * 100 <= 38) & (df['MFI_pct'].shift(1) * 100 <= 38)
                                & (((df['regime'] == 'sideways') & (df['BBU_Angle_Degree'] < 150) & (df['BBM_Angle_Degree'] < 150)) |
                                  ((df['regime'] == 'other') & (df['EMA_Angle_Degree'] <= 140)))
                                & (((df['Close'] - df['Open'])/df['Close'])*100 >= 0.22)  
                                & (df['RSI_pct'] * 100 <= 100) & (df['EMA_Angle_Degree'] < 178) & (df['High'] < df['BBU']) &  (df['BBU_Angle_Degree'] < 210)
                                )
                                | (((df['Low'].shift(2) < df['BBL'].shift(2)) & (df['volume_profile'].shift(2) == 0) & (df['High'].shift(1) > df['BBU'].shift(1)) 
                                  & (df['High'] > df['BBU']) & (df['Close'] > df['Close'].shift(2)) & (df['Close'] > df['Close'].shift(1)) & (df['volume_profile'] == 1))
                                  | ((df['Low'].shift(3) < df['BBL'].shift(3)) & (df['volume_profile'].shift(3) == 0) & (df['High'].shift(2) > df['BBU'].shift(2)) 
                                  & (df['High'].shift(1) > df['BBU'].shift(1)) & (df['High'] > df['BBU']) & (df['Close'] > df['Close'].shift(2)) 
                                  & (df['Close'] > df['Close'].shift(1)) & (df['volume_profile'] == 1))
                                )
                                | (((df['EMA9'].shift(5) > df['BBM'].shift(5)) | (df['EMA9'].shift(6) > df['BBM'].shift(6)))
                                   & ((df['EMA9'].shift(3) < df['BBM'].shift(3)) | (df['EMA9'].shift(4) < df['BBM'].shift(4)) | (df['EMA9'].shift(2) < df['BBM'].shift(2)))
                                   & ((df['EMA9'].shift(1) > df['BBM'].shift(1)) | (df['EMA9'] > df['BBM']))
                                  #  & (df['EMA_Trend'].shift(1) == 'Uptrend') & (df['Trend'].shift(1) == 'Uptrend') & ((df['regime'] == 'other'))
                                   & (df['BBU_Angle_Degree'] < 160) & (df['BBU_Angle_Degree'].shift(1) < 160)
                                )
                                ) & (((df['volume_profile'] == 1) & ((((df['Close'] - df['Open']) / df['Close']) * 100) < 6.0)) | (df['volume_profile'] == 0))
    
    prev_close_less_bbl_4 =  (df['Low'].shift(4) < df['BBL'].shift(4)) & (df['Trend'].shift(4) == 'Downtrend') &  (df['EMA_Trend'].shift(4) == 'Downtrend')
    prev_close_less_bbl_5 =  (df['Low'].shift(5) < df['BBL'].shift(5)) & (df['Trend'].shift(5) == 'Downtrend') &  (df['EMA_Trend'].shift(5) == 'Downtrend')
    prev_close_less_bbl_6 =  (df['Low'].shift(6) < df['BBL'].shift(6)) & (df['Trend'].shift(6) == 'Downtrend') &  (df['EMA_Trend'].shift(6) == 'Downtrend')
    trend_down_and_rising = (((df['Trend'].shift(1) == 'Downtrend')  & ((df['regime'].shift(1) == 'other') | (df['regime'].shift(1) == 'sideways')))
                            | ((df['Trend'].shift(2) == 'Downtrend') & ((df['regime'].shift(2) == 'other') | (df['regime'].shift(2) == 'sideways'))))

    prev_low_close_to_bbl= (((df['Low'].shift(4) > df['BBL'].shift(4)) & (((df['Low'].shift(4) - df['BBL'].shift(4))/df['Low'].shift(4))*100 <= 0.80))
                              | ((df['Low'].shift(2) > df['BBL'].shift(2)) & (((df['Low'].shift(2) - df['BBL'].shift(2))/df['Low'].shift(2))*100 <= 0.80))
                              | ((df['Low'].shift(3) > df['BBL'].shift(3)) & (((df['Low'].shift(3) - df['BBL'].shift(3))/df['Low'].shift(3))*100 <= 0.80)))

    condition_downtrend_reverse = (((((df['Trend'].shift(2) == 'Downtrend') &  ((df['EMA_Trend'].shift(2) == 'Downtrend') | (df['EMA_Trend'].shift(2) == 'Flat')) 
                                      & (df['regime'].shift(2) == 'downtrend') & (df['Close'].shift(2) < df['EMA9'].shift(2)) & (df['Low'].shift(2) < df['BBL'].shift(2)))
                                  | ((df['Trend'].shift(3) == 'Downtrend') &  ((df['EMA_Trend'].shift(3) == 'Downtrend') | (df['EMA_Trend'].shift(3) == 'Flat')) 
                                     & (df['regime'].shift(3) == 'downtrend') & (df['Close'].shift(3) < df['EMA9'].shift(3)) & (df['Low'].shift(3) < df['BBL'].shift(3)))
                                  | ((df['Trend'].shift(4) == 'Downtrend') &  ((df['EMA_Trend'].shift(4) == 'Downtrend') | (df['EMA_Trend'].shift(4) == 'Flat')) 
                                     & (df['regime'].shift(4) == 'downtrend') & (df['Close'].shift(4) < df['EMA9'].shift(4)) & (df['Low'].shift(4) < df['BBL'].shift(4))) 
                                  | ((df['Trend'].shift(5) == 'Downtrend') &  ((df['EMA_Trend'].shift(5) == 'Downtrend') | (df['EMA_Trend'].shift(5) == 'Flat')) 
                                     & (df['regime'].shift(5) == 'downtrend') & (df['Close'].shift(5) < df['EMA9'].shift(5)) & (df['Low'].shift(5) < df['BBL'].shift(5)))
                                  | ((df['Trend'].shift(1) == 'Downtrend') &  ((df['EMA_Trend'].shift(1) == 'Downtrend') | (df['EMA_Trend'].shift(1) == 'Flat')) 
                                     & (df['regime'].shift(1) == 'downtrend') & (df['Close'].shift(1) < df['EMA9'].shift(1)) & (df['Low'].shift(1) < df['BBL'].shift(1))))
                                  & (df['High'] < df['BBU']) & (df['EMA_Angle_Degree'] < 180) & (df['BBU_Angle_Degree'] < df['BBU_Angle_Degree'].shift(1)) 
                                  & (df['Close'] > df['EMA9']) & (df['volume_profile'] == 1) & (df['Low'] < df['EMA9']))
                                  | 
                                  ((prev_close_less_bbl_4 | prev_close_less_bbl_5 | prev_close_less_bbl_6) & trend_down_and_rising
                                  & (df['EMA_Angle_Degree'].shift(1) < 160) & (df['EMA_Angle_Degree'].shift(2) < 180) & (df['EMA_Angle_Degree'] < 160)
                                  & (df['Close'].shift(1) > df['EMA9'].shift(1)) & (df['Close'] > df['EMA9'])  & (df['regime'] != 'sideways') & (df['Low'] < df['EMA9'])
                                  & ((df['volume_profile'] == 1) | (((df['volume_profile'] == 0) & (df['BBU'] > df['High'])))))
                                  | 
                                  (prev_low_close_to_bbl & (df['Trend'] == 'Uptrend') & (df['BB_trend'] == 'bullish') & (df['Close'] > df['EMA9']) & (df['Close'] > df['BBM'])
                                   & ((df['EMA_Trend'] == 'Uptrend') | (df['EMA_Trend'] == 'Flat')) & (df['volume_profile'] == 1) & (df['volume_profile'].shift(1) == 1)
                                   & (df['BBM_Angle_Degree'] < 160) & (df['EMA_Angle_Degree'] < 150) & (df['EMA_Angle_Degree'].shift(1) < 160))
                                  )

    
    df['Super_Low_Buy_Signal'] = condition_super_low_buy & trade_allowed
    df['Super_Low_Buy_Signal_2'] = condition_super_low_buy_2 & trade_allowed
    df['Mid_Buy_Signal_2'] = condition_mid_buy_2 & (df['Date'].dt.time >= pd.to_datetime('09:18:00').time()) & (df['Date'].dt.time < pd.to_datetime('15:28:00').time()) & allowed_trade_series
    df['RSI_pct_buy'] = RSI_pct_buy_signal & trade_allowed
    df['Downtrend_Reverse_Buy_Signal'] = condition_downtrend_reverse & (df['Date'].dt.time >= pd.to_datetime('09:18:00').time()) & (df['Date'].dt.time < pd.to_datetime('15:28:00').time()) & allowed_trade_series  #& trade_allowed
    df['New_Uptrend_Buy_Signal'] = condition_new_uptrend_buy & (df['Date'].dt.time >= pd.to_datetime('09:22:00').time()) & (df['Date'].dt.time < pd.to_datetime('15:28:00').time()) & allowed_trade_series 

    return df
