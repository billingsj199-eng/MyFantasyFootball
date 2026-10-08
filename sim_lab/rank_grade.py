"""Shared rank grader (Jack's in-season objective: weekly within-position rank order, top 150).
rank_stats(pred, mask, target, year, wk, pos) -> (mean Spearman over (year, week, position) groups of 8+ rows, % of pairs ordered right)
"""
from collections import defaultdict
import numpy as np
from scipy.stats import rankdata


def rank_stats(p, m, T, year, wk, pos):
    groups = defaultdict(list)
    for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    rh, pw, tot = [], 0, 0
    for ix in (np.array(x) for x in groups.values()):
        if len(ix) < 8: continue
        a, pv = T[ix], p[ix]
        if np.std(a) == 0 or np.std(pv) == 0: continue
        rh.append(np.corrcoef(rankdata(a), rankdata(pv))[0, 1])
        d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); okp = (d[iu] != 0) & (o[iu] != 0)
        pw += int(((d[iu] > 0) == (o[iu] > 0))[okp].sum()); tot += int(okp.sum())
    return (float(np.mean(rh)) if rh else np.nan), 100.0 * pw / max(1, tot)


def rank_line(preds, m, T, year, wk, pos, off="off"):
    """one-line delta vs preds[off] for every other variant"""
    r0, p0 = rank_stats(preds[off], m, T, year, wk, pos)
    return f"rank vs {off} (rho {r0:.4f}, pairs {p0:.2f}%): " + "  ".join(f"{k}: rho {rank_stats(preds[k], m, T, year, wk, pos)[0] - r0:+.4f} pairs {rank_stats(preds[k], m, T, year, wk, pos)[1] - p0:+.2f}" for k in preds if k != off)


def rank_seasons(p, b0, m, T, year, wk, pos, years):
    """seasons where the variant's rank rho beats the base"""
    return sum(1 for y in years if (m & (year == y)).sum() >= 8 and rank_stats(p, m & (year == y), T, year, wk, pos)[0] > rank_stats(b0, m & (year == y), T, year, wk, pos)[0] + 1e-12)
