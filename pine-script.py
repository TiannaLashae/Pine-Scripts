//@version=6
// ═══════════════════════════════════════════════════════════════════
// ULTIMATE TRADING BOT v5.2 — EUR/USD | 5-Minute Chart
// ═══════════════════════════════════════════════════════════════════
//
// LIVE vs BACKTEST NOTE:
// ─────────────────────────────────────────────────────────────────
// Signals fire at confirmed bar CLOSE (barstate.isconfirmed).
//
// With process_orders_on_close = false (default Pine behaviour):
//   - strategy.entry() submitted at bar close
//   - fill simulated at NEXT bar open
//   - strategy.position_avg_price = next bar open price
//
// Alert SL/TP are estimated from signal-bar close + signalSlDist.
// Actual backtest SL/TP are from position_avg_price (next open).
// Gap is usually small for liquid markets at bar close.
//
// For live trading: server.py should recalculate SL/TP from
// actual broker fill price using sl_dist from the alert payload.
//
// WHY process_orders_on_close = false:
//   Setting true fills on the same bar the signal fires — unrealistic
//   for live execution. False gives an honest backtest matching real
//   market order flow where fills happen at next bar open.
// ═══════════════════════════════════════════════════════════════════

strategy("Ultimate Trading Bot v5.2",
     overlay                 = true,
     default_qty_type        = strategy.percent_of_equity,
     default_qty_value       = 1,
     commission_type         = strategy.commission.percent,
     commission_value        = 0.005,
     slippage                = 2,
     calc_on_order_fills     = false,
     process_orders_on_close = false)

// ─────────────────────────────────────────────────────────────────────
// SECTION 1: INPUTS
// ─────────────────────────────────────────────────────────────────────

useRSI   = input.bool(true,  "Use RSI Filter",        group="Indicator Toggles")
useMA    = input.bool(true,  "Use MA Trend Filter",   group="Indicator Toggles")
useMACD  = input.bool(true,  "Use MACD Filter",       group="Indicator Toggles")
useStoch = input.bool(true,  "Use Stochastic Filter", group="Indicator Toggles")

rsiLen = input.int(14, "RSI Length",     group="RSI", minval=1)
rsiOB  = input.int(70, "RSI Overbought", group="RSI", minval=50, maxval=100)
rsiOS  = input.int(30, "RSI Oversold",   group="RSI", minval=0,  maxval=50)

maLen = input.int(50, "MA Length", group="MA", minval=1)

macdFast = input.int(12, "Fast",   group="MACD", minval=1)
macdSlow = input.int(26, "Slow",   group="MACD", minval=1)
macdSig  = input.int(9,  "Signal", group="MACD", minval=1)

stochLen  = input.int(14, "Length",     group="Stochastic", minval=1)
stochSmth = input.int(3,  "Smooth K",   group="Stochastic", minval=1)
stochOB   = input.int(80, "Overbought", group="Stochastic", minval=50, maxval=100)
stochOS   = input.int(20, "Oversold",   group="Stochastic", minval=0,  maxval=50)

useStrictCross = input.bool(false, "Strict Same-Bar Cross (MACD + Stoch)", group="Signal Logic")
crossWindow    = input.int(3,      "Recent Cross Window (bars)",           group="Signal Logic", minval=1, maxval=10)
entryStyle     = input.string("Pullback", "Entry Style",
     options=["Pullback","Breakout"], group="Signal Logic")

allowReversal = input.bool(false, "Allow Immediate Reversal (Long↔Short)", group="Reversal Guard")

slMethod    = input.string("ATR", "Stop Loss Method",
     options=["ATR","Fixed Pips"], group="Risk Management")
atrLen      = input.int(14,    "ATR Length",                   group="Risk Management", minval=1)
atrMult     = input.float(1.5, "ATR Multiplier",               group="Risk Management", minval=0.1)
fixedPips   = input.float(10.0,"Fixed Stop (Pips)",            group="Risk Management", minval=0.1)
minStopPips = input.float(3.0, "Minimum Stop Distance (Pips)", group="Risk Management", minval=0.1)
rrRatio     = input.float(2.0, "Reward:Risk Ratio",            group="Risk Management", minval=0.1)

useBreakEven = input.bool(true,  "Enable Break-Even",                group="Break-Even")
beActivateR  = input.float(1.0,  "Activate BE after X × Risk",       group="Break-Even", minval=0.1)
beOffsetPips = input.float(1.0,  "BE Stop Offset (pips past entry)", group="Break-Even", minval=0.0)

useSession   = input.bool(true,           "Enable Session Filter",           group="Session")
sessionInput = input.session("0700-1600", "Trading Session (Exchange Time)", group="Session")

useHTF   = input.bool(false,     "Enable HTF Trend Filter", group="HTF Filter")
htfTF    = input.timeframe("60", "Higher Timeframe",        group="HTF Filter")
htfMALen = input.int(50,         "HTF MA Length",           group="HTF Filter", minval=1)

entryCooldown    = input.int(5,      "Cooldown Bars After Entry", group="Cooldown", minval=0)
useExitCooldown  = input.bool(false, "Enable Exit Cooldown",      group="Cooldown")
exitCooldownBars = input.int(3,      "Cooldown Bars After Exit",  group="Cooldown", minval=0)

useOncePerDir = input.bool(false, "One Trade Per Direction Until Flat", group="Trade Limits")

useAtrFloor  = input.bool(false, "Enable ATR Volatility Floor",  group="ATR Filter")
atrFloorPips = input.float(2.0,  "Minimum ATR (Pips) to Trade", group="ATR Filter", minval=0.1)

// ─────────────────────────────────────────────────────────────────────
// SECTION 2: INDICATOR CALCULATIONS
// ─────────────────────────────────────────────────────────────────────

pip = 0.0001

rsi               = ta.rsi(close, rsiLen)
ma                = ta.sma(close, maLen)
[macdL, macdS, _] = ta.macd(close, macdFast, macdSlow, macdSig)
stochK            = ta.sma(ta.stoch(close, high, low, stochLen), stochSmth)
stochD            = ta.sma(stochK, stochSmth)
atr               = ta.atr(atrLen)

rawSL  = slMethod == "ATR" ? atr * atrMult : fixedPips * pip
slDist = math.max(rawSL, minStopPips * pip)

atrFloorOK = not useAtrFloor or atr >= atrFloorPips * pip

// ─────────────────────────────────────────────────────────────────────
// SECTION 3: HTF FILTER — Non-Repainting
// ─────────────────────────────────────────────────────────────────────

htfClose = request.security(syminfo.tickerid, htfTF, close[1],
     lookahead=barmerge.lookahead_off)
htfMA    = request.security(syminfo.tickerid, htfTF,
     ta.sma(close, htfMALen)[1], lookahead=barmerge.lookahead_off)

htfBull = not useHTF or htfClose > htfMA
htfBear = not useHTF or htfClose < htfMA

// ─────────────────────────────────────────────────────────────────────
// SECTION 4: SESSION FILTER
// ─────────────────────────────────────────────────────────────────────

inSession = not useSession or not na(time(timeframe.period, sessionInput))

// ─────────────────────────────────────────────────────────────────────
// SECTION 5: CROSS DETECTION
// ─────────────────────────────────────────────────────────────────────

macdUp  = ta.crossover(macdL,  macdS)
macdDn  = ta.crossunder(macdL, macdS)
stochUp = ta.crossover(stochK,  stochD)
stochDn = ta.crossunder(stochK, stochD)

macdRecentUp  = false
macdRecentDn  = false
stochRecentUp = false
stochRecentDn = false

for i = 0 to crossWindow - 1
    if macdUp[i]
        macdRecentUp  := true
    if macdDn[i]
        macdRecentDn  := true
    if stochUp[i]
        stochRecentUp := true
    if stochDn[i]
        stochRecentDn := true

macdBull  = useStrictCross ? macdUp  : macdRecentUp
macdBear  = useStrictCross ? macdDn  : macdRecentDn
stochBull = useStrictCross ? stochUp : stochRecentUp
stochBear = useStrictCross ? stochDn : stochRecentDn

// ─────────────────────────────────────────────────────────────────────
// SECTION 6: ENTRY CONDITIONS
// ─────────────────────────────────────────────────────────────────────

rsiLong_pb   = not useRSI   or (rsi > rsiOS and rsi < 55)
rsiLong_bo   = not useRSI   or rsi > 50
maLong       = not useMA    or close > ma
macdLong     = not useMACD  or macdBull
stochLong_pb = not useStoch or (stochBull and stochK < 60)
stochLong_bo = not useStoch or (stochK > 50 and stochK > stochD)

longCond = entryStyle == "Pullback"
     ? (maLong and macdLong and rsiLong_pb  and stochLong_pb)
     : (maLong and macdLong and rsiLong_bo  and stochLong_bo)

rsiShort_pb   = not useRSI   or (rsi < rsiOB and rsi > 45)
rsiShort_bo   = not useRSI   or rsi < 50
maShort       = not useMA    or close < ma
macdShort     = not useMACD  or macdBear
stochShort_pb = not useStoch or (stochBear and stochK > 40)
stochShort_bo = not useStoch or (stochK < 50 and stochK < stochD)

shortCond = entryStyle == "Pullback"
     ? (maShort and macdShort and rsiShort_pb and stochShort_pb)
     : (maShort and macdShort and rsiShort_bo and stochShort_bo)

// ─────────────────────────────────────────────────────────────────────
// SECTION 7: POSITION TRANSITION DETECTION
// ─────────────────────────────────────────────────────────────────────

isNewLong  = strategy.position_size > 0  and strategy.position_size[1] <= 0
isNewShort = strategy.position_size < 0  and strategy.position_size[1] >= 0
isNewFlat  = strategy.position_size == 0 and strategy.position_size[1] != 0

// ─────────────────────────────────────────────────────────────────────
// SECTION 8: COOLDOWN TRACKING
// ─────────────────────────────────────────────────────────────────────

var int entryBarIdx = -9999
var int exitBarIdx  = -9999

if isNewLong or isNewShort
    entryBarIdx := bar_index

if isNewFlat
    exitBarIdx := bar_index

entryCooldownOK = (bar_index - entryBarIdx) >= entryCooldown
exitCooldownOK  = not useExitCooldown or (bar_index - exitBarIdx) >= exitCooldownBars
cooldownOK      = entryCooldownOK and exitCooldownOK

// ─────────────────────────────────────────────────────────────────────
// SECTION 9: REVERSAL GUARD
// ─────────────────────────────────────────────────────────────────────

var int flatSinceBar = -9999

if isNewFlat
    flatSinceBar := bar_index

flatLongEnough = (bar_index - flatSinceBar) >= 1

canGoLong  = allowReversal
     ? strategy.position_size <= 0
     : (strategy.position_size == 0 and flatLongEnough)

canGoShort = allowReversal
     ? strategy.position_size >= 0
     : (strategy.position_size == 0 and flatLongEnough)

// ─────────────────────────────────────────────────────────────────────
// SECTION 10: ONE TRADE PER DIRECTION UNTIL FLAT
// ─────────────────────────────────────────────────────────────────────

var bool longUsed  = false
var bool shortUsed = false

if isNewLong
    longUsed  := true

if isNewShort
    shortUsed := true

if isNewFlat
    longUsed  := false
    shortUsed := false

onceLongOK  = not useOncePerDir or not longUsed
onceShortOK = not useOncePerDir or not shortUsed

// ─────────────────────────────────────────────────────────────────────
// SECTION 11: FINAL SIGNAL GATE
// ─────────────────────────────────────────────────────────────────────

confirmed = barstate.isconfirmed

buySignal  = confirmed and inSession and cooldownOK and canGoLong and onceLongOK and htfBull and atrFloorOK and longCond
sellSignal = confirmed and inSession and cooldownOK and canGoShort and onceShortOK and htfBear and atrFloorOK and shortCond

// ─────────────────────────────────────────────────────────────────────
// SECTION 12: LOCK STOP DISTANCE AT SIGNAL BAR
// ─────────────────────────────────────────────────────────────────────

var float signalSlDist = na

if buySignal or sellSignal
    signalSlDist := slDist

estLongSL  = close - signalSlDist
estLongTP  = close + signalSlDist * rrRatio
estShortSL = close + signalSlDist
estShortTP = close - signalSlDist * rrRatio

// ─────────────────────────────────────────────────────────────────────
// SECTION 13: STRATEGY ENTRIES
// ─────────────────────────────────────────────────────────────────────

if buySignal
    strategy.entry("Long",  strategy.long)

if sellSignal
    strategy.entry("Short", strategy.short)

// ─────────────────────────────────────────────────────────────────────
// SECTION 14: LOCKED TRADE STATE & ACTIVE EXIT MANAGEMENT
// ─────────────────────────────────────────────────────────────────────

var float lockedEntry   = na
var float lockedRisk    = na
var float lockedTP      = na
var float longActiveSL  = na
var float shortActiveSL = na
var bool  inTrade       = false

if isNewLong
    lockedEntry   := strategy.position_avg_price
    lockedRisk    := signalSlDist
    lockedTP      := strategy.position_avg_price + signalSlDist * rrRatio
    longActiveSL  := strategy.position_avg_price - signalSlDist
    shortActiveSL := na
    inTrade       := true

if isNewShort
    lockedEntry   := strategy.position_avg_price
    lockedRisk    := signalSlDist
    lockedTP      := strategy.position_avg_price - signalSlDist * rrRatio
    shortActiveSL := strategy.position_avg_price + signalSlDist
    longActiveSL  := na
    inTrade       := true

if isNewFlat
    lockedEntry   := na
    lockedRisk    := na
    lockedTP      := na
    longActiveSL  := na
    shortActiveSL := na
    inTrade       := false

var bool beDone = false

if isNewLong or isNewShort
    beDone := false

if isNewFlat
    beDone := false

beOffset = beOffsetPips * pip

if useBreakEven and not beDone and not na(lockedEntry)
    if strategy.position_size > 0 and high >= lockedEntry + lockedRisk * beActivateR
        longActiveSL := lockedEntry + beOffset
        beDone       := true

    if strategy.position_size < 0 and low <= lockedEntry - lockedRisk * beActivateR
        shortActiveSL := lockedEntry - beOffset
        beDone        := true

if strategy.position_size > 0 and not na(longActiveSL)
    strategy.exit("Long Exit",  from_entry="Long", stop=longActiveSL,  limit=lockedTP)

if strategy.position_size < 0 and not na(shortActiveSL)
    strategy.exit("Short Exit", from_entry="Short", stop=shortActiveSL, limit=lockedTP)

// ─────────────────────────────────────────────────────────────────────
// SECTION 15: VISUAL PLOTTING
// ─────────────────────────────────────────────────────────────────────

plot(ma, "MA", color=color.rgb(0, 255, 255), linewidth=2)
plot(useHTF ? htfMA : na, "HTF MA",
     color=color.rgb(255, 165, 0), linewidth=1, style=plot.style_stepline)

plotshape(series=buySignal,
     title="Buy",
     location=location.belowbar,
     style=shape.triangleup,
     color=color.rgb(0, 255, 255),
     size=size.small)

plotshape(series=sellSignal,
     title="Sell",
     location=location.abovebar,
     style=shape.triangledown,
     color=color.rgb(255, 0, 255),
     size=size.small)

var line ln_e = na
var line ln_s = na
var line ln_t = na

if buySignal
    line.delete(ln_e)
    line.delete(ln_s)
    line.delete(ln_t)
    ln_e := line.new(bar_index, close,     bar_index + 20, close,
         color=color.white,            width=1, style=line.style_dashed)
    ln_s := line.new(bar_index, estLongSL, bar_index + 20, estLongSL,
         color=color.rgb(255, 60, 60), width=1, style=line.style_dashed)
    ln_t := line.new(bar_index, estLongTP, bar_index + 20, estLongTP,
         color=color.rgb(60, 255, 60), width=1, style=line.style_dashed)

if sellSignal
    line.delete(ln_e)
    line.delete(ln_s)
    line.delete(ln_t)
    ln_e := line.new(bar_index, close,      bar_index + 20, close,
         color=color.white,            width=1, style=line.style_dashed)
    ln_s := line.new(bar_index, estShortSL, bar_index + 20, estShortSL,
         color=color.rgb(255, 60, 60), width=1, style=line.style_dashed)
    ln_t := line.new(bar_index, estShortTP, bar_index + 20, estShortTP,
         color=color.rgb(60, 255, 60), width=1, style=line.style_dashed)

if strategy.position_size > 0 and not na(lockedEntry)
    if not na(ln_e)
        line.set_y1(ln_e, lockedEntry)
        line.set_y2(ln_e, lockedEntry)
    if not na(ln_s)
        line.set_y1(ln_s, longActiveSL)
        line.set_y2(ln_s, longActiveSL)
    if not na(ln_t)
        line.set_y1(ln_t, lockedTP)
        line.set_y2(ln_t, lockedTP)

if strategy.position_size < 0 and not na(lockedEntry)
    if not na(ln_e)
        line.set_y1(ln_e, lockedEntry)
        line.set_y2(ln_e, lockedEntry)
    if not na(ln_s)
        line.set_y1(ln_s, shortActiveSL)
        line.set_y2(ln_s, shortActiveSL)
    if not na(ln_t)
        line.set_y1(ln_t, lockedTP)
        line.set_y2(ln_t, lockedTP)

// ─────────────────────────────────────────────────────────────────────
// SECTION 16: ALERTS
// ─────────────────────────────────────────────────────────────────────

if buySignal
    alert(
         '{"action":"buy"' +
         ',"symbol":"EUR_USD"' +
         ',"price":'    + str.tostring(close,        "#.#####") +
         ',"sl":'       + str.tostring(estLongSL,    "#.#####") +
         ',"tp":'       + str.tostring(estLongTP,    "#.#####") +
         ',"sl_dist":'  + str.tostring(signalSlDist, "#.#####") +
         ',"bar_time":' + str.tostring(time) +
         '}',
         alert.freq_once_per_bar_close)

if sellSignal
    alert(
         '{"action":"sell"' +
         ',"symbol":"EUR_USD"' +
         ',"price":'    + str.tostring(close,        "#.#####") +
         ',"sl":'       + str.tostring(estShortSL,   "#.#####") +
         ',"tp":'       + str.tostring(estShortTP,   "#.#####") +
         ',"sl_dist":'  + str.tostring(signalSlDist, "#.#####") +
         ',"bar_time":' + str.tostring(time) +
         '}',
         alert.freq_once_per_bar_close)
