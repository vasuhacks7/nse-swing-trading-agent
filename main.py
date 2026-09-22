import argparse
import logging
import sys
import json
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from agent.trading_agent import TradingAgent
from agent.alert_engine import AlertEngine
from agent.improvement_engine import ImprovementEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "agent.log"),
    ],
)
logger = logging.getLogger("main")


def cmd_market(settings: Settings, args):
    engine = AlertEngine(settings)
    snap = engine.get_market_snapshot()

    print(f"\n{'='*60}")
    print(f"  MARKET CONTEXT — {datetime.now():%B %d, %Y}")
    print(f"{'='*60}\n")

    ms = snap["market_open"]
    print(f"  Market Open:     {'YES' if ms['open'] else 'NO'} ({ms['reason']})")

    r = snap["regime"]
    regime = r.get("regime", "?")
    regime_icon = {"BULLISH": "+", "BEARISH": "-", "SIDEWAYS": "~"}.get(regime, "?")
    print(f"  Nifty Regime:    {regime_icon} {regime}")
    print(f"  Nifty Close:     {r.get('nifty_close', '?')}")
    print(f"  Nifty RSI:       {r.get('nifty_rsi', '?')}")
    print(f"  5-Day Return:    {r.get('return_5d', '?')}%")
    print(f"  20-Day Return:   {r.get('return_20d', '?')}%")
    print(f"  Volatility:      {r.get('volatility', '?')}% ({r.get('volatility_regime', '?')})")
    print(f"  EMA Status:      {'Above' if r.get('above_ema21') else 'Below'} 21 | "
          f"{'Above' if r.get('above_ema50') else 'Below'} 50 | "
          f"{'Above' if r.get('above_ema200') else 'Below'} 200")

    f = snap["fii_dii"]
    print(f"\n  FII Sentiment:   {f.get('fii_sentiment', '?')}")
    if f.get("fii_net_cr") is not None:
        print(f"  FII Net:         Rs.{f['fii_net_cr']:.0f} Cr")
        print(f"  DII Net:         Rs.{f.get('dii_net_cr', 0):.0f} Cr")
    print()


def cmd_alerts(settings: Settings, args):
    engine = AlertEngine(settings)
    print("\n Generating today's stock alerts...\n")
    alerts = engine.generate_daily_alerts()

    if not alerts:
        print("No stocks met the criteria today. Try again tomorrow.\n")
        return

    print(f"{'='*70}")
    print(f"  DAILY STOCK ALERTS — {datetime.now():%B %d, %Y}")
    print(f"{'='*70}")

    if alerts and alerts[0].get("market_regime"):
        print(f"  Market: {alerts[0]['market_regime']} | "
              f"FII: {alerts[0].get('fii_sentiment', '?')}")
    print()

    for i, a in enumerate(alerts, 1):
        rr = a.get('risk_reward_ratio', 0)
        qty = a.get('qty_pct', 1.0)
        print(f"  Alert #{i}: {a['action']} {a['symbol']}")
        print(f"  Strategy:    {a['strategy']}")
        print(f"  Sector:      {a.get('sector', '?')}")
        print(f"  Entry:       Rs.{a['entry_price']:.2f}")
        print(f"  Target:      Rs.{a.get('target_price', 0):.2f}")
        print(f"  Stop Loss:   Rs.{a.get('stop_loss', 0):.2f}")
        print(f"  R:R Ratio:   1:{rr:.1f}")
        print(f"  Deploy:      {qty * 100:.0f}% of position (installment {a.get('installment', 1)})")
        print(f"  Score:       {a.get('signal_score', 0):.3f}")
        print(f"  Reasoning:   {a.get('reasoning', '')}")
        print(f"  Technical:   {a.get('technical_summary', '')}")
        print(f"  Fundamental: {a.get('fundamental_summary', '')}")
        print(f"  {'-'*50}")
    print()


def cmd_track(settings: Settings, args):
    engine = AlertEngine(settings)
    print("\n Checking open alerts...\n")
    closed = engine.check_and_close_alerts()

    if closed:
        print("Trades closed today:")
        for c in closed:
            emoji = "+" if c["pnl_pct"] > 0 else "-"
            print(f"  {emoji} {c['symbol']}: {c['pnl_pct']:+.2f}% ({c['exit_reason']}, {c['holding_days']}d)")
    else:
        print("No trades closed today.")

    open_alerts = engine.store.get_open_alerts()
    if not open_alerts.empty:
        print(f"\nOpen positions ({len(open_alerts)}):")
        for _, a in open_alerts.iterrows():
            print(f"  {a['symbol']} @ Rs.{a['entry_price']:.2f} [{a['strategy']}] since {a['date']}")
    print()


def cmd_report(settings: Settings, args):
    engine = AlertEngine(settings)
    perf = engine.get_performance_summary()

    print(f"\n{'='*50}")
    print(f"  PERFORMANCE REPORT")
    print(f"{'='*50}\n")

    if perf["total_trades"] == 0:
        print("  No closed trades yet.\n")
        return

    print(f"  Total Trades:    {perf['total_trades']}")
    print(f"  Win Rate:        {perf['win_rate']}%")
    print(f"  Avg Return:      {perf['avg_return_pct']:+.2f}%")
    print(f"  Avg Win:         {perf['avg_win_pct']:+.2f}%")
    print(f"  Avg Loss:        {perf['avg_loss_pct']:.2f}%")
    print(f"  Best Trade:      {perf['best_trade']:+.2f}%")
    print(f"  Worst Trade:     {perf['worst_trade']:.2f}%")
    print(f"  Total P&L:       {perf['total_pnl_pct']:+.2f}%")
    print(f"  Avg Hold:        {perf['avg_holding_days']} days")
    print(f"  Current Streak:  {perf.get('current_streak', '—')}\n")

    imp_engine = ImprovementEngine(settings)
    scores = imp_engine.compute_strategy_scores()

    print(f"  {'Strategy':<25} {'Trades':>6} {'WinRate':>8} {'AvgRet':>8} {'Weight':>7}")
    print(f"  {'-'*55}")
    for name, s in scores.items():
        print(f"  {name:<25} {s.get('total_alerts',0):>6} "
              f"{s.get('win_rate',0):>7.1%} "
              f"{s.get('avg_return_pct',0):>+7.2f}% "
              f"{s.get('current_weight',1.0):>6.2f}")
    print()


def cmd_improve(settings: Settings, args):
    engine = ImprovementEngine(settings)
    print("\n Running self-improvement cycle...\n")
    result = engine.run_full_improvement_cycle()

    print(f"\n{'='*50}")
    print(f"  IMPROVEMENT RESULTS")
    print(f"{'='*50}\n")

    print("  Updated strategy weights:")
    for name, weight in result.get("new_weights", {}).items():
        print(f"    {name}: {weight:.2f}")

    reflection = result.get("reflection", {})
    if reflection and "error" not in reflection:
        print(f"\n  AI Insights:")
        for insight in reflection.get("key_insights", []):
            print(f"    - {insight}")
        if reflection.get("risk_warnings"):
            print(f"\n  Warnings:")
            for w in reflection["risk_warnings"]:
                print(f"    ! {w}")
    print()


def cmd_history(settings: Settings, args):
    engine = AlertEngine(settings)
    alerts = engine.get_alert_history(int(args.limit))

    if alerts.empty:
        print("\nNo alert history yet.\n")
        return

    print(f"\n{'Date':<12} {'Symbol':<15} {'Strategy':<22} {'Entry':>8} {'Exit':>8} {'P&L%':>7} {'Status':<10}")
    print("-" * 90)
    for _, a in alerts.iterrows():
        exit_price = f"{a['exit_price']:.2f}" if a.get("exit_price") else "—"
        pnl = f"{a['pnl_pct']:+.2f}%" if a.get("pnl_pct") is not None else "—"
        print(f"{a['date']:<12} {a['symbol']:<15} {a['strategy']:<22} "
              f"{a['entry_price']:>8.2f} {exit_price:>8} {pnl:>7} {a['status']:<10}")
    print()


def cmd_daily(settings: Settings, args):
    agent = TradingAgent(settings)
    result = agent.daily_run()
    cmd_alerts(settings, args)
    if result.get("closed_today"):
        print("Trades closed:")
        for c in result["closed_today"]:
            print(f"  {c['symbol']}: {c['pnl_pct']:+.2f}%")


def cmd_dashboard(settings: Settings, args):
    import subprocess
    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path),
                    "--server.port", str(args.port)])


def main():
    parser = argparse.ArgumentParser(
        description="Self-Improving Indian Stock Market Swing Trading Agent"
    )
    parser.add_argument("--config", default=None, help="Path to config YAML")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("market", help="Show market context: Nifty regime, FII/DII, sector strength")
    sub.add_parser("alerts", help="Generate today's 1-2 stock alerts")
    sub.add_parser("track", help="Check and close open alerts based on price")
    sub.add_parser("report", help="Show performance report and strategy scoreboard")
    sub.add_parser("improve", help="Run self-improvement cycle")
    sub.add_parser("daily", help="Full daily run: track + alerts + improve if due")

    hist = sub.add_parser("history", help="Show alert history")
    hist.add_argument("--limit", default="50")

    dash = sub.add_parser("dashboard", help="Launch Streamlit dashboard")
    dash.add_argument("--port", type=int, default=8501)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    settings = Settings(args.config)

    commands = {
        "market": cmd_market,
        "alerts": cmd_alerts,
        "track": cmd_track,
        "report": cmd_report,
        "improve": cmd_improve,
        "daily": cmd_daily,
        "history": cmd_history,
        "dashboard": cmd_dashboard,
    }
    commands[args.command](settings, args)


if __name__ == "__main__":
    main()
