import streamlit as st
import smartsheet
import pandas as pd
import plotly.express as px
import google.generativeai as genai
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
# Your Active Projects Folder ID
ROOT_ID = 6632675466340228 

TARGET_FILE_KEYWORD = "Project Plan"

# --- AUTHENTICATION ---
try:
    ss_client = smartsheet.Smartsheet(st.secrets["SMARTSHEET_ACCESS_TOKEN"])
    ss_client.errors_as_exceptions(True)
except Exception as e:
    st.error(f"Smartsheet API Error: {e}")
    st.stop()

# Configure Gemini
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

# --- HELPER FUNCTIONS ---
def get_specific_col_id(sheet, target_names):
    sheet_cols = {c.title.strip().lower(): c.id for c in sheet.columns}
    for name in target_names:
        clean_name = name.strip().lower()
        if clean_name in sheet_cols:
            return sheet_cols[clean_name]
    return None

def get_cell_value(row, col_id):
    if not col_id: return None
    cell = next((c for c in row.cells if c.column_id == col_id), None)
    if cell:
        if hasattr(cell, 'display_value') and cell.display_value:
            return cell.display_value
        if hasattr(cell, 'value') and cell.value:
            return cell.value
    return None

# --- NEW: DYNAMIC MODEL FINDER ---
def get_flash_model():
    """Loops through available models to find a valid Flash version."""
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if 'flash' in m.name.lower():
                    return m.name
        # Fallback if no specific 'flash' model is found
        return 'gemini-1.5-flash'
    except:
        return 'gemini-1.5-flash'

# --- DATA ENGINE ---
def fetch_data_from_api(root_id):
    all_rows = []
    found_sheets = []
    
    with st.spinner('Connecting to Smartsheet API...'):
        try:
            try:
                root_obj = ss_client.Workspaces.get_workspace(root_id)
            except:
                root_obj = ss_client.Folders.get_folder(root_id)
            
            def scan(container):
                if hasattr(container, 'sheets'):
                    for s in container.sheets:
                        if TARGET_FILE_KEYWORD.lower() in s.name.lower():
                            found_sheets.append({"sheet": s, "context": container.name})
                if hasattr(container, 'folders'):
                    for f in container.folders:
                        try:
                            full = ss_client.Folders.get_folder(f.id)
                            scan(full)
                        except: continue
            scan(root_obj)
            
        except Exception as e:
            st.error(f"Connection Error: {e}")
            return pd.DataFrame()

    st.write(f"📂 Found {len(found_sheets)} sheets. Downloading data...")
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_sheets = len(found_sheets)
    
    for i, item in enumerate(found_sheets):
        progress_bar.progress((i + 1) / total_sheets)
        status_text.text(f"Scanning {i+1}/{total_sheets}: {item['sheet'].name}")
        
        try:
            sheet = ss_client.Sheets.get_sheet(item["sheet"].id)
            
            # Mapping
            end_date_id = get_specific_col_id(sheet, ["Finish Date", "Target End Date", "Finish"])
            start_date_id = get_specific_col_id(sheet, ["Start Date", "Target Start Date", "Start"])
            status_id = get_specific_col_id(sheet, ["Status", "% Complete", "Progress"])
            assign_id = get_specific_col_id(sheet, ["Assigned To", "Project Owner", "Functional Owner"])
            task_id = get_specific_col_id(sheet, ["Task Name", "Project Name", "Task", "Activity"])

            for row in sheet.rows:
                task_val = get_cell_value(row, task_id)
                if not task_val: continue
                
                all_rows.append({
                    "Project": item["context"], 
                    "Task": task_val,
                    "Status": get_cell_value(row, status_id) or "Not Started",
                    "Assigned To": get_cell_value(row, assign_id) or "Unassigned",
                    "Start Date": get_cell_value(row, start_date_id),
                    "End Date": get_cell_value(row, end_date_id),
                    "Link": row.permalink
                })
        except: continue
        
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(all_rows)

# --- APP STARTUP ---
st.set_page_config(layout="wide", page_title="Media Hub")

# SIDEBAR CONTROLS
st.sidebar.title("Controls")
if st.sidebar.button("🔄 Refresh Data Now"):
    if "master_df" in st.session_state:
        del st.session_state["master_df"]
    st.rerun()

if "master_df" not in st.session_state or st.session_state["master_df"].empty:
    st.session_state["master_df"] = fetch_data_from_api(ROOT_ID)

df = st.session_state["master_df"]

# --- LAYOUT HEADER WITH METRICS ---
if not df.empty:
    # DATA CLEANUP
    working_df = df.copy()
    working_df["End Date"] = pd.to_datetime(working_df["End Date"], errors='coerce')
    working_df["Start Date"] = pd.to_datetime(working_df["Start Date"], errors='coerce')
    working_df["Start Date"] = working_df["Start Date"].fillna(working_df["End Date"])
    
    today = pd.Timestamp.now().normalize()
    current_year = today.year
    done_statuses = ["Complete", "Done", "Shipped", "Cancelled", "Complete / Shipped"]

    # --- TOP METRICS CALCULATION ---
    active_rows = working_df[~working_df["Status"].isin(done_statuses)]
    projects_in_flight = len(active_rows["Project"].unique())
    started_ytd = len(working_df[working_df["Start Date"].dt.year == current_year]["Project"].unique())
    completed_rows = working_df[
        (working_df["Status"].isin(done_statuses)) & 
        (working_df["End Date"].dt.year == current_year)
    ]
    completed_ytd = len(completed_rows["Project"].unique())

    # --- HEADER UI ---
    col_header_1, col_header_2, col_header_3, col_header_4 = st.columns([2, 1, 1, 1])
    
    with col_header_1:
        st.title("🚀 Project Media Hub")
    with col_header_2:
        st.metric("✈️ Projects In Flight", projects_in_flight)
    with col_header_3:
        st.metric("🏁 Started (YTD)", started_ytd)
    with col_header_4:
        st.metric("✅ Active Completed (YTD)", completed_ytd)
    
    st.divider()

    # --- FILTER ---
    st.sidebar.header("Filters")
    people = sorted([x for x in working_df["Assigned To"].unique() if x is not None])
    selected_person = st.sidebar.selectbox("Filter by Person", ["All"] + people)
    
    table_df = working_df.copy()
    timeline_df = working_df.dropna(subset=["End Date"])
    
    if selected_person != "All":
        table_df = table_df[table_df["Assigned To"] == selected_person]
        timeline_df = timeline_df[timeline_df["Assigned To"] == selected_person]

    # ==========================================
    # 1. RESOURCE GANTT
    # ==========================================
    st.subheader("👥 Resource Schedule (Next 30 Days)")
    
    next_30 = today + timedelta(days=30)
    resource_view = timeline_df[
        (timeline_df["End Date"] >= today) & 
        (timeline_df["Start Date"] <= next_30) &
        (~timeline_df["Status"].isin(done_statuses))
    ]
    
    if not resource_view.empty:
        resource_view = resource_view.sort_values("Assigned To")
        fig_resource = px.timeline(
            resource_view, 
            x_start="Start Date", x_end="End Date", 
            y="Assigned To", color="Project",
            hover_data=["Task", "Status"],
            height=350 + (len(resource_view["Assigned To"].unique()) * 30),
            title="Who is working on what?"
        )
        fig_resource.update_xaxes(dtick="D1", tickformat="%d\n%b", range=[today, next_30])
        fig_resource.update_yaxes(autorange="reversed") 
        st.plotly_chart(fig_resource, use_container_width=True)
    else:
        st.info("No active scheduled work for the next 30 days.")

    st.divider()

    # ==========================================
    # 2. PROJECT TIMELINE
    # ==========================================
    st.subheader(f"📅 Project Timeline: {selected_person}")
    if not timeline_df.empty:
        gantt = timeline_df.sort_values("Start Date")
        fig = px.timeline(gantt, x_start="Start Date", x_end="End Date", y="Task", color="Project", hover_data=["Status"])
        fig.update_yaxes(autorange="reversed") 
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No timeline data found.")

    st.divider()

    # 3. SLIPPAGE
    col_slip_1, col_slip_2 = st.columns([2,1])
    with col_slip_1:
        st.subheader("🚨 Slippage Meter")
        overdue = timeline_df[(timeline_df["End Date"] < today) & (~timeline_df["Status"].isin(done_statuses))]
        if not overdue.empty:
            st.dataframe(overdue[["Project", "Task", "End Date", "Assigned To"]], use_container_width=True, hide_index=True)
        else:
            st.success("On track!")
            
    with col_slip_2:
        st.metric("Total Overdue", len(overdue), delta=-len(overdue), delta_color="inverse")

    st.divider()

    # 4. URGENT
    st.subheader("⚠️ Due Next 7 Days")
    next_week = today + timedelta(days=7)
    urgent = timeline_df[
        (timeline_df["End Date"] >= today) & 
        (timeline_df["End Date"] <= next_week) & 
        (~timeline_df["Status"].isin(done_statuses))
    ]
    if not urgent.empty:
        for i, row in urgent.iterrows():
            st.warning(f"**{row['Project']}**: {row['Task']} (Due {row['End Date'].strftime('%Y-%m-%d')})")
    else:
        st.success("No urgent items.")

    st.divider()

    # 5. HEATMAP & LIST
    st.subheader("🔥 Workload")
    active = table_df[~table_df["Status"].isin(done_statuses)]
    if not active.empty:
        counts = active["Assigned To"].value_counts() if selected_person == "All" else active["Project"].value_counts()
        st.bar_chart(counts, color="#FF4B4B")

    st.subheader("📋 Detailed Task List")
    st.dataframe(table_df[["Project", "Task", "Status", "End Date", "Assigned To"]], use_container_width=True, hide_index=True)

    st.divider()

    # ==========================================
    # 6. AI REPORT AGENT (DYNAMIC MODEL)
    # ==========================================
    st.subheader("🤖 AI Morning Briefing")
    
    if st.button("✨ Generate Email Report with Gemini"):
        if "GOOGLE_API_KEY" not in st.secrets:
            st.error("Please add your GOOGLE_API_KEY to Streamlit Secrets.")
        else:
            with st.spinner("Finding best model & analyzing..."):
                # Data Prep
                overdue_txt = overdue[["Project", "Task", "Assigned To", "End Date"]].head(15).to_string(index=False)
                urgent_txt = urgent[["Project", "Task", "Assigned To", "End Date"]].head(15).to_string(index=False)
                
                prompt = f"""
                Act as a Senior Project Manager. Write a morning briefing email.
                
                **Global Metrics:**
                - Projects In Flight: {projects_in_flight}
                - Projects Started YTD: {started_ytd}
                - Active Completed YTD: {completed_ytd}
                - Overdue Tasks: {len(overdue)}
                
                **Critical Items:**
                {overdue_txt}
                
                **Upcoming:**
                {urgent_txt}
                
                Write a concise, bulleted email summary.
                """
                
                try:
                    # DYNAMICALLY FIND A WORKING 'FLASH' MODEL
                    model_name = get_flash_model()
                    st.caption(f"Using AI Model: {model_name}") # Shows you which model picked
                    
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    st.success("Draft Generated!")
                    st.text_area("📧 Email Draft:", value=response.text, height=500)
                except Exception as e:
                    st.error(f"AI Error: {e}")

else:
    st.error("❌ No Data Found. Check Folder ID.")
