import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import calendar
from ortools.sat.python import cp_model
from google.cloud import firestore
from google.oauth2 import service_account
import json
import base64
import random

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="NefroPlanner Pro", layout="wide")

# --- 2. CONEXIÓN A FIRESTORE ---
@st.cache_resource
def iniciar_firestore():
    try:
        b64_string = st.secrets["FIREBASE_B64"]
        json_string = base64.b64decode(b64_string).decode('utf-8')
        creds_dict = json.loads(json_string)
        
        creds = service_account.Credentials.from_service_account_info(creds_dict)
        client = firestore.Client(credentials=creds, project=creds_dict["project_id"])
        return client
    except Exception as e:
        st.error(f"Error crítico al conectar con Firestore: {e}")
        return None

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
    if db is None: return False
    try:
        fechas_str = [f.strftime('%Y-%m-%d') for f in lista_fechas]
        db.collection("ausencias").document(nombre).set({"fechas": fechas_str})
        return True
    except: return False

if 'ausencias_globales' not in st.session_state:
    st.session_state.ausencias_globales = cargar_ausencias_db()


# --- 3. ESTILOS CSS BASE ---
estilos_css = """
<style>
    body { font-family: sans-serif; }
    .calendar-table { width: 100%; border-collapse: collapse; margin-bottom: 30px; }
    .calendar-table th { background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6; text-align: center; }
    .calendar-table td { height: 115px; width: 14%; border: 1px solid #dee2e6; vertical-align: top; padding: 5px; }
    .day-number { font-weight: bold; margin-bottom: 5px; color: #555; }
    .residente-label { 
        padding: 6px; border-radius: 4px; font-size: 0.82em; font-weight: bold; 
        text-align: center; margin-top: 8px; color: #1a1a1a; border: 1px solid rgba(0,0,0,0.1);
    }
    .mes-titulo { color: #2c3e50; margin-top: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
</style>
"""
st.markdown(estilos_css, unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias Nefrología")

# --- 4. CONFIGURACIÓN DE PLANTILLA ---
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

st.sidebar.header("2. Periodo de Planificación")
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

col_a, col_b = st.sidebar.columns(2)
mes_ini = col_a.selectbox("Mes Inicio", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
mes_fin = col_b.selectbox("Mes Fin", range(1, 13), index=8, format_func=lambda x: mes_nombres[x-1])
anio_sel = st.sidebar.number_input("Año", value=2026)

if mes_fin < mes_ini:
    st.sidebar.error("El Mes Fin debe ser igual o posterior al Mes Inicio.")
    st.stop()

# Generar rango de fechas global
primer_dia = datetime(anio_sel, mes_ini, 1)
ultimo_dia_mes = calendar.monthrange(anio_sel, mes_fin)[1]
ultimo_dia = datetime(anio_sel, mes_fin, ultimo_dia_mes)
rango_fechas = pd.date_range(primer_dia, ultimo_dia)


# --- 5. GESTIÓN DE AUSENCIAS ---
st.subheader("📅 Registro de Ausencias (Rojos)")

tabs = st.tabs([row["Nombre"] for _, row in df_residentes.iterrows()])

for i, (idx, row) in enumerate(df_residentes.iterrows()):
    nombre = row["Nombre"]
    with tabs[i]:
        if nombre not in st.session_state.ausencias_globales:
            st.session_state.ausencias_globales[nombre] = set()
        
        actuales = [d for d in st.session_state.ausencias_globales[nombre] if primer_dia <= d <= ultimo_dia]
        
        seleccion = st.multiselect(
            f"Selecciona días rojos para {nombre} (Entre {mes_nombres[mes_ini-1]} y {mes_nombres[mes_fin-1]}):", 
            rango_fechas, 
            default=actuales, 
            format_func=lambda x: f"{x.day} {mes_nombres[x.month-1]}", 
            key=f"m_{nombre}_{mes_ini}_{mes_fin}"
        )
        
        st.session_state.ausencias_globales[nombre] = {d for d in st.session_state.ausencias_globales[nombre] if not (primer_dia <= d <= ultimo_dia)}
        for d in seleccion:
            st.session_state.ausencias_globales[nombre].add(d)

if st.button("☁️ Sincronizar / Guardar en la Nube"):
    with st.spinner("Guardando en Firestore..."):
        exito = True
        for nombre, fechas in st.session_state.ausencias_globales.items():
            if not guardar_ausencias_db(nombre, fechas): exito = False
        if exito: st.success("✅ ¡Datos guardados permanentemente!")


# --- 6. RENDERIZADO DEL CALENDARIO POR MES ---
def render_mes_html(df_plan, mes_objetivo):
    plan_dict = {row['Fecha']: row['Residente'] for _, row in df_plan.iterrows()}
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(anio_sel, mes_objetivo)
    
    html = f'<h3 class="mes-titulo">{mes_nombres[mes_objetivo-1]} {anio_sel}</h3>'
    html += '<table class="calendar-table"><thead><tr>'
    for d in ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]: html += f'<th>{d}</th>'
    html += '</tr></thead><tbody>'
    
    for week in month_days:
        html += '<tr>'
        for day in week:
            if day == 0: html += '<td style="background-color: #f1f1f1;"></td>'
            else:
                f_str = f"{anio_sel}-{mes_objetivo:02d}-{day:02d}"
                res = plan_dict.get(f_str, "VACÍO")
                color = USER_COLOR_MAP.get(res, "#ffffff")
                label = f"{res} ({USER_R_MAP.get(res, '')})" if res != "VACÍO" else "VACÍO"
                style = f'background-color: {color};' if res != "VACÍO" else ""
                html += f'<td><div class="day-number">{day}</div><div class="residente-label" style="{style}">{label}</div></td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html


# --- 7. MOTOR DE RESOLUCIÓN MULTI-MES ---
def resolver():
    model = cp_model.CpModel()
    num_res, num_dias = len(df_residentes), len(rango_fechas)
    g = {}
    
    for r in range(num_res):
        for d in range(num_dias): g[(r, d)] = model.NewBoolVar(f'r{r}d{d}')
    
    for d in range(num_dias):
        # Máximo 1 residente por día
        model.Add(sum(g[(r, d)] for r in range(num_res)) <= 1)
        
        for r in range(num_res):
            nombre = df_residentes.iloc[r]["Nombre"]
            
            # Ausencias programadas
            if rango_fechas[d] in st.session_state.ausencias_globales.get(nombre, set()):
                model.Add(g[(r, d)] == 0)
                
            # Regla 48h estricta
            if d < num_dias - 1: model.Add(g[(r, d)] + g[(r, d+1)] <= 1)
            
            # --- REGLA ESTRICTA 1: Jueves -> Libra Vie/Sab/Dom ---
            if rango_fechas[d].weekday() == 3: # Jueves
                for dt in [1, 2, 3]:
                    if d + dt < num_dias: model.Add(g[(r, d+dt)] == 0).OnlyEnforceIf(g[(r, d)])
                    
            # --- REGLA ESTRICTA 2: Si hace Viernes, HACE el Domingo (pero el Viernes puede quedar vacío) ---
            if rango_fechas[d].weekday() == 4: # Viernes
                if d + 2 < num_dias: # Domingo
                    model.Add(g[(r, d)] <= g[(r, d+2)])
    
    objetivos = []
    
    meses_presentes = list(set(rango_fechas.month))
    for mes in meses_presentes:
        indices_del_mes = [d for d in range(num_dias) if rango_fechas[d].month == mes]
        idx_findes = [d for d in indices_del_mes if rango_fechas[d].weekday() in [5, 6]] # Sábados y Domingos
        
        for r in range(num_res):
            tope_mensual = df_residentes.iloc[r]["Tope"]
            
            # Control del Tope general
            model.Add(sum(g[(r, d)] for d in indices_del_mes) <= tope_mensual)
            
            # --- REGLA EQUIDAD FINES DE SEMANA ---
            if tope_mensual >= 6:
                max_findes = 2
            elif tope_mensual >= 4:
                max_findes = 2
            else:
                max_findes = 1
            model.Add(sum(g[(r, d)] for d in idx_findes) <= max_findes)
            
            # Control para no repetir el mismo día > 2 veces
            for wd in range(7): 
                idx_wd_mes = [d for d in indices_del_mes if rango_fechas[d].weekday() == wd]
                suma_dias = sum(g[(r, d)] for d in idx_wd_mes)
                
                model.Add(suma_dias <= 2) # Hard limit
                
                # Multa por equidad
                hace_dos = model.NewBoolVar(f'r{r}_m{mes}_wd{wd}_hace_dos')
                model.Add(suma_dias <= 1 + hace_dos)
                objetivos.append(hace_dos * -50000)

    for d in range(num_dias):
        wd = rango_fechas[d].weekday()
        # Pesos anti-vacíos base
        if wd == 4: peso_base = 100000      # Viernes (Pierde menos si se queda vacío)
        elif wd == 1: peso_base = 101000    # Martes
        elif wd == 2: peso_base = 102000    # Miércoles
        else: peso_base = 110000            # Resto
        
        for r in range(num_res): 
            peso_final = peso_base + random.randint(1, 999) 
            objetivos.append(g[(r, d)] * peso_final)
    
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


# --- 8. EJECUCIÓN Y TABLA DE ESTADÍSTICAS ---
st.divider()
if st.button("🚀 Generar Planificación Final", type="primary"):
    with st.spinner(f"Optimizando de forma equitativa desde {mes_nombres[mes_ini-1]} hasta {mes_nombres[mes_fin-1]}..."):
        df_f = resolver()
        
        if df_f is not None:
            # Preparar el archivo HTML para descarga
            html_descarga = f"<html><head><meta charset='utf-8'>{estilos_css}</head><body>"
            html_descarga += "<h1>🏥 Planificación de Guardias - Nefrología</h1>"
            
            meses_a_pintar = range(mes_ini, mes_fin + 1)
            for m in meses_a_pintar:
                mes_html = render_mes_html(df_f, m)
                st.write(mes_html, unsafe_allow_html=True)
                html_descarga += mes_html
                
            html_descarga += "</body></html>"
            
            st.divider()
            st.subheader("📊 Resumen de Guardias y Cobertura")
            
            # Preparar datos para tabla y CSV
            df_valid = df_f[df_f["Residente"] != "VACÍO"].copy()
            df_valid["Fecha"] = pd.to_datetime(df_valid["Fecha"])
            
            dias_semana_str = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            df_valid["Dia"] = df_valid["Fecha"].dt.weekday.map(lambda x: dias_semana_str[x])
            df_valid["Residente_R"] = df_valid["Residente"].apply(lambda x: f"{x} ({USER_R_MAP.get(x, '')})")
            
            tabla = pd.crosstab(df_valid["Residente_R"], df_valid["Dia"])
            
            for d in dias_semana_str:
                if d not in tabla.columns: tabla[d] = 0
                    
            tabla = tabla[dias_semana_str]
            tabla.index.name = "Residente"
            
            tabla["Total Guardias"] = tabla.sum(axis=1)
            tabla.loc["Total Cobertura"] = tabla.sum(axis=0)
            
            st.dataframe(tabla.style.format(precision=0), use_container_width=True)
            
            # --- ZONA DE DESCARGAS ---
            st.divider()
            st.subheader("📥 Exportar Planificación")
            col1, col2 = st.columns(2)
            
            # Botón 1: HTML visual
            nombre_archivo_html = f"Guardias_{mes_nombres[mes_ini-1]}_{mes_nombres[mes_fin-1]}_{anio_sel}.html"
            col1.download_button(
                label="🎨 Descargar Calendario Visual (Imprimible)",
                data=html_descarga,
                file_name=nombre_archivo_html,
                mime="text/html",
                type="primary"
            )
            
            # Botón 2: CSV de datos puros
            nombre_archivo_csv = f"Datos_Guardias_{mes_nombres[mes_ini-1]}_{mes_nombres[mes_fin-1]}_{anio_sel}.csv"
            # Formatear fecha para el CSV
            df_csv = df_valid[["Fecha", "Dia", "Residente_R"]].copy()
            df_csv["Fecha"] = df_csv["Fecha"].dt.strftime('%Y-%m-%d')
            csv_data = df_csv.to_csv(index=False).encode('utf-8')
            
            col2.download_button(
                label="📊 Descargar Datos en Formato Excel (CSV)",
                data=csv_data,
                file_name=nombre_archivo_csv,
                mime="text/csv"
            )
            
        else:
            st.error("❌ No hay solución matemática posible. Prueba a flexibilizar ausencias o topes de guardia.")
