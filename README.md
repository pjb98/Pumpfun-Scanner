# Pumpfun Scanner

A **Pump.fun platform-heat monitor**. It doesn't pick individual tokens — you trade
those yourself. It watches the *whole platform* and tells you **when conditions are
good to be trading**: when volume is up, tokens are migrating quickly and in high
quantity, launches are pouring in, and buy pressure is strong.

> Core question: *Is right now a good time to be trading Pump.fun — and which
> hours/conditions are historically the best?*

## What it measures (platform-wide)

| Metric | Meaning |
| --- | --- |
| **Launch rate** | new tokens / min — how busy the casino is |
| **Migration rate** | migrations / hour — how much is actually graduating |
| **Migration speed** | median minutes for migrating tokens to bond — faster = hotter |
| **Volume (5m)** | aggregate SOL traded across tracked tokens |
| **Active buyers (5m)** | unique wallets buying platform-wide |
| **Buy/sell pressure** | aggregate SOL in vs out |
| **Pump.fun froth** | launch rate ÷ migration rate — frothy churn (your #1 lead) |
| **SOL market froth** | f(SOL 24h % change, 24h volume vs baseline) — risk appetite |
| **SOL price** | spot price + 24h change, shown as context |

These roll into a single composite **heat score (0–100)** and a **GO / NEUTRAL / WAIT**
signal. "Hot" is judged **relative to a trailing baseline** of your own recorded
history (it cold-starts on reference levels until enough history exists), because raw
Pump.fun numbers drift over time.

**Heat weighting:** migrations 0.22 · volume 0.20 · pump.fun froth 0.18 · migration
speed 0.16 · buyers 0.12 · SOL froth 0.12. SOL price/volume come from CoinGecko's
free API (Binance is geo-blocked in many regions); if SOL data is unavailable the
monitor keeps running and treats SOL froth as neutral.

## Two modes

**Live** — `monitor.py` streams the platform in real time, shows the current heat
panel and GO/WAIT call, and logs a snapshot to SQLite every minute.

**History / best-times** — `best_times.py` reads the logged snapshots and shows when
heat/volume/migration flow have historically been strongest, by hour of day (and
optionally day-of-week × hour). The longer the monitor runs, the sharper this gets.

## Files

| File | Role |
| --- | --- |
| `monitor.py` | Live platform-heat monitor + snapshot logger (run this continuously) |
| `platform_state.py` | Rolling platform-wide aggregation from the PumpPortal stream |
| `heat.py` | Composite heat score (incl. pump.fun + SOL froth) + GO/NEUTRAL/WAIT signal |
| `market.py` | SOL price / 24h change / volume from CoinGecko (cached, fail-safe) |
| `alerts.py` | Discord webhook alert on the rising edge into GO |
| `storage.py` | SQLite persistence of snapshots (stdlib) |
| `best_times.py` | Hour-of-day / day-of-week best-time analysis over recorded history |
| `config.py` | Settings from `.env` |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # optional — sane defaults work out of the box
```

## Usage

```bash
# 1. run the monitor continuously (it collects history as it goes)
python monitor.py

# 2. after it has run for a while, see your best trading windows
python best_times.py            # hour-of-day summary
python best_times.py --dow      # + day-of-week x hour heatmap
```

For real "best times" you want it running for **days**, ideally as a background
service (systemd / tmux), so the hour-of-day patterns are built from enough data.

## Calibration

The cold-start `REF_*` levels in `.env` are rough guesses. Once you've collected a
day or two of snapshots, set them near your own median values so the live signal is
grounded in your actual platform, not defaults.

## Roadmap

- Confidence weighting on best-times (down-weight thin hours)
- Froth columns in the best-times report
- Optional fear & greed input

## Project spec

See [`pumpfunscanner.txt`](pumpfunscanner.txt) for the original design notes.
