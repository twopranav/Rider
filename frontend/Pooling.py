import streamlit as st
from utils import post, get

st.title("🚕 Pooling Feature")

rider_id = st.text_input("Rider ID")
pickup = st.text_input("Pickup Location")
drop = st.text_input("Drop Location")

if st.button("Request Pooling Ride"):
    res = post("/pool/request", {
        "rider_id": rider_id,
        "pickup": pickup,
        "drop": drop
    })
    st.success(res)

st.subheader("Available Pools")
if st.button("Show Pools"):
    st.json(get("/pool/list"))
