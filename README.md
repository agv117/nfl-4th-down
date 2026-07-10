# Should They Have Gone For It?

**An interactive NFL 4th-down decision model.** Set any game state — down/distance, field position, score, time — and get the analytically-correct call (**go / punt / field goal**) with the win probability each choice buys. Plus a coach leaderboard of win probability burned by kicking when the math said go.

**Live demo → https://anandvaghasia.com/nfl-4th-down/**

Finance read: this is expected-value maximization under uncertainty, applied to the most second-guessed decision in football.

## How it works

A 4th down is a choice between three lotteries. The model prices each in win probability.

1. **Win probability model** — a gradient-boosted classifier (`HistGradientBoostingClassifier`) trained on ~450k plays of [nflverse](https://github.com/nflverse/nflverse-data) play-by-play (2015–2024). Features: score differential, seconds remaining, field position, down, distance. Label: did the team with the ball win.
2. **Go** = P(convert)·WP(1st-and-10 at new spot) + P(fail)·WP(opponent ball on downs). Conversion rates are empirical by distance (a decade of 3rd/4th-down attempts).
3. **Field goal** = P(make)·WP(up 3, opponent receives) + P(miss)·WP(opponent ball at the spot). Make rates empirical by kick distance.
4. **Punt** = WP(opponent ball at the expected post-punt field position), measured from real punt outcomes.

Every 4th-down outcome resolves to a 1st-and-10 or a score, so the baked win-probability table only needs 1st-and-10 states — which keeps the payload small and the **decision arithmetic fully client-side and inspectable** (see `web/app.js`, `options()`).

## Architecture

```
pipeline/build.py   pull 10 seasons locally → train WP model → bake JSON
web/wp_grid.json    WP for 1st-and-10 by (score diff, time, field position)
web/tables.json     conversion% / FG make% / punt field-position, all empirical
web/coaches.json    coach leaderboard (WP burned kicking, 2020–2024)
web/index.html+css+js   static interactive page, zero server cost
deploy.py           FTPS upload to the /nfl-4th-down/ slug
```

No framework. No live compute. The browser does the EV math against small lookup tables.

## Run it yourself

```bash
python3 -m venv .venv && .venv/bin/pip install pandas pyarrow scikit-learn requests
.venv/bin/python pipeline/build.py     # downloads data, trains, bakes web/*.json
python3 -m http.server -d web 8000      # open localhost:8000
```

## Honesty

- Empirical WP is noisy in rare states (long distances, blowouts, final seconds) — treat those as directional.
- v1 has **no** weather, injuries, kicker/defense quality, or timeout context.
- The coach leaderboard measures conservatism _against this model_, not ground truth. Public models like [nfl4th](https://www.nfl4th.com/articles/4th-down-research.html) reach the same conclusion: coaches kick too much. Academic anchor: [arXiv:2311.03490](https://arxiv.org/html/2311.03490v4).
- Data is nflverse only. No scraping of Sports-Reference (against their ToS).

## Built with Claude Code

Data pipeline, win-probability model, and the interface — built end to end with [Claude Code](https://claude.com/claude-code).

— Anand Vaghasia, 2026
