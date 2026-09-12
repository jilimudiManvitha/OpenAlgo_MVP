"""V1_buy_1m_HA_BB20x2_VWAP_SL0p1_RR2_TR0_PXnone_SXnone_TXema21_full

See the adjacent Markdown document for the complete rules.
"""

from strategies.ha_bb_vwap_v1 import Config, Strategy

CONFIG = Config(**{'side': 'buy', 'timeframe_minutes': 1, 'sl_buffer': 0.1, 'reward_risk': 2.0, 'trail_fraction': 0.0, 'partial': 'none', 'stop_rule': 'none', 'target_rule': 'ema21_full', 'short_stop_anchor': 'high', 'trail_basis': 'target_distance', 'capital': 100000.0})


def create_strategy(symbol: str, is_fo: bool) -> Strategy:
    return Strategy(symbol=symbol, is_fo=is_fo, config=CONFIG)
