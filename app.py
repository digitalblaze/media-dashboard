import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION ---
# 1. COLUMN MAPPING: Ensure these match your "FULL Project Plan" columns
COLUMN_MAPPING = {
    "status": ["Status", "State", "Progress", "% Complete"],
    "assigned_to": ["Assigned To", "Owner", "Lead"],
    "date": ["End Date", "Due Date", "Finish", "Target Date"],
    "task_name": ["Task Name", "Task", "Activity"]
}

# 2. FILE MATCHING
# The script will only open sheets that contain this text in their name
TARGET_FILE_KEYWORD = "Project Plan" 

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Connection Failed: {e}")
    st.stop()

# --- DATA ENGINE ---
def get_col_id(sheet, possible_names):
    """Finds column ID by matching names loosely."""
    for col in sheet.columns:
        if col.title in possible_names:
            return col.id
    return None

@st.cache_data(ttl=600) 
def fetch_bar_projects(bar_folder_id):
    """
    1. Enters the 'BAR' folder.
    2. Iterates through every Project Subfolder.
    3. Finds the 'Project Plan' sheet in that subfolder.
    4. Aggregates the data.
    """
    all_rows = []
    
    try:
        # Get the main BAR folder
        bar_folder = ss_client.Folders.get_folder(bar_folder_id)
        project_folders = bar_folder.folders # These are "AASE", "NextGen", etc.
    except Exception as e:
        st.error(f"Could not find BAR Folder. Check ID. Error: {e}")
        return pd.DataFrame()

    progress_bar = st.progress(0)
    total_projects = len(project_folders)

    for i, proj_folder in enumerate(project_folders):
        # Update progress bar
        progress_bar.progress((i + 1) / total_projects)
        
        # Get the contents of the specific Project Folder
        try:
            full_proj_folder = ss_client.Folders.get_folder(proj_folder.id)
            sheets = full_proj_folder.sheets
            
            # Find the specific "Project Plan" sheet in this folder
            target_sheet = None
            for s in sheets:
                if TARGET_FILE_KEYWORD.lower() in s.name.lower():
                    target_sheet = s
                    break
            
            if target_sheet:
                # Open the sheet and read data
                sheet = ss_client.Sheets.get_sheet(target_sheet.id)
                
                # Map Columns
                status_id = get_col_id(sheet, COLUMN_MAPPING["status"])
                assign_id = get_col_id(sheet, COLUMN_MAPPING["assigned_to"])
                date_id = get_col_id(sheet, COLUMN_MAPPING["date"])
                task_id = get_col_id(sheet, COLUMN_MAPPING["task_name"])

                for row in sheet.rows:
                    # Helper to grab cell data safely
                    def get_val(col_id):
                        if not col_id: return None
                        cell = next((c for c in row.cells if c.column_id == col_id), None)
                        return cell.display_value if cell else None

                    assignee = get_val(assign_id)
                    due_date = get_val(date_id)
                    
                    # Only collect rows that actually have an assignee or a date
                    if assignee or due_date:
                        all_rows.append({
                            "Project": proj_folder.name, # e.g. "AASE Conference Video"
                            "Task": get_val(task_id) or "Untitled Task",
                            "Status": get_val(status_id) or "Not Started",
                            "Assigned To": assignee or "Unassigned",
                            "Due Date": due_date,
                            "Link": row.permalink
                        })
        except Exception as e:
            continue
            
    progress_bar.empty()
    return pd.DataFrame(all_rows)

# --- DASHBOARD UI ---
st.set_page_config(page_title="BAR Media Dashboard", layout="wide")
st.title("🎬 BAR Media Production Hub")

# SIDEBAR: Configuration
# You need to find the Folder ID for "BAR" specifically
bar_folder_id = 7157965225518980 # <--- REPLACE WITH YOUR BAR FOLDER ID
df = fetch_bar_projects(bar_folder_id)

if not df.empty:
    # Ensure Date parsing
    df["Due Date"] = pd.to_datetime(df["Due Date"], errors='coerce')
    today = pd.Timestamp.now()
    next_week = today + timedelta(days=7)

    # --- FILTER: PERSON ---
    st.sidebar.header("Filters")
    people = ["All"] + sorted(df["Assigned To"].unique().tolist())
    selected_person = st.sidebar.selectbox("Filter by Assignee", people)
    
    if selected_person != "All":
        display_df = df[df["Assigned To"] == selected_person]
    else:
        display_df = df

    # --- WIDGET 1: DEADLINE ALERTS (Top Priority) ---
    st.subheader("🔥 Upcoming Deadlines (Next 7 Days)")
    
    # Filter for items due in the next 7 days that are not complete
    upcoming = display_df[
        (display_df["Due Date"] >= today) & 
        (display_df["Due Date"] <= next_week) &
        (~display_df["Status"].isin(["Complete", "Done", "Shipped"]))
    ]
    
    if not upcoming.empty:
        # Show as urgent cards
        for idx, row in upcoming.iterrows():
            st.warning(
                f"**{row['Project']}**: {row['Task']} \n\n"
                f"👤 {row['Assigned To']} | 📅 {row['Due Date'].strftime('%b %d')}"
            )
    else:
        st.success("No urgent deadlines for the selected view!")

    st.divider()

    # --- WIDGET 2: PROJECT LOAD (Who is working on what?) ---
    st.subheader(f"📋 Project Load: {selected_person}")
    
    # Clean up table for display
    table_view = display_df.copy()
    table_view["Due Date"] = table_view["Due Date"].dt.strftime('%Y-%m-%d')
    
    st.dataframe(
        table_view[["Project", "Task", "Status", "Due Date", "Assigned To"]].sort_values("Due Date"),
        use_container_width=True,
        hide_index=True
    )

else:

    st.info("No data found. Please check your BAR_FOLDER_ID in the code.")
