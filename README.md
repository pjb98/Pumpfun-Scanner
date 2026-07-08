# Pumpfun Scanner

A live **Pump.fun pre-migration token scanner**. Instead of analyzing tokens after
they migrate, it surfaces tokens that are likely to give a tradable move **before**
migration — while filtering out dev dumps, holder dumps, and dead curves.

> Core question: *Which Pump.fun tokens are likely to give a tradable move before
> migration, without getting trapped in a dev dump / holder dump / dead curve?*

## What it tracks

| Category | Signals | Why it matters |
| --- | --- | --- |
| **Curve progress** | % bonded, market cap, SOL in curve | How close to the attention zone |
| **Bonding speed** | time to 25% / 50% / 75% / 90% bonded | Fast curves attract traders |
| **Curve acceleration** | change in 5m bonding speed | Accelerating vs stalling vs reversing |
| **Volume** | 1m / 5m / 15m volume | Confirms real activity |
| **Buyers** | unique buyers over 1m / 5m / 15m | Better than raw volume |
| **Buy pressure** | buys vs sells, SOL in vs out | Is momentum still alive |
| **Holder quality** | top-10 %, dev %, fresh wallets | Concentration / dump risk |
| **Dev activity** | dev buy / sell / transfers | Major risk filter |
| **Sniper activity** | first 10–20 buyers, bundle behavior | Avoid toxic charts |
| **Social presence** | website, X, Telegram, CA mentions | Narrative traction |
| **Market heat** | launches/hour, active buyers, SOL price | Are conditions good |

## Pre-migration score

A composite score drives a simple label per token:

```
Pre-Migration Score =
    bonding speed
  + volume acceleration
  + unique buyer growth
  + buy/sell pressure
  + social presence
  + dev still holding
  - top holder concentration
  - sniper dump pressure
  - stalled curve penalty
```

Tokens are labeled **TRADE / WATCH / AVOID / TOXIC**.

## MVP roadmap

1. Live Pump.fun token scanner table
2. Bonding % and bonding speed
3. 1m / 5m / 15m volume
4. Unique buyers
5. Buy/sell ratio
6. Dev wallet status
7. Top-10 holder %
8. Social links present
9. Pre-migration score
10. Best time-of-day stats

**Later:** repeat early-wallet classification, dev-linked side-wallet detection,
stalled-curve alerts, backtest by entry bonding zone, personal trade-journal analysis.

The first screen to build — the **Pre-Migration Edge Finder**: tokens between
35–75% bonded where bonding speed is accelerating, unique buyers are rising, dev is
still holding, top-holder concentration is falling, and social presence exists.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys
```

## Usage

```bash
python scanner.py
```

## Project spec

See [`pumpfunscanner.txt`](pumpfunscanner.txt) for the full design notes.
