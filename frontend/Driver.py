import streamlit as st
from utils import post, get

st.title("🚗 Driver Dashboard")

driver_id = st.text_input("Driver ID")

st.header("Incoming Ride Requests")
if st.button("Fetch Requests"):
    res = get(f"/driver/requests/{driver_id}")
    st.json(res)

ride_id = st.text_input("Ride ID")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Accept Ride"):
        st.json(post("/driver/accept", {"driver_id": driver_id, "ride_id": ride_id}))
with col2:
    if st.button("Start Ride"):
        st.json(post("/driver/start", {"ride_id": ride_id}))
with col3:
    if st.button("Finish Ride"):
        st.json(post("/driver/finish", {"ride_id": ride_id}))
