"""Polars CSV preparation; pandas boundary preserves the strategy's semantics."""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import polars as pl

TZ = "Asia/Kolkata"
OHLC = ["open", "high", "low", "close"]
COLUMNS = ["timestamp", "symbol", *OHLC, "volume"]


@dataclass
class PreparedCandles:
    candles: pl.DataFrame
    source_bars: int
    source_last_timestamp: str
    exclusions: list[dict]

    def to_strategy(self) -> pd.DataFrame:
        # No Arrow extension dtypes: the existing strategy expects NumPy columns.
        result = pd.DataFrame(self.candles.select(COLUMNS).to_dict(as_series=False))
        result["timestamp"] = pd.to_datetime(result.timestamp).astype(f"datetime64[ns, {TZ}]")
        return result

    def write(self, out: Path):
        self.candles.write_csv(out / "validated_ohlcv.csv")
        pd.DataFrame(self.exclusions, columns=["date", "bars", "first", "last", "reason"]).to_csv(
            out / "excluded_sessions.csv", index=False)


def prepare_historify(csv: Path, symbol: str = "ATHERENERG", now=None) -> PreparedCandles:
    """Validate actual OHLCV and retain complete regular IST sessions.

    Scan and project only required columns. All timestamps are bar opens.
    Full input is materialized for global duplicate/session validation; this is
    not a claim that the whole backtest can process data larger than memory.
    """
    clock = pd.Timestamp.now(tz=TZ) if now is None else pd.Timestamp(now)
    clock = clock.tz_localize(TZ) if clock.tzinfo is None else clock.tz_convert(TZ)
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Empty symbol")
    query = pl.scan_csv(csv, with_column_names=lambda names: [n.strip().lower() for n in names],
                        schema_overrides={"date": pl.String, "time": pl.String,
                                          **{c: pl.Float64 for c in [*OHLC, "volume"]}})
    data = (query.select("date", "time", *OHLC, "volume")
            .with_columns(pl.concat_str("date", "time", separator=" ")
                          .str.to_datetime(time_unit="ns", strict=True)
                          .dt.replace_time_zone(TZ).alias("timestamp"),
                          pl.lit(symbol).alias("symbol"))
            .sort("timestamp").collect())
    if data.is_empty() or any(data.select(COLUMNS).null_count().row(0)):
        raise ValueError("CSV is empty or contains missing fields")
    if data["timestamp"].n_unique() != data.height:
        raise ValueError("Duplicate timestamps in source")
    invalid = (~pl.all_horizontal(pl.col([*OHLC, "volume"]).is_finite())
               | pl.any_horizontal(pl.col(OHLC) <= 0) | (pl.col("volume") < 0)
               | (pl.col("high") < pl.max_horizontal("open", "low", "close"))
               | (pl.col("low") > pl.min_horizontal("open", "high", "close")))
    if data.select(invalid.any()).item():
        raise ValueError("Invalid/non-finite OHLCV or inconsistent OHLC ranges")
    stamp = pl.col("timestamp")
    minute = stamp.dt.hour().cast(pl.Int32) * 60 + stamp.dt.minute().cast(pl.Int32)
    grid = ((minute >= 555) & (minute <= 925) & ((minute - 555) % 5 == 0)
            & (stamp.dt.second() == 0) & (stamp.dt.nanosecond() == 0))
    sessions = (data.with_columns(stamp.dt.date().alias("_session"))
                .group_by("_session").agg(pl.len().alias("bars"),
                  stamp.min().alias("first"), stamp.max().alias("last"),
                  grid.all().alias("on_grid"))
                .with_columns(((pl.col("bars") == 75) & pl.col("on_grid")).alias("complete"),
                  (pl.col("last") + pl.duration(minutes=5) <= pl.lit(clock.to_pydatetime())).alias("finished"))
                .sort("_session"))
    exclusions = []
    for row in sessions.filter(~(pl.col("complete") & pl.col("finished"))).iter_rows(named=True):
        exclusions.append({"date": str(row["_session"]), "bars": row["bars"],
                           "first": str(row["first"]), "last": str(row["last"]),
                           "reason": "Incomplete/non-regular session" if not row["complete"] else "Unfinished bar"})
    days = sessions.filter(pl.col("complete") & pl.col("finished")).select("_session")
    accepted = (data.with_columns(stamp.dt.date().alias("_session"))
                .join(days, on="_session", how="semi").drop("_session").sort("timestamp"))
    if accepted.is_empty():
        raise ValueError("No complete finished regular sessions")
    return PreparedCandles(accepted, data.height, str(data["timestamp"][-1]), exclusions)


def export_heikin_ashi(d: pd.DataFrame, out: Path):
    """Export the exact HA used by the strategy, never reconvert synthetic OHLC."""
    columns = ["symbol", "ha_open", "ha_high", "ha_low", "ha_close", "volume"]
    d[columns].rename(columns={f"ha_{c}": c for c in OHLC}).to_csv(
        out / "ATHERENERG_heikin_ashi_5m.csv", index_label="timestamp")
    d[["symbol", *OHLC, "ha_open", "ha_high", "ha_low", "ha_close", "volume"]].to_csv(
        out / "real_vs_heikin_ashi.csv", index_label="timestamp")


def aggregate_pnl(trades: pd.DataFrame, daily_equity: pd.Series, capital: float):
    """Group the trade ledger in Polars, preserving no-trade sessions and IST dates."""
    ledger = pl.DataFrame({
        "date": trades.exit_time.dt.strftime("%Y-%m-%d").tolist(),
        **{c: trades[c].to_numpy() for c in ["gross_pnl", "costs", "net_pnl"]},
        "reason": trades.reason.tolist(),
    })
    sessions = pl.DataFrame({"date": daily_equity.index.strftime("%Y-%m-%d").tolist(),
                             "closing_equity": daily_equity.to_numpy()})
    grouped = ledger.group_by("date").agg(pl.len().alias("trades"),
        pl.col("gross_pnl").sum(), pl.col("costs").sum().alias("fees"), pl.col("net_pnl").sum())
    daily = (sessions.join(grouped, on="date", how="left").sort("date")
             .with_columns(pl.col("trades", "gross_pnl", "fees", "net_pnl").fill_null(0))
             .with_columns(((pl.col("closing_equity") / pl.col("closing_equity").shift(1).fill_null(capital) - 1) * 100).alias("return_pct")))
    monthly = (daily.with_columns(pl.col("date").str.slice(0,7).alias("month"))
               .group_by("month").agg(pl.col("trades", "gross_pnl", "fees", "net_pnl").sum(),
                                     pl.col("closing_equity").last())
               .sort("month").with_columns((pl.col("net_pnl") / pl.col("closing_equity").shift(1).fill_null(capital) * 100).alias("return_pct")))
    by_exit = ledger.group_by("reason").agg(pl.len().alias("trades"), pl.col("net_pnl").sum()).sort("reason")
    daily_pd = pd.DataFrame(daily.to_dict(as_series=False)).set_index("date")
    daily_pd.index = pd.DatetimeIndex(pd.to_datetime(daily_pd.index)).tz_localize(TZ)
    daily_pd = daily_pd[["trades", "gross_pnl", "fees", "net_pnl", "closing_equity", "return_pct"]]
    return daily_pd, pd.DataFrame(monthly.to_dict(as_series=False)).set_index("month"), pd.DataFrame(by_exit.to_dict(as_series=False)).set_index("reason")
