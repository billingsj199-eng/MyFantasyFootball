# -*- coding: utf-8 -*-
"""Shared team folder layout for the hand-picked legend headshots
(E:/Sports/All Time Players/<AFC|NFC>/<Division>/<Nickname>)."""
import os
import re

ROOT_DIR = os.environ.get('MFF_ALL_TIME_PLAYERS', r'E:\Sports\All Time Players')

# site abbreviation -> (conference, division, folder nickname)
TEAM_FOLDERS = {
    'BUF': ('AFC', 'East', 'Bills'), 'MIA': ('AFC', 'East', 'Dolphins'),
    'NE': ('AFC', 'East', 'Patriots'), 'NYJ': ('AFC', 'East', 'Jets'),
    'BAL': ('AFC', 'North', 'Ravens'), 'CIN': ('AFC', 'North', 'Bengals'),
    'CLE': ('AFC', 'North', 'Browns'), 'PIT': ('AFC', 'North', 'Steelers'),
    'HOU': ('AFC', 'South', 'Texans'), 'IND': ('AFC', 'South', 'Colts'),
    'JAX': ('AFC', 'South', 'Jaguars'), 'TEN': ('AFC', 'South', 'Titans'),
    'DEN': ('AFC', 'West', 'Broncos'), 'KC': ('AFC', 'West', 'Chiefs'),
    'LV': ('AFC', 'West', 'Raiders'), 'LAC': ('AFC', 'West', 'Chargers'),
    'DAL': ('NFC', 'East', 'Cowboys'), 'NYG': ('NFC', 'East', 'Giants'),
    'PHI': ('NFC', 'East', 'Eagles'), 'WAS': ('NFC', 'East', 'Commanders'),
    'CHI': ('NFC', 'North', 'Bears'), 'DET': ('NFC', 'North', 'Lions'),
    'GB': ('NFC', 'North', 'Packers'), 'MIN': ('NFC', 'North', 'Vikings'),
    'ATL': ('NFC', 'South', 'Falcons'), 'CAR': ('NFC', 'South', 'Panthers'),
    'NO': ('NFC', 'South', 'Saints'), 'TB': ('NFC', 'South', 'Bucs'),
    'ARI': ('NFC', 'West', 'Cardinals'), 'LAR': ('NFC', 'West', 'Rams'),
    'SF': ('NFC', 'West', '49ers'), 'SEA': ('NFC', 'West', 'Seahawks'),
}
# folder nickname (lower) -> abbreviation, with the spellings people actually use
FOLDER_TO_TEAM = {v[2].lower(): k for k, v in TEAM_FOLDERS.items()}
FOLDER_TO_TEAM.update({'buccaneers': 'TB', 'washington': 'WAS', 'redskins': 'WAS',
                       'niners': 'SF', 'oilers': 'TEN', 'raiders': 'LV'})


def team_folder(abbr):
    t = TEAM_FOLDERS.get(abbr)
    return os.path.join(ROOT_DIR, *t) if t else None


def folder_team(path):
    """Abbreviation for the team folder a file sits in (walks up the path)."""
    for part in reversed(os.path.normpath(path).split(os.sep)):
        k = FOLDER_TO_TEAM.get(part.strip().lower())
        if k:
            return k
    return None


def slug(name):
    s = re.sub(r"[^a-z0-9]+", '-', name.lower()).strip('-')
    return s or 'player'
