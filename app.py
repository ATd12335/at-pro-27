import streamlit as st
import folium
from streamlit_folium import st_folium
import json
import csv
import math
from pyproj import Transformer
from io import StringIO, BytesIO
from fpdf import FPDF

# ==========================================
# CONFIGURATION DE LA PAGE
# ==========================================
st.set_page_config(page_title="AT PRO 27 - Web", page_icon="🌍", layout="wide")

# ==========================================
# AUTHENTIFICATION
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; color: #003366;'>AT PRO 27 - Mobile & Web</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Système d'Information Géographique Foncier</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        pwd = st.text_input("🔑 Entrez le mot de passe", type="password")
        if st.button("DÉVERROUILLER", use_container_width=True):
            if pwd == "209287":
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Accès Refusé. Mot de passe incorrect.")
        st.markdown("<p style='text-align: center; color: gray; font-size: 12px; margin-top: 50px;'>© 2026 TANTAWI ADIL - Propriété Intellectuelle</p>", unsafe_allow_html=True)
    st.stop()

# ==========================================
# FONCTIONS SIG MATHÉMATIQUES
# ==========================================
def nettoyer_tf(tf_str):
    tf_str = tf_str.strip().strip('"').upper()
    if '/' in tf_str:
        parts = tf_str.split('/')
        base = parts[0].lstrip('0')
        if not base: base = '0'
        return f"{base}/{parts[1].strip()}"
    return tf_str.lstrip('0') if tf_str.lstrip('0') else '0'

def safe_txt(t):
    if not isinstance(t, str):
        t = str(t)
    t = t.replace('é','e').replace('è','e').replace('à','a').replace('²','2')
    return t.encode('latin-1', errors='replace').decode('latin-1')

transformer_inv = Transformer.from_crs("EPSG:4326", "EPSG:26191", always_xy=True)
transformer_fwd = Transformer.from_crs("EPSG:26191", "EPSG:4326", always_xy=True)

# ==========================================
# INITIALISATION DES VARIABLES DE SESSION
# ==========================================
if "donnees_tf" not in st.session_state:
    st.session_state.donnees_tf = {}
if "recherche_actuelle" not in st.session_state:
    st.session_state.recherche_actuelle = None

# ==========================================
# PARSER MIF / MID (Adapté pour le Web)
# ==========================================
def parser_fichiers(mif_file, mid_file):
    geometries = []
    columns_info = []
    data_start = 0
    in_columns = False
    
    # Lecture MIF
    mif_lines = mif_file.getvalue().decode('windows-1252', errors='ignore').splitlines()
    for i, ligne in enumerate(mif_lines):
        ligne_lower = ligne.strip().lower()
        if ligne_lower == "data":
            data_start = i + 1
            in_columns = False
            break
        if ligne_lower.startswith("columns"):
            in_columns = True
            continue
        if in_columns:
            parts = ligne.strip().split()
            if len(parts) >= 1:
                columns_info.append(parts[0].upper())

    idx_tf, idx_t_min, idx_indice, idx_surf_adop, idx_surf_calc = -1, -1, -1, -1, -1
    for idx, col in enumerate(columns_info):
        if col in ["TF", "TITRE", "TITRE_FONCIER"]: idx_tf = idx
        elif col == "T_MIN": idx_t_min = idx
        elif col == "INDICE": idx_indice = idx
        elif col in ["SURF_ADOP", "SURFACE_ADOPTEE", "S_ADOP", "SUPERFICIE"]: idx_surf_adop = idx
        elif col in ["SURF_CALC", "SURFACE_CALCULEE", "S_CALC"]: idx_surf_calc = idx

    if idx_tf == -1 and len(columns_info) > 15: idx_tf = 15
    if idx_t_min == -1 and len(columns_info) > 9: idx_t_min = 9
    if idx_indice == -1 and len(columns_info) > 2: idx_indice = 2
    if idx_surf_adop == -1 and len(columns_info) > 7: idx_surf_adop = 7
    if idx_surf_calc == -1 and len(columns_info) > 6: idx_surf_calc = 6

    in_feature = False
    current_coords = []
    mots_cles = ("region", "point", "line", "pline", "arc", "text", "ellipse", "rect", "roundrect", "none", "multipoint", "collection")
    
    for i, ligne in enumerate(mif_lines[data_start:]):
        ligne = ligne.strip()
        if not ligne: continue
        if ligne.lower().startswith(mots_cles):
            if in_feature: geometries.append(current_coords)
            in_feature = True
            current_coords = []
            continue
        if in_feature:
            parts = ligne.split()
            if len(parts) == 2: 
                try: current_coords.append((float(parts[0]), float(parts[1])))
                except ValueError: pass
    if in_feature: geometries.append(current_coords)

    # Lecture MID
    donnees_tf = {}
    mid_content = mid_file.getvalue().decode('windows-1252', errors='ignore')
    reader = csv.reader(StringIO(mid_content), delimiter=",")
    
    def parse_surface(val):
        if not val: return 0.0
        clean_val = val.replace(' ', '').replace('"', '').replace(',', '.')
        try: return float(clean_val)
        except ValueError: return 0.0

    for i, row in enumerate(reader):
        if i < len(geometries):
            tfs_potentiels = set()
            if idx_tf != -1 and len(row) > idx_tf:
                val_tf = row[idx_tf].strip().strip('"')
                if val_tf and val_tf not in ["0", ""]:
                    tfs_potentiels.add(nettoyer_tf(val_tf))
            t_min = ""
            indice = ""
            if idx_t_min != -1 and len(row) > idx_t_min: t_min = nettoyer_tf(row[idx_t_min])
            if idx_indice != -1 and len(row) > idx_indice: indice = nettoyer_tf(row[idx_indice])
            if t_min and t_min != "0":
                tf_compose = f"{t_min}/{indice}" if indice else t_min
                tfs_potentiels.add(nettoyer_tf(tf_compose))
            
            s_adop = parse_surface(row[idx_surf_adop]) if idx_surf_adop != -1 and len(row) > idx_surf_adop else 0.0
            s_calc = parse_surface(row[idx_surf_calc]) if idx_surf_calc != -1 and len(row) > idx_surf_calc else 0.0
            surf_num = s_adop if s_adop > 0 else s_calc
            surf_texte = "{:,.2f}".format(surf_num).replace(',', ' ') if surf_num > 0 else "Non précisée"
            
            for tf_name in tfs_potentiels:
                if tf_name and tf_name != "0":
                    if tf_name not in donnees_tf:
                        donnees_tf[tf_name] = {'polygones': [], 'surfaces_list': []}
                    if geometries[i]:
                        donnees_tf[tf_name]['polygones'].append(geometries[i])
                        donnees_tf[tf_name]['surfaces_list'].append(surf_texte)
                        
    return donnees_tf

# ==========================================
# EXPORT PDF ET KML
# ==========================================
def generer_pdf(tf_nom, data):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 18)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(190, 15, txt="RAPPORT TOPOGRAPHIQUE DE PARCELLE", ln=True, align='C')
    pdf.line(10, 25, 200, 25)
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(190, 10, txt=f"Numero du Titre Foncier : {tf_nom}", ln=True)
    
    surfaces_list = data.get('surfaces_list', [])
    pdf.set_font("Arial", '', 14)
    if len(surfaces_list) > 1:
        for i, s in enumerate(surfaces_list):
            pdf.cell(190, 10, txt=f"Superficie {i+1} enregistree : {safe_txt(s)} m2", ln=True)
    else:
        surf_val = surfaces_list[0] if surfaces_list else 'Non precisee'
        pdf.cell(190, 10, txt=f"Superficie enregistree : {safe_txt(surf_val)} m2", ln=True)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'I', 11)
    pdf.cell(190, 10, txt="(Version Mobile/Web - L'extrait cartographique n'est pas inclus)", ln=True)

    pdf.set_y(-30)
    pdf.set_font("Arial", 'I', 10)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(0, 10, txt="Document genere par AT PRO 27 Web - Propriete Intellectuelle : TANTAWI ADIL", align='C', ln=True)
    
    return pdf.output(dest='S').encode('latin1')

def generer_kml(tf_nom, data):
    kml = '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n'
    kml += f'<name>Titre Foncier {tf_nom}</name>\n<Style id="parcelle">\n  <LineStyle><color>ff00ffff</color><width>3</width></LineStyle>\n  <PolyStyle><color>00ffffff</color></PolyStyle>\n</Style>\n'
    
    polygones = data.get('polygones', [])
    surfaces = data.get('surfaces_list', [])
    
    for index, poly in enumerate(polygones):
        if not poly: continue
        surf = surfaces[index] if index < len(surfaces) else 'Non precisee'
        suffix = f" (Partie {index+1})" if len(polygones) > 1 else ""
        
        kml += f'<Placemark>\n  <name>TF {tf_nom}{suffix} - {surf} m²</name>\n'
        kml += '  <ExtendedData>\n'
        kml += f'    <Data name="Titre Foncier"><value>{tf_nom}{suffix}</value></Data>\n'
        kml += f'    <Data name="Superficie"><value>{surf} m²</value></Data>\n'
        kml += '  </ExtendedData>\n'
        kml += '  <styleUrl>#parcelle</styleUrl>\n'
        kml += '  <Polygon><outerBoundaryIs><LinearRing><coordinates>\n'
        for x, y in poly:
            lon, lat = transformer_fwd.transform(x, y)
            kml += f'      {lon},{lat},0\n'
        lon_f, lat_f = transformer_fwd.transform(poly[0][0], poly[0][1])
        kml += f'      {lon_f},{lat_f},0\n  </coordinates></LinearRing></outerBoundaryIs></Polygon>\n</Placemark>\n'
        
    kml += '</Document>\n</kml>'
    return kml.encode('utf-8')

# ==========================================
# INTERFACE UTILISATEUR (UI)
# ==========================================
st.sidebar.title("AT PRO 27 - Web")
st.sidebar.markdown("---")

# 1. Chargement des données
st.sidebar.subheader("1. Base de données")
mif_upload = st.sidebar.file_uploader("Fichier .MIF", type=['mif'])
mid_upload = st.sidebar.file_uploader("Fichier .MID", type=['mid'])

if mif_upload and mid_upload:
    if st.sidebar.button("Traiter les fichiers"):
        with st.spinner("Analyse et construction de la base en cours..."):
            st.session_state.donnees_tf = parser_fichiers(mif_upload, mid_upload)
            st.sidebar.success(f"{len(st.session_state.donnees_tf)} Titres chargés !")

st.sidebar.markdown("---")

# 2. Recherche
st.sidebar.subheader("2. Recherche Foncier")
tf_input = st.sidebar.text_input("Ex: 12505/C").upper()

if st.sidebar.button("🔍 Localiser"):
    tf_propre = nettoyer_tf(tf_input)
    if tf_propre in st.session_state.donnees_tf:
        st.session_state.recherche_actuelle = tf_propre
    else:
        st.sidebar.error("Titre introuvable.")

# 3. Exportation
if st.session_state.recherche_actuelle:
    st.sidebar.markdown("---")
    st.sidebar.subheader("3. Exportations")
    tf = st.session_state.recherche_actuelle
    data = st.session_state.donnees_tf[tf]
    
    pdf_bytes = generer_pdf(tf, data)
    st.sidebar.download_button(label="📄 Exporter Rapport PDF", data=pdf_bytes, file_name=f"Rapport_TF_{tf.replace('/', '_')}.pdf", mime="application/pdf")
    
    kml_bytes = generer_kml(tf, data)
    st.sidebar.download_button(label="🌍 Exporter KML (Google Earth)", data=kml_bytes, file_name=f"TF_{tf.replace('/', '_')}.kml", mime="application/vnd.google-earth.kml+xml")

st.sidebar.markdown("---")
st.sidebar.markdown("<p style='text-align: center; color: gray; font-size: 11px;'>© 2026 - TANTAWI ADIL<br>Propriété Intellectuelle</p>", unsafe_allow_html=True)

# ==========================================
# AFFICHAGE DE LA CARTE (FOLIUM)
# ==========================================
# Centre par défaut (Casablanca)
lat_center, lon_center = 33.59, -7.61
zoom_start = 12

if st.session_state.recherche_actuelle:
    tf = st.session_state.recherche_actuelle
    data = st.session_state.donnees_tf[tf]
    polygones = data.get('polygones', [])
    
    if polygones:
        # Calcul du centre pour zoomer
        lat_moy, lon_moy, nb_pts = 0, 0, 0
        for poly in polygones:
            for x, y in poly:
                lon, lat = transformer_fwd.transform(x, y)
                lat_moy += lat
                lon_moy += lon
                nb_pts += 1
        if nb_pts > 0:
            lat_center = lat_moy / nb_pts
            lon_center = lon_moy / nb_pts
            zoom_start = 18

m = folium.Map(location=[lat_center, lon_center], zoom_start=zoom_start, control_scale=True)

# Ajout du fond Google Satellite (Utilisation d'Internet car sur serveur Web)
folium.TileLayer(
    tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
    attr='Google',
    name='Google Satellite',
    overlay=False,
    control=True
).add_to(m)

# Dessin des polygones si recherche
if st.session_state.recherche_actuelle:
    tf = st.session_state.recherche_actuelle
    data = st.session_state.donnees_tf[tf]
    polygones = data.get('polygones', [])
    surfaces = data.get('surfaces_list', [])
    
    st.subheader(f"📍 Localisation du TF : {tf}")
    
    for i, s in enumerate(surfaces):
        st.write(f"**Superficie {i+1} :** {s} m²")
    
    for index, poly in enumerate(polygones):
        chemin_latlon = []
        for x, y in poly:
            lon, lat = transformer_fwd.transform(x, y)
            chemin_latlon.append((lat, lon))
        
        surf = surfaces[index] if index < len(surfaces) else 'Non précisée'
        tooltip_text = f"TF {tf} - {surf} m²"
        
        # Le contour jaune sans remplissage (fill=False, color='#ffff00') -> ZERO HACHURES, ADAPTÉ AU TACTILE MOBILE
        folium.Polygon(
            locations=chemin_latlon,
            color='#ffff00',
            weight=4,
            fill=False,
            tooltip=tooltip_text
        ).add_to(m)

# Affichage de la carte sur Streamlit
st_folium(m, width=1200, height=600, returned_objects=[])
