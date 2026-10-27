"""Shared data + rendering code. Free data: Yahoo Finance (via yfinance, unofficial) and public RSS feeds."""
import html as _h

import pandas as pd
import streamlit as st
import yfinance as yf

try:
    import feedparser
except Exception:  # news is optional
    feedparser = None

NIFTY = ["^NSEI"]
SECTORS = {
    "auto": ["^CNXAUTO", "NIFTY_AUTO.NS"],
    "banks": ["^NSEBANK", "NIFTY_BANK.NS"],
    "it": ["^CNXIT", "NIFTY_IT.NS"],
    "pharma": ["^CNXPHARMA", "NIFTY_PHARMA.NS"],
    "fmcg": ["^CNXFMCG", "NIFTY_FMCG.NS"],
    "metals": ["^CNXMETAL", "NIFTY_METAL.NS"],
    "realty": ["^CNXREALTY", "NIFTY_REALTY.NS"],
    "capgoods": ["NIFTY_CAPITAL_GOODS.NS", "^CNXCAPGOODS"],  # often missing on Yahoo
}
D1M, D3M = 21, 63

FEEDS = {
    "Moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "Mint Markets": "https://www.livemint.com/rss/markets",
}


def _score3(x, lo, hi):
    return 0 if x < lo else 2 if x > hi else 1


def _pct(s, n):
    return (s.iloc[-1] / s.iloc[-1 - n] - 1) * 100


@st.cache_data(ttl=900, show_spinner=False)
def hist(sym):
    """Daily history with naive date index, or None."""
    try:
        h = yf.Ticker(sym).history(period="2y")
        if h is None or len(h) < 130:
            return None
        h = h[["Close", "Volume"]].dropna(subset=["Close"])
        h.index = pd.DatetimeIndex(h.index).tz_localize(None).normalize()
        return h[~h.index.duplicated(keep="last")]
    except Exception:
        return None


def get_close(cands):
    for t in cands:
        h = hist(t)
        if h is not None:
            return t, h["Close"]
    return None, None


@st.cache_data(ttl=900, show_spinner=False)
def sector_data():
    _, nifty = get_close(NIFTY)
    if nifty is None:
        return None
    c = nifty.iloc[-1]
    ma50, ma200 = nifty.rolling(50).mean().iloc[-1], nifty.rolling(200).mean().iloc[-1]
    trend = 2 if c > ma50 > ma200 else 0 if c < ma50 < ma200 else 1
    out = {"asof": str(nifty.index[-1].date()),
           "nifty": {"trend": trend, "ret3m": round(_pct(nifty, D3M), 1)},
           "sectors": {}, "failed": [], "stocks": {}}
    for key, cands in SECTORS.items():
        t, s = get_close(cands)
        if s is None:
            out["failed"].append(key)
            continue
        df = pd.concat([s, nifty], axis=1, join="inner").dropna()
        df.columns = ["sec", "nif"]
        if len(df) < 70:
            out["failed"].append(key)
            continue
        rs3 = _pct(df["sec"], D3M) - _pct(df["nif"], D3M)
        ratio = df["sec"] / df["nif"]
        rsl = (ratio.iloc[-1] / ratio.iloc[-21] - 1) * 100
        out["sectors"][key] = {"ret1m": round(_pct(df["sec"], D1M), 1), "ret3m": round(_pct(df["sec"], D3M), 1),
                               "rs3": round(rs3, 1), "rs3s": _score3(rs3, -2, 2), "rsls": _score3(rsl, -1, 1)}
    return out


def norm_symbol(s):
    s = s.strip().upper().replace(" ", "")
    return s if s.endswith(".NS") or s.endswith(".BO") or s.startswith("^") else s + ".NS"


@st.cache_data(ttl=900, show_spinner=False)
def stock_data(sym, sec):
    h = hist(sym)
    _, nifty = get_close(NIFTY)
    if h is None or nifty is None:
        return None
    c, v = h["Close"], h["Volume"].dropna()
    n3 = _pct(nifty, D3M)
    return {"sec": sec,
            "below": round((1 - c.iloc[-1] / c.tail(252).max()) * 100, 1),
            "ret3m": round(_pct(c, D3M), 1),
            "vs": round(_pct(c, D3M) - n3, 1),
            "dma": int(c.iloc[-1] > c.rolling(50).mean().iloc[-1]),
            "vol": round(v.tail(5).mean() / v.tail(50).mean(), 2) if len(v) >= 50 else 1.0,
            "price": round(float(c.iloc[-1]), 2)}


@st.cache_data(ttl=3600, show_spinner=False)
def fundamentals(sym):
    try:
        i = yf.Ticker(sym).info or {}
    except Exception:
        return {}
    keys = ["trailingPE", "returnOnEquity", "debtToEquity", "profitMargins", "revenueGrowth",
            "earningsGrowth", "operatingCashflow", "netIncomeToCommon", "longName"]
    return {k: i.get(k) for k in keys}


def fund_flags(f, sector):
    """Red/green flags from Yahoo fundamentals. Yahoo data can be missing or stale."""
    out, bank = [], sector == "banks"

    def add(c, t):
        out.append((c, t))
    roe = f.get("returnOnEquity")
    if roe is not None:
        roe *= 100
        add("pos" if roe >= 15 else "neg" if roe < 8 else "amb", f"ROE {roe:.1f}%")
    de = f.get("debtToEquity")
    if de is not None and not bank:
        de /= 100  # Yahoo gives percent
        add("pos" if de <= 0.5 else "neg" if de > 1.5 else "amb", f"Debt/Equity {de:.2f}")
    cfo, ni = f.get("operatingCashflow"), f.get("netIncomeToCommon")
    if cfo and ni and ni > 0 and not bank:
        q = cfo / ni
        add("pos" if q >= 0.8 else "neg" if q < 0.6 else "amb", f"CFO / PAT {q:.2f}" + (" (paper profit ka khatra)" if q < 0.6 else ""))
    for k, lab in (("revenueGrowth", "Revenue growth (latest)"), ("earningsGrowth", "Earnings growth (latest)")):
        if f.get(k) is not None:
            add("pos" if f[k] > 0 else "neg", f"{lab} {f[k] * 100:.1f}%")
    if f.get("profitMargins") is not None:
        add("amb", f"Profit margin {f['profitMargins'] * 100:.1f}%")
    if f.get("trailingPE") is not None:
        add("amb", f"P/E {f['trailingPE']:.1f} (apni history se compare karo)")
    return out


@st.cache_data(ttl=600, show_spinner=False)
def news(keyword=None, limit=8):
    if feedparser is None:
        return []
    items = []
    for src, url in FEEDS.items():
        try:
            for e in feedparser.parse(url).entries[:60]:
                t = e.get("title", "")
                if keyword and keyword.lower() not in (t + " " + e.get("summary", "")).lower():
                    continue
                items.append((t, e.get("link", ""), src))
        except Exception:
            pass
    return items[:limit]


# ===== DASHBOARD BANANE WALA HISSA (kuch mat badlo) =====
import html as _h

_NAMES = {"auto": "Auto", "banks": "Banks", "it": "IT", "pharma": "Pharma", "fmcg": "FMCG",
          "metals": "Metals", "realty": "Realty", "capgoods": "Capital Goods"}
_K = ["neg", "amb", "pos"]
_RL = ["gir rahi", "flat", "chadh rahi"]

_CSS = """
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
.mk{background:#EDF0F5;color:#14213D;font:15px/1.5 "Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;padding:14px;border-radius:14px;max-width:560px}
.mk *{box-sizing:border-box}
.mk h1{font-size:20px;margin:2px 0;font-weight:700}
.mk .sub{color:#5B6577;font-size:13px;margin:0 0 12px}
.mk .pos{--c:#1F7A55}.mk .amb{--c:#8A5A00}.mk .neg{--c:#B3382C}
.mk .hero{background:#fff;border:1px solid #D5DBE6;border-left:6px solid var(--c);border-radius:10px;padding:16px}
.mk .st{font-size:34px;font-weight:700;line-height:1.1;color:var(--c);margin:0 0 6px}
.mk .hero p{margin:0 0 6px}
.mk .mut{color:#5B6577;font-size:13px}
.mk .m{display:grid;grid-template-columns:104px 1fr 34px;gap:8px;align-items:center;font-size:13px;margin-top:8px}
.mk .trk{height:6px;border-radius:3px;background:#E7EAF0;position:relative}
.mk .trk i{position:absolute;top:-4px;width:4px;height:14px;border-radius:2px;background:#14213D;transform:translateX(-2px)}
.mk .trk b{position:absolute;left:50%;top:0;width:1px;height:6px;background:#5B6577}
.mk section{background:#fff;border:1px solid #D5DBE6;border-radius:10px;padding:14px;margin-top:14px}
.mk h2{font-size:16px;margin:0 0 2px;font-weight:700}
.mk .d{color:#5B6577;font-size:13px;margin:0 0 8px}
.mk details{border:1px solid #D5DBE6;border-radius:10px;margin-top:8px;padding:8px 12px}
.mk summary{cursor:pointer;display:grid;grid-template-columns:12px 1fr auto;gap:4px 10px;align-items:center;min-height:36px;list-style:none}
.mk summary::-webkit-details-marker{display:none}
.mk .dot{width:12px;height:12px;border-radius:50%;background:var(--c)}
.mk .nm{font-weight:600}
.mk .vs{font-weight:700;color:var(--c)}
.mk .bar{grid-column:1/-1;height:6px;border-radius:3px;background:#E7EAF0;position:relative}
.mk .bar i{position:absolute;top:0;bottom:0;border-radius:3px;background:var(--c)}
.mk .bar b{position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:#5B6577}
.mk .inner{margin-top:10px;font-size:14px}
.mk .stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;text-align:center;margin-bottom:8px}
.mk .stats span{display:block;color:#5B6577;font-size:12px}
.mk .fl{padding:8px 10px;border-radius:8px;font-size:13px;margin-top:6px}
.mk .fl.pos{background:#DDF1E7;color:#1F7A55}.mk .fl.amb{background:#FBEFD2;color:#8A5A00}.mk .fl.neg{background:#F8E3E0;color:#B3382C}
.mk .row3{display:grid;grid-template-columns:26px 1fr;gap:8px;margin-top:10px;font-size:14px}
.mk .num{width:22px;height:22px;border-radius:50%;background:#2F4B7C;color:#fff;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center}
.mk .na{opacity:.65;margin-top:8px;padding:10px 12px;border:1px dashed #9AA6BD;border-radius:10px;font-size:14px}
.mk .card{background:#fff;border:1px solid #D5DBE6;border-left:6px solid var(--c);border-radius:10px;padding:14px;margin-top:10px}
.mk .card .big{font-size:22px;font-weight:700;color:var(--c)}
</style>
"""


def _sg(v):
    return ("+" if v > 0 else "") + str(v)


def _why(x):
    s, l = x["rs3s"], x["rsls"]
    if s == 2 and l == 2:
        return "Leader: Nifty se aage aur aur tez ho raha hai. Isko pehle dekho."
    if s == 2:
        return "Nifty se aage hai, lekin RS line " + _RL[l] + ". Momentum thanda ho raha hai, naye entry mein savdhan."
    if s == 1:
        return ("Nifty ke barabar, par RS line chadh rahi. Improving ka early sign ho sakta hai." if l == 2
                else "Nifty ke saath chal raha hai. Koi khaas edge nahi.")
    return ("Kamzor: Nifty se peeche aur peeche hi ja raha hai. Abhi door raho." if l == 0
            else "Peeche hai lekin sudhar ke sign dikh rahe hain. Watchlist mein rakho, confirmation ka wait karo.")


def _meter(label, v):
    return (f'<div class="m"><span>{label}</span><div class="trk"><b></b><i style="left:{(v + 1) * 50:.0f}%"></i></div>'
            f'<span>{"+" if v > 0 else ""}{v:.1f}</span></div>')


def _stock(sym, x, sec):
    s = sec.get(x["sec"])
    p = 2 if x["below"] <= 10 else 0 if x["below"] > 40 else 1
    r = 2 if x["vs"] > 2 else 0 if x["vs"] < -2 else 1
    m = 2 if x["dma"] else 0
    ck = [s["rs3s"] if s else 1, p, r, m]
    g, rd = ck.count(2), ck.count(0)
    if s and s["rs3s"] == 0:
        v = ("Rukna", 0, "Sector kamzor hai, funnel yahin rukta hai.")
    elif g >= 3 and rd == 0:
        v = ("Dekhne layak", 2, "Price ke hisaab se strong. Ab Screener par ROCE aur debt dekho.")
    elif rd >= 2:
        v = ("Kamzor", 0, "Market is stock ko pasand nahi kar raha.")
    else:
        v = ("Wait", 1, "Mixed. Aur confirmation ka wait karo.")
    lab = {2: "Green", 1: "Dhyan", 0: "Red"}
    rows = [
        (ck[0], "Sector: " + (["kamzor", "barabar", "aage"][s["rs3s"]] if s else "data nahi")),
        (p, f'52 hafte ke high se {x["below"]}% neeche'),
        (r, f'3 mahine Nifty se {_sg(x["vs"])} point'),
        (m, "50 din ke average ke " + ("upar" if x["dma"] else "neeche")),
    ]
    flags = "".join(f'<div class="fl {_K[c]}">{lab[c]}: {t}</div>' for c, t in rows)
    name = _h.escape(sym.replace(".NS", ""))
    card = (f'<div class="card {_K[v[1]]}"><div class="mut">{_NAMES.get(x["sec"], x["sec"])}</div>'
            f'<div class="big">{name}: {v[0]}</div><div class="mut" style="margin-bottom:4px">{v[2]}</div>{flags}'
            f'<div class="mut" style="margin-top:8px">Volume (5 din / 50 din): {x["vol"]}</div></div>')
    return name, v, card


def render_html(d, show_stocks=True):
    n, sec = d["nifty"], d["sectors"]
    nt = n["trend"]
    ranked = sorted(sec, key=lambda z: -sec[z]["rs3"])
    green = [k for k in ranked if sec[k]["rs3s"] == 2]
    red = [k for k in ranked if sec[k]["rs3s"] == 0]
    adv = ["Risk kam, size chhota, sirf sabse strong sector par nazar.",
           "Wait karo, direction clear hone do.",
           "Risk lena theek, trend ke saath chalo."][nt]
    where = ["neeche", "beech mein", "upar"][nt]
    top = ranked[0]
    m_sec = sum(sec[k]["rs3s"] - 1 for k in sec) / len(sec)
    m_mom = sum(sec[k]["rsls"] - 1 for k in sec) / len(sec)

    o = [_CSS, '<div class="mk">', '<h1>Market Dashboard</h1>',
         f'<p class="sub">Data: {_h.escape(d["asof"])} ka closing, Yahoo Finance</p>']
    o.append(f'<div class="hero {_K[nt]}"><div class="st">Market: {["Weak", "Sideways", "Strong"][nt]}</div>'
             f'<p>Nifty 50 aur 200 din ke average ke {where}. 3 mahine: {_sg(n["ret3m"])}%</p>'
             f'<p class="mut">{len(green)} sector Nifty se aage, {len(red)} peeche. Sabse strong: '
             f'{_NAMES.get(top, top)} ({_sg(sec[top]["rs3"])}).</p><p class="mut">{adv}</p>'
             + _meter("Market", nt - 1) + _meter("Sector RS (avg)", m_sec) + _meter("RS momentum", m_mom) + '</div>')

    stocks = {sym: _stock(sym, x, sec) for sym, x in d.get("stocks", {}).items()}
    passed = [nm for nm, v, _ in stocks.values() if v[0] == "Dekhne layak"]
    foc = ", ".join(f"{_NAMES.get(k, k)} ({_sg(sec[k]['rs3'])})" for k in green[:2]) or "Koi clear leader nahi"
    o.append('<section><h2>Funnel</h2><p class="d">Upar se neeche, ek ek level (Lesson 13).</p>'
             f'<div class="row3"><div class="num">1</div><div><b>Market:</b> {["Weak", "Sideways", "Strong"][nt]}. {adv}</div></div>'
             f'<div class="row3"><div class="num">2</div><div><b>Focus sectors:</b> {foc}</div></div>'
             + (f'<div class="row3"><div class="num">3</div><div><b>Stocks jo pass hue:</b> '
                f'{", ".join(passed) if passed else "Abhi koi nahi"}</div></div>' if show_stocks else '')
             + '</section>')

    o.append('<section><h2>Sectors</h2><p class="d">Nifty se kitna aage ya peeche (3 mahine). Tap karo, detail khulegi.</p>')
    for k in ranked:
        x = sec[k]
        c = _K[x["rs3s"]]
        w = min(50, abs(x["rs3"]) / 20 * 50)
        side = "left" if x["rs3"] >= 0 else "right"
        o.append(f'<details class="{c}"><summary><span class="dot"></span><span class="nm">{_NAMES.get(k, k)}</span>'
                 f'<span class="vs">{_sg(x["rs3"])}</span><span class="bar"><b></b><i style="{side}:50%;width:{w:.0f}%"></i></span></summary>'
                 f'<div class="inner"><div class="stats"><div><span>1 mahina</span><b>{_sg(x["ret1m"])}%</b></div>'
                 f'<div><span>3 mahine</span><b>{_sg(x["ret3m"])}%</b></div><div><span>RS line</span><b>{_RL[x["rsls"]]}</b></div></div>'
                 f'{_why(x)}</div></details>')
    for k in d.get("failed", []):
        o.append(f'<div class="na">{_NAMES.get(k, k)}: data nahi aaya, manual dekho.</div>')
    o.append('</section>')

    if show_stocks:
        o.append('<section><h2>Stocks</h2><p class="d">Price ke hisaab se.</p>')
        o.extend(c for _, _, c in stocks.values()) if stocks else o.append('<div class="na">Koi stock nahi.</div>')
        o.append('</section>')

    o.append('<p class="mut" style="margin-top:14px">Hara = Nifty se 2+ aage, peela = barabar, laal = 2+ peeche. '
             'RS line = sector / Nifty ka ratio. Unofficial data, sirf padhai ke liye, buy ya sell call nahi.</p></div>')
    return "".join(o)
