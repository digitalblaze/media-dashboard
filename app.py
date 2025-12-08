import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
COLUMN_MAPPING = {
    "status": ["Status", "State", "Progress", "% Complete", "Status/Health"],
    "assigned_to": ["Assigned To", "Owner", "Lead", "Editor", "Person", "Producer"],
    "date": ["End Date", "Due Date", "Finish", "Target Date", "Deadline"],
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
    """
    Recursively digs through every sub-folder to find sheets.
    """
    try:
        # Update the UI to show what we are scanning right now
        status_text.text(f"📂 Scanning folder: {folder_obj.name}...")
        
        # Fetch the full folder content
        full_folder = ss_client.Folders.get_folder(folder_obj.id)
        
        # 1. Check for Sheets in this folder
        for sheet in full_folder.sheets:
            if TARGET_FILE_KEYWORD.lower() in sheet.name.lower():
                found_sheets.append({
                    "sheet": sheet,
                    "project_context": full_folder.name
                })
        
        # 2. Dig deeper into Sub-Folders
        for sub_folder in full_folder.folders:
            scan_folder(sub_folder, found_sheets, status_text)
            
    except Exception as e:
        print(f"Skipping folder {folder_obj.name}: {e}")

@st.cache_data(ttl=600) 
def fetch_data_from_folder(root_folder_id):
    all_rows = []
    found_sheets = []
    
    # Create a placeholder for live status updates
    status_text = st.empty()
    
    try:
        # 1. Get the Main Target Folder (e.g., "Active Projects")
        root_folder = ss_client.Folders.get_folder(root_folder_id)
        
        # 2. Check for Sheets directly in this root folder
        for sheet in root_folder.sheets:
            if TARGET_FILE_KEYWORD.lower() in sheet.name.lower():
                found_sheets.append({"sheet": sheet, "project_context": root_folder.name})
        
        # 3. Recursive Scan of Sub-Folders (ACE, BAR, etc.)
        for folder in root_folder.folders:
            scan_folder(folder, found_sheets, status_text)
            
    except Exception as e:
        st.error(f"Folder Error: {e}")
        return pd.DataFrame()

    status_text.text(f"✅ Found {len(found_sheets)} project plans. Reading data...")
    
    # 4. Extract Data from Found Sheets
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
            date_id = get_col_id(sheet, COLUMN_MAPPING["date"])
            task_id = get_col_id(sheet, COLUMN_MAPPING["task_name"])

            for row in sheet.rows:
                def get_val(col_id):
                    if not col_id: return None
                    cell = next((c for c in row.cells if c.column_id == col_id), None)
                    return cell.display_value if cell else None
                
                assignee = get_val(assign_id)
                due_date_str = get_val(date_id)
                
                if assignee or due_date_str:
                    all_rows.append({
                        "Project": context_name,
                        "Sheet Name": sheet.name,
                        "Task": get_val(task_id) or "Untitled Task",
                        "Status": get_val(status_id) or "Not Started",
                        "Assigned To": assignee or "Unassigned",
                        "Due Date": due_date_str,
                        "Link": row.permalink
                    })
        except:
            continue
            
    progress_bar.empty()
    status_text.empty() # Clear the status text when done
    
    return pd.DataFrame(all_rows)

# --- DASHBOARD LAYOUT ---
st.set_page_config(page_title="Product Tracking Hub", layout="wide")
st.title("🚀 Product Portfolio Dashboard")

# CONFIG: REPLACE WITH THE FOLDER ID FOR 'ACTIVE PROJECTS'
active_projects_folder_id = 6632675466340228

df = fetch_data_from_folder(active_projects_folder_id)

if not df.empty:
    df["Due Date"] = pd.to_datetime(df["Due Date"], errors='coerce')
    today = pd.Timestamp.now()
    done_statuses = ["Complete", "Done", "Shipped", "Cancelled", "Green", "Complete / Shipped"]

    # 1. SLIPPAGE METER
    st.header("🚨 Slippage Meter")
    overdue_df = df[(df["Due Date"] < today) & (~df["Status"].isin(done_statuses))]
    
    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Overdue Items", len(overdue_df), delta=-len(overdue_df), delta_color="inverse")
    with col2:
        if not overdue_df.empty:
            st.dataframe(overdue_df[["Project", "Task", "Assigned To", "Due Date", "Status"]], use_container_width=True, hide_index=True)
        else:
            st.success("No slippage detected!")

    st.divider()

    # 2. WORKLOAD HEATMAP
    st.header("🔥 Workload Heatmap")
    active_work = df[~df["Status"].isin(done_statuses)]
    if not active_work.empty:
        workload_counts = active_work["Assigned To"].value_counts()
        st.bar_chart(workload_counts, color="#FF4B4B")
        with st.expander("View Details"):
            st.dataframe(active_work[["Assigned To", "Project", "Task", "Due Date"]], use_container_width=True)

    st.divider()

    # 3. LOOKAHEAD
    st.header("🔭 30-Day Lookahead")
    next_30 = today + timedelta(days=30)
    lookahead_df = df[(df["Due Date"] >= today) & (df["Due Date"] <= next_30) & (~df["Status"].isin(done_statuses))]

    if not lookahead_df.empty:
        st.dataframe(lookahead_df[["Due Date", "Project", "Task", "Assigned To"]].sort_values("Due Date"), use_container_width=True, hide_index=True)
    else:
        st.info("No tasks due in the next 30 days.")

else:
    st.warning("No data found. If this persists, verify your Folder ID and ensure 'Project Plan' files exist inside.")
