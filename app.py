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

# --- RECURSIVE FOLDER SCANNER (Required for your deep folders) ---
def scan_folder(folder_obj, found_sheets, status_text):
    """
    Recursively digs through every sub-folder to find sheets.
    """
    try:
        # Update status so you know it's working
        status_text.text(f"📂 Scanning: {folder_obj.name}...")
        
        # Fetch full folder content
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
            time.sleep(0.1) # Prevent API rate limits
            
    except Exception as e:
        print(f"Skipping folder {folder_obj.name}: {e}")

@st.cache_data(ttl=600) 
def fetch_active_projects(root_folder_id):
    all_rows = []
    found_sheets = []
    
    # UI Placeholder for scanning status
    status_text = st.empty()
    
    try:
        # Get the main folder (e.g., Active Projects)
        root_folder = ss_client.Folders.get_folder(root_folder_id)
        
        # Scan root sheets
        for sheet in root_folder.sheets:
            if TARGET_FILE_KEYWORD.lower() in sheet.name.lower():
                found_sheets.append({"sheet": sheet, "project_context": root_folder.name})
        
        # Recursive Scan of Sub-Folders
        for folder in root_folder.folders:
            scan_folder(folder, found_sheets, status_text)
            
    except Exception as e:
        st.error(f"Folder Error: {e}")
        return pd.DataFrame()

    status_text.text(f"✅ Found {len(found_sheets)} project plans. processing data...")
    
    # Extract Data
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
                
                # Only keep rows with an assignee or date
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
    status_text.empty()
    return pd.DataFrame(all_rows)

# --- DASHBOARD UI ---
st.set_page_config(page_title="Active Projects Hub", layout="wide")
st.title("🎬 Active Projects Hub")

# CONFIG: INPUT YOUR 'ACTIVE PROJECTS' FOLDER ID HERE
active_projects_folder_id = 6632675466340228

df = fetch_active_projects(active_projects_folder_id)

if not df.empty:
    # Date Cleanup
    df["Due Date"] = pd.to_datetime(df["Due Date"], errors='coerce')
    today = pd.Timestamp.now()
    next_week = today + timedelta(days=7)

    # --- FILTER: SELECT PERSON ---
    st.sidebar.header("Filters")
    # Get unique list of people, sort them, and add "All" option
    people_list = sorted([x for x in df["Assigned To"].unique() if x is not None])
    selected_person = st.sidebar.selectbox("Select Team Member", ["All"] + people_list)
    
    # Apply Filter
    if selected_person != "All":
        display_df = df[df["Assigned To"] == selected_person]
    else:
        display_df = df

    # --- WIDGET 1: URGENT ALERTS (Next 7 Days) ---
    st.subheader(f"🔥 Urgent Tasks (Next 7 Days)")
    
    urgent_tasks = display_df[
        (display_df["Due Date"] >= today) & 
        (display_df["Due Date"] <= next_week) &
        (~display_df["Status"].isin(["Complete", "Done", "Shipped", "Green"]))
    ]
    
    if not urgent_tasks.empty:
        for idx, row in urgent_tasks.iterrows():
            st.warning(
                f"**{row['Project']}**: {row['Task']} \n\n"
                f"👤 {row['Assigned To']} | 📅 {row['Due Date'].strftime('%Y-%m-%d')}"
            )
    else:
        st.success(f"No urgent deadlines for {selected_person}!")

    st.divider()

    # --- WIDGET 2: PROJECT LOAD (Individual Task List) ---
    st.subheader(f"📋 Full Task List: {selected_person}")
    
    # Format dates nicely for the table
    table_view = display_df.copy()
    table_view["Due Date"] = table_view["Due Date"].dt.strftime('%Y-%m-%d')
    
    # Show the clean table
    st.dataframe(
        table_view[["Project", "Task", "Status", "Due Date", "Assigned To"]].sort_values("Due Date"),
        use_container_width=True,
        hide_index=True
    )

else:
    st.warning("No data found. Please check your Folder ID at line 123.")

