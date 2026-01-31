import pandas as pd
import numpy as np

def add_long_signal(df):
    # Ensure working on a copy
    df = df.copy()

    # Main Buy conditions
    condition_rsi = (df['RSI']< 75) 
    condition_stochrsi_crossover = df['STOCHRSIk'] > df['STOCHRSId']
    condition_stoch_band_diff = (df['STOCHRSIk'] - df['STOCHRSId']) >= 2
    bbm_angle = (df['BBM_Angle'] <= 20)
    angle_trend_condition = df['BBM_Angle'].shift(1).rolling(window=4).mean() < df['BBM_Angle']
    volume_trend_condition = df['Volume'].shift(1).rolling(window=6).mean() < df['Volume']
    condition_no_final_position = (df['Date'].dt.time != pd.to_datetime('15:29:00').time())
    condtion_bbm_eme_high_1 = (df['High'] > df['EMA9'])
    breaking_resistance =  df['High'].shift(1).rolling(window=7).max() < df['High']
    condition_mfi_perc_buy = ((df['MFI_pct'].shift(2) <= df['MFI_pct'].shift(1)) & (df['MFI_pct'].shift(1) <= df['MFI_pct']))
    volume_profile_green = (df['volume_profile'] == 1)
    volume_greater_than_prev = df['Volume'] > df['Volume'].shift(1)
    cond_low_lower_ema = (df['EMA9'] >= df['Low'])
    cond_limit_volume = (abs((df['Volume'].shift(1) - df['Volume']))/ df['Volume'].shift(1)) < 2
    cond_ema_tred = (df['EMA_Trend'] == 'Downtrend')
    no_trade_if_close_less_than_5 = (df['Close'] > 5)
    round_ema_more_than_bbm = (round(df['EMA9'],1) >= round(df['BBM'],1))
    
    # Generate buy signal
    df['Buy_Signal'] = (
        condition_stochrsi_crossover  & angle_trend_condition & condition_stoch_band_diff &
        bbm_angle & condition_rsi   & cond_low_lower_ema & volume_trend_condition & 
        condition_no_final_position & condtion_bbm_eme_high_1 & breaking_resistance
        & condition_mfi_perc_buy & volume_profile_green  & volume_greater_than_prev
        & cond_limit_volume & cond_ema_tred & no_trade_if_close_less_than_5 & round_ema_more_than_bbm
    )
        
    # Middle buy signal conditions
    condition_prev_close_near_ema = (df['Close'].shift(1) > df['BBM'].shift(1))
    condition_curr_ema_near_Low = (df['Close'] > df['EMA9'])
    condition_curr_bbm_near_Low = (df['Close'] > df['BBM'])
    condition_stoch_rsi_crossover = (df['STOCHRSIk'] >= df['STOCHRSId']) & (df['STOCHRSIk'] > 50)
    bbm_angle_mid = df['BBM_Angle'] >= 10
    Cond_ema_angle_mid = df['EMA_Angle'] >= 40
    volume_trend_super_rise = df['Volume'] > 1.4 * df['Volume'].rolling(window=5).mean()
    condition_mfi_more_rsi = ((df['MFI_pct']*100) > df['RSI'])
    cond_limit_volume_1 = (abs((df['Volume'].shift(1) - df['Volume']))/ df['Volume'].shift(1)) < 2.5
    condition_curr_ema_greater_than_bbm =  (df['BBM'] < df['EMA9'])
    volume_greater_than_prev_prev = df['Volume'] > df['Volume'].shift(2)
    
    # Final Mid BBM Bounce Buy Signal
    condition_bbm_bounce = (
    condition_curr_ema_near_Low &
    condition_prev_close_near_ema & 
    condition_curr_bbm_near_Low & 
    condition_stoch_rsi_crossover 
    #& bbm_angle_mid
    & Cond_ema_angle_mid  
    & volume_profile_green & (volume_greater_than_prev |volume_greater_than_prev_prev)
    & volume_trend_super_rise 
    & condition_mfi_more_rsi & cond_limit_volume_1
    & condition_curr_ema_greater_than_bbm
    )
    df['Mid_Buy_Signal'] = condition_bbm_bounce

    ## overslod condition
    condition_stoch_over_sold = ((df['STOCHRSIk'].shift(1) < 5) & (df['STOCHRSIk'] > df['STOCHRSId']))
    condition_mfi_over_sold = ((df['MFI_pct'].shift(1) <= 0.625) & (df['MFI_pct'].shift(1) <= df['MFI_pct']))
    condition_rsi_low_up = ((df['RSI'] > df['RSI_lo']) & (df['RSI'].shift(1) > df['RSI_lo'].shift(1)))
    condition_ema_rising = (df['EMA9'] > df['EMA9'].shift(1))
    condition_low_less_bbl = (df['Low'].shift(1) <= df['BBL'].shift(1))
    condition_candle_high_bbm= (df['High'] >= df['BBM'])
    df['OverSold_Buy_Signal'] = (condition_stoch_over_sold & condition_mfi_over_sold & condition_ema_rising & condition_candle_high_bbm
                                 & condition_no_final_position & volume_profile_green & condition_rsi_low_up 
                                 & condition_low_less_bbl & no_trade_if_close_less_than_5)

    # New RSI Range Buy Signal
    rsi_percent_diff_2= ((df['RSI'].shift(1) - df['RSI_lo'].shift(1)) / df['RSI'].shift(1)) * 100
    rsi_low_current_rangediff = (rsi_percent_diff_2 < 20.50)
    condition_rsi_lower_range =  ((df['RSI'].shift(1) < df['RSI_lo'].shift(1)) & (df['RSI'] > df['RSI_lo']))
    condition_rsi_lower_range_1 = (rsi_low_current_rangediff) & (df['RSI'].shift(1) > df['RSI_lo'].shift(1)) & (df['RSI'] > df['RSI_lo'])
    condition_close_up = (df['Close'].shift(1) < df['Close'])
    cond_rsi_greter_than_mfi = ((df['RSI'].shift(1) > df['MFI_pct'].shift(1)) & (df['RSI'] < df['MFI_pct']))
    condition_curr_ema_greater_than_bbm =  (df['BBM'] < df['EMA9'])
    condition_stoch_rsi_crossover = (df['STOCHRSIk'] >= df['STOCHRSId'])
    condition_candle_high_less_BBH = (df['High'] < df['BBU'])
    condition_down_filter = ((df['is_downtrend'] == False) &
    ((df['MFI'] > 30) | (df['STOCHRSIk'] > 25)) & (df['BBM_Angle_pct'] > 0.4))
    condition_high_greater_than_prev_mean = (df['High'] > df['High'].shift(1).rolling(window=4).mean())

    df['RSI_Range_Buy_Signal'] = ((condition_rsi_lower_range | condition_rsi_lower_range_1 | cond_rsi_greter_than_mfi)
                                  & (condition_stoch_rsi_crossover) & (condition_candle_high_less_BBH) & (condition_down_filter) 
                                  & (condition_no_final_position) & (condition_close_up) & (no_trade_if_close_less_than_5)
                                  & (condition_curr_ema_greater_than_bbm))
    
    ## new super low buy condition
    bbm_angle_sl = ((df['BBM_Angle'] <= 0) & (df['BBM_Angle'] > -60) & (df['EMA_Angle'] > -40))
    prev_close_less_ema_bbm =  (df['Close'].shift(1) < df['BBM'].shift(1))
    prev_close_less_ema_bbm_1 =  (df['Close'].shift(2) < df['BBM'].shift(2))
    round_ema_more_than_bbm = (round(df['EMA9'],1) >= round(df['BBM'],1))
    curre_close_greater_ema_bbm = ((df['Close'] > df['EMA9']) | (df['Close'] > df['BBM']))
    condtion_high_gret_bbu = (df['High'] > df['BBU'])
                        
    cond_stoch_low = (df['STOCHRSIk'] < 71)

    cond_prev_ema_bbm_more_current_ema_bbm = ((df['EMA9'].shift(1) - df['BBM'].shift(1)) <= (df['EMA9'] - df['BBM']))

    cond_sudden_mfi_prcentile_rise = (((df['MFI_pct'].shift(2) < 0.1) | (df['MFI_pct'].shift(1) < 0.1)) & (df['MFI_pct'] >= 0.9)
                                      & (prev_close_less_ema_bbm | prev_close_less_ema_bbm_1))

    
    condition_super_low_buy = ((prev_close_less_ema_bbm  & cond_stoch_low  &  round_ema_more_than_bbm & bbm_angle_sl & volume_profile_green 
                                & curre_close_greater_ema_bbm & no_trade_if_close_less_than_5)
                               | cond_sudden_mfi_prcentile_rise) 
    
    bbm_angle_sl_1 = ((df['BBM_Angle'] >= 0) & (df['BBM_Angle'] > -60) & (df['EMA_Angle'] > -40))
    prev_close_less_ema_bbm_2 =  (df['Close'].shift(3) < df['BBM'].shift(3))
    prev_close_less_ema_bbm_3 =  (df['Close'].shift(4) < df['BBM'].shift(4))
    condtion_BBU_rise = ((df['BBU'].shift(1) < df['BBU'].shift(2)) & (df['BBL'].shift(1) > df['BBL'].shift(2)))
    condtion_BBU_funnel = ((df['BBU'] > df['BBU'].shift(1)) & (df['BBL'] < df['BBL'].shift(1)))

    condition_mid_buy_2 = (bbm_angle_sl_1 & (prev_close_less_ema_bbm | prev_close_less_ema_bbm_1 |prev_close_less_ema_bbm_2 | prev_close_less_ema_bbm_3) 
                           & round_ema_more_than_bbm & curre_close_greater_ema_bbm & condtion_BBU_rise & volume_greater_than_prev
                           & condtion_high_gret_bbu & condtion_BBU_funnel & (cond_ema_tred | (df['EMA_Trend'] == 'Uptrend')) 
                           & (df['volume_profile'].shift(1) == 1))
    
    df['Super_Low_Buy_Signal'] = condition_super_low_buy
    df['Mid_Buy_Signal_2'] = condition_mid_buy_2

    ######## Sell conditions ############ 
    condition_mfi_percentile = ((df['MFI_pct'].shift(2) >= df['MFI_pct'].shift(1)) & (df['MFI_pct'].shift(1) > df['MFI_pct']))
    condition_mfi_percentile_1 = ((df['MFI_pct'].shift(2) <= df['MFI_pct'].shift(1)) & (df['MFI_pct'].shift(1) > df['MFI_pct']))
    condition_close_sell = ((df['Close'] < df['Close'].shift(1) * 0.996) & (df['Close'].shift(1) < df['Close'].shift(2)))
    volume_profile_red = (df['volume_profile'] == 0)
    volume_decresing = (df['Volume'] > df['Volume'].shift(1))
    volume_decresing_2 = ((df['Volume'].shift(2) < df['Volume'].shift(1)) & (df['volume_profile'].shift(1) == 0))
    condition_stoch_band_diff_sell = (df['STOCHRSId'] - df['STOCHRSIk']) >= 2.2 
    condition_super_high = (((df['STOCHRSId'].shift(1) > 95)) & (df['STOCHRSIk'] < df['STOCHRSId']))
    bbm_angle_sell = (df['BBM_Angle'] <= 35)
    close_less_ema_1 = df['Close'] < df['EMA9']
    condition_bbl_lower = (df['BBL'] < df['BBL'].shift(1))

    ## close positions at 3.29 
    condition_close_all_positions = (df['Date'].dt.time == pd.to_datetime('15:29:00').time())

    ## exit at top 
    condition_exit_at_top = (condition_super_high  & condition_stoch_band_diff_sell & close_less_ema_1 & volume_profile_red 
                             & condition_bbl_lower) 
                             
    condition_exit_at_top_2 = (((volume_profile_red & (df['EMA_Angle'] > 10)) 
                                & (((df['High'] - df['BBU'])/ df['High'])*100 >= 0.90)
                                & (((df['Open'] - df['Close'])/ df['Open'])*100 >= 0.60)
                                & ((((df['EMA9'] - df['BBM'])/ df['EMA9'])*100 <= 2.75) | (((df['EMA9'] - df['BBM'])/ df['EMA9'])*100 >= 7)))
                                | (volume_profile_red & (((df['High'] - df['BBU'])/ df['High'])*100 >= 3) & (df['EMA_Angle'] > 30)))

    ## ema & bbm angle sell condition
    condtion_ema_bbm_sell = (bbm_angle_sell  & close_less_ema_1  & condition_close_sell  & volume_profile_red & (condition_mfi_percentile | condition_mfi_percentile_1))

    ## alt sell condition
    alt_sell = (((df['RSI'].shift(1) >= 75) & (df['BBM_Angle_pct'].shift(1) >= 0.85) 
                & (df['MFI'] >= 80) & (condition_mfi_percentile | condition_mfi_percentile_1) & volume_decresing) 
                | ((df['RSI_hi'].shift(1) < df['RSI'].shift(1)) & (df['RSI_hi'] > df['RSI']) & (volume_decresing)))

    # cond based on MFI percentile & Stoch rsi
    cond_mfi_perc_stoch = ((df['STOCHRSIk'].shift(1) > 75) & (condition_mfi_percentile | condition_mfi_percentile_1)
                            & (((df['Close'].shift(1) - df['Close']) / df['Close'].shift(1)) > 0.025) &  (df['High'] < df['BBU'])
                            & (volume_decresing) 
                            & (((df['Volume'] - df['Volume'].shift(1))/df['Volume']) >= 0.10))  

    #cond based on bbm and ema cross
    condition_ema_less_bbm = (((df['EMA9'].shift(1) >= df['BBM'].shift(1)) & (df['EMA9'] < df['BBM'])) 
                              & ((df['STOCHRSId'] - df['STOCHRSIk']) >= 5))

    # sell signal based on volume profile
    condition_volume_profile_sell = ((df['volume_profile'] == 0)
                                     & (df['BBM_Angle_pct'].shift(1) > df['BBM_Angle_pct'])
                                     & (volume_decresing) & (df['High'] <= df['BBU'])
                                     & (((df['Close'].shift(1) - df['Close']) / df['Close'].shift(1)) > 0.02)
                                     & (((df['Volume'] - df['Volume'].shift(1))/df['Volume']) >= 0.10)
                                     & ((df['BBM_Angle']>= 0.8) | (df['BBM_Angle_pct'] >= 0.8)))

    condition_volume_profile_sell_2 = ((df['volume_profile'] == 0)
                                     & (df['MFI_pct'].shift(1) > df['MFI_pct'])
                                     & ((df['Low'] < df['EMA9']) | (df['Low'] < df['BBM']))
                                     & (df['RSI'].shift(1) > df['RSI'])
                                     & (volume_decresing)
                                     & (((df['Close'].shift(1) - df['Close']) / df['Close'].shift(1)) > 0.005)
                                     & (((df['Volume'] - df['Volume'].shift(1))/df['Volume']) >= 0.10))

    #Generate sell signal
    df['Sell_Signal'] = ((condition_close_all_positions) 
                         | (condtion_ema_bbm_sell)
                         | (alt_sell) 
                         | (cond_mfi_perc_stoch)
                         | (condition_volume_profile_sell) 
                         | (condition_ema_less_bbm)
                         | (condition_volume_profile_sell_2)
                         | (condition_exit_at_top)
                         | (condition_exit_at_top_2))
    return df
