#!/usr/bin/env bash
# 2026-10-20 extended backtest: build the walk-forward inputs for the CURRENT SIM_BT_* environment into sim_lab/_bt_ext/
#   SIM_BT_YEARS=2012-2025 bash bt_ext_build.sh        (main extended build: Clay-free pool, team per game)
#   SIM_BT_TEAMFIX=1 bash bt_ext_build.sh              (2019-25 Clay pool with the team fix)
# Steps: opportunity prior (opp_prior_preds) -> context features -> live layers (pool_mult). Default files never written.
set -e
cd "$(dirname "$0")"
export TMP='E:\MyFantasyFootball\_bt_tmp' TEMP='E:\MyFantasyFootball\_bt_tmp'
PY=${PY:-python}
$PY -c "import bt_ext as b; assert b.EXT, 'bt_ext_build.sh only runs in extended mode (set SIM_BT_YEARS / SIM_BT_POOL / SIM_BT_TEAMFIX)'; print('extended build:', b.describe(), b.TAG)"
$PY backtest_opp_prior.py > /dev/null
$PY build_context_features.py | tail -3
$PY build_live_layers.py | tail -2
