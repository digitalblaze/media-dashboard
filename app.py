import streamlit as st
import smartsheet
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
# PASTE YOUR ACTIVE PROJECTS FOLDER ID HERE
ROOT_ID = 6632675466340228 # <--- MAKE SURE THIS IS YOUR FOLDER ID

TARGET_FILE_KEYWORD = "Project Plan"

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Connection Failed: {e}")
    st.stop()

# --- HELPER: FUZZY COLUMN MATCHER ---
def get_col_id(sheet, possible_names):
    # Normalize the sheet columns (strip spaces, lowercase)
    sheet_cols = {c.title.strip().lower(): c.id for c in sheet.columns}
    
    for name in possible_names:
        clean_name = name.strip().lower()
        if clean_name in sheet_cols:
            return sheet_cols[clean_name]
    return None

# --- CORE LOGIC ---
@st.cache_data(ttl=600)
def fetch_debug_data(root_id):
    all_rows = []
    found_sheets = []
    
    # 1. Connect (Auto-Detect Workspace vs Folder)
    try:
        root_obj = ss_client.Workspaces.get_workspace(root_id)
        root_type = "Workspace"
    except:
        try:
            root_obj = ss_client.Folders.get_folder(root_id)
            root_type = "Folder"
        except:
            st.error(f"❌ ID {root_id} is invalid.")
            return pd.DataFrame()

    st.success(f"✅ Connected to {root_type}: {root_obj.name}")

    # 2. Recursive Scan
    def scan(container):
        if hasattr(container, 'sheets'):
            for s in container.sheets:
                if TARGET_FILE_KEYWORD.lower() in s.name.lower():
                    found_sheets.append({"sheet": s, "context": container.name})
        if hasattr(container, 'folders'):
            for f in container.folders:
                try:
                    # Must fetch full folder
                    full = ss_client.Folders.get_folder(f.id)
                    scan(full)
                except: continue
                
    scan(root_obj)
    st.info(f"📂 Found {len(found_sheets)} sheets. Extracting raw data...")

    # 3. Extract Data (NO FILTERS - GET EVERYTHING)
    progress = st.progress(0)
    for i, item in enumerate(found_sheets):
        progress.progress((i+1)/len(found_sheets))
        try:
            sheet = ss_client.Sheets.get_sheet(item["sheet"].id)
            
            # Match Columns (Fuzzy Match)
            status_id = get_col_id(sheet, ["Status", "% Complete", "Progress"])
            assign_id = get_col_id(sheet, ["Assigned To", "Project Owner", "Functional Owner"])
            end_id = get_col_id(sheet, ["End Date", "Finish Date", "Target End Date", "Due Date"])
            start_id = get_col_id(sheet, ["Start Date", "Target Start Date", "Start"])
            task_id = get_col_id(sheet, ["Task Name", "Project Name", "Task", "Activity"])

            for row in sheet.rows:
                def get_val(cid):
                    if not cid: return "MISSING_COL"
                    cell = next((c for c in row.cells if c.column_id == cid), None)
                    return cell.display_value if cell else None

                # APPEND EVERYTHING - DO NOT FILTER YET
                all_rows.append({
                    "Project": item["context"],
                    "Sheet": sheet.name,
                    "Task": get_val(task_id),
                    "Status": get_val(status_id),
                    "Assigned To": get_val(assign_id),
                    "Start Date": get_val(start_id),
                    "End Date": get_val(end_id),
                    "Raw Link": row.permalink
                })
        except: continue
        
    progress.empty()
    return pd.DataFrame(all_rows)

# --- UI ---
st.set_page_config(layout="wide", page_title="Debug Dashboard")
st.title("🕵️ Data Inspector Mode")

df = fetch_debug_data(ROOT_ID)

if not df.empty:
    st.write(f"**Raw Rows Found:** {len(df)}")
    
    # 1. RAW DATA PREVIEW (See what we actually got)
    with st.expander("🔍 Click to Inspect Raw Data (First 20 Rows)", expanded=True):
        st.dataframe(df.head(20))

    # 2. DATE PARSING ATTEMPT
    # We clean the dates carefully
    df["Clean End Date"] = pd.to_datetime(df["End Date"], errors='coerce')
    df["Clean Start Date"] = pd.to_datetime(df["Start Date"], errors='coerce')
    
    # Check how many dates failed parsing
    failed_dates = df[df["End Date"].notnull() & df["Clean End Date"].isnull()]
    if not failed_dates.empty:
        st.warning(f"⚠️ Warning: {len(failed_dates)} rows have dates we couldn't read.")
        st.write("Examples of bad dates:", failed_dates[["End Date"]].head())

    # 3. NOW APPLY FILTERS (Only valid rows)
    # Fill missing start dates with end dates for Gantt
    df["Clean Start Date"] = df["Clean Start Date"].fillna(df["Clean End Date"])
    
    # Valid Data for Dashboard
    valid_df = df.dropna(subset=["Clean End Date"])

    if not valid_df.empty:
        st.success(f"🎉 We have {len(valid_df)} valid rows for the timeline!")
        
        # GANTT
        st.subheader("📅 Timeline")
        fig = px.timeline(valid_df.sort_values("Clean Start Date"), 
                          x_start="Clean Start Date", x_end="Clean End Date", 
                          y="Task", color="Project", hover_data=["Status", "Assigned To"])
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)

        # TABLE
        st.subheader("📋 Full Data")
        st.dataframe(valid_df[["Project", "Task", "Status", "Clean End Date", "Assigned To"]])
    else:
        st.error("❌ We found data, but after filtering for valid dates, nothing was left. Check the 'Raw Data' above to see why your dates are failing.")

else:
    st.error("❌ No data rows extracted. The script connected but found 0 rows.")
