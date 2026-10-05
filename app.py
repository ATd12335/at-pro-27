import streamlit as st
import folium
from streamlit_folium import st_folium
import pyproj
from fpdf import FPDF
import io
import tempfile
import matplotlib.pyplot as plt
from shapely.geometry import Point, Polygon
import zipfile

# Configuration optimale pour Mobile (Web)
st.set_page_config(page_title="SIG Foncier Mobile", layout="centered", initial_sidebar_state="collapsed")

# 1. Authentification
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Accès Sécurisé")
    pwd = st.text_input("Mot de passe", type="password")
    if pwd == "209287":
        st.session_state.auth = True
        st.rerun()
    elif pwd:
        st.error("Mot de passe incorrect")
    st.stop()

# --- Initialisation des états ---
if "polygons" not in st.session_state:
    st.session_state.polygons = {}
if "selected_tf" not in st.session_state:
    st.session_state.selected_tf = None
if "map_center" not in st.session_state:
    st.session_state.map_center = [33.5731, -7.5898] # Casablanca par défaut

st.title("📍 SIG Foncier Mobile")
st.markdown("Interface 100% tactile avec imagerie Satellite Haute Définition.")

# 2. Upload de l'archive ZIP
with st.expander("📁 Importer l'archive (.ZIP)", expanded=(not st.session_state.polygons)):
    archive_file = st.file_uploader("Fichier .ZIP (contenant le .MIF et .MID)", type=['zip'])

    if archive_file and st.button("Traiter les données"):
        mif_text = None
        mid_text = None
        
        try:
            with zipfile.ZipFile(archive_file, 'r') as z:
                for filename in z.namelist():
                    if filename.lower().endswith('.mif'):
                        mif_text = z.read(filename).decode("latin-1", errors="ignore").splitlines()
                    elif filename.lower().endswith('.mid'):
                        mid_text = z.read(filename).decode("latin-1", errors="ignore").splitlines()
                        
            if not mif_text or not mid_text:
                st.error("❌ Erreur : L'archive ZIP doit obligatoirement contenir au moins un fichier .MIF et un fichier .MID.")
            else:
                # Projections (Lambert Nord Maroc = EPSG:26191)
                transformer = pyproj.Transformer.from_crs("EPSG:26191", "EPSG:4326", always_xy=True)
                
                polygons = {}
                current_tf_index = 0
                i = 0
                while i < len(mif_text):
                    line = mif_text[i].strip()
                    if line.upper().startswith("REGION"):
                        try:
                            num_polys = int(line.split()[1])
                            coords = []
                            # CORRECTION ALGORITHMIQUE : Gestion des multi-polygones pour garder l'alignement
                            for poly_idx in range(num_polys):
                                i += 1
                                num_points = int(mif_text[i].strip().split()[0])
                                for _ in range(num_points):
                                    i += 1
                                    if poly_idx == 0: # On trace le polygone principal
                                        pts = mif_text[i].strip().split()
                                        x, y = float(pts[0]), float(pts[1])
                                        lon, lat = transformer.transform(x, y)
                                        coords.append((lat, lon))
                            
                            # Assignation stricte 1-à-1 entre REGION et ligne MID
                            if current_tf_index < len(mid_text):
                                tf_name = mid_text[current_tf_index].replace('"', '').strip()
                                polygons[tf_name] = coords
                            current_tf_index += 1
                        except Exception as e:
                            pass
                    i += 1
                
                if polygons:
                    st.session_state.polygons = polygons
                    first_poly = list(polygons.values())[0]
                    st.session_state.map_center = first_poly[0]
                    st.success(f"✅ {len(polygons)} parcelles extraites et chargées avec succès !")
                    st.rerun()
        except zipfile.BadZipFile:
            st.error("❌ Le fichier importé n'est pas un fichier ZIP valide ou est corrompu.")

# 3. Fonction pour générer le PDF
def generate_pdf(tf_name, coords):
    # Calcul strict de la superficie en Lambert 1 (mètres carrés réels)
    transformer_back = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:26191", always_xy=True)
    coords_lambert = [transformer_back.transform(lon, lat) for lat, lon in coords]
    poly_lambert = Polygon(coords_lambert)
    area = abs(poly_lambert.area)
    
    fig, ax = plt.subplots(figsize=(6, 6))
    xs = [p[0] for p in coords_lambert]
    ys = [p[1] for p in coords_lambert]
    ax.plot(xs, ys, color='red', linewidth=2)
    ax.fill(xs, ys, alpha=0.3, color='red')
    ax.set_aspect('equal')
    ax.axis('off')
    plt.title(f"Croquis Topographique : {tf_name}", fontsize=14)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    buf.seek(0)
    plt.close(fig)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(buf.getvalue())
        tmp_path = tmp.name
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="RAPPORT D'IDENTIFICATION FONCIERE", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(50, 10, txt="Titre Foncier :", ln=False)
    pdf.set_font("Arial", '', 12)
    pdf.cell(100, 10, txt=str(tf_name), ln=True)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(50, 10, txt="Superficie reelle :", ln=False)
    pdf.set_font("Arial", '', 12)
    pdf.cell(100, 10, txt=f"{area:,.2f} m2".replace(',', ' '), ln=True)
    
    pdf.ln(10)
    pdf.image(tmp_path, x=30, y=None, w=150)
    
    return pdf.output(dest='S').encode('latin-1')

# 4. Affichage de la Carte et Interaction Tactile
if st.session_state.polygons:
    st.markdown("### 🗺️ Carte Satellite")
    st.info("👆 **Touchez une parcelle jaune** pour l'identifier.")
    
    m = folium.Map(location=st.session_state.map_center, zoom_start=18, tiles=None)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satellite HD',
        max_zoom=20
    ).add_to(m)
    
    for tf_name, coords in st.session_state.polygons.items():
        color = "red" if tf_name == st.session_state.selected_tf else "yellow"
        folium.Polygon(
            locations=coords,
            color=color,
            weight=3,
            fill=True,
            fill_color=color,
            fill_opacity=0.5,
            tooltip=tf_name
        ).add_to(m)
    
    map_data = st_folium(m, use_container_width=True, height=500, returned_objects=["last_clicked"])
    
    if map_data and map_data.get("last_clicked"):
        lat = map_data["last_clicked"]["lat"]
        lon = map_data["last_clicked"]["lng"]
        point = Point(lon, lat)
        
        trouve = False
        for tf_name, coords in st.session_state.polygons.items():
            poly_shapely = Polygon([(c[1], c[0]) for c in coords])
            if poly_shapely.contains(point):
                st.session_state.selected_tf = tf_name
                st.session_state.map_center = [lat, lon]
                trouve = True
                st.rerun()
                break
        
        if not trouve:
            st.warning("❌ Aucun titre foncier sous votre doigt.")

    if st.session_state.selected_tf:
        tf_actuel = st.session_state.selected_tf
        coords_actuelles = st.session_state.polygons[tf_actuel]
        
        st.success(f"✅ Titre identifié : **{tf_actuel}**")
        
        pdf_bytes = generate_pdf(tf_actuel, coords_actuelles)
        
        st.download_button(
            label="📥 TÉLÉCHARGER LE RAPPORT PDF",
            data=pdf_bytes,
            file_name=f"Rapport_{tf_actuel}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
