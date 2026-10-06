import streamlit as st
import folium
from folium.plugins import Fullscreen
from streamlit_folium import st_folium
import csv
import zipfile
from pyproj import Transformer
from io import StringIO

# ==========================================
# CONFIGURATION DE LA PAGE & CSS (Optimisé iOS)
# ==========================================
st.set_page_config(page_title="AT PRO 27", page_icon="🌍", layout="wide", initial_sidebar_state="expanded")

# Injection CSS puissante pour un look "App Native" et un faux plein-écran fluide
st.markdown("""
<style>
    /* Masquer les éléments inutiles de Streamlit */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Supprimer les marges pour maximiser l'espace de la carte sur mobile */
    .block-container {
        padding: 0rem !important;
        margin: 0 !important;
        max-width: 100% !important;
    }
    
    /* Style iOS pour les boutons */
    div.stButton > button:first-child {
        background: linear-gradient(180deg, #0055ff 0%, #0033aa 100%);
        color: white;
        border-radius: 12px;
        border: none;
        padding: 10px 20px;
        font-weight: 600;
        box-shadow: 0px 4px 10px rgba(0, 51, 170, 0.3);
        transition: all 0.2s ease-in-out;
    }
    div.stButton > button:first-child:active {
        transform: scale(0.95);
        box-shadow: 0px 2px 5px rgba(0, 51, 170, 0.2);
    }
    
    /* Bouton d'effacement spécifique */
    div:nth-child(2) > div.stButton > button:first-child {
        background: linear-gradient(180deg, #ff4444 0%, #cc0000 100%);
        box-shadow: 0px 4px 10px rgba(204, 0, 0, 0.3);
    }

    /* Arrondir les champs de texte */
    .stTextInput>div>div>input {
        border-radius: 10px;
        border: 1px solid #ddd;
        padding: 12px;
        font-size: 16px; /* Empêche le zoom auto sur Safari iOS */
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# AUTHENTIFICATION
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<div style='padding: 2rem;'>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align: center; color: #003366; margin-bottom: 0; font-family: -apple-system, sans-serif;'>AT PRO 27</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 14px; color: #555;'>Système d'Information Géographique Foncier</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 10, 1])
    with col2:
        st.write("") 
        pwd = st.text_input("🔑 Mot de passe", type="password", placeholder="Saisir le mot de passe...")
        if st.button("DÉVERROUILLER", use_container_width=True):
            if pwd == "209287":
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Accès Refusé.")
        st.markdown("<p style='text-align: center; color: gray; font-size: 11px; margin-top: 50px;'>© 2026 TANTAWI ADIL<br>Propriété Intellectuelle</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
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
# VARIABLES DE SESSION
# ==========================================
if "donnees_tf" not in st.session_state:
    st.session_state.donnees_tf = {}
if "recherche_actuelle" not in st.session_state:
    st.session_state.recherche_actuelle = None

# ==========================================
# PARSER ZIP (Optimisé)
# ==========================================
@st.cache_data(show_spinner=False)
def parser_fichiers_zip_cached(zip_bytes):
    mif_content = None
    mid_content = None
    
    with zipfile.ZipFile(zip_bytes, 'r') as z:
        for filename in z.namelist():
            if filename.lower().endswith('.mif'):
                mif_content = z.read(filename).decode('windows-1252', errors='ignore')
            elif filename.lower().endswith('.mid'):
                mid_content = z.read(filename).decode('windows-1252', errors='ignore')

    if not mif_content or not mid_content:
        return {}

    geometries = []
    columns_info = []
    data_start = 0
    in_columns = False
    
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
            
            # Formatage avec espace séparateur des milliers
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
# INTERFACE LATÉRALE (SIDEBAR)
# ==========================================
st.sidebar.markdown("<h3 style='text-align: center; color: #003366; font-family: -apple-system, sans-serif;'>AT PRO 27</h3>", unsafe_allow_html=True)
st.sidebar.markdown("---")

zip_upload = st.sidebar.file_uploader("📂 Importer ZIP (MIF & MID)", type=['zip'])

if zip_upload:
    with st.spinner("Analyse en cours..."):
        # Utilisation du cache pour éviter de recharger le fichier ZIP à chaque interaction tactile
        st.session_state.donnees_tf = parser_fichiers_zip_cached(zip_upload)
        st.sidebar.success(f"✅ {len(st.session_state.donnees_tf)} Titres chargés")

st.sidebar.markdown("---")
st.sidebar.markdown("<p style='font-weight: 600; color: #333; margin-bottom: 5px;'>🔍 Recherche Foncier</p>", unsafe_allow_html=True)
tf_input = st.sidebar.text_input("N° du Titre (Ex: 12505/C)", placeholder="Ex: 12505/C", label_visibility="collapsed")

col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    if st.button("Chercher", use_container_width=True):
        tf_propre = nettoyer_tf(tf_input)
        if tf_propre in st.session_state.donnees_tf:
            st.session_state.recherche_actuelle = tf_propre
        else:
            st.sidebar.error("Introuvable.")

with col_btn2:
    if st.button("Effacer", use_container_width=True):
        st.session_state.recherche_actuelle = None
        st.rerun()

if st.session_state.recherche_actuelle:
    tf = st.session_state.recherche_actuelle
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"<p style='color: #003366; font-weight: bold;'>📍 Actif : TF {tf}</p>", unsafe_allow_html=True)
    data = st.session_state.donnees_tf[tf]
    kml_bytes = generer_kml(tf, data)
    st.sidebar.download_button(label="🌍 Télécharger KML", data=kml_bytes, file_name=f"TF_{tf.replace('/', '_')}.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)

# ==========================================
# MOTEUR CARTOGRAPHIQUE (FOLIUM HD)
# ==========================================
lat_center, lon_center = 33.59, -7.61
zoom_start = 12

if st.session_state.recherche_actuelle:
    tf = st.session_state.recherche_actuelle
    data = st.session_state.donnees_tf[tf]
    polygones = data.get('polygones', [])
    
    if polygones:
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
            zoom_start = 19 # Zoom rapproché

# Création de la carte avec max_zoom élevé
m = folium.Map(location=[lat_center, lon_center], zoom_start=zoom_start, control_scale=False, max_zoom=22, zoom_control=False)

# Plein écran classique (pour Android / PC)
Fullscreen(position='topright').add_to(m)

# Couche Google Satellite Haute Définition
folium.TileLayer(
    tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}&scale=2',
    attr='Google HD',
    name='Google Satellite HD',
    overlay=False,
    max_zoom=22
).add_to(m)

if st.session_state.recherche_actuelle:
    tf = st.session_state.recherche_actuelle
    data = st.session_state.donnees_tf[tf]
    polygones = data.get('polygones', [])
    surfaces = data.get('surfaces_list', [])
    
    for index, poly in enumerate(polygones):
        chemin_latlon = []
        for x, y in poly:
            lon, lat = transformer_fwd.transform(x, y)
            chemin_latlon.append((lat, lon))
        
        surf = surfaces[index] if index < len(surfaces) else 'Non précisée'
        
        # Le tracé du polygone (Couleur néon dynamique)
        folium.Polygon(
            locations=chemin_latlon,
            color='#FFEA00', # Jaune très éclatant
            weight=4,
            fill=True,
            fill_opacity=0.1, # Très léger pour préserver l'image satellite
            fill_color='#FFEA00'
        ).add_to(m)

        if chemin_latlon:
            c_lat = sum(pt[0] for pt in chemin_latlon) / len(chemin_latlon)
            c_lon = sum(pt[1] for pt in chemin_latlon) / len(chemin_latlon)

            # ÉTIQUETTE CORRIGÉE : Plus de forme résiduelle grâce à icon_size=(0,0) et class_name "dummy"
            folium.Marker(
                location=[c_lat, c_lon],
                icon=folium.DivIcon(
                    class_name="dummy", # Détruit la classe par défaut de Leaflet
                    icon_size=(0, 0),   # Alloue 0 pixel d'espace initial
                    icon_anchor=(0, 0),
                    html=f"""
                    <div style="
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        font-size: 13px; 
                        color: #ffffff; 
                        font-weight: 700; 
                        background-color: rgba(20, 30, 40, 0.85); 
                        border: 1px solid rgba(255, 255, 255, 0.3); 
                        border-radius: 8px; 
                        padding: 6px 12px; 
                        text-align: center; 
                        white-space: nowrap; 
                        transform: translate(-50%, -50%); 
                        box-shadow: 0px 8px 15px rgba(0,0,0,0.5);
                        backdrop-filter: blur(5px);
                        -webkit-backdrop-filter: blur(5px);
                    ">
                    {surf} m²</div>
                    """
                )
            ).add_to(m)

# Hauteur fixée à 850px pour simuler le plein écran direct sur le téléphone
st_data = st_folium(m, use_container_width=True, height=850, returned_objects=["last_clicked"])

# ==========================================
# RECHERCHE INVERSÉE (TAPER SUR LA CARTE)
# ==========================================
if st_data and st_data.get("last_clicked"):
    lat_c = st_data["last_clicked"]["lat"]
    lon_c = st_data["last_clicked"]["lng"]
    x_click, y_click = transformer_inv.transform(lon_c, lat_c)
    
    found_tf = None
    for tf_name, data_tf in st.session_state.donnees_tf.items():
        for poly in data_tf.get('polygones', []):
            if point_in_polygon(x_click, y_click, poly):
                found_tf = tf_name
                break
        if found_tf:
            break
            
    if found_tf and found_tf != st.session_state.recherche_actuelle:
        st.session_state.recherche_actuelle = found_tf
        st.rerun()
