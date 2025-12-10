import streamlit as st
import smartsheet
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
# PASTE YOUR ACTIVE PROJECTS FOLDER ID HERE
ROOT_ID = 3438747011311492 

TARGET_FILE_KEYWORD = "Project Plan"

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Connection Failed: {e}")
    st.stop()

# --- HELPER FUNCTIONS ---
def get_all_col_ids(sheet, possible_names):
    found_ids = []
    sheet_cols = {c.title.strip().lower(): c.id for c in sheet.columns}
    for name in possible_names:
        clean_name = name.strip().lower()
        if clean_name in sheet_cols:
            found_ids.append(sheet_cols[clean_name])
    return found_ids

def get_first_val(row, col_ids):
    for cid in col_ids:
        cell = next((c for c in row.cells if c.column_id == cid), None)
        if cell and cell.display_value:
            return cell.display_value
    return None

# --- DATA ENGINE ---
def fetch_data_from_api(root_id):
    all_rows = []
    found_sheets = []
    
    # 1. CONNECT & SCAN
    with st.spinner('Connecting to Smartsheet API...'):
        try:
            try:
                root_obj = ss_client.Workspaces.get_workspace(root_id)
            except:
                root_obj = ss_client.Folders.get_folder(root_id)
            
            def scan(container):
                if hasattr(container, 'sheets'):
                    for s in container.sheets:
                        if TARGET_FILE_KEYWORD.lower() in s.name.lower():
                            found_sheets.append({"sheet": s, "context": container.name})
                if hasattr(container, 'folders'):
                    for f in container.folders:
                        try:
                            full = ss_client.Folders.get_folder(f.id)
                            scan(full)
                        except: continue
            scan(root_obj)
            
        except Exception as e:
            st.error(f"Connection Error: {e}")
            return pd.DataFrame()

    # 2. DOWNLOAD DATA
    st.write(f"📂 Found {len(found_sheets)} sheets. Downloading data...")
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_sheets = len(found_sheets)
    
    for i, item in enumerate(found_sheets):
        current_progress = (i + 1) / total_sheets
        progress_bar.progress(current_progress)
        status_text.text(f"Reading file {i+1}/{total_sheets}: {item['sheet'].name}")
        
        try:
            sheet = ss_client.Sheets.get_sheet(item["sheet"].id)
            
            # Map Columns
            status_ids = get_all_col_ids(sheet, ["Status", "% Complete", "Progress"])
            assign_ids = get_all_col_ids(sheet, ["Assigned To", "Project Owner", "Functional Owner"])
            task_ids = get_all_col_ids(sheet, ["Task Name", "Project Name", "Task", "Activity"])
            end_date_ids = get_all_col_ids(sheet, ["Finish Date", "End Date", "Target End Date", "Due Date"])
            start_date_ids = get_all_col_ids(sheet, ["Start Date", "Target Start Date", "Start"])

            for row in sheet.rows:
                task_val = get_first_val(row, task_ids)
                if not task_val: continue
                
                all_rows.append({
                    "Project": item["context"],
                    "Task": task_val,
                    "Status": get_first_val(row, status_ids) or "Not Started",
                    "Assigned To": get_first_val(row, assign_ids) or "Unassigned",
                    "Start Date": get_first_val(row, start_date_ids),
                    "End Date": get_first_val(row, end_date_ids),
                    "Link": row.permalink
                })
        except: continue
        
    progress_bar.empty()
    status_text.empty()
    
    return pd.DataFrame(all_rows)

# --- APP STARTUP ---
st.set_page_config(layout="wide", page_title="Media Hub")

# CONTROLS
st.sidebar.title("Controls")
if st.sidebar.button("🔄 Refresh Data Now"):
    if "master_df" in st.session_state:
        del st.session_state["master_df"]
    st.rerun()

if "master_df" not in st.session_state:
    st.session_state["master_df"] = fetch_data_from_api(ROOT_ID)

df = st.session_state["master_df"]

st.title("🚀 Project Media Hub")

if not df.empty:
    # DATA CLEANUP
    working_df = df.copy()
    working_df["End Date"] = pd.to_datetime(working_df["End Date"], errors='coerce')
    working_df["Start Date"] = pd.to_datetime(working_df["Start Date"], errors='coerce')
    working_df["Start Date"] = working_df["Start Date"].fillna(working_df["End Date"])
    
    table_df = working_df.copy()
    timeline_df = working_df.dropna(subset=["End Date"])

    # --- FIX 1: Normalize Today's Date (Fixes "Midnight Bug") ---
    today = pd.Timestamp.now().normalize()
    next_week = today + timedelta(days=7)
    
    # --- FIX 2: Relaxed Done Statuses (Fixes "Green Trap") ---
    # Removed "Green" and "Blue" so they count as ACTIVE work
    done_statuses = ["Complete", "Done", "Shipped", "Cancelled", "Complete / Shipped"]

    # FILTER
    st.sidebar.header("Filters")
    people = sorted([x for x in working_df["Assigned To"].unique() if x is not None])
    selected_person = st.sidebar.selectbox("Filter by Person", ["All"] + people)
    
    if selected_person != "All":
        table_df = table_df[table_df["Assigned To"] == selected_person]
        timeline_df = timeline_df[timeline_df["Assigned To"] == selected_person]

    # 1. GANTT
    st.subheader(f"📅 Timeline: {selected_person}")
    if not timeline_df.empty:
        gantt = timeline_df.sort_values("Start Date")
        fig = px.timeline(gantt, x_start="Start Date", x_end="End Date", y="Task", color="Project", hover_data=["Status"])
        fig.update_yaxes(autorange="reversed") 
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No timeline data found.")

    st.divider()

    # 2. SLIPPAGE
    st.subheader("🚨 Slippage Meter")
    overdue = timeline_df[(timeline_df["End Date"] < today) & (~timeline_df["Status"].isin(done_statuses))]
    c1, c2 = st.columns([1,3])
    c1.metric("Overdue", len(overdue), delta=-len(overdue), delta_color="inverse")
    if not overdue.empty:
        st.dataframe(overdue[["Project", "Task", "End Date", "Status"]], use_container_width=True, hide_index=True)
    else:
        st.success("On track!")

    st.divider()

    # 3. HEATMAP
    st.subheader("🔥 Workload")
    active = table_df[~table_df["Status"].isin(done_statuses)]
    if not active.empty:
        counts = active["Assigned To"].value_counts() if selected_person == "All" else active["Project"].value_counts()
        st.bar_chart(counts, color="#FF4B4B")

    st.divider()

    # 4. URGENT
    st.subheader("⚠️ Due Next 7 Days")
    # Filters: 
    # 1. Date is >= Today
    # 2. Date is <= Next Week
    # 3. Status is NOT in "Done" list (Green/Blue will now SHOW UP)
    urgent = timeline_df[
        (timeline_df["End Date"] >= today) & 
        (timeline_df["End Date"] <= next_week) & 
        (~timeline_df["Status"].isin(done_statuses))
    ]
    
    if not urgent.empty:
        for i, row in urgent.iterrows():
            st.warning(f"**{row['Project']}**: {row['Task']} (Due {row['End Date'].strftime('%Y-%m-%d')})")
    else:
        st.success("No urgent items.")

    st.divider()

    # 5. FULL LIST
    st.subheader("📋 Detailed Task List")
    st.dataframe(table_df[["Project", "Task", "Status", "End Date", "Assigned To"]], use_container_width=True, hide_index=True)

else:
    st.error("❌ No Data Found. Check Folder ID.")
