import importlib.util
import sys
from pathlib import Path
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from data import complete_sessions,aggregate_five,connect,init_catalog,ingest_csvs
from engine import Config,features,signals,replay,TRADE_COLUMNS,experiments
from report import metrics,period_tables


def candles(days=25):
    rng=np.random.default_rng(42)
    dates=pd.bdate_range('2025-01-02',periods=days,tz='Asia/Kolkata')
    stamps=np.concatenate([(d+pd.Timedelta(hours=9,minutes=15)+pd.to_timedelta(np.arange(375),unit='m')).as_unit('s').asi8 for d in dates])
    close=100+np.cumsum(rng.normal(0,.03,len(stamps)))
    return pd.DataFrame({'timestamp':stamps,'open':close-.01,'high':close+.04,'low':close-.04,'close':close,'volume':100.})


def test_complete_sessions_reject_gaps_duplicates_invalid():
    d=candles(3)
    d=d.drop(index=50)
    d.loc[400,'low']=999
    cleaned,report=complete_sessions(d)
    assert len(cleaned)==375
    assert report.valid_session.tolist()==[False,False,True]
    clean,_=complete_sessions(pd.concat([candles(1),candles(1).iloc[:1]]))
    assert clean.empty


def test_five_minute_alignment():
    d=candles(1);a=aggregate_five(d)
    assert len(a)==75
    assert a.open.iloc[0]==d.open.iloc[0]
    assert a.high.iloc[0]==d.high.iloc[:5].max()
    assert a.close.iloc[0]==d.close.iloc[4]
    assert a.volume.iloc[0]==500
    assert (a.timestamp.iloc[0]//60+330)%1440==555


def test_original_indicator_parity():
    path=Path(__file__).parents[1]/'stratagies/ha_bb_vwap_strategy_astra.py'
    spec=importlib.util.spec_from_file_location('reference_strategy',path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    raw=candles();five=aggregate_five(raw)
    original=five.copy();original['symbol']='TEST'
    original['timestamp']=pd.to_datetime(original.timestamp,unit='s',utc=True).dt.tz_convert('Asia/Kolkata')
    expected=module.indicators(original,module.Config())
    actual=features(raw,5)
    for col in ['ha_open','ha_high','ha_low','ha_close','bb_middle','bb_upper','bb_lower','vwap','rvol']:
        np.testing.assert_allclose(actual[col],expected[col],equal_nan=True,rtol=1e-10,atol=1e-10)
    np.testing.assert_array_equal(signals(actual,Config(rollover='fresh'))==1,expected.signal)


def test_default_requires_fresh_cross_continuation_is_separate():
    frame=pd.DataFrame({'ha_open':[98.,100.,102.], 'ha_low':[98.,100.,102.],
                        'ha_high':[100.,104.,106.], 'ha_close':[99.,103.,105.],
                        'bb_upper':[101.,102.,103.], 'bb_lower':[95.,95.,95.],
                        'vwap':[98.,99.,100.], 'rvol':[3.,3.,3.]})
    np.testing.assert_array_equal(signals(frame,Config()),[0,1,0])
    np.testing.assert_array_equal(signals(frame,experiments()['rolling_continuation']),[0,1,1])


def engineered(direction=1):
    d=candles(1)
    n=len(d)
    prices=np.tile([100.,100.,100.,100.,99.],(n,1))
    sig=np.zeros(n,dtype=np.int8)
    levels=np.tile([101.,99.,99.,101.],(n,1))
    for s in [5,10,15,20]:
        sig[s]=direction
        if direction==1:
            prices[s+1]=[100.,101.5,100.,101.2,99.]
            prices[s+2]=[104.,110.,103.,105.,99.]
        else:
            prices[s+1]=[100.,100.,98.5,98.8,101.]
            prices[s,4]=101.
            prices[s+2]=[96.,97.,90.,95.,101.]
    return d.timestamp.to_numpy(),prices,sig,levels


@pytest.mark.parametrize('direction',[1,-1])
def test_intrabar_entries_reentry_and_no_three_trade_limit(direction):
    stamps,prices,sig,levels=engineered(direction)
    t,curve,occupied,fees=replay(stamps,prices,sig,levels,1,100000.,.01,.0005,0.,2.,920,False)
    assert len(t)==4
    first=t[0]
    assert first[1]==6 and first[2]==7
    assert first[7]==int(100000//first[4])
    assert curve[-1]==pytest.approx(sum(x[12] for x in t))
    assert fees[-1]==pytest.approx(sum(x[10]+x[11] for x in t))
    assert occupied.max()<=100000


def test_vwap_uses_completed_bar_only_and_no_next_day_signal():
    stamps,p,s,l=engineered()
    p[:,4]=200.
    t,*_=replay(stamps,p,s,l,1,100000.,.01,0.,0.,2.,920,False)
    assert not t


def test_stop_first_and_target_first_sensitivity():
    stamps,p,s,l=engineered()
    p[7]=[102.,110.,95.,102.,99.]
    conservative=replay(stamps,p,s,l,1,100000.,.01,0.,0.,2.,920,False)[0]
    alternate=replay(stamps,p,s,l,1,100000.,.01,0.,0.,2.,920,True)[0]
    assert conservative[0][13]==1 and alternate[0][13]==2
    assert conservative[0][14]==1
    assert conservative[0][12]<alternate[0][12]


def test_causal_features_unchanged_by_future_prices():
    raw=candles();a=features(raw,1)
    changed=raw.copy();changed.loc[8500:,'close']+=10
    b=features(changed,1)
    for col in ['ha_close','bb_upper','vwap','rvol']:
        np.testing.assert_allclose(a[col].iloc[:8500],b[col].iloc[:8500],equal_nan=True)


def test_catalog_idempotent_and_synthetic_not_raw(tmp_path):
    source=tmp_path/'inputs';source.mkdir()
    d=candles(1);d['symbol']='TEST';d.to_csv(source/'TEST.csv',index=False)
    d.to_csv(source/'TEST_heikin_ashi.csv',index=False)
    with connect(tmp_path/'research.duckdb') as c:
        init_catalog(c)
        ingest_csvs(c,[source]);ingest_csvs(c,[source])
        assert c.execute('SELECT count(*) FROM source_files').fetchone()[0]==2
        assert c.execute('SELECT count(*) FROM csv_rows').fetchone()[0]==750
        assert c.execute('SELECT count(*) FROM csv_ohlcv').fetchone()[0]==375


def test_period_profit_reconciliation():
    stamps,p,s,l=engineered()
    t,curve,occupied,fees=replay(stamps,p,s,l,1,100000.,.01,.0005,0.,2.,920,False)
    trades=pd.DataFrame(t,columns=TRADE_COLUMNS)
    trades['side']=trades.side.map({1:'LONG',-1:'SHORT'})
    for name in ['entry','exit']:
        trades[name+'_timestamp']=stamps[trades[name+'_index'].astype(int)]
    periods=period_tables(stamps,curve,trades,100000)
    assert periods.query("period_type=='month'").net_pnl.sum()==pytest.approx(trades.net_pnl.sum())
    assert periods.query("period_type=='ten_year'").partial_window.all()
