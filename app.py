import streamlit as st
import smartsheet

# --- CONFIGURATION ---
# Your Workspace ID (Already verified as working)
ROOT_ID = 6632675466340228
TARGET_FILE_KEYWORD = "Project Plan"

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Connection Failed: {e}")
    st.stop()

# --- SNOOPER FUNCTION ---
def find_and_inspect_first_sheet(root_id):
    st.write("🔍 Scanning for the first 'Project Plan' file...")
    
    try:
        # Get Workspace
        workspace = ss_client.Workspaces.get_workspace(root_id)
        
        # Helper to recursively search
        def recursive_search(folder_obj):
            # Check sheets in this folder
            if hasattr(folder_obj, 'sheets'):
                for sheet in folder_obj.sheets:
                    if TARGET_FILE_KEYWORD.lower() in sheet.name.lower():
                        return sheet
            
            # Check subfolders
            if hasattr(folder_obj, 'folders'):
                for sub in folder_obj.folders:
                    # We must fetch the full folder to see inside it
                    full_sub = ss_client.Folders.get_folder(sub.id)
                    found = recursive_search(full_sub)
                    if found: return found
            return None

        # Start search
        found_sheet = recursive_search(workspace)
        
        if found_sheet:
            st.success(f"✅ Found File: {found_sheet.name}")
            
            # INSPECT COLUMNS
            full_sheet = ss_client.Sheets.get_sheet(found_sheet.id)
            st.subheader("📋 ACTUAL COLUMN NAMES FOUND:")
            
            # Create a clean list
            col_names = [col.title for col in full_sheet.columns]
            st.code(col_names)
            
            st.write("---")
            st.write("Please copy the list above and paste it into the chat!")
        else:
            st.error("❌ Could not find any file with 'Project Plan' in the name.")
            
    except Exception as e:
        st.error(f"Error: {e}")

# --- RUN UI ---
st.title("🕵️ Column Snooper")
find_and_inspect_first_sheet(ROOT_ID)
