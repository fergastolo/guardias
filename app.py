import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import calendar
from ortools.sat.python import cp_model
from google.cloud import firestore
from google.oauth2 import service_account
import json
import os

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="NefroPlanner Pro", layout="wide")

# --- 2. CONEXIÓN A FIRESTORE (LA VÍA SEGURA CON ARCHIVO TEMPORAL) ---
@st.cache_resource
def iniciar_firestore():
    try:
        # 1. Leer los secretos exactamente como están en [connections.firestore]
        creds_data = dict(st.secrets["connections"]["firestore"])
        
        # 2. Arreglar cualquier salto de línea que Streamlit haya roto al final
        pk = creds_data["private_key"].replace("\\n", "\n")
        if "=-----END" in pk and "=\n-----END" not in pk:
            pk = pk.replace("=-----END", "=\n-----END")
        creds_data["private_key"] = pk

        # 3. Guardar esto en un archivo físico en el servidor de Streamlit
        temp_file = "firebase_key_temp.json"
        with open(temp_file, "w") as f:
            json.dump(creds_data, f)
            
        # 4. Le decimos a Google que lea ese archivo físico
        creds = service_account.Credentials.from_service_account_file(temp_file)
        client = firestore.Client(credentials=creds, project=creds_data["project_id"])
        
        # 5. Borrar el archivo de credenciales por seguridad
        if os.path.exists(temp_file):
            os.remove(temp_file)
            
        return client
        
    except Exception as e:
        st.error(f"Error crítico al conectar con Firestore: {e}")
        return None

# Inicializamos db de forma global
db = iniciar_firestore()

def cargar_ausencias_db():
    ausencias_dict = {}
    if db is None:
        st.warning("⚠️ Sin conexión a Base de Datos. Usando memoria temporal.")
        return ausencias_dict
        
    try:
        docs = db.collection("ausencias").stream()
        for doc in docs:
            data = doc.to_dict()
            fechas_obj = {datetime.strptime(f, '%Y-%m-%d') for f in data.get("fechas", [])}
            ausencias_dict[doc.id] = fechas_obj
    except Exception as e:
        st.error(f"Error al leer la colección 'ausencias': {e}")
    return ausencias_dict

def guardar_ausencias_db(nombre, lista_fechas):
    if db is None:
        return False
    try:
        fechas_str = [f.strftime('%Y-%m-%d') for f in lista_fechas]
        db.collection("ausencias").document(nombre).set({"fechas": fechas_str})
        return True
    except Exception as e:
        st.error(f"Error al guardar datos para {nombre}: {e}")
        return False

# Inicializamos la memoria de la app con los datos de la DB
if 'ausencias_globales' not in st.session_state:
    st.session_state.ausencias_globales = cargar_ausencias_db()


# --- 3. ESTILOS CSS ---
st.markdown("""
<style>
    .calendar-table { width: 100%; border-collapse: collapse; font-family: sans-serif; }
    .calendar-table th { background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6; text-align: center; }
    .calendar-table td { height: 115px; width: 14%; border: 1px solid #dee2e6; vertical-align: top; padding: 5px; }
    .day-number { font-weight: bold; margin-bottom: 5px; color: #555; }
    .residente-label { 
        padding: 6px; border-radius: 4px; font-size: 0.82em; font-weight: bold; 
        text-align: center; margin-top: 8px; color: #1a1a1a; border: 1px solid rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias Nefrología")


# --- 4. CONFIGURACIÓN DE PLANTILLA (Sidebar) ---
st.sidebar.header("1. Plantilla de Residentes")
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

USER_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_residentes.iterrows()}
USER_R_MAP = {row["Nombre"]: row["R"] for _, row in df_residentes.iterrows()}

st.sidebar.header("2. Periodo")
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
mes_sel = st.sidebar.selectbox("Mes", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
anio_sel = st.sidebar.number_input("Año", value=2026)

primer_dia = datetime(anio_sel, mes_sel, 1)
ultimo_dia_mes = calendar.monthrange(anio_sel, mes_sel)[1]
rango_fechas = pd.date_range(primer_dia, periods=ultimo_dia_mes)


# --- 5. GESTIÓN DE AUSENCIAS ---
st.subheader("📅 Registro de Ausencias (Rojos)")

tabs = st.tabs([row["Nombre"] for _, row in df_residentes.iterrows()])

for i, (idx, row) in enumerate(df_residentes.iterrows()):
    nombre = row["Nombre"]
    with tabs[i]:
        if nombre not in st.session_state.ausencias_globales:
            st.session_state.ausencias_globales[nombre] = set()
        
        actuales = [d for d in st.session_state.ausencias_globales[nombre] if d.month == mes_sel and d.year == anio_sel]
        
        seleccion = st.multiselect(f"Selecciona días rojos para {nombre}:", rango_fechas, default=actuales, format_func=lambda x: x.strftime('%d'), key=f"m_{nombre}_{mes_sel}")
        
        st.session_state.ausencias_globales[nombre] = {d for d in st.session_state.ausencias_globales[nombre] if not (d.month == mes_sel and d.year == anio_sel)}
        for d in seleccion:
            st.session_state.ausencias_globales[nombre].add(d)

if st.button("☁️ Sincronizar / Guardar en la Nube"):
    if db is None:
        st.error("❌ No se puede guardar: No hay conexión a Firestore. Revisa los Secrets.")
    else:
        with st.spinner("Guardando en Firestore..."):
            exito = True
            for nombre, fechas in st.session_state.ausencias_globales.items():
                if not guardar_ausencias_db(nombre, fechas):
                    exito = False
            if exito:
                st.success("✅ ¡Datos guardados permanentemente en Google Cloud!")


# --- 6. RENDERIZADO DEL CALENDARIO ---
def render_calendar_html(df_plan):
    plan_dict = {row['Fecha']: row['Residente'] for _, row in df_plan.iterrows()}
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(anio_sel, mes_sel)
    html = '<table class="calendar-table"><thead><tr>'
    for d in ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]: html += f'<th>{d}</th>'
    html += '</tr></thead><tbody>'
    for week in month_days:
        html += '<tr>'
        for day in week:
            if day == 0: html += '<td style="background-color: #f1f1f1;"></td>'
            else:
                f_str = f"{anio_sel}-{mes_sel:02d}-{day:02d}"
                res = plan_dict.get(f_str, "VACÍO")
                color = USER_COLOR_MAP.get(res, "#ffffff")
                label = f"{res} ({USER_R_MAP.get(res, '')})" if res != "VACÍO" else "VACÍO"
                style = f'background-color: {color};' if res != "VACÍO" else ""
                html += f'<td><div class="day-number">{day}</div><div class="residente-label" style="{style}">{label}</div></td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html


# --- 7. MOTOR DE RESOLUCIÓN DE GUARDIAS ---
def resolver():
    model = cp_model.CpModel()
    num_res, num_dias = len(df_residentes), len(rango_fechas)
    g = {}
    
    for r in range(num_res):
        for d in range(num_dias): g[(r, d)] = model.NewBoolVar(f'r{r}d{d}')
    
    for d in range(num_dias):
        model.Add(sum(g[(r, d)] for r in range(num_res)) <= 1)
        
        for r in range(num_res):
            nombre = df_residentes.iloc[r]["Nombre"]
            if rango_fechas[d] in st.session_state.ausencias_globales.get(nombre, set()):
                model.Add(g[(r, d)] == 0)
            if d < num_dias - 1: model.Add(g[(r, d)] + g[(r, d+1)] <= 1)
            if rango_fechas[d].weekday() == 3: # Jueves
                for dt in [1, 2, 3]:
                    if d + dt < num_dias: model.Add(g[(r, d+dt)] == 0).OnlyEnforceIf(g[(r, d)])
    
    for r in range(num_res):
        model.Add(sum(g[(r, d)] for d in range(num_dias)) <= df_residentes.iloc[r]["Tope"])
        for wd in range(7): 
            idx_wd = [d for d in range(num_dias) if rango_fechas[d].weekday() == wd]
            model.Add(sum(g[(r, d)] for d in idx_wd) <= 2)

    objetivos = []
    for d in range(num_dias):
        wd = rango_fechas[d].weekday()
        peso = 1 if wd == 4 else (10 if wd == 1 else (20 if wd == 2 else 100))
        for r in range(num_res): objetivos.append(g[(r, d)] * peso)
    
    model.Maximize(sum(objetivos))
    
    solver = cp_model.CpSolver()
    if solver.Solve(model) in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        res = []
        for d in range(num_dias):
            nom = "VACÍO"
            for r in range(num_res):
                if solver.Value(g[(r, d)]) == 1: nom = df_residentes.iloc[r]["Nombre"]
            res.append({"Fecha": rango_fechas[d].strftime('%Y-%m-%d'), "Residente": nom})
        return pd.DataFrame(res)
    return None


# --- 8. EJECUCIÓN ---
st.divider()
if st.button("🚀 Generar Planificación Final"):
    with st.spinner("Optimizando cuadrante..."):
        df_f = resolver()
        if df_f is not None:
            st.write(render_calendar_html(df_f), unsafe_allow_html=True)
            
            st.divider()
            st.subheader("📊 Control de Equidad")
            conteo = df_f[df_f["Residente"] != "VACÍO"]["Residente"].value_counts().reset_index()
            conteo.columns = ["Residente", "Total Guardias"]
            st.table(conteo)
        else:
            st.error("No hay solución matemática posible. Prueba a subir algún tope de guardia o quitar alguna ausencia.")
