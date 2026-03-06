import streamlit as st
import pandas as pd
import googlemaps
import datetime
import folium
from streamlit_folium import st_folium
import polyline
import urllib.parse

# 1. Configuración de la App
st.set_page_config(page_title="Optimización Logística", layout="wide")

# 2. Conexión Segura (Busca la API KEY en Secrets)
if "MAPS_API_KEY" not in st.secrets:
    st.error("⚠️ Error: Configura la MAPS_API_KEY en los Secrets de Streamlit.")
    st.stop()

gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])

# Definición de Flota (Capacidades y Costos)
flota = [
    {"nombre": "ISUZU 2", "capacidad": 6500, "costo": 3.42},
    {"nombre": "RAM 4000", "capacidad": 3500, "costo": 6.31},
    {"nombre": "ISUZU 1", "capacidad": 4000, "costo": 3.68},
    {"nombre": "VW CRAFTER", "capacidad": 1000, "costo": 1.76},
    {"nombre": "URVAN PANEL", "capacidad": 1350, "costo": 1.90},
    {"nombre": "CHEVROLET TORNADO", "capacidad": 650, "costo": 1.70}
]

st.title("🚚 Optimizador de Rutas Iztapalapa Pro")

# --- BARRA LATERAL: CONFIGURACIÓN ---
with st.sidebar:
    st.header("📋 Parámetros de Ruta")
    with st.form("panel_control"):
        origen = st.text_input("Base de Salida", "20 de Noviembre, Santa María Aztahuacán, Iztapalapa")
        peso = st.number_input("Carga total (kg)", min_value=1, value=500)
        f_salida = st.date_input("Fecha", datetime.date.today())
        h_salida = st.time_input("Hora Salida", datetime.time(8, 0))
        
        st.write("---")
        st.subheader("📍 Destinos")
        # Tabla inicial limpia con checkbox para prioridad
        df_base = pd.DataFrame(columns=["Destino", "¿Límite?", "Hora Límite"])
        df_editado = st.data_editor(
            df_base, 
            num_rows="dynamic", 
            hide_index=True,
            column_config={
                "¿Límite?": st.column_config.CheckboxColumn("¿Límite?", default=False),
                "Hora Límite": st.column_config.TimeColumn("Hora Límite", format="HH:mm")
            }
        )
        btn_calcular = st.form_submit_button("🚀 OPTIMIZAR RUTA")

# --- FUNCIÓN PARA LIMPIAR FORMATO DE HORA (EVITA ERROR DE MICROSEGUNDOS) ---
def limpiar_hora(dato):
    if isinstance(dato, datetime.time):
        return dato
    if isinstance(dato, str) and dato.strip() != "" and dato != "None":
        try:
            # Extrae solo HH:MM ignorando segundos o milisegundos que envíe la tabla
            partes = dato.split(":")
            return datetime.time(int(partes[0]), int(partes[1]))
        except:
            return None
    return None

# --- LÓGICA DE CÁLCULO ---
if btn_calcular:
    destinos_raw = df_editado[df_editado["Destino"].str.strip() != ""].copy()
    
    if destinos_raw.empty:
        st.warning("⚠️ Agrega al menos un destino para calcular.")
    else:
        try:
            # Ajuste de zona horaria y tiempo de salida
            tz = datetime.timezone(datetime.timedelta(hours=-6)) # Ciudad de México
            dt_inicio = datetime.datetime.combine(f_salida, h_salida).replace(tzinfo=tz)
            ahora = datetime.datetime.now(tz)
            # Evita error de Google Maps por "tiempo pasado"
            ts_envio = int(dt_inicio.timestamp()) if dt_inicio > ahora else int(ahora.timestamp())

            # PASO 1: Intentar la ruta 100% óptima (Menor distancia total)
            res = gmaps.directions(
                origen, origen,
                waypoints=destinos_raw["Destino"].tolist(),
                optimize_waypoints=True,
                departure_time=ts_envio
            )
            
            orden_indices = res[0]['waypoint_order']
            ruta_propuesta = [destinos_raw.iloc[i].to_dict() for i in orden_indices]
            legs = res[0]['legs']
            
            # PASO 2: Validar si la ruta óptima cumple las ventanas de tiempo
            incumple = False
            seg_acum = 0
            for i, p in enumerate(ruta_propuesta):
                seg_acum += legs[i].get('duration_in_traffic', legs[i]['duration'])['value']
                h_lim_p = limpiar_hora(p.get("Hora Límite"))
                
                if p["¿Límite?"] and h_lim_p:
                    llegada = (dt_inicio + datetime.timedelta(seconds=seg_acum)).time()
                    if llegada > h_lim_p:
                        incumple = True
                        break
            
            # PASO 3: Si se incumple un horario, re-ordenar priorizando los límites
            if incumple:
                st.info("🔄 Ajustando ruta: Priorizando entregas con límite de horario...")
                prio = destinos_raw[destinos_raw["¿Límite?"] == True].copy()
                norm = destinos_raw[destinos_raw["¿Límite?"] == False].copy()
                destinos_finales = pd.concat([prio, norm])
                
                res = gmaps.directions(
                    origen, origen,
                    waypoints=destinos_finales["Destino"].tolist(),
                    optimize_waypoints=False, # Mantiene el orden de prioridad
                    departure_time=ts_envio
                )
                ruta_propuesta = destinos_finales.to_dict('records')
                legs = res[0]['legs']

            # --- VISUALIZACIÓN DE RESULTADOS ---
            col1, col2 = st.columns([1, 1.2])
            
            with col1:
                st.subheader("🏁 Itinerario Detallado")
                # Selección de Vehículo
                v = min([v for v in flota if v['capacidad'] >= peso], key=lambda x: x['costo'])
                st.success(f"Unidad Sugerida: **{v['nombre']}**")
                
                # ENLACE UNIVERSAL A GOOGLE MAPS
                dest_para_url = [urllib.parse.quote(p['Destino']) for p in ruta_propuesta]
                url_gmaps = f"https://www.google.com/maps/dir/{urllib.parse.quote(origen)}/" + "/".join(dest_para_url) + f"/{urllib.parse.quote(origen)}"
                st.link_button("🗺️ ABRIR NAVEGACIÓN (GOOGLE MAPS)", url_gmaps)

                tabla_itinerario = []
                acumulado_seg = 0
                for i, p in enumerate(ruta_propuesta):
                    duracion_tramo = legs[i].get('duration_in_traffic', legs[i]['duration'])['value']
                    acumulado_seg += duracion_tramo
                    eta = dt_inicio + datetime.timedelta(seconds=acumulado_seg)
                    h_lim_p = limpiar_hora(p.get("Hora Límite"))
                    
                    status = "🟢 A TIEMPO"
                    if p["¿Límite?"] and h_lim_p and eta.time() > h_lim_p:
                        status = f"🔴 RETRASO (Límite: {h_lim_p.strftime('%H:%M')})"
                    
                    tabla_itinerario.append({
                        "Orden": i+1, 
                        "Destino": p["Destino"], 
                        "Llegada": eta.strftime("%I:%M %p"), 
                        "Estatus": status
                    })
                st.table(pd.DataFrame(tabla_itinerario))

            with col2:
                st.subheader("🗺️ Mapa Interactivo")
                # Decodificar línea de ruta
                puntos_ruta = polyline.decode(res[0]['overview_polyline']['points'])
                m = folium.Map(location=puntos_ruta[0], zoom_start=11)
                folium.PolyLine(puntos_ruta, color="#2E86C1", weight=6, opacity=0.8).add_to(m)
                
                # Marcadores en el mapa
                for i, leg in enumerate(legs[:-1]):
                    folium.Marker(
                        [leg['end_location']['lat'], leg['end_location']['lng']],
                        icon=folium.Icon(color='red' if ruta_propuesta[i]['¿Límite?'] else 'blue', icon='truck', prefix='fa'),
                        popup=f"Parada {i+1}: {ruta_propuesta[i]['Destino']}"
                    ).add_to(m)
                st_folium(m, width=600, height=500, returned_objects=[], key="mapa_final")

        except Exception as e:
            st.error(f"Error en el proceso de optimización: {e}")
