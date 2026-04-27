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

dias_espanol = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# --- 3. INICIALIZACIÓN DE SESIÓN (ESTADO DE LA APP) ---
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

# CARGA CRÍTICA: Guardias fijas desde Firestore
if 'guardias_fijas' not in st.session_state:
    st.session_state.guardias_fijas = cargar_coleccion_dict("guardias_fijas")

if 'plan_generado' not in st.session_state:
    st.session_state.plan_generado = None

# --- 4. ESTILOS CSS ---
estilos_css = """
<style>
    body { font-family: sans-serif; }
    .calendar-table { width: 100%; border-collapse: collapse; margin-bottom: 30px; }
    .calendar-table th { background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; }
    .calendar-table td { height: 150px; width: 14%; border: 1px solid #dee2e6; vertical-align: top; padding: 6px; }
    .day-number { font-weight: bold; margin-bottom: 8px; color: #555; font-size: 1.1em; }
    .adjunto-label, .residente-label { padding: 6px; border-radius: 4px; font-size: 1.0em; font-weight: bold; text-align: center; margin-top: 4px; border: 1px solid rgba(0,0,0,0.15); }
    .vacio-label { font-size: 0.85em; color: #888; text-align: center; margin-top: 6px; font-style: italic; }
    .summary-table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 1.0em; }
</style>
"""
st.markdown(estilos_css, unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias Nefrología")

# --- 5. SIDEBAR ---
st.sidebar.header("⚙️ Configuración")
incluir_adjuntos = st.sidebar.checkbox("✅ Incluir Adjuntos", value=True)
st.sidebar.divider()

try: conf_c = {"Color": st.column_config.ColorColumn("🎨 Color")}
except: conf_c = {}

if incluir_adjuntos:
    st.sidebar.header("👨‍⚕️ 1. Plantilla Adjuntos")
    df_adjuntos = st.sidebar.data_editor(st.session_state.adjuntos_init, num_rows="dynamic", key="edit_adj", column_config=conf_c)
    if "Nombre" in df_adjuntos.columns:
        df_adjuntos = df_adjuntos.dropna(subset=["Nombre"]).drop_duplicates(subset=["Nombre"])
        ADJ_COLOR_MAP = {row["Nombre"]: row.get("Color", "#444444") for _, row in df_adjuntos.iterrows()}
    else: df_adjuntos = pd.DataFrame(columns=["Nombre", "Tope", "Color"]); ADJ_COLOR_MAP = {}
else:
    df_adjuntos = pd.DataFrame(); ADJ_COLOR_MAP = {}

st.sidebar.header("🎓 2. Plantilla Residentes")
df_residentes = st.sidebar.data_editor(st.session_state.residentes_init, num_rows="dynamic", key="edit_res", column_config=conf_c)
if "Nombre" in df_residentes.columns:
    df_residentes = df_residentes.dropna(subset=["Nombre"]).drop_duplicates(subset=["Nombre"])
    RES_COLOR_MAP = {row["Nombre"]: row.get("Color", "#FFFFFF") for _, row in df_residentes.iterrows()}
    USER_R_MAP = {row["Nombre"]: row.get("R", "") for _, row in df_residentes.iterrows()}
else: df_residentes = pd.DataFrame(columns=["Nombre", "Tope", "R", "Color"]); RES_COLOR_MAP = {}; USER_R_MAP = {}

st.sidebar.header("📅 3. Periodo")
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
col_a, col_b = st.sidebar.columns(2)
mes_ini = col_a.selectbox("Inicio", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
mes_fin = col_b.selectbox("Fin", range(1, 13), index=8, format_func=lambda x: mes_nombres[x-1])
anio_sel = st.sidebar.number_input("Año", value=2026)
rango_fechas = pd.date_range(datetime(anio_sel, mes_ini, 1), datetime(anio_sel, mes_fin, calendar.monthrange(anio_sel, mes_fin)[1]))

st.sidebar.divider()
st.sidebar.header("🚨 Peligro")
if st.sidebar.button("🗑️ Borrar TODAS las Guardias Fijas (Nube)", type="primary"):
    if db:
        docs = db.collection("guardias_fijas").stream()
        batch = db.batch()
        for doc in docs: batch.delete(doc.reference)
        batch.commit()
    st.session_state.guardias_fijas = {}
    st.rerun()

# --- 6. TABS PRINCIPALES ---
t1, t2, t3 = st.tabs(["👨‍⚕️ Ausencias Adjuntos", "🎓 Ausencias Residentes", "📝 Editor Manual (Guardias Fijas)"])

def generar_grilla(nombres, key_p):
    grid_data = {d.strftime('%d/%m'): [bool(d in st.session_state.ausencias_globales.get(n, set())) for n in nombres] for d in rango_fechas}
    df_grid = pd.DataFrame(grid_data, index=nombres).astype(bool)
    return st.data_editor(df_grid, use_container_width=True, key=f"g_{key_p}", column_config={c: st.column_config.CheckboxColumn(c) for c in grid_data.keys()})

with t1:
    g_adj = generar_grilla(df_adjuntos["Nombre"].tolist(), "adj") if incluir_adjuntos and not df_adjuntos.empty else pd.DataFrame()

with t2:
    g_res = generar_grilla(df_residentes["Nombre"].tolist(), "res") if not df_residentes.empty else pd.DataFrame()

with t3:
    st.warning("⚠️ Los cambios aquí se perderán si refrescas la página sin pulsar '💾 GUARDAR CAMBIOS MANUALES'.")
    ops_adj = ["VACÍO"] + (df_adjuntos["Nombre"].tolist() if not df_adjuntos.empty else [])
    ops_res = ["VACÍO"] + (df_residentes["Nombre"].tolist() if not df_residentes.empty else [])
    
    filas_manual = []
    for d in rango_fechas:
        f_str = d.strftime('%Y-%m-%d')
        fijo = st.session_state.guardias_fijas.get(f_str, {})
        filas_manual.append({
            "Fecha": f_str, "Día": dias_espanol[d.weekday()],
            "Adjunto": fijo.get("Adjunto", "VACÍO") if pd.notna(fijo.get("Adjunto")) else "VACÍO",
            "Residente": fijo.get("Residente", "VACÍO") if pd.notna(fijo.get("Residente")) else "VACÍO"
        })
    
    df_manual_edit = st.data_editor(
        pd.DataFrame(filas_manual), use_container_width=True, hide_index=True,
        column_config={
            "Fecha": st.column_config.TextColumn("Fecha", disabled=True),
            "Día": st.column_config.TextColumn("Día", disabled=True),
            "Adjunto": st.column_config.SelectboxColumn("Adjunto Fijo", options=ops_adj),
            "Residente": st.column_config.SelectboxColumn("Residente Fijo", options=ops_res)
        }, key="editor_manual_pers"
    )
    
    if st.button("💾 GUARDAR CAMBIOS MANUALES (En la nube)", type="primary", use_container_width=True):
        with st.spinner("Sincronizando..."):
            batch = db.batch() if db else None
            for _, row in df_manual_edit.iterrows():
                f_str, a_nom, r_nom = row["Fecha"], row["Adjunto"], row["Residente"]
                if a_nom != "VACÍO" or r_nom != "VACÍO":
                    data = {"Adjunto": a_nom, "Residente": r_nom}
                    st.session_state.guardias_fijas[f_str] = data
                    if batch: batch.set(db.collection("guardias_fijas").document(f_str), data)
                else:
                    if f_str in st.session_state.guardias_fijas:
                        del st.session_state.guardias_fijas[f_str]
                        if batch: batch.delete(db.collection("guardias_fijas").document(f_str))
            if batch: batch.commit()
        st.success("✅ ¡Guardias fijadas correctamente! Ya no se borrarán al refrescar.")
        st.rerun()

st.divider()
if st.button("☁️ Sincronizar Plantillas y Ausencias", use_container_width=True):
    with st.spinner("Guardando..."):
        if incluir_adjuntos and not df_adjuntos.empty:
            for _, row in df_adjuntos.iterrows(): db.collection("plantilla_adjuntos").document(row["Nombre"]).set(row.to_dict())
        if not df_residentes.empty:
            for _, row in df_residentes.iterrows(): db.collection("plantilla_residentes").document(row["Nombre"]).set(row.to_dict())
        
        listas_sync = []
        if not df_residentes.empty: listas_sync.append((g_res, df_residentes["Nombre"].tolist()))
        if incluir_adjuntos and not df_adjuntos.empty: listas_sync.append((g_adj, df_adjuntos["Nombre"].tolist()))
        
        for g, nombres in listas_sync:
            for nom in nombres:
                if not nom: continue
                nuevas = {rango_fechas[i] for i, v in enumerate(g.loc[nom]) if v}
                fuera = {d for d in st.session_state.ausencias_globales.get(nom, set()) if not (rango_fechas[0] <= d <= rango_fechas[-1])}
                st.session_state.ausencias_globales[nom] = nuevas.union(fuera)
                db.collection("ausencias").document(nom).set({"nombre": nom, "fechas": [d.strftime('%Y-%m-%d') for d in st.session_state.ausencias_globales[nom]]})
        st.success("✅ Ausencias sincronizadas."); st.rerun()

# --- 7. DETECTIVE Y MOTOR ---
def diagnosticar_conflictos():
    errores = []
    n_dias = len(rango_fechas)
    def obtener_disponibles(dia_idx, df_staff, is_adj, ex_nom):
        disponibles = []; d_date = rango_fechas[dia_idx]; rol_k = "Adjunto" if is_adj else "Residente"
        for _, r in df_staff.iterrows():
            nom = r["Nombre"]
            if nom == ex_nom: continue
            if d_date in st.session_state.ausencias_globales.get(nom, set()): continue
            f_a = st.session_state.guardias_fijas.get(rango_fechas[dia_idx-1].strftime('%Y-%m-%d'), {}) if dia_idx > 0 else {}
            f_d = st.session_state.guardias_fijas.get(rango_fechas[dia_idx+1].strftime('%Y-%m-%d'), {}) if dia_idx < n_dias-1 else {}
            if f_a.get(rol_k) == nom or f_d.get(rol_k) == nom: continue
            disponibles.append(nom)
        return disponibles[:3]

    for df_s, is_a, rol in [(df_adjuntos, True, "Adjunto"), (df_residentes, False, "Residente")]:
        if is_a and not incluir_adjuntos: continue
        if df_s.empty: continue
        for _, row in df_s.iterrows():
            nom = row["Nombre"]; dias_idx = []
            for d in range(n_dias):
                f_s = rango_fechas[d].strftime('%Y-%m-%d'); fijo = st.session_state.guardias_fijas.get(f_s, {})
                if fijo.get(rol) == nom:
                    dias_idx.append(d)
                    if rango_fechas[d] in st.session_state.ausencias_globales.get(nom, set()):
                        sug = obtener_disponibles(d, df_s, is_a, nom)
                        errores.append(f"**{nom}** tiene guardia fija el {f_s} pero está **AUSENTE**. 💡 Sugerencias: {', '.join(sug)}")
            for i in dias_idx:
                if i + 1 in dias_idx: errores.append(f"**{nom}** tiene guardias consecutivas fijadas: {rango_fechas[i].strftime('%d/%m')} y {rango_fechas[i+1].strftime('%d/%m')}.")
    return errores

def resolver():
    model = cp_model.CpModel(); num_dias = len(rango_fechas)
    def aplicar_reglas(staff, prefix, es_adj):
        n = len(staff); v = {(r, d): model.NewBoolVar(f'{prefix}_r{r}d{d}') for r in range(n) for d in range(num_dias)}
        if n == 0: return v, []
        for d in range(num_dias):
            f_str = rango_fechas[d].strftime('%Y-%m-%d'); fijo = st.session_state.guardias_fijas.get(f_str)
            model.Add(sum(v[(r, d)] for r in range(n)) <= 1)
            if fijo:
                val = fijo.get("Adjunto") if es_adj else fijo.get("Residente")
                if pd.notna(val) and val != "VACÍO":
                    for r in range(n): 
                        if staff.iloc[r]["Nombre"] == val: model.Add(v[(r, d)] == 1)
                elif val == "VACÍO":
                    for r in range(n): model.Add(v[(r, d)] == 0)
            for r in range(n):
                nom = staff.iloc[r]["Nombre"]
                if rango_fechas[d] in st.session_state.ausencias_globales.get(nom, set()): model.Add(v[(r, d)] == 0)
                if d < num_dias - 1: model.Add(v[(r, d)] + v[(r, d+1)] <= 1)
                if rango_fechas[d].weekday() == 5 and d+5 < num_dias: model.Add(v[(r, d+5)] == 0).OnlyEnforceIf(v[(r, d)])
                if rango_fechas[d].weekday() == 3 and d+2 < num_dias: model.Add(v[(r, d+2)] == 0).OnlyEnforceIf(v[(r, d)])
                if not es_adj and rango_fechas[d].weekday() == 4 and d+2 < num_dias: model.Add(v[(r, d)] <= v[(r, d+2)])
        objs = []
        for m in list(set(rango_fechas.month)):
            idx_m = [d for d in range(num_dias) if rango_fechas[d].month == m]
            for r in range(n):
                model.Add(sum(v[(r, d)] for d in idx_m) <= staff.iloc[r]["Tope"])
                for wd in [0, 3, 5, 6]:
                    idx_wd = [d for d in idx_m if rango_fechas[d].weekday() == wd]
                    suma_wd = sum(v[(r, d)] for d in idx_wd)
                    h2 = model.NewBoolVar(f'{prefix}_r{r}m{m}wd{wd}_h2')
                    model.Add(suma_wd <= 1 + h2); objs.append(h2 * -80000)
        for d in range(num_dias):
            for r in range(n): objs.append(v[(r, d)] * (100000 + random.randint(1, 999)))
        return v, objs

    v_adj, o_adj = (aplicar_reglas(df_adjuntos, "adj", True) if incluir_adjuntos and not df_adjuntos.empty else ({}, []))
    v_res, o_res = (aplicar_reglas(df_residentes, "res", False) if not df_residentes.empty else ({}, []))
    model.Maximize(sum(o_adj) + sum(o_res))
    solver = cp_model.CpSolver()
    if solver.Solve(model) in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        res = []
        for d in range(num_dias):
            an = next((df_adjuntos.iloc[r]["Nombre"] for r in range(len(df_adjuntos)) if solver.Value(v_adj[(r, d)]) == 1), "VACÍO") if (incluir_adjuntos and not df_adjuntos.empty) else "VACÍO"
            rn = next((df_residentes.iloc[r]["Nombre"] for r in range(len(df_residentes)) if solver.Value(v_res[(r, d)]) == 1), "VACÍO") if not df_residentes.empty else "VACÍO"
            res.append({"Fecha": rango_fechas[d].strftime('%Y-%m-%d'), "Adjunto": an, "Residente": rn})
        return pd.DataFrame(res)
    return None

# --- 8. RENDERIZADO CALENDARIO ---
def render_mes_html(df, m, modo_adj):
    cal = calendar.Calendar(firstweekday=0)
    html = f'<h3 style="color:#2c3e50; border-bottom:2px solid #eee; padding-bottom:5px;">{mes_nombres[m-1]} {anio_sel}</h3><table class="calendar-table"><thead><tr>'
    for d in ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]: html += f'<th>{d}</th>'
    html += '</tr></thead><tbody>'
    for week in cal.monthdayscalendar(anio_sel, m):
        html += '<tr>'
        for day in week:
            if day == 0: html += '<td style="background-color: #f1f1f1;"></td>'
            else:
                f_str = f"{anio_sel}-{m:02d}-{day:02d}"; rows = df[df["Fecha"] == f_str]
                if rows.empty: continue
                row = rows.iloc[0]; candado = " 🔒" if f_str in st.session_state.guardias_fijas else ""
                html += f'<td><div class="day-number">{day}</div>'
                if modo_adj:
                    if row["Adjunto"] != "VACÍO":
                        c_a = ADJ_COLOR_MAP.get(row["Adjunto"], "#444")
                        html += f'<div class="adjunto-label" style="background-color:{c_a}; color:{get_contrast_color(c_a)};">{row["Adjunto"]}{candado}</div>'
                    else: html += '<div class="vacio-label">Adj: VACÍO</div>'
                    if row["Residente"] != "VACÍO":
                        c_r = RES_COLOR_MAP.get(row["Residente"], "#fff")
                        html += f'<div class="residente-label" style="background-color:{c_r}; color:{get_contrast_color(c_r)};">{row["Residente"]} ({USER_R_MAP.get(row["Residente"], "")}){candado}</div>'
                    else: html += '<div class="vacio-label">Res: VACÍO</div>'
                else:
                    if row["Residente"] != "VACÍO":
                        c_r = RES_COLOR_MAP.get(row["Residente"], "#fff")
                        html += f'<div class="residente-label" style="background-color:{c_r}; color:{get_contrast_color(c_r)}; margin-top:25px; padding:12px; font-size:1.1em;">{row["Residente"]}{candado}</div>'
                    else: html += '<div class="vacio-label" style="margin-top: 35px;">VACÍO</div>'
                html += '</td>'
        html += '</tr>'
    return html + '</tbody></table>'

st.subheader("🚀 Generación de Resultados")
if st.button("CALCULAR PLANIFICACIÓN", type="primary", use_container_width=True):
    df_f = resolver()
    if df_f is not None:
        def build_stats(df, col, staff, es_res):
            if staff.empty: return None
            df_v = df[df[col] != "VACÍO"].copy(); df_v["Fecha"] = pd.to_datetime(df_v["Fecha"])
            ds = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            df_v["Dia"] = df_v["Fecha"].dt.weekday.map(lambda x: ds[x])
            lbl = df_v[col].apply(lambda x: f"{x} ({USER_R_MAP.get(x, '')})") if es_res else df_v[col]
            t = pd.crosstab(lbl, df_v["Dia"])
            for d in ds:
                if d not in t.columns: t[d] = 0
            t = t[ds].reindex([f"{r['Nombre']} ({r['R']})" for _, r in staff.iterrows()] if es_res else staff["Nombre"].tolist(), fill_value=0)
            t["TOTAL PERIODO"] = t.sum(axis=1); return t
        
        st.session_state.plan_generado = {
            "df": df_f, "t_adj": build_stats(df_f, "Adjunto", df_adjuntos, False) if incluir_adjuntos else None, 
            "t_res": build_stats(df_f, "Residente", df_residentes, True), "meses": range(mes_ini, mes_fin+1), "adj": incluir_adjuntos
        }
    else: 
        confs = diagnosticar_conflictos()
        if confs:
            st.error("❌ Contradicciones detectadas:")
            for e in confs: st.warning(e)
        else: st.error("❌ Conflicto complejo. Revisa los topes.")

if st.session_state.plan_generado:
    d = st.session_state.plan_generado
    for m in d["meses"]: st.write(render_mes_html(d["df"], m, d["adj"]), unsafe_allow_html=True)
    st.divider()
    if d["adj"] and d["t_adj"] is not None:
        st.subheader("👨‍⚕️ Resumen Adjuntos"); st.dataframe(d["t_adj"].style.format(precision=0), use_container_width=True)
    st.subheader("🎓 Resumen Residentes"); st.dataframe(d["t_res"].style.format(precision=0), use_container_width=True)
