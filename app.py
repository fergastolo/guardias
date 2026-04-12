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

def cargar_ausencias_db():
    ausencias_dict = {}
    if db is None: return ausencias_dict
    try:
        docs = db.collection("ausencias").stream()
        for doc in docs:
            data = doc.to_dict()
            fechas_obj = {datetime.strptime(f, '%Y-%m-%d') for f in data.get("fechas", [])}
            ausencias_dict[doc.id] = fechas_obj
    except: pass
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

if 'plan_generado' not in st.session_state:
    st.session_state.plan_generado = None

# --- 3. ESTILOS CSS ---
estilos_css = """
<style>
    body { font-family: sans-serif; }
    .calendar-table { width: 100%; border-collapse: collapse; margin-bottom: 30px; }
    .calendar-table th { background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6; text-align: center; }
    .calendar-table td { height: 140px; width: 14%; border: 1px solid #dee2e6; vertical-align: top; padding: 5px; }
    .day-number { font-weight: bold; margin-bottom: 5px; color: #555; }
    .adjunto-label { 
        padding: 4px; border-radius: 4px; font-size: 0.75em; font-weight: bold; 
        text-align: center; margin-top: 2px; color: #fff; border: 1px solid rgba(0,0,0,0.1);
    }
    .residente-label { 
        padding: 4px; border-radius: 4px; font-size: 0.75em; font-weight: bold; 
        text-align: center; margin-top: 4px; color: #1a1a1a; border: 1px solid rgba(0,0,0,0.1);
    }
    .vacio-label { font-size: 0.7em; color: #aaa; text-align: center; margin-top: 4px; font-style: italic; }
    .mes-titulo { color: #2c3e50; margin-top: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
    .summary-table { width: 100%; border-collapse: collapse; margin-top: 20px; margin-bottom: 40px; font-size: 0.95em; }
    .summary-table th { background-color: #e9ecef; padding: 12px; border: 1px solid #dee2e6; text-align: center; font-weight: bold; }
    .summary-table td { padding: 10px; border: 1px solid #dee2e6; text-align: center; }
</style>
"""
st.markdown(estilos_css, unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias Nefrología")

# --- 4. CONFIGURACIÓN DE PLANTILLAS ---
# Verificación de seguridad para versiones antiguas
try:
    config_color_adj = {"Color": st.column_config.ColorColumn("🎨 Color")}
    config_color_res = {"Color": st.column_config.ColorColumn("🎨 Color")}
except AttributeError:
    st.warning("⚠️ Tu versión de Streamlit es antigua. El selector de color visual no funcionará hasta que actualices (usa requirements.txt).")
    config_color_adj = {}
    config_color_res = {}

st.sidebar.header("👨‍⚕️ 1. Plantilla Adjuntos")
df_adj_init = pd.DataFrame([
    {"Nombre": "Adjunto 1", "Tope": 4, "Color": "#444444"},
    {"Nombre": "Adjunto 2", "Tope": 4, "Color": "#555555"},
    {"Nombre": "Adjunto 3", "Tope": 4, "Color": "#666666"},
])
df_adjuntos = st.sidebar.data_editor(df_adj_init, num_rows="dynamic", key="editor_adj", column_config=config_color_adj)

st.sidebar.header("🎓 2. Plantilla Residentes")
df_res_init = pd.DataFrame([
    {"Nombre": "Daniela", "Tope": 6, "R": "R4", "Color": "#FFC1CC"},
    {"Nombre": "Sandra", "Tope": 6, "R": "R3", "Color": "#FFDAB9"},
    {"Nombre": "Mavi", "Tope": 6, "R": "R3", "Color": "#B2E2F2"},
    {"Nombre": "Lei", "Tope": 4, "R": "R2", "Color": "#FF6B6B"},
    {"Nombre": "May", "Tope": 4, "R": "R2", "Color": "#D3D3D3"},
    {"Nombre": "Residente A", "Tope": 2, "R": "R1", "Color": "#E6B3FF"},
    {"Nombre": "Residente B", "Tope": 2, "R": "R1", "Color": "#B3FFB3"},
])
df_residentes = st.sidebar.data_editor(df_res_init, num_rows="dynamic", key="editor_res", column_config=config_color_res)

ADJ_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_adjuntos.iterrows()}
RES_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_residentes.iterrows()}
USER_R_MAP = {row["Nombre"]: row["R"] for _, row in df_residentes.iterrows()}

st.sidebar.header("📅 3. Periodo")
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
col_a, col_b = st.sidebar.columns(2)
mes_ini = col_a.selectbox("Inicio", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
mes_fin = col_b.selectbox("Fin", range(1, 13), index=8, format_func=lambda x: mes_nombres[x-1])
anio_sel = st.sidebar.number_input("Año", value=2026)

primer_dia = datetime(anio_sel, mes_ini, 1)
ultimo_dia_mes_val = calendar.monthrange(anio_sel, mes_fin)[1]
ultimo_dia = datetime(anio_sel, mes_fin, ultimo_dia_mes_val)
rango_fechas = pd.date_range(primer_dia, ultimo_dia)

# --- 5. GESTIÓN DE AUSENCIAS (GRILLA) ---
st.subheader("📅 Grilla de Ausencias")

def generar_grilla(nombres, key_prefix):
    data = {}
    for d in rango_fechas:
        col_name = d.strftime('%d/%m')
        data[col_name] = [d in st.session_state.ausencias_globales.get(nom, set()) for nom in nombres]
    df = pd.DataFrame(data, index=nombres)
    return st.data_editor(df, use_container_width=True, key=f"grid_{key_prefix}",
                         column_config={c: st.column_config.CheckboxColumn(c) for c in data.keys()})

col_abs_adj, col_abs_res = st.tabs(["👨‍⚕️ Adjuntos", "🎓 Residentes"])
with col_abs_adj: grid_adj = generar_grilla(df_adjuntos["Nombre"].tolist(), "adj")
with col_abs_res: grid_res = generar_grilla(df_residentes["Nombre"].tolist(), "res")

if st.button("☁️ Sincronizar y Guardar en la Nube"):
    for df_grid in [grid_adj, grid_res]:
        for nom in df_grid.index:
            row = df_grid.loc[nom]
            nuevas = {rango_fechas[i] for i, val in enumerate(row) if val}
            fuera = {d for d in st.session_state.ausencias_globales.get(nom, set()) if not (primer_dia <= d <= ultimo_dia)}
            st.session_state.ausencias_globales[nom] = nuevas.union(fuera)
    with st.spinner("Guardando..."):
        for nom, fechas in st.session_state.ausencias_globales.items(): guardar_ausencias_db(nom, fechas)
        st.success("✅ Datos guardados.")

# --- 6. RENDERIZADO DEL CALENDARIO ---
def render_mes_html(df_plan, mes_objetivo):
    plan_adj = {row['Fecha']: row['Adjunto'] for _, row in df_plan.iterrows()}
    plan_res = {row['Fecha']: row['Residente'] for _, row in df_plan.iterrows()}
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
                adj = plan_adj.get(f_str, "VACÍO")
                res = plan_res.get(f_str, "VACÍO")
                html += f'<td><div class="day-number">{day}</div>'
                if adj != "VACÍO": html += f'<div class="adjunto-label" style="background-color: {ADJ_COLOR_MAP.get(adj, "#444")};">{adj}</div>'
                else: html += f'<div class="vacio-label">Adj: VACÍO</div>'
                if res != "VACÍO": html += f'<div class="residente-label" style="background-color: {RES_COLOR_MAP.get(res, "#fff")};">{res} ({USER_R_MAP.get(res, "")})</div>'
                else: html += f'<div class="vacio-label">Res: VACÍO</div>'
                html += '</td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html

# --- 7. MOTOR DE RESOLUCIÓN ---
def resolver():
    model = cp_model.CpModel()
    num_dias = len(rango_fechas)
    def crear_reglas(df_staff, prefix):
        num = len(df_staff)
        v = {}
        for r in range(num):
            for d in range(num_dias): v[(r, d)] = model.NewBoolVar(f'{prefix}_r{r}d{d}')
        for d in range(num_dias):
            model.Add(sum(v[(r, d)] for r in range(num)) <= 1)
            for r in range(num):
                nom = df_staff.iloc[r]["Nombre"]
                if rango_fechas[d] in st.session_state.ausencias_globales.get(nom, set()): model.Add(v[(r, d)] == 0)
                if d < num_dias - 1: model.Add(v[(r, d)] + v[(r, d+1)] <= 1)
                if rango_fechas[d].weekday() == 3: # Jueves -> Prohibido Sábado
                    if d + 2 < num_dias: model.Add(v[(r, d+2)] == 0).OnlyEnforceIf(v[(r, d)])
                if rango_fechas[d].weekday() == 5: # Sábado -> Prohibido Jueves siguiente
                    if d + 5 < num_dias: model.Add(v[(r, d+5)] == 0).OnlyEnforceIf(v[(r, d)])
                if rango_fechas[d].weekday() == 4: # Viernes -> Domingo
                    if d + 2 < num_dias: model.Add(v[(r, d)] <= v[(r, d+2)])
        objs = []
        for mes in list(set(rango_fechas.month)):
            idx_m = [d for d in range(num_dias) if rango_fechas[d].month == mes]
            idx_f = [d for d in idx_m if rango_fechas[d].weekday() in [5, 6]]
            for r in range(num):
                tope = df_staff.iloc[r]["Tope"]
                model.Add(sum(v[(r, d)] for d in idx_m) <= tope)
                max_f = 2 if tope >= 4 else 1
                model.Add(sum(v[(r, d)] for d in idx_f) <= max_f)
                for wd in range(7):
                    idx_wd = [d for d in idx_m if rango_fechas[d].weekday() == wd]
                    model.Add(sum(v[(r, d)] for d in idx_wd) <= 2)
                    h2 = model.NewBoolVar(f'{prefix}_r{r}m{mes}w{wd}h2')
                    model.Add(sum(v[(r, d)] for d in idx_wd) <= 1 + h2)
                    objs.append(h2 * -50000)
        for d in range(num_dias):
            wd = rango_fechas[d].weekday()
            pb = 100000 if wd == 4 else (101000 if wd == 1 else (102000 if wd == 2 else 110000))
            for r in range(num): objs.append(v[(r, d)] * (pb + random.randint(1, 999)))
        return v, objs
    v_adj, o_adj = crear_reglas(df_adjuntos, "adj")
    v_res, o_res = crear_reglas(df_residentes, "res")
    model.Maximize(sum(o_adj) + sum(o_res))
    solver = cp_model.CpSolver()
    if solver.Solve(model) in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        res = []
        for d in range(num_dias):
            a_n, r_n = "VACÍO", "VACÍO"
            for r in range(len(df_adjuntos)):
                if solver.Value(v_adj[(r, d)]) == 1: a_n = df_adjuntos.iloc[r]["Nombre"]
            for r in range(len(df_residentes)):
                if solver.Value(v_res[(r, d)]) == 1: r_n = df_residentes.iloc[r]["Nombre"]
            res.append({"Fecha": rango_fechas[d].strftime('%Y-%m-%d'), "Adjunto": a_n, "Residente": r_n})
        return pd.DataFrame(res)
    return None

# --- 8. EJECUCIÓN ---
st.divider()
if st.button("🚀 Generar Planificación Final", type="primary"):
    with st.spinner("Optimizando cuadrante..."):
        df_f = resolver()
        if df_f is not None:
            def build_stats(df, col, staff_df, is_res):
                df_v = df[df[col] != "VACÍO"].copy()
                df_v["Fecha"] = pd.to_datetime(df_v["Fecha"])
                ds = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                df_v["Dia"] = df_v["Fecha"].dt.weekday.map(lambda x: ds[x])
                label = df_v[col].apply(lambda x: f"{x} ({USER_R_MAP.get(x, '')})") if is_res else df_v[col]
                orden = [f"{r['Nombre']} ({r['R']})" for _, r in staff_df.iterrows()] if is_res else staff_df["Nombre"].tolist()
                t = pd.crosstab(label, df_v["Dia"])
                for d in ds:
                    if d not in t.columns: t[d] = 0
                return t[ds].reindex(orden, fill_value=0)
            
            t_adj = build_stats(df_f, "Adjunto", df_adjuntos, False)
            t_res = build_stats(df_f, "Residente", df_residentes, True)
            v_data = [{"Nombre": r['Nombre'], "Días Vacaciones": sum(1 for d in st.session_state.ausencias_globales.get(r['Nombre'], set()) if primer_dia <= d <= ultimo_dia and d.weekday() < 5)} for _, r in pd.concat([df_adjuntos, df_residentes]).iterrows()]
            
            html = f"<html><head><meta charset='utf-8'>{estilos_css}</head><body><h1>🏥 Planificación</h1>"
            for m in range(mes_ini, mes_fin + 1): html += render_mes_html(df_f, m)
            html += "<h2>📊 Adjuntos</h2>" + t_adj.to_html(classes="summary-table") + "<h2>📊 Residentes</h2>" + t_res.to_html(classes="summary-table") + "</body></html>"
            st.session_state.plan_generado = {"df": df_f, "html": html, "t_adj": t_adj, "t_res": t_res, "t_vac": pd.DataFrame(v_data).set_index("Nombre"), "meses": range(mes_ini, mes_fin+1)}
        else: st.error("❌ Sin solución.")

if st.session_state.plan_generado:
    d = st.session_state.plan_generado
    for m in d["meses"]: st.write(render_mes_html(d["df"], m), unsafe_allow_html=True)
    st.divider()
    st.subheader("👨‍⚕️ Adjuntos")
    st.dataframe(d["t_adj"])
    st.subheader("🎓 Residentes")
    st.dataframe(d["t_res"])
    st.subheader("🏖️ Vacaciones")
    st.dataframe(d["t_vac"])
    st.download_button("🎨 Descargar HTML", d["html"], "Plan.html", "text/html", type="primary")
