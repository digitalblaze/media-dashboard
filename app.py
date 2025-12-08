import streamlit as st
import smartsheet
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
COLUMN_MAPPING = {
    "status": ["Status", "State", "Progress", "% Complete", "Status/Health"],
    "assigned_to": ["Assigned To", "Owner", "Lead", "Editor", "Person", "Producer"],
    "end_date": ["End Date", "Due Date", "Finish", "Target Date", "Deadline"],
    "start_date": ["Start Date", "Start", "Begin"], 
    "task_name": ["Task Name", "Task", "Activity", "Item", "Primary Column"]
}

TARGET_FILE_KEYWORD = "Project Plan" 

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Connection Failed: {e}")
    st.stop()

# --- HELPER FUNCTIONS ---
def get_col_id(sheet, possible_names):
    for col in sheet.columns:
        if col.title in possible_names:
            return col.id
    return None

# --- RECURSIVE FOLDER SCANNER ---
def scan_folder(folder_obj, found_sheets, status_text):
    try:
        status_text.text(f"📂 Scanning: {folder_obj.name}...")
        full_folder = ss_client.Folders.get_folder(folder_obj.id)
        
        for sheet in full_folder.sheets:
            if TARGET_FILE_KEYWORD.lower() in sheet.name.lower():
                found_sheets.append({
                    "sheet": sheet,
                    "project_context": full_folder.name
                })
        
        for sub_folder in full_folder.folders:
            scan_folder(sub_folder, found_sheets, status_text)
            time.sleep(0.1) 
            
    except Exception as e:
        print(f"Skipping folder {folder_obj.name}: {e}")

@st.cache_data(ttl=600) 
def fetch_active_projects(root_folder_id):
    all_rows = []
    found_sheets = []
    status_text = st.empty()
    
    try:
        root_folder = ss_client.Folders.get_folder(root_folder_id)
        for sheet in root_folder.sheets:
            if TARGET_FILE_KEYWORD.lower() in sheet.name.lower():
                found_sheets.append({"sheet": sheet, "project_context": root_folder.name})
        
        for folder in root_folder.folders:
            scan_folder(folder, found_sheets, status_text)
            
    except Exception as e:
        st.error(f"Folder Error: {e}")
        return pd.DataFrame()

    status_text.text(f"✅ Found {len(found_sheets)} project plans. Processing data...")
    
    progress_bar = st.progress(0)
    total_sheets = len(found_sheets)
    
    for i, item in enumerate(found_sheets):
        progress_bar.progress((i + 1) / total_sheets)
        
        sheet_obj = item["sheet"]
        context_name = item["project_context"]
        
        try:
            sheet = ss_client.Sheets.get_sheet(sheet_obj.id)
            
            status_id = get_col_id(sheet, COLUMN_MAPPING["status"])
            assign_id = get_col_id(sheet, COLUMN_MAPPING["assigned_to"])
            end_date_id = get_col_id(sheet, COLUMN_MAPPING["end_date"])
            start_date_id = get_col_id(sheet, COLUMN_MAPPING["start_date"]) 
            task_id = get_col_id(sheet, COLUMN_MAPPING["task_name"])

            for row in sheet.rows:
                def get_val(col_id):
                    if not col_id: return None
                    cell = next((c for c in row.cells if c.column_id == col_id), None)
                    return cell.display_value if cell else None
                
                assignee = get_val(assign_id)
                end_val = get_val(end_date_id)
                start_val = get_val(start_date_id)
                
                # Keep row if it has an assignee OR a date
                if assignee or end_val:
                    all_rows.append({
                        "Project": context_name,
                        "Sheet Name": sheet.name,
                        "Task": get_val(task_id) or "Untitled Task",
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

# --- DASHBOARD UI ---
st.set_page_config(page_title="Active Projects Hub", layout="wide")
st.title("🎬 Active Projects Hub")

# CONFIG: INPUT YOUR 'ACTIVE PROJECTS' FOLDER ID HERE
active_projects_folder_id = 6632675466340228

df = fetch_active_projects(active_projects_folder_id)

if not df.empty:
    # --- DATE CLEANUP (The Fix) ---
    df["End Date"] = pd.to_datetime(df["End Date"], errors='coerce')
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors='coerce')
    
    # CRITICAL FIX: If Start Date is missing, make it equal to End Date
    # This ensures "Milestones" still appear on the Gantt chart
    df["Start Date"] = df["Start Date"].fillna(df["End Date"]) 
    
    # Remove rows where even the End Date is missing (cannot plot those)
    df = df.dropna(subset=["End Date"])
    
    today = pd.Timestamp.now()
    next_week = today + timedelta(days=7)
    done_statuses = ["Complete", "Done", "Shipped", "Cancelled", "Green", "Complete / Shipped"]

    # --- FILTER: SELECT PERSON ---
    st.sidebar.header("Filters")
    people_list = sorted([x for x in df["Assigned To"].unique() if x is not None])
    selected_person = st.sidebar.selectbox("Select Team Member", ["All"] + people_list)
    
    if selected_person != "All":
        display_df = df[df["Assigned To"] == selected_person]
    else:
        display_df = df

    # ==========================================
    # 1. GANTT CHART
    # ==========================================
    st.subheader(f"📅 Project Timeline: {selected_person}")
    
    # Prepare data: Make sure we have at least one valid date
    gantt_data = display_df.copy()
    
    if not gantt_data.empty:
        gantt_data = gantt_data.sort_values("Start Date")
        
        fig = px.timeline(
            gantt_data, 
            x_start="Start Date", 
            x_end="End Date", 
            y="Task", 
            color="Project",
            hover_data=["Status", "Assigned To"],
            height=400 + (len(gantt_data) * 20) # Auto-adjust height so it's not squished
        )
        # Fix the axis so tasks read top-to-bottom
        fig.update_yaxes(autorange="reversed") 
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No tasks with valid dates found for timeline.")

    st.divider()

    # ==========================================
    # 2. SLIPPAGE METER
    # ==========================================
    st.header("🚨 Slippage Meter")
    overdue_df = display_df[(display_df["End Date"] < today) & (~display_df["Status"].isin(done_statuses))]
    
    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Overdue Items", len(overdue_df), delta=-len(overdue_df), delta_color="inverse")
    with col2:
        if not overdue_df.empty:
            st.dataframe(overdue_df[["Project", "Task", "End Date", "Status"]], use_container_width=True, hide_index=True)
        else:
            st.success("No slippage! Everything is on track.")

    st.divider()

    # ==========================================
    # 3. WORKLOAD HEATMAP
    # ==========================================
    st.header("🔥 Workload Heatmap")
    active_work = display_df[~display_df["Status"].isin(done_statuses)]
    
    if not active_work.empty:
        if selected_person == "All":
            counts = active_work["Assigned To"].value_counts()
            st.bar_chart(counts, color="#FF4B4B")
        else:
            counts = active_work["Project"].value_counts()
            st.bar_chart(counts, color="#FF4B4B")
    else:
        st.info("No active tasks found.")

    st.divider()

    # ==========================================
    # 4. URGENT ALERTS
    # ==========================================
    st.subheader(f"⚠️ Urgent Tasks (Next 7 Days)")
    urgent_tasks = display_df[
        (display_df["End Date"] >= today) & 
        (display_df["End Date"] <= next_week) &
        (~display_df["Status"].isin(done_statuses))
    ]
    
    if not urgent_tasks.empty:
        for idx, row in urgent_tasks.iterrows():
            st.warning(f"**{row['Project']}**: {row['Task']} (Due: {row['End Date'].strftime('%Y-%m-%d')})")
    else:
        st.success("No urgent deadlines coming up.")

    st.divider()

    # ==========================================
    # 5. FULL TASK LIST
    # ==========================================
    st.subheader(f"📋 Detailed Task List")
    table_view = display_df.copy()
    table_view["Start Date"] = table_view["Start Date"].dt.strftime('%Y-%m-%d')
    table_view["End Date"] = table_view["End Date"].dt.strftime('%Y-%m-%d')
    
    st.dataframe(
        table_view[["Project", "Task", "Status", "Start Date", "End Date", "Assigned To"]].sort_values("End Date"),
        use_container_width=True,
        hide_index=True
    )

else:
    st.warning("No data found. Please check your Folder ID at line 124.")
