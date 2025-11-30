import streamlit as st
from utils import post, get
import asyncio

st.title("🚕 Rider Dashboard")

rider_id = st.text_input("Rider ID")
pickup = st.text_input("Pickup Location")
drop = st.text_input("Drop Location")

if st.button("Book Ride"):
    data = {
        "rider_id": rider_id,
        "pickup": pickup,
        "drop": drop
    }
    res = post("/rider/book", data)
    st.success(res)

# Real-time updates
st.subheader("Live Ride Updates")

if st.button("Start Listening"):
    ws_url = f"ws://localhost:8000/ws/rider/{rider_id}"

    placeholder = st.empty()

    async def callback(msg):
        placeholder.write(msg)

    asyncio.run(utils.ws_listen(ws_url, callback))
