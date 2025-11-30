import streamlit as st
from utils import post, get

st.title("📅 Scheduled Rides")

rider_id = st.text_input("Rider ID")
pickup = st.text_input("Pickup")
drop = st.text_input("Drop")
when = st.date_input("Date")
time = st.time_input("Time")

if st.button("Schedule Ride"):
    datetime_str = f"{when} {time}"
    res = post("/schedule/create", {
        "rider_id": rider_id,
        "pickup": pickup,
        "drop": drop,
        "datetime": datetime_str
    })
    st.success(res)

st.subheader("Your Scheduled Rides")
if st.button("View Scheduled"):
    st.json(get(f"/schedule/list/{rider_id}"))
