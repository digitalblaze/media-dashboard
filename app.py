import streamlit as st
import smartsheet
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
# PASTE YOUR ACTIVE PROJECTS FOLDER ID HERE
ROOT_ID = 6632675466340228

TARGET_FILE_KEYWORD = "Project Plan"

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Connection Failed: {e}")
    st.stop()

# --- HELPER FUNCTIONS ---
def get_specific_col_id(sheet, target_names):
    """
    Strictly looks for the specific column names we want.
    """
    sheet_cols = {c.title.strip().lower(): c.id for c in sheet.columns}
    
    for name in target_names:
        clean_name = name.strip().lower()
        if clean_name in sheet_cols:
            return sheet_cols[clean_name]
    return None

def get_cell_value(row, col_id):
    """
    ROBUST GETTER: Checks display_value first, then falls back to raw value.
    This fixes the 'blank date' bug.
    """
    if not col_id: return None
    cell = next((c for c in row.cells if c.column_id == col_id), None)
    
    if cell:
        # Priority 1: The formatted text
        if hasattr(cell, 'display_value') and cell.display_value:
            return cell.display_value
        # Priority 2: The raw value (Critical for Dates!)
        if hasattr(cell, 'value') and cell.value:
            return cell.value
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
    st.write(f"📂 Found {len(found_sheets)} sheets. Reading 'Finish Date' column...")
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_sheets = len(found_sheets)
    
    for i, item in enumerate(found_sheets):
        progress_bar.progress((i + 1) / total_sheets)
        status_text.text(f"Scanning {i+1}/{total_sheets}: {item['sheet'].name}")
        
        try:
            sheet = ss_client.Sheets.get_sheet(item["sheet"].id)
            
            # --- STRICT MAPPING ---
            # Using Finish Date as primary source
            end_date_id = get_specific_col_id(sheet, ["Finish Date", "Target End Date", "Finish"])
            start_date_id = get_specific_col_id(sheet, ["Start Date", "Target Start Date", "Start"])
            status_id = get_specific_col_id(sheet, ["Status", "% Complete", "Progress"])
            assign_id = get_specific_col_id(sheet, ["Assigned To", "Project Owner", "Functional Owner"])
            task_id = get_specific_col_id(sheet, ["Task Name", "Project Name", "Task", "Activity"])

            for row in sheet.rows:
                task_val = get_cell_value(row, task_id)
                if not task_val: continue
                
                all_rows.append({
                    "Project": item["context"],
                    "Task": task_val,
                    "Status": get_cell_value(row, status_id) or "Not Started",
                    "Assigned To": get_cell_value(row, assign_id) or "Unassigned",
                    "Start Date": get_cell_value(row, start_date_id),
                    "End Date": get_cell_value(row, end_date_id),
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

    today = pd.Timestamp.now().normalize()
    next_week = today + timedelta(days=7)
    
    # Statuses that mean "Work is over"
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
        st.info("No timeline data found (Finish Date missing).")

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
