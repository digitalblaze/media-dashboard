import streamlit as st
import smartsheet

# --- CONFIGURATION ---
# Paste your ID here (It can be the Workspace ID OR the Active Projects Folder ID)
ROOT_ID = 6632675466340228
TARGET_FILE_KEYWORD = "Project Plan"

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"API Token Error: {e}")
    st.stop()

def get_universal_object(obj_id):
    """
    Tries to fetch the ID as a Workspace first.
    If that fails (404), it tries to fetch it as a Folder.
    """
    try:
        # Try Workspace
        obj = ss_client.Workspaces.get_workspace(obj_id)
        return obj, "Workspace"
    except smartsheet.exceptions.ApiError as e:
        if e.error.result.code == 1006: # Not Found (likely because it's a folder)
            try:
                # Try Folder
                obj = ss_client.Folders.get_folder(obj_id)
                return obj, "Folder"
            except Exception as e2:
                st.error(f"❌ ID {obj_id} is not a valid Workspace OR Folder. Check the number.")
                st.stop()
        else:
            st.error(f"API Error: {e}")
            st.stop()

def find_columns():
    st.title("🕵️ Column Detective")
    
    # 1. Connect Smartly
    root_obj, type_name = get_universal_object(ROOT_ID)
    st.success(f"✅ Connected to {type_name}: {root_obj.name}")
    
    # 2. Search for the first 'Project Plan' file
    st.info(f"Scanning {type_name} for files matching '{TARGET_FILE_KEYWORD}'...")
    
    found_sheet = None
    
    # Helper to recursively search
    def recursive_search(container):
        # Check sheets in this container
        if hasattr(container, 'sheets'):
            for sheet in container.sheets:
                if TARGET_FILE_KEYWORD.lower() in sheet.name.lower():
                    return sheet
        
        # Check subfolders
        if hasattr(container, 'folders'):
            for sub in container.folders:
                # Must re-fetch folder to see contents
                try:
                    full_sub = ss_client.Folders.get_folder(sub.id)
                    found = recursive_search(full_sub)
                    if found: return found
                except:
                    continue
        return None

    found_sheet = recursive_search(root_obj)
    
    if found_sheet:
        st.subheader(f"📄 Found File: {found_sheet.name}")
        st.write("Reading column names...")
        
        # 3. Get Columns
        try:
            full_sheet = ss_client.Sheets.get_sheet(found_sheet.id)
            columns = [col.title for col in full_sheet.columns]
            
            st.markdown("### 📋 Copy this list:")
            st.code(columns)
            
            st.write("---")
            st.warning("Please copy the list above and paste it into the chat so I can update your dashboard!")
        except Exception as e:
            st.error(f"Error reading sheet: {e}")
    else:
        st.error(f"❌ No sheets found matching '{TARGET_FILE_KEYWORD}' inside this {type_name}.")

if __name__ == "__main__":
    find_columns()
