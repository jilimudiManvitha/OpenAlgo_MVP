"""Causal HA/BB/VWAP research engine. Never connects to a trading endpoint."""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from numba import njit

from data import OHLCV, aggregate_five


@dataclass(frozen=True)
class Config:
    allocation: float = 100000.0
    tick: float = 0.01  # Original strategy convention; override from verified instrument metadata.
    fee_bps: float = 5.0  # Illustrative all-in charge per side, NOT verified broker tariffs.
    slippage_bps: float = 5.0
    reward_r: float = 2.0
    volume_days: int = 20
    volume_multiple: float = 2.0
    rollover: str = 'rolling'
    filter_name: str = 'none'
    stop_source: str = 'ha'
    square_off: int = 920  # 15:20 IST, original strategy's liquidation time.
    target_first: bool = False

    def validate(self):
        for value in [self.allocation, self.tick, self.reward_r, self.volume_multiple]:
            if not np.isfinite(value) or value <= 0:
                raise ValueError('allocation, tick, reward and volume multiplier must be positive')
        if self.volume_days < 1 or not 556 <= self.square_off <= 929:
            raise ValueError('invalid volume lookback or square-off')
        if not 0 <= self.fee_bps < 10000 or not 0 <= self.slippage_bps < 10000:
            raise ValueError('invalid costs')
        if self.rollover not in ['rolling', 'fresh'] or self.stop_source not in ['ha', 'real']:
            raise ValueError('invalid signal/stop policy')
        if self.filter_name not in ['none', 'ema50', 'rsi', 'adx20', 'vwap_distance']:
            raise ValueError('unknown research filter')


@njit(cache=True)
def ha_values(raw):
    n = len(raw)
    ha = np.empty((n, 4))
    for i in range(n):
        hc = (raw[i,0]+raw[i,1]+raw[i,2]+raw[i,3])/4
        ho = (raw[i,0]+raw[i,3])/2 if i == 0 else (ha[i-1,0]+ha[i-1,3])/2
        ha[i] = (ho, max(raw[i,1],ho,hc), min(raw[i,2],ho,hc), hc)
    return ha


def features(raw, timeframe, volume_days=20):
    d = aggregate_five(raw) if timeframe == 5 else raw.copy()
    a = d[OHLCV].to_numpy(dtype=float)
    ha = ha_values(a)
    close = pd.Series(ha[:,3])
    mid = close.rolling(20).mean().to_numpy()
    sd = close.rolling(20).std(ddof=0).to_numpy()
    bars = 375 // timeframe
    volumes = a[:,4].reshape(-1,bars)
    cumulative = volumes.cumsum(axis=1).ravel()
    totals = volumes.sum(axis=1)
    baseline = pd.Series(totals).shift().rolling(volume_days).mean().to_numpy()
    rvol = np.divide(cumulative, np.repeat(baseline,bars),
                     out=np.full(len(d),np.nan), where=np.repeat(baseline,bars)>0)
    tpv = (a[:,1]+a[:,2]+a[:,3])/3*a[:,4]
    vwap = np.divide(tpv.reshape(-1,bars).cumsum(axis=1).ravel(), cumulative,
                     out=np.full(len(d),np.nan), where=cumulative>0)
    d[['ha_open','ha_high','ha_low','ha_close']] = ha
    d['bb_middle'], d['bb_upper'], d['bb_lower'] = mid, mid+2*sd, mid-2*sd
    d['vwap'], d['rvol'] = vwap, rvol
    return d


def signals(d, cfg):
    """Completed signal candles only; never use unfinished confirmation HA."""
    tol = np.maximum(1e-8, np.abs(d.ha_open.to_numpy())*1e-10)
    long = ((d.ha_close>d.ha_open) & (abs(d.ha_low-d.ha_open)<=tol)
            & (d.ha_close>d.bb_upper) & (d.ha_close>d.vwap))
    short = ((d.ha_close<d.ha_open) & (abs(d.ha_high-d.ha_open)<=tol)
             & (d.ha_close<d.bb_lower) & (d.ha_close<d.vwap))
    if cfg.rollover == 'fresh':
        long &= d.ha_close.shift() <= d.bb_upper.shift()
        short &= d.ha_close.shift() >= d.bb_lower.shift()
    volume_ok = d.rvol >= cfg.volume_multiple
    long &= volume_ok
    short &= volume_ok
    if cfg.filter_name != 'none':
        from openalgo import ta
        if cfg.filter_name == 'ema50':
            ema = ta.ema(d.close.to_numpy(), 50)
            long &= d.close>ema
            short &= d.close<ema
        elif cfg.filter_name == 'rsi':
            rsi = ta.rsi(d.close.to_numpy(), 14)
            long &= (rsi>=55) & (rsi<=75)
            short &= (rsi<=45) & (rsi>=25)
        elif cfg.filter_name == 'adx20':
            adx = ta.adx(d.high.to_numpy(),d.low.to_numpy(),d.close.to_numpy(),14)
            long &= adx>=20
            short &= adx>=20
        elif cfg.filter_name == 'vwap_distance':
            distance = abs(d.close/d.vwap-1)
            long &= distance<=0.02
            short &= distance<=0.02
    return np.where(long.fillna(False),1,np.where(short.fillna(False),-1,0)).astype(np.int8)


@njit(cache=True)
def tick_up(x,tick):
    return np.ceil(x/tick-1e-9)*tick


@njit(cache=True)
def tick_down(x,tick):
    return np.floor(x/tick+1e-9)*tick


@njit(cache=True)
def replay(stamps, prices, signal, levels, timeframe, allocation, tick, fee, slip,
           reward, square_off, target_first):
    """One position per stock; no daily count cap; conservatively sequenced bars.

    Returns a trade ledger, close-marked cumulative P&L, occupied notional,
    and cumulative paid fees. Occupied notional includes intrabar exits and is
    a conservative simultaneous-capital bound when aggregating OHLC bars.
    """
    n = len(stamps)
    curve, occupied, fees_curve = np.zeros(n),np.zeros(n),np.zeros(n)
    trades = []
    side, quantity, entry_i, sig_i, last_used, last_exit = 0,0,-1,-1,-1,-1
    entry, stop, target, realised, paid, entry_fee, notional = 0.,0.,0.,0.,0.,0.,0.
    for i in range(n):
        stamp = stamps[i]
        minute = (stamp//60+330)%1440
        day = (stamp+19800)//86400
        o,h,l,c = prices[i,0],prices[i,1],prices[i,2],prices[i,3]
        was_active = side != 0
        entered_now = False
        s = i//timeframe-1
        # Mapping assumes validated full regular sessions and exact 5:1 bars.
        if side == 0 and s>=0 and s!=last_used and minute>=560 and minute<square_off:
            signal_end = (s+1)*timeframe
            sig_day = (stamps[s*timeframe]+19800)//86400
            if sig_day==day and signal_end>last_exit and signal[s]!=0:
                direction = signal[s]
                reference = levels[s,0] if direction==1 else levels[s,1]
                # Latest completed execution (1m) candle VWAP is passed in prices[:,4].
                vw = prices[i-1,4] if i>0 else np.nan
                if np.isfinite(vw):
                    trigger = (tick_down(max(reference,vw),tick)+tick if direction==1
                               else tick_up(min(reference,vw),tick)-tick)
                    crossed = h>=trigger if direction==1 else l<=trigger
                    if crossed:
                        base = max(o,trigger) if direction==1 else min(o,trigger)
                        proposed_entry = (tick_up(base*(1+slip),tick) if direction==1
                                          else tick_down(base*(1-slip),tick))
                        proposed_stop = (tick_down(levels[s,2],tick) if direction==1
                                         else tick_up(levels[s,3],tick))
                        risk = direction*(proposed_entry-proposed_stop)
                        q = int(allocation//proposed_entry) if proposed_entry>0 else 0
                        if risk>0 and q>0:
                            side,quantity,entry_i,sig_i = direction,q,i,s
                            entry,stop = proposed_entry,proposed_stop
                            target = (tick_up(entry+reward*risk,tick) if side==1
                                      else tick_down(entry-reward*risk,tick))
                            notional=entry*quantity
                            entry_fee=notional*fee
                            realised-=entry_fee
                            paid+=entry_fee
                            last_used=s
                            entered_now=True
        if side != 0:
            occupied[i]=notional
            exit_price,reason,ambiguous = 0.,0,0
            if was_active and minute>=square_off:
                exit_price=o
                reason=3
            else:
                stop_hit = l<=stop if side==1 else h>=stop
                target_hit = h>=target if side==1 else l<=target
                gap_stop = (o<=stop if side==1 else o>=stop) and not entered_now
                gap_target = (o>=target if side==1 else o<=target) and not entered_now
                # An entry-bar touch may precede entry; flag and stress both policies.
                ambiguous=int((stop_hit and target_hit) or (entered_now and (stop_hit or target_hit)))
                if gap_stop:
                    exit_price,reason=o,1
                elif gap_target:
                    exit_price,reason=target,2
                elif stop_hit and target_hit and target_first:
                    exit_price,reason=target,2
                elif stop_hit:
                    exit_price,reason=stop,1
                elif target_hit:
                    exit_price,reason=target,2
            if reason:
                if reason!=2:
                    exit_price=(max(tick,tick_down(exit_price*(1-slip),tick)) if side==1
                                else tick_up(exit_price*(1+slip),tick))
                gross=side*quantity*(exit_price-entry)
                exit_fee=quantity*exit_price*fee
                realised+=gross-exit_fee
                paid+=exit_fee
                trades.append((float(sig_i*timeframe),float(entry_i),float(i),float(side),
                               entry,stop,target,float(quantity),exit_price,gross,
                               entry_fee,exit_fee,gross-entry_fee-exit_fee,float(reason),
                               float(ambiguous),notional))
                last_exit=i
                side=0
        curve[i]=realised+(side*quantity*(c-entry) if side else 0.)
        fees_curve[i]=paid
    return trades,curve,occupied,fees_curve


TRADE_COLUMNS=['signal_index','entry_index','exit_index','side','entry','stop','target',
               'quantity','exit','gross_pnl','entry_cost','exit_cost','net_pnl','reason_code',
               'ambiguous','entry_notional']


def simulate(raw, prepared, timeframe, cfg):
    cfg.validate()
    stamps=raw.timestamp.to_numpy(dtype=np.int64)
    a=raw[OHLCV[:4]].to_numpy(dtype=float)
    v=raw.volume.to_numpy(dtype=float).reshape(-1,375).cumsum(axis=1).ravel()
    pv=((a[:,1]+a[:,2]+a[:,3])/3*raw.volume.to_numpy()).reshape(-1,375).cumsum(axis=1).ravel()
    vw=np.divide(pv,v,out=np.full(len(raw),np.nan),where=v>0)
    prices=np.column_stack([a,vw])
    low=prepared.ha_low if cfg.stop_source=='ha' else prepared.low
    high=prepared.ha_high if cfg.stop_source=='ha' else prepared.high
    levels=np.column_stack([prepared.ha_high,prepared.ha_low,low,high])
    trades,curve,occupied,fees=replay(stamps,prices,signals(prepared,cfg),levels,timeframe,
                                    cfg.allocation,cfg.tick,cfg.fee_bps/10000,
                                    cfg.slippage_bps/10000,cfg.reward_r,cfg.square_off,cfg.target_first)
    ledger=pd.DataFrame(trades,columns=TRADE_COLUMNS)
    for name in ['signal','entry','exit']:
        indices=ledger[name+'_index'].to_numpy(dtype=int)
        ledger[name+'_timestamp']=stamps[indices]
    ledger['side']=ledger.side.map({1.:'LONG',-1.:'SHORT'})
    ledger['reason']=ledger.reason_code.map({1.:'stop',2.:'target',3.:'square_off'})
    return ledger,curve,occupied,fees


def experiments():
    """Fixed bounded registry; HA, Bollinger and VWAP are never optimized."""
    base=asdict(Config())
    variants={'baseline':Config()}
    for name in ['ema50','rsi','adx20','vwap_distance']:
        variants[name]=Config(**{**base,'filter_name':name})
    variants['target_1_5R']=Config(**{**base,'reward_r':1.5})
    variants['target_3R']=Config(**{**base,'reward_r':3.0})
    variants['fresh_cross']=Config(**{**base,'rollover':'fresh'})
    variants['target_first_sensitivity']=Config(**{**base,'target_first':True})
    variants['double_cost_stress']=Config(**{**base,'fee_bps':10.,'slippage_bps':10.})
    return variants
