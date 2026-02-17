import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from dotenv import load_dotenv


TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
}


@dataclass
class Config:
    login: int
    password: str
    server: str
    path: Optional[str]
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    bars: int = 500
    risk_per_trade: float = 0.005
    daily_max_loss_r: float = 3.0
    max_positions: int = 1
    dry_run: bool = True
    magic: int = 550051
    poll_seconds: int = 5
    slippage_points: int = 30

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        return cls(
            login=int(os.getenv("MT5_LOGIN", "0")),
            password=os.getenv("MT5_PASSWORD", ""),
            server=os.getenv("MT5_SERVER", ""),
            path=os.getenv("MT5_PATH"),
            symbol=os.getenv("SYMBOL", "XAUUSD"),
            timeframe=os.getenv("TIMEFRAME", "M5"),
            risk_per_trade=float(os.getenv("RISK_PER_TRADE", "0.005")),
            daily_max_loss_r=float(os.getenv("DAILY_MAX_LOSS_R", "3")),
            max_positions=int(os.getenv("MAX_POSITIONS", "1")),
            dry_run=os.getenv("DRY_RUN", "true").lower() == "true",
            magic=int(os.getenv("MAGIC", "550051")),
            poll_seconds=int(os.getenv("POLL_SECONDS", "5")),
            slippage_points=int(os.getenv("SLIPPAGE_POINTS", "30")),
        )


class MT5Client:
    def __init__(self, config: Config):
        self.config = config

    def connect(self) -> None:
        ok = mt5.initialize(path=self.config.path) if self.config.path else mt5.initialize()
        if not ok:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        authorized = mt5.login(self.config.login, password=self.config.password, server=self.config.server)
        if not authorized:
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
        symbol_info = mt5.symbol_info(self.config.symbol)
        if symbol_info is None:
            raise RuntimeError(f"Symbol {self.config.symbol} not found")
        if not symbol_info.visible:
            if not mt5.symbol_select(self.config.symbol, True):
                raise RuntimeError(f"Cannot select symbol {self.config.symbol}")

    def shutdown(self) -> None:
        mt5.shutdown()

    def bars(self) -> pd.DataFrame:
        timeframe = TIMEFRAME_MAP[self.config.timeframe]
        rates = mt5.copy_rates_from_pos(self.config.symbol, timeframe, 0, self.config.bars)
        if rates is None or len(rates) < 100:
            raise RuntimeError("Not enough bars from MT5")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def positions_total(self) -> int:
        positions = mt5.positions_get(symbol=self.config.symbol)
        return 0 if positions is None else len(positions)

    def account_equity(self) -> float:
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("Cannot read account_info")
        return float(info.equity)

    def latest_tick(self):
        tick = mt5.symbol_info_tick(self.config.symbol)
        if tick is None:
            raise RuntimeError("Cannot read latest tick")
        return tick

    def send_market_order(self, side: str, volume: float, sl: float, tp: float) -> None:
        tick = self.latest_tick()
        order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
        price = tick.ask if side == "buy" else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.config.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": self.config.slippage_points,
            "magic": self.config.magic,
            "comment": "xauusd_m5_regime_bot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"Order failed: {result}")


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).ewm(alpha=1 / length, adjust=False).mean()
    roll_down = pd.Series(down, index=series.index).ewm(alpha=1 / length, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def true_range(df: pd.DataFrame) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(df)
    atr_smooth = tr.ewm(alpha=1 / length, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / length, adjust=False).mean() / atr_smooth
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / length, adjust=False).mean() / atr_smooth
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(alpha=1 / length, adjust=False).mean()


def bollinger(close: pd.Series, length: int = 20, std_dev: float = 2.0):
    mid = close.rolling(length).mean()
    sd = close.rolling(length).std(ddof=0)
    upper = mid + std_dev * sd
    lower = mid - std_dev * sd
    bw = (upper - lower) / mid
    return upper, mid, lower, bw


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema9"] = ema(out["close"], 9)
    out["ema21"] = ema(out["close"], 21)
    out["ema50"] = ema(out["close"], 50)
    out["rsi9"] = rsi(out["close"], 9)
    out["rsi14"] = rsi(out["close"], 14)
    out["atr14"] = atr(out, 14)
    out["adx14"] = adx(out, 14)
    bb_u, bb_m, bb_l, bb_bw = bollinger(out["close"], 20, 2.0)
    out["bb_upper"] = bb_u
    out["bb_mid"] = bb_m
    out["bb_lower"] = bb_l
    out["bb_bw"] = bb_bw
    return out.dropna().reset_index(drop=True)


def detect_regime(row: pd.Series, prev_row: pd.Series, bbw_low_threshold: float) -> str:
    trending = row["adx14"] > 25
    bbw_expanding = row["bb_bw"] > prev_row["bb_bw"]
    bbw_low = row["bb_bw"] <= bbw_low_threshold
    if trending and bbw_expanding:
        return "trend_momentum"
    if trending and not bbw_expanding:
        return "trend_compression"
    if not trending and bbw_low:
        return "range_low_vol"
    return "range_choppy"


def signal_trend_pullback(last: pd.Series) -> Optional[dict]:
    if last["close"] > last["ema50"] and last["ema9"] > last["ema21"] and 50 < last["rsi9"] < 70:
        sl = min(last["low"], last["close"] - last["atr14"])
        tp = last["close"] + 1.5 * (last["close"] - sl)
        return {"side": "buy", "sl": sl, "tp": tp, "name": "trend_pullback"}
    if last["close"] < last["ema50"] and last["ema9"] < last["ema21"] and 30 < last["rsi9"] < 50:
        sl = max(last["high"], last["close"] + last["atr14"])
        tp = last["close"] - 1.5 * (sl - last["close"])
        return {"side": "sell", "sl": sl, "tp": tp, "name": "trend_pullback"}
    return None


def signal_momentum(last: pd.Series, prev: pd.Series) -> Optional[dict]:
    impulse = (last["high"] - last["low"]) >= 1.2 * last["atr14"]
    if not impulse:
        return None
    if last["close"] > prev["close"] and last["ema9"] > last["ema21"] and last["rsi14"] > 50:
        sl = min(prev["low"], last["close"] - last["atr14"])
        tp = last["close"] + 2.0 * (last["close"] - sl)
        return {"side": "buy", "sl": sl, "tp": tp, "name": "momentum"}
    if last["close"] < prev["close"] and last["ema9"] < last["ema21"] and last["rsi14"] < 50:
        sl = max(prev["high"], last["close"] + last["atr14"])
        tp = last["close"] - 2.0 * (sl - last["close"])
        return {"side": "sell", "sl": sl, "tp": tp, "name": "momentum"}
    return None


def signal_breakout(df: pd.DataFrame) -> Optional[dict]:
    window = df.iloc[-20:]
    last = window.iloc[-1]
    squeeze = last["bb_bw"] <= window["bb_bw"].quantile(0.2)
    if not squeeze:
        return None
    high_range = window["high"].max()
    low_range = window["low"].min()
    if last["close"] > high_range - 0.1 * last["atr14"]:
        sl = low_range
        tp = last["close"] + 1.8 * (last["close"] - sl)
        return {"side": "buy", "sl": sl, "tp": tp, "name": "breakout"}
    if last["close"] < low_range + 0.1 * last["atr14"]:
        sl = high_range
        tp = last["close"] - 1.8 * (sl - last["close"])
        return {"side": "sell", "sl": sl, "tp": tp, "name": "breakout"}
    return None


def signal_mean_reversion(last: pd.Series) -> Optional[dict]:
    if last["adx14"] >= 20:
        return None
    if last["close"] < last["bb_lower"] and last["rsi14"] < 30:
        sl = last["close"] - last["atr14"]
        tp = last["bb_mid"]
        return {"side": "buy", "sl": sl, "tp": tp, "name": "mean_reversion"}
    if last["close"] > last["bb_upper"] and last["rsi14"] > 70:
        sl = last["close"] + last["atr14"]
        tp = last["bb_mid"]
        return {"side": "sell", "sl": sl, "tp": tp, "name": "mean_reversion"}
    return None


def compute_volume(client: MT5Client, entry: float, sl: float, cfg: Config) -> float:
    info = mt5.symbol_info(cfg.symbol)
    if info is None:
        raise RuntimeError("symbol_info unavailable")
    equity = client.account_equity()
    risk_cash = equity * cfg.risk_per_trade
    stop_distance = abs(entry - sl)
    if stop_distance <= 0:
        return 0.0
    tick_value = info.trade_tick_value
    tick_size = info.trade_tick_size
    if tick_size <= 0 or tick_value <= 0:
        raise RuntimeError("Invalid tick_size/tick_value from broker")
    value_per_price_unit = tick_value / tick_size
    loss_per_lot = stop_distance * value_per_price_unit
    raw = risk_cash / loss_per_lot
    stepped = np.floor(raw / info.volume_step) * info.volume_step
    volume = float(max(info.volume_min, min(stepped, info.volume_max)))
    return round(volume, 2)


class DailyRiskGuard:
    def __init__(self, max_loss_r: float):
        self.max_loss_r = max_loss_r
        self.day = date.today()
        self.realized_r = 0.0

    def reset_if_needed(self):
        if date.today() != self.day:
            self.day = date.today()
            self.realized_r = 0.0

    def can_trade(self) -> bool:
        self.reset_if_needed()
        return self.realized_r > -self.max_loss_r

    def record_loss_r(self, loss_r: float) -> None:
        self.reset_if_needed()
        self.realized_r -= abs(loss_r)


def choose_signal(df: pd.DataFrame) -> Optional[dict]:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    bbw_low_threshold = df["bb_bw"].iloc[-100:].quantile(0.2)
    regime = detect_regime(last, prev, bbw_low_threshold)

    if regime == "trend_momentum":
        return signal_momentum(last, prev) or signal_trend_pullback(last)
    if regime == "trend_compression":
        return signal_breakout(df)
    if regime == "range_low_vol":
        return signal_mean_reversion(last)
    return None


def run_bot():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    cfg = Config.from_env()
    if cfg.login == 0 or not cfg.password or not cfg.server:
        raise RuntimeError("Missing MT5 credentials in .env")

    client = MT5Client(cfg)
    guard = DailyRiskGuard(cfg.daily_max_loss_r)

    try:
        client.connect()
        logging.info("Connected to MT5 | symbol=%s timeframe=%s", cfg.symbol, cfg.timeframe)

        while True:
            if not guard.can_trade():
                logging.warning("Daily loss limit reached. Sleeping...")
                time.sleep(cfg.poll_seconds)
                continue

            if client.positions_total() >= cfg.max_positions:
                time.sleep(cfg.poll_seconds)
                continue

            df = enrich_indicators(client.bars())
            signal = choose_signal(df)

            if signal is None:
                time.sleep(cfg.poll_seconds)
                continue

            tick = client.latest_tick()
            entry = tick.ask if signal["side"] == "buy" else tick.bid
            volume = compute_volume(client, entry, signal["sl"], cfg)
            if volume <= 0:
                logging.info("Skipped: computed volume <= 0")
                time.sleep(cfg.poll_seconds)
                continue

            msg = (
                f"{signal['name']} | {signal['side']} | entry={entry:.2f} sl={signal['sl']:.2f} "
                f"tp={signal['tp']:.2f} vol={volume:.2f} dry_run={cfg.dry_run}"
            )

            if cfg.dry_run:
                logging.info("DRY_RUN %s", msg)
            else:
                client.send_market_order(signal["side"], volume, signal["sl"], signal["tp"])
                logging.info("EXECUTED %s", msg)

            time.sleep(cfg.poll_seconds)

    finally:
        client.shutdown()


if __name__ == "__main__":
    run_bot()
