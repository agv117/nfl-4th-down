"""NFL 4th-Down Decision Bot - data pipeline.

Pulls nflverse play-by-play (2015-2024, free, no auth) and bakes:
  web/wp_grid.json   - win probability for 1st-and-10 states, by (score_diff, time, yardline)
  web/tables.json    - empirical conversion% by distance, FG make% by distance, punt field-position map
  web/coaches.json   - leaderboard of win-probability burned by kicking when the model said GO

The decision math (go vs punt vs FG) is done CLIENT-SIDE in app.js from these tables,
so it is fully transparent. This script only bakes the ingredients.

Model: a win-probability model trained on ~450k plays. Label = did the team with the ball win.
Every 4th-down outcome resolves to one of:
  - offense keeps ball, 1st-and-10 at a new spot        (go, converted)
  - a score (+7 TD / +3 FG), opponent receives kickoff  (go->TD / made FG)
  - opponent takes over, 1st-and-10 at some spot         (go fail / punt / missed FG)
...all of which are 1st-and-10 states or post-score kickoffs. So we only need WP for
1st-and-10, which keeps the baked grid tiny.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingClassifier

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RAW = ROOT / "data"
WEB = ROOT / "web"
RAW.mkdir(exist_ok=True)
WEB.mkdir(exist_ok=True)

SEASONS = list(range(2015, 2025))          # decade of data for the WP model + rates
COACH_SEASONS = list(range(2020, 2025))    # recent era for the coach leaderboard

REL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.parquet"

# columns we actually use (out of 372) - keeps memory sane
COLS = [
    "season", "season_type", "game_id", "posteam", "defteam", "home_team", "away_team",
    "home_coach", "away_coach", "down", "ydstogo", "yardline_100", "score_differential",
    "game_seconds_remaining", "half_seconds_remaining", "qtr", "play_type",
    "field_goal_result", "kick_distance", "return_yards", "touchback",
    "yards_gained", "first_down", "result", "wp",
]


def fetch_season(yr):
    fp = RAW / f"pbp_{yr}.parquet"
    if not fp.exists():
        print(f"  downloading {yr} ...", flush=True)
        r = requests.get(REL.format(yr), timeout=180)
        r.raise_for_status()
        fp.write_bytes(r.content)
    df = pd.read_parquet(fp)
    keep = [c for c in COLS if c in df.columns]
    return df[keep]


def load():
    print("Loading seasons", SEASONS[0], "-", SEASONS[-1])
    frames = [fetch_season(y) for y in SEASONS]
    df = pd.concat(frames, ignore_index=True)
    print("  total rows:", len(df))
    return df


# ---------- WP model ----------
FEATS = ["score_differential", "game_seconds_remaining", "half_seconds_remaining",
         "yardline_100", "down", "ydstogo"]


def train_wp(df):
    d = df.copy()
    # winner label from final margin (result = home final margin)
    d = d[d["result"].notna()]
    posteam_is_home = d["posteam"] == d["home_team"]
    home_won = d["result"] > 0
    away_won = d["result"] < 0
    won = np.where(posteam_is_home, home_won, away_won)
    tie = d["result"] == 0
    d = d.assign(won=won.astype(float))
    d = d[~tie]  # drop ties (rare)
    d = d.dropna(subset=FEATS + ["won"])
    d = d[(d["down"] >= 1) & (d["down"] <= 4)]
    X = d[FEATS].to_numpy(dtype=float)
    y = d["won"].to_numpy(dtype=int)
    print("  training WP on", len(d), "plays")
    clf = HistGradientBoostingClassifier(
        max_iter=300, max_depth=6, learning_rate=0.06,
        l2_regularization=1.0, min_samples_leaf=200, random_state=7,
    )
    clf.fit(X, y)
    # quick calibration sanity: brier score
    p = clf.predict_proba(X)[:, 1]
    brier = np.mean((p - y) ** 2)
    print(f"  in-sample Brier: {brier:.4f} (lower=better; ~0.20 baseline coin-flip)")
    return clf


# ---------- empirical rates ----------
def conversion_by_distance(df):
    """P(convert) by yards-to-go, using 3rd & 4th down run/pass attempts (more signal)."""
    d = df[df["down"].isin([3, 4]) & df["play_type"].isin(["run", "pass"])].copy()
    d = d.dropna(subset=["ydstogo", "yards_gained"])
    d = d[(d["ydstogo"] >= 1) & (d["ydstogo"] <= 20)]
    success = ((d["first_down"] == 1) | (d["yards_gained"] >= d["ydstogo"])).astype(int)
    d = d.assign(success=success)
    out = {}
    for togo in range(1, 16):
        sub = d[d["ydstogo"] == togo]
        if len(sub) >= 40:
            out[togo] = round(float(sub["success"].mean()), 4)
    # smooth/fill gaps monotonically-ish by carrying nearest computed value down
    last = out.get(1, 0.72)
    filled = {}
    for togo in range(1, 16):
        if togo in out:
            last = out[togo]
        filled[togo] = round(last, 4)
    return filled


def fg_make_by_distance(df):
    """P(make) by kick distance (yards)."""
    d = df[(df["play_type"] == "field_goal")].copy()
    d = d.dropna(subset=["kick_distance", "field_goal_result"])
    d = d[(d["kick_distance"] >= 15) & (d["kick_distance"] <= 70)]
    made = (d["field_goal_result"] == "made").astype(int)
    d = d.assign(made=made)
    out = {}
    for dist in range(15, 71):
        sub = d[(d["kick_distance"] >= dist - 2) & (d["kick_distance"] <= dist + 2)]  # +/-2yd window
        if len(sub) >= 30:
            out[dist] = round(float(sub["made"].mean()), 4)
    # fill: near range ~0.98, long range decays; carry nearest
    keys = sorted(out)
    filled = {}
    for dist in range(15, 71):
        if dist in out:
            filled[dist] = out[dist]
        else:
            # nearest computed
            near = min(keys, key=lambda k: abs(k - dist)) if keys else None
            filled[dist] = out[near] if near is not None else max(0.0, 1.0 - (dist - 15) * 0.03)
    return filled


def punt_result_by_yardline(df):
    """Expected OPPONENT starting yardline_100 after a punt from our yardline_100=Y.
    Empirical where sample is thick; formula fallback where punts are rare (deep in opp territory).
    """
    d = df[(df["play_type"] == "punt")].copy()
    d = d.dropna(subset=["yardline_100"])
    # net punt = kick_distance - return_yards ; touchback -> opp own 20 (their yardline_100 = 80)
    d["net"] = (d["kick_distance"].fillna(40) - d["return_yards"].fillna(0))
    tb = d["touchback"] == 1
    opp = 100 - d["yardline_100"] + d["net"]
    opp = opp.where(~tb, 80.0).clip(1, 99)
    d = d.assign(opp_start=opp)
    out = {}
    for Y in range(1, 100):
        sub = d[d["yardline_100"] == Y]
        if len(sub) >= 20:
            out[Y] = round(float(sub["opp_start"].mean()), 2)
        else:
            # fallback: net ~42, cap opp start at own 20 (yardline_100 80) for short punts
            out[Y] = round(min(80.0, max(1.0, 100 - Y + 42)), 2)
    return out


# ---------- bake WP grid for 1st-and-10 ----------
SCORE_MIN, SCORE_MAX = -24, 24
SEC_STEP = 120                      # bucket game seconds every 2 minutes
SEC_BUCKETS = list(range(0, 3600 + 1, SEC_STEP))  # 0..3600


def bake_wp_grid(clf):
    score_diffs = list(range(SCORE_MIN, SCORE_MAX + 1))          # 49
    yardlines = list(range(1, 100))                              # 99
    grid = {}                                                    # score_diff -> [sec_bucket][yardline]
    for sd in score_diffs:
        plane = []
        for sec in SEC_BUCKETS:
            half_sec = sec - 1800 if sec > 1800 else sec        # approx half clock
            half_sec = max(0, half_sec)
            rows = np.array([[sd, sec, half_sec, yl, 1, 10] for yl in yardlines], dtype=float)
            p = clf.predict_proba(rows)[:, 1]
            plane.append([round(float(x), 4) for x in p])
        grid[str(sd)] = plane
    return {
        "score_min": SCORE_MIN, "score_max": SCORE_MAX,
        "sec_step": SEC_STEP, "sec_buckets": SEC_BUCKETS,
        "grid": grid,
    }


# ---------- coach leaderboard ----------
def _batch_wp1st10(clf, sd_arr, sec_arr, yl_arr):
    """Vectorized WP for 1st-and-10 states. One predict_proba over the whole batch."""
    n = len(sd_arr)
    sdc = np.clip(np.round(sd_arr), SCORE_MIN, SCORE_MAX)
    ylc = np.clip(np.round(yl_arr), 1, 99)
    secc = np.clip(sec_arr, 0, 3600)
    half = np.where(secc > 1800, secc - 1800, secc)
    X = np.column_stack([sdc, secc, half, ylc, np.ones(n), np.full(n, 10.0)])
    return clf.predict_proba(X)[:, 1]


def bake_coaches(df, clf, tables):
    """For real 4th-down FG/punt decisions 2020-2024, if the model says GO had higher WP,
    credit the coach with the WP they burned (model WP_go - model WP_of_their_kick).
    Fully vectorized: 8 batched model calls total."""
    pconv = tables["conversion"]
    pmake = tables["fg_make"]
    punt_res = tables["punt_result"]

    d = df[df["season"].isin(COACH_SEASONS)].copy()
    d = d[(d["down"] == 4) & d["play_type"].isin(["punt", "field_goal", "run", "pass"])]
    d = d.dropna(subset=["yardline_100", "game_seconds_remaining", "ydstogo",
                         "score_differential", "posteam", "home_team", "away_team",
                         "home_coach", "away_coach"])
    d["coach"] = np.where(d["posteam"] == d["home_team"], d["home_coach"], d["away_coach"])
    d = d[d["coach"].apply(lambda x: isinstance(x, str))]

    sd = d["score_differential"].to_numpy(float)
    sec = d["game_seconds_remaining"].to_numpy(float)
    yl = d["yardline_100"].to_numpy(float)
    togo = np.clip(d["ydstogo"].to_numpy(float), 1, 15)
    pt = d["play_type"].to_numpy()
    n = len(d)
    W = lambda a, s, y: _batch_wp1st10(clf, a, s, y)

    # GO
    pconv_arr = np.array([pconv.get(int(round(t)), 0.5) for t in togo])
    new_yl = yl - togo
    td_mask = new_yl <= 0
    wp_td = 1 - W(-(sd + 7), sec, np.full(n, 75.0))
    wp_first = W(sd, sec, np.clip(new_yl, 1, 99))
    wp_succeed = np.where(td_mask, wp_td, wp_first)
    wp_fail = 1 - W(-sd, sec, 100 - yl)
    wgo = pconv_arr * wp_succeed + (1 - pconv_arr) * wp_fail

    # FIELD GOAL
    dist = yl + 17
    pmake_arr = np.array([pmake.get(int(round(dd)), 0.02 if dd > 66 else 0.9) for dd in dist])
    wp_make = 1 - W(-(sd + 3), sec, np.full(n, 75.0))
    wp_miss = 1 - W(-sd, sec, np.minimum(80, 100 - (yl + 7)))
    wfg = pmake_arr * wp_make + (1 - pmake_arr) * wp_miss

    # PUNT
    punt_opp = np.array([punt_res.get(int(round(y)), min(80, 100 - y + 42)) for y in yl])
    wpunt = 1 - W(-sd, sec, punt_opp)

    is_kick = np.isin(pt, ["punt", "field_goal"])
    wkick = np.where(pt == "punt", wpunt, wfg)
    conservative = is_kick & (wgo > wkick)
    burned_per = np.where(conservative, wgo - wkick, 0.0)

    res = pd.DataFrame({
        "coach": d["coach"].to_numpy(), "team": d["posteam"].to_numpy(),
        "is_kick": is_kick.astype(int), "burned": burned_per, "conservative": conservative.astype(int),
    })
    g = res.groupby("coach")
    agg = pd.DataFrame({
        "total_kicks": g["is_kick"].sum(),
        "burned": g["burned"].sum(),
        "conservative_kicks": g["conservative"].sum(),
        "team": g["team"].agg(lambda s: s.mode().iat[0]),
    }).reset_index()

    rows = []
    for _, r in agg.iterrows():
        if r["total_kicks"] < 60:
            continue
        rows.append({
            "coach": r["coach"],
            "team": r["team"],
            "wp_burned": round(float(r["burned"]) * 100, 1),
            "conservative_kicks": int(r["conservative_kicks"]),
            "total_kicks": int(r["total_kicks"]),
            "burn_per_kick": round(float(r["burned"]) * 100 / r["total_kicks"], 3),
        })
    rows.sort(key=lambda x: x["wp_burned"], reverse=True)
    return {"seasons": [COACH_SEASONS[0], COACH_SEASONS[-1]], "leaderboard": rows}


def main():
    df = load()
    print("Training WP model ...")
    clf = train_wp(df)

    print("Computing empirical rates ...")
    tables = {
        "conversion": conversion_by_distance(df),
        "fg_make": fg_make_by_distance(df),
        "punt_result": punt_result_by_yardline(df),
        "seasons": [SEASONS[0], SEASONS[-1]],
    }

    print("Baking WP grid ...")
    wp_grid = bake_wp_grid(clf)

    print("Baking coach leaderboard ...")
    coaches = bake_coaches(df, clf, tables)

    (WEB / "tables.json").write_text(json.dumps(tables))
    (WEB / "wp_grid.json").write_text(json.dumps(wp_grid))
    (WEB / "coaches.json").write_text(json.dumps(coaches))

    print("\nWROTE:")
    for f in ("tables.json", "wp_grid.json", "coaches.json"):
        sz = (WEB / f).stat().st_size
        print(f"  web/{f}  {sz:,} bytes")
    print("  top burner:", coaches["leaderboard"][0] if coaches["leaderboard"] else "none")


if __name__ == "__main__":
    main()
