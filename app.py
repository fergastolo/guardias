import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import calendar
from ortools.sat.python import cp_model

st.set_page_config(page_title="NefroPlanner 2026", layout="wide")

# --- VERIFICACIÓN DE VERSIÓN PARA EVITAR EL ERROR ---
HAS_COLUMN_CONFIG = hasattr(st, "column_config")

# --- ESTILOS CSS ---
st.markdown("""
<style>
    .calendar-table { width: 100%; border-collapse: collapse; font-family: sans-serif; margin-bottom: 20px;}
    .calendar-table th { background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6; text-align: center; }
    .calendar-table td { height: 110px; width: 14%; border: 1px solid #dee2e6; vertical-align: top; padding: 5px; }
    .day-number { font-weight: bold; margin-bottom: 5px; color: #555; }
    .residente-label { 
        padding: 6px; border-radius: 4px; font-size: 0.85em; font-weight: bold; 
        text-align: center; margin-top: 10px; color: #1a1a1a; border: 1px solid rgba(0,0,0,0.1);
    }
    .vacío { color: #999; font-style: italic; background-color: #f9f9f9; border: 1px dashed #ccc; }
</style>
""", unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias")

# --- 1. CONFIGURACIÓN DE PLANTILLA ---
st.sidebar.header("Configuración de Plantilla")

df_res_init = pd.DataFrame([
    {"Nombre": "Daniela", "Tope": 6, "R": "R4", "Color": "#FFC1CC"},
    {"Nombre": "Sandra", "Tope": 6, "R": "R3", "Color": "#FFDAB9"},
    {"Nombre": "Mavi", "Tope": 6, "R": "R3", "Color": "#B2E2F2"},
    {"Nombre": "Lei", "Tope": 4, "R": "R2", "Color": "#FF6B6B"},
    {"Nombre": "May", "Tope": 4, "R": "R2", "Color": "#D3D3D3"},
    {"Nombre": "Residente A", "Tope": 2, "R": "R1", "Color": "#E6B3FF"},
    {"Nombre": "Residente B", "Tope": 2, "R": "R1", "Color": "#B3FFB3"},
])

# Solo usamos column_config si la versión de Streamlit lo soporta
if HAS_COLUMN_CONFIG:
    df_residentes = st.sidebar.data_editor(
        df_res_init,
        column_config={
            "Color": st.column_config.ColorColumn("Color"),
            "R": st.column_config.SelectboxColumn("Año", options=["R1", "R2", "R3", "R4"])
        },
        num_rows="dynamic"
    )
else:
    st.sidebar.warning("Usando modo compatibilidad (versión antigua). Escribe los colores en código Hex (ej: #FF0000)")
    df_residentes = st.sidebar.data_editor(df_res_init, num_rows="dynamic")

# Mapas de datos
USER_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_residentes.iterrows()}
USER_R_MAP = {row["Nombre"]: row["R"] for _, row in df_residentes.iterrows()}

# --- 2. SELECCIÓN DE TIEMPO ---
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
col1, col2 = st.columns(2)
with col1:
    mes_sel = st.selectbox("Mes", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
with col2:
    anio_sel = st.number_input("Año", value=2026)

primer_dia = datetime(anio_sel, mes_sel, 1)
ultimo_dia = datetime(anio_sel, mes_sel, calendar.monthrange(anio_sel, mes_sel)[1])
rango_fechas = pd.date_range(primer_dia, ultimo_dia)

# --- 3. AUSENCIAS ---
st.subheader("📅 Registro de Ausencias")
ausencias = {}
with st.expander("Marcar días de vacaciones"):
    cols = st.columns(3)
    for idx, row in df_residentes.iterrows():
        nombre = row["Nombre"]
        with cols[idx % 3]:
            ausencias[nombre] = st.multiselect(f"Ausente: {nombre}", rango_fechas, format_func=lambda x: x.strftime('%d'), key=f"aus_{nombre}")

# --- 4. RENDER CALENDARIO ---
def render_calendar_html(df_plan):
    plan_dict = {row['Fecha']: row['Residente'] for _, row in df_plan.iterrows()}
    cal = calendar.Calendar(firstweekday=0)
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
                color = USER_COLOR_MAP.get(res_nombre, "#ffffff")
                anio_res = USER_R_MAP.get(res_nombre, "")
                
                label = f"{res_nombre} ({anio_res})" if res_nombre != "VACÍO" else "VACÍO"
                style = f'background-color: {color};' if res_nombre != "VACÍO" else ""

                html += f'<td><div class="day-number">{day}</div>'
                html += f'<div class="residente-label" style="{style}">{label}</div></td>'
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
            guardias[(r, d)] = model.NewBoolVar(f'r{r}_d{d}')
    for d in range(num_dias):
        model.Add(sum(guardias[(r, d)] for r in range(num_res)) <= 1)
        for r in range(num_res):
            nombre = df_residentes.iloc[r]["Nombre"]
            if rango_fechas[d] in ausencias[nombre]:
                model.Add(guardias[(r, d)] == 0)
            if d < num_dias - 1:
                model.Add(guardias[(r, d)] + guardias[(r, d+1)] <= 1)
            if rango_fechas[d].weekday() == 3: # Jueves
                for delta in [1, 2, 3]:
                    if d + delta < num_dias:
                        model.Add(guardias[(r, d+delta)] == 0).OnlyEnforceIf(guardias[(r, d)])
    for r in range(num_res):
        model.Add(sum(guardias[(r, d)] for d in range(num_dias)) <= df_residentes.iloc[r]["Tope"])
    
    model.Maximize(sum(guardias[(r, d)] for r in range(num_res) for d in range(num_dias)))
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        res = []
        for d in range(num_dias):
            nom = "VACÍO"
            for r in range(num_res):
                if solver.Value(guardias[(r, d)]) == 1: nom = df_residentes.iloc[r]["Nombre"]
            res.append({"Fecha": rango_fechas[d].strftime('%Y-%m-%d'), "Residente": nom})
        return pd.DataFrame(res)
    return None

# --- 6. EJECUCIÓN ---
if st.button("🚀 Generar Planificación"):
    df_res = resolver()
    if df_res is not None:
        st.write(render_calendar_html(df_res), unsafe_allow_html=True)
    else:
        st.error("No se encontró solución viable.")
