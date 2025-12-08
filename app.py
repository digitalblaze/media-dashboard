import streamlit as st
import smartsheet
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
# PASTE YOUR FOLDER ID HERE
ROOT_ID = 6632675466340228

TARGET_FILE_KEYWORD = "Project Plan"

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Connection Failed: {e}")
    st.stop()

# --- HELPER: FIND ALL MATCHING COLUMN IDs ---
def get_all_col_ids(sheet, possible_names):
    """Returns a list of ALL column IDs that match the keywords."""
    found_ids = []
    sheet_cols = {c.title.strip().lower(): c.id for c in sheet.columns}
    
    for name in possible_names:
        clean_name = name.strip().lower()
        if clean_name in sheet_cols:
            found_ids.append(sheet_cols[clean_name])
    return found_ids

def get_first_val(row, col_ids):
    """Checks a list of columns for this row. Returns the first non-empty value."""
    for cid in col_ids:
        cell = next((c for c in row.cells if c.column_id == cid), None)
        if cell and cell.display_value:
            return cell.display_value
    return None

# --- CORE LOGIC ---
@st.cache_data(ttl=600)
def fetch_robust_data(root_id):
    all_rows = []
    found_sheets = []
    
    # 1. Connect
    try:
        root_obj = ss_client.Workspaces.get_workspace(root_id)
    except:
        try:
            root_obj = ss_client.Folders.get_folder(root_id)
        except:
            return pd.DataFrame()

    # 2. Scan
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
    
    # 3. Extract Data (Waterfall Method)
    progress = st.progress(0)
    for i, item in enumerate(found_sheets):
        progress.progress((i+1)/len(found_sheets))
        try:
            sheet = ss_client.Sheets.get_sheet(item["sheet"].id)
            
            # Get List of Candidate Columns
            status_ids = get_all_col_ids(sheet, ["Status", "% Complete", "Progress"])
            assign_ids = get_all_col_ids(sheet, ["Assigned To", "Project Owner", "Functional Owner"])
            task_ids = get_all_col_ids(sheet, ["Task Name", "Project Name", "Task", "Activity"])
            
            # DATE WATERFALL: Look for ANY of these
            end_date_ids = get_all_col_ids(sheet, ["Finish Date", "End Date", "Target End Date", "Due Date"])
            start_date_ids = get_all_col_ids(sheet, ["Start Date", "Target Start Date", "Start"])

            for row in sheet.rows:
                # Grab the first valid value found in any of the matching columns
                task_val = get_first_val(row, task_ids)
                
                # OPTIONAL: Skip rows with no Task Name (keeps data clean)
                if not task_val: continue
                
                all_rows.append({
                    "Project": item["context"],
                    "Task": task_val,
                    "Status": get_first_val(row, status_ids) or "Not Started",
                    "Assigned To": get_first_val(row, assign_ids) or "Unassigned",
                    "Start Date": get_first_val(row, start_date_ids),
                    "End Date": get_first_val(row, end_date_ids), # <--- Will try Finish, then End, then Target...
                    "Link": row.permalink
                })
        except: continue
        
    progress.empty()
    return pd.DataFrame(all_rows)

# --- UI ---
st.set_page_config(layout="wide", page_title="Media Hub")
st.title("🚀 Project Media Hub")

df = fetch_robust_data(ROOT_ID)

if not df.empty:
    # Cleanup Dates
    df["End Date"] = pd.to_datetime(df["End Date"], errors='coerce')
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors='coerce')
    df["Start Date"] = df["Start Date"].fillna(df["End Date"])
    
    # SEPARATE DATA STREAMS
    # 1. Total Data (For Table - show everything even if dates are missing)
    table_df = df.copy()
    
    # 2. Timeline Data (Must have valid dates)
    timeline_df = df.dropna(subset=["End Date"])

    today = pd.Timestamp.now()
    next_week = today + timedelta(days=7)
    done_statuses = ["Complete", "Done", "Shipped", "Cancelled", "Green", "Blue"]

    # --- FILTER ---
    people = sorted([x for x in df["Assigned To"].unique() if x is not None])
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
        st.info("No tasks with valid dates found for this view.")

    st.divider()

    # 2. SLIPPAGE (Uses timeline_df because we need dates)
    st.subheader("🚨 Slippage Meter")
    overdue = timeline_df[(timeline_df["End Date"] < today) & (~timeline_df["Status"].isin(done_statuses))]
    
    c1, c2 = st.columns([1,3])
    c1.metric("Overdue Tasks", len(overdue), delta=-len(overdue), delta_color="inverse")
    if not overdue.empty:
        st.dataframe(overdue[["Project", "Task", "End Date", "Status"]], use_container_width=True, hide_index=True)
    else:
        st.success("No overdue items!")

    st.divider()

    # 3. HEATMAP
    st.subheader("🔥 Workload Heatmap")
    active = table_df[~table_df["Status"].isin(done_statuses)]
    if not active.empty:
        counts = active["Assigned To"].value_counts() if selected_person == "All" else active["Project"].value_counts()
        st.bar_chart(counts, color="#FF4B4B")
    else:
        st.info("No active tasks.")

    st.divider()

    # 4. URGENT
    st.subheader("⚠️ Due Next 7 Days")
    urgent = timeline_df[(timeline_df["End Date"] >= today) & (timeline_df["End Date"] <= next_week) & (~timeline_df["Status"].isin(done_statuses))]
    if not urgent.empty:
        for i, row in urgent.iterrows():
            st.warning(f"**{row['Project']}**: {row['Task']} (Due {row['End Date'].strftime('%Y-%m-%d')})")
    else:
        st.success("No urgent items.")

    st.divider()

    # 5. TABLE (Shows EVERYTHING, even if dates are missing)
    st.subheader("📋 Detailed Task List")
    st.write(f"Total Rows: {len(table_df)}")
    st.dataframe(table_df[["Project", "Task", "Status", "End Date", "Assigned To"]], use_container_width=True, hide_index=True)

else:
    st.error("❌ No Data Found. Please double check your Folder ID.")
