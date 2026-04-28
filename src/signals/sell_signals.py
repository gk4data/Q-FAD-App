import pandas as pd
import numpy as np
from typing import List


def _ensure_columns(df: pd.DataFrame, cols: List[str]):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for sell signals: {missing}")


def generate_sell_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Generate sell-related signal columns on a copy of `df` and return it.

    Requires columns such as 'MFI_pct', 'Close', 'STOCHRSId', 'STOCHRSIk', 'BBM_Angle',
    'EMA9', 'BBL', 'Date', 'Volume', 'BBU', 'Open', 'BBM', 'RSI', 'BBM_Angle_pct', 'MFI', 'RSI_hi'.
    """
    df = df.copy()

    required = [
        'MFI_pct', 'Close', 'STOCHRSId', 'STOCHRSIk', 'BBM_Angle', 'EMA9', 'BBL', 'Date',
        'Volume', 'BBU', 'Open', 'BBM', 'RSI', 'BBM_Angle_pct', 'MFI', 'RSI_hi', 'volume_profile',
        'Trend', 'BBU_Angle_Degree', 'BBM_Angle_Degree', 'EMA_Angle', 'BBL_Angle_Degree', 'BB_trend', 'regime', 'RSI_pct', 'EMA_Trend'
    ]
    _ensure_columns(df, required)

    # time mask to avoid early sell alerts
    no_sell_time = (df['Date'].dt.time > pd.to_datetime('09:36:00').time())
    condition_mfi_percentile = ((df['MFI_pct'].shift(2) >= df['MFI_pct'].shift(1)) & (df['MFI_pct'].shift(1) > df['MFI_pct']))
    condition_mfi_percentile_1 = ((df['MFI_pct'].shift(2) <= df['MFI_pct'].shift(1)) & (df['MFI_pct'].shift(1) > df['MFI_pct']))
    condition_close_sell = ((df['Close'] < df['Close'].shift(1) * 0.996) & (df['Close'].shift(1) < df['Close'].shift(2)))
    volume_profile_red = (df['volume_profile'] == 0)
    volume_decresing = (df['Volume'] > df['Volume'].shift(1))
    bbm_angle_sell = (df['BBM_Angle'] <= 35)
    close_less_ema_1 = df['Close'] < df['EMA9']
    ema_bbm_minor_diff = ((((df['EMA9'] - df['BBM'].shift(1))/df['EMA9'])*100 <= 0.17) | (df['EMA9'] <= df['BBM']))

    ## close positions at 3.29 
    condition_close_all_positions = (df['Date'].dt.time == pd.to_datetime('15:29:00').time())
                             
    condition_exit_at_top_2 = (
                              ((df['Trend'] == 'Uptrend')  #& ((df['Volume'].shift(1) > df['Volume'].shift(2)))
                                & volume_profile_red & (df['BBU_Angle_Degree'] < 120)
                                & (((((df['Open']) - df['Close']) / df['Open'])*100 > 1.60) | ((df['Open'] < df['BBU']) & (df['Close'] < df['BBU'])) | ((df['Open'] > df['BBU']) & (df['Close'] > df['BBU'])))
                                & (((((df['High'].shift(1) - df['Close'].shift(1))/ df['High'].shift(1))*100) >= 3.5) 
                                | ((((df['BBU'].shift(1) - df['Close'].shift(1))/ df['BBU'].shift(1))*100) <= 1.2))
                                & ((((df['High'].shift(1) - df['BBU'].shift(1))/ df['High'].shift(1))*100) >= 4.5)
                                #& (df['High'].shift(1) > df['Open'])
                                )|
                                ((df['Trend'] == 'Uptrend') & (df['EMA_Angle_Degree'] < 120) & (df['BBU_Angle_Degree']  < 120)
                                  & ((df['BBL_Angle_Degree']  < 130) | (df['BBL_Angle_Degree'].shift(1)  < 130))
                                  & (df['BBU_Angle_Degree'] > df['BBU_Angle_Degree'].shift(1)) & (df['volume_profile'] == 0)
                                 #  & ((df['Open'].shift(1) > df['BBU'].shift(1)) & (df['volume_profile'].shift(1) == 1))
                                 #  & (((df['Open'] > df['BBU']) & (df['volume_profile'] == 0)) | ((df['High'] > df['BBU']) & (df['volume_profile'] == 0)))
                                  & (((((df['Open']) - df['Close']) / df['Open'])*100 > 1.60))
                                )
                                |
                                ((df['Trend'] == 'Uptrend') & (df['EMA_Angle_Degree'] > 190) & (df['EMA_Angle_Degree'].shift(1)  > 190)
                                & (df['High'].shift(1).rolling(window=3).mean() > df['High'])
                                & (df['Low'].shift(1) > df['Low'])  & (df['Low'].shift(2) > df['Low'])
                                & ((df['Close'] < df['BBM']) & (df['Close'] < df['EMA9'])))
                              )
    
    ## ema & bbm angle sell condition
    condtion_ema_bbm_sell = (bbm_angle_sell & ema_bbm_minor_diff & close_less_ema_1  & condition_close_sell  & volume_profile_red 
                             & (condition_mfi_percentile | condition_mfi_percentile_1) & (df['STOCHRSId'] > df['STOCHRSIk'])
                             & volume_decresing
                             )

    ## alt sell condition
    alt_sell = ((((df['RSI_hi'].shift(1) < df['RSI'].shift(1)) | (df['RSI_hi'].shift(2) < df['RSI'].shift(2)))
                   & (df['RSI_hi'] > df['RSI']) & (df['RSI_pct']*100 < df['RSI']) & (df['Low'].shift(1) > df['Low']) 
                   & (df['Low'].shift(2) > df['Low']) & volume_profile_red & (df['EMA9'] > df['Low']) & (df['MFI_pct']*100 <= 50))
                | (((df['RSI_hi'].shift(1) > df['RSI'].shift(1)) | (df['RSI_hi'].shift(2) > df['RSI'].shift(2))) & (df['EMA9'] > df['Low'])
                   & ((df['BBM'] > df['Low']) & ((((df['BBM']) - df['Low']) / df['BBM'])*100 > 0.66))
                   & ((df['Close'] < df['BBM']) | (df['Close'] < df['EMA9'])) & (df['MFI_pct']*100 <= 50)
                   & ((((df['RSI_hi'].shift(1) - df['RSI'].shift(1))/ df['RSI_hi'].shift(1))*100 <= 6) | (((df['RSI_hi'].shift(2) - df['RSI'].shift(2))/ df['RSI_hi'].shift(2))*100 <= 6))
                   & volume_profile_red & (df['Low'] < df['Low'].shift(1)) & (df['Close'] < df['Close'].shift(1))) 
                | (((df['RSI_hi'].shift(1) < df['RSI'].shift(1)) | (df['RSI_hi'].shift(2) < df['RSI'].shift(2)))) & (df['RSI_hi'] > df['RSI'])
                   & (df['Low'].shift(1) > df['Low']) & (df['Low'].shift(2) > df['Low']) & volume_profile_red & (df['EMA9'] > df['Close'])
                   & (df['Trend'] == 'Uptrend') & (df['EMA_Trend'] == 'Uptrend') & (df['BBU_Angle_Degree'] >= 190) & (df['EMA_Angle_Degree'] >= 190)
                   & (((df['High'] - df['Low'])/df['High'])*100 >= 1)
                )& (df['High'] < df['BBU'])  & no_sell_time
    
    # cond based on MFI percentile & Stoch rsi
    condition_mfi_percentile_low = (((df['MFI_pct'].shift(2)*100 > df['RSI_hi'].shift(2)) | (df['MFI_pct'].shift(1)*100 >df['RSI_hi'].shift(1))) 
                                    & (df['MFI_pct'].shift(2) >= df['MFI_pct'].shift(1)) & (df['MFI_pct'].shift(1) > df['MFI_pct']) & volume_profile_red
                                    & (df['BBM_Angle_pct'].shift(1) > df['BBM_Angle_pct']) & (df['Low'] <= df['EMA9']) & (df['MFI_pct']*100 < df['RSI_hi'])
                                    & (((((df['Close'] - df['Low']))/df['Close']))*100 > 0.15)
                                    & (((df['EMA9'] > df['BBM']) & ((((df['EMA9'] - df['BBM']))/df['EMA9'])*100 < 2.75) & (((((df['BBM'] - df['Low']))/df['BBM']))*100 > 0.50)) 
                                       | (df['EMA9'] < df['BBM'])
                                       | ((df['EMA9'] > df['BBM']) & ((((df['Close'].shift(1) - df['Close']))/df['Close'].shift(1))*100 > 6) & (((((df['BBM'] - df['Low']))/df['BBM']))*100 > 0.50)))
                                    &  (((((df['Open'] - df['Close']))/df['Open']))*100 > 0.05)
                                    & (((((df['BBM'] - df['Low']))/df['BBM']))*100 > 0.50))


    bbu_angle_and_candle_high_sell = ((df['BBU_Angle_Degree'] >= 181) & ((df['High'].shift(1) > df['BBU'].shift(1)) | (df['High'].shift(2) > df['BBU'].shift(2)))
                                        & (df['volume_profile'] == 0) & (df['volume_profile'].shift(1) == 0) & (df['Close'] <= df['BBM'])
                                        & (((df['BBU'].shift(1) - df['BBU'])/df['BBU'].shift(1))*100 >= 0.01)
                                        & (((df['EMA9'] > df['BBM']) & (((df['EMA9'] - df['BBM'])/df['EMA9'])*100 > 0.30)) | (df['EMA9'] < df['BBM']))
                                        & (df['BBU_Angle_Degree'].shift(1) < df['BBU_Angle_Degree'])
                                        & (df['High'] < df['BBU'])#& (df['regime'] != 'downtrend')
                                        )
    
    bbu_curve_sell_signal = (((df['BBU_Angle_Degree'].shift(4) <= df['BBU_Angle_Degree'].shift(3)) & (df['BBU_Angle_Degree'].shift(3) <= df['BBU_Angle_Degree'].shift(2))
                             & (df['BBU_Angle_Degree'].shift(2) <= df['BBU_Angle_Degree'].shift(1)) & (df['BBU_Angle_Degree'].shift(1) <= df['BBU_Angle_Degree'])
                              & (df['volume_profile'] == 0) & (df['volume_profile'].shift(1) == 0) & (df['volume_profile'].shift(2) == 0) & (df['volume_profile'].shift(3) == 0) 
                              & (df['Close'].shift(3) > df['Close'].shift(2)) & (df['Close'].shift(2) > df['Close'].shift(1)) & (df['Close'].shift(1) > df['Close'])
                              & (df['Close'] <= df['BBU']) & (df['RSI_pct'] < df['MFI_pct'])
                              & (df['EMA_Trend'].shift(1) == 'Uptrend') & (df['Trend'].shift(1) == 'Uptrend')
                              & (df['EMA_Angle'].shift(1) > df['BBM_Angle'].shift(1)) & (df['EMA_Angle'] < df['BBM_Angle']))
                              | ((df['volume_profile'] == 0) & (df['volume_profile'].shift(1) == 0) & (df['volume_profile'].shift(2) == 0)
                                 & (df['Close'].shift(3) > df['Close'].shift(2)) & (df['Close'].shift(2) > df['Close'].shift(1)) & (df['Close'].shift(1) > df['Close'])
                                 & (((df['BBM_Angle_Degree'].shift(3) < 130) & (df['BBM_Angle_Degree'].shift(4) < 130)) 
                                 | ((df['BBM_Angle_Degree'].shift(4) < 130) & (df['BBM_Angle_Degree'].shift(5) < 130)))
                                 & (df['EMA_Angle_Degree'] > 220) & (df['BBU_Angle_Degree'] > 190) & (df['Close'] < df['EMA9']) & (df['Close'] < df['BBM'])))
                              
    rsi_pct_bbu_angle_sell = (
                              ((df['BBU_Angle_Degree'].shift(1) <= df['BBU_Angle_Degree'])
                                 & ((((df['Open']) - df['Close']) / df['Open'])*100 > 2) & (df['RSI_pct']*100 > df['RSI_lo']) 
                                 & ((df['RSI_pct'].shift(1)*100 > df['RSI_hi']) | (df['RSI_pct'].shift(2)*100 > df['RSI_hi']))
                                 & (df['RSI_pct']*100 < df['RSI_hi']) & (df['RSI_pct'] < df['MFI_pct'])
                                 & ((df['Low'] <  df['Low'].shift(3)) &  (((df['Low'].shift(3) - df['Low'])/ df['Low'].shift(3))*100 >= 0.78))
                                 & (np.where(df['regime'] != 'other', (df['RSI_pct'] * 100 < df['RSI']), 
                                 (((df['BBU_Angle_Degree'].shift(1) <= 180) & (df['BBM_Angle_Degree'] >= 135) & (df['BBU_Angle_Degree'] >= 130)
                                   & (df['EMA_Angle_Degree'] >= 182))))))
                              |
                                ((df['BBU_Angle_Degree'].shift(1) >= df['BBU_Angle_Degree'].shift(2)) & ((df['RSI_pct'].shift(2)*100 > df['RSI_hi']))         
                                 & ((df['RSI_pct'].shift(2)*100 > df['RSI'])) & ((df['RSI_pct'].shift(1)*100 < df['RSI']))
                                 & (df['RSI_pct']*100 < df['RSI_lo']))
                            ) & volume_profile_red & no_sell_time & (df['Low'] < df['BBM']) & (((df['BBM'] - df['Low'])/ df['BBM'])*100 >= 0.25)
    
    new_ema_sell_condition = ((df['Close'] <= df['EMA9'])  &  volume_profile_red 
                              & (df['BBU_Angle_Degree'].shift(1) < df['BBU_Angle_Degree']) & (df['BBL_Angle_Degree'].shift(1) > df['BBL_Angle_Degree'])
                              & (df['EMA9'].shift(1) > (df['EMA9'])) & (df['Low'].shift(1).rolling(window=3).mean() > df['Low'])
                              & ((((df['Open'] - df['Close']) / df['Open'])*100) >= 0.25)
                              & ((df['EMA9'] > df['BBM']) & (((df['EMA9'] - df['BBM'])/df['EMA9'])*100 <= 0.35)))
                             
    
    downtrend_ema_sell_signal = (((df['EMA_Trend'] == 'Downtrend') & (df['Trend'] == 'Downtrend') & (df['regime'] == 'downtrend') & (df['volume_profile'] == 0)
                                & ((df['Close'].shift(1) >= df['EMA9'].shift(1)) 
                                    | ((df['Open'].shift(1) >= df['EMA9'].shift(1)) & (df['Close'].shift(1) <= df['EMA9'].shift(1)))) 
                                & (df['Close'] < df['EMA9']) & (df['High'].shift(2) >= df['High']))
                                |
                                (((df['Close'].shift(1) >= df['EMA9'].shift(1)) | (df['Close'].shift(2) >= df['EMA9'].shift(2)) | (df['Close'].shift(3) >= df['EMA9'].shift(3)) 
                                 | (df['Close'].shift(4) >= df['EMA9'].shift(4)))
                                 & ((df['EMA_Trend'] == 'Downtrend') | (df['EMA_Trend'] == 'Flat')) & (df['Trend'] == 'Downtrend') & (df['regime'] == 'downtrend')
                                 & (df['Close'] < df['EMA9']) & (df['volume_profile'] == 0) & (df['BBM'] > df['Low']) 
                                 & (df['Close'].shift(2) < df['Close'].shift(3)) & (df['Close'].shift(1) < df['Close'].shift(2)) & (df['Close'].shift(1) > df['Close']))
                                |((df['Trend'].shift(1) == 'Downtrend') & (df['Trend'].shift(2) == 'Downtrend') & ((df['regime'] == 'downtrend') | (df['regime'] == 'sideways'))
                                  & ((df['regime'].shift(1) == 'downtrend') | (df['regime'].shift(1) == 'sideways'))
                                  & (((df['Close'].shift(1) >= df['EMA9'].shift(1)) & (df['Close'].shift(2) >= df['EMA9'].shift(2)))
                                  | ((df['Close'].shift(2) >= df['EMA9'].shift(2)) & (df['Close'].shift(3) >= df['EMA9'].shift(3))))
                                  & (df['Close'] < df['EMA9']) & (df['Close'] < df['BBM'])
                                 ))
    
    uptrend_ema_sell_signal = ((((((df['EMA_Trend'] == 'Uptrend') & (df['Trend'] == 'Uptrend')) & ((df['regime']== 'downtrend') | (df['regime']== 'sideways')))
                               | (((df['EMA_Trend'] == 'Flat') & (df['Trend'] == 'Uptrend')) & ((df['regime']== 'downtrend') | (df['regime']== 'sideways')))
                               | (((df['EMA_Trend'] == 'Flat') & (df['Trend'] == 'Flat')) & ((df['regime']== 'downtrend') | (df['regime']== 'sideways'))))
                                & (df['volume_profile'] == 0) & (df['Low'].shift(1) > df['Low'])
                                & (df['High'].shift(1) >= df['EMA9'].shift(1)) & (df['High'].shift(2) >= df['EMA9'].shift(2))
                                & (df['Close'] < df['EMA9']) & (df['Close'] < df['BBM']) & (df['volume_profile'].shift(1) == 0)
                                & (df['EMA_Angle_Degree'] >= 180) & (df['BBM_Angle_Degree'] >= 180) & (df['EMA_Angle_Degree'].shift(1) < df['EMA_Angle_Degree']))
                              |(((df['EMA_Trend'] == 'Uptrend') & (df['Trend'] == 'Uptrend') & (df['regime']== 'other'))
                                & ((df['High'].shift(3) >= df['BBU'].shift(3)) | (df['High'].shift(4) >= df['BBU'].shift(4)))
                                & (df['volume_profile'].shift(2) == 0) & (df['volume_profile'].shift(1) == 0) & (df['volume_profile'] == 0)
                                & (df['BBM'] > df['Low']) & (df['EMA9'] > df['Low']) & (df['BBM_Angle_Degree'] >= df['BBM_Angle_Degree'].shift(1)))
                              |(((df['EMA_Trend'] == 'Uptrend') & (df['Trend'] == 'Uptrend') & (df['regime']== 'sideways'))
                                & ((df['High'].shift(3) >= df['BBU'].shift(3)) | (df['High'].shift(4) >= df['BBU'].shift(4)))
                                & (df['volume_profile'].shift(2) == 0) & (df['volume_profile'].shift(1) == 0) & (df['volume_profile'] == 0)
                                & (df['BBM'] > df['Close']) & (df['EMA9'] > df['Close']) & (df['EMA_Angle_Degree'] >= df['EMA_Angle_Degree'].shift(1)))
                              |(((df['EMA_Trend'] == 'Flat') & (df['Trend'] == 'Uptrend'))
                                & ((df['High'].shift(3) >= df['BBU'].shift(3)) | (df['High'].shift(4) >= df['BBU'].shift(4)) | (df['High'].shift(2) >= df['BBU'].shift(2)))
                                & (df['volume_profile'].shift(2) == 0) & (df['volume_profile'].shift(1) == 0) & (df['volume_profile'] == 0)
                                & (df['BBM'] > df['Close']) & (df['EMA9'] > df['Close']) & (df['EMA_Angle_Degree'] >= df['EMA_Angle_Degree'].shift(1))
                                & (df['EMA_Angle_Degree'] >= 190) & (df['BBU_Angle_Degree'] >= 180))
                              )
                        
    ema_downside_sell = ((df['regime'] == 'sideways') & (df['volume_profile'] == 0)
                        & ((df['BB_trend'] == 'neutral') | (df['BB_trend'] == 'bearish'))
                        & ((df['EMA_Angle_Degree'].shift(3) < df['EMA_Angle_Degree'].shift(2)) & (df['EMA_Angle_Degree'].shift(2) < df['EMA_Angle_Degree'].shift(1)) 
                          & (df['EMA_Angle_Degree'].shift(1) < df['EMA_Angle_Degree']))
                        & ((df['Close'].shift(1) >= df['EMA9'].shift(1)) | (df['Close'].shift(2) >= df['EMA9'].shift(2)))
                        & (df['Close'] < df['EMA9']) & (~(df['EMA_Trend'] == 'Flat') & (df['Trend'] == 'Uptrend'))
                        & (df['Low'].shift(1) >= df['Low']))
    
    sideways_regime_bbu_top_sell = (
                                    ((df['regime'] == 'sideways') & ((df['BB_trend'] == 'neutral') | (df['BB_trend'] == 'bearish'))
                                    & (df['EMA_Trend'] == 'Flat') & (df['volume_profile'] == 0) & (df['Low'] < df['EMA9'])
                                    & ((((df['Open'] > df['EMA9']) | (df['Open'] > df['BBM']))
                                       & ((df['High'] > df['BBU']) & ((((df['High'] - df['BBU'])/ df['High'])*100) >= 1.8)))
                                    | ((((df['High'].shift(2) > df['BBU'].shift(2)) & (df['volume_profile'].shift(2) == 0) & (df['Close'].shift(2) > df['EMA9'].shift(2))) 
                                     |((df['High'].shift(1) > df['BBU'].shift(1)) & (df['volume_profile'].shift(1) == 0) & (df['Close'].shift(1) > df['EMA9'].shift(1))))
                                     & (df['Close'] < df['EMA9']) & (df['EMA9'] < df['EMA9'].shift(1))))
                                     & (((df['EMA9'] > df['BBM']) & (((df['EMA9'] - df['BBM'])/df['EMA9'])*100 > 0.30)) | (df['EMA9'] < df['BBM']))
                                     & ((df['Close'] < df['BBM']) | ((df['Low'] < df['BBM']) & (((df['BBM'] - df['Low'])/df['BBM'])*100 > 1)))
                                     )
                                    |
                                    ((df['regime'] == 'sideways') & ((df['EMA_Trend'] == 'Flat') & (df['EMA_Trend'].shift(1) == 'Uptrend')) 
                                      & (df['Open'].shift(1) > df['EMA9'].shift(1)) & (df['Close'] < df['EMA9']) & (df['Close'] < df['BBM'])
                                      & (((df['EMA9'] > df['BBM']) & (((df['EMA9'] - df['BBM'])/df['EMA9'])*100 > 0.30)) | (df['EMA9'] < df['BBM']))
                                      & (df['volume_profile'].shift(1) == 0) & (df['volume_profile']== 0) & (df['EMA9'].shift(1) > df['EMA9']))
                                    | 
                                    ((df['regime'] == 'sideways') & ((df['EMA_Trend'] == 'Flat')) & (df['Trend'] == 'Uptrend')
                                       & (df['volume_profile'] == 0) & (df['Close'] < df['EMA9']) & (df['Close'] < df['BBM'])
                                       & (((df['EMA9'] > df['BBM']) & (((df['EMA9'] - df['BBM'])/df['EMA9'])*100 > 0.30)) | (df['EMA9'] < df['BBM']))
                                       & ((df['BBM_Angle_Degree'] >= 185) | (df['BBU_Angle_Degree'] >= 185)))
                                      )
                                    
    
    bottleneck_sell_condition = ((((df['Close'] < df['EMA9']) | (df['Close'] < df['BBM']))  &  volume_profile_red 
                                & ((((df['BBU'].shift(3) > df['BBU'].shift(2)) & (df['BBL'].shift(3) < df['BBL'].shift(2)))
                                & ((df['BBU'].shift(2) > df['BBU'].shift(1)) & (df['BBL'].shift(2) < df['BBL'].shift(1))))
                                | (((df['BBU'].shift(4) > df['BBU'].shift(3)) & (df['BBL'].shift(4) < df['BBL'].shift(3)))
                                & ((df['BBU'].shift(3) > df['BBU'].shift(2)) & (df['BBL'].shift(3) < df['BBL'].shift(2)))))
                                & ((df['Low'] < df['BBL'])))
                              |(((df['Close'] < df['EMA9']) | (df['Close'] < df['BBM']))  &  volume_profile_red
                                & (df['Close'].shift(2) < df['EMA9'].shift(2)) & (df['Close'].shift(1) < df['EMA9'].shift(1))
                                & ((df['BBU'].shift(2) > df['BBU'].shift(1)) & (df['BBL'].shift(2) < df['BBL'].shift(1)))
                                & ((df['BBU'] > df['BBU'].shift(1)) & (df['BBL'] < df['BBL'].shift(1)))
                                & (df['Low'] < df['BBL']))
                              | ((((df['Close'].shift(2) > df['EMA9'].shift(2)) & (df['EMA9'].shift(2) > df['BBM'].shift(2))) 
                                | ((df['Close'].shift(3) > df['EMA9'].shift(3)) & (df['EMA9'].shift(3) > df['BBM'].shift(3)))
                                | ((df['Close'].shift(4) > df['EMA9'].shift(4)) & (df['EMA9'].shift(4) > df['BBM'].shift(4))))
                                & (df['BBL_Angle_Degree'].shift(1) < df['BBL_Angle_Degree']) & (df['BBL_Angle_Degree'] > 190)
                                & (df['Close'] < df['EMA9']) & (df['Low'] < df['BBL']) & volume_profile_red)
                                & ((df['EMA_Trend'] == 'Downtrend') | (df['EMA_Trend'] == 'Flat')))
      
    downtrend_bbl_sell_signal = (((df['EMA_Trend'] == 'Downtrend') | (df['EMA_Trend'] == 'Flat')) 
                                & (df['Trend'] == 'Downtrend') & (df['regime'] == 'downtrend') & (df['volume_profile'] == 0)
                                & ((df['Close'].shift(2) > df['EMA9'].shift(2)) | (df['Close'].shift(3) > df['EMA9'].shift(3))
                                   | (df['Close'].shift(1) > df['EMA9'].shift(1)) | (df['Close'].shift(4) > df['EMA9'].shift(4)))   
                                & (df['Close'] < df['EMA9']) & (df['Close'] < df['BBM']) & (df['BBL'] >= df['Low']))
    
    test_past_signal = (
                        (((df['New_Uptrend_Buy_Signal'].shift(1) == True) | (df['New_Uptrend_Buy_Signal'].shift(2) == True)) 
                        & volume_profile_red & (((df['Open'] - df['Close'])/df['Open'])*100 >= 1.20) & (df['Close'] < df['BBM'])
                        & ((df['BBU_Angle_Degree'] >= 188) | ((df['BBL_Angle_Degree'] >= 180) & (df['regime'] == 'sideways'))))
                        | (((df['New_Uptrend_Buy_Signal'].shift(2) == True) | (df['New_Uptrend_Buy_Signal'].shift(3) == True) | (df['New_Uptrend_Buy_Signal'].shift(4) == True))
                           & ((df['BBU_Angle_Degree'] >= 188) | ((df['BBL_Angle_Degree'] >= 180) & (df['regime'] == 'sideways'))) 
                           & (df['Close'] < df['EMA9']) & ((df['Close'] < df['BBM']))# | ((df['Close'] < df['Close'].shift(1)) & (df['Close'].shift(1) < df['Close'].shift(2))))  
                           & (((df['Open'] - df['Close'])/df['Open'])*100 >= 1.20) & volume_profile_red)
                        |
                        (((df['Downtrend_Reverse_Buy_Signal'].shift(1) == True) | (df['Downtrend_Reverse_Buy_Signal'].shift(2) == True))
                         & (df['EMA9'] < df['BBM']) & ((df['EMA9'].shift(1) < df['BBM'].shift(1)) | (df['EMA9'].shift(2) < df['BBM'].shift(2)))
                         & volume_profile_red & (df['BBM_Angle_Degree'] > 180) & (df['EMA_Angle_Degree'] > 180)
                         & (((df['Low'] < df['Low'].shift(1)) & (((df['Low'].shift(1) - df['Low']) / df['Low'].shift(1))*100 > 0.05)) 
                            | ((((df['Open']) - df['Close']) / df['Open'])*100 > 0.55) | (df['BBL'] < df['BBL'].shift(1))
                            | ((df['BBM'] - df['EMA9']) > (df['BBM'].shift(1) - df['EMA9'].shift(1)))))
                        | (((df['drop_down_signal_for_cond_ema_cross'].shift(1) == True) | (df['drop_down_signal_for_cond_ema_cross'].shift(2) == True)
                           | (df['drop_down_signal_for_cond_ema_cross'].shift(3) == True)) & volume_profile_red
                          & (df['BBU_Angle_Degree'] > 180) & (df['EMA_Angle_Degree'] > 185) 
                          & (df['Close'] < df['EMA9']) & ((df['Close'] < df['BBM'])))
                        )

##Generate sell signal
    df['Sell_Signal'] =  ((condition_close_all_positions)
                         | (condtion_ema_bbm_sell)
                         | (alt_sell) 
                         | (condition_mfi_percentile_low)
                         | (condition_exit_at_top_2)
                         | (bbu_angle_and_candle_high_sell)
                         | (bbu_curve_sell_signal)
                         | (rsi_pct_bbu_angle_sell) 
                         | (new_ema_sell_condition)
                         | (downtrend_ema_sell_signal)
                         | (ema_downside_sell)
                         | (sideways_regime_bbu_top_sell)
                         | (bottleneck_sell_condition)
                         | (downtrend_bbl_sell_signal)
                         | (uptrend_ema_sell_signal)
                         | (test_past_signal)
                          ) & (df['condition_ema_bbu_crossover'] != True)
   #df['Sell_Signal'] =  (condition_exit_at_top_2 | condition_close_all_positions)
    return df