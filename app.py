import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
import re

# 1. ตั้งค่าหน้ากระดาษ
st.set_page_config(layout="wide", page_title="Foundation Zoning Dashboard v2")

st.title("🏗️ Foundation Zoning & Pile Load Dashboard")
st.markdown("---")

# 2. ฟังก์ชันตรวจสอบและโหลดข้อมูลเฉพาะที่มีอยู่จริง
@st.cache_data
def load_etabs_data_dynamically(file):
    xl = pd.ExcelFile(file)
    available_sheets = xl.sheet_names
    
    # แม่แบบชื่อ Sheet ที่เราต้องการค้นหา
    target_sheets = {
        "Points": "Point Object Connectivity",
        "Cols_Conn": "Column Object Connectivity",
        "Joint_Rxn": "Joint Reactions",
        "Col_Forces": "Element Forces - Columns",
        "Pier_Forces": "Pier Forces",
        "Pier_Props": "Pier Section Properties"
    }
    
    data = {}
    for key, sheet_title in target_sheets.items():
        if sheet_title in available_sheets:
            df = pd.read_excel(file, sheet_name=sheet_title, skiprows=[0, 2])
            df.columns = df.columns.str.strip()
            if 'UniqueName' in df.columns: 
                df.rename(columns={'UniqueName': 'Unique Name'}, inplace=True)
            data[key] = df
            
    return data

# ฟังก์ชันจัดการชื่อ Pier
def extract_base_pier_name(name):
    name = str(name).strip()
    base_name = re.sub(r'[_-]?[XY]\d*$', '', name, flags=re.IGNORECASE)
    return base_name

# --- UI: เมนูด้านข้าง ---
st.sidebar.header("⚙️ การตั้งค่าข้อมูล")
uploaded_file = st.sidebar.file_uploader("📂 อัปโหลดไฟล์ Excel (.xlsx)", type=["xlsx"])

if uploaded_file:
    try:
        # โหลดข้อมูลแบบ Dynamic
        loaded_data = load_etabs_data_dynamically(uploaded_file)
        
        mode = st.sidebar.radio(
            "🔄 เลือกโหมดการวิเคราะห์:",
            ["1. Joint Reactions (เช็คละเอียดแยกตาม Node)", 
             "2. Column + Pier (ดูภาพรวมจัดโซนฐานราก)"]
        )
        
        st.sidebar.markdown("---")
        
        # --- ตรวจสอบเงื่อนไขการใช้ Sheet ของแต่ละโหมด ---
        df_merged = pd.DataFrame()
        
        if mode.startswith("1"):
            # โหมด 1 ต้องการ: Points และ Joint_Rxn
            missing_sheets = []
            if "Points" not in loaded_data: missing_sheets.append("Point Object Connectivity")
            if "Joint_Rxn" not in loaded_data: missing_sheets.append("Joint Reactions")
            
            if missing_sheets:
                st.error(f"❌ ไม่สามารถเปิดโหมด 1 ได้ เนื่องจากขาด Sheet: {', '.join(missing_sheets)}")
                st.info("💡 คำแนะนำ: สำหรับโหมดนี้ ให้ Export เฉพาะ 'Point Object Connectivity' และ 'Joint Reactions' จาก ETABS ก็เพียงพอครับ")
                st.stop()
                
            # เริ่มประมวลผลโหมด 1
            df_forces = loaded_data["Joint_Rxn"].copy()
            df_points = loaded_data["Points"].copy()
            
            df_forces['FZ'] = pd.to_numeric(df_forces['FZ'], errors='coerce')
            df_forces['Max_Load'] = df_forces['FZ'].abs()
            
            df_merged = df_forces.merge(df_points[['Unique Name', 'X', 'Y', 'Z']], on='Unique Name', how='inner')
            df_merged['Name_Label'] = "Joint " + df_merged['Label'].astype(str)
            df_merged['Type'] = 'Joint Node'
            
        else:
            # โหมด 2 ต้องการอย่างน้อย: Points, Cols_Conn, Col_Forces
            missing_sheets = []
            if "Points" not in loaded_data: missing_sheets.append("Point Object Connectivity")
            if "Cols_Conn" not in loaded_data: missing_sheets.append("Column Object Connectivity")
            if "Col_Forces" not in loaded_data: missing_sheets.append("Element Forces - Columns")
            
            if missing_sheets:
                st.error(f"❌ ไม่สามารถเปิดโหมด 2 ได้ เนื่องจากขาด Sheet หลัก: {', '.join(missing_sheets)}")
                st.stop()
                
            # -- ส่วนเสา (Columns) --
            df_col_f = loaded_data["Col_Forces"].copy()
            df_col_c = loaded_data["Cols_Conn"].copy()
            df_pts = loaded_data["Points"].copy()
            
            df_col_f['P'] = pd.to_numeric(df_col_f['P'], errors='coerce')
            df_col_max = df_col_f.sort_values(['Unique Name', 'Output Case', 'P'], ascending=[True, True, False]).drop_duplicates(subset=['Unique Name', 'Output Case'])
            
            df_col_pts = df_col_c.merge(df_pts, left_on='UniquePtJ', right_on='Unique Name', how='left')
            df_col_merged = df_col_max.merge(df_col_pts[['Unique Name_x', 'X', 'Y', 'Z']], left_on='Unique Name', right_on='Unique Name_x', how='inner')
            
            df_col_final = pd.DataFrame({
                'Name_Label': "Col " + df_col_merged['Column'].astype(str),
                'Output Case': df_col_merged['Output Case'],
                'Max_Load': df_col_merged['P'].abs(),
                'X': df_col_merged['X'],
                'Y': df_col_merged['Y'],
                'Z': df_col_merged['Z'],
                'Type': 'Column'
            })
            
            # -- ส่วนผนัง (Piers) -> ตรวจสอบแบบยืดหยุ่น ถ้าไม่มี Core Wall ก็ให้ผ่านได้
            df_pier_final = pd.DataFrame()
            if "Pier_Forces" in loaded_data and "Pier_Props" in loaded_data:
                df_pier_f = loaded_data["Pier_Forces"].copy()
                df_pier_props = loaded_data["Pier_Props"].copy()
                
                df_pier_f['P'] = pd.to_numeric(df_pier_f['P'], errors='coerce')
                df_pier_f = df_pier_f[df_pier_f['Location'].str.lower() == 'bottom']
                    
                df_pier_merged = df_pier_f.merge(df_pier_props[['Story', 'Pier', 'CG Bottom X', 'CG Bottom Y', 'CG Bottom Z']], on=['Story', 'Pier'], how='left')
                df_pier_merged['Base_Pier'] = df_pier_merged['Pier'].apply(extract_base_pier_name)
                df_pier_merged['Abs_P'] = df_pier_merged['P'].abs()
                
                def weighted_cg(group):
                    total_p = group['Abs_P'].sum()
                    if total_p == 0: total_p = 1e-9 
                    x_avg = (group['CG Bottom X'] * group['Abs_P']).sum() / total_p
                    y_avg = (group['CG Bottom Y'] * group['Abs_P']).sum() / total_p
                    z_avg = group['CG Bottom Z'].min() 
                    return pd.Series({'Max_Load': total_p, 'X': x_avg, 'Y': y_avg, 'Z': z_avg})

                df_pier_grouped = df_pier_merged.groupby(['Base_Pier', 'Output Case']).apply(weighted_cg).reset_index()
                
                df_pier_final = pd.DataFrame({
                    'Name_Label': "Pier " + df_pier_grouped['Base_Pier'].astype(str),
                    'Output Case': df_pier_grouped['Output Case'],
                    'Max_Load': df_pier_grouped['Max_Load'],
                    'X': df_pier_grouped['X'],
                    'Y': df_pier_grouped['Y'],
                    'Z': df_pier_grouped['Z'],
                    'Type': 'Core Wall'
                })
            else:
                st.sidebar.info("ℹ️ ไม่พบข้อมูล Pier (โปรแกรมประมวลผลเฉพาะข้อมูลเสา)")

            # รวมข้อมูลตามที่มีจริง
            df_merged = pd.concat([df_col_final, df_pier_final], ignore_index=True)

        # --- Sidebar: เลือก Z-Level ---
        st.sidebar.header("🏢 เลือกระดับความสูง (Z-Level)")
        df_merged['Z'] = pd.to_numeric(df_merged['Z'], errors='coerce')
        df_merged.dropna(subset=['Z'], inplace=True)
        df_merged['Z_Level'] = df_merged['Z'].round(2)
        available_z = sorted(df_merged['Z_Level'].unique())
        
        selected_z = st.sidebar.multiselect("แสดงผลเฉพาะระดับ Z (m):", available_z, default=available_z)
        
        # --- Sidebar: เลือก Load Case ---
        st.sidebar.header("📊 เลือก Load Combinations")
        all_cases = sorted(df_merged['Output Case'].unique())
        select_all = st.sidebar.checkbox("เลือกทั้งหมด", value=True)
        if select_all:
            selected_cases = st.sidebar.multiselect("เลือก Load", all_cases, default=all_cases)
        else:
            selected_cases = st.sidebar.multiselect("เลือก Load", all_cases, default=[all_cases[0]] if all_cases else [])

        # --- Sidebar: แบ่งโซนน้ำหนัก ---
        st.sidebar.header("🎯 แบ่งโซนน้ำหนักฐานราก")
        zone_inputs = st.sidebar.text_input("ช่วงน้ำหนัก (Tons):", "400, 800, 1500")
        
        try:
            thresholds = sorted([float(x.strip()) for x in zone_inputs.split(',')])
        except:
            st.error("⚠️ กรุณากรอกตัวเลขให้ถูกต้อง เช่น 400, 800, 1500")
            st.stop()

        bins = [-np.inf] + thresholds + [np.inf]
        labels = [f"1. 0 - {thresholds[0]} Tons"]
        for i in range(1, len(thresholds)):
            labels.append(f"{i+1}. > {thresholds[i-1]} - {thresholds[i]} Tons")
        labels.append(f"{len(thresholds)+1}. > {thresholds[-1]} Tons")

        # --- คำนวณ Envelope ---
        df_filtered = df_merged[
            (df_merged['Output Case'].isin(selected_cases)) & 
            (df_merged['Z_Level'].isin(selected_z))
        ].copy()
        
        if df_filtered.empty:
            st.warning("⚠️ ไม่มีข้อมูลสำหรับเงื่อนไขที่เลือก")
            st.stop()

        df_envelope = df_filtered.sort_values('Max_Load').groupby('Name_Label').tail(1).copy()
        df_envelope['Zone'] = pd.cut(df_envelope['Max_Load'], bins=bins, labels=labels, right=True)
        df_envelope['Display_Load'] = df_envelope['Max_Load'].astype(int).astype(str)

        # --- ส่วนแสดงผลแผนที่ (Plotly) ---
        st.subheader("📍 แผนที่จัดโซนฐานราก (Foundation Zoning Map)")
        color_sequence = px.colors.qualitative.Set1 + px.colors.qualitative.Pastel
        symbol_col = 'Type' if mode.startswith("2") else None

        fig = px.scatter(
            df_envelope.sort_values('Zone'), x="X", y="Y", color="Zone", symbol=symbol_col,
            size="Max_Load", text="Display_Load", hover_data=['Name_Label', 'Output Case', 'Z_Level'],
            color_discrete_sequence=color_sequence, size_max=40
        )
        fig.update_traces(textposition='top center', textfont=dict(family="Arial Black", size=11, color="black"))
        fig.update_layout(
            plot_bgcolor='white', paper_bgcolor='white', height=850,
            yaxis=dict(scaleanchor="x", scaleratio=1),
            legend=dict(bordercolor="black", borderwidth=1)
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- ตารางสรุป ---
        st.subheader(f"📊 ตารางสรุปน้ำหนักวิกฤต (Envelope) จำนวน {len(df_envelope)} จุด")
        display_cols = ['Name_Label', 'Type', 'Zone', 'Max_Load', 'Output Case', 'Z_Level', 'X', 'Y']
        st.dataframe(df_envelope[display_cols].sort_values('Max_Load', ascending=False), use_container_width=True)

    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในการประมวลผลไฟล์: {e}")

else:
    # หน้าจอแนะนำ (User Guide) ที่ปรับปรุงใหม่ แยกโหมดชัดเจน
    st.info("☝️ กรุณาอัปโหลดไฟล์ Excel เพื่อเริ่มต้นใช้งาน")
    st.markdown("""
    ### 📝 คู่มือการเตรียมไฟล์ Excel จาก ETABS (แยกตามโหมดการใช้งาน)
    โปรแกรมนี้ออกแบบมาให้ทำงานแบบ **ยืดหยุ่น** คุณสามารถเลือกที่จะ Export ไฟล์มาเฉพาะโหมดที่ต้องการใช้งานได้ โดยไม่จำเป็นต้องใช้ครบทุก Sheet ทุกครั้งครับ
    
    ---
    
    #### 🟢 ชุดที่ 1: ต้องการใช้ "โหมด 1: Joint Reactions" เท่านั้น
    *(เหมาะสำหรับเช็คแรงปฏิกิริยาดิ่งแบบละเอียดรายโหนด Mesh)*
    **ต้องการเพียง 2 ชื่อ Sheet นี้ในไฟล์ Excel:**
    1. `Point Object Connectivity`
    2. `Joint Reactions`

    ---

    #### 🔵 ชุดที่ 2: ต้องการใช้ "โหมด 2: Column + Pier" เท่านั้น
    *(เหมาะสำหรับการรวมน้ำหนักขาผนังลิฟต์ วางผังจัดโซนเสาเข็มอาคารภาพรวม)*
    **ต้องการชื่อ Sheet ดังนี้:**
    1. `Point Object Connectivity` *(จำเป็น)*
    2. `Column Object Connectivity` *(จำเป็น)*
    3. `Element Forces - Columns` *(จำเป็น)*
    4. `Pier Forces` *(ใช้เมื่อมี Core Wall)*
    5. `Pier Section Properties` *(ใช้เมื่อมี Core Wall)*

    ---
    
    #### 🟣 ชุดที่ 3: ต้องการใช้ทั้งสองโหมดสลับกัน
    * ให้ทำการรวม Sheet ทั้งหมดของทั้งชุดที่ 1 และ ชุดที่ 2 ไว้ในไฟล์ Excel เดียวกันก่อนทำการอัปโหลดครับ
    
    *💡 ข้อแนะนำ: ตอน Export ตารางกลุ่ม Forces/Reactions จาก ETABS แนะนำให้ลากเลือกเฉพาะชิ้นส่วนและโหนดที่ **ชั้นฐานราก (Base/Bottom Station)** เท่านั้น เพื่อให้ขนาดไฟล์ไม่ใหญ่จนเกินไปและโปรแกรมประมวลผลได้อย่างรวดเร็ว*
    """)
