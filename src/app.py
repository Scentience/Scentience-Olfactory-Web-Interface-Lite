import queue
from datetime import datetime

import pandas as pd
import streamlit as st

from scentience import ScentienceDevice

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_POINTS = 200
REFRESH_INTERVAL = 5  # seconds — matches BLE broadcast cadence

# Compounds broadcast on both sensor channels (A & B)
DUAL_CHANNEL = ["NH3", "NO", "NO2", "CO", "C2H5OH", "H2", "CH4", "C3H8", "C4H10"]

ENV_CHARTS = [
    ("Temperature (°C)", "ENV_temperatureC"),
    ("Humidity (%)", "ENV_humidity"),
    ("Pressure (hPa)", "ENV_pressureHpa"),
]

# ── Session state ──────────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "device": None,
        "connected": False,
        "data_q": queue.Queue(),
        "history": [],
        "connect_error": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

_init_state()

# ── BLE helpers ────────────────────────────────────────────────────────────────
def _ble_callback(data: dict) -> None:
    data["_ts"] = datetime.now().strftime("%H:%M:%S")
    st.session_state.data_q.put(data)


def _connect(api_key: str, char_uuid: str) -> None:
    try:
        dev = ScentienceDevice(api_key=api_key)
        dev.connect_ble(char_uuid=char_uuid)
        dev.stream_ble(callback=_ble_callback)
        st.session_state.device = dev
        st.session_state.connected = True
        st.session_state.connect_error = None
    except Exception as exc:
        st.session_state.connect_error = str(exc)
        st.session_state.connected = False


def _disconnect() -> None:
    dev = st.session_state.device
    if dev:
        try:
            dev.stop_stream()
            dev.disconnect()
        except Exception:
            pass
    st.session_state.device = None
    st.session_state.connected = False


def _drain_queue() -> bool:
    q = st.session_state.data_q
    added = False
    while not q.empty():
        try:
            st.session_state.history.append(q.get_nowait())
            added = True
        except queue.Empty:
            break
    if len(st.session_state.history) > MAX_POINTS:
        st.session_state.history = st.session_state.history[-MAX_POINTS:]
    return added


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Scentience Live", layout="wide", page_icon="🧪")
st.title("Scentience Live Dashboard")

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Device Connection")

    api_key_input = st.text_input(
        "API Key", 
        key="api_key_input"
        )
    uuid_input = st.text_input(
        "GATT Characteristic UUID",
        # placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        key="uuid_input",
    )

    btn_col1, btn_col2 = st.columns(2)
    connect_clicked = btn_col1.button(
        "Connect", use_container_width=True, disabled=st.session_state.connected
    )
    disconnect_clicked = btn_col2.button(
        "Disconnect", use_container_width=True, disabled=not st.session_state.connected
    )

    if connect_clicked:
        if not api_key_input:
            st.error("Enter your API key.")
        elif not uuid_input:
            st.error("Enter the GATT characteristic UUID.")
        else:
            with st.spinner("Scanning for Scentience device…"):
                _connect(api_key_input, uuid_input)
            st.rerun()

    if disconnect_clicked:
        _disconnect()
        st.rerun()

    if st.session_state.connect_error:
        st.error(st.session_state.connect_error)

    st.divider()
    if st.session_state.connected:
        st.success("🟢 Connected — streaming")
    else:
        st.warning("🔴 Disconnected")

    st.caption(f"Refresh every {REFRESH_INTERVAL} s · Max {MAX_POINTS} points")

    if st.button("Clear history", use_container_width=True):
        st.session_state.history.clear()
        st.rerun()


# ── Live dashboard (auto-refreshes every 5 s) ──────────────────────────────────
@st.fragment(run_every=REFRESH_INTERVAL)
def _dashboard():
    _drain_queue()

    if not st.session_state.history:
        if st.session_state.connected:
            st.info("Connected — waiting for first broadcast…")
        else:
            st.info("Enter your API key and GATT UUID in the sidebar, then click **Connect**.")
        return

    df = pd.DataFrame(st.session_state.history)
    if "_ts" in df.columns:
        df = df.set_index("_ts")

    # ── Environment ──────────────────────────────────────────────────────────
    st.subheader("Environment")
    env_cols = st.columns(3)
    for col, (label, field) in zip(env_cols, ENV_CHARTS):
        with col:
            st.markdown(f"**{label}**")
            if field in df.columns:
                st.line_chart(df[[field]].rename(columns={field: label}), height=200)
            else:
                st.caption("No data received yet")

    st.divider()

    # ── CO₂ (single channel) ─────────────────────────────────────────────────
    if "CO2" in df.columns:
        st.subheader("CO₂")
        st.line_chart(df[["CO2"]], height=200)
        st.divider()

    # ── Dual-channel chemical compounds ──────────────────────────────────────
    st.subheader("Chemical Compounds")
    n_cols = 3
    for i in range(0, len(DUAL_CHANNEL), n_cols):
        group = DUAL_CHANNEL[i : i + n_cols]
        row_cols = st.columns(n_cols)
        for col, chem in zip(row_cols, group):
            a_key = f"{chem}_A"
            b_key = f"{chem}_B"
            present = [k for k in (a_key, b_key) if k in df.columns]
            with col:
                st.markdown(f"**{chem}**")
                if present:
                    st.line_chart(df[present], height=200)
                else:
                    st.caption("No data received yet")
        # pad empty cells when group is smaller than n_cols
        for col in row_cols[len(group):]:
            col.empty()

    # ── Latest reading (raw) ──────────────────────────────────────────────────
    with st.expander("Latest reading (raw JSON)"):
        st.json(st.session_state.history[-1])


_dashboard()
