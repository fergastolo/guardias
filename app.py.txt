import streamlit as st
import pandas as pd
from datetime import datetime
from ortools.sat.python import cp_model

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Planificador Nefrología 2026", layout="wide")
st.title("🏥 Sistema de Planificación de Guardias")

# --- 1. CONFIGURACIÓN DE RESIDENTES (Editable en la web) ---
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

# El usuario puede editar nombres y topes directamente en la web
df_residentes = st.sidebar.data_editor(df_res_init, num_rows="dynamic")

# --- 2. CONFIGURACIÓN DEL PERIODO ---
col1, col2 = st.columns(2)
with col1:
    mes_seleccionado = st.selectbox("Selecciona el mes a planificar", 
                                    range(1, 13), format_func=lambda x: datetime(2026, x, 1).strftime('%B'))
with col2:
    año = st.number_input("Año", value=2026)

# --- 3. SECCIÓN DE VACACIONES (Calendario interactivo) ---
st.subheader("📅 Registro de Ausencias (Vacaciones/Rojos)")
fechas_ausentes = st.multiselect(
    "Selecciona los días que alguien NO puede hacer guardia:",
    pd.date_range(datetime(año, mes_seleccionado, 1), periods=31).filter(items=range(31)) 
    # (Nota: Esto es simplificado, en la app real usarías un selector por residente)
)

# --- 4. EL MOTOR (La función que ya teníamos) ---
def ejecutar_optimizacion(res_data, mes, anio):
    model = cp_model.CpModel()
    
    # Generar rango de fechas
    inicio = datetime(anio, mes, 1)
    if mes == 12: fin = datetime(anio, 12, 31)
    else: fin = datetime(anio, mes + 1, 1) - pd.Timedelta(days=1)
    rango = pd.date_range(inicio, fin)
    
    # Variables, Reglas y Solver (Aquí va la lógica anterior...)
    # [Para ahorrar espacio, asumimos que aquí se integra la lógica de OR-Tools]
    
    return "Tabla generada"

# --- 5. BOTÓN DE ACCIÓN ---
if st.button("🚀 Generar Planificación Mensual"):
    with st.spinner("Calculando la mejor distribución..."):
        # Aquí se llama a la función de optimización pasándole df_residentes
        st.success("¡Planificación completada!")
        
        # Simulación de resultado
        st.dataframe(df_res_init) # Aquí mostrarías el calendario real
        
        # Botón para descargar a Excel
        st.download_button("📥 Descargar Excel", data="datos", file_name="guardias.xlsx")