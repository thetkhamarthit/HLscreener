"""
=========================================================
 hm_core.py — ตรรกะของ HM Breakout Screener (ไม่มี Streamlit)
 ---------------------------------------------------------
 จำลองเงื่อนไข "เข้าไม้แรก" ของ Pine Strategy
   Fractal Band · เข้า H×HM · Pyramid LS · ออก Lower 3 วัน

   HS : H[2] <  H[1] >= H[0]          LS : L[2] >  L[1] <= L[0]
   HM : ใช้กฎเดียวกันกับลำดับ HS       LM / LL : ใช้กฎเดียวกันกับลำดับ LS / LM
   ระดับ HM = HM ล่าสุดที่ยืนยันแล้ว (ขยับในแท่งที่ยืนยัน ไม่เปลี่ยนย้อนหลัง)

   Condition : EMA เร็ว > EMA กลาง > EMA ช้า
   Entry     : ta.crossover(high, HM) และ Condition ผ่าน

 ไม่จำลอง pyramid / exit / stop  (Strategy จริงจะไม่เข้าซ้ำถ้ายังถือไม้เดิมอยู่)
=========================================================
"""
import os
from datetime import datetime

import numpy as np
import pandas as pd

MARKETS = {
    "SET": {"label": "🇹🇭 SET (ไทย)", "tv_market": "thailand",
            "exchanges": ["SET", "MAI"], "currency": "THB",
            "tz": "Asia/Bangkok", "close_hm": (17, 0),
            "min_price": 1.0, "min_value_m": 5.0},
    "US": {"label": "🇺🇸 NASDAQ / NYSE", "tv_market": "america",
           "exchanges": ["NASDAQ", "NYSE"], "currency": "USD",
           "tz": "America/New_York", "close_hm": (16, 15),
           "min_price": 5.0, "min_value_m": 20.0},
}

TV_EMA_AVAILABLE = {5, 10, 20, 30, 50, 100, 200}   # EMA ที่ tradingview_screener มีให้

STATUS_ORDER = {"🟢 สัญญาณวันนี้": 0, "🔵 สัญญาณล่าสุด": 1, "🟡 ใกล้ HM": 2,
                "⚫ รอ": 3, "🔴 อยู่เหนือ HM แล้ว": 4, "⚪ EMA ไม่เรียง": 5,
                "— ข้อมูลไม่พอ": 6}


def bars_path(market):
    return f"hm_bars_{market}.parquet"


def result_path(market):
    return f"hm_scan_{market}.parquet"


def short(sym):
    return str(sym).split(":")[-1]


# =========================================================
# STAGE 1 : รายชื่อหุ้นทั้งตลาด + กรองเบื้องต้น
# =========================================================
def fetch_universe(market, ema_lens, min_price, min_value_m, use_cond=True):
    """
    ดึงหุ้นทั้งตลาดจาก tradingview_screener แล้วกรองสภาพคล่อง
    ถ้า EMA ทั้ง 3 ตัวมีใน TradingView screener จะกรอง EMA เรียงกันไว้ก่อนด้วย
    (ลดจำนวนหุ้นที่ต้องดึงแท่งเทียน) — ผลสุดท้ายคำนวณใหม่จากแท่งเทียนเสมอ
    คืน (DataFrame, error)
    """
    try:
        from tradingview_screener import Query
    except ImportError:
        return None, ("ไม่พบ tradingview_screener — ติดตั้งด้วย\n"
                      "python -m pip install --user tradingview-screener")

    m = MARKETS[market]
    cols = ["name", "description", "close", "volume", "average_volume_10d_calc",
            "sector", "type", "exchange"]
    pre_ema = use_cond and all(int(n) in TV_EMA_AVAILABLE for n in ema_lens)
    if pre_ema:
        cols += [f"EMA{int(n)}" for n in ema_lens]

    try:
        q = Query().select(*cols).set_markets(m["tv_market"]).limit(10000)
        try:
            _, df = q.get_scanner_data(timeout=60)
        except TypeError:
            _, df = q.get_scanner_data()
    except Exception as e:
        return None, f"ดึงรายชื่อหุ้นจาก TradingView ไม่สำเร็จ: {e}"

    if df is None or df.empty:
        return None, "TradingView ไม่ส่งข้อมูลกลับมา"

    df = df.copy()
    if "ticker" in df.columns:
        df["Symbol"] = df["ticker"].astype(str)
    else:
        ex = df["exchange"].astype(str) if "exchange" in df.columns else m["exchanges"][0]
        df["Symbol"] = ex + ":" + df["name"].astype(str)

    df = df[df["Symbol"].str.split(":").str[0].isin(m["exchanges"])]
    if "type" in df.columns:
        df = df[df["type"].astype(str).str.lower().isin(["stock", "dr", "fund", "nan"])
                | df["type"].isna()]

    for c in ["close", "average_volume_10d_calc"] + [c for c in df.columns
                                                     if c.startswith("EMA")]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["avg_value_m"] = df["close"] * df["average_volume_10d_calc"] / 1e6
    n_all = len(df)
    df = df[(df["close"] >= min_price) & (df["avg_value_m"] >= min_value_m)]
    n_liq = len(df)

    if pre_ema:
        a, b, c = [f"EMA{int(n)}" for n in ema_lens]
        if all(x in df.columns for x in (a, b, c)):
            df = df[(df[a] > df[b]) & (df[b] > df[c])]
        else:
            pre_ema = False          # TradingView ไม่ส่งคอลัมน์มา — ข้ามการคัดเบื้องต้น

    df.attrs["funnel"] = {"ทั้งตลาด": n_all, "ผ่านสภาพคล่อง": n_liq,
                          "ผ่าน EMA (คัดเบื้องต้น)": len(df) if pre_ema else None}
    keep = ["Symbol", "description", "sector", "close", "avg_value_m"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True), None


# =========================================================
# STAGE 2 : แท่งเทียนรายวัน (มี cache)
# =========================================================
BAR_COLS = ["Date", "Symbol", "open", "high", "low", "close", "volume", "fetched_at"]


def read_bars(market):
    p = bars_path(market)
    if not os.path.exists(p):
        return pd.DataFrame(columns=BAR_COLS)
    try:
        df = pd.read_parquet(p)
    except Exception:
        return pd.DataFrame(columns=BAR_COLS)
    df["Date"] = pd.to_datetime(df["Date"]).dt.normalize()
    df["fetched_at"] = pd.to_datetime(df.get("fetched_at"), errors="coerce")
    return df[[c for c in BAR_COLS if c in df.columns]]


def fetch_bars(symbols, market, n_bars=400, cache_hours=6.0, username=None,
               password=None, on_progress=None):
    """ดึงแท่งเทียนเฉพาะตัวที่ไม่มีใน cache หรือ cache เก่ากว่า cache_hours"""
    cache = read_bars(market)
    now = pd.Timestamp.now()
    if cache.empty:
        last_fetch = pd.Series(dtype="datetime64[ns]")
    else:
        last_fetch = cache.groupby("Symbol")["fetched_at"].max()

    todo = [s for s in symbols
            if s not in last_fetch.index or pd.isna(last_fetch[s])
            or (now - last_fetch[s]).total_seconds() / 3600 > cache_hours]

    log, new = [], []
    if todo:
        try:
            from tvDatafeed import TvDatafeed, Interval
        except ImportError:
            return cache, pd.DataFrame([{"Symbol": "-", "status": "ERROR",
                                         "error": "ไม่พบ tvDatafeed"}])
        tv = TvDatafeed(username=username or None, password=password or None)
        for i, sym in enumerate(todo, 1):
            ex, tk = sym.split(":", 1)
            try:
                h = tv.get_hist(symbol=tk, exchange=ex,
                                interval=Interval.in_daily, n_bars=int(n_bars))
                if h is None or len(h) == 0:
                    log.append({"Symbol": sym, "status": "NO_DATA", "error": ""})
                else:
                    h = h.reset_index()
                    h["Date"] = pd.to_datetime(h["datetime"]).dt.normalize()
                    h["Symbol"] = sym
                    h["fetched_at"] = now
                    new.append(h[[c for c in BAR_COLS if c in h.columns]])
                    log.append({"Symbol": sym, "status": "OK", "error": ""})
            except Exception as e:
                log.append({"Symbol": sym, "status": "ERROR", "error": str(e)[:150]})
            if on_progress:
                on_progress(i, len(todo), sym)

    if new:
        fresh = pd.concat(new, ignore_index=True)
        old = cache[~cache["Symbol"].isin(fresh["Symbol"].unique())]
        bars = pd.concat([x for x in (old, fresh) if not x.empty], ignore_index=True)
        bars = bars.drop_duplicates(["Date", "Symbol"], keep="last") \
                   .sort_values(["Symbol", "Date"])
        bars.to_parquet(bars_path(market), index=False)
    else:
        bars = cache
    return bars, pd.DataFrame(log)


def drop_unclosed(d, market, now=None):
    """ตัดแท่งของวันนี้ถ้าตลาดยังไม่ปิด (Pine ใช้ barstate.isconfirmed)"""
    if d.empty:
        return d
    m = MARKETS[market]
    now = now if now is not None else pd.Timestamp.now(tz=m["tz"])
    today = pd.Timestamp(now.date())
    hh, mm = m["close_hm"]
    if (now.hour, now.minute) < (hh, mm) and d["Date"].iloc[-1] >= today:
        return d.iloc[:-1]
    return d


# =========================================================
# ตรรกะ Pine
# =========================================================
def _check(pts, is_high):
    """3 จุดท้ายของชั้นล่าง : จุดกลางเป็นยอด/ก้นของชั้นถัดไปไหม"""
    if len(pts) < 3:
        return None
    a, b, c = pts[-3][1], pts[-2][1], pts[-1][1]
    ok = (b > a and b >= c) if is_high else (b < a and b <= c)
    return pts[-2] if ok else None


def fractal_levels(high, low):
    """
    เดินทีละแท่งเหมือน Pine — คืนระดับล่าสุดที่ยืนยันแล้ว ณ แต่ละแท่ง
    และรายการจุด (ตำแหน่งจุดจริง, ราคา, แท่งที่ยืนยัน)
    """
    h = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    n = len(h)
    out = {k: np.full(n, np.nan) for k in ["HS", "HM", "LS", "LM", "LL"]}
    pts = {k: [] for k in ["HS", "HM", "LS", "LM", "LL"]}
    cur = dict.fromkeys(out, np.nan)

    for t in range(2, n):
        if h[t - 1] > h[t - 2] and h[t - 1] >= h[t]:
            pts["HS"].append((t - 1, h[t - 1], t))
            cur["HS"] = h[t - 1]
            r = _check(pts["HS"], True)
            if r:
                pts["HM"].append((r[0], r[1], t))
                cur["HM"] = r[1]
        if lo[t - 1] < lo[t - 2] and lo[t - 1] <= lo[t]:
            pts["LS"].append((t - 1, lo[t - 1], t))
            cur["LS"] = lo[t - 1]
            r = _check(pts["LS"], False)
            if r:
                pts["LM"].append((r[0], r[1], t))
                cur["LM"] = r[1]
                r2 = _check(pts["LM"], False)
                if r2:
                    pts["LL"].append((r2[0], r2[1], t))
                    cur["LL"] = r2[1]
        for k in out:
            out[k][t] = cur[k]
    return out, pts


def ema(s, n):
    """ta.ema ของ Pine : alpha = 2/(n+1) เริ่มจากค่าแรก"""
    return pd.Series(s, dtype=float).ewm(span=int(n), adjust=False).mean().to_numpy()


def atr(h, lo, c, n):
    h, lo, c = (np.asarray(x, dtype=float) for x in (h, lo, c))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    return pd.Series(tr).ewm(alpha=1 / int(n), adjust=False).mean().to_numpy()


def analyze(d, cfg):
    """
    วิเคราะห์หุ้น 1 ตัว (d = แท่งเทียนเรียงตามวัน)
    คืน (สรุป dict, ข้อมูลรายแท่งสำหรับกราฟ)
    """
    e_f, e_m, e_s = cfg["emas"]
    d = d.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    if len(d) < max(30, int(e_s) // 4):
        return {"status": "— ข้อมูลไม่พอ", "bars": len(d)}, None

    h, lo, c = d["high"].to_numpy(float), d["low"].to_numpy(float), d["close"].to_numpy(float)
    lv, pts = fractal_levels(h, lo)
    e1, e2, e3 = ema(c, e_f), ema(c, e_m), ema(c, e_s)
    a = atr(h, lo, c, cfg.get("atr_len", 20))

    cond = (e1 > e2) & (e2 > e3) if cfg.get("use_cond", True) else np.ones(len(d), bool)
    hm = lv["HM"]
    hm_prev = np.r_[np.nan, hm[:-1]]
    h_prev = np.r_[np.nan, h[:-1]]
    with np.errstate(invalid="ignore"):
        cross = (h > hm) & (h_prev <= hm_prev)          # ta.crossover(high, bHM)
    entry = cross & cond

    d = d.assign(HS=lv["HS"], HM=hm, LS=lv["LS"], LM=lv["LM"], LL=lv["LL"],
                 ema_f=e1, ema_m=e2, ema_s=e3, atr=a, cond=cond,
                 cross=cross, entry=entry)
    d.attrs["pts"] = pts

    i = len(d) - 1
    hm_now = hm[i]
    sig_idx = np.flatnonzero(entry)
    age = int(i - sig_idx[-1]) if len(sig_idx) else None

    # นับวันที่ EMA เรียงติดกันจนถึงแท่งล่าสุด
    cond_days = 0
    for k in range(i, -1, -1):
        if not cond[k]:
            break
        cond_days += 1

    armed = bool(np.isfinite(hm_now) and h[i] <= hm_now)   # แท่งถัดไปยัง crossover ได้
    dist_pct = (hm_now / c[i] - 1) * 100 if np.isfinite(hm_now) else np.nan
    dist_atr = (hm_now - c[i]) / a[i] if np.isfinite(hm_now) and a[i] > 0 else np.nan
    hm_pt = pts["HM"][-1] if pts["HM"] else None

    if not np.isfinite(hm_now):
        status = "— ข้อมูลไม่พอ"
    elif not cond[i]:
        status = "⚪ EMA ไม่เรียง"
    elif entry[i]:
        status = "🟢 สัญญาณวันนี้"
    elif age is not None and age <= cfg.get("recent_days", 5):
        status = "🔵 สัญญาณล่าสุด"
    elif not armed:
        status = "🔴 อยู่เหนือ HM แล้ว"
    elif dist_pct <= cfg.get("near_pct", 3.0):
        status = "🟡 ใกล้ HM"
    else:
        status = "⚫ รอ"

    summary = {
        "status": status,
        "date": d["Date"].iloc[i],
        "close": c[i], "high": h[i],
        "HM": hm_now,
        "hm_date": d["Date"].iloc[hm_pt[0]] if hm_pt else pd.NaT,
        "hm_age": (i - hm_pt[2]) if hm_pt else None,
        "dist_pct": dist_pct,
        "dist_atr": dist_atr,
        "atr_pct": a[i] / c[i] * 100 if c[i] else np.nan,
        "LM": lv["LM"][i], "LL": lv["LL"][i],
        "below_lm": bool(np.isfinite(lv["LM"][i]) and c[i] < lv["LM"][i]),
        "cond": bool(cond[i]), "cond_days": cond_days,
        "armed": armed,
        "sig_age": age,
        "sig_date": d["Date"].iloc[sig_idx[-1]] if len(sig_idx) else pd.NaT,
        "sig_price": c[sig_idx[-1]] if len(sig_idx) else np.nan,
        "n_signals": int(len(sig_idx)),
        "ema_f": e1[i], "ema_m": e2[i], "ema_s": e3[i],
        "bars": len(d),
    }
    return summary, d


def scan(bars, symbols, cfg, market, info=None, drop_today=True):
    """วิเคราะห์ทุกตัว คืน DataFrame เรียงตามสถานะ + ระยะห่าง HM"""
    rows = []
    if bars is None or bars.empty:
        return pd.DataFrame()
    g = dict(tuple(bars.groupby("Symbol")))
    for s in symbols:
        d = g.get(s)
        if d is None:
            continue
        d = d.sort_values("Date").reset_index(drop=True)
        if drop_today:
            d = drop_unclosed(d, market)
        summ, _ = analyze(d, cfg)
        summ["Symbol"] = s
        rows.append(summ)
    if not rows:
        return pd.DataFrame()
    res = pd.DataFrame(rows)
    if info is not None and not info.empty:
        res = res.merge(info.drop(columns=["close"], errors="ignore"),
                        on="Symbol", how="left")
    res["ticker"] = res["Symbol"].map(short)
    res["_o"] = res["status"].map(STATUS_ORDER).fillna(9)
    res = res.sort_values(["_o", "sig_age", "dist_atr"], na_position="last") \
             .drop(columns="_o").reset_index(drop=True)
    res["scanned_at"] = datetime.now()
    return res
