import streamlit as st
import smartsheet
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
# Your "Active Projects" Folder ID
ROOT_ID = 6632675466340228 # <--- PASTE YOUR FOLDER ID HERE AGAIN

TARGET_FILE_KEYWORD = "Project Plan"

# ✅ UPDATED MAPPING: Prioritizes 'Finish Date' over 'End Date'
COLUMN_MAPPING = {
    "status": ["Status", "% Complete", "Progress"],
    "assigned_to": ["Assigned To", "Project Owner", "Functional Owner"],
    "start_date": ["Start Date", "Target Start Date"],
    "end_date": ["Finish Date", "End Date", "Target End Date", "Due Date"], # <--- FIX IS HERE
    "task_name": ["Task Name", "Project Name", "Task"]
}

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Connection Failed: {e}")
    st.stop()

# --- HELPER: COLUMN FINDER ---
def get_col_id(sheet, possible_names):
    # Normalize column names to avoid case/space issues
    sheet_cols = {c.title.strip().lower(): c.id for c in sheet.columns}
    
    for name in possible_names:
        clean_name = name.strip().lower()
        if clean_name in sheet_cols:
            return sheet_cols[clean_name]
    return None

# --- CORE LOGIC: RECURSIVE SCANNER ---
@st.cache_data(ttl=600)
def fetch_final_data(root_id):
    all_rows = []
    found_sheets = []
    
    # 1. Connect
    try:
        # Try as Workspace first
        root_obj = ss_client.Workspaces.get_workspace(root_id)
    except:
        try:
            # Try as Folder second
            root_obj = ss_client.Folders.get_folder(root_id)
        except:
            st.error(f"❌ ID {root_id} is invalid.")
            return pd.DataFrame()

    # 2. Scan for Sheets
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
    
    # 3. Extract Data
    progress = st.progress(0)
    for i, item in enumerate(found_sheets):
        progress.progress((i+1)/len(found_sheets))
        try:
            sheet = ss_client.Sheets.get_sheet(item["sheet"].id)
            
            # Map Columns
            status_id = get_col_id(sheet, COLUMN_MAPPING["status"])
            assign_id = get_col_id(sheet, COLUMN_MAPPING["assigned_to"])
            start_id = get_col_id(sheet, COLUMN_MAPPING["start_date"])
            end_id = get_col_id(sheet, COLUMN_MAPPING["end_date"])
            task_id = get_col_id(sheet, COLUMN_MAPPING["task_name"])

            for row in sheet.rows:
                def get_val(cid):
                    if not cid: return None
                    cell = next((c for c in row.cells if c.column_id == cid), None)
                    return cell.display_value if cell else None

                # Extract
                assignee = get_val(assign_id)
                end_val = get_val(end_id)
                start_val = get_val(start_id)

                # Keep if it has data
                if assignee or end_val:
                    all_rows.append({
                        "Project": item["context"],
                        "Task": get_val(task_id) or "Untitled",
                        "Status": get_val(status_id) or "Not Started",
                        "Assigned To": assignee or "Unassigned",
                        "Start Date": start_val,
                        "End Date": end_val,
                        "Link": row.permalink
                    })
        except: continue
        
    progress.empty()
    return pd.DataFrame(all_rows)

# --- UI LAYOUT ---
st.set_page_config(layout="wide", page_title="Media Hub")
st.title("🚀 Project Media Hub")

df = fetch_final_data(ROOT_ID)

if not df.empty:
    # --- DATA CLEANUP ---
    # Parse Dates
    df["End Date"] = pd.to_datetime(df["End Date"], errors='coerce')
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors='coerce')
    
    # Fill missing start dates for Gantt
    df["Start Date"] = df["Start Date"].fillna(df["End Date"])
    
    # Remove rows with no valid dates
    df = df.dropna(subset=["End Date"])
    
    today = pd.Timestamp.now()
    next_week = today + timedelta(days=7)
    done_statuses = ["Complete", "Done", "Shipped", "Cancelled", "Green", "Blue"]

    # --- FILTER ---
    people = sorted([x for x in df["Assigned To"].unique() if x is not None])
    selected_person = st.sidebar.selectbox("Filter by Person", ["All"] + people)
    
    if selected_person != "All":
        display_df = df[df["Assigned To"] == selected_person]
    else:
        display_df = df

    # 1. GANTT
    st.subheader(f"📅 Timeline: {selected_person}")
    if not display_df.empty:
        gantt = display_df.sort_values("Start Date")
        fig = px.timeline(
            gantt, 
            x_start="Start Date", x_end="End Date", 
            y="Task", color="Project",
            hover_data=["Status", "Assigned To"],
            height=400 + (len(gantt) * 10)
        )
        fig.update_yaxes(autorange="reversed") 
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No timeline data.")

    st.divider()

    # 2. SLIPPAGE
    st.subheader("🚨 Slippage Meter")
    overdue = display_df[(display_df["End Date"] < today) & (~display_df["Status"].isin(done_statuses))]
    
    c1, c2 = st.columns([1,3])
    c1.metric("Overdue Tasks", len(overdue), delta=-len(overdue), delta_color="inverse")
    if not overdue.empty:
        st.dataframe(overdue[["Project", "Task", "End Date", "Status"]], use_container_width=True, hide_index=True)
    else:
        st.success("No overdue items!")

    st.divider()

    # 3. HEATMAP
    st.subheader("🔥 Workload Heatmap")
    active = display_df[~display_df["Status"].isin(done_statuses)]
    if not active.empty:
        counts = active["Assigned To"].value_counts() if selected_person == "All" else active["Project"].value_counts()
        st.bar_chart(counts, color="#FF4B4B")
    else:
        st.info("No active tasks.")

    st.divider()

    # 4. URGENT
    st.subheader("⚠️ Due Next 7 Days")
    urgent = display_df[(display_df["End Date"] >= today) & (display_df["End Date"] <= next_week) & (~display_df["Status"].isin(done_statuses))]
    if not urgent.empty:
        for i, row in urgent.iterrows():
            st.warning(f"**{row['Project']}**: {row['Task']} (Due {row['End Date'].strftime('%Y-%m-%d')})")
    else:
        st.success("No urgent items.")

    st.divider()

    # 5. TABLE
    st.subheader("📋 Detailed Task List")
    st.dataframe(display_df[["Project", "Task", "Status", "End Date", "Assigned To"]], use_container_width=True, hide_index=True)

else:
    st.warning("No Data Found. Please double check that 'Finish Date' is populated in your Smartsheet.")
