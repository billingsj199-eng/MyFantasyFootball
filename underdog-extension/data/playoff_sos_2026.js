// Pre-computed Playoff SOS (BBM weeks 15-17) per NFL team + position.
// Built from the main site's _mtGetPlayoffSosWeekly() helper.
// v0.10.31: now includes impliedTotal field (team-relative implied points).
// 2026-07-21: regenerated from auto-pulled DK game lines (pull_betting_lines.py)
//   -- 65 spreads/totals moved vs the 2026-05-15 board, ranks/colors reblended.
//
// Structure: MFF_PLAYOFF_SOS[teamAbbr][position][week] =
//   { opp, home, label, color, gameTotal, teamSpread, impliedTotal, rank }
// position in {QB, RB, WR, TE}; week in {15, 16, 17}.

window.MFF_PLAYOFF_SOS = {
  "ARI": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 6,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 44.5,
        "home": false,
        "impliedTotal": 19.5,
        "label": "M",
        "opp": "NO",
        "rank": 21,
        "teamSpread": 5.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "E",
        "opp": "LV",
        "rank": 10,
        "teamSpread": 1.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 8,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 44.5,
        "home": false,
        "impliedTotal": 19.5,
        "label": "H",
        "opp": "NO",
        "rank": 23,
        "teamSpread": 5.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "M",
        "opp": "LV",
        "rank": 12,
        "teamSpread": 1.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 9,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 44.5,
        "home": false,
        "impliedTotal": 19.5,
        "label": "H",
        "opp": "NO",
        "rank": 24,
        "teamSpread": 5.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "E",
        "opp": "LV",
        "rank": 10,
        "teamSpread": 1.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 5,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 44.5,
        "home": false,
        "impliedTotal": 19.5,
        "label": "H",
        "opp": "NO",
        "rank": 23,
        "teamSpread": 5.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "E",
        "opp": "LV",
        "rank": 11,
        "teamSpread": 1.5
      }
    }
  },
  "ATL": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "WAS",
        "rank": 3,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 22,
        "label": "M",
        "opp": "TB",
        "rank": 13,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 44.5,
        "home": true,
        "impliedTotal": 23,
        "label": "M",
        "opp": "NO",
        "rank": 19,
        "teamSpread": -1.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "WAS",
        "rank": 10,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 22,
        "label": "M",
        "opp": "TB",
        "rank": 19,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 44.5,
        "home": true,
        "impliedTotal": 23,
        "label": "M",
        "opp": "NO",
        "rank": 13,
        "teamSpread": -1.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "WAS",
        "rank": 7,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 22,
        "label": "M",
        "opp": "TB",
        "rank": 17,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 44.5,
        "home": true,
        "impliedTotal": 23,
        "label": "M",
        "opp": "NO",
        "rank": 17,
        "teamSpread": -1.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "WAS",
        "rank": 8,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 22,
        "label": "M",
        "opp": "TB",
        "rank": 17,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 44.5,
        "home": true,
        "impliedTotal": 23,
        "label": "M",
        "opp": "NO",
        "rank": 17,
        "teamSpread": -1.5
      }
    }
  },
  "BAL": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "H",
        "opp": "PIT",
        "rank": 26,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 26.75,
        "label": "H",
        "opp": "CLE",
        "rank": 23,
        "teamSpread": -10
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "CIN",
        "rank": 3,
        "teamSpread": 2.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "PIT",
        "rank": 18,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 26.75,
        "label": "M",
        "opp": "CLE",
        "rank": 13,
        "teamSpread": -10
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "CIN",
        "rank": 6,
        "teamSpread": 2.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "PIT",
        "rank": 17,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 26.75,
        "label": "M",
        "opp": "CLE",
        "rank": 16,
        "teamSpread": -10
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "CIN",
        "rank": 4,
        "teamSpread": 2.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "PIT",
        "rank": 21,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 26.75,
        "label": "M",
        "opp": "CLE",
        "rank": 12,
        "teamSpread": -10
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "CIN",
        "rank": 5,
        "teamSpread": 2.5
      }
    }
  },
  "BUF": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27.5,
        "label": "E",
        "opp": "CHI",
        "rank": 9,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24,
        "label": "H",
        "opp": "DEN",
        "rank": 26,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 27.5,
        "label": "E",
        "opp": "MIA",
        "rank": 2,
        "teamSpread": -7.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27.5,
        "label": "E",
        "opp": "CHI",
        "rank": 5,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "DEN",
        "rank": 21,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 27.5,
        "label": "E",
        "opp": "MIA",
        "rank": 1,
        "teamSpread": -7.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27.5,
        "label": "E",
        "opp": "CHI",
        "rank": 11,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24,
        "label": "H",
        "opp": "DEN",
        "rank": 25,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 27.5,
        "label": "E",
        "opp": "MIA",
        "rank": 1,
        "teamSpread": -7.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27.5,
        "label": "E",
        "opp": "CHI",
        "rank": 10,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24,
        "label": "H",
        "opp": "DEN",
        "rank": 24,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 27.5,
        "label": "E",
        "opp": "MIA",
        "rank": 1,
        "teamSpread": -7.5
      }
    }
  },
  "CAR": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "E",
        "opp": "CIN",
        "rank": 4,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 19,
        "label": "H",
        "opp": "PIT",
        "rank": 28,
        "teamSpread": 3.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 18.5,
        "label": "H",
        "opp": "SEA",
        "rank": 32,
        "teamSpread": 5.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "E",
        "opp": "CIN",
        "rank": 6,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 19,
        "label": "H",
        "opp": "PIT",
        "rank": 27,
        "teamSpread": 3.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 18.5,
        "label": "H",
        "opp": "SEA",
        "rank": 32,
        "teamSpread": 5.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "E",
        "opp": "CIN",
        "rank": 3,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 19,
        "label": "H",
        "opp": "PIT",
        "rank": 26,
        "teamSpread": 3.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 18.5,
        "label": "H",
        "opp": "SEA",
        "rank": 32,
        "teamSpread": 5.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "E",
        "opp": "CIN",
        "rank": 3,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 19,
        "label": "H",
        "opp": "PIT",
        "rank": 27,
        "teamSpread": 3.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 18.5,
        "label": "H",
        "opp": "SEA",
        "rank": 32,
        "teamSpread": 5.5
      }
    }
  },
  "CHI": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "BUF",
        "rank": 13,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "GB",
        "rank": 12,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 25.5,
        "label": "M",
        "opp": "DET",
        "rank": 13,
        "teamSpread": -1.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "BUF",
        "rank": 15,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "GB",
        "rank": 10,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 25.5,
        "label": "M",
        "opp": "DET",
        "rank": 16,
        "teamSpread": -1.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "BUF",
        "rank": 13,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "GB",
        "rank": 14,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 25.5,
        "label": "M",
        "opp": "DET",
        "rank": 15,
        "teamSpread": -1.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "BUF",
        "rank": 14,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "GB",
        "rank": 13,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 25.5,
        "label": "M",
        "opp": "DET",
        "rank": 12,
        "teamSpread": -1.5
      }
    }
  },
  "CIN": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 25,
        "label": "M",
        "opp": "CAR",
        "rank": 12,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": false,
        "impliedTotal": 27,
        "label": "E",
        "opp": "IND",
        "rank": 8,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "BAL",
        "rank": 11,
        "teamSpread": -2.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 25,
        "label": "M",
        "opp": "CAR",
        "rank": 13,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": false,
        "impliedTotal": 27,
        "label": "E",
        "opp": "IND",
        "rank": 7,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "BAL",
        "rank": 10,
        "teamSpread": -2.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 25,
        "label": "M",
        "opp": "CAR",
        "rank": 12,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": false,
        "impliedTotal": 27,
        "label": "E",
        "opp": "IND",
        "rank": 7,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27,
        "label": "M",
        "opp": "BAL",
        "rank": 12,
        "teamSpread": -2.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 25,
        "label": "E",
        "opp": "CAR",
        "rank": 11,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": false,
        "impliedTotal": 27,
        "label": "E",
        "opp": "IND",
        "rank": 8,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27,
        "label": "M",
        "opp": "BAL",
        "rank": 13,
        "teamSpread": -2.5
      }
    }
  },
  "CLE": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 40.5,
        "home": false,
        "impliedTotal": 18,
        "label": "M",
        "opp": "NYG",
        "rank": 17,
        "teamSpread": 4.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 16.75,
        "label": "H",
        "opp": "BAL",
        "rank": 24,
        "teamSpread": 10
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "M",
        "opp": "IND",
        "rank": 15,
        "teamSpread": 2.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 40.5,
        "home": false,
        "impliedTotal": 18,
        "label": "M",
        "opp": "NYG",
        "rank": 20,
        "teamSpread": 4.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 16.75,
        "label": "H",
        "opp": "BAL",
        "rank": 30,
        "teamSpread": 10
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "M",
        "opp": "IND",
        "rank": 14,
        "teamSpread": 2.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 40.5,
        "home": false,
        "impliedTotal": 18,
        "label": "M",
        "opp": "NYG",
        "rank": 14,
        "teamSpread": 4.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 16.75,
        "label": "H",
        "opp": "BAL",
        "rank": 28,
        "teamSpread": 10
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "M",
        "opp": "IND",
        "rank": 13,
        "teamSpread": 2.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 40.5,
        "home": false,
        "impliedTotal": 18,
        "label": "M",
        "opp": "NYG",
        "rank": 13,
        "teamSpread": 4.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 16.75,
        "label": "H",
        "opp": "BAL",
        "rank": 28,
        "teamSpread": 10
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "M",
        "opp": "IND",
        "rank": 18,
        "teamSpread": 2.5
      }
    }
  },
  "DAL": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 52.5,
        "home": false,
        "impliedTotal": 23.25,
        "label": "H",
        "opp": "LAR",
        "rank": 27,
        "teamSpread": 6
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27.25,
        "label": "M",
        "opp": "JAX",
        "rank": 19,
        "teamSpread": -3
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "NYG",
        "rank": 7,
        "teamSpread": -4.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 52.5,
        "home": false,
        "impliedTotal": 23.25,
        "label": "H",
        "opp": "LAR",
        "rank": 27,
        "teamSpread": 6
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27.25,
        "label": "M",
        "opp": "JAX",
        "rank": 15,
        "teamSpread": -3
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "NYG",
        "rank": 3,
        "teamSpread": -4.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 52.5,
        "home": false,
        "impliedTotal": 23.25,
        "label": "H",
        "opp": "LAR",
        "rank": 28,
        "teamSpread": 6
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27.25,
        "label": "M",
        "opp": "JAX",
        "rank": 13,
        "teamSpread": -3
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "NYG",
        "rank": 3,
        "teamSpread": -4.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 52.5,
        "home": false,
        "impliedTotal": 23.25,
        "label": "H",
        "opp": "LAR",
        "rank": 28,
        "teamSpread": 6
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 51.5,
        "home": true,
        "impliedTotal": 27.25,
        "label": "M",
        "opp": "JAX",
        "rank": 14,
        "teamSpread": -3
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "NYG",
        "rank": 3,
        "teamSpread": -4.5
      }
    }
  },
  "DEN": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 23,
        "label": "E",
        "opp": "LV",
        "rank": 8,
        "teamSpread": -4.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "BUF",
        "rank": 17,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20,
        "label": "H",
        "opp": "NE",
        "rank": 30,
        "teamSpread": 2.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 23,
        "label": "E",
        "opp": "LV",
        "rank": 3,
        "teamSpread": -4.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "BUF",
        "rank": 17,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20,
        "label": "H",
        "opp": "NE",
        "rank": 30,
        "teamSpread": 2.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 23,
        "label": "E",
        "opp": "LV",
        "rank": 4,
        "teamSpread": -4.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "BUF",
        "rank": 12,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20,
        "label": "H",
        "opp": "NE",
        "rank": 31,
        "teamSpread": 2.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 23,
        "label": "E",
        "opp": "LV",
        "rank": 7,
        "teamSpread": -4.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "BUF",
        "rank": 16,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20,
        "label": "H",
        "opp": "NE",
        "rank": 30,
        "teamSpread": 2.5
      }
    }
  },
  "DET": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24,
        "label": "H",
        "opp": "MIN",
        "rank": 22,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "NYG",
        "rank": 7,
        "teamSpread": -4.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "CHI",
        "rank": 12,
        "teamSpread": 1.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "MIN",
        "rank": 17,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "NYG",
        "rank": 4,
        "teamSpread": -4.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "CHI",
        "rank": 15,
        "teamSpread": 1.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "MIN",
        "rank": 18,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "NYG",
        "rank": 2,
        "teamSpread": -4.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "CHI",
        "rank": 16,
        "teamSpread": 1.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "MIN",
        "rank": 17,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": true,
        "impliedTotal": 27,
        "label": "E",
        "opp": "NYG",
        "rank": 3,
        "teamSpread": -4.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "CHI",
        "rank": 15,
        "teamSpread": 1.5
      }
    }
  },
  "GB": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 28,
        "label": "E",
        "opp": "MIA",
        "rank": 2,
        "teamSpread": -10.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 23,
        "label": "M",
        "opp": "CHI",
        "rank": 14,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "HOU",
        "rank": 31,
        "teamSpread": -2.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 28,
        "label": "E",
        "opp": "MIA",
        "rank": 2,
        "teamSpread": -10.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 23,
        "label": "M",
        "opp": "CHI",
        "rank": 18,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "HOU",
        "rank": 27,
        "teamSpread": -2.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 28,
        "label": "E",
        "opp": "MIA",
        "rank": 2,
        "teamSpread": -10.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 23,
        "label": "M",
        "opp": "CHI",
        "rank": 19,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "HOU",
        "rank": 30,
        "teamSpread": -2.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 28,
        "label": "E",
        "opp": "MIA",
        "rank": 2,
        "teamSpread": -10.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 23,
        "label": "M",
        "opp": "CHI",
        "rank": 19,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "HOU",
        "rank": 31,
        "teamSpread": -2.5
      }
    }
  },
  "HOU": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 23.25,
        "label": "H",
        "opp": "JAX",
        "rank": 24,
        "teamSpread": -3
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 37.5,
        "home": false,
        "impliedTotal": 17.5,
        "label": "H",
        "opp": "PHI",
        "rank": 31,
        "teamSpread": 2.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20,
        "label": "M",
        "opp": "GB",
        "rank": 21,
        "teamSpread": 2.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 23.25,
        "label": "M",
        "opp": "JAX",
        "rank": 16,
        "teamSpread": -3
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 37.5,
        "home": false,
        "impliedTotal": 17.5,
        "label": "H",
        "opp": "PHI",
        "rank": 32,
        "teamSpread": 2.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20,
        "label": "M",
        "opp": "GB",
        "rank": 20,
        "teamSpread": 2.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 23.25,
        "label": "M",
        "opp": "JAX",
        "rank": 20,
        "teamSpread": -3
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 37.5,
        "home": false,
        "impliedTotal": 17.5,
        "label": "H",
        "opp": "PHI",
        "rank": 31,
        "teamSpread": 2.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20,
        "label": "H",
        "opp": "GB",
        "rank": 22,
        "teamSpread": 2.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 23.25,
        "label": "H",
        "opp": "JAX",
        "rank": 22,
        "teamSpread": -3
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 37.5,
        "home": false,
        "impliedTotal": 17.5,
        "label": "H",
        "opp": "PHI",
        "rank": 29,
        "teamSpread": 2.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20,
        "label": "H",
        "opp": "GB",
        "rank": 22,
        "teamSpread": 2.5
      }
    }
  },
  "IND": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "TEN",
        "rank": 7,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": true,
        "impliedTotal": 25.5,
        "label": "E",
        "opp": "CIN",
        "rank": 3,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 23,
        "label": "H",
        "opp": "CLE",
        "rank": 24,
        "teamSpread": -2.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "TEN",
        "rank": 4,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": true,
        "impliedTotal": 25.5,
        "label": "E",
        "opp": "CIN",
        "rank": 6,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 23,
        "label": "H",
        "opp": "CLE",
        "rank": 22,
        "teamSpread": -2.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "TEN",
        "rank": 6,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": true,
        "impliedTotal": 25.5,
        "label": "E",
        "opp": "CIN",
        "rank": 3,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 23,
        "label": "H",
        "opp": "CLE",
        "rank": 23,
        "teamSpread": -2.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "TEN",
        "rank": 4,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": true,
        "impliedTotal": 25.5,
        "label": "E",
        "opp": "CIN",
        "rank": 5,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 23,
        "label": "M",
        "opp": "CLE",
        "rank": 19,
        "teamSpread": -2.5
      }
    }
  },
  "JAX": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 20.25,
        "label": "H",
        "opp": "HOU",
        "rank": 32,
        "teamSpread": 3
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24.25,
        "label": "E",
        "opp": "DAL",
        "rank": 1,
        "teamSpread": 3
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 48.5,
        "home": true,
        "impliedTotal": 26,
        "label": "E",
        "opp": "WAS",
        "rank": 1,
        "teamSpread": -3.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 20.25,
        "label": "H",
        "opp": "HOU",
        "rank": 32,
        "teamSpread": 3
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24.25,
        "label": "E",
        "opp": "DAL",
        "rank": 8,
        "teamSpread": 3
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 48.5,
        "home": true,
        "impliedTotal": 26,
        "label": "E",
        "opp": "WAS",
        "rank": 2,
        "teamSpread": -3.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 20.25,
        "label": "H",
        "opp": "HOU",
        "rank": 32,
        "teamSpread": 3
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24.25,
        "label": "E",
        "opp": "DAL",
        "rank": 4,
        "teamSpread": 3
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 48.5,
        "home": true,
        "impliedTotal": 26,
        "label": "E",
        "opp": "WAS",
        "rank": 2,
        "teamSpread": -3.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 20.25,
        "label": "H",
        "opp": "HOU",
        "rank": 32,
        "teamSpread": 3
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 51.5,
        "home": false,
        "impliedTotal": 24.25,
        "label": "E",
        "opp": "DAL",
        "rank": 6,
        "teamSpread": 3
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 48.5,
        "home": true,
        "impliedTotal": 26,
        "label": "E",
        "opp": "WAS",
        "rank": 2,
        "teamSpread": -3.5
      }
    }
  },
  "KC": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 24,
        "label": "H",
        "opp": "NE",
        "rank": 28,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 24.75,
        "label": "E",
        "opp": "SF",
        "rank": 11,
        "teamSpread": -3
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 22,
        "label": "H",
        "opp": "LAC",
        "rank": 22,
        "teamSpread": 1.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 24,
        "label": "H",
        "opp": "NE",
        "rank": 22,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 24.75,
        "label": "M",
        "opp": "SF",
        "rank": 12,
        "teamSpread": -3
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 22,
        "label": "M",
        "opp": "LAC",
        "rank": 21,
        "teamSpread": 1.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 24,
        "label": "H",
        "opp": "NE",
        "rank": 26,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 24.75,
        "label": "E",
        "opp": "SF",
        "rank": 11,
        "teamSpread": -3
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 22,
        "label": "M",
        "opp": "LAC",
        "rank": 20,
        "teamSpread": 1.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 24,
        "label": "H",
        "opp": "NE",
        "rank": 27,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 24.75,
        "label": "E",
        "opp": "SF",
        "rank": 9,
        "teamSpread": -3
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 22,
        "label": "M",
        "opp": "LAC",
        "rank": 20,
        "teamSpread": 1.5
      }
    }
  },
  "LAC": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 25,
        "label": "E",
        "opp": "SF",
        "rank": 10,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 26.25,
        "label": "E",
        "opp": "MIA",
        "rank": 4,
        "teamSpread": -7
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 23.5,
        "label": "M",
        "opp": "KC",
        "rank": 18,
        "teamSpread": -1.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 25,
        "label": "M",
        "opp": "SF",
        "rank": 14,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 26.25,
        "label": "E",
        "opp": "MIA",
        "rank": 2,
        "teamSpread": -7
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 23.5,
        "label": "M",
        "opp": "KC",
        "rank": 17,
        "teamSpread": -1.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 25,
        "label": "E",
        "opp": "SF",
        "rank": 10,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 26.25,
        "label": "E",
        "opp": "MIA",
        "rank": 5,
        "teamSpread": -7
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 23.5,
        "label": "M",
        "opp": "KC",
        "rank": 18,
        "teamSpread": -1.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 25,
        "label": "E",
        "opp": "SF",
        "rank": 9,
        "teamSpread": -2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 26.25,
        "label": "E",
        "opp": "MIA",
        "rank": 2,
        "teamSpread": -7
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 23.5,
        "label": "M",
        "opp": "KC",
        "rank": 16,
        "teamSpread": -1.5
      }
    }
  },
  "LAR": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": true,
        "impliedTotal": 29.25,
        "label": "E",
        "opp": "DAL",
        "rank": 1,
        "teamSpread": -6
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 23,
        "label": "H",
        "opp": "SEA",
        "rank": 30,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 48.5,
        "home": false,
        "impliedTotal": 26.5,
        "label": "E",
        "opp": "TB",
        "rank": 8,
        "teamSpread": -4.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": true,
        "impliedTotal": 29.25,
        "label": "E",
        "opp": "DAL",
        "rank": 1,
        "teamSpread": -6
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 23,
        "label": "H",
        "opp": "SEA",
        "rank": 29,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 48.5,
        "home": false,
        "impliedTotal": 26.5,
        "label": "E",
        "opp": "TB",
        "rank": 5,
        "teamSpread": -4.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": true,
        "impliedTotal": 29.25,
        "label": "E",
        "opp": "DAL",
        "rank": 1,
        "teamSpread": -6
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 23,
        "label": "H",
        "opp": "SEA",
        "rank": 29,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 48.5,
        "home": false,
        "impliedTotal": 26.5,
        "label": "E",
        "opp": "TB",
        "rank": 7,
        "teamSpread": -4.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 52.5,
        "home": true,
        "impliedTotal": 29.25,
        "label": "E",
        "opp": "DAL",
        "rank": 1,
        "teamSpread": -6
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 23,
        "label": "H",
        "opp": "SEA",
        "rank": 30,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 48.5,
        "home": false,
        "impliedTotal": 26.5,
        "label": "E",
        "opp": "TB",
        "rank": 8,
        "teamSpread": -4.5
      }
    }
  },
  "LV": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 18.5,
        "label": "H",
        "opp": "DEN",
        "rank": 29,
        "teamSpread": 4.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22,
        "label": "E",
        "opp": "TEN",
        "rank": 9,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 22,
        "label": "E",
        "opp": "ARI",
        "rank": 5,
        "teamSpread": -1.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 18.5,
        "label": "H",
        "opp": "DEN",
        "rank": 30,
        "teamSpread": 4.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22,
        "label": "E",
        "opp": "TEN",
        "rank": 9,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 22,
        "label": "E",
        "opp": "ARI",
        "rank": 4,
        "teamSpread": -1.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 18.5,
        "label": "H",
        "opp": "DEN",
        "rank": 30,
        "teamSpread": 4.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22,
        "label": "E",
        "opp": "TEN",
        "rank": 9,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 22,
        "label": "E",
        "opp": "ARI",
        "rank": 5,
        "teamSpread": -1.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 18.5,
        "label": "H",
        "opp": "DEN",
        "rank": 30,
        "teamSpread": 4.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22,
        "label": "E",
        "opp": "TEN",
        "rank": 10,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 22,
        "label": "E",
        "opp": "ARI",
        "rank": 4,
        "teamSpread": -1.5
      }
    }
  },
  "MIA": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 17.5,
        "label": "M",
        "opp": "GB",
        "rank": 21,
        "teamSpread": 10.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 19.25,
        "label": "H",
        "opp": "LAC",
        "rank": 25,
        "teamSpread": 7
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 20,
        "label": "M",
        "opp": "BUF",
        "rank": 20,
        "teamSpread": 7.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 17.5,
        "label": "H",
        "opp": "GB",
        "rank": 28,
        "teamSpread": 10.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 19.25,
        "label": "H",
        "opp": "LAC",
        "rank": 26,
        "teamSpread": 7
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 20,
        "label": "H",
        "opp": "BUF",
        "rank": 25,
        "teamSpread": 7.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 17.5,
        "label": "H",
        "opp": "GB",
        "rank": 27,
        "teamSpread": 10.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 19.25,
        "label": "H",
        "opp": "LAC",
        "rank": 27,
        "teamSpread": 7
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 20,
        "label": "M",
        "opp": "BUF",
        "rank": 19,
        "teamSpread": 7.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 17.5,
        "label": "H",
        "opp": "GB",
        "rank": 26,
        "teamSpread": 10.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 19.25,
        "label": "H",
        "opp": "LAC",
        "rank": 25,
        "teamSpread": 7
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 20,
        "label": "H",
        "opp": "BUF",
        "rank": 23,
        "teamSpread": 7.5
      }
    }
  },
  "MIN": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "DET",
        "rank": 18,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "WAS",
        "rank": 5,
        "teamSpread": -2.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 39.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 6,
        "teamSpread": -3.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "DET",
        "rank": 25,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "WAS",
        "rank": 3,
        "teamSpread": -2.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 39.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 7,
        "teamSpread": -3.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "DET",
        "rank": 22,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "WAS",
        "rank": 6,
        "teamSpread": -2.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 39.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 8,
        "teamSpread": -3.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "DET",
        "rank": 18,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "E",
        "opp": "WAS",
        "rank": 4,
        "teamSpread": -2.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 39.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 7,
        "teamSpread": -3.5
      }
    }
  },
  "NE": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "M",
        "opp": "KC",
        "rank": 20,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 40.5,
        "home": false,
        "impliedTotal": 23.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 6,
        "teamSpread": -6.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "DEN",
        "rank": 26,
        "teamSpread": -2.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "H",
        "opp": "KC",
        "rank": 26,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 40.5,
        "home": false,
        "impliedTotal": 23.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 5,
        "teamSpread": -6.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "DEN",
        "rank": 23,
        "teamSpread": -2.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "H",
        "opp": "KC",
        "rank": 25,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 40.5,
        "home": false,
        "impliedTotal": 23.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 8,
        "teamSpread": -6.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "DEN",
        "rank": 26,
        "teamSpread": -2.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "H",
        "opp": "KC",
        "rank": 24,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 40.5,
        "home": false,
        "impliedTotal": 23.5,
        "label": "E",
        "opp": "NYJ",
        "rank": 7,
        "teamSpread": -6.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "DEN",
        "rank": 27,
        "teamSpread": -2.5
      }
    }
  },
  "NO": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 21,
        "label": "M",
        "opp": "TB",
        "rank": 15,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 44.5,
        "home": true,
        "impliedTotal": 25,
        "label": "E",
        "opp": "ARI",
        "rank": 2,
        "teamSpread": -5.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 44.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "M",
        "opp": "ATL",
        "rank": 17,
        "teamSpread": 1.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 21,
        "label": "M",
        "opp": "TB",
        "rank": 19,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 44.5,
        "home": true,
        "impliedTotal": 25,
        "label": "E",
        "opp": "ARI",
        "rank": 1,
        "teamSpread": -5.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 44.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "M",
        "opp": "ATL",
        "rank": 18,
        "teamSpread": 1.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 21,
        "label": "M",
        "opp": "TB",
        "rank": 19,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 44.5,
        "home": true,
        "impliedTotal": 25,
        "label": "E",
        "opp": "ARI",
        "rank": 1,
        "teamSpread": -5.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 44.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "M",
        "opp": "ATL",
        "rank": 21,
        "teamSpread": 1.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 21,
        "label": "M",
        "opp": "TB",
        "rank": 19,
        "teamSpread": 3.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 44.5,
        "home": true,
        "impliedTotal": 25,
        "label": "E",
        "opp": "ARI",
        "rank": 1,
        "teamSpread": -5.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 44.5,
        "home": false,
        "impliedTotal": 21.5,
        "label": "M",
        "opp": "ATL",
        "rank": 21,
        "teamSpread": 1.5
      }
    }
  },
  "NYG": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 40.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "CLE",
        "rank": 25,
        "teamSpread": -4.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "DET",
        "rank": 16,
        "teamSpread": 4.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "E",
        "opp": "DAL",
        "rank": 4,
        "teamSpread": 4.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 40.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "CLE",
        "rank": 24,
        "teamSpread": -4.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "DET",
        "rank": 25,
        "teamSpread": 4.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "E",
        "opp": "DAL",
        "rank": 8,
        "teamSpread": 4.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 40.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "CLE",
        "rank": 23,
        "teamSpread": -4.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "DET",
        "rank": 21,
        "teamSpread": 4.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "E",
        "opp": "DAL",
        "rank": 6,
        "teamSpread": 4.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 40.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "CLE",
        "rank": 20,
        "teamSpread": -4.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "DET",
        "rank": 20,
        "teamSpread": 4.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 49.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "E",
        "opp": "DAL",
        "rank": 6,
        "teamSpread": 4.5
      }
    }
  },
  "NYJ": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 20,
        "label": "E",
        "opp": "ARI",
        "rank": 5,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 40.5,
        "home": true,
        "impliedTotal": 17,
        "label": "H",
        "opp": "NE",
        "rank": 29,
        "teamSpread": 6.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 39.5,
        "home": true,
        "impliedTotal": 18,
        "label": "H",
        "opp": "MIN",
        "rank": 25,
        "teamSpread": 3.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 20,
        "label": "E",
        "opp": "ARI",
        "rank": 7,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 40.5,
        "home": true,
        "impliedTotal": 17,
        "label": "H",
        "opp": "NE",
        "rank": 31,
        "teamSpread": 6.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 39.5,
        "home": true,
        "impliedTotal": 18,
        "label": "H",
        "opp": "MIN",
        "rank": 31,
        "teamSpread": 3.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 20,
        "label": "E",
        "opp": "ARI",
        "rank": 5,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 40.5,
        "home": true,
        "impliedTotal": 17,
        "label": "H",
        "opp": "NE",
        "rank": 32,
        "teamSpread": 6.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 39.5,
        "home": true,
        "impliedTotal": 18,
        "label": "H",
        "opp": "MIN",
        "rank": 28,
        "teamSpread": 3.5
      }
    },
    "WR": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 41.5,
        "home": false,
        "impliedTotal": 20,
        "label": "E",
        "opp": "ARI",
        "rank": 6,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 40.5,
        "home": true,
        "impliedTotal": 17,
        "label": "H",
        "opp": "NE",
        "rank": 31,
        "teamSpread": 6.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 39.5,
        "home": true,
        "impliedTotal": 18,
        "label": "H",
        "opp": "MIN",
        "rank": 28,
        "teamSpread": 3.5
      }
    }
  },
  "PHI": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "SEA",
        "rank": 31,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 37.5,
        "home": true,
        "impliedTotal": 20,
        "label": "H",
        "opp": "HOU",
        "rank": 32,
        "teamSpread": -2.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 22,
        "label": "M",
        "opp": "SF",
        "rank": 14,
        "teamSpread": 1.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "SEA",
        "rank": 29,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 37.5,
        "home": true,
        "impliedTotal": 20,
        "label": "H",
        "opp": "HOU",
        "rank": 28,
        "teamSpread": -2.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 22,
        "label": "M",
        "opp": "SF",
        "rank": 19,
        "teamSpread": 1.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "SEA",
        "rank": 31,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 37.5,
        "home": true,
        "impliedTotal": 20,
        "label": "H",
        "opp": "HOU",
        "rank": 30,
        "teamSpread": -2.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 22,
        "label": "M",
        "opp": "SF",
        "rank": 14,
        "teamSpread": 1.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "SEA",
        "rank": 31,
        "teamSpread": -1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 37.5,
        "home": true,
        "impliedTotal": 20,
        "label": "H",
        "opp": "HOU",
        "rank": 32,
        "teamSpread": -2.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 22,
        "label": "M",
        "opp": "SF",
        "rank": 14,
        "teamSpread": 1.5
      }
    }
  },
  "PIT": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22,
        "label": "M",
        "opp": "BAL",
        "rank": 19,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "CAR",
        "rank": 18,
        "teamSpread": -3.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 22,
        "label": "E",
        "opp": "TEN",
        "rank": 9,
        "teamSpread": -1.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22,
        "label": "H",
        "opp": "BAL",
        "rank": 23,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "CAR",
        "rank": 16,
        "teamSpread": -3.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 22,
        "label": "E",
        "opp": "TEN",
        "rank": 11,
        "teamSpread": -1.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22,
        "label": "H",
        "opp": "BAL",
        "rank": 24,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "CAR",
        "rank": 15,
        "teamSpread": -3.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 22,
        "label": "E",
        "opp": "TEN",
        "rank": 9,
        "teamSpread": -1.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 22,
        "label": "H",
        "opp": "BAL",
        "rank": 25,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 41.5,
        "home": true,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "CAR",
        "rank": 15,
        "teamSpread": -3.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 22,
        "label": "E",
        "opp": "TEN",
        "rank": 9,
        "teamSpread": -1.5
      }
    }
  },
  "SEA": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 21,
        "label": "H",
        "opp": "PHI",
        "rank": 30,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "H",
        "opp": "LAR",
        "rank": 27,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#facc15",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 24,
        "label": "M",
        "opp": "CAR",
        "rank": 16,
        "teamSpread": -5.5
      }
    },
    "RB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 21,
        "label": "H",
        "opp": "PHI",
        "rank": 31,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "LAR",
        "rank": 20,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 24,
        "label": "E",
        "opp": "CAR",
        "rank": 9,
        "teamSpread": -5.5
      }
    },
    "TE": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 21,
        "label": "H",
        "opp": "PHI",
        "rank": 29,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "H",
        "opp": "LAR",
        "rank": 23,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 24,
        "label": "E",
        "opp": "CAR",
        "rank": 11,
        "teamSpread": -5.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 43.5,
        "home": false,
        "impliedTotal": 21,
        "label": "H",
        "opp": "PHI",
        "rank": 29,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "H",
        "opp": "LAR",
        "rank": 26,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 24,
        "label": "E",
        "opp": "CAR",
        "rank": 10,
        "teamSpread": -5.5
      }
    }
  },
  "SF": {
    "QB": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "LAC",
        "rank": 23,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 21.75,
        "label": "M",
        "opp": "KC",
        "rank": 20,
        "teamSpread": 3
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 23.5,
        "label": "H",
        "opp": "PHI",
        "rank": 28,
        "teamSpread": -1.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "LAC",
        "rank": 21,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 21.75,
        "label": "H",
        "opp": "KC",
        "rank": 22,
        "teamSpread": 3
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 23.5,
        "label": "H",
        "opp": "PHI",
        "rank": 29,
        "teamSpread": -1.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "M",
        "opp": "LAC",
        "rank": 21,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 21.75,
        "label": "H",
        "opp": "KC",
        "rank": 22,
        "teamSpread": 3
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 23.5,
        "label": "H",
        "opp": "PHI",
        "rank": 27,
        "teamSpread": -1.5
      }
    },
    "WR": {
      "15": {
        "color": "#ef4444",
        "gameTotal": 47.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "LAC",
        "rank": 23,
        "teamSpread": 2.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 21.75,
        "label": "M",
        "opp": "KC",
        "rank": 21,
        "teamSpread": 3
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 23.5,
        "label": "H",
        "opp": "PHI",
        "rank": 26,
        "teamSpread": -1.5
      }
    }
  },
  "TB": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "NO",
        "rank": 16,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 23.5,
        "label": "M",
        "opp": "ATL",
        "rank": 15,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 48.5,
        "home": true,
        "impliedTotal": 22,
        "label": "H",
        "opp": "LAR",
        "rank": 27,
        "teamSpread": 4.5
      }
    },
    "RB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "NO",
        "rank": 12,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 23.5,
        "label": "M",
        "opp": "ATL",
        "rank": 14,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 48.5,
        "home": true,
        "impliedTotal": 22,
        "label": "H",
        "opp": "LAR",
        "rank": 28,
        "teamSpread": 4.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "NO",
        "rank": 15,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 23.5,
        "label": "M",
        "opp": "ATL",
        "rank": 18,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 48.5,
        "home": true,
        "impliedTotal": 22,
        "label": "H",
        "opp": "LAR",
        "rank": 29,
        "teamSpread": 4.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": true,
        "impliedTotal": 24.5,
        "label": "M",
        "opp": "NO",
        "rank": 15,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 45.5,
        "home": false,
        "impliedTotal": 23.5,
        "label": "M",
        "opp": "ATL",
        "rank": 18,
        "teamSpread": -1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 48.5,
        "home": true,
        "impliedTotal": 22,
        "label": "H",
        "opp": "LAR",
        "rank": 29,
        "teamSpread": 4.5
      }
    }
  },
  "TEN": {
    "QB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 23,
        "label": "E",
        "opp": "IND",
        "rank": 11,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20.5,
        "label": "E",
        "opp": "LV",
        "rank": 10,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "H",
        "opp": "PIT",
        "rank": 29,
        "teamSpread": 1.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 23,
        "label": "E",
        "opp": "IND",
        "rank": 11,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20.5,
        "label": "E",
        "opp": "LV",
        "rank": 11,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "H",
        "opp": "PIT",
        "rank": 26,
        "teamSpread": 1.5
      }
    },
    "TE": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 23,
        "label": "E",
        "opp": "IND",
        "rank": 8,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20.5,
        "label": "E",
        "opp": "LV",
        "rank": 10,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "H",
        "opp": "PIT",
        "rank": 25,
        "teamSpread": 1.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 47.5,
        "home": true,
        "impliedTotal": 23,
        "label": "M",
        "opp": "IND",
        "rank": 12,
        "teamSpread": 1.5
      },
      "16": {
        "color": "#22c55e",
        "gameTotal": 42.5,
        "home": false,
        "impliedTotal": 20.5,
        "label": "E",
        "opp": "LV",
        "rank": 11,
        "teamSpread": 1.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 42.5,
        "home": true,
        "impliedTotal": 20.5,
        "label": "H",
        "opp": "PIT",
        "rank": 25,
        "teamSpread": 1.5
      }
    }
  },
  "WAS": {
    "QB": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 25,
        "label": "M",
        "opp": "ATL",
        "rank": 14,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 22,
        "label": "H",
        "opp": "MIN",
        "rank": 22,
        "teamSpread": 2.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 48.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "JAX",
        "rank": 23,
        "teamSpread": 3.5
      }
    },
    "RB": {
      "15": {
        "color": "#22c55e",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 25,
        "label": "E",
        "opp": "ATL",
        "rank": 9,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 22,
        "label": "H",
        "opp": "MIN",
        "rank": 24,
        "teamSpread": 2.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 48.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "JAX",
        "rank": 24,
        "teamSpread": 3.5
      }
    },
    "TE": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 25,
        "label": "M",
        "opp": "ATL",
        "rank": 16,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 22,
        "label": "M",
        "opp": "MIN",
        "rank": 20,
        "teamSpread": 2.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 48.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "JAX",
        "rank": 24,
        "teamSpread": 3.5
      }
    },
    "WR": {
      "15": {
        "color": "#facc15",
        "gameTotal": 46.5,
        "home": true,
        "impliedTotal": 25,
        "label": "M",
        "opp": "ATL",
        "rank": 16,
        "teamSpread": -3.5
      },
      "16": {
        "color": "#ef4444",
        "gameTotal": 46.5,
        "home": false,
        "impliedTotal": 22,
        "label": "H",
        "opp": "MIN",
        "rank": 22,
        "teamSpread": 2.5
      },
      "17": {
        "color": "#ef4444",
        "gameTotal": 48.5,
        "home": false,
        "impliedTotal": 22.5,
        "label": "H",
        "opp": "JAX",
        "rank": 24,
        "teamSpread": 3.5
      }
    }
  }
};
