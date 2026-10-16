"""
=========================================================
 HM Breakout Screener — หาหุ้นที่ใกล้เกิดสัญญาณ "เข้าไม้แรก"
 ของ Pine Strategy : Fractal Band · เข้า H×HM
 ---------------------------------------------------------
 รัน :  python -m streamlit run hm_screener_app.py --server.port 8503
 ต้องมี : hm_core.py · tradingview-screener · tradingview-datafeed
=========================================================
"""
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import hm_core as hc

st.set_page_config(page_title="HM Breakout Screener", page_icon="🎯",
                   layout="wide", initial_sidebar_state="expanded")
st.markdown("<style>.block-container{padding-top:2rem}</style>",
            unsafe_allow_html=True)

GRID = "#EEF1F5"

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.markdown("### 🎯 HM Breakout Screener")
    market = st.radio("ตลาด", list(hc.MARKETS), horizontal=True,
                      format_func=lambda k: hc.MARKETS[k]["label"])
    M = hc.MARKETS[market]

    st.markdown("**Market Condition**")
    use_cond = st.checkbox("EMA เร็ว > กลาง > ช้า", value=True)
    c1, c2, c3 = st.columns(3)
    e_f = c1.number_input("เร็ว", 1, 400, 50, 1)
    e_m = c2.number_input("กลาง", 1, 400, 100, 1)
    e_s = c3.number_input("ช้า", 1, 400, 200, 1)

    st.markdown("**สัญญาณ**")
    near_pct = st.slider("“ใกล้ HM” เมื่อราคาปิดห่างไม่เกิน (%)", 0.5, 15.0, 3.0, 0.5)
    recent_days = st.number_input("นับเป็น “สัญญาณล่าสุด” ภายใน (แท่ง)", 1, 30, 5, 1)
    atr_len = st.number_input("ATR", 2, 100, 20, 1)

    st.markdown(f"**สภาพคล่อง ({M['currency']})**")
    min_price = st.number_input("ราคาขั้นต่ำ", 0.0, 10000.0, float(M["min_price"]),
                                0.5, key=f"mp_{market}")
    min_val = st.number_input("มูลค่าซื้อขายเฉลี่ย 10 วัน (ล้าน)", 0.0, 100000.0,
                              float(M["min_value_m"]), 1.0, key=f"mv_{market}")

    with st.expander("ขั้นสูง"):
        max_syms = st.number_input("ดึงแท่งเทียนสูงสุด (ตัว)", 10, 2000, 300, 10)
        n_bars = st.number_input("จำนวนแท่งย้อนหลัง", 250, 2000, 500, 50,
                                 help="อย่างน้อย 2 เท่าของ EMA ช้า เพื่อให้ EMA ใกล้ TradingView")
        cache_h = st.number_input("ใช้ cache แท่งเทียนได้นาน (ชั่วโมง)", 0.0, 168.0, 6.0, 1.0)
        drop_today = st.checkbox("ไม่ใช้แท่งวันนี้ถ้าตลาดยังไม่ปิด", value=True,
                                 help="Pine คำนวณเฉพาะแท่งที่ปิดแล้ว (barstate.isconfirmed)")
        tv_user = st.text_input("TradingView username", "")
        tv_pass = st.text_input("TradingView password", "", type="password")

CFG = {"emas": (int(e_f), int(e_m), int(e_s)), "use_cond": use_cond,
       "near_pct": float(near_pct), "recent_days": int(recent_days),
       "atr_len": int(atr_len)}

# =========================================================
# HEADER + SCAN
# =========================================================
st.title("🎯 HM Breakout Screener")
st.caption("หาหุ้นที่**ใกล้เกิดสัญญาณเข้าไม้แรก** ของ Strategy "
           "“Fractal Band · เข้า H×HM” — High ตัดขึ้นเหนือ HM ล่าสุด "
           f"ขณะที่ EMA{e_f} > EMA{e_m} > EMA{e_s}")

b1, b2, b3 = st.columns([2, 2, 4])
run = b1.button("🔍 สแกนตลาด", type="primary", use_container_width=True)
rescore = b2.button("♻️ คำนวณใหม่จาก cache", use_container_width=True,
                    help="เปลี่ยนค่าตั้งแล้วคำนวณใหม่โดยไม่ดึงข้อมูล")

if run:
    stage = st.empty()
    prog = st.progress(0.0)
    stage.info("ดึงรายชื่อหุ้นทั้งตลาด...")
    uni, err = hc.fetch_universe(market, CFG["emas"], min_price, min_val, use_cond)
    if err:
        stage.error(err)
        st.stop()
    syms = uni["Symbol"].tolist()[:int(max_syms)]
    stage.info(f"คัดเบื้องต้นเหลือ {len(uni):,} ตัว — ดึงแท่งเทียน {len(syms):,} ตัว...")

    def _p(i, n, s):
        prog.progress(i / max(n, 1), text=f"แท่งเทียน {i}/{n} — {hc.short(s)}")

    bars, log = hc.fetch_bars(syms, market, n_bars, cache_h, tv_user, tv_pass, _p)
    res = hc.scan(bars, syms, CFG, market, uni, drop_today)
    res.attrs = {}
    res.to_parquet(hc.result_path(market), index=False)
    pd.Series(uni.attrs.get("funnel", {})).to_json(f"hm_funnel_{market}.json")
    st.session_state[f"log_{market}"] = log
    prog.empty()
    stage.empty()

if rescore:
    old = (pd.read_parquet(hc.result_path(market))
           if os.path.exists(hc.result_path(market)) else None)
    if old is None or old.empty:
        st.warning("ยังไม่มีผลสแกน — กดสแกนตลาดก่อน")
    else:
        info = old[[c for c in ["Symbol", "description", "sector", "avg_value_m"]
                    if c in old.columns]]
        res = hc.scan(hc.read_bars(market), old["Symbol"].tolist(), CFG, market,
                      info, drop_today)
        res.to_parquet(hc.result_path(market), index=False)

if not os.path.exists(hc.result_path(market)):
    st.info("ยังไม่มีผลสแกนของตลาดนี้ — กด **🔍 สแกนตลาด**")
    st.stop()

res = pd.read_parquet(hc.result_path(market))
if res.empty:
    st.warning("ไม่มีหุ้นที่ผ่านการคัดเบื้องต้น — ลองลดเกณฑ์สภาพคล่อง")
    st.stop()

with b3:
    st.caption(f"สแกนล่าสุด {pd.Timestamp(res['scanned_at'].iloc[0]):%d %b %Y %H:%M} · "
               f"แท่งล่าสุด {pd.to_datetime(res['date']).max():%d %b %Y}")

# =========================================================
# สรุป
# =========================================================
cnt = res["status"].value_counts()
k = st.columns(5)
for col, s in zip(k, ["🟢 สัญญาณวันนี้", "🔵 สัญญาณล่าสุด", "🟡 ใกล้ HM",
                      "⚫ รอ", "🔴 อยู่เหนือ HM แล้ว"]):
    col.metric(s, f"{int(cnt.get(s, 0)):,} ตัว")

fn_path = f"hm_funnel_{market}.json"
if os.path.exists(fn_path):
    fn = pd.read_json(fn_path, typ="series").dropna()
    st.caption(" → ".join(f"{k} {int(v):,}" for k, v in fn.items())
               + f" → วิเคราะห์ {len(res):,} ตัว")

# =========================================================
# ตาราง
# =========================================================
st.divider()
f1, f2, f3 = st.columns([4, 2, 3])
show = f1.multiselect("สถานะ", list(hc.STATUS_ORDER),
                      default=["🟢 สัญญาณวันนี้", "🔵 สัญญาณล่าสุด", "🟡 ใกล้ HM"])
hide_lm = f2.checkbox("ซ่อนตัวที่ปิดใต้ LM", value=False,
                      help="ราคาปิดต่ำกว่าก้นชั้นกลาง = โครงสร้างอ่อน")
secs = sorted(res["sector"].dropna().astype(str).unique()) if "sector" in res else []
pick_sec = f3.multiselect("กลุ่มอุตสาหกรรม", secs, placeholder="ทุกกลุ่ม")

v = res[res["status"].isin(show)] if show else res
if hide_lm:
    v = v[~v["below_lm"].fillna(False)]
if pick_sec:
    v = v[v["sector"].astype(str).isin(pick_sec)]

tbl = pd.DataFrame({
    "หุ้น": v["ticker"],
    "สถานะ": v["status"],
    "ราคาปิด": v["close"],
    "HM": v["HM"],
    "ถึง HM %": v["dist_pct"],
    "ถึง HM (ATR)": v["dist_atr"],
    "สัญญาณ (แท่งก่อน)": v["sig_age"],
    "ราคาวันสัญญาณ": v["sig_price"],
    "HM ยืนยันมา (แท่ง)": v["hm_age"],
    "EMA เรียงมา (แท่ง)": v["cond_days"],
    "ATR %": v["atr_pct"],
    "LM": v["LM"],
    "มูลค่า/วัน (ล้าน)": v.get("avg_value_m"),
    "กลุ่ม": v.get("sector"),
})
st.dataframe(
    tbl, use_container_width=True, hide_index=True, height=420,
    column_config={
        "ราคาปิด": st.column_config.NumberColumn(format="%.2f"),
        "HM": st.column_config.NumberColumn(format="%.2f",
              help="ยอดชั้นกลางล่าสุดที่ยืนยันแล้ว — ตั้ง Buy Stop เหนือระดับนี้"),
        "ถึง HM %": st.column_config.NumberColumn(format="%+.2f",
              help="ราคาปิดต้องขึ้นอีกกี่ % ถึง HM (ติดลบ = อยู่เหนือแล้ว)"),
        "ถึง HM (ATR)": st.column_config.NumberColumn(format="%.2f",
              help="ระยะถึง HM เป็นเท่าของ ATR — ยิ่งน้อยยิ่งมีโอกาสแตะเร็ว"),
        "สัญญาณ (แท่งก่อน)": st.column_config.NumberColumn(format="%d"),
        "ราคาวันสัญญาณ": st.column_config.NumberColumn(format="%.2f"),
        "ATR %": st.column_config.NumberColumn(format="%.2f"),
        "LM": st.column_config.NumberColumn(format="%.2f"),
        "มูลค่า/วัน (ล้าน)": st.column_config.NumberColumn(format="%.1f"),
    })
st.caption("**ถึง HM (ATR) ≤ 1** = ราคาแกว่งปกติวันเดียวก็แตะ HM ได้ · "
           "🔴 = High เคยอยู่เหนือ HM แล้ว ต้องรอ HM ใหม่หรือราคาย่อลงก่อนจึงเกิด crossover ใหม่")

# ---- ส่งออก ----
e1c, e2c = st.columns([2, 5])
e1c.download_button("⬇️ CSV", v.to_csv(index=False).encode("utf-8-sig"),
                    f"hm_scan_{market}.csv", "text/csv", use_container_width=True)
with e2c.expander("📋 Watchlist สำหรับ TradingView"):
    wl = ",".join(v["Symbol"].tolist())
    st.code(wl or "—", language=None)
    st.download_button("⬇️ ไฟล์ .txt (Import list ใน TradingView)", wl.encode(),
                       f"hm_watchlist_{market}.txt", "text/plain")

# =========================================================
# กราฟ
# =========================================================
st.divider()
if v.empty:
    st.info("ไม่มีหุ้นตามตัวกรอง")
    st.stop()

g1, g2, g3 = st.columns([3, 2, 3])
sym = g1.selectbox("กราฟ", v["Symbol"].tolist(),
                   format_func=lambda s: f"{hc.short(s)}  {res.set_index('Symbol').at[s, 'status']}")
lookback = g2.select_slider("ช่วง", [60, 120, 180, 260, 400], value=180)
with g3:
    o1, o2, o3 = st.columns(3)
    sh_ema = o1.checkbox("EMA", True)
    sh_hs = o2.checkbox("HS/LS", False)
    sh_ll = o3.checkbox("LM/LL", True)

bars = hc.read_bars(market)
d = bars[bars["Symbol"] == sym].sort_values("Date").reset_index(drop=True)
if drop_today:
    d = hc.drop_unclosed(d, market)
summ, dd = hc.analyze(d, CFG)
if dd is None:
    st.warning("ข้อมูลไม่พอ")
    st.stop()

pts = dd.attrs["pts"]
start = max(0, len(dd) - int(lookback))
w = dd.iloc[start:]
X = lambda idx: dd["Date"].iloc[idx]  # noqa: E731

fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2],
                    vertical_spacing=0.03)
fig.add_trace(go.Candlestick(x=w["Date"], open=w["open"], high=w["high"], low=w["low"],
                             close=w["close"], name=hc.short(sym),
                             increasing_line_color="rgba(38,166,154,.75)",
                             decreasing_line_color="rgba(239,83,80,.75)"), 1, 1)
if sh_ema:
    for col, nm, colr in [("ema_f", f"EMA{e_f}", "#EF5350"), ("ema_m", f"EMA{e_m}", "#26C6DA"),
                          ("ema_s", f"EMA{e_s}", "#546E7A")]:
        fig.add_scatter(x=w["Date"], y=w[col], name=nm, line=dict(color=colr, width=1.3),
                        row=1, col=1)
fig.add_scatter(x=w["Date"], y=w["HM"], name="HM", line=dict(color="#F57C00", width=2,
                shape="hv"), row=1, col=1)
if sh_ll:
    fig.add_scatter(x=w["Date"], y=w["LM"], name="LM", line=dict(color="#558B2F", width=2,
                    shape="hv"), row=1, col=1)
    fig.add_scatter(x=w["Date"], y=w["LL"], name="LL", line=dict(color="#D32F2F", width=2.5,
                    shape="hv"), row=1, col=1)

def _pts(key, color, size, up):
    p = [x for x in pts[key] if x[0] >= start]
    if p:
        fig.add_scatter(x=[X(i) for i, _, _ in p], y=[val for _, val, _ in p], mode="markers",
                        name=key, marker=dict(symbol="circle-open", size=size, color=color,
                                              line=dict(width=2)), row=1, col=1)

_pts("HM", "#F57C00", 12, True)
if sh_hs:
    _pts("HS", "#5C6BC0", 7, True)
    _pts("LS", "#5C6BC0", 7, False)
if sh_ll:
    _pts("LM", "#558B2F", 12, False)

e = w[w["entry"]]
if not e.empty:
    fig.add_scatter(x=e["Date"], y=e["low"] * 0.985, mode="markers", name="เข้าไม้แรก (H>HM)",
                    marker=dict(symbol="triangle-up", size=13, color="#00C853"), row=1, col=1)
x2 = w[w["cross"] & ~w["entry"]]
if not x2.empty:
    fig.add_scatter(x=x2["Date"], y=x2["low"] * 0.985, mode="markers",
                    name="ทะลุ HM แต่ EMA ไม่เรียง",
                    marker=dict(symbol="triangle-up-open", size=11, color="#9E9E9E"),
                    row=1, col=1)

if np.isfinite(summ["HM"]):
    fig.add_hline(y=summ["HM"], line=dict(color="#F57C00", dash="dot", width=1),
                  annotation_text=f"Buy Stop > {summ['HM']:,.2f}",
                  annotation_position="top left", row=1, col=1)

fig.add_bar(x=w["Date"], y=w["volume"], name="Volume", marker_color="rgba(120,120,120,.45)",
            row=2, col=1)
gaps = [x.strftime("%Y-%m-%d") for x in pd.date_range(w["Date"].min(), w["Date"].max())
        if x.weekday() < 5 and x not in set(w["Date"])]
fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])] + ([dict(values=gaps)] if gaps else []),
                 showgrid=True, gridcolor=GRID)
fig.update_yaxes(showgrid=True, gridcolor=GRID, side="right")
fig.update_layout(height=620, margin=dict(l=10, r=60, t=30, b=20), plot_bgcolor="white",
                  xaxis_rangeslider_visible=False, hovermode="x unified",
                  legend=dict(orientation="h", y=1.04, x=0))
st.plotly_chart(fig, use_container_width=True)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("สถานะ", summ["status"])
m2.metric("HM", f"{summ['HM']:,.2f}", f"{summ['dist_pct']:+.2f}% จากราคาปิด", delta_color="off")
m3.metric("ระยะถึง HM", f"{summ['dist_atr']:.2f} ATR", f"ATR {summ['atr_pct']:.2f}%",
          delta_color="off")
m4.metric("EMA เรียงมาแล้ว", f"{summ['cond_days']} แท่ง")
m5.metric("สัญญาณเข้าในข้อมูลนี้", f"{summ['n_signals']} ครั้ง",
          (f"ล่าสุด {summ['sig_age']} แท่งก่อน" if summ["sig_age"] is not None else "ยังไม่เคย"),
          delta_color="off")

with st.expander("ℹ️ วิธีอ่าน"):
    st.markdown(f"""
- **🟢 สัญญาณวันนี้** — แท่งล่าสุดเกิด `High ตัดขึ้นเหนือ HM` ขณะ EMA เรียง ตรงกับลูกศรเข้าไม้แรกใน TradingView
- **🔵 สัญญาณล่าสุด** — เกิดภายใน {recent_days} แท่งที่ผ่านมา
- **🟡 ใกล้ HM** — EMA เรียงแล้ว High ยังไม่เกิน HM และราคาปิดห่าง HM ไม่เกิน {near_pct}% → ตั้ง **Buy Stop เหนือ HM** ได้เลย
- **🔴 อยู่เหนือ HM แล้ว** — High เคยขึ้นไปเหนือ HM แล้ว ต้องรอ HM ตัวใหม่ยืนยัน หรือราคาย่อลงใต้ HM ก่อน จึงจะเกิด crossover ใหม่
- Strategy จริงจะ**ไม่เข้าถ้ายังถือไม้เดิมอยู่** แอปนี้ไม่ได้จำลองการออก หุ้นที่ขึ้น 🟢 อาจไม่มีลูกศรใน TradingView ถ้าตอนนั้น Strategy ยังถือไม้ก่อนหน้า
- จุด HM ช่วงต้นข้อมูลอาจต่างจาก TradingView เล็กน้อย เพราะเริ่มนับจากแท่งแรกที่ดึงมา ({n_bars} แท่ง)
""")
