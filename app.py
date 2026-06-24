import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
import re

# 1. ตั้งค่าหน้ากระดาษ
st.set_page_config(layout="wide", page_title="Foundation Zoning Dashboard v5")

st.title("🏗️ Foundation Zoning & Pile Load Dashboard")
st.markdown("---")

# 2. ฟังก์ชันตรวจสอบและโหลดข้อมูลแบบ Dynamic พร้อมดักจับหน่วยแรง
@st.cache_data
def load_etabs_data_dynamically(file):
    xl = pd.ExcelFile(file)
    available_sheets = xl.sheet_names
    
    target_sheets = {
        "Points": "Point Object Connectivity",
        "Cols_Conn": "Column Object Connectivity",
        "Joint_Rxn": "Joint Reactions",
        "Col_Forces": "Element Forces - Columns",
        "Pier_Forces": "Pier Forces",
        "Pier_Props": "Pier Section Properties"
    }
    
    data = {}
    detected_unit = "Tons"  # ค่าเริ่มต้นหากไม่พบหน่วย
    
    for key, sheet_title in target_sheets.items():
        if sheet_title in available_sheets:
            # อ่านข้อมูลโดยข้ามเฉพาะแถวหัวข้อตารางแถวแรกสุด (TABLE: ...)
            df = pd.read_excel(file, sheet_name=sheet_title, skiprows=[0])
            df.columns = df.columns.str.strip()
            
            if len(df) > 0:
                # แถวแรกสุดของ DataFrame (แถวที่ 3 ใน Excel) คือแถวแสดงหน่วยแรงของ ETABS
                unit_row = df.iloc[0]
                
                # ดักจับหน่วยแรงดิ่งจาก Sheet ที่มีค่าแรง
                if key == "Joint_Rxn" and "FZ" in df.columns:
                    detected_unit = str(unit_row["FZ"]).strip()
                elif key == "Col_Forces" and "P" in df.columns:
                    detected_unit = str(unit_row["P"]).strip()
                elif key == "Pier_Forces" and "P" in df.columns:
                    detected_unit = str(unit_row["P"]).strip()
                
                # ทำการลบแถวหน่วยแรงออกจากข้อมูลดิบ เพื่อไม่ให้รบกวนการคำนวณ
                df = df.iloc[1:].reset_index(drop=True)
            
            if 'UniqueName' in df.columns: 
                df.rename(columns={'UniqueName': 'Unique Name'}, inplace=True)
            data[key] = df
            
    return data, detected_unit

def extract_base_pier_name(name):
    name = str(name).strip()
    base_name = re.sub(r'[_-]?[XY]\d*$', '', name, flags=re.IGNORECASE)
    return base_name

# --- UI: เมนูด้านข้าง ---
st.sidebar.header("⚙️ การตั้งค่าข้อมูล")
uploaded_file = st.sidebar.file_uploader("📂 อัปโหลดไฟล์ Excel (.xlsx)", type=["xlsx"])

if uploaded_file:
    try:
        # โหลดข้อมูลและดักจับหน่วยแรงแบบ Dynamic
        loaded_data, force_unit = load_etabs_data_dynamically(uploaded_file)
        
        mode = st.sidebar.radio(
            "🔄 เลือกโหมดการวิเคราะห์:",
            ["1. Joint Reactions (เช็คละเอียดแยกตาม Node)", 
             "2. Column + Pier (ดูภาพรวมจัดโซนฐานราก)"]
        )
        
        st.sidebar.markdown("---")
        
        df_merged = pd.DataFrame()
        
        if mode.startswith("1"):
            missing_sheets = []
            if "Points" not in loaded_data: missing_sheets.append("Point Object Connectivity")
            if "Joint_Rxn" not in loaded_data: missing_sheets.append("Joint Reactions")
            
            if missing_sheets:
                st.error(f"❌ ไม่สามารถเปิดโหมด 1 ได้ เนื่องจากขาด Sheet: {', '.join(missing_sheets)}")
                st.stop()
                
            df_forces = loaded_data["Joint_Rxn"].copy()
            df_points = loaded_data["Points"].copy()
            
            df_forces['FZ'] = pd.to_numeric(df_forces['FZ'], errors='coerce')
            df_forces['Max_Load'] = df_forces['FZ'].abs()
            
            df_merged = df_forces.merge(df_points[['Unique Name', 'X', 'Y', 'Z']], on='Unique Name', how='inner')
            df_merged['Name_Label'] = "Joint " + df_merged['Label'].astype(str)
            df_merged['Type'] = 'Joint Node'
            
        else:
            missing_sheets = []
            if "Points" not in loaded_data: missing_sheets.append("Point Object Connectivity")
            if "Cols_Conn" not in loaded_data: missing_sheets.append("Column Object Connectivity")
            if "Col_Forces" not in loaded_data: missing_sheets.append("Element Forces - Columns")
            
            if missing_sheets:
                st.error(f"❌ ไม่สามารถเปิดโหมด 2 ได้ เนื่องจากขาด Sheet หลัก: {', '.join(missing_sheets)}")
                st.stop()
                
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
                st.sidebar.info("ℹ️ ไม่พบข้อมูล Pier (ประมวลผลเฉพาะข้อมูลเสาเฟรม)")

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

        # --- Sidebar: แบ่งโซนน้ำหนัก (Dynamic Unit Binding) ---
        st.sidebar.header("🎯 แบ่งโซนน้ำหนักฐานราก")
        zone_inputs = st.sidebar.text_input(f"ช่วงน้ำหนัก ขอบเขตหน่วย ({force_unit}):", "400, 800, 1500")
        
        try:
            thresholds = sorted([float(x.strip()) for x in zone_inputs.split(',')])
        except:
            st.error(f"⚠️ กรุณากรอกตัวเลขให้ถูกต้อง คั่นด้วยเครื่องหมายจุลภาค เช่น 400, 800, 1500")
            st.stop()

        bins = [-np.inf] + thresholds + [np.inf]
        labels = [f"1. 0 - {thresholds[0]} {force_unit}"]
        for i in range(1, len(thresholds)):
            labels.append(f"{i+1}. > {thresholds[i-1]} - {thresholds[i]} {force_unit}")
        labels.append(f"{len(thresholds)+1}. > {thresholds[-1]} {force_unit}")

        # --- Sidebar: การตั้งค่ากราฟและการปรับสเกลตัวเลข ---
        st.sidebar.header("🎨 ตั้งค่าการแสดงผลกราฟ")
        show_labels = st.sidebar.checkbox("👁️ แสดงตัวเลขน้ำหนักบนแผนที่", value=False)
        font_size_scale = st.sidebar.slider("📐 ปรับขนาดตัวเลขพล็อตบนแผนที่", 5, 30, 10)
        marker_size_factor = st.sidebar.slider("🟢 ปรับขนาดจุดฐานราก", 10, 60, 25)

        # --- คำนวณ Envelope ---
        df_filtered = df_merged[
            (df_merged['Output Case'].isin(selected_cases)) & 
            (df_merged['Z_Level'].isin(selected_z))
        ].copy()
        
        if df_filtered.empty:
            st.warning("⚠️ ไม่มีข้อมูลสำหรับเงื่อนไขและ Load Case ที่เลือก")
            st.stop()

        df_envelope = df_filtered.sort_values('Max_Load').groupby('Name_Label').tail(1).copy()
        df_envelope['Zone'] = pd.cut(df_envelope['Max_Load'], bins=bins, labels=labels, right=True)
        df_envelope['Display_Load'] = df_envelope['Max_Load'].astype(int).astype(str)

        # --- ส่วนแสดงผลแผนที่ (Plotly) ---
        st.subheader(f"📍 แผนที่จัดโซนฐานราก (หน่วยแรงโมเดลนี้: {force_unit})")
        color_sequence = px.colors.qualitative.Set1 + px.colors.qualitative.Pastel
        symbol_col = 'Type' if mode.startswith("2") else None
        text_col = "Display_Load" if show_labels else None

        fig = px.scatter(
            df_envelope.sort_values('Zone'), x="X", y="Y", color="Zone", symbol=symbol_col,
            size="Max_Load", text=text_col, hover_data=['Name_Label', 'Output Case', 'Z_Level'],
            color_discrete_sequence=color_sequence, size_max=marker_size_factor
        )
        
        if show_labels:
            fig.update_traces(
                textposition='top center', 
                textfont=dict(family="Arial Black", size=font_size_scale, color="black")
            )
            
        fig.update_traces(marker=dict(line=dict(width=1, color='DarkSlateGrey')))
        
        fig.update_layout(
            plot_bgcolor='white', paper_bgcolor='white', height=850, font=dict(color="black"),
            xaxis=dict(showgrid=True, gridcolor='lightgray', zeroline=False, title="X (m)", color="black"),
            yaxis=dict(showgrid=True, gridcolor='lightgray', zeroline=False, title="Y (m)", scaleanchor="x", scaleratio=1, color="black"),
            legend=dict(
                title=dict(text=f'ช่วงน้ำหนัก ({force_unit}) / ประเภท', font=dict(size=14, color="black")),
                font=dict(size=12, color="black"), bgcolor="rgba(255, 255, 255, 0.9)",
                bordercolor="black", borderwidth=1
            )
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- ตารางสรุปจำนวนราย Zone (อัปเดตระบบคำนวณ Capacity และ แถว Sum) ---
        st.markdown("---")
        st.subheader("📊 ตารางสรุปจำนวนฐานรากและโหลดรวมแยกตามช่วงน้ำหนัก (Zone Capacity Summary)")
        
        # นับจำนวนจุดราย Zone
        df_zone_counts = df_envelope.groupby('Zone', observed=False).size().reset_index(name='จำนวนฐานราก (จุด)')
        total_points = len(df_envelope)
        df_zone_counts['สัดส่วนจากทั้งหมด (%)'] = ((df_zone_counts['จำนวนฐานราก (จุด)'] / total_points) * 100).round(1)
        
        #คำนวณหาระดับขีดจำกัด (Load Capacity Limit) ของแต่ละโซน
        zone_caps = []
        for i, label in enumerate(labels):
            if i < len(thresholds):
                zone_caps.append(thresholds[i])
            else:
                # โซนสุดท้ายจับค่าที่สูงที่สุดที่เกิดขึ้นจริงเพื่อให้คำนวณผลคูณน้ำหนักรวมได้ใกล้เคียงความจริง
                zone_data = df_envelope[df_envelope['Zone'] == label]
                if not zone_data.empty:
                    zone_caps.append(int(zone_data['Max_Load'].max()))
                else:
                    zone_caps.append(thresholds[-1])
                    
        df_zone_counts[f'Load Capacity ({force_unit})'] = zone_caps
        df_zone_counts[f'Total Load ({force_unit})'] = df_zone_counts['จำนวนฐานราก (จุด)'] * df_zone_counts[f'Load Capacity ({force_unit})']
        
        # สร้างแถวสรุปผลรวม (Total SUM Row)
        sum_row = pd.DataFrame({
            'Zone': ['รวมทั้งหมด (Total SUM)'],
            'จำนวนฐานราก (จุด)': [df_zone_counts['จำนวนฐานราก (จุด)'].sum()],
            'สัดส่วนจากทั้งหมด (%)': [df_zone_counts['สัดส่วนจากทั้งหมด (%)'].sum().round(1)],
            f'Load Capacity ({force_unit})': [np.nan],  # ไม่นำค่าลิมิตรายโซนมาบวกรวมกัน
            f'Total Load ({force_unit})': [df_zone_counts[f'Total Load ({force_unit})'].sum()]
        })
        
        df_zone_summary = pd.concat([df_zone_counts, sum_row], ignore_index=True)
        st.dataframe(df_zone_summary, use_container_width=True)

        # --- ตารางสรุปแบบละเอียดเดิม ---
        st.subheader(f"📊 ตารางสรุปน้ำหนักวิกฤตสูงสุดรายต้น (Envelope Summary Table) จำนวน {total_points} จุดวิเคราะห์")
        display_cols = ['Name_Label', 'Type', 'Zone', 'Max_Load', 'Output Case', 'Z_Level', 'X', 'Y']
        st.dataframe(df_envelope[display_cols].sort_values('Max_Load', ascending=False), use_container_width=True)

    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในการประมวลผลไฟล์: {e}")

else:
    # คู่มือแนะนำการใช้งานแสดงที่หน้าแรก
    st.info("☝️ กรุณาอัปโหลดไฟล์ Excel (.xlsx) เพื่อเริ่มต้นระบบวิเคราะห์จัดโซน")
    st.markdown("""
    ### 📝 คู่มือการเตรียมข้อมูลจากโปรแกรม ETABS และแนวทางการใช้งาน
    แดชบอร์ดนี้ออกแบบมาเพื่อช่วยวิศวกรโครงสร้างในการทำ **Preliminary Design** เพื่อจัดโซนน้ำหนักและกะปริมาณเสาเข็มได้อย่างรวดเร็ว โดยแบ่งออกเป็น 2 โหมดอิสระตามความต้องการของทีมงาน
    
    ---
    
    #### 🟢 ทางเลือกที่ 1: สำหรับผู้ใช้ "โหมด 1: Joint Reactions" เท่านั้น
    *(ใช้ตรวจสอบแรงปฏิกิริยาดิ่งแยกรายจุดต่อโหนด เหมาะสำหรับงานฐานรากแพหรือเช็ค Mesh ผนังแบบละเอียด)*
    **ชื่อ Sheet ที่จำเป็นต้องมีในไฟล์ Excel:**
    1. `Point Object Connectivity` *(ระบุตำแหน่งพิกัด)*
    2. `Joint Reactions` *(ดึงแรง FZ ดิ่ง)*

    ---

    #### 🔵 ทางเลือกที่ 2: สำหรับผู้ใช้ "โหมด 2: Column + Pier" เท่านั้น
    *(ใช้ยุบรวมแรงขาผนังลิฟต์/Core Wall และเสาอาคารให้ออกมาเป็นจุดศูนย์กลางชิ้นงานจุดเดียว สะดวกต่อการจัดกลุ่มผังฐานราก)*
    **ชื่อ Sheet ที่จำเป็นต้องมีในไฟล์ Excel:**
    1. `Point Object Connectivity` *(จำเป็น)*
    2. `Column Object Connectivity` *(จำเป็น)*
    3. `Element Forces - Columns` *(จำเป็น - ดึงแรง P สูงสุด)*
    4. `Pier Forces` *(ใช้เมื่อโมเดลมี Core Wall - ดึงแรงที่ตำแหน่ง Bottom)*
    5. `Pier Section Properties` *(ใช้เมื่อโมเดลมี Core Wall - ดึงพิกัด CG ล่างสุด)*

    ---
    
    #### ⚙️ ฟีเจอร์อำนวยความสะดวกในเวอร์ชันนี้:
    * **ระบบอ่านหน่วยอัตโนมัติ (Auto Unit Detection):** ตัวโปรแกรมจะอ่านแถวบอกหน่วยจาก ETABS เอง ไม่ว่าจะเป็นหน่วย `tonf`, `kN`, หรือ `kip` ช่องกรอกช่วงโซนน้ำหนักและตารางสรุปจะเปลี่ยนข้อความตามหน่วยนั้นๆ ทันทีโดยไม่ต้องตั้งค่าใหม่
    * **แถบควบคุมกราฟอัจฉริยะ (Visual Scale Controls):** หากจุดบนแปลนฐานรากเบียดแน่นเกินไป แนะนำให้ **ปิด** การแสดงตัวเลขบนแผนที่ แล้วใช้เมาส์เลื่อนชี้ (Hover) เพื่อดูค่ารายต้น หรือใช้ Slider ปรับขนาดฟอนต์ตัวเลขให้เล็กลงตามสัดส่วนที่เหมาะสมได้เลยครับ
    """)
