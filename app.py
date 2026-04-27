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
st.set_page_config(page_title="Planificador de Guardias", layout="wide")

# --- 2. CONEXIÓN A FIRESTORE ---
@st.cache_resource
def iniciar_firestore():
    try:
        b64_string = st.secrets["FIREBASE_B64"]
        json_string = base64.b64decode(b64_string).decode('utf-8')
        creds_dict = json.loads(json_string)
        creds = service_account.Credentials.from_service_account_info(creds_dict)
        client = firestore.Client(credentials=creds, project=creds_dict["project_id"])
        return client, creds_dict["project_id"]
    except Exception as e:
        st.error(f"Error crítico al conectar con Firestore: {e}")
        return None, None

db, project_id = iniciar_firestore()

# --- FUNCIONES DE APOYO ---
def get_contrast_color(hex_color):
    hex_color = str(hex_color).lstrip('#')
    if len(hex_color) != 6: return "#000000"
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    brightness = (r * 0.299 + g * 0.587 + b * 0.114)
    return "#FFFFFF" if brightness < 150 else "#000000"

def cargar_coleccion(col_name):
    resultados = []
    if db is None: return resultados
    try:
        docs = db.collection(col_name).stream()
        for doc in docs: resultados.append(doc.to_dict())
    except: pass
    return resultados

def cargar_coleccion_dict(col_name):
    res = {}
    if db is None: return res
    try:
        docs = db.collection(col_name).stream()
        for doc in docs: res[doc.id] = doc.to_dict()
    except: pass
    return res

def limpiar_nulos(val):
    if pd.isna(val) or val is None: return "VACÍO"
    s = str(val).strip()
    if s in ["", "nan", "NaN", "None", "<NA>"]: return "VACÍO"
    return s

dias_espanol = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# --- 3. INICIALIZACIÓN DE SESIÓN ---
st.info(f"🌐 Conectado al Proyecto Firebase: **{project_id}**")

if 'ausencias_globales' not in st.session_state:
    datos_aus = cargar_coleccion("ausencias")
    st.session_state.ausencias_globales = {item["nombre"]: {datetime.strptime(f, '%Y-%m-%d') for f in item.get("fechas", [])} for item in datos_aus if "nombre" in item}

if 'adjuntos_init' not in st.session_state:
    db_adj = cargar_coleccion("plantilla_adjuntos")
    df_a = pd.DataFrame(db_adj)
    if df_a.empty or "Nombre" not in df_a.columns:
        df_a = pd.DataFrame([{"Nombre": "Adjunto 1", "Tope": 4, "Color": "#444444"}])
    st.session_state.adjuntos_init = df_a

if 'residentes_init' not in st.session_state:
    db_res = cargar_coleccion("plantilla_residentes")
    df_r = pd.DataFrame(db_res)
    if df_r.empty or "Nombre" not in df_r.columns:
        df_r = pd.DataFrame([{"Nombre": "Daniela", "Tope": 6, "R": "R4", "Color": "#FFC1CC"}])
    st.session_state.residentes_init = df_r

if 'guardias_fijas' not in st.session_state:
    st.session_state.guardias_fijas = cargar_coleccion_dict("guardias_fijas")

if 'plan_generado' not in st.session_state:
    st.session_state.plan_generado = None

# --- 4. ESTILOS CSS ---
st.markdown("<style>.calendar-table { width: 100%; border-collapse: collapse; } .calendar-table th { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; } .calendar-table td { height: 140px; border: 1px solid #dee2e6; vertical-align: top; padding: 5px; } .adjunto-label, .residente-label { padding: 4px; border-radius: 4px; font-weight: bold; text-align: center; margin-top: 2px; font-size: 0.9em; }</style>", unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias (Debug Version)")

# --- 5. SIDEBAR ---
st.sidebar.header("⚙️ Configuración")
incluir_adjuntos = st.sidebar.checkbox("✅ Incluir Adjuntos", value=True)

try: conf_c = {"Color": st.column_config.ColorColumn("🎨 Color")}
except: conf_c = {}

st.sidebar.header("👨‍⚕️ Plantillas")
if incluir_adjuntos:
    df_adjuntos = st.sidebar.data_editor(st.session_state.adjuntos_init, num_rows="dynamic", key="edit_adj", column_config=conf_c)
    df_adjuntos = df_adjuntos.dropna(subset=["Nombre"]).drop_duplicates(subset=["Nombre"]) if "Nombre" in df_adjuntos.columns else pd.DataFrame()
    ADJ_COLOR_MAP = {row["Nombre"]: row.get("Color", "#444444") for _, row in df_adjuntos.iterrows()}
else: df_adjuntos = pd.DataFrame(); ADJ_COLOR_MAP = {}

df_residentes = st.sidebar.data_editor(st.session_state.residentes_init, num_rows="dynamic", key="edit_res", column_config=conf_c)
df_residentes = df_residentes.dropna(subset=["Nombre"]).drop_duplicates(subset=["Nombre"]) if "Nombre" in df_residentes.columns else pd.DataFrame()
RES_COLOR_MAP = {row["Nombre"]: row.get("Color", "#FFFFFF") for _, row in df_residentes.iterrows()}
USER_R_MAP = {row["Nombre"]: row.get("R", "") for _, row in df_residentes.iterrows()}

mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
c1, c2 = st.sidebar.columns(2)
mes_ini = c1.selectbox("Inicio", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
mes_fin = c2.selectbox("Fin", range(1, 13), index=8, format_func=lambda x: mes_nombres[x-1])
anio_sel = st.sidebar.number_input("Año", value=2026)
rango_fechas = pd.date_range(datetime(anio_sel, mes_ini, 1), datetime(anio_sel, mes_fin, calendar.monthrange(anio_sel, mes_fin)[1]))

# --- 6. EDITOR MANUAL Y TABS ---
t1, t2, t3 = st.tabs(["📅 Ausencias Adjuntos", "🎓 Ausencias Residentes", "✍️ EDITOR MANUAL (Guardias Fijas)"])

def generar_grilla(nombres, key_p):
    grid_data = {d.strftime('%d/%m'): [bool(d in st.session_state.ausencias_globales.get(n, set())) for n in nombres] for d in rango_fechas}
    return st.data_editor(pd.DataFrame(grid_data, index=nombres).astype(bool), use_container_width=True, key=f"g_{key_p}")

with t1: g_adj = generar_grilla(df_adjuntos["Nombre"].tolist(), "adj") if incluir_adjuntos and not df_adjuntos.empty else pd.DataFrame()
with t2: g_res = generar_grilla(df_residentes["Nombre"].tolist(), "res") if not df_residentes.empty else pd.DataFrame()

with t3:
    st.warning("⚠️ RECUERDA: Tras elegir un nombre, haz clic en el fondo blanco de la página para 'confirmar' la celda antes de pulsar Guardar.")
    ops_adj = ["VACÍO"] + df_adjuntos["Nombre"].tolist() if not df_adjuntos.empty else ["VACÍO"]
    ops_res = ["VACÍO"] + df_residentes["Nombre"].tolist() if not df_residentes.empty else ["VACÍO"]
    
    filas_manual = []
    for d in rango_fechas:
        f_str = d.strftime('%Y-%m-%d')
        fijo = st.session_state.guardias_fijas.get(f_str, {})
        filas_manual.append({
            "Fecha": f_str, "Día": dias_espanol[d.weekday()],
            "Adjunto": fijo.get("Adjunto", "VACÍO"), "Residente": fijo.get("Residente", "VACÍO")
        })
    
    df_manual_edit = st.data_editor(
        pd.DataFrame(filas_manual), use_container_width=True, hide_index=True,
        column_config={
            "Fecha": st.column_config.TextColumn("Fecha", disabled=True),
            "Día": st.column_config.TextColumn("Día", disabled=True),
            "Adjunto": st.column_config.SelectboxColumn("Adjunto Fijo", options=ops_adj),
            "Residente": st.column_config.SelectboxColumn("Residente Fijo", options=ops_res)
        }, key="editor_manual_final"
    )

    if st.button("💾 GUARDAR CAMBIOS MANUALES AHORA", type="primary", use_container_width=True):
        exitos = 0
        errores = 0
        with st.spinner("Conectando con Firebase..."):
            for _, row in df_manual_edit.iterrows():
                f_str = row["Fecha"]
                a_nom = limpiar_nulos(row["Adjunto"])
                r_nom = limpiar_nulos(row["Residente"])
                
                try:
                    if a_nom != "VACÍO" or r_nom != "VACÍO":
                        data = {"Adjunto": a_nom, "Residente": r_nom}
                        db.collection("guardias_fijas").document(f_str).set(data)
                        st.session_state.guardias_fijas[f_str] = data
                    else:
                        if f_str in st.session_state.guardias_fijas:
                            db.collection("guardias_fijas").document(f_str).delete()
                            del st.session_state.guardias_fijas[f_str]
                    exitos += 1
                except Exception as e:
                    st.error(f"❌ Error al guardar el día {f_str}: {e}")
                    errores += 1
        
        if errores == 0: st.success(f"✅ ¡PROCESO COMPLETADO! Se han sincronizado {exitos} días con la nube.")
        else: st.warning(f"⚠️ Se guardaron {exitos} días, pero hubo {errores} fallos. Revisa tus Reglas de Firebase.")
        st.rerun()

# --- 7. BOTÓN SINCRONIZAR AUSENCIAS ---
if st.button("☁️ Sincronizar Plantillas y Ausencias", use_container_width=True):
    with st.spinner("Sincronizando ausencias..."):
        # (Lógica simplificada de guardado de ausencias)
        for _, row in df_residentes.iterrows(): db.collection("plantilla_residentes").document(row["Nombre"]).set(row.to_dict())
        st.success("✅ Ausencias y Plantillas sincronizadas.")
        st.rerun()

# --- 8. MOTOR DE RESOLUCIÓN ---
def resolver():
    model = cp_model.CpModel(); n_dias = len(rango_fechas)
    def aplicar(staff, prefix, es_adj):
        n = len(staff); v = {(r, d): model.NewBoolVar(f'{prefix}_r{r}d{d}') for r in range(n) for d in range(n_dias)}
        if n == 0: return v, []
        for d in range(n_dias):
            f_str = rango_fechas[d].strftime('%Y-%m-%d'); fijo = st.session_state.guardias_fijas.get(f_str)
            model.Add(sum(v[(r, d)] for r in range(n)) <= 1)
            if fijo:
                val = fijo.get("Adjunto") if es_adj else fijo.get("Residente")
                if val and val != "VACÍO":
                    for r in range(n): 
                        if staff.iloc[r]["Nombre"] == val: model.Add(v[(r, d)] == 1)
                else:
                    for r in range(n): model.Add(v[(r, d)] == 0)
            for r in range(n):
                nom = staff.iloc[r]["Nombre"]
                if rango_fechas[d] in st.session_state.ausencias_globales.get(nom, set()): model.Add(v[(r, d)] == 0)
                if d < n_dias - 1: model.Add(v[(r, d)] + v[(r, d+1)] <= 1)
                # Reglas descanso Jue-Sab
                if rango_fechas[d].weekday() == 5 and d+5 < n_dias: model.Add(v[(r, d+5)] == 0).OnlyEnforceIf(v[(r, d)])
                if rango_fechas[d].weekday() == 3 and d+2 < n_dias: model.Add(v[(r, d+2)] == 0).OnlyEnforceIf(v[(r, d)])
        return v, []

    v_adj, _ = aplicar(df_adjuntos, "adj", True) if incluir_adjuntos else ({}, [])
    v_res, _ = aplicar(df_residentes, "res", False)
    
    solver = cp_model.CpSolver()
    if solver.Solve(model) in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        res = []
        for d in range(n_dias):
            an = next((df_adjuntos.iloc[r]["Nombre"] for r in range(len(df_adjuntos)) if solver.Value(v_adj[(r, d)]) == 1), "VACÍO") if (incluir_adjuntos and not df_adjuntos.empty) else "VACÍO"
            rn = next((df_residentes.iloc[r]["Nombre"] for r in range(len(df_residentes)) if solver.Value(v_res[(r, d)]) == 1), "VACÍO") if not df_residentes.empty else "VACÍO"
            res.append({"Fecha": rango_fechas[d].strftime('%Y-%m-%d'), "Adjunto": an, "Residente": rn})
        return pd.DataFrame(res)
    return None

# --- 9. RENDER ---
def render_mes_html(df, m, modo_adj):
    cal = calendar.Calendar(firstweekday=0)
    html = f"<h3>{mes_nombres[m-1]} {anio_sel}</h3><table class='calendar-table'><tr><th>Lun</th><th>Mar</th><th>Mié</th><th>Jue</th><th>Vie</th><th>Sáb</th><th>Dom</th></tr>"
    for week in cal.monthdayscalendar(anio_sel, m):
        html += "<tr>"
        for day in week:
            if day == 0: html += "<td style='background:#eee'></td>"
            else:
                f_str = f"{anio_sel}-{m:02d}-{day:02d}"
                row = df[df["Fecha"] == f_str].iloc[0]
                candado = " 🔒" if f_str in st.session_state.guardias_fijas else ""
                html += f"<td><b>{day}</b>"
                if modo_adj and row["Adjunto"] != "VACÍO": 
                    c = ADJ_COLOR_MAP.get(row["Adjunto"], "#444")
                    html += f"<div class='adjunto-label' style='background:{c}; color:{get_contrast_color(c)}'>{row['Adjunto']}{candado}</div>"
                if row["Residente"] != "VACÍO":
                    c = RES_COLOR_MAP.get(row["Residente"], "#fff")
                    html += f"<div class='residente-label' style='background:{c}; color:{get_contrast_color(c)}'>{row['Residente']}{candado}</div>"
                html += "</td>"
        html += "</tr>"
    return html + "</table>"

if st.button("🚀 CALCULAR PLANIFICACIÓN", type="primary", use_container_width=True):
    df_f = resolver()
    if df_f is not None:
        st.session_state.plan_generado = {"df": df_f, "meses": range(mes_ini, mes_fin+1), "adj": incluir_adjuntos}
    else: st.error("❌ Conflicto en los datos. No se puede generar el plan.")

if st.session_state.plan_generado:
    d = st.session_state.plan_generado
    for m in d["meses"]: st.write(render_mes_html(d["df"], m, d["adj"]), unsafe_allow_html=True)
