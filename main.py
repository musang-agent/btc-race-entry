"""Rally rider: a time-boxed 60-bar breakout bot for cbBTC (CBBTC/USDC).

Strategy (original design, written from the dev-window data, not from any
kit baseline):
  - Flat most of the time. Enter long only when the close breaks above the
    highest high of the last 60 one-minute bars AND the 15-bar return is
    above +40 bps: a fresh high with real momentum behind it, not a drift.
  - Buy with all available cash (one position, long only).
  - Exit by selling everything 30 bars after the entry decision, whatever
    the price: the measured edge after a 60-bar breakout lives in the next
    ~30 minutes, and holding longer hands the gain back to the drift.
  - No trailing stop, no take-profit, no second entry while holding.
  - If an order is rejected (e.g. max slippage on a spike), the same
    decision is simply re-evaluated on the next bar.

Costs: a full-size round trip pays ~26-43 bps (4 bps fee + 2 bps slippage
each way, plus constant-product impact vs the bar's pool depth), so the
30-bar hold only pays when the breakout keeps running; the momentum filter
keeps the weak breakouts out. In the dev window this is near-flat in
quarters without a rally and strongly positive in the quarter with one.

Determinism: no randomness, no wall clock, no environment reads. All state
comes from the bars the harness sends. The entry/exit rules depend only on
the received bar history, so two runs on the same data decide identically.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# Entry: breakout lookback (bars) and the momentum filter (bps over 15 bars).
LOOKBACK = 60
MOM_BARS = 15
MOM_BPS = 40
# Exit: bars held after the entry decision.
HOLD_BARS = 30
# Slippage cap on every order, in bps from the latest close (1-minute moves
# rarely exceed 2%; a rejected order is simply retried next bar).
MAX_SLIP_BPS = 200


class RallyRider:
    def __init__(self):
        self.highs = []    # high of each received CBBTC bar, in order
        self.closes = []   # close of each received CBBTC bar, in order
        self.entry_seq = None  # seq of the batch where the buy was decided
        self._last_t = None    # close time of the last bar appended

    def on_batch(self, state, batch):
        if state.warming_up:
            return []
        bar = state.latest.get(SYMBOL)
        if bar is None:
            return []
        # Only append once per new bar (a batch carries the bar that closed;
        # a gap minute re-sends the previous bar via state.latest).
        if bar["t"] != self._last_t:
            self.highs.append(int(bar["h"]))
            self.closes.append(int(bar["c"]))
            self._last_t = bar["t"]

        holding = state.positions.get(SYMBOL)
        qty = holding.qty if holding is not None else 0
        close = int(bar["c"])

        if qty > 0:
            # Exit: 30 bars after the entry decision, sell everything.
            if self.entry_seq is not None and state.seq - self.entry_seq >= HOLD_BARS:
                return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                         "max_slippage_bps": MAX_SLIP_BPS}]
            return []

        # Flat: look for a fresh 60-bar high with momentum behind it.
        if len(self.closes) < LOOKBACK + 1:
            return []
        hi = max(self.highs[-LOOKBACK - 1:-1])
        mom = (close * 10000) // self.closes[-1 - MOM_BARS] - 10000
        if close > hi and mom > MOM_BPS:
            self.entry_seq = state.seq
            # All available cash, capped at the weight room the caps allow
            # (identical when flat: room == cash at a 100% weight cap).
            notional = min(state.cash, state.weight_room(SYMBOL))
            return [{"side": "buy", "symbol": SYMBOL,
                     "notional_quote_units": notional,
                     "max_slippage_bps": MAX_SLIP_BPS}]
        return []


def on_batch(state, batch):
    return _BOT.on_batch(state, batch)


_BOT = RallyRider()

makefun_bars.run(on_batch)
