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

# --- 3. INICIALIZACIÓN DE DATOS ---
if 'ausencias_globales' not in st.session_state:
    datos_aus = cargar_coleccion("ausencias")
    st.session_state.ausencias_globales = {
        item["nombre"]: {datetime.strptime(f, '%Y-%m-%d') for f in item.get("fechas", [])} 
        for item in datos_aus if "nombre" in item
    }

if 'adjuntos_init' not in st.session_state:
    db_adj = cargar_coleccion("plantilla_adjuntos")
    st.session_state.adjuntos_init = pd.DataFrame(db_adj) if db_adj else pd.DataFrame([{"Nombre": "Adjunto 1", "Tope": 4, "Color": "#444444"}])

if 'residentes_init' not in st.session_state:
    db_res = cargar_coleccion("plantilla_residentes")
    st.session_state.residentes_init = pd.DataFrame(db_res) if db_res else pd.DataFrame([{"Nombre": "Daniela", "Tope": 6, "R": "R4", "Color": "#FFC1CC"}])

if 'plan_generado' not in st.session_state:
    st.session_state.plan_generado = None

# --- 4. ESTILOS CSS ---
estilos_css = """
<style>
    body { font-family: sans-serif; }
    .calendar-table { width: 100%; border-collapse: collapse; margin-bottom: 30px; table-layout: fixed; }
    .calendar-table th { background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; }
    .calendar-table td { height: 160px; border: 1px solid #dee2e6; vertical-align: top; padding: 8px; overflow: hidden; }
    .day-number { font-weight: bold; margin-bottom: 8px; color: #555; font-size: 1.2em; }
    .adjunto-label, .residente-label { 
        padding: 6px; border-radius: 4px; font-size: 1.05em; font-weight: bold; 
        text-align: center; margin-top: 4px; border: 1px solid rgba(0,0,0,0.2);
    }
    .vacio-label { font-size: 0.9em; color: #999; text-align: center; margin-top: 6px; font-style: italic; }
    .summary-table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 1.0em; }
    .summary-table th { background-color: #e9ecef; padding: 12px; border: 1px solid #dee2e6; text-align: center; font-weight: bold; }
    .summary-table td { padding: 10px; border: 1px solid #dee2e6; text-align: center; }
</style>
"""
st.markdown(estilos_css, unsafe_allow_html=True)

st.title("🏥 Planificador Nefrología: Equidad Proporcional")

# --- 5. SIDEBAR ---
try: conf_c = {"Color": st.column_config.ColorColumn("🎨 Color")}
except: conf_c = {}

st.sidebar.header("👨‍⚕️ 1. Plantilla Adjuntos")
df_adjuntos = st.sidebar.data_editor(st.session_state.adjuntos_init, num_rows="dynamic", key="edit_adj", column_config=conf_c)
df_adjuntos = df_adjuntos.dropna(subset=["Nombre"]).drop_duplicates(subset=["Nombre"])

st.sidebar.header("🎓 2. Plantilla Residentes")
df_residentes = st.sidebar.data_editor(st.session_state.residentes_init, num_rows="dynamic", key="edit_res", column_config=conf_c)
df_residentes = df_residentes.dropna(subset=["Nombre"]).drop_duplicates(subset=["Nombre"])

ADJ_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_adjuntos.iterrows()}
RES_COLOR_MAP = {row["Nombre"]: row["Color"] for _, row in df_residentes.iterrows()}
USER_R_MAP = {row["Nombre"]: row["R"] for _, row in df_residentes.iterrows() if "R" in row}

st.sidebar.header("📅 3. Periodo")
mes_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
col_a, col_b = st.sidebar.columns(2)
mes_ini = col_a.selectbox("Inicio", range(1, 13), index=5, format_func=lambda x: mes_nombres[x-1])
mes_fin = col_b.selectbox("Fin", range(1, 13), index=7, format_func=lambda x: mes_nombres[x-1])
anio_sel = st.sidebar.number_input("Año", value=2026)

primer_dia = datetime(anio_sel, mes_ini, 1)
ultimo_dia = datetime(anio_sel, mes_fin, calendar.monthrange(anio_sel, mes_fin)[1])
rango_fechas = pd.date_range(primer_dia, ultimo_dia)

# --- 6. AUSENCIAS ---
st.subheader("📅 Grilla de Ausencias")
def generar_grilla(nombres, key_p):
    grid_data = {d.strftime('%d/%m'): [bool(n in st.session_state.ausencias_globales and d in st.session_state.ausencias_globales[n]) for n in nombres] for d in rango_fechas}
    return st.data_editor(pd.DataFrame(grid_data, index=nombres).astype(bool), use_container_width=True, key=f"g_{key_p}", column_config={c: st.column_config.CheckboxColumn(c) for c in grid_data.keys()})

t1, t2 = st.tabs(["👨‍⚕️ Adjuntos", "🎓 Residentes"])
with t1: g_adj = generar_grilla(df_adjuntos["Nombre"].tolist(), "adj")
with t2: g_res = generar_grilla(df_residentes["Nombre"].tolist(), "res")

if st.button("☁️ Sincronizar y Guardar TODO"):
    with st.spinner("Guardando datos..."):
        for _, row in df_adjuntos.iterrows(): db.collection("plantilla_adjuntos").document(row["Nombre"]).set(row.to_dict())
        for _, row in df_residentes.iterrows(): db.collection("plantilla_residentes").document(row["Nombre"]).set(row.to_dict())
        for g, nombres in [(g_adj, df_adjuntos["Nombre"].tolist()), (g_res, df_residentes["Nombre"].tolist())]:
            for nom in nombres:
                if not nom: continue
                row_data = g.loc[nom]
                nuevas = {rango_fechas[i] for i, v in enumerate(row_data) if v}
                fuera = {d for d in st.session_state.ausencias_globales.get(nom, set()) if not (primer_dia <= d <= ultimo_dia)}
                st.session_state.ausencias_globales[nom] = nuevas.union(fuera)
                db.collection("ausencias").document(nom).set({"nombre": nom, "fechas": [d.strftime('%Y-%m-%d') for d in list(st.session_state.ausencias_globales[nom])]})
        st.success("✅ Guardado.")
        st.rerun()

# --- 7. MOTOR DE EQUIDAD PROPORCIONAL ---
def resolver():
    model = cp_model.CpModel()
    num_dias = len(rango_fechas)
    
    def aplicar_motor(staff, prefix, es_adj):
        n = len(staff)
        v = {(r, d): model.NewBoolVar(f'{prefix}_r{r}d{d}') for r in range(n) for d in range(num_dias)}
        
        # 1. Reglas básicas y ausencias
        for d in range(num_dias):
            if es_adj: model.Add(sum(v[(r, d)] for r in range(n)) == 1)
            else: model.Add(sum(v[(r, d)] for r in range(n)) <= 1)
            for r in range(n):
                nom = staff.iloc[r]["Nombre"]
                if d in st.session_state.ausencias_globales.get(nom, set()): model.Add(v[(r, d)] == 0)
                if d < num_dias - 1: model.Add(v[(r, d)] + v[(r, d+1)] <= 1)
                # Sábado-Jueves
                if rango_fechas[d].weekday() == 5 and d + 5 < num_dias: model.Add(v[(r, d+5)] == 0).OnlyEnforceIf(v[(r, d)])
                if rango_fechas[d].weekday() == 3 and d + 2 < num_dias: model.Add(v[(r, d+2)] == 0).OnlyEnforceIf(v[(r, d)])
                if not es_adj and rango_fechas[d].weekday() == 4 and d + 2 < num_dias: model.Add(v[(r, d)] <= v[(r, d+2)])

        # 2. Lógica de Equidad Basada en Disponibilidad Real
        objs = []
        dias_criticos = [0, 3, 5, 6] # L, J, S, D
        
        for wd in dias_criticos:
            total_dias_periodo = sum(1 for d in range(num_dias) if rango_fechas[d].weekday() == wd)
            
            # Calculamos disponibilidad total del grupo para ese día de la semana
            disponibilidad_total_grupo = 0
            disp_por_persona = []
            for r in range(n):
                nom = staff.iloc[r]["Nombre"]
                dias_libres = sum(1 for d in range(num_dias) if rango_fechas[d].weekday() == wd and d not in st.session_state.ausencias_globales.get(nom, set()))
                disp_por_persona.append(dias_libres)
                disponibilidad_total_grupo += dias_libres
            
            # Reparto Proporcional
            for r in range(n):
                if disponibilidad_total_grupo > 0:
                    # El objetivo es: (Mis días disponibles / Disponibilidad total) * Total de días a cubrir
                    objetivo_proporcional = (disp_por_persona[r] / disponibilidad_total_grupo) * total_dias_periodo
                    count_wd = sum(v[(r, d)] for d in range(num_dias) if rango_fechas[d].weekday() == wd)
                    
                    # Penalización por desviarse del objetivo proporcional (Soft constraint)
                    # Usamos una variable auxiliar para la diferencia absoluta
                    diff = model.NewIntVar(0, total_dias_periodo, f'diff_{prefix}_{r}_{wd}')
                    model.Add(count_wd - int(objetivo_proporcional + 0.5) <= diff)
                    model.Add(int(objetivo_proporcional + 0.5) - count_wd <= diff)
                    objs.append(diff * -100000) # Penalización alta por desbalance proporcional

        # 3. Topes mensuales (Hard constraint)
        for m in list(set(rango_fechas.month)):
            idx_m = [d for d in range(num_dias) if rango_fechas[d].month == m]
            for r in range(n):
                model.Add(sum(v[(r, d)] for d in idx_m) <= staff.iloc[r]["Tope"])

        # Variedad aleatoria
        for d in range(num_dias):
            for r in range(n): objs.append(v[(r, d)] * random.randint(1, 50))
            
        return v, objs

    v_adj, o_adj = aplicar_motor(df_adjuntos, "adj", True)
    v_res, o_res = aplicar_motor(df_residentes, "res", False)
    
    model.Maximize(sum(o_adj) + sum(o_res))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0 # Tiempo límite para buscar la mejor solución
    
    if solver.Solve(model) in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        res = []
        for d in range(num_dias):
            an = next((df_adjuntos.iloc[r]["Nombre"] for r in range(len(df_adjuntos)) if solver.Value(v_adj[(r, d)]) == 1), "VACÍO")
            rn = next((df_residentes.iloc[r]["Nombre"] for r in range(len(df_residentes)) if solver.Value(v_res[(r, d)]) == 1), "VACÍO")
            res.append({"Fecha": rango_fechas[d].strftime('%Y-%m-%d'), "Adjunto": an, "Residente": rn})
        return pd.DataFrame(res)
    return None

# --- 8. RENDER ---
def render_calendario(df, m):
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
                r = df[df["Fecha"] == f_str].iloc[0]
                html += f'<td><div class="day-number">{day}</div>'
                if r["Adjunto"] != "VACÍO":
                    c = ADJ_COLOR_MAP.get(r["Adjunto"], "#444")
                    html += f'<div class="adjunto-label" style="background-color:{c}; color:{get_contrast_color(c)};">{r["Adjunto"]}</div>'
                else: html += '<div class="vacio-label">Adj: VACÍO</div>'
                if r["Residente"] != "VACÍO":
                    c = RES_COLOR_MAP.get(r["Residente"], "#fff")
                    html += f'<div class="residente-label" style="background-color:{c}; color:{get_contrast_color(c)};">{r["Residente"]} ({USER_R_MAP.get(r["Residente"], "")})</div>'
                else: html += '<div class="vacio-label">Res: VACÍO</div>'
                html += '</td>'
        html += '</tr>'
    return html + '</tbody></table>'

st.divider()
if st.button("🚀 Generar Planificación Proporcional", type="primary"):
    df_f = resolver()
    if df_f is not None:
        def stats(df, col, staff, is_res):
            df_v = df[df[col] != "VACÍO"].copy()
            df_v["Fecha"] = pd.to_datetime(df_v["Fecha"])
            ds = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            df_v["Dia"] = df_v["Fecha"].dt.weekday.map(lambda x: ds[x])
            lbl = df_v[col].apply(lambda x: f"{x} ({USER_R_MAP.get(x, '')})") if is_res else df_v[col]
            ord_p = [f"{r['Nombre']} ({r['R']})" for _, r in staff.iterrows()] if is_res else staff["Nombre"].tolist()
            t = pd.crosstab(lbl, df_v["Dia"])
            for d in ds:
                if d not in t.columns: t[d] = 0
            t = t[ds].reindex(ord_p, fill_value=0)
            t["TOTAL"] = t.sum(axis=1)
            return t

        st.session_state.plan_generado = {
            "df": df_f, "t_adj": stats(df_f, "Adjunto", df_adjuntos, False), 
            "t_res": stats(df_f, "Residente", df_residentes, True), 
            "meses": range(mes_ini, mes_fin+1)
        }
    else: st.error("❌ No hay solución posible. Prueba a relajar ausencias o subir topes.")

if st.session_state.plan_generado:
    d = st.session_state.plan_generado
    for m in d["meses"]: st.write(render_calendario(d["df"], m), unsafe_allow_html=True)
    st.divider()
    st.subheader("👨‍⚕️ Resumen Adjuntos")
    st.dataframe(d["t_adj"].style.format(precision=0), use_container_width=True)
    st.subheader("🎓 Resumen Residentes")
    st.dataframe(d["t_res"].style.format(precision=0), use_container_width=True)
