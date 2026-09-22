# Self-Improving Indian Stock Market Swing Trading Agent

## What It Does
Scans ALL NSE-listed stocks (~2000+), checks market regime and institutional flows, runs 5 parallel strategies, and picks the 1-2 best setups daily. Tracks every alert's P&L with trailing stop-losses, and self-improves by promoting winning strategies and demoting losers. Inspired by Apoorv's swing trading approach (hashtaghammer).

## Architecture
- `config/` — YAML config with dynamic universe scanning, 5 strategy configs, risk params
- `data/nse_universe.py` — Fetches all NSE symbols dynamically, caches weekly, pre-filters by volume/price
- `data/market_context.py` — Nifty regime (BULLISH/BEARISH/SIDEWAYS), FII/DII flows, NSE holiday calendar
- `data/earnings_calendar.py` — Skips stocks with results within 5 days
- `data/circuit_check.py` — Detects stocks at upper/lower circuit limits
- `data/sector_strength.py` — Ranks sectors by momentum, boosts/penalizes picks accordingly
- `data/fetcher.py` — Yahoo Finance for NSE stocks (.NS), OHLCV + fundamentals (P/E, ROE, D/E, growth)
- `data/store.py` — SQLite: alerts (with trailing SL, installments), strategy scores, improvement log, premium picks
- `data/apoorv_tracker.py` — Expert channel scanner: scrapes public TradingView analysis posts, parses stock symbols, deduplicates, stores in DB
- `data/preprocessor.py` — Technical indicators (RSI, MACD, Bollinger, ADX, Stochastic, EMAs, ATR)
- `data/advanced_analysis.py` — Fibonacci retracement/extensions, supply/demand zones, trendline detection, confluence scoring
- `strategy/` — 5 independent strategies, each enforces minimum 1:2 R:R:
  - `momentum_breakout.py` — 20-day high breakout with volume surge (1:3 R:R)
  - `mean_reversion.py` — RSI oversold + Bollinger lower band + strong fundamentals (1:2+ R:R)
  - `macd_rsi_confluence.py` — MACD crossover + RSI in buy zone (1:2.5 R:R)
  - `fundamental_value.py` — Low P/E, high ROE, low debt, growing revenue + technical confirmation (1:2 R:R)
  - `trend_following.py` — EMA alignment + ADX strength + pullback entry (1:3 R:R)
- `strategy/manager.py` — Runs all strategies, applies weights, returns top picks
- `agent/alert_engine.py` — Orchestrates all 6 pre-checks + strategy scan + quality gate
- `agent/improvement_engine.py` — Strategy scoreboard, weight adjustment, LLM reflection
- `agent/trading_agent.py` — Orchestrates daily workflow
- `reflection/llm_advisor.py` — Claude analyzes trade patterns, suggests weight/param changes
- `agent/paper_trader.py` — Paper trading engine with virtual ₹10L portfolio, auto-trades based on confluence signals
- `agent/apoorv_learner.py` — Cross-validates expert picks with our 12-point confluence engine, tracks patterns, generates suggestions
- `dashboard/app.py` — Streamlit UI with 4 tabs + market context header
- `web/app.py` — FastAPI web app with dark theme UI + JSON API
- `web/templates/` — Jinja2 templates: dashboard, analysis, paper trading, history, scoreboard, premium picks
- `web/static/style.css` — Dark theme CSS
- `notifications/telegram_bot.py` — Telegram push notifications for alerts, closes, summaries
- `scheduler.py` — APScheduler for automated daily runs (IST timezone)
- `Dockerfile` + `docker-compose.yml` — Containerized deployment (web + scheduler)
- `deploy/` — AWS EC2 setup script + Nginx config

## India-Specific Features
1. **Market Regime Filter** — Checks Nifty 50 EMA alignment, RSI, returns. In BEARISH regime, quality bar is raised +0.10
2. **FII/DII Flow Tracking** — Fetches institutional activity from NSE. Heavy FII selling raises min score
3. **Earnings Calendar** — Auto-skips stocks with results within 5 days
4. **Circuit Limit Detection** — Rejects stocks at/near upper circuit (can't buy) or lower circuit
5. **NSE Holiday Calendar** — Won't run on weekends or NSE holidays (2025-2026 calendar built in)
6. **Sector Rotation** — Ranks sectors by momentum, gives +5% score boost to strong sectors, -5% to weak

## Apoorv-Inspired Features
- **Trailing Stop Loss** — After price moves 1R in profit, SL trails at 3% below highest price
- **R:R Based Targets** — All strategies enforce minimum 1:2 risk-reward ratio
- **Installment Entries** — Deploy 50% initially, add remaining on confirmation
- **Position Sizing** — Scale up after 5+ win streak, scale down after 2+ losses
- **No-Trade Days** — If best pick scores below 0.70, skip the day entirely

## Daily Workflow
1. `python main.py daily` — Full daily run:
   - Check if market is open (skip weekends/holidays)
   - Analyze Nifty regime + FII/DII flows → adjust quality thresholds
   - Check open alerts → update trailing stops → close if target/SL/max-hold hit
   - Scan all NSE stocks → filter circuits → filter earnings → sector boost → quality gate
   - Generate top 1-2 alerts (or none if quality is low)
   - Auto-run improvement cycle if review interval passed

## Commands
```bash
python main.py market     # Show Nifty regime, FII/DII, volatility (no trades)
python main.py alerts     # Generate today's 1-2 stock picks
python main.py track      # Check open positions, update trailing stops, close if criteria met
python main.py report     # Performance report + strategy scoreboard + streak info
python main.py improve    # Force self-improvement cycle
python main.py history    # Show full alert history with P&L
python main.py dashboard  # Launch Streamlit web UI
```

## Self-Improvement Loop
1. Track every alert: entry, exit, P&L, holding period, strategy used, R:R achieved
2. Score each strategy: win rate, avg return, profit factor
3. Promote strategies with >55% win rate (increase weight up to 3x)
4. Demote strategies with <35% win rate (decrease weight down to 0.2x)
5. LLM reflection: Claude analyzes patterns, suggests parameter tweaks
6. All changes logged in improvement_log table

## Web App
```bash
python -m uvicorn web.app:app --host 0.0.0.0 --port 8000  # Start FastAPI server
python scheduler.py                                          # Start automated scheduler
```

Routes: `/` (dashboard), `/analysis?symbol=X` (chart analysis + auto paper trade), `/paper-trading` (virtual portfolio), `/history`, `/scoreboard`, `/premium-picks` (expert picks tracker), `/generate` (trigger scan)
API: `/api/alerts`, `/api/generate`, `/api/track`, `/api/market`, `/api/performance`, `/api/scoreboard`, `/api/analyze/{symbol}`, `/api/paper-portfolio`, `/api/paper-track`, `/api/apoorv/scan`, `/api/apoorv/picks`, `/api/apoorv/track`, `/api/apoorv/suggestions`, `/api/apoorv/learn`

## Analysis Engine (Apoorv-Style)
Enter any NSE symbol on `/analysis` to get:
1. **Fibonacci Retracement** — Auto-detects swing high/low, draws 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100% levels
2. **Fibonacci Extensions** — 127.2%, 161.8%, 200%, 261.8% targets
3. **Supply/Demand Zones** — Detects price zones where reversals happened repeatedly
4. **Trendline Detection** — Ascending support and descending resistance from swing points
5. **Confluence Scoring** — Scores 0-7 based on how many factors align (Fib + zones + trendlines + EMA + RSI)
6. **Auto Paper Trade** — If confluence >= 2 with demand/support alignment, auto-buys with 10% of virtual capital
7. **Interactive Chart** — Candlestick chart (Lightweight Charts) with Fib levels, entry/target/SL, zones overlaid

## Premium Picks (Expert Channel Scanner)
Scans public expert analysis channels for stock picks, cross-validates with our engine:
1. **Channel Scraper** — Fetches messages from public sources, extracts stock symbols from TradingView analysis links
2. **Symbol Parser** — Detects NSE symbols from TradingView URLs, direct mentions (NSE:SYMBOL, #SYMBOL), and trade recommendations
3. **Deduplication** — Skips pinned/duplicate messages, stores only unique symbols per scan
4. **Cross-Validation** — Runs each pick through our 12-point confluence engine, assigns our own BUY/WATCH/NEUTRAL signal
5. **Performance Tracking** — Tracks entry/exit prices, P&L, win rate, compares validated vs unvalidated picks
6. **Learning Engine** — Analyzes patterns in winning picks, compares confluence scores, generates insights
7. **Scheduler** — Auto-scans at 9:00 AM IST daily before market opens

## LLM Backend (AWS Bedrock)
Uses AWS Bedrock for Claude LLM calls (self-improvement reflection). Falls back to direct Anthropic API if no AWS config.
- **Bedrock (production)**: Set `AWS_REGION` in `.env`. EC2 instance must have IAM role with `bedrock:InvokeModel` permission (see `deploy/iam-policy.json`)
- **Direct API (local dev)**: Set `ANTHROPIC_API_KEY` in `.env` instead
- Model: `claude-sonnet-5` (configurable in `config/default_config.yaml` under `reflection.model`)
- Code: `reflection/llm_advisor.py` — auto-detects backend, resolves Bedrock model IDs

## Deployment (AWS EC2)
```bash
# Option A: Full automated launch from local machine (creates IAM role, SG, EC2)
bash deploy/aws-launch.sh ap-south-1

# Option B: Manual setup on existing EC2 Ubuntu instance
bash deploy/setup.sh           # Install Docker, Nginx, verify IAM
cp .env.example .env && nano .env  # Set AWS_REGION + Telegram tokens
docker compose up -d --build   # Start web + scheduler containers
```

### Deploy files
- `deploy/aws-launch.sh` — One-shot: creates IAM role, security group, launches EC2 instance
- `deploy/setup.sh` — On-instance: installs Docker, Nginx, verifies Bedrock access
- `deploy/iam-policy.json` — IAM policy granting `bedrock:InvokeModel` on Anthropic models
- `deploy/nginx.conf` — Nginx reverse proxy config
- `Dockerfile` — Python 3.11 slim, 2 uvicorn workers
- `docker-compose.yml` — web (port 8000) + scheduler, shared DB volume, health checks

## Telegram Setup
1. Message @BotFather on Telegram → /newbot → get bot token
2. Add bot to your channel/group
3. Get chat ID via @userinfobot or @getidsbot
4. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env

## Setup
### Local Development
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env`, add `ANTHROPIC_API_KEY` + Telegram tokens
3. `python main.py market` to check market context
4. `python main.py alerts` to generate first alerts

### AWS Production
1. Enable Claude models in AWS Bedrock console (region: ap-south-1 or your preferred)
2. `bash deploy/aws-launch.sh ap-south-1` (from local machine with AWS CLI)
3. SSH into instance, run `bash deploy/setup.sh`
4. Create `.env` with `AWS_REGION=ap-south-1` + Telegram tokens
5. `docker compose up -d --build`
6. Access at `http://<EC2-public-ip>`
