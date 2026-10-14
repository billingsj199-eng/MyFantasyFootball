"""
early_tgt_share.py — season-to-date TARGET SHARE through week W, built from the site's
weekly game logs (player targets) and nflverse play-by-play (team targets).

Replaces the ctx_features wk-5 row used first in research_wr_bounce_volume.py: that row
only exists when the player played week 5 (bye / absence -> no row -> read as 0%), and
some players are missing from ctx entirely (DJ Chark 2019).

share(key, Y) = player targets in weeks 1..W he played / his team's targets in those
same weeks. Team = his season team from the World career row (weekly 'tm' is blank in
older logs). Team targets = REG pass plays with a receiver (pbp receiver_player_id set).
"""
import json
import os
import re
from collections import defaultdict

import pandas as pd

from dyn_common import _norm_name

SITE_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'MyFantasyFootball Files', 'data')
PBP = r'E:\MyFantasyFootball\pbp_cache'
ALIAS = {'LA': 'LAR', 'OAK': 'LV', 'SD': 'LAC', 'STL': 'LAR', 'WSH': 'WAS', 'JAC': 'JAX'}


def _weekly_logs():
    """{(norm name, pos): {year: {wk: tgt}}} from weekly_stats_active + retired_1..3."""
    out = defaultdict(dict)
    for fn in ('weekly_stats_active.js', 'weekly_stats_retired_1.js', 'weekly_stats_retired_2.js', 'weekly_stats_retired_3.js'):
        p = os.path.join(SITE_DATA, fn)
        if not os.path.exists(p):
            continue
        s = open(p, encoding='utf-8').read()
        d = json.JSONDecoder().raw_decode(s, s.index('{"'))[0]   # '{"' skips the window.X=window.X||{} fallback
        for name, v in d.items():
            if not isinstance(v, dict) or 'seasons' not in v:
                continue
            k = (_norm_name(name), v.get('pos'))
            for yr, games in v['seasons'].items():
                out[k][int(yr)] = {g['wk']: g.get('tgt') for g in games if g.get('wk')}
    return out


def _team_targets(years, W):
    """{(team, year, wk): team targets} for weeks <= W."""
    out = {}
    for Y in years:
        df = pd.read_csv(os.path.join(PBP, f'play_by_play_{Y}.csv.gz'),
                         usecols=['season_type', 'week', 'posteam', 'receiver_player_id', 'play_type'], low_memory=False)
        df = df[(df.season_type == 'REG') & (df.week <= W) & df.receiver_player_id.notna() & (df.play_type == 'pass')]
        for (t, wk), n in df.groupby(['posteam', 'week']).size().items():
            out[(ALIAS.get(t, t), Y, int(wk))] = int(n)
    return out


def build(w, keys_years, W=4):
    """keys_years: iterable of (key, Y). -> {(key, Y): (share or None, games, targets)}."""
    logs = _weekly_logs()
    years = sorted({Y for _, Y in keys_years})
    tt = _team_targets(years, W)
    res = {}
    for key, Y in keys_years:
        row = (w.players.get(key) or {}).get('by', {}).get(Y) or {}
        team = ALIAS.get(row.get('tm') or '', row.get('tm') or '')
        g = logs.get(key, {}).get(Y, {})
        wks = [wk for wk in g if wk <= W and g[wk] is not None]
        pt = sum(g[wk] for wk in wks)
        tot = sum(tt.get((team, Y, wk), 0) for wk in wks)
        res[(key, Y)] = (pt / tot if tot else (0.0 if not wks else None), len(wks), pt)
    return res
