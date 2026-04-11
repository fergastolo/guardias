import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import calendar
from ortools.sat.python import cp_model

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="NefroPlanner 2026", layout="wide")

# --- ESTILOS CSS PARA EL CALENDARIO ---
st.markdown("""
<style>
    .calendar-table { width: 100%; border-collapse: collapse; font-family: sans-serif; }
    .calendar-table th { background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6; text-align: center; color: #333; }
    .calendar-table td { height: 110px; width: 14%; border: 1px solid #dee2e6; vertical-align: top; padding: 5px; }
    .day-number { font-weight: bold; margin-bottom: 5px; color: #555; }
    .residente-label { 
        padding: 6px; border-radius: 4px; font-size: 0.85em; font-weight: bold; 
        text-align: center; margin-top: 10px; color: #1a1a1a; border: 1px solid rgba(0,0,0,0.1);
    }
    .vacío { color: #999; font-style: italic; background-color: #f9f9f9; border: 1px dashed #ccc; }
</style>
""", unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias Nefrología")

# --- 1. CONFIGURACIÓN DE PLANTILLA (Versión Simplificada para evitar errores) ---
st.sidebar.header("Configuración de Plantilla")
st.sidebar.info("Escribe el color en formato Hex (ej: #FFC1CC).")

# Tabla inicial
df_res_init = pd.DataFrame([
    {"Nombre": "Daniela", "Tope": 6, "R": "R4", "Color": "#FFC1CC"},
    {"Nombre": "Sandra", "Tope": 6, "R": "R3", "Color": "#FFDAB9"},
    {"Nombre": "Mavi", "Tope": 6, "R": "R3", "Color": "#B2E2F2"},
    {"Nombre": "Lei", "Tope": 4, "R": "R2", "Color": "#FF6B6B"},
    {"Nombre": "May", "Tope": 4, "R": "R2", "Color": "#D3D3D3"},
    {"Nombre": "Residente A", "Tope": 2, "R": "R1", "Color": "#E6B3FF"},
    {"Nombre": "Residente B", "Tope": 2, "R": "R1", "Color": "#B3FFB3"},
])

# Usamos st.data_editor básico sin column_config para asegurar compatibilidad total
df_residentes = st.sidebar.data_editor(df_res_init, num_rows="dynamic")

# Mapas de datos
USER_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_residentes.iterrows()}
USER_R_MAP = {row["Nombre"]: row["R"] for _, row in df_residentes.iterrows()}

# --- 2. SELECCIÓN DE MES Y AÑO ---
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
col1, col2 = st.columns(2)
with col1:
    mes_sel = st.selectbox("Mes", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
with col2:
    anio_sel = st.number_input("Año", value=2026)

primer_dia = datetime(anio_sel, mes_sel, 1)
ultimo_dia = datetime(anio_sel, mes_sel, calendar.monthrange(anio_sel, mes_sel)[1])
rango_fechas = pd.date_range(primer_dia, ultimo_dia)

# --- 3. REGISTRO DE AUSENCIAS ---
st.subheader("📅 Registro de Ausencias")
ausencias = {}
with st.expander("Marcar días rojos por residente"):
    cols = st.columns(3)
    for idx, row in df_residentes.iterrows():
        nombre = row["Nombre"]
        with cols[idx % 3]:
            ausencias[nombre] = st.multiselect(f"Rojos: {nombre}", rango_fechas, format_func=lambda x: x.strftime('%d'), key=f"a_{nombre}")

# --- 4. FUNCIÓN RENDERIZAR CALENDARIO ---
def render_calendar_html(df_plan):
    plan_dict = {row['Fecha']: row['Residente'] for _, row in df_plan.iterrows()}
    cal = calendar.Calendar(firstweekday=0) # Lunes
    month_days = cal.monthdayscalendar(anio_sel, mes_sel)
    
    html = '<table class="calendar-table"><thead><tr>'
    for d in ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]:
        html += f'<th>{d}</th>'
    html += '</tr></thead><tbody>'
    
    for week in month_days:
        html += '<tr>'
        for day in week:
            if day == 0:
                html += '<td style="background-color: #f1f1f1;"></td>'
            else:
                fecha_str = f"{anio_sel}-{mes_sel:02d}-{day:02d}"
                res_nombre = plan_dict.get(fecha_str, "VACÍO")
                
                # Obtener color y R
                color = USER_COLOR_MAP.get(res_nombre, "#ffffff")
                anio_res = USER_R_MAP.get(res_nombre, "")
                
                label = f"{res_nombre} ({anio_res})" if res_nombre != "VACÍO" else "VACÍO"
                class_name = "residente-label" if res_nombre != "VACÍO" else "residente-label vacío"
                style = f'background-color: {color};' if res_nombre != "VACÍO" else ""

                html += f'<td><div class="day-number">{day}</div>'
                html += f'<div class="{class_name}" style="{style}">{label}</div></td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html

# --- 5. SOLVER ---
def resolver():
    model = cp_model.CpModel()
    num_res = len(df_residentes)
    num_dias = len(rango_fechas)
    guardias = {}
    for r in range(num_res):
        for d in range(num_dias):
            guardias[(r, d)] =
