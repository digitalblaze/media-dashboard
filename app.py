import streamlit as st
import smartsheet
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
# PASTE YOUR ID HERE (Can be Workspace ID or Folder ID)
ROOT_ID = 6632675466340228

TARGET_FILE_KEYWORD = "Project Plan"

# ✅ UPDATED MAPPING BASED ON YOUR DATA
COLUMN_MAPPING = {
    "status": ["Status", "% Complete", "Progress"],
    "assigned_to": ["Assigned To", "Project Owner", "Functional Owner"],
    "start_date": ["Start Date", "Target Start Date"],
    "end_date": ["Finish Date", "End Date", "Target End Date"], # Prioritizes 'Finish Date' for Gantt
    "task_name": ["Task Name", "Project Name"]
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
    for col in sheet.columns:
        if col.title in possible_names:
            return col.id
    return None

# --- CORE LOGIC: RECURSIVE SCANNER ---
def scan_container(container_obj, found_sheets, status_text):
    try:
        status_text.text(f"📂 Scanning: {container_obj.name}...")
        
        # Identify Object Type and Fetch Contents
        if hasattr(container_obj, 'permalink'):
            if isinstance(container_obj, smartsheet.models.Workspace):
                 full_obj = ss_client.Workspaces.get_workspace(container_obj.id)
            elif isinstance(container_obj, smartsheet.models.Folder):
                 full_obj = ss_client.Folders.get_folder(container_obj.id)
            else:
                 return 
        else:
            full_obj = container_obj

        # Grab Sheets
        if hasattr(full_obj, 'sheets'):
            for sheet in full_obj.sheets:
                if TARGET_FILE_KEYWORD.lower() in sheet.name.lower():
                    found_sheets.append({
                        "sheet": sheet,
                        "context": full_obj.name
                    })

        # Dive into Sub-Folders
        if hasattr(full_obj, 'folders'):
            for sub_folder in full_obj.folders:
                scan_container(sub_folder, found_sheets, status_text)
                time.sleep(0.1) 

    except Exception as e:
        print(f"Skipping {container_obj.name}: {e}")

@st.cache_data(ttl=600)
def fetch_dashboard_data(root_id):
    all_rows = []
    found_sheets = []
    status_text = st.empty()
    
    # 1. Connect
    try:
        # Try as Workspace first
        root_obj = ss_client.Workspaces.get_workspace(root_id)
        st.success(f"✅ Connected to Workspace: {root_obj.name}")
    except:
        try:
            # Try as Folder second
            root_obj = ss_client.Folders.get_folder(root_id)
            st.success(f"✅ Connected to Folder: {root_obj.name}")
        except:
            st.error(f"❌ Critical Error: ID {root_id} is invalid.")
            return pd.DataFrame()

    # 2. Scan
    scan_container(root_obj, found_sheets, status_text)
    
    status_text.text(f"✅ Found {len(found_sheets)} sheets. extracting data...")
    
    # 3. Process Data
    progress_bar = st.progress(0)
    total = len(found_sheets)
    
    for i, item in enumerate(found_sheets):
        if total > 0: progress_bar.progress((i + 1) / total)
        
        try:
            sheet = ss_client.Sheets.get_sheet(item["sheet"].id)
            
            # Get IDs using your EXACT column names
            status_id = get_col_id(sheet, COLUMN_MAPPING["status"])
            assign_id = get_col_id(sheet, COLUMN_MAPPING["assigned_to"])
            start_id = get_col_id(sheet, COLUMN_MAPPING["start_date"])
            end_id = get_col_id(sheet, COLUMN_MAPPING["end_date"])
            task_id = get_col_id(sheet, COLUMN_MAPPING["task_name"])

            for row in sheet.rows:
                def get_val(col_id):
                    if not col_id: return None
                    cell = next((c for c in row.cells if c.column_id == col_id), None)
                    return cell.display_value if cell else None
                
                assignee = get_val(assign_id)
                end_val = get_val(end_id)
                start_val = get_val(start_id)
                
                # Filter: Keep row if it has an Assignee OR a Date
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
        except:
            continue
            
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(all_rows)

# --- UI LAYOUT ---
st.set_page_config(layout="wide", page_title="Media Hub")
st.title("🚀 Project Media Hub")

df = fetch_dashboard_data(ROOT_ID)

if not df.empty:
    # --- DATA CLEANUP ---
    df["End Date"] = pd.to_datetime(df["End Date"], errors='coerce')
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors='coerce')
    # Fix for Gantt: If start is missing, assume it starts on the End Date (Milestone)
    df["Start Date"] = df["Start Date"].fillna(df["End Date"])
    
    # Remove rows with NO dates at all (cannot plot them)
    df = df.dropna(subset=["End Date"])
    
    today = pd.Timestamp.now()
    next_week = today + timedelta(days=7)
    done_statuses = ["Complete", "Done", "Shipped", "Cancelled", "Green", "Complete / Shipped"]

    # --- FILTER SIDEBAR ---
    people = sorted([x for x in df["Assigned To"].unique() if x is not None])
    selected_person = st.sidebar.selectbox("Filter by Person", ["All"] + people)
    
    if selected_person != "All":
        display_df = df[df["Assigned To"] == selected_person]
    else:
        display_df = df

    # 1. GANTT CHART
    st.subheader(f"📅 Timeline: {selected_person}")
    if not display_df.empty:
        gantt_data = display_df.sort_values("Start Date")
        fig = px.timeline(
            gantt_data, 
            x_start="Start Date", x_end="End Date", 
            y="Task", color="Project",
            hover_data=["Status", "Assigned To"],
            height=400 + (len(gantt_data) * 15) # Dynamic height
        )
        fig.update_yaxes(autorange="reversed") 
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No timeline data available for this view.")

    st.divider()

    # 2. SLIPPAGE METER
    st.subheader("🚨 Slippage Meter")
    overdue = display_df[(display_df["End Date"] < today) & (~display_df["Status"].isin(done_statuses))]
    
    c1, c2 = st.columns([1,3])
    c1.metric("Overdue Tasks", len(overdue), delta=-len(overdue), delta_color="inverse")
    if not overdue.empty:
        st.dataframe(overdue[["Project", "Task", "End Date", "Assigned To"]], use_container_width=True, hide_index=True)
    else:
        st.success("No overdue items!")

    st.divider()

    # 3. WORKLOAD HEATMAP
    st.subheader("🔥 Workload Heatmap")
    active = display_df[~display_df["Status"].isin(done_statuses)]
    if not active.empty:
        if selected_person == "All":
            # Show tasks per Person
            counts = active["Assigned To"].value_counts()
            st.bar_chart(counts, color="#FF4B4B")
        else:
            # Show tasks per Project (since we filtered to one person)
            counts = active["Project"].value_counts()
            st.bar_chart(counts, color="#FF4B4B")
    else:
        st.info("No active tasks found.")

    st.divider()

    # 4. URGENT ALERTS
    st.subheader("⚠️ Due Next 7 Days")
    urgent = display_df[(display_df["End Date"] >= today) & (display_df["End Date"] <= next_week) & (~display_df["Status"].isin(done_statuses))]
    if not urgent.empty:
        for i, row in urgent.iterrows():
            st.warning(f"**{row['Project']}**: {row['Task']} (Due {row['End Date'].strftime('%Y-%m-%d')})")
    else:
        st.success("No urgent items for the next week.")

    st.divider()

    # 5. DATA TABLE
    st.subheader("📋 Detailed Task List")
    st.dataframe(display_df[["Project", "Task", "Status", "Start Date", "End Date", "Assigned To"]], use_container_width=True, hide_index=True)

else:
    st.warning("No Data Found. Connected successfully, but found no matching rows.")
