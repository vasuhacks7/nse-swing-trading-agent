import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime

from config.settings import Settings
from agent.alert_engine import AlertEngine
from agent.improvement_engine import ImprovementEngine

st.set_page_config(page_title="Indian Swing Trading Agent", layout="wide", page_icon="📈")


@st.cache_resource
def get_settings():
    return Settings()


@st.cache_resource
def get_alert_engine():
    return AlertEngine(get_settings())


@st.cache_resource
def get_improvement_engine():
    return ImprovementEngine(get_settings())


def render_header():
    st.title("Self-Improving Indian Stock Market Agent")
    st.caption("NSE Swing Trading — All Stocks, 5 Strategies, Full Market Context")
    engine = get_alert_engine()

    try:
        snap = engine.get_market_snapshot()
        r = snap["regime"]
        f = snap["fii_dii"]
        ms = snap["market_open"]

        regime = r.get("regime", "?")
        regime_colors = {"BULLISH": "green", "BEARISH": "red", "SIDEWAYS": "orange"}
        rc = regime_colors.get(regime, "gray")

        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        mc1.metric("Market", "OPEN" if ms["open"] else "CLOSED")
        mc2.metric("Nifty Regime", regime)
        mc3.metric("Nifty RSI", r.get("nifty_rsi", "?"))
        mc4.metric("FII Sentiment", f.get("fii_sentiment", "?"))
        mc5.metric("Volatility", f"{r.get('volatility', '?')}%")
    except Exception:
        pass

    perf = engine.get_performance_summary()

    if perf["total_trades"] > 0:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total Trades", perf["total_trades"])
        c2.metric("Win Rate", f"{perf['win_rate']}%")
        c3.metric("Avg Return", f"{perf['avg_return_pct']:+.2f}%")
        c4.metric("Best Trade", f"{perf['best_trade']:+.2f}%")
        c5.metric("Total P&L", f"{perf['total_pnl_pct']:+.2f}%")
        c6.metric("Streak", perf.get("current_streak", "—"))


def render_alerts_tab():
    st.subheader("Today's Alerts")
    engine = get_alert_engine()

    if st.button("Generate Today's Alerts", type="primary"):
        with st.spinner("Scanning all NSE stocks across 5 strategies..."):
            alerts = engine.generate_daily_alerts()
            st.session_state["today_alerts"] = alerts

    if "today_alerts" in st.session_state:
        alerts = st.session_state["today_alerts"]
        if not alerts:
            st.info("No stocks met the criteria today. Markets may be sideways or overbought.")
        else:
            for a in alerts:
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                    with col1:
                        st.markdown(f"### {a['action']} {a['symbol']}")
                        st.caption(f"Strategy: **{a['strategy']}** | Score: **{a.get('signal_score', 0):.3f}**")
                    with col2:
                        st.metric("Entry", f"₹{a['entry_price']:.2f}")
                    with col3:
                        st.metric("Target", f"₹{a.get('target_price', 0):.2f}")
                    with col4:
                        rr = a.get('risk_reward_ratio', 0)
                        st.metric("R:R", f"1:{rr:.1f}" if rr else "—")

                    st.markdown(f"**Reasoning:** {a.get('reasoning', '')}")

                    tc, fc, pc = st.columns(3)
                    with tc:
                        st.caption(f"Technical: {a.get('technical_summary', '')}")
                    with fc:
                        st.caption(f"Fundamental: {a.get('fundamental_summary', '')}")
                    with pc:
                        qty = a.get('qty_pct', 1.0)
                        inst = a.get('installment', 1)
                        st.caption(f"Deploy: {qty * 100:.0f}% (installment {inst})")

                    st.caption(f"Stop Loss: ₹{a.get('stop_loss', 0):.2f} | Trailing SL active after 1R profit")

    open_alerts = engine.store.get_open_alerts()
    if not open_alerts.empty:
        st.subheader(f"Open Positions ({len(open_alerts)})")
        display_cols = ["date", "symbol", "strategy", "entry_price", "target_price",
                        "stop_loss", "trailing_stop", "highest_price",
                        "risk_reward_ratio", "qty_pct", "signal_score"]
        available = [c for c in display_cols if c in open_alerts.columns]
        st.dataframe(open_alerts[available], use_container_width=True)


def render_history_tab():
    st.subheader("Alert History & P&L Tracker")
    engine = get_alert_engine()
    alerts = engine.get_alert_history(200)

    if alerts.empty:
        st.info("No alerts generated yet. Run 'Generate Alerts' first.")
        return

    status_filter = st.selectbox("Filter", ["All", "OPEN", "CLOSED"])
    if status_filter != "All":
        alerts = alerts[alerts["status"] == status_filter]

    display_cols = ["date", "symbol", "strategy", "action", "entry_price",
                    "exit_price", "pnl_pct", "exit_reason", "holding_days", "status"]
    available = [c for c in display_cols if c in alerts.columns]
    st.dataframe(alerts[available], use_container_width=True)

    closed = alerts[alerts["status"] == "CLOSED"].copy()
    if not closed.empty and "pnl_pct" in closed.columns:
        closed = closed.sort_values("exit_date")
        closed["cumulative_pnl"] = closed["pnl_pct"].cumsum()

        fig = px.line(closed, x="exit_date", y="cumulative_pnl",
                      title="Cumulative P&L (%)", markers=True)
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        st.plotly_chart(fig, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            fig_dist = px.histogram(closed, x="pnl_pct", nbins=20,
                                     title="Return Distribution", color_discrete_sequence=["#1f77b4"])
            fig_dist.add_vline(x=0, line_dash="dash", line_color="red")
            st.plotly_chart(fig_dist, use_container_width=True)

        with col2:
            by_strategy = closed.groupby("strategy").agg(
                trades=("pnl_pct", "count"),
                avg_return=("pnl_pct", "mean"),
                win_rate=("pnl_pct", lambda x: (x > 0).mean() * 100),
            ).round(2)
            fig_bar = px.bar(by_strategy, y="avg_return", color="win_rate",
                             title="Avg Return by Strategy",
                             color_continuous_scale="RdYlGn")
            st.plotly_chart(fig_bar, use_container_width=True)


def render_scoreboard_tab():
    st.subheader("Strategy Scoreboard")
    imp = get_improvement_engine()
    scores = imp.compute_strategy_scores()

    if not scores:
        st.info("No data yet. Generate alerts and let trades close to see scores.")
        return

    rows = []
    for name, s in scores.items():
        rows.append({
            "Strategy": name,
            "Trades": s.get("total_alerts", 0),
            "Wins": s.get("winning_alerts", 0),
            "Losses": s.get("losing_alerts", 0),
            "Win Rate": f"{s.get('win_rate', 0):.1%}",
            "Avg Return": f"{s.get('avg_return_pct', 0):+.2f}%",
            "Avg Win": f"{s.get('avg_win_pct', 0):+.2f}%",
            "Avg Loss": f"{s.get('avg_loss_pct', 0):.2f}%",
            "Profit Factor": s.get("profit_factor", 0),
            "Weight": s.get("current_weight", 1.0),
        })

    if rows:
        df_scores = pd.DataFrame(rows)
        st.dataframe(df_scores, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(df_scores, x="Strategy", y="Profit Factor",
                         title="Profit Factor by Strategy",
                         color="Profit Factor", color_continuous_scale="Greens")
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            fig = px.bar(df_scores, x="Strategy", y="Weight",
                         title="Current Strategy Weights",
                         color="Weight", color_continuous_scale="Blues")
            st.plotly_chart(fig, use_container_width=True)

    score_history = imp.store.get_strategy_scores()
    if not score_history.empty:
        st.subheader("Weight Evolution Over Time")
        st.dataframe(score_history[["strategy", "win_rate", "avg_return_pct",
                                     "current_weight", "updated_at"]].head(30),
                     use_container_width=True)


def render_improvement_tab():
    st.subheader("Self-Improvement Engine")
    imp = get_improvement_engine()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Update Strategy Weights", type="primary"):
            with st.spinner("Computing strategy performance and adjusting weights..."):
                weights = imp.update_strategy_weights()
            st.success("Weights updated!")
            for name, w in weights.items():
                st.write(f"- **{name}**: {w:.2f}")

    with col2:
        if st.button("Run AI Reflection"):
            if not imp.llm_advisor:
                st.error("Set ANTHROPIC_API_KEY in .env to enable AI reflection.")
            else:
                with st.spinner("AI is analyzing your trading patterns..."):
                    analysis = imp.run_llm_reflection()
                if "error" in analysis:
                    st.error(f"Analysis failed: {analysis['error']}")
                else:
                    st.write("### Market Regime")
                    st.write(analysis.get("market_regime", "N/A"))

                    c1, c2 = st.columns(2)
                    with c1:
                        st.write("### Winning Patterns")
                        for p in analysis.get("winning_patterns", []):
                            st.write(f"- {p}")
                    with c2:
                        st.write("### Losing Patterns")
                        for p in analysis.get("losing_patterns", []):
                            st.write(f"- {p}")

                    st.write("### Key Insights")
                    for i in analysis.get("key_insights", []):
                        st.write(f"- {i}")

                    if analysis.get("risk_warnings"):
                        st.warning("Risk Warnings: " + " | ".join(analysis["risk_warnings"]))

    log = imp.store.get_improvement_log(20)
    if not log.empty:
        st.subheader("Improvement History")
        for _, entry in log.iterrows():
            with st.expander(f"{entry['date']} — {entry['type']}"):
                st.write(entry.get("description", ""))
                if entry.get("changes"):
                    try:
                        changes = json.loads(entry["changes"])
                        for c in changes:
                            st.write(f"- {c}")
                    except (json.JSONDecodeError, TypeError):
                        st.text(str(entry.get("changes", "")))
                if entry.get("llm_analysis"):
                    try:
                        st.json(json.loads(entry["llm_analysis"]))
                    except (json.JSONDecodeError, TypeError):
                        st.text(str(entry.get("llm_analysis", "")))


def main():
    render_header()

    tab1, tab2, tab3, tab4 = st.tabs([
        "Today's Alerts", "History & P&L", "Strategy Scoreboard", "Self-Improvement",
    ])

    with tab1:
        render_alerts_tab()
    with tab2:
        render_history_tab()
    with tab3:
        render_scoreboard_tab()
    with tab4:
        render_improvement_tab()


if __name__ == "__main__":
    main()
