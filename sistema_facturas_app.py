import os
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

# ============================================================
# CONFIGURACION
# ============================================================
st.set_page_config(page_title="Sistema Digital de Facturas", page_icon="📄", layout="wide")

BASE_DIR = Path("base_facturas")
PDF_DIR = BASE_DIR / "pdf"
XML_DIR = BASE_DIR / "xml"
DB_PATH = BASE_DIR / "facturas.db"

for carpeta in [BASE_DIR, PDF_DIR, XML_DIR]:
    carpeta.mkdir(parents=True, exist_ok=True)

AREAS = ["Adquisiciones", "Contabilidad", "Inventarios"]

# ============================================================
# DISEÑO
# ============================================================
st.markdown('''
<style>
.stApp {
    background: linear-gradient(135deg, #EEF8F5 0%, #FFF7E7 50%, #F8C2A5 100%);
}
.block-container { padding-top: 25px; }
.header-card {
    background: linear-gradient(135deg, rgba(219,246,241,0.98), rgba(255,242,216,0.98));
    padding: 26px; border-radius: 22px; box-shadow: 0px 8px 24px rgba(0,0,0,0.12);
    text-align: center; margin-bottom: 20px;
}
.header-card h1 { color: #087B75; font-weight: 900; }
.card {
    background: rgba(255,255,255,0.85); padding: 22px; border-radius: 18px;
    box-shadow: 0px 5px 15px rgba(0,0,0,0.09); border-left: 7px solid #087B75;
    margin-bottom: 18px;
}
.stButton > button {
    background: linear-gradient(90deg, #E94E1B, #F2B233); color: white; border: none;
    border-radius: 14px; padding: 12px; font-weight: 900; width: 100%;
}
.stDownloadButton > button {
    background: linear-gradient(90deg, #087B75, #14A39A); color: white; border: none;
    border-radius: 14px; padding: 12px; font-weight: 900; width: 100%;
}
</style>
''', unsafe_allow_html=True)

# ============================================================
# BASE DE DATOS
# ============================================================
def conectar():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def inicializar_db():
    con = conectar()
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_captura TEXT,
            area TEXT,
            proveedor TEXT,
            rfc_proveedor TEXT,
            receptor TEXT,
            rfc_receptor TEXT,
            uuid TEXT UNIQUE,
            serie TEXT,
            folio TEXT,
            fecha_factura TEXT,
            subtotal REAL,
            iva REAL,
            total REAL,
            moneda TEXT,
            metodo_pago TEXT,
            forma_pago TEXT,
            uso_cfdi TEXT,
            conceptos TEXT,
            pdf_path TEXT,
            xml_path TEXT,
            observaciones TEXT
        )
    ''')
    con.commit()
    con.close()

inicializar_db()

# ============================================================
# LECTOR XML CFDI
# ============================================================
def extraer_datos_xml(xml_bytes):
    datos = {
        "proveedor": "", "rfc_proveedor": "", "receptor": "", "rfc_receptor": "",
        "uuid": "", "serie": "", "folio": "", "fecha_factura": "",
        "subtotal": 0.0, "iva": 0.0, "total": 0.0, "moneda": "",
        "metodo_pago": "", "forma_pago": "", "uso_cfdi": "", "conceptos": ""
    }

    try:
        root = ET.fromstring(xml_bytes)
        comprobante = root

        datos["serie"] = comprobante.attrib.get("Serie", "")
        datos["folio"] = comprobante.attrib.get("Folio", "")
        datos["fecha_factura"] = comprobante.attrib.get("Fecha", "")
        datos["subtotal"] = float(comprobante.attrib.get("SubTotal", 0) or 0)
        datos["total"] = float(comprobante.attrib.get("Total", 0) or 0)
        datos["moneda"] = comprobante.attrib.get("Moneda", "")
        datos["metodo_pago"] = comprobante.attrib.get("MetodoPago", "")
        datos["forma_pago"] = comprobante.attrib.get("FormaPago", "")

        conceptos = []
        iva = 0.0

        for elem in root.iter():
            tag = elem.tag.lower()

            if tag.endswith("emisor"):
                datos["proveedor"] = elem.attrib.get("Nombre", "")
                datos["rfc_proveedor"] = elem.attrib.get("Rfc", "")

            elif tag.endswith("receptor"):
                datos["receptor"] = elem.attrib.get("Nombre", "")
                datos["rfc_receptor"] = elem.attrib.get("Rfc", "")
                datos["uso_cfdi"] = elem.attrib.get("UsoCFDI", "")

            elif tag.endswith("timbrefiscaldigital"):
                datos["uuid"] = elem.attrib.get("UUID", "")

            elif tag.endswith("concepto"):
                cantidad = elem.attrib.get("Cantidad", "")
                desc = elem.attrib.get("Descripcion", "")
                valor = elem.attrib.get("ValorUnitario", "")
                importe = elem.attrib.get("Importe", "")
                conceptos.append(f"{cantidad} x {desc} | VU: {valor} | Importe: {importe}")

            elif tag.endswith("traslado"):
                impuesto = elem.attrib.get("Impuesto", "")
                importe = elem.attrib.get("Importe", "")
                if impuesto == "002" and importe:
                    try:
                        iva += float(importe)
                    except Exception:
                        pass

        datos["iva"] = iva
        datos["conceptos"] = "\n".join(conceptos)

    except Exception as e:
        st.error(f"No se pudo leer el XML: {e}")

    return datos

def guardar_archivo(uploaded_file, carpeta, nombre_archivo):
    ruta = carpeta / nombre_archivo
    with open(ruta, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(ruta)

def insertar_factura(datos, area, pdf_path, xml_path, observaciones):
    con = conectar()
    cur = con.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO facturas (
            fecha_captura, area, proveedor, rfc_proveedor, receptor, rfc_receptor,
            uuid, serie, folio, fecha_factura, subtotal, iva, total, moneda,
            metodo_pago, forma_pago, uso_cfdi, conceptos, pdf_path, xml_path, observaciones
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), area,
        datos["proveedor"], datos["rfc_proveedor"], datos["receptor"], datos["rfc_receptor"],
        datos["uuid"], datos["serie"], datos["folio"], datos["fecha_factura"],
        datos["subtotal"], datos["iva"], datos["total"], datos["moneda"],
        datos["metodo_pago"], datos["forma_pago"], datos["uso_cfdi"],
        datos["conceptos"], pdf_path, xml_path, observaciones
    ))
    con.commit()
    con.close()

def leer_facturas():
    con = conectar()
    df = pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC", con)
    con.close()
    return df

def filtrar_facturas(df, texto="", area="Todas"):
    if df.empty:
        return df
    resultado = df.copy()

    if area != "Todas":
        resultado = resultado[resultado["area"] == area]

    if texto:
        t = texto.upper()
        campos = ["proveedor", "rfc_proveedor", "receptor", "rfc_receptor", "uuid", "folio", "conceptos", "observaciones"]
        filtro = False
        for campo in campos:
            filtro = filtro | resultado[campo].astype(str).str.upper().str.contains(t, na=False)
        resultado = resultado[filtro]

    return resultado

def crear_excel(df):
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    return output

def crear_zip_facturas(df):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for _, row in df.iterrows():
            for campo in ["pdf_path", "xml_path"]:
                ruta = row.get(campo, "")
                if ruta and os.path.exists(ruta):
                    z.write(ruta, arcname=os.path.basename(ruta))
    output.seek(0)
    return output

def descargar_archivo(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None

# ============================================================
# PANTALLA
# ============================================================
st.markdown('''
<div class="header-card">
<h1>📄 Sistema Digital de Facturas</h1>
<p>Adquisiciones · Contabilidad · Inventarios</p>
</div>
''', unsafe_allow_html=True)

menu = st.sidebar.radio(
    "Menú",
    ["🏠 Inicio", "📤 Subir factura", "🔎 Buscar factura", "📊 Reportes",
     "🛒 Adquisiciones", "💰 Contabilidad", "📦 Inventarios", "⚙️ Administración"]
)

df = leer_facturas()

if menu == "🏠 Inicio":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Resumen general")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Facturas registradas", len(df))
    c2.metric("Total general", f"${df['total'].sum():,.2f}" if not df.empty else "$0.00")
    c3.metric("Proveedores", df["proveedor"].nunique() if not df.empty else 0)
    c4.metric("Áreas", df["area"].nunique() if not df.empty else 0)
    st.markdown("</div>", unsafe_allow_html=True)

    st.subheader("Últimas facturas")
    if df.empty:
        st.warning("Todavía no hay facturas registradas.")
    else:
        st.dataframe(df[["id", "area", "proveedor", "folio", "uuid", "fecha_factura", "total"]].head(20), use_container_width=True)

elif menu == "📤 Subir factura":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Subir factura PDF + XML")

    area = st.selectbox("Área responsable", AREAS)
    pdf_file = st.file_uploader("Factura en PDF", type=["pdf"])
    xml_file = st.file_uploader("Factura en XML", type=["xml"])
    observaciones = st.text_area("Observaciones")

    if xml_file:
        datos = extraer_datos_xml(xml_file.getvalue())

        st.markdown("### Datos detectados del XML")
        c1, c2, c3 = st.columns(3)
        c1.text_input("Proveedor", value=datos["proveedor"], disabled=True)
        c2.text_input("RFC proveedor", value=datos["rfc_proveedor"], disabled=True)
        c3.text_input("UUID", value=datos["uuid"], disabled=True)

        c4, c5, c6 = st.columns(3)
        c4.text_input("Folio", value=f'{datos["serie"]}{datos["folio"]}', disabled=True)
        c5.text_input("Fecha factura", value=datos["fecha_factura"], disabled=True)
        c6.text_input("Total", value=f'${datos["total"]:,.2f}', disabled=True)

        st.text_area("Conceptos", value=datos["conceptos"], height=150, disabled=True)

        if st.button("💾 Guardar factura digital"):
            if not pdf_file:
                st.error("Falta subir el PDF.")
            elif not datos["uuid"]:
                st.error("El XML no tiene UUID. Revisa que sea CFDI válido.")
            else:
                nombre_base = datos["uuid"]
                pdf_path = guardar_archivo(pdf_file, PDF_DIR, f"{nombre_base}.pdf")
                xml_path = guardar_archivo(xml_file, XML_DIR, f"{nombre_base}.xml")
                insertar_factura(datos, area, pdf_path, xml_path, observaciones)
                st.success("Factura guardada correctamente.")
                st.rerun()
    else:
        st.info("Primero sube el XML para leer los datos automáticamente.")

    st.markdown("</div>", unsafe_allow_html=True)

elif menu == "🔎 Buscar factura":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Buscar factura")

    col1, col2 = st.columns(2)
    with col1:
        texto = st.text_input("Buscar por proveedor, RFC, folio, UUID, concepto o nota")
    with col2:
        area = st.selectbox("Área", ["Todas"] + AREAS)

    resultado = filtrar_facturas(df, texto=texto, area=area)

    st.write(f"Resultados encontrados: **{len(resultado)}**")

    if resultado.empty:
        st.warning("No se encontraron facturas.")
    else:
        st.dataframe(resultado[["id", "area", "proveedor", "rfc_proveedor", "folio", "uuid", "fecha_factura", "subtotal", "iva", "total"]], use_container_width=True)

        id_sel = st.selectbox("Selecciona una factura para descargar", resultado["id"].tolist())
        factura = resultado[resultado["id"] == id_sel].iloc[0]

        st.markdown("### Detalle")
        st.write(f"**Proveedor:** {factura['proveedor']}")
        st.write(f"**RFC:** {factura['rfc_proveedor']}")
        st.write(f"**UUID:** {factura['uuid']}")
        st.write(f"**Total:** ${factura['total']:,.2f}")
        st.text_area("Conceptos", value=str(factura["conceptos"]), height=150, disabled=True)

        col1, col2 = st.columns(2)
        pdf_data = descargar_archivo(factura["pdf_path"])
        xml_data = descargar_archivo(factura["xml_path"])

        with col1:
            if pdf_data:
                st.download_button("📄 Descargar PDF", data=pdf_data, file_name=f"{factura['uuid']}.pdf", mime="application/pdf")
        with col2:
            if xml_data:
                st.download_button("🧾 Descargar XML", data=xml_data, file_name=f"{factura['uuid']}.xml", mime="text/xml")

    st.markdown("</div>", unsafe_allow_html=True)

elif menu == "📊 Reportes":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Reportes de costos")

    if df.empty:
        st.warning("Todavía no hay facturas registradas.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            area = st.selectbox("Área", ["Todas"] + AREAS)
        with col2:
            proveedor = st.selectbox("Proveedor", ["Todos"] + sorted(df["proveedor"].dropna().unique().tolist()))

        rep = df.copy()
        if area != "Todas":
            rep = rep[rep["area"] == area]
        if proveedor != "Todos":
            rep = rep[rep["proveedor"] == proveedor]

        c1, c2 = st.columns(2)
        c1.metric("Total filtrado", f"${rep['total'].sum():,.2f}")
        c2.metric("Facturas filtradas", len(rep))

        st.markdown("### Total por área")
        resumen_area = rep.groupby("area", as_index=False)["total"].sum()
        st.dataframe(resumen_area, use_container_width=True)
        if not resumen_area.empty:
            st.bar_chart(resumen_area.set_index("area"))

        st.markdown("### Total por proveedor")
        resumen_prov = rep.groupby("proveedor", as_index=False)["total"].sum().sort_values("total", ascending=False)
        st.dataframe(resumen_prov, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button("📥 Descargar reporte Excel", data=crear_excel(rep), file_name="reporte_facturas.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with col2:
            st.download_button("📦 Descargar PDF/XML en ZIP", data=crear_zip_facturas(rep), file_name="facturas_digitales.zip", mime="application/zip")

    st.markdown("</div>", unsafe_allow_html=True)

elif menu in ["🛒 Adquisiciones", "💰 Contabilidad", "📦 Inventarios"]:
    area_actual = menu.split(" ", 1)[1]
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader(f"Área: {area_actual}")

    area_df = df[df["area"] == area_actual] if not df.empty else df
    st.metric("Facturas", len(area_df))
    st.metric("Total", f"${area_df['total'].sum():,.2f}" if not area_df.empty else "$0.00")

    if area_df.empty:
        st.warning("No hay facturas para esta área.")
    else:
        st.dataframe(area_df[["id", "proveedor", "folio", "uuid", "fecha_factura", "total"]], use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

elif menu == "⚙️ Administración":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Administración de facturas")

    if df.empty:
        st.warning("No hay facturas registradas.")
    else:
        st.dataframe(df, use_container_width=True)

        id_sel = st.selectbox("Selecciona ID para eliminar", df["id"].tolist())
        if st.button("🗑️ Eliminar factura seleccionada"):
            con = conectar()
            cur = con.cursor()
            factura = df[df["id"] == id_sel].iloc[0]

            for campo in ["pdf_path", "xml_path"]:
                ruta = factura[campo]
                if ruta and os.path.exists(ruta):
                    os.remove(ruta)

            cur.execute("DELETE FROM facturas WHERE id = ?", (int(id_sel),))
            con.commit()
            con.close()
            st.success("Factura eliminada.")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
