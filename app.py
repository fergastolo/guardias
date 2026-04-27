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
    .summary-table th { background-color: #e9ecef; padding: 12px; border: 1px solid #dee2e6; text-align: center; font-weight: bold; }
    .summary-table td { padding: 10px; border: 1px solid #dee2e6; text-align: center; }
</style>
"""
st.markdown(estilos_css, unsafe_allow_html=True)

st.title("🏥 Planificador de Guardias")

# --- 5. SIDEBAR ---
st.sidebar.header("⚙️ Configuración")
incluir_adjuntos = st.sidebar.checkbox("✅ Incluir Adjuntos en la planificación", value=True)
forzar_manuales = st.sidebar.checkbox("⚠️ Permitir que manuales rompan reglas", value=False)
st.sidebar.divider()

try: conf_c = {"Color": st.column_config.ColorColumn("🎨 Color")}
except: conf_c = {}

st.sidebar.header("👨‍⚕️ Plantillas")
if incluir_adjuntos:
    df_adjuntos = st.sidebar.data_editor(st.session_state.adjuntos_init, num_rows="dynamic", key="edit_adj", column_config=conf_c)
    if "Nombre" in df_adjuntos.columns:
        df_adjuntos = df_adjuntos.dropna(subset=["Nombre"]).drop_duplicates(subset=["Nombre"])
        ADJ_COLOR_MAP = {row["Nombre"]: row.get("Color", "#444444") for _, row in df_adjuntos.iterrows()}
    else:
        df_adjuntos = pd.DataFrame(columns=["Nombre", "Tope", "Color"]); ADJ_COLOR_MAP = {}
else:
    df_adjuntos = pd.DataFrame(); ADJ_COLOR_MAP = {}

df_residentes = st.sidebar.data_editor(st.session_state.residentes_init, num_rows="dynamic", key="edit_res", column_config=conf_c)
if "Nombre" in df_residentes.columns:
    df_residentes = df_residentes.dropna(subset=["Nombre"]).drop_duplicates(subset=["Nombre"])
    RES_COLOR_MAP = {row["Nombre"]: row.get("Color", "#FFFFFF") for _, row in df_residentes.iterrows()}
    USER_R_MAP = {row["Nombre"]: row.get("R", "") for _, row in df_residentes.iterrows()}
else:
    df_residentes = pd.DataFrame(columns=["Nombre", "Tope", "R", "Color"]); RES_COLOR_MAP = {}; USER_R_MAP = {}

st.sidebar.header("📅 Periodo")
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
col_a, col_b = st.sidebar.columns(2)
mes_ini = col_a.selectbox("Inicio", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
mes_fin = col_b.selectbox("Fin", range(1, 13), index=8, format_func=lambda x: mes_nombres[x-1])
anio_sel = st.sidebar.number_input("Año", value=2026)
rango_fechas = pd.date_range(datetime(anio_sel, mes_ini, 1), datetime(anio_sel, mes_fin, calendar.monthrange(anio_sel, mes_fin)[1]))

st.sidebar.divider()
with st.sidebar.expander("🚨 Zona de Peligro"):
    if st.button("🗑️ Borrar TODAS las Guardias Fijas", type="primary"):
        with st.spinner("Borrando historial..."):
            if db:
                docs = db.collection("guardias_fijas").stream()
                for doc in docs: doc.reference.delete()
            st.session_state.guardias_fijas = {}
        st.success("✅ Base de datos limpia."); st.rerun()

# --- 6. AUSENCIAS Y EDITOR MANUAL ---
st.subheader("📅 Grilla de Ausencias y Editor Manual")
def generar_grilla(nombres, key_p):
    grid_data = {d.strftime('%d/%m'): [bool(d in st.session_state.ausencias_globales.get(n, set())) for n in nombres] for d in rango_fechas}
    df_grid = pd.DataFrame(grid_data, index=nombres).astype(bool)
    return st.data_editor(df_grid, use_container_width=True, key=f"g_{key_p}", column_config={c: st.column_config.CheckboxColumn(c) for c in grid_data.keys()})

t1, t2, t3 = st.tabs(["👨‍⚕️ Ausencias Adjuntos", "🎓 Ausencias Residentes", "📝 Editor Manual de Guardias Fijas"])

with t1:
    if incluir_adjuntos: g_adj = generar_grilla(df_adjuntos["Nombre"].tolist(), "adj") if not df_adjuntos.empty else pd.DataFrame()
    else: g_adj = pd.DataFrame()

with t2:
    g_res = generar_grilla(df_residentes["Nombre"].tolist(), "res") if not df_residentes.empty else pd.DataFrame()

with t3:
    st.info("💡 Haz clic fuera de la celda tras editar y luego pulsa Guardar.")
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
            "Día": st.column_config.TextColumn("Día de la semana", disabled=True),
            "Adjunto": st.column_config.SelectboxColumn("Adjunto Fijo", options=ops_adj),
            "Residente": st.column_config.SelectboxColumn("Residente Fijo", options=ops_res)
        }, key="editor_manual_final_fuerza_bruta"
    )

st.markdown("<br>", unsafe_allow_html=True)
if st.button("☁️ SINCRONIZAR Y GUARDAR TODO (Ausencias y Manuales)", type="primary", use_container_width=True):
    exitos = 0
    with st.spinner("Guardando en la nube..."):
        try:
            batch = db.batch() if db else None
            if incluir_adjuntos and not df_adjuntos.empty:
                for _, row in df_adjuntos.iterrows(): 
                    if batch: batch.set(db.collection("plantilla_adjuntos").document(row["Nombre"]), {k: ("" if pd.isna(v) else v) for k, v in row.items()})
            if not df_residentes.empty:
                for _, row in df_residentes.iterrows(): 
                    if batch: batch.set(db.collection("plantilla_residentes").document(row["Nombre"]), {k: ("" if pd.isna(v) else v) for k, v in row.items()})
            
            listas_sync = []
            if not df_residentes.empty: listas_sync.append((g_res, df_residentes["Nombre"].tolist()))
            if incluir_adjuntos and not df_adjuntos.empty: listas_sync.append((g_adj, df_adjuntos["Nombre"].tolist()))
            for g, nombres in listas_sync:
                for nom in nombres:
                    if not nom: continue
                    nuevas = {rango_fechas[i] for i, v in enumerate(g.loc[nom]) if v}
                    fuera = {d for d in st.session_state.ausencias_globales.get(nom, set()) if not (rango_fechas[0] <= d <= rango_fechas[-1])}
                    final = nuevas.union(fuera)
                    st.session_state.ausencias_globales[nom] = final
                    if batch: batch.set(db.collection("ausencias").document(nom), {"nombre": nom, "fechas": [d.strftime('%Y-%m-%d') for d in final]})
            
            for _, row in df_manual_edit.iterrows():
                f_str = row["Fecha"]
                a_nom = limpiar_nulos(row["Adjunto"])
                r_nom = limpiar_nulos(row["Residente"])
                if a_nom != "VACÍO" or r_nom != "VACÍO":
                    data = {"Adjunto": a_nom, "Residente": r_nom}
                    st.session_state.guardias_fijas[f_str] = data
                    if batch: batch.set(db.collection("guardias_fijas").document(f_str), data)
                    exitos += 1
                else:
                    if f_str in st.session_state.guardias_fijas:
                        del st.session_state.guardias_fijas[f_str]
                    if batch: batch.delete(db.collection("guardias_fijas").document(f_str))
            if batch: batch.commit()
            st.success(f"✅ ¡Guardado completado! {exitos} guardias fijadas."); st.rerun()
        except Exception as e: st.error(f"❌ Error al enviar a Firebase: {e}")

# --- FUNCIÓN DETECTIVE DE CONFLICTOS ---
def diagnosticar_conflictos():
    errores = []
    n_dias = len(rango_fechas)
    def obtener_disponibles(dia_idx, df_staff, is_adj, exclude_nom):
        disponibles = []; d_date = rango_fechas[dia_idx]; rol_k = "Adjunto" if is_adj else "Residente"
        for _, r in df_staff.iterrows():
            nom = r["Nombre"]
            if nom == exclude_nom: continue
            if d_date in st.session_state.ausencias_globales.get(nom, set()): continue
            f_antes = st.session_state.guardias_fijas.get(rango_fechas[dia_idx-1].strftime('%Y-%m-%d'), {}) if dia_idx > 0 else {}
            f_despues = st.session_state.guardias_fijas.get(rango_fechas[dia_idx+1].strftime('%Y-%m-%d'), {}) if dia_idx < n_dias-1 else {}
            if f_antes.get(rol_k) == nom or f_despues.get(rol_k) == nom: continue
            wd = d_date.weekday()
            if wd == 3: 
                if dia_idx+2 < n_dias and st.session_state.guardias_fijas.get(rango_fechas[dia_idx+2].strftime('%Y-%m-%d'), {}).get(rol_k) == nom: continue
                if dia_idx-5 >= 0 and st.session_state.guardias_fijas.get(rango_fechas[dia_idx-5].strftime('%Y-%m-%d'), {}).get(rol_k) == nom: continue
            if wd == 5: 
                if dia_idx-2 >= 0 and st.session_state.guardias_fijas.get(rango_fechas[dia_idx-2].strftime('%Y-%m-%d'), {}).get(rol_k) == nom: continue
                if dia_idx+5 < n_dias and st.session_state.guardias_fijas.get(rango_fechas[dia_idx+5].strftime('%Y-%m-%d'), {}).get(rol_k) == nom: continue
            if not is_adj:
                if wd == 4 and dia_idx+2 < n_dias: 
                    dom_fijo = st.session_state.guardias_fijas.get(rango_fechas[dia_idx+2].strftime('%Y-%m-%d'), {}).get(rol_k)
                    if dom_fijo and dom_fijo != "VACÍO" and dom_fijo != nom: continue
                if wd == 6 and dia_idx-2 >= 0: 
                    vie_fijo = st.session_state.guardias_fijas.get(rango_fechas[dia_idx-2].strftime('%Y-%m-%d'), {}).get(rol_k)
                    if vie_fijo and vie_fijo != "VACÍO" and vie_fijo != nom: continue
            mes_actual = d_date.month
            guardias_este_mes = sum(1 for d in range(n_dias) if rango_fechas[d].month == mes_actual and st.session_state.guardias_fijas.get(rango_fechas[d].strftime('%Y-%m-%d'), {}).get(rol_k) == nom)
            if guardias_este_mes >= r["Tope"]: disponibles.append(f"{nom} (⚠️ Excede tope)") 
            else: disponibles.append(nom)
        return disponibles[:4]

    for df_staff, is_adj, rol in [(df_adjuntos, True, "Adjunto"), (df_residentes, False, "Residente")]:
        if is_adj and not incluir_adjuntos: continue
        if df_staff.empty: continue
        for _, row in df_staff.iterrows():
            nom = row["Nombre"]; dias_idx = []
            for d in range(n_dias):
                f_str = rango_fechas[d].strftime('%Y-%m-%d'); fijo = st.session_state.guardias_fijas.get(f_str, {})
                if fijo.get(rol) == nom:
                    dias_idx.append(d)
                    if rango_fechas[d] in st.session_state.ausencias_globales.get(nom, set()):
                        sug = obtener_disponibles(d, df_staff, is_adj, nom)
                        errores.append(f"**{nom}** tiene guardia fija el {f_str} pero está **AUSENTE**.\n* 💡 Sustitutos: {', '.join(sug) if sug else 'Nadie'}.")
            for i in dias_idx:
                if i + 1 in dias_idx:
                    sug1 = obtener_disponibles(i, df_staff, is_adj, nom); sug2 = obtener_disponibles(i+1, df_staff, is_adj, nom)
                    errores.append(f"**{nom}** tiene fijado {rango_fechas[i].strftime('%d/%m')} y {rango_fechas[i+1].strftime('%d/%m')} (Consecutivos).")
                wd = rango_fechas[i].weekday()
                if wd == 5 and i + 5 in dias_idx:
                    sug_sab = obtener_disponibles(i, df_staff, is_adj, nom)
                    errores.append(f"**{nom}** fijado Sáb {rango_fechas[i].strftime('%d/%m')} y Jue {rango_fechas[i+5].strftime('%d/%m')} (Descanso roto).")
                if wd == 3 and i + 2 in dias_idx:
                    sug_jue = obtener_disponibles(i, df_staff, is_adj, nom)
                    errores.append(f"**{nom}** fijado Jue {rango_fechas[i].strftime('%d/%m')} y Sáb {rango_fechas[i+2].strftime('%d/%m')} (Descanso roto).")
                if not is_adj and wd == 4 and i + 2 < n_dias:
                    f2_str = rango_fechas[i+2].strftime('%Y-%m-%d'); fijo_dom = st.session_state.guardias_fijas.get(f2_str, {}).get(rol)
                    if fijo_dom and fijo_dom != "VACÍO" and fijo_dom != nom:
                        errores.append(f"**{nom}** hace Viernes {rango_fechas[i].strftime('%d/%m')}, pero asignaste Domingo a **{fijo_dom}**.")
    return list(set(errores))

# --- 8. MOTOR DE RESOLUCIÓN CON "MODO DIOS" ---
def resolver():
    model = cp_model.CpModel(); n_dias = len(rango_fechas)
    def aplicar(staff, prefix, es_adj):
        n = len(staff); v = {(r, d): model.NewBoolVar(f'{prefix}_r{r}d{d}') for r in range(n) for d in range(n_dias)}
        if n == 0: return v, []
        rol_k = "Adjunto" if es_adj else "Residente"
        for d in range(n_dias):
            f_str = rango_fechas[d].strftime('%Y-%m-%d'); fijo = st.session_state.guardias_fijas.get(f_str)
            model.Add(sum(v[(r, d)] for r in range(n)) <= 1)
            if fijo:
                val = fijo.get(rol_k)
                if pd.notna(val) and val != "VACÍO":
                    for r in range(n): 
                        if staff.iloc[r]["Nombre"] == val: model.Add(v[(r, d)] == 1)
            for r in range(n):
                nom = staff.iloc[r]["Nombre"]; fijo_d = (fijo.get(rol_k) == nom) if fijo else False
                if rango_fechas[d] in st.session_state.ausencias_globales.get(nom, set()): 
                    if not (forzar_manuales and fijo_d): model.Add(v[(r, d)] == 0)
                if d < n_dias - 1:
                    fijo_d1 = st.session_state.guardias_fijas.get(rango_fechas[d+1].strftime('%Y-%m-%d'), {}).get(rol_k) == nom
                    if not (forzar_manuales and fijo_d and fijo_d1): model.Add(v[(r, d)] + v[(r, d+1)] <= 1)
                if rango_fechas[d].weekday() == 5 and d+5 < n_dias:
                    fijo_jue = st.session_state.guardias_fijas.get(rango_fechas[d+5].strftime('%Y-%m-%d'), {}).get(rol_k) == nom
                    if not (forzar_manuales and fijo_d and fijo_jue): model.Add(v[(r, d+5)] == 0).OnlyEnforceIf(v[(r, d)])
                if rango_fechas[d].weekday() == 3 and d+2 < n_dias:
                    fijo_sab = st.session_state.guardias_fijas.get(rango_fechas[d+2].strftime('%Y-%m-%d'), {}).get(rol_k) == nom
                    if not (forzar_manuales and fijo_d and fijo_sab): model.Add(v[(r, d+2)] == 0).OnlyEnforceIf(v[(r, d)])
                if not es_adj and rango_fechas[d].weekday() == 4 and d+2 < n_dias:
                    fijo_dom_val = st.session_state.guardias_fijas.get(rango_fechas[d+2].strftime('%Y-%m-%d'), {}).get(rol_k)
                    fijo_vie_val = st.session_state.guardias_fijas.get(rango_fechas[d].strftime('%Y-%m-%d'), {}).get(rol_k)
                    rompe_finde = False
                    if forzar_manuales:
                        if fijo_vie_val == nom and fijo_dom_val and fijo_dom_val != "VACÍO" and fijo_dom_val != nom: rompe_finde = True
                        if fijo_dom_val == nom and fijo_vie_val and fijo_vie_val != "VACÍO" and fijo_vie_val != nom: rompe_finde = True
                    if not rompe_finde: model.Add(v[(r, d)] <= v[(r, d+2)])
        objs = []
        for m in list(set(rango_fechas.month)):
            idx_m = [d for d in range(n_dias) if rango_fechas[d].month == m]
            for r in range(n):
                nom = staff.iloc[r]["Nombre"]; tope_real = staff.iloc[r]["Tope"]
                if forzar_manuales:
                    fijos_mes = sum(1 for d_idx in idx_m if st.session_state.guardias_fijas.get(rango_fechas[d_idx].strftime('%Y-%m-%d'), {}).get(rol_k) == nom)
                    tope_real = max(tope_real, fijos_mes)
                model.Add(sum(v[(r, d)] for d in idx_m) <= tope_real)
                for wd in [0, 3, 5, 6]:
                    idx_wd = [d for d in idx_m if rango_fechas[d].weekday() == wd]
                    suma_wd = sum(v[(r, d)] for d in idx_wd)
                    h2 = model.NewBoolVar(f'{prefix}_r{r}m{m}wd{wd}_h2')
                    model.Add(suma_wd <= 1 + h2); objs.append(h2 * -80000)
        for d in range(n_dias):
            for r in range(n): objs.append(v[(r, d)] * (100000 + random.randint(1, 999)))
        return v, objs

    v_adj, o_adj = aplicar(df_adjuntos, "adj", True) if incluir_adjuntos else ({}, [])
    v_res, o_res = aplicar(df_residentes, "res", False) if not df_residentes.empty else ({}, [])
    model.Maximize(sum(o_adj) + sum(o_res))
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
                f_str = f"{anio_sel}-{m:02d}-{day:02d}"; rows = df[df["Fecha"] == f_str]
                if rows.empty: continue
                row = rows.iloc[0]; candado = " 🔒" if f_str in st.session_state.guardias_fijas else ""
                html += f"<td><b>{day}</b>"
                if modo_adj:
                    if row["Adjunto"] != "VACÍO": 
                        c = ADJ_COLOR_MAP.get(row["Adjunto"], "#444")
                        html += f"<div class='adjunto-label' style='background:{c}; color:{get_contrast_color(c)}'>{row['Adjunto']}{candado}</div>"
                    else: html += "<div class='vacio-label'>Adj: VACÍO</div>"
                    if row["Residente"] != "VACÍO":
                        c = RES_COLOR_MAP.get(row["Residente"], "#fff")
                        html += f"<div class='residente-label' style='background:{c}; color:{get_contrast_color(c)}'>{row['Residente']} ({USER_R_MAP.get(row['Residente'], '')}){candado}</div>"
                    else: html += "<div class='vacio-label'>Res: VACÍO</div>"
                else:
                    if row["Residente"] != "VACÍO":
                        c = RES_COLOR_MAP.get(row["Residente"], "#fff")
                        html += f"<div class='residente-label' style='background:{c}; color:{get_contrast_color(c)}; margin-top:25px; padding:12px; font-size:1.1em;'>{row['Residente']}{candado}</div>"
                    else: html += "<div class='vacio-label' style='margin-top:35px'>VACÍO</div>"
                html += "</td>"
        html += "</tr>"
    return html + "</table>"

st.subheader("🚀 Generación de Resultados")
if st.button("CALCULAR PLANIFICACIÓN", type="primary", use_container_width=True):
    df_f = resolver()
    if df_f is not None:
        def build_stats(df, col, staff, es_res):
            if staff.empty: return None
            df_v = df[df[col] != "VACÍO"].copy()
            if df_v.empty: return pd.DataFrame()
            df_v["Fecha"] = pd.to_datetime(df_v["Fecha"]); ds = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            df_v["Dia"] = df_v["Fecha"].dt.weekday.map(lambda x: ds[x])
            lbl = df_v[col].apply(lambda x: f"{x} ({USER_R_MAP.get(x, '')})") if es_res else df_v[col]
            t = pd.crosstab(lbl, df_v["Dia"])
            for d in ds:
                if d not in t.columns: t[d] = 0
            t = t[ds].reindex([f"{r['Nombre']} ({r['R']})" for _, r in staff.iterrows()] if es_res else staff["Nombre"].tolist(), fill_value=0)
            t["TOTAL PERIODO"] = t.sum(axis=1) # AQUI ESTA LA LINEA RECUPERADA
            return t
        
        def build_theoretical(staff, es_res):
            if staff.empty: return None
            ds = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            rows_list = []
            for _, r in staff.iterrows():
                nom = r["Nombre"]; row_d = {"Nombre": f"{nom} ({r['R']})" if es_res else nom}
                for d in ds: row_d[d] = 0
                for d_date in rango_fechas:
                    if d_date not in st.session_state.ausencias_globales.get(nom, set()):
                        row_d[ds[d_date.weekday()]] += 1
                row_d["TOTAL DISPONIBLE"] = sum(row_d[d] for d in ds); rows_list.append(row_d)
            return pd.DataFrame(rows_list).set_index("Nombre")

        st.session_state.plan_generado = {
            "df": df_f, "t_adj": build_stats(df_f, "Adjunto", df_adjuntos, False) if incluir_adjuntos else None,
            "t_res": build_stats(df_f, "Residente", df_residentes, True), "meses": range(mes_ini, mes_fin+1), "adj": incluir_adjuntos,
            "th_res": build_theoretical(df_residentes, True), "th_adj": build_theoretical(df_adjuntos, False) if incluir_adjuntos else None
        }
    else: 
        confs = diagnosticar_conflictos()
        if confs:
            st.error("❌ Conflicto detectado:"); [st.warning(e) for e in confs]
        else: st.error("❌ Conflicto complejo.")

if st.session_state.plan_generado:
    d = st.session_state.plan_generado
    full_html = f"<html><head><meta charset='utf-8'>{estilos_css}</head><body><h1>Planificación</h1>"
    for m in d["meses"]:
        m_html = render_mes_html(d["df"], m, d["adj"]); st.write(m_html, unsafe_allow_html=True); full_html += m_html
        if st.button(f"🔒 Fijar y Bloquear {mes_nombres[m-1]}", key=f"lk_{m}", use_container_width=True):
            df_m = d["df"][pd.to_datetime(d["df"]["Fecha"]).dt.month == m]
            for _, r in df_m.iterrows():
                f_s = r["Fecha"]; dat = {"Adjunto": r["Adjunto"], "Residente": r["Residente"]}
                st.session_state.guardias_fijas[f_s] = dat
                if db: db.collection("guardias_fijas").document(f_s).set(dat)
            st.success(f"✅ {mes_nombres[m-1]} bloqueado."); st.rerun()

    st.divider()
    if d["adj"] and d["t_adj"] is not None:
        st.subheader("👨‍⚕️ Resumen Adjuntos"); st.dataframe(d["t_adj"]); full_html += "<h2>Adjuntos</h2>" + d["t_adj"].to_html(classes="summary-table")
    st.subheader("🎓 Resumen Residentes"); st.dataframe(d["t_res"]); full_html += "<h2>Residentes</h2>" + d["t_res"].to_html(classes="summary-table")
    
    st.subheader("📊 Disponibilidad Teórica (Máximo posible según ausencias)"); st.dataframe(d["th_res"])
    full_html += "<h2>📊 Disponibilidad Teórica (Residentes)</h2>" + d["th_res"].to_html(classes="summary-table")
    if d["adj"] and d["th_adj"] is not None:
        full_html += "<h2>📊 Disponibilidad Teórica (Adjuntos)</h2>" + d["th_adj"].to_html(classes="summary-table")

    st.download_button("📄 Descargar HTML", full_html + "</body></html>", "plan.html", "text/html", type="primary", use_container_width=True)
