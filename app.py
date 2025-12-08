import streamlit as st
import smartsheet
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Connection Failed: {e}")
    st.stop()

# --- CONFIG ---
# PASTE YOUR FOLDER ID HERE
active_projects_folder_id = 6632675466340228
TARGET_FILE_KEYWORD = "Project Plan"

# --- DIAGNOSTIC SCANNER ---
@st.cache_data(ttl=600)
def scan_and_debug(root_folder_id):
    debug_log = []
    found_sheets = []
    
    try:
        root_folder = ss_client.Folders.get_folder(root_folder_id)
        
        # recursive helper
        def recursive_scan(folder_obj):
            # Scan sheets in current folder
            try:
                # Need to re-fetch folder to see sheets if it's a subfolder object
                if hasattr(folder_obj, 'sheets'):
                    sheets = folder_obj.sheets
                else:
                    full = ss_client.Folders.get_folder(folder_obj.id)
                    sheets = full.sheets
                    
                for sheet in sheets:
                    if TARGET_FILE_KEYWORD.lower() in sheet.name.lower():
                        found_sheets.append(sheet)
                        
                # Recurse subfolders
                if hasattr(folder_obj, 'folders'):
                    subfolders = folder_obj.folders
                else:
                    full = ss_client.Folders.get_folder(folder_obj.id)
                    subfolders = full.folders
                    
                for sub in subfolders:
                    recursive_scan(sub)
                    time.sleep(0.1)
            except Exception as e:
                debug_log.append(f"Error scanning folder {folder_obj.name}: {e}")

        recursive_scan(root_folder)
        
    except Exception as e:
        st.error(f"Critical Folder Error: {e}")
        return [], []

    return found_sheets, debug_log

# --- DASHBOARD UI ---
st.set_page_config(layout="wide")
st.title("🛠️ Dashboard Diagnostics")

sheets, logs = scan_and_debug(active_projects_folder_id)

st.write(f"**Found {len(sheets)} sheets matching '{TARGET_FILE_KEYWORD}'**")

if len(sheets) > 0:
    # Pick the first sheet and analyze its columns
    test_sheet = ss_client.Sheets.get_sheet(sheets[0].id)
    
    st.subheader(f"Analyzing Sheet: {test_sheet.name}")
    st.write("The script is looking for columns. Here are the ACTUAL column names in your sheet:")
    
    # Print all column names found
    actual_cols = [col.title for col in test_sheet.columns]
    st.code(actual_cols)
    
    st.warning("👇 Check if these names match the mapping below:")
    
    # Check mappings
    mapping_check = {
        "Status": ["Status", "State", "Progress", "% Complete", "Status/Health"],
        "Assigned To": ["Assigned To", "Owner", "Lead", "Editor", "Person", "Producer"],
        "End Date": ["End Date", "Due Date", "Finish", "Target Date", "Deadline"],
        "Start Date": ["Start Date", "Start", "Begin"]
    }
    
    for category, keywords in mapping_check.items():
        match = next((col for col in actual_cols if col in keywords), None)
        if match:
            st.success(f"✅ {category}: Found column '{match}'")
        else:
            st.error(f"❌ {category}: NO MATCH FOUND. (Script expects one of: {keywords})")

elif active_projects_folder_id == 1234567890123456:
    st.error("⚠️ You forgot to paste your Folder ID into the script!")
else:
    st.error("No sheets found. Double check your Folder ID and that sheets contain 'Project Plan' in the name.")

if logs:
    with st.expander("View Error Logs"):
        st.write(logs)
