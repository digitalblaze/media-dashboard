import streamlit as st
import smartsheet
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION ---
# 1. COLUMN MAPPING: Ensure these match your actual Smartsheet column names
COLUMN_MAPPING = {
    "status": ["Status", "State", "Progress", "% Complete", "Status/Health"],
    "assigned_to": ["Assigned To", "Owner", "Lead", "Editor", "Person"],
    "date": ["End Date", "Due Date", "Finish", "Target Date", "Deadline"],
    "task_name": ["Task Name", "Task", "Activity", "Item"]
}

# 2. TARGET KEYWORD: We only read sheets containing this text
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
    """Finds the ID of a column by matching names loosely."""
    for col in sheet.columns:
        if col.title in possible_names:
            return col.id
    return None

@st.cache_data(ttl=600) 
def fetch_workspace_data(workspace_id):
    """
    Scans the entire workspace (root sheets + all subfolders)
    for any sheet containing 'Project Plan'.
    """
    all_rows = []
    
    try:
        workspace = ss_client.Workspaces.get_workspace(workspace_id)
    except Exception as e:
        st.error(f"Could not load Workspace. Check ID. Error: {e}")
        return pd.DataFrame()
    
    # 1. Build a list of all potential sheets to scan
    sheets_to_scan = []
    
    # Add sheets sitting at the root of the workspace
    for sheet in workspace.sheets:
        sheets_to_scan.append({"sheet": sheet, "project_context": "Root Workspace"})

    # Add sheets sitting inside folders (and sub-folders)
    for folder in workspace.folders:
        try:
            # Fetch folder contents to get sheets
            full_folder = ss_client.Folders.get_folder(folder.id)
            for sheet in full_folder.sheets:
                sheets_to_scan.append({"sheet": sheet, "project_context": folder.name})
        except:
            continue

    # 2. Iterate through found sheets
    progress_bar = st.progress(0)
    total_sheets = len(sheets_to_scan)
    
    for i, item in enumerate(sheets_to_scan):
        progress_bar.progress((i + 1) / total_sheets)
        
        sheet_obj = item["sheet"]
        context_name = item["project_context"]
        
        # FILTER: Only process sheets that match our keyword
        if TARGET_FILE_KEYWORD.lower() in sheet_obj.name.lower():
            try:
                sheet = ss_client.Sheets.get_sheet(sheet_obj.id)
                
                # Map Columns
                status_id = get_col_id(sheet, COLUMN_MAPPING["status"])
                assign_id = get_col_id(sheet, COLUMN_MAPPING["assigned_to"])
                date_id = get_col_id(sheet, COLUMN_MAPPING["date"])
                task_id = get_col_id(sheet, COLUMN_MAPPING["task_name"])

                for row in sheet.rows:
                    # Helper to get cell value safely
                    def get_val(col_id):
                        if not col_id: return None
                        cell = next((c for c in row.cells if c.column_id == col_id), None)
                        return cell.display_value if cell else None
                    
                    assignee = get_val(assign_id)
                    due_date_str = get_val(date_id)
                    
                    # Only collect rows that have an assignee or a date (skips empty rows)
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
            except Exception as e:
                continue # Skip sheets that trigger errors
                
    progress_bar.empty()
    return pd.DataFrame(all_rows)

# --- DASHBOARD LAYOUT ---
st.set_page_config(page_title="Product Tracking Hub", layout="wide")
st.title("🚀 Product Portfolio Dashboard")

# CONFIG: REPLACE WITH YOUR WORKSPACE ID
# (Get this from the URL: app.smartsheet.com/workspaces/12345...)
workspace_id = 3438747011311492

df = fetch_workspace_data(workspace_id)

if not df.empty:
    # --- DATA PREP ---
    # Convert dates to datetime objects
    df["Due Date"] = pd.to_datetime(df["Due Date"], errors='coerce')
    today = pd.Timestamp.now()
    
    # Define "Done" statuses to exclude from critical lists
    done_statuses = ["Complete", "Done", "Shipped", "Cancelled", "Green"]

    # ---------------------------------------------------------
    # 1. THE SLIPPAGE METER (Overdue Tracking)
    # ---------------------------------------------------------
    st.header("🚨 Slippage Meter")
    st.caption("Tasks that are past their due date and not marked Complete.")

    overdue_df = df[
        (df["Due Date"] < today) & 
        (~df["Status"].isin(done_statuses))
    ]
    
    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Overdue Items", len(overdue_df), delta=-len(overdue_df), delta_color="inverse")
    with col2:
        if not overdue_df.empty:
            st.dataframe(
                overdue_df[["Project", "Task", "Assigned To", "Due Date", "Status"]].sort_values("Due Date"),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.success("No slippage detected. All projects on track!")

    st.divider()

    # ---------------------------------------------------------
    # 2. WORKLOAD HEATMAP (Resource Management)
    # ---------------------------------------------------------
    st.header("🔥 Workload Heatmap")
    st.caption("Active tasks per person (Completed tasks excluded).")

    # Filter for active work only
    active_work = df[~df["Status"].isin(done_statuses)]
    
    if not active_work.empty:
        # Count tasks per person
        workload_counts = active_work["Assigned To"].value_counts()
        
        # Display as a Bar Chart
        st.bar_chart(workload_counts, color="#FF4B4B") # Red bars for visibility
        
        # Optional: Expandable view to see the details
        with st.expander("View Workload Details"):
            st.dataframe(active_work[["Assigned To", "Project", "Task", "Due Date"]].sort_values("Assigned To"), use_container_width=True)
    else:
        st.info("No active work found.")

    st.divider()

    # ---------------------------------------------------------
    # 3. THE LOOKAHEAD (Next 30 Days)
    # ---------------------------------------------------------
    st.header("🔭 30-Day Lookahead")
    st.caption("What is coming down the pipeline in the next month?")

    # Filter for dates between Today and Today + 30
    next_30 = today + timedelta(days=30)
    lookahead_df = df[
        (df["Due Date"] >= today) & 
        (df["Due Date"] <= next_30) &
        (~df["Status"].isin(done_statuses))
    ]

    if not lookahead_df.empty:
        # Display distinct projects appearing in the next 30 days
        unique_projects = lookahead_df["Project"].unique()
        st.write(f"**Projects with upcoming deadlines:** {', '.join(unique_projects)}")
        
        st.dataframe(
            lookahead_df[["Due Date", "Project", "Task", "Assigned To"]].sort_values("Due Date"),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No tasks due in the next 30 days.")

else:
    st.warning("No data found. Please check your Workspace ID and ensure your sheets contain 'Project Plan' in the name.")
