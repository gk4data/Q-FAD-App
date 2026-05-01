# Q-FAD Algorithm Trading Explainer

This document explains how the Q-FAD intraday options trading system works at a practical level: how market data is prepared, how indicators and regimes are derived, how each family of buy and sell signals behaves, and how those signals become trades in backtest and live execution.

It is written as a working explainer for the current codebase, not as a theory document. The main sources are:

- [server.py](/c:/Users/GaneshKakade/Downloads/Q-FAD%20App/server.py)
- [src/indicators/indicators.py](/c:/Users/GaneshKakade/Downloads/Q-FAD%20App/src/indicators/indicators.py)
- [src/signals/regime_detection.py](/c:/Users/GaneshKakade/Downloads/Q-FAD%20App/src/signals/regime_detection.py)
- [src/signals/buy_signals.py](/c:/Users/GaneshKakade/Downloads/Q-FAD%20App/src/signals/buy_signals.py)
- [src/signals/sell_signals.py](/c:/Users/GaneshKakade/Downloads/Q-FAD%20App/src/signals/sell_signals.py)
- [src/backtest/backtest_engine.py](/c:/Users/GaneshKakade/Downloads/Q-FAD%20App/src/backtest/backtest_engine.py)

## 1. What the strategy is trying to do

At a high level, the strategy is a long-only intraday signal engine built around:

- 1-minute candle data
- Bollinger Band structure and Bollinger-band angles
- EMA/BBM relationship and EMA recovery behavior
- RSI, adaptive RSI bands, RSI percentile, MFI percentile, and Stoch RSI
- Regime filters to separate downtrend, sideways, and general conditions
- Strong opening-session filters to avoid bad early trades
- Multiple entry templates rather than one single entry rule
- A unified sell engine that closes any open long position

The system does not treat every bullish situation the same way. Instead, it creates several specialized buy families for different market behaviors:

- continuation after recovery
- BBM/EMA bounce entries
- oversold rebound entries
- RSI range recovery entries
- deep pullback / super-low entries
- supreme-low crossover entries after heavy drop and curved recovery
- new uptrend ignition entries
- downtrend reversal entries
- EMA/BBM/BBU crossover-style recovery entries

Then it uses one aggregated sell engine to get out when momentum, structure, or regime weakens.

## 2. End-to-end pipeline

The app’s analysis flow is:

1. Fetch raw intraday candles from Upstox.
2. Optionally append previous-market-day candles so indicators have context immediately after the open.
3. Calculate indicators.
4. Detect regime and directional trend labels.
5. Generate buy signals.
6. Generate sell signals.
7. Plot, backtest, or trade from the final signal columns.

In code, the main signal path is:

1. `calculate_indicators(...)`
2. `detect_regimes_relaxed(...)`
3. `classify_trend_by_angles(...)`
4. `add_long_signal(...)`
5. `generate_buy_signals(...)`
6. `generate_sell_signals(...)`

`classify_trend_by_angles(...)` produces a helpful angle-based trend label, but the trading logic mainly depends on the columns written by `calculate_indicators(...)` and `detect_regimes_relaxed(...)`.

## 3. Core inputs and derived features

The strategy expects standard OHLCV candles:

- `Date`
- `Open`
- `High`
- `Low`
- `Close`
- `Volume`

From these it derives the following key features.

### 3.1 Trend and location features

- `EMA9`: fast directional reference
- `BBL`, `BBM`, `BBU`: Bollinger lower / middle / upper bands
- `VWAP`: session VWAP
- `volume_profile`: simple candle color proxy
  - `1` means close >= open
  - `0` means close < open

### 3.2 Momentum and oscillator features

- `RSI`
- `MFI`
- `STOCHRSIk`
- `STOCHRSId`
- `RSI_pct`: percentile rank of RSI
- `MFI_pct`: percentile rank of MFI
- `BBM_Angle_pct`: percentile rank of BBM angle

### 3.3 Adaptive thresholds

The strategy does not use a fixed RSI 30/70 band only. It creates adaptive RSI bounds:

- `RSI_lo`
- `RSI_hi`

These are widened or tightened using normalized trend and volatility. That means “oversold” and “overbought” become dynamic and session-aware.

### 3.4 Angle features

The system relies heavily on angle behavior:

- `BBM_Angle`
- `EMA_Angle`
- `BBM_Angle_Degree`
- `EMA_Angle_Degree`
- `BBU_Angle_Degree`
- `BBL_Angle_Degree`

The degree columns are especially important. In this codebase, values around `180` are roughly neutral. Lower or higher values represent the strength and direction of slope in a transformed angle space. The signal logic uses many thresholds like `140`, `160`, `180`, `190`, `240`, `250`, and `260` to separate acceptable trend shape from extreme or unstable shape.

## 4. Regime detection

The strategy uses two directional labels and one market regime label:

- `EMA_Trend`: based mainly on EMA short vs EMA long plus slope
- `Trend`: based mainly on BBM angle / BBM slope
- `regime`: one of `downtrend`, `sideways`, or `other`
- `BB_trend`: one of `bullish`, `bearish`, or `neutral`
- `is_downtrend`: helper boolean

### 4.1 How `EMA_Trend` is decided

`EMA_Trend` becomes:

- `Uptrend` when the fast EMA is above the longer EMA and slope is positive enough
- `Downtrend` when the fast EMA is below the longer EMA and slope is negative enough
- `Flat` otherwise

### 4.2 How `Trend` is decided

`Trend` uses BBM angle or BBM slope and classifies each bar as:

- `Uptrend`
- `Downtrend`
- `Flat`

This is useful because many entries look for agreement or disagreement between price, EMA, and the Bollinger middle band.

### 4.3 How `regime` is decided

`regime` is the coarser market state:

- `downtrend`: weakness supported by price below EMA, slope weakness, structure weakness, high ATR percentile, or bearish Bollinger trend
- `sideways`: narrow bands, flat EMA/BBM angles, muted Stoch behavior, or compressed volatility
- `other`: everything that is neither confirmed downtrend nor sideways

In practice:

- `downtrend` is used to enable reversal-style buys and trend-following sells
- `sideways` is often filtered to avoid false breakouts
- `other` is where many cleaner trend resumption entries are allowed

## 5. Trade permission layer before any buy signal

One of the most important parts of this system is that a bullish pattern alone is not enough. The strategy first decides whether trading is allowed at all.

### 5.1 Session timing logic

The day is split into four windows:

- `09:15` to `10:14`
- `10:15` to `11:59`
- `12:00` to `13:59`
- `14:00` onward

The code uses checkpoint comparisons at roughly:

- `10:15`
- `12:00`
- `14:00`

These checkpoints are used to decide whether VWAP-style recovery is strong enough to continue trading later in the day.

### 5.2 Opening filters

The buy engine reads the first tradable session candles and blocks trading in many dangerous opening situations, including:

- gap-up then quick red reversal
- triple-BBU exhaustion
- gap-down-green traps
- huge opening expansion
- huge opening collapse

This is one of the system’s most defensive design choices. It tries to avoid forcing entries on distorted opening structures.

### 5.3 VWAP permission / rejection logic

The engine then builds:

- `trade_if_vwap_back_*` conditions
- `vwap_coming_down_*` conditions
- `base_allowed_trade_series`
- `allowed_trade_series`
- `trade_allowed`

Conceptually:

- early or mid-session weakness can block trades
- recovery relative to VWAP and the first-session structure can reactivate trading
- late-day trading is only allowed if prior session blocks showed tradable behavior

### 5.4 Time window restrictions

Even if a setup looks valid, most buys require the session to be inside a practical intraday window. The common operating window is:

- after `09:36`
- before `15:28`

Several individual buy families also add their own minimum start times like `09:18`, `09:20`, or `09:25`.

### 5.5 Expiry-day restriction

The buy engine computes `no_trade_on_expiry_after_13`, which blocks certain buy families after `1:00 PM` on the selected expiry day.

This is a very important options-specific safety check. It reduces exposure to unstable post-lunch expiry behavior.

### 5.6 Unstable candle filter

The code computes `unstable_candle` and rejects many buys when a candle is too noisy. It blocks:

- very large total range
- very large wick ratios
- extreme upper or lower wick dominance
- very tiny green or red bodies that indicate indecision / unreliability

This is effectively a candle quality gate.

## 6. Buy signal families

The final buy side is not one rule. It is a collection of named signal columns.

### 6.1 `Buy_Signal`

This is the main base buy entry. It is a broad bullish entry family built from combinations of:

- Stoch RSI bullish crossover
- RSI not overly stretched
- rising volume behavior
- EMA near or above BBM
- breakout through recent highs or near BBU
- favorable EMA / BBM / BBU angle structure
- trend normalization checks
- trade permission and unstable-candle filters

This family mostly tries to capture “general bullish structure with enough strength and not too much distortion.”

### 6.2 `Mid_Buy_Signal`

This is a BBM bounce / mid-band continuation style entry.

Typical ingredients:

- close above EMA9 and BBM
- Stoch RSI crossover above 50
- rising EMA angle
- increasing EMA-to-BBM separation
- MFI percentile stronger than RSI
- supportive BBL angle behavior
- allowed intraday timing and stable candle behavior

This family is more of a structured continuation entry than a deep reversal entry.

### 6.3 `OverSold_Buy_Signal`

This is an oversold rebound entry.

Typical ingredients:

- prior Stoch RSI in oversold territory
- MFI percentile washed out and improving
- RSI crossing back above adaptive lower band
- prior low probing BBL
- non-extreme BBU/BBM angle behavior
- green candle confirmation

This family aims to catch recovery after short-term exhaustion.

### 6.4 `RSI_Range_Buy_Signal`

This entry is centered on adaptive RSI range recovery rather than only raw price breakout.

Typical ingredients:

- RSI crossing back above `RSI_lo`
- close recovering above EMA9 or BBM
- non-extreme BBU angle context
- moderate EMA angle
- not a bad sideways/downtrend corner case

This family is useful when momentum re-enters a tradable range after a dip.

### 6.5 `RSI_pct_buy`

This family uses percentile behavior of RSI and MFI rather than only absolute oscillator levels.

Typical ingredients:

- RSI percentile was previously weak versus MFI percentile
- current RSI percentile flips strongly higher
- price interacts constructively with EMA9
- trend is not strongly hostile
- angle structure is still tradable

This is effectively an internal-strength rotation signal.

### 6.6 `Super_Low_Buy_Signal`

This family looks for deeper pullback recovery entries.

Typical ingredients:

- price resetting into EMA / BBM / BBL areas
- supportive trend context or recovery from a locally depressed state
- price not yet in an extreme blow-off shape
- controlled candle body and volume behavior

Compared with `Buy_Signal`, this family is more “buying weakness that is stabilizing” than “buying obvious breakout strength.”

### 6.7 `Super_Low_Buy_Signal_2`

This is a second deep-pullback / recovery family with different shape tolerances. It allows another path into reversal/continuation after weakness, especially when:

- trend context still supports recovery
- high/low structure suggests rejection of lower prices
- the candle is near EMA9 but not structurally broken

### 6.8 `condition_supreme_low_crossover`

This family is designed for a very specific recovery shape after a heavy downside move.

Typical ingredients:

- the recent `BBU_Angle_Degree` average shows a strong prior downward stretch
- `BBL_Angle_Degree` and `EMA_Angle_Degree` averages suggest the downside curve is easing
- current EMA angle is no longer too steep
- `BBM_Angle_Degree` starts improving
- current close is back above both `EMA9` and `BBM`
- the prior candle’s high had already started reclaiming EMA / BBM territory

In plain terms, this is a curved recovery setup after a sharp drop, where the structure stops accelerating down and begins to re-accept the mid-band / EMA area.

### 6.9 `Mid_Buy_Signal_2`

This is another mid-zone continuation / recovery family with alternative structural conditions.

It tends to look for:

- pullback completion
- price closing back above important middle references
- acceptable angle conditions
- acceptable volatility and volume transitions

### 6.10 `condition_ema_bbu_crossover`

This is one of the most complex bullish families in the system.

It is not a single crossover rule. It combines several related bullish recovery and trend-change templates, including:

- EMA9 crossing above BBM after prior weakness
- recovery after prior lows below BBL
- recovery after price closes above BBU
- pullback continuation in confirmed uptrend
- recovery after a downtrend-to-uptrend transition
- opening reversal after strong early downside slope

This family is effectively a “major bullish re-acceptance” bucket. It contains several sub-patterns that all describe price reclaiming EMA/BBM/BBU structure after weakness.

### 6.11 `drop_down_signal_for_cond_ema_cross`

This is not a trade on its own in the final app, but it is an important helper signal and also used by the sell logic.

Conceptually it marks a recovery after older candles had:

- EMA above close but still below BBM
- then later candles show EMA reclaiming BBM
- current structure improves while previous trend was weak

It acts like a bullish recovery marker that downstream logic can reference.

### 6.12 `New_Uptrend_Buy_Signal`

This family tries to catch the start of a fresh uptrend rather than a mature continuation.

It commonly looks for:

- recent bearish or weak candles followed by bullish recovery
- close reclaiming BBM and EMA9
- supportive green-candle sequence
- non-extreme angle values
- acceptable regime context

This is one of the clearest “trend ignition” families in the system.

### 6.13 `Downtrend_Reverse_Buy_Signal`

This family targets reversal out of prior downside conditions.

Typical ingredients:

- recent `EMA_Trend` / `Trend` weakness
- current recovery above EMA9 and BBM
- controlled angle thresholds
- price no longer trapped below upper structure
- green-candle confirmation

This family is more aggressive than standard continuation buys and is specifically meant for trend reversal.

## 7. Sell signal families

There is one final `Sell_Signal` column, but it is built from many exit templates. These are all used to close long trades.

### 7.1 `condition_close_all_positions`

This is the hard end-of-day exit.

- At `15:29`, the system marks a sell.

This guarantees positions are not intentionally carried beyond the session in normal flow.

### 7.2 `condtion_ema_bbm_sell`

This is a classic momentum failure exit.

Typical ingredients:

- close below EMA9
- BBM angle weakness
- bearish Stoch RSI relationship
- MFI percentile weakening
- red candle and softer price behavior

This is the basic “trend continuation has broken” exit.

### 7.3 `condition_exit_at_top_2`

This is an exit-after-extension family.

It tries to detect situations where price was previously extended near or above BBU and now shows:

- strong red candle
- weakening angle shape
- failure after an uptrend push

This is a profit-protection style exit near local tops.

### 7.4 `alt_sell`

This family uses RSI / MFI / low structure to detect deterioration even when the standard trend-failure template is not the best fit.

Typical ingredients:

- RSI falling back under upper adaptive area
- lower lows or softer closes
- price under BBM or EMA9
- red candle confirmation

### 7.5 `condition_mfi_percentile_low`

This is an exit based on MFI percentile rollover and weakening candle structure.

It typically appears when:

- MFI percentile had been elevated
- then starts rolling over
- price no longer holds its internal support cleanly

### 7.6 `bbu_angle_and_candle_high_sell`

This family tries to sell after upper-band stress loses strength.

Typical ingredients:

- recent highs above BBU
- current close back under BBM
- red candle sequence
- BBU angle behavior showing loss of upside shape

### 7.7 `bbu_curve_sell_signal`

This is a curvature or roll-over exit.

It looks for:

- repeated red candles
- falling close sequence
- BBU angle shape curving in an unfavorable way
- weakening EMA-vs-BBM angle relationship

This is a “trend is rounding off” style exit.

### 7.8 `rsi_pct_bbu_angle_sell`

This is a percentile and angle-based weakness exit.

Typical ingredients:

- RSI percentile rotation from strong to weak
- large red body
- low breaking lower
- bearish BBU / BBM angle confirmation

### 7.9 `new_ema_sell_condition`

This family exits when price loses EMA support with weakening band geometry.

Typical ingredients:

- close below EMA9
- red candle
- EMA flattening or declining
- weakening BBU / BBL structure

### 7.10 `downtrend_ema_sell_signal`

This family is used when the regime and trend have shifted into clearer downside conditions.

Typical ingredients:

- `EMA_Trend` is `Downtrend` or `Flat`
- `Trend` is `Downtrend`
- current close is below EMA9 and often below BBM
- recent bars had only temporary recovery, then failed

### 7.11 `uptrend_ema_sell_signal`

This is important because a long trade can still need to exit while the broader earlier context had been uptrend.

This family tries to catch:

- uptrend fatigue
- transition from uptrend into downside / sideways deterioration
- repeated red candles after previous strength
- failure around EMA9 / BBM / BBU

### 7.12 `ema_downside_sell`

This is a sideways-regime weakness exit, especially when:

- regime is sideways
- EMA angle is deteriorating
- price loses EMA9
- band trend is neutral or bearish

It helps reduce death-by-chop after a long trade stops working.

### 7.13 `sideways_regime_bbu_top_sell`

This family is a specific sideways-market top rejection exit.

Typical ingredients:

- sideways regime
- failure from near/above BBU
- close back below EMA9 or BBM
- red candle confirmation

### 7.14 `bottleneck_sell_condition`

This family exits when the Bollinger envelope compresses or twists in a way that often precedes breakdown, especially when:

- close falls below EMA9 / BBM
- lower band is threatened or broken
- the band structure suggests a downside squeeze

### 7.15 `downtrend_bbl_sell_signal`

This is a more direct downside continuation exit.

Typical ingredients:

- downtrend regime
- close below EMA9 and BBM
- prior bars had temporary strength but failed
- low is testing or breaking the lower band

### 7.16 `test_past_signal`

This family exits by looking at recent buy-signal history.

It tries to detect when a previous bullish trigger has now visibly failed. For example, it references recent:

- `New_Uptrend_Buy_Signal`
- `Downtrend_Reverse_Buy_Signal`
- `drop_down_signal_for_cond_ema_cross`

and then asks whether current bearish structure invalidates those recent bullish setups.

This is a very practical “the last bullish thesis is no longer valid” exit bucket.

## 8. How the system actually enters and exits trades

### 8.1 Signal aggregation

The system does not assign a different order type to each buy family. Instead, it aggregates them.

Backtest considers a long entry true if any of these are true:

- `Buy_Signal`
- `Mid_Buy_Signal`
- `Mid_Buy_Signal_2`
- `OverSold_Buy_Signal`
- `RSI_Range_Buy_Signal`
- `Super_Low_Buy_Signal`
- `Super_Low_Buy_Signal_2`
- `condition_supreme_low_crossover`
- `New_Uptrend_Buy_Signal`
- `Downtrend_Reverse_Buy_Signal`
- `RSI_pct_buy`
- `condition_ema_bbu_crossover`

Sell is simpler:

- any `Sell_Signal` closes the open long

### 8.2 Single-position behavior

The trade engine is effectively single-position and long-only:

- it enters only if no position is open
- it ignores new buy signals while a position is already open
- it exits only if a position is open

### 8.3 Backtest execution model

The manual backtest engine:

- enters at the current bar close
- exits at the current bar close
- supports one open position at a time
- optionally applies a stop-loss
- force-closes any leftover position on the last bar

Default backtest stop-loss is `15%` in `calculate_manual_pnl(...)`.

### 8.4 Live execution model

Live trading places:

- market buy orders on aggregated buy signal
- market sell orders on aggregated sell signal
- stop-loss orders as part of the live flow

For production trading, the app can also use exit-all behavior tagged to the strategy.

## 9. Important implementation notes

### 9.1 Backtest and live entries are not perfectly identical

This is important.

Backtest includes `condition_ema_bbu_crossover` as a valid entry trigger.

The current live trading aggregation in `server.py` does not include `condition_ema_bbu_crossover` in the final `buy_signal` boolean used for order placement.

That means:

- charts may show that signal
- backtests may trade that signal
- live execution may ignore that specific signal family

This is worth keeping in mind whenever you compare backtest and live behavior.

### 9.2 `trend_regime_angles` is mainly descriptive right now

`classify_trend_by_angles(...)` computes an angle-based regime such as:

- `pure_up`
- `pure_down`
- `pure_sideways`
- `up_trend_mixed`
- `down_trend_mixed`

It is useful for diagnostics and future refinement, but the present buy/sell engine mainly keys off:

- `Trend`
- `EMA_Trend`
- `regime`
- `BB_trend`
- angle degree columns directly

### 9.3 Signal names are families, not perfect English labels

Some names like `condition_ema_bbu_crossover` or `Super_Low_Buy_Signal_2` should be read as internal strategy families. Their code now contains several related sub-patterns, so the name is narrower than the behavior.

## 10. Mental model for how to read the strategy

The easiest way to understand the strategy is:

1. First ask: is today / this time / this candle even tradable?
2. Then ask: what market regime are we in?
3. Then ask: is this a continuation, a bounce, a recovery, or a reversal?
4. Then ask: do EMA, BBM, BBU, RSI, MFI, and Stoch all agree enough?
5. Then ask: is the candle clean enough, or is it noisy / unstable?
6. If yes, one of the buy families can trigger.
7. Once in a trade, any valid sell family can close it.

That is why the system works more like a layered decision engine than a single-indicator strategy.

## 11. Short glossary

- `BBL`: lower Bollinger band
- `BBM`: middle Bollinger band
- `BBU`: upper Bollinger band
- `EMA9`: fast EMA reference
- `VWAP`: session volume-weighted average price
- `volume_profile = 1`: green candle
- `volume_profile = 0`: red candle
- `regime = sideways`: compressed, range-like environment
- `regime = downtrend`: structured downside environment
- `regime = other`: tradable non-sideways, non-confirmed-downtrend environment

## 12. Suggested next improvements for documentation

If you want, the next useful documents to add would be:

- a signal-by-signal cheat sheet with exact code references
- a “live vs backtest differences” note
- a parameter handbook for angle thresholds and time windows
- a trader-facing guide that explains how to interpret the chart markers visually
