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
        return client
    except Exception as e:
        st.error(f"Error crítico al conectar con Firestore: {e}")
        return None

db = iniciar_firestore()

# --- FUNCIONES DE PERSISTENCIA ---
def cargar_datos_db(coleccion):
    dict_recuperado = {}
    if db is None: return dict_recuperado
    try:
        docs = db.collection(coleccion).stream()
        for doc in docs:
            dict_recuperado[doc.id] = doc.to_dict()
    except: pass
    return dict_recuperado

def guardar_documento_db(coleccion, doc_id, datos):
    if db is None: return False
    try:
        db.collection(coleccion).document(doc_id).set(datos)
        return True
    except: return False

# --- 3. CARGA DE DATOS INICIAL ---
if 'plantilla_adjuntos' not in st.session_state:
    datos = cargar_datos_db("plantilla_adjuntos")
    if datos:
        st.session_state.plantilla_adjuntos = pd.DataFrame.from_dict(datos, orient='index').reset_index(drop=True)
    else:
        st.session_state.plantilla_adjuntos = pd.DataFrame([{"Nombre": "Adjunto 1", "Tope": 4, "Color": "#444444"}])

if 'plantilla_residentes' not in st.session_state:
    datos = cargar_datos_db("plantilla_residentes")
    if datos:
        st.session_state.plantilla_residentes = pd.DataFrame.from_dict(datos, orient='index').reset_index(drop=True)
    else:
        st.session_state.plantilla_residentes = pd.DataFrame([{"Nombre": "Daniela", "Tope": 6, "R": "R4", "Color": "#FFC1CC"}])

if 'ausencias_globales' not in st.session_state:
    datos = cargar_datos_db("ausencias")
    st.session_state.ausencias_globales = {k: {datetime.strptime(f, '%Y-%m-%d') for f in v.get("fechas", [])} for k, v in datos.items()}

if 'plan_generado' not in st.session_state:
    st.session_state.plan_generado = None

# --- 4. ESTILOS CSS ---
estilos_css = """
<style>
    body { font-family: sans-serif; }
    .calendar-table { width: 100%; border-collapse: collapse; margin-bottom: 30px; }
    .calendar-table th { background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6; text-align: center; }
    .calendar-table td { height: 140px; width: 14%; border: 1px solid #dee2e6; vertical-align: top; padding: 5px; }
    .day-number { font-weight: bold; margin-bottom: 5px; color: #555; }
    .adjunto-label { padding: 4px; border-radius: 4px; font-size: 0.75em; font-weight: bold; text-align: center; margin-top: 2px; color: #fff; border: 1px solid rgba(0,0,0,0.1); }
    .residente-label { padding: 4px; border-radius: 4px; font-size: 0.75em; font-weight: bold; text-align: center; margin-top: 4px; color: #1a1a1a; border: 1px solid rgba(0,0,0,0.1); }
    .vacio-label { font-size: 0.7em; color: #aaa; text-align: center; margin-top: 4px; font-style: italic; }
    .summary-table { width: 100%; border-collapse: collapse; margin-top: 20px; margin-bottom: 40px; font-size: 0.95em; }
    .summary-table th { background-color: #e9ecef; padding: 12px; border: 1px solid #dee2e6; text-align: center; font-weight: bold; }
    .summary-table td { padding: 10px; border: 1px solid #dee2e6; text-align: center; }
</style>
"""
st.markdown(estilos_css, unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias")

# --- 5. CONFIGURACIÓN DE PLANTILLAS (Sidebar) ---
try:
    conf_c = {"Color": st.column_config.ColorColumn("🎨 Color")}
except: conf_c = {}

st.sidebar.header("👨‍⚕️ 1. Plantilla Adjuntos")
df_adjuntos = st.sidebar.data_editor(st.session_state.plantilla_adjuntos, num_rows="dynamic", key="edit_adj", column_config=conf_c)

st.sidebar.header("🎓 2. Plantilla Residentes")
df_residentes = st.sidebar.data_editor(st.session_state.plantilla_residentes, num_rows="dynamic", key="edit_res", column_config=conf_c)

ADJ_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_adjuntos.iterrows()}
RES_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_residentes.iterrows()}
USER_R_MAP = {row["Nombre"]: row["R"] for _, row in df_residentes.iterrows() if "R" in row}

st.sidebar.header("📅 3. Periodo")
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
col_a, col_b = st.sidebar.columns(2)
mes_ini = col_a.selectbox("Inicio", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
mes_fin = col_b.selectbox("Fin", range(1, 13), index=8, format_func=lambda x: mes_nombres[x-1])
anio_sel = st.sidebar.number_input("Año", value=2026)

primer_dia = datetime(anio_sel, mes_ini, 1)
ultimo_dia = datetime(anio_sel, mes_fin, calendar.monthrange(anio_sel, mes_fin)[1])
rango_fechas = pd.date_range(primer_dia, ultimo_dia)

# --- 6. AUSENCIAS ---
st.subheader("📅 Grilla de Ausencias")
def generar_grilla(nombres, key_p):
    data = {d.strftime('%d/%m'): [d in st.session_state.ausencias_globales.get(n, set()) for n in nombres] for d in rango_fechas}
    return st.data_editor(pd.DataFrame(data, index=nombres), use_container_width=True, key=f"g_{key_p}", column_config={c: st.column_config.CheckboxColumn(c) for c in data.keys()})

t1, t2 = st.tabs(["👨‍⚕️ Adjuntos", "🎓 Residentes"])
with t1: g_adj = generar_grilla(df_adjuntos["Nombre"].tolist(), "adj")
with t2: g_res = generar_grilla(df_residentes["Nombre"].tolist(), "res")

if st.button("☁️ Sincronizar y Guardar TODO"):
    with st.spinner("Sincronizando con la nube..."):
        # Guardar Plantillas
        for i, row in df_adjuntos.iterrows(): guardar_documento_db("plantilla_adjuntos", str(i), row.to_dict())
        for i, row in df_residentes.iterrows(): guardar_documento_db("plantilla_residentes", str(i), row.to_dict())
        # Guardar Ausencias
        for g, nombres in [(g_adj, df_adjuntos["Nombre"].tolist()), (g_res, df_residentes["Nombre"].tolist())]:
            for nom in nombres:
                row = g.loc[nom]
                nuevas = {rango_fechas[i] for i, v in enumerate(row) if v}
                fuera = {d for d in st.session_state.ausencias_globales.get(nom, set()) if not (primer_dia <= d <= ultimo_dia)}
                final = nuevas.union(fuera)
                st.session_state.ausencias_globales[nom] = final
                guardar_documento_db("ausencias", nom, {"fechas": [d.strftime('%Y-%m-%d') for d in final]})
        st.success("✅ ¡Todo guardado! Los nombres y colores persistirán ahora.")

# --- 7. MOTOR ---
def resolver():
    model = cp_model.CpModel()
    num_dias = len(rango_fechas)
    
    def aplicar_reglas(staff, prefix, es_adjunto):
        n = len(staff)
        v = {(r, d): model.NewBoolVar(f'{prefix}_r{r}d{d}') for r in range(n) for d in range(num_dias)}
        for d in range(num_dias):
            # REGLA DURA ADJUNTOS: == 1 (PROHIBIDO VACÍOS)
            if es_adjunto: model.Add(sum(v[(r, d)] for r in range(n)) == 1)
            else: model.Add(sum(v[(r, d)] for r in range(n)) <= 1)
            
            for r in range(n):
                nom = staff.iloc[r]["Nombre"]
                if rango_fechas[d] in st.session_state.ausencias_globales.get(nom, set()): model.Add(v[(r, d)] == 0)
                if d < num_dias - 1: model.Add(v[(r, d)] + v[(r, d+1)] <= 1)
                # Sábado -> Jueves siguiente prohibido
                if rango_fechas[d].weekday() == 5 and d + 5 < num_dias: model.Add(v[(r, d+5)] == 0).OnlyEnforceIf(v[(r, d)])
                # Jueves -> Sábado prohibido
                if rango_fechas[d].weekday() == 3 and d + 2 < num_dias: model.Add(v[(r, d+2)] == 0).OnlyEnforceIf(v[(r, d)])
                # Doblete Viernes-Domingo (SOLO RESIDENTES)
                if not es_adjunto and rango_fechas[d].weekday() == 4 and d + 2 < num_dias: model.Add(v[(r, d)] <= v[(r, d+2)])

        objs = []
        for mes in list(set(rango_fechas.month)):
            idx_m = [d for d in range(num_dias) if rango_fechas[d].month == mes]
            idx_f = [d for d in idx_m if rango_fechas[d].weekday() in [5, 6]]
            for r in range(n):
                t = staff.iloc[r]["Tope"]
                model.Add(sum(v[(r, d)] for d in idx_m) <= t)
                mf = 2 if t >= 4 else 1
                model.Add(sum(v[(r, d)] for d in idx_f) <= mf)
                for wd in range(7):
                    idx_wd = [d for d in idx_m if rango_fechas[d].weekday() == wd]
                    model.Add(sum(v[(r, d)] for d in idx_wd) <= 2)
        
        for d in range(num_dias):
            wd = rango_fechas[d].weekday()
            pb = 100000 if wd == 4 else (101000 if wd == 1 else (102000 if wd == 2 else 110000))
            for r in range(n): objs.append(v[(r, d)] * (pb + random.randint(1, 999)))
        return v, objs

    v_adj, o_adj = aplicar_reglas(df_adjuntos, "adj", True)
    v_res, o_res = aplicar_reglas(df_residentes, "res", False)
    model.Maximize(sum(o_adj) + sum(o_res))
    solver = cp_model.CpSolver()
    if solver.Solve(model) in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        res = []
        for d in range(num_dias):
            an, rn = "VACÍO", "VACÍO"
            for r in range(len(df_adjuntos)):
                if solver.Value(v_adj[(r, d)]) == 1: an = df_adjuntos.iloc[r]["Nombre"]
            for r in range(len(df_residentes)):
                if solver.Value(v_res[(r, d)]) == 1: rn = df_residentes.iloc[r]["Nombre"]
            res.append({"Fecha": rango_fechas[d].strftime('%Y-%m-%d'), "Adjunto": an, "Residente": rn})
        return pd.DataFrame(res)
    return None

# --- 8. RENDER ---
def render_mes_html(df, m):
    cal = calendar.Calendar(firstweekday=0)
    html = f'<h3 class="mes-titulo">{mes_nombres[m-1]} {anio_sel}</h3><table class="calendar-table"><thead><tr>'
    for d in ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]: html += f'<th>{d}</th>'
    html += '</tr></thead><tbody>'
    for week in cal.monthdayscalendar(anio_sel, m):
        html += '<tr>'
        for day in week:
            if day == 0: html += '<td style="background-color: #f1f1f1;"></td>'
            else:
                f_str = f"{anio_sel}-{m:02d}-{day:02d}"
                row = df[df["Fecha"] == f_str].iloc[0]
                html += f'<td><div class="day-number">{day}</div>'
                if row["Adjunto"] != "VACÍO": html += f'<div class="adjunto-label" style="background-color: {ADJ_COLOR_MAP.get(row["Adjunto"], "#444")};">{row["Adjunto"]}</div>'
                else: html += '<div class="vacio-label">Adj: VACÍO</div>'
                if row["Residente"] != "VACÍO": html += f'<div class="residente-label" style="background-color: {RES_COLOR_MAP.get(row["Residente"], "#fff")};">{row["Residente"]} ({USER_R_MAP.get(row["Residente"], "")})</div>'
                else: html += '<div class="vacio-label">Res: VACÍO</div>'
                html += '</td>'
        html += '</tr>'
    return html + '</tbody></table>'

st.divider()
if st.button("🚀 Generar Planificación", type="primary"):
    df_f = resolver()
    if df_f is not None:
        def build_stats(df, col, staff, es_res):
            df_v = df[df[col] != "VACÍO"].copy()
            df_v["Fecha"] = pd.to_datetime(df_v["Fecha"])
            ds = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            df_v["Dia"] = df_v["Fecha"].dt.weekday.map(lambda x: ds[x])
            lbl = df_v[col].apply(lambda x: f"{x} ({USER_R_MAP.get(x, '')})") if es_res else df_v[col]
            ord_p = [f"{r['Nombre']} ({r['R']})" for _, r in staff.iterrows()] if es_res else staff["Nombre"].tolist()
            t = pd.crosstab(lbl, df_v["Dia"])
            for d in ds:
                if d not in t.columns: t[d] = 0
            t = t[ds].reindex(ord_p, fill_value=0)
            t["TOTAL PERIODO"] = t.sum(axis=1) # Columna de total
            return t
        
        t_adj = build_stats(df_f, "Adjunto", df_adjuntos, False)
        t_res = build_stats(df_f, "Residente", df_residentes, True)
        
        html = f"<html><head><meta charset='utf-8'>{estilos_css}</head><body><h1>Planificación</h1>"
        for m in range(mes_ini, mes_fin+1): html += render_mes_html(df_f, m)
        html += "<h2>Estadísticas Adjuntos</h2>" + t_adj.to_html(classes="summary-table")
        html += "<h2>Estadísticas Residentes</h2>" + t_res.to_html(classes="summary-table")
        html += "</body></html>"
        st.session_state.plan_generado = {"df": df_f, "html": html, "t_adj": t_adj, "t_res": t_res, "meses": range(mes_ini, mes_fin+1)}
    else: st.error("❌ Error: Los topes de los adjuntos no son suficientes para cubrir todos los días o hay demasiadas ausencias.")

if st.session_state.plan_generado:
    d = st.session_state.plan_generado
    for m in d["meses"]: st.write(render_mes_html(d["df"], m), unsafe_allow_html=True)
    st.divider()
    st.subheader("📊 Resumen Adjuntos")
    st.dataframe(d["t_adj"])
    st.subheader("📊 Resumen Residentes")
    st.dataframe(d["t_res"])
    st.download_button("🎨 Descargar Plan", d["html"], "Plan.html", "text/html", type="primary")
