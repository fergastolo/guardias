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
    .calendar-table td { height: 115px; width: 14%; border: 1px solid #dee2e6; vertical-align: top; padding: 5px; }
    .day-number { font-weight: bold; margin-bottom: 5px; color: #555; }
    .residente-label { 
        padding: 6px; border-radius: 4px; font-size: 0.82em; font-weight: bold; 
        text-align: center; margin-top: 8px; color: #1a1a1a; border: 1px solid rgba(0,0,0,0.1);
    }
    .vacío { color: #999; font-style: italic; background-color: #f9f9f9; border: 1px dashed #ccc; }
</style>
""", unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias Nefrología")

# --- 1. CONFIGURACIÓN DE PLANTILLA ---
st.sidebar.header("Configuración de Plantilla")
st.sidebar.info("Modifica nombres, topes y colores (ej: #FFC1CC)")

df_res_init = pd.DataFrame([
    {"Nombre": "Daniela", "Tope": 6, "R": "R4", "Color": "#FFC1CC"},
    {"Nombre": "Sandra", "Tope": 6, "R": "R3", "Color": "#FFDAB9"},
    {"Nombre": "Mavi", "Tope": 6, "R": "R3", "Color": "#B2E2F2"},
    {"Nombre": "Lei", "Tope": 4, "R": "R2", "Color": "#FF6B6B"},
    {"Nombre": "May", "Tope": 4, "R": "R2", "Color": "#D3D3D3"},
    {"Nombre": "Residente A", "Tope": 2, "R": "R1", "Color": "#E6B3FF"},
    {"Nombre": "Residente B", "Tope": 2, "R": "R1", "Color": "#B3FFB3"},
])

df_residentes = st.sidebar.data_editor(df_res_init, num_rows="dynamic")

# Mapas de datos para el renderizado
USER_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_residentes.iterrows()}
USER_R_MAP = {row["Nombre"]: row["R"] for _, row in df_residentes.iterrows()}

# --- 2. SELECCIÓN DE TIEMPO ---
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
col1, col2 = st.columns(2)
with col1:
    mes_sel = st.selectbox("Mes", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
with col2:
    anio_sel = st.number_input("Año", value=2026)

primer_dia = datetime(anio_sel, mes_sel, 1)
ultimo_dia_mes = calendar.monthrange(anio_sel, mes_sel)[1]
rango_fechas = pd.date_range(primer_dia, periods=ultimo_dia_mes)

# --- 3. REGISTRO DE AUSENCIAS (CALENDARIO VISUAL) ---
st.subheader("📅 Registro de Ausencias")
st.write("Haz clic en los días que el residente **no** esté disponible (se marcarán como rojos).")

# Creamos pestañas para cada residente para que no se amontonen
tabs = st.tabs([row["Nombre"] for _, row in df_residentes.iterrows()])

ausencias = {}

for i, (idx, row) in enumerate(df_residentes.iterrows()):
    nombre = row["Nombre"]
    with tabs[i]:
        st.write(f"Calendario de ausencias para **{nombre}**")
        
        # Obtener la estructura de semanas del mes (0 es día fuera del mes)
        cal = calendar.Calendar(firstweekday=0)
        semanas = cal.monthdayscalendar(anio_sel, mes_sel)
        
        # Dibujar encabezados de días
        cols_header = st.columns(7)
        dias_semana = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        for j, dia_nom in enumerate(dias_semana):
            cols_header[j].write(f"**{dia_nom}**")
        
        # Lista para guardar los días seleccionados
        dias_seleccionados = []
        
        # Dibujar los checkboxes en cuadrícula
        for semana in semanas:
            cols = st.columns(7)
            for j, dia in enumerate(semana):
                if dia != 0:
                    # Crear un checkbox por cada día
                    # El key es único por residente y día para que Streamlit no se confunda
                    es_ausente = cols[j].checkbox(str(dia), key=f"check_{nombre}_{dia}")
                    if es_ausente:
                        # Si está marcado, lo añadimos a la lista de fechas prohibidas
                        fecha_ausencia = datetime(anio_sel, mes_sel, dia)
                        dias_seleccionados.append(fecha_ausencia)
                else:
                    cols[j].write("") # Espacio vacío para días fuera del mes
        
        ausencias[nombre] = dias_seleccionados

# --- 4. FUNCIÓN RENDERIZAR CALENDARIO ---
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
                class_name = "residente-label" if res_nombre != "VACÍO" else "residente-label vacío"
                style = f'background-color: {color};' if res_nombre != "VACÍO" else ""

                html += f'<td><div class="day-number">{day}</div>'
                html += f'<div class="{class_name}" style="{style}">{label}</div></td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html

# --- 5. MOTOR DE RESOLUCIÓN (SOLVER) ---
def resolver_guardias():
    model = cp_model.CpModel()
    num_res = len(df_residentes)
    num_dias = len(rango_fechas)
    
    # Aquí estaba el error: la línea ahora está completa
    guardias = {}
    for r in range(num_res):
        for d in range(num_dias):
            guardias[(r, d)] = model.NewBoolVar(f'res{r}_dia{d}')

    # Restricciones
    for d in range(num_dias):
        # Máximo 1 residente por día
        model.Add(sum(guardias[(r, d)] for r in range(num_res)) <= 1)
        
        for r in range(num_res):
            nombre = df_residentes.iloc[r]["Nombre"]
            # Ausencias
            if rango_fechas[d] in ausencias[nombre]:
                model.Add(guardias[(r, d)] == 0)
            # No 2 días seguidos
            if d < num_dias - 1:
                model.Add(guardias[(r, d)] + guardias[(r, d+1)] <= 1)
            # Regla Jueves -> Libre Vie, Sab, Dom
            if rango_fechas[d].weekday() == 3:
                for delta in [1, 2, 3]:
                    if d + delta < num_dias:
                        model.Add(guardias[(r, d+delta)] == 0).OnlyEnforceIf(guardias[(r, d)])

    # Topes Mensuales
    for r in range(num_res):
        tope = df_residentes.iloc[r]["Tope"]
        model.Add(sum(guardias[(r, d)] for d in range(num_dias)) <= tope)

    # Maximizar cobertura
    model.Maximize(sum(guardias[(r, d)] for r in range(num_res) for d in range(num_dias)))
    
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        res_data = []
        for d in range(num_dias):
            asignado = "VACÍO"
            for r in range(num_res):
                if solver.Value(guardias[(r, d)]) == 1:
                    asignado = df_residentes.iloc[r]["Nombre"]
            res_data.append({"Fecha": rango_fechas[d].strftime('%Y-%m-%d'), "Residente": asignado})
        return pd.DataFrame(res_data)
    return None

# --- 6. EJECUCIÓN ---
if st.button("🚀 Generar Planificación Final"):
    with st.spinner("Calculando cuadrante..."):
        df_final = resolver_guardias()
        if df_final is not None:
            st.write(render_calendar_html(df_final), unsafe_allow_html=True)
            
            st.divider()
            st.subheader("📊 Resumen de Guardias")
            conteo = df_final[df_final["Residente"] != "VACÍO"]["Residente"].value_counts().reset_index()
            conteo.columns = ["Residente", "Total Guardias"]
            st.table(conteo)
        else:
            st.error("No se encontró una solución válida. Prueba a aumentar los topes de guardia.")
