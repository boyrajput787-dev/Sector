import html as h

import streamlit as st
import streamlit.components.v1 as components

from core import (_CSS, _NAMES, _stock, fund_flags, fundamentals, news, norm_symbol,
                  sector_data, stock_data)

st.set_page_config(page_title="Stock Check", page_icon="🔎", layout="centered")
st.title("Stock Check")

c1, c2 = st.columns([2, 1])
raw = c1.text_input("NSE symbol", value="TCS", help="Jaise TCS, MARUTI, INFY")
keys = list(_NAMES.keys())[:-1]
sec = c2.selectbox("Sector", keys, format_func=lambda k: _NAMES[k])

if st.button("Data refresh karo"):
    st.cache_data.clear()
    st.rerun()

sym = norm_symbol(raw)
with st.spinner("Data aa raha hai..."):
    d = sector_data()
    x = stock_data(sym, sec)

if d is None or x is None:
    st.error("Data nahi mila. Symbol check karo (jaise TCS) ya 1-2 minute baad dobara try karo.")
    st.stop()

name, verdict, card = _stock(sym, x, d["sectors"])
st.markdown(f"**{h.escape(sym)}** | Price ₹{x['price']}")
components.html(_CSS + '<div class="mk">' + card + '</div>', height=430, scrolling=True)

st.subheader("Fundamentals (Yahoo ka data)")
f = fundamentals(sym)
flags = fund_flags(f, sec)
lab = {"pos": "Green", "amb": "Dhyan", "neg": "Red"}
if flags:
    body = "".join(f'<div class="fl {c}">{lab[c]}: {h.escape(t)}</div>' for c, t in flags)
    components.html(_CSS + '<div class="mk">' + body + '</div>', height=60 + 48 * len(flags), scrolling=True)
    st.caption("Yahoo ka Indian fundamentals data kabhi adhura ya purana hota hai. Screener.in se verify karo.")
else:
    st.info("Fundamentals Yahoo par nahi mile. Screener.in par dekho.")

st.subheader("Is stock ki headlines")
items = news(sym.replace(".NS", "").replace(".BO", ""), 8)
if not items:
    st.write("Abhi koi headline nahi mili.")
for t, link, src in items:
    st.markdown(f"- [{t}]({link}) ({src})")
st.caption("Sirf padhai ke liye, buy ya sell call nahi.")
