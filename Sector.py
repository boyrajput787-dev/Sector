import streamlit as st
import streamlit.components.v1 as components

from core import sector_data, render_html, news

st.set_page_config(page_title="Sector Dashboard", page_icon="📊", layout="centered")

if st.button("Data refresh karo"):
    st.cache_data.clear()
    st.rerun()

with st.spinner("Data aa raha hai..."):
    d = sector_data()

if d is None:
    st.error("Data nahi aaya (Yahoo Finance ne shayad rok diya). 1-2 minute baad Refresh dabao.")
    st.stop()

components.html(render_html(d, show_stocks=False), height=1250, scrolling=True)

with st.expander("Market headlines"):
    items = news(None, 10)
    if not items:
        st.write("Abhi headlines nahi mili.")
    for t, link, src in items:
        st.markdown(f"- [{t}]({link}) ({src})")

st.caption("Data: Yahoo Finance (unofficial, thoda delayed). Sirf padhai ke liye, buy ya sell call nahi.")
