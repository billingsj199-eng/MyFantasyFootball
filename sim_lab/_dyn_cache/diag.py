import runpy, sys
sys.argv=['x']
src=open('backtest_dynasty_sim.py',encoding='utf-8').read()
src=src.replace("    print('\n=== A.", "    DIAG(adp_pool, preds, players)\n    return\n    print('\n=== A.",1)
def DIAG(pool, preds, players):
    for Y in (2018, 2021):
        yr=[r for r in pool if r['Y']==Y]
        yr.sort(key=lambda r:-sum(preds[(id(r),0.4)][:3]))
        print(f'--- {Y} SIM top 30')
        for r in yr[:30]:
            p=preds[(id(r),0.4)]
            print(f"{r['key'][0][:22]:<23}{r['pos']:<3} age{r['age0']} rk{int(r['rookie'])} base{r.get('base',0):5.1f} adp{r['adp']:6.1f} sim3 {sum(p[:3]):6.1f} [{', '.join(f'{x:.0f}' for x in p[:3])}] true3 {sum(v or 0 for v in r['vor'][:3]):6.1f}")
g={'DIAG':DIAG,'__name__':'__main__','__file__':r'E:/MyFantasyFootball/sim_lab/backtest_dynasty_sim.py'}
exec(compile(src,'bt','exec'),g)
