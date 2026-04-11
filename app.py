import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Planificador Nefrología 2026", layout="wide")
st.title("🏥 Sistema de Planificación de Guardias")

# --- 1. CONFIGURACIÓN DE PLANTILLA (Sidebar) ---
st.sidebar.header("Configuración de Plantilla")
df_res_init = pd.DataFrame([
    {"Nombre": "Daniela", "Tope": 6, "R": "R4"},
    {"Nombre": "Sandra", "Tope": 6, "R": "R3"},
    {"Nombre": "Mavi", "Tope": 6, "R": "R3"},
    {"Nombre": "Lei", "Tope": 4, "R": "R2"},
    {"Nombre": "May", "Tope": 4, "R": "R2"},
    {"Nombre": "Residente A", "Tope": 2, "R": "R1"},
    {"Nombre": "Residente B", "Tope": 2, "R": "R1"},
])

df_residentes = st.sidebar.data_editor(df_res_init, num_rows="dynamic")

# --- 2. SELECCIÓN DE MES Y AÑO ---
col1, col2 = st.columns(2)
with col1:
    mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                   "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    mes_seleccionado = st.selectbox("Selecciona el mes a planificar", range(1, 13), 
                                    index=5, format_func=lambda x: mes_nombres[x-1])
with col2:
    año = st.number_input("Año", value=2026)

# --- 3. CÁLCULO DE FECHAS DEL MES ---
fecha_inicio = datetime(año, mes_seleccionado, 1)
if mes_seleccionado == 12:
    fecha_fin = datetime(año, 12, 31)
else:
    fecha_fin = datetime(año, mes_seleccionado + 1, 1) - timedelta(days=1)

rango_fechas = pd.date_range(fecha_inicio, fecha_fin)

# --- 4. REGISTRO DE AUSENCIAS ---
st.subheader("📅 Registro de Ausencias (Vacaciones/Rojos)")
st.info("Selecciona qué residente NO puede estar disponible en qué días.")

ausencias = {}
for idx, row in df_residentes.iterrows():
    nombre = row["Nombre"]
    ausencias[nombre] = st.multiselect(
        f"Días de AUSENCIA para {nombre}",
        rango_fechas,
        format_func=lambda x: x.strftime('%d - %A'),
        key=f"aus_{nombre}"
    )

# --- 5. MOTOR DE OPTIMIZACIÓN (OR-TOOLS) ---
def resolver_guardias(df_res, fechas, dic_ausencias):
    model = cp_model.CpModel()
    num_res = len(df_res)
    num_dias = len(fechas)
    
    # Variables
    guardias = {}
    for r in range(num_res):
        for d in range(num_dias):
            guardias[(r, d)] = model.NewBoolVar(f'r{r}_d{d}')

    # Regla 1: Máximo 1 residente por día
    for d in range(num_dias):
        model.Add(sum(guardias[(r, d)] for r in range(num_res)) <= 1)

    for r in range(num_res):
        nombre = df_res.iloc[r]["Nombre"]
        tope = df_res.iloc[r]["Tope"]
        
        # Regla 2: Topes mensuales
        model.Add(sum(guardias[(r, d)] for d in range(num_dias)) <= tope)

        # Regla 3: Ausencias/Vacaciones
        for d in range(num_dias):
            if fechas[d] in dic_ausencias[nombre]:
                model.Add(guardias[(r, d)] == 0)

        # Regla 4: No 2 días seguidos
        for d in range(num_dias - 1):
            model.Add(guardias[(r, d)] + guardias[(r, d+1)] <= 1)

        # Regla 5: Jueves -> Descanso Vie, Sab, Dom
        for d in range(num_dias):
            if fechas[d].weekday() == 3: # Jueves
                for delta in [1, 2, 3]:
                    if d + delta < num_dias:
                        model.Add(guardias[(r, d+delta)] == 0).OnlyEnforceIf(guardias[(r, d)])

    # Objetivo: Maximizar cobertura
    model.Maximize(sum(guardias[(r, d)] for r in range(num_res) for d in range(num_dias)))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        resultado = []
        for d in range(num_dias):
            asignado = "VACÍO"
            for r in range(num_res):
                if solver.Value(guardias[(r, d)]) == 1:
                    asignado = df_res.iloc[r]["Nombre"]
            resultado.append({"Fecha": fechas[d].strftime('%Y-%m-%d'), "Día": fechas[d].strftime('%A'), "Residente": asignado})
        return pd.DataFrame(resultado)
    return None

# --- 6. BOTÓN Y RESULTADOS ---
if st.button("🚀 Generar Planificación"):
    df_final = resolver_guardias(df_residentes, rango_fechas, ausencias)
    
    if df_final is not None:
        st.success("¡Calendario generado con éxito!")
        st.dataframe(df_final, use_container_width=True)
        
        # Estadísticas de equidad
        st.subheader("📊 Resumen de Carga")
        conteo = df_final[df_final["Residente"] != "VACÍO"]["Residente"].value_counts()
        st.bar_chart(conteo)
        
        # Botón de descarga
        csv = df_final.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Descargar CSV", csv, "plan_guardias.csv", "text/csv")
    else:
        st.error("No se encontró solución. Revisa si hay demasiadas ausencias para cubrir el mes.")
