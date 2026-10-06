import streamlit as st
import folium
from streamlit_folium import st_folium
import csv
import zipfile
from pyproj import Transformer
from io import StringIO

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

# Algorithme Ray-Casting pour détecter un clic dans un polygone (Recherche inversée)
def point_in_polygon(x, y, poly):
    n = len(poly)
    inside = False
    if n == 0: return False
    p1x, p1y = poly[0]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

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
# PARSER ZIP (MIF / MID)
# ==========================================
def parser_fichiers_zip(zip_file):
    mif_content = None
    mid_content = None
    
    # Extraction en mémoire
    with zipfile.ZipFile(zip_file, 'r') as z:
        for filename in z.namelist():
            if filename.lower().endswith('.mif'):
                mif_content = z.read(filename).decode('windows-1252', errors='ignore')
            elif filename.lower().endswith('.mid'):
                mid_content = z.read(filename).decode('windows-1252', errors='ignore')

    if not mif_content or not mid_content:
        st.error("Erreur : Le fichier ZIP doit contenir à la fois un fichier .MIF et un fichier .MID")
        return {}

    geometries = []
    columns_info = []
    data_start = 0
    in_columns = False
    
    # Analyse de la structure du MIF
    mif_lines = mif_content.splitlines()
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

    # Détection des colonnes
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

    # Lecture des géométries MIF
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

    # Lecture des attributs MID et liaison exacte
    donnees = {}
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
                    if tf_name not in donnees:
                        donnees[tf_name] = {'polygones': [], 'surfaces_list': []}
                    if geometries[i]:
                        donnees[tf_name]['polygones'].append(geometries[i])
                        donnees[tf_name]['surfaces_list'].append(surf_texte)
                        
    return donnees

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
zip_upload = st.sidebar.file_uploader("Fichier ZIP (contenant MIF & MID)", type=['zip'])

if zip_upload:
    if st.sidebar.button("Traiter le fichier ZIP", use_container_width=True):
        with st.spinner("Analyse et construction de la base en cours..."):
            st.session_state.donnees_tf = parser_fichiers_zip(zip_upload)
            st.sidebar.success(f"{len(st.session_state.donnees_tf)} Titres chargés avec succès !")

st.sidebar.markdown("---")

# 2. Recherche
st.sidebar.subheader("2. Recherche Foncier")
tf_input = st.sidebar.text_input("Ex: 12505/C").upper()

col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    if st.button("🔍 Localiser", use_container_width=True):
        tf_propre = nettoyer_tf(tf_input)
        if tf_propre in st.session_state.donnees_tf:
            st.session_state.recherche_actuelle = tf_propre
        else:
            st.error("Titre introuvable.")

with col_btn2:
    if st.button("🗑️ Effacer", use_container_width=True):
        st.session_state.recherche_actuelle = None
        st.rerun()

# 3. Exportation
if st.session_state.recherche_actuelle:
    st.sidebar.markdown("---")
    st.sidebar.subheader("3. Exportations")
    tf = st.session_state.recherche_actuelle
    data = st.session_state.donnees_tf[tf]
    
    kml_bytes = generer_kml(tf, data)
    st.sidebar.download_button(label="🌍 Exporter KML (Google Earth)", data=kml_bytes, file_name=f"TF_{tf.replace('/', '_')}.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)

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

# Ajout du fond Google Satellite
folium.TileLayer(
    tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
    attr='Google',
    name='Google Satellite',
    overlay=False,
    control=True
).add_to(m)

# Dessin des polygones dynamiquement
if st.session_state.recherche_actuelle:
    tf = st.session_state.recherche_actuelle
    data = st.session_state.donnees_tf[tf]
    polygones = data.get('polygones', [])
    surfaces = data.get('surfaces_list', [])
    
    st.subheader(f"📍 Localisation du TF : {tf}")
    
    for index, poly in enumerate(polygones):
        chemin_latlon = []
        for x, y in poly:
            lon, lat = transformer_fwd.transform(x, y)
            chemin_latlon.append((lat, lon))
        
        surf = surfaces[index] if index < len(surfaces) else 'Non précisée'
        tooltip_text = f"TF {tf}"
        
        # Le contour jaune
        folium.Polygon(
            locations=chemin_latlon,
            color='#ffff00',
            weight=4,
            fill=True,
            fill_opacity=0.2, # Légèrement transparent pour voir le fond
            fill_color='#ffff00',
            tooltip=tooltip_text
        ).add_to(m)

        # Calculer le centre (Centroïde) du polygone pour afficher le texte
        if chemin_latlon:
            c_lat = sum(pt[0] for pt in chemin_latlon) / len(chemin_latlon)
            c_lon = sum(pt[1] for pt in chemin_latlon) / len(chemin_latlon)

            # Placer la superficie au centre du polygone
            folium.Marker(
                location=[c_lat, c_lon],
                icon=folium.DivIcon(
                    html=f"""
                    <div style="font-size: 11pt; color: black; font-weight: bold; 
                    background-color: rgba(255,255,255,0.8); border: 2px solid #003366; 
                    border-radius: 5px; padding: 2px 5px; text-align: center; 
                    white-space: nowrap; transform: translate(-50%, -50%); box-shadow: 2px 2px 5px rgba(0,0,0,0.5);">
                    {surf} m²</div>
                    """
                )
            ).add_to(m)

# Affichage fluide pour mobile
st_data = st_folium(m, use_container_width=True, height=500, returned_objects=["last_clicked"])

# ==========================================
# GESTION DU CLIC SUR LA CARTE (Recherche inversée)
# ==========================================
if st_data and st_data.get("last_clicked"):
    lat_c = st_data["last_clicked"]["lat"]
    lon_c = st_data["last_clicked"]["lng"]
    
    # Conversion du point cliqué (WGS84 -> Lambert Merchich)
    x_click, y_click = transformer_inv.transform(lon_c, lat_c)
    
    found_tf = None
    
    # Recherche dans toutes les géométries en mémoire
    for tf_name, data_tf in st.session_state.donnees_tf.items():
        for poly in data_tf.get('polygones', []):
            if point_in_polygon(x_click, y_click, poly):
                found_tf = tf_name
                break
        if found_tf:
            break
            
    # Si on trouve un terrain cliqué et que ce n'est pas déjà celui affiché, on met à jour
    if found_tf and found_tf != st.session_state.recherche_actuelle:
        st.session_state.recherche_actuelle = found_tf
        st.rerun()
