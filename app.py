import os
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
from fpdf import FPDF

# ============================================================
# CONFIGURACION GENERAL
# ============================================================
st.set_page_config(
    page_title="Sistema Integral de Facturas DIF",
    page_icon="📄",
    layout="wide"
)

BASE_DIR = Path("base_facturas")
PDF_DIR = BASE_DIR / "pdf"
XML_DIR = BASE_DIR / "xml"
REQ_DIR = BASE_DIR / "requisiciones"
COT_DIR = BASE_DIR / "cotizaciones"
EVID_DIR = BASE_DIR / "evidencias"
DB_PATH = BASE_DIR / "facturas.db"

for carpeta in [BASE_DIR, PDF_DIR, XML_DIR, REQ_DIR, COT_DIR, EVID_DIR]:
    carpeta.mkdir(parents=True, exist_ok=True)

AREAS = ["Adquisiciones", "Contabilidad", "Inventarios"]
ESTADOS = ["Capturada", "En revision", "Autorizada", "Pagada", "Recibida", "Cancelada"]
USUARIOS = {
    "admin": {"password": "1234", "rol": "Administrador"},
    "adquisiciones": {"password": "1234", "rol": "Adquisiciones"},
    "contabilidad": {"password": "1234", "rol": "Contabilidad"},
    "inventarios": {"password": "1234", "rol": "Inventarios"},
    "consulta": {"password": "1234", "rol": "Consulta"},
}

# ============================================================
# DISENO
# ============================================================
st.markdown('''
<style>
.stApp {
    background:
        radial-gradient(circle at top left, rgba(8,123,117,0.18), transparent 30%),
        radial-gradient(circle at bottom right, rgba(233,78,27,0.25), transparent 34%),
        linear-gradient(135deg, #EEF8F5 0%, #FFF7E7 50%, #F8C2A5 100%);
}
.block-container { padding-top: 25px; }
.header-card {
    background: linear-gradient(135deg, rgba(219,246,241,0.98), rgba(255,242,216,0.98));
    padding: 26px; border-radius: 22px; box-shadow: 0px 8px 24px rgba(0,0,0,0.12);
    text-align: center; margin-bottom: 20px;
}
.header-card h1 { color: #087B75; font-weight: 900; }
.card {
    background: rgba(255,255,255,0.87); padding: 22px; border-radius: 18px;
    box-shadow: 0px 5px 15px rgba(0,0,0,0.09); border-left: 7px solid #087B75;
    margin-bottom: 18px;
}
.small-card {
    background: rgba(255,255,255,0.80);
    padding: 15px;
    border-radius: 14px;
    box-shadow: 0px 4px 12px rgba(0,0,0,0.08);
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
            expediente TEXT UNIQUE,
            fecha_captura TEXT,
            area TEXT,
            estado TEXT,
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
            requisicion_path TEXT,
            cotizacion_path TEXT,
            evidencia_path TEXT,
            observaciones TEXT,
            usuario TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS proveedores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE,
            rfc TEXT,
            telefono TEXT,
            correo TEXT,
            direccion TEXT,
            contacto TEXT,
            giro TEXT,
            fecha_registro TEXT
        )
    ''')

    con.commit()
    con.close()

def agregar_columna_si_no_existe(tabla, columna, tipo):
    con = conectar()
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({tabla})")
    columnas = [c[1] for c in cur.fetchall()]
    if columna not in columnas:
        cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
    con.commit()
    con.close()

inicializar_db()
for col, tipo in [
    ("expediente", "TEXT"),
    ("estado", "TEXT"),
    ("requisicion_path", "TEXT"),
    ("cotizacion_path", "TEXT"),
    ("evidencia_path", "TEXT"),
    ("usuario", "TEXT"),
]:
    agregar_columna_si_no_existe("facturas", col, tipo)

# ============================================================
# LOGIN
# ============================================================
def login():
    if "logueado" not in st.session_state:
        st.session_state.logueado = False
        st.session_state.usuario = ""
        st.session_state.rol = ""

    if st.session_state.logueado:
        return True

    st.markdown('''
    <div class="header-card">
    <h1>📄 Sistema Integral de Facturas DIF</h1>
    <p>Acceso de usuarios</p>
    </div>
    ''', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    usuario = st.text_input("Usuario")
    password = st.text_input("Contraseña", type="password")

    if st.button("🔐 Entrar"):
        if usuario in USUARIOS and password == USUARIOS[usuario]["password"]:
            st.session_state.logueado = True
            st.session_state.usuario = usuario
            st.session_state.rol = USUARIOS[usuario]["rol"]
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")

    st.info("Usuarios iniciales: admin / adquisiciones / contabilidad / inventarios / consulta. Contraseña: 1234")
    st.markdown("</div>", unsafe_allow_html=True)
    return False

if not login():
    st.stop()

# ============================================================
# XML CFDI
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

# ============================================================
# FUNCIONES
# ============================================================
def generar_expediente():
    anio = datetime.now().year
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM facturas WHERE expediente LIKE ?", (f"EXP-{anio}-%",))
    total = cur.fetchone()[0] + 1
    con.close()
    return f"EXP-{anio}-{total:04d}"

def guardar_archivo(uploaded_file, carpeta, nombre_archivo):
    if uploaded_file is None:
        return ""
    ruta = carpeta / nombre_archivo
    with open(ruta, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(ruta)

def guardar_proveedor_si_no_existe(nombre, rfc):
    if not nombre:
        return
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT id FROM proveedores WHERE nombre = ?", (nombre,))
    existe = cur.fetchone()
    if not existe:
        cur.execute('''
            INSERT INTO proveedores (nombre, rfc, fecha_registro)
            VALUES (?, ?, ?)
        ''', (nombre, rfc, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()

def insertar_factura(datos, area, estado, pdf_path, xml_path, req_path, cot_path, evid_path, observaciones):
    expediente = generar_expediente()
    con = conectar()
    cur = con.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO facturas (
            expediente, fecha_captura, area, estado, proveedor, rfc_proveedor, receptor, rfc_receptor,
            uuid, serie, folio, fecha_factura, subtotal, iva, total, moneda,
            metodo_pago, forma_pago, uso_cfdi, conceptos, pdf_path, xml_path,
            requisicion_path, cotizacion_path, evidencia_path, observaciones, usuario
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        expediente,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), area, estado,
        datos["proveedor"], datos["rfc_proveedor"], datos["receptor"], datos["rfc_receptor"],
        datos["uuid"], datos["serie"], datos["folio"], datos["fecha_factura"],
        datos["subtotal"], datos["iva"], datos["total"], datos["moneda"],
        datos["metodo_pago"], datos["forma_pago"], datos["uso_cfdi"],
        datos["conceptos"], pdf_path, xml_path, req_path, cot_path, evid_path,
        observaciones, st.session_state.usuario
    ))
    con.commit()
    con.close()
    guardar_proveedor_si_no_existe(datos["proveedor"], datos["rfc_proveedor"])
    return expediente

def leer_facturas():
    con = conectar()
    df = pd.read_sql_query("SELECT * FROM facturas ORDER BY id DESC", con)
    con.close()
    return df

def leer_proveedores():
    con = conectar()
    df = pd.read_sql_query("SELECT * FROM proveedores ORDER BY nombre", con)
    con.close()
    return df

def actualizar_estado_factura(id_factura, nuevo_estado):
    con = conectar()
    cur = con.cursor()
    cur.execute("UPDATE facturas SET estado = ? WHERE id = ?", (nuevo_estado, int(id_factura)))
    con.commit()
    con.close()

def actualizar_proveedor(id_prov, telefono, correo, direccion, contacto, giro):
    con = conectar()
    cur = con.cursor()
    cur.execute('''
        UPDATE proveedores
        SET telefono = ?, correo = ?, direccion = ?, contacto = ?, giro = ?
        WHERE id = ?
    ''', (telefono, correo, direccion, contacto, giro, int(id_prov)))
    con.commit()
    con.close()

def filtrar_facturas(df, texto="", area="Todas", estado="Todos"):
    if df.empty:
        return df
    resultado = df.copy()

    if area != "Todas":
        resultado = resultado[resultado["area"] == area]
    if estado != "Todos":
        resultado = resultado[resultado["estado"] == estado]

    if texto:
        t = texto.upper()
        campos = ["expediente", "proveedor", "rfc_proveedor", "receptor", "rfc_receptor", "uuid", "folio", "conceptos", "observaciones"]
        filtro = False
        for campo in campos:
            if campo in resultado.columns:
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
            carpeta_exp = str(row.get("expediente", "SIN_EXPEDIENTE"))
            for campo in ["pdf_path", "xml_path", "requisicion_path", "cotizacion_path", "evidencia_path"]:
                ruta = row.get(campo, "")
                if ruta and os.path.exists(ruta):
                    z.write(ruta, arcname=f"{carpeta_exp}/{os.path.basename(ruta)}")
    output.seek(0)
    return output

def descargar_archivo(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None

def texto_limpio(txt):
    if txt is None:
        return ""
    txt = str(txt)
    reemplazos = {"Á":"A","É":"E","Í":"I","Ó":"O","Ú":"U","Ñ":"N","á":"a","é":"e","í":"i","ó":"o","ú":"u","ñ":"n"}
    for a, b in reemplazos.items():
        txt = txt.replace(a, b)
    return txt

def crear_pdf_reporte(df, titulo="REPORTE DE FACTURAS"):
    output = BytesIO()
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Arial", "B", 15)
    pdf.cell(190, 10, texto_limpio(titulo), ln=True, align="C")
    pdf.set_font("Arial", "", 9)
    pdf.cell(190, 8, f"Fecha de generacion: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(5)

    total = df["total"].sum() if not df.empty else 0
    pdf.set_font("Arial", "B", 11)
    pdf.cell(190, 7, f"Total facturas: {len(df)}     Monto total: ${total:,.2f}", ln=True)
    pdf.ln(4)

    pdf.set_font("Arial", "B", 7)
    pdf.cell(35, 7, "EXP", 1)
    pdf.cell(45, 7, "PROVEEDOR", 1)
    pdf.cell(30, 7, "AREA", 1)
    pdf.cell(25, 7, "ESTADO", 1)
    pdf.cell(25, 7, "FECHA", 1)
    pdf.cell(30, 7, "TOTAL", 1, ln=True)

    pdf.set_font("Arial", "", 6)
    for _, row in df.iterrows():
        pdf.cell(35, 6, texto_limpio(str(row.get("expediente", "")))[:18], 1)
        pdf.cell(45, 6, texto_limpio(str(row.get("proveedor", "")))[:25], 1)
        pdf.cell(30, 6, texto_limpio(str(row.get("area", "")))[:15], 1)
        pdf.cell(25, 6, texto_limpio(str(row.get("estado", "")))[:15], 1)
        pdf.cell(25, 6, texto_limpio(str(row.get("fecha_factura", "")))[:10], 1)
        pdf.cell(30, 6, f"${float(row.get('total', 0) or 0):,.2f}", 1, ln=True)

    output.write(pdf.output(dest="S").encode("latin-1", errors="ignore"))
    output.seek(0)
    return output

# ============================================================
# ENCABEZADO
# ============================================================
st.markdown('''
<div class="header-card">
<h1>📄 Sistema Integral de Facturas DIF</h1>
<p>Adquisiciones · Contabilidad · Inventarios · Expediente Digital</p>
</div>
''', unsafe_allow_html=True)

st.sidebar.success(f"Usuario: {st.session_state.usuario} | Rol: {st.session_state.rol}")
if st.sidebar.button("Cerrar sesion"):
    st.session_state.logueado = False
    st.session_state.usuario = ""
    st.session_state.rol = ""
    st.rerun()

menu = st.sidebar.radio(
    "Menú",
    [
        "🏠 Inicio",
        "📤 Subir factura",
        "🔎 Buscar factura",
        "📁 Expediente digital",
        "📊 Dashboard",
        "🏢 Proveedores",
        "📋 Reportes PDF",
        "🛒 Adquisiciones",
        "💰 Contabilidad",
        "📦 Inventarios",
        "⚙️ Administración"
    ]
)

df = leer_facturas()
proveedores_df = leer_proveedores()

# ============================================================
# INICIO
# ============================================================
if menu == "🏠 Inicio":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Resumen general")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Facturas registradas", len(df))
    c2.metric("Total general", f"${df['total'].sum():,.2f}" if not df.empty else "$0.00")
    c3.metric("Proveedores", df["proveedor"].nunique() if not df.empty else 0)
    c4.metric("Pendientes", len(df[df["estado"].isin(["Capturada", "En revision"])]) if not df.empty and "estado" in df.columns else 0)
    st.markdown("</div>", unsafe_allow_html=True)

    st.subheader("Últimas facturas")
    if df.empty:
        st.warning("Todavía no hay facturas registradas.")
    else:
        st.dataframe(df[["id", "expediente", "area", "estado", "proveedor", "folio", "uuid", "fecha_factura", "total"]].head(20), use_container_width=True)

# ============================================================
# SUBIR FACTURA
# ============================================================
elif menu == "📤 Subir factura":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Subir factura PDF + XML")

    col_a, col_b = st.columns(2)
    with col_a:
        area = st.selectbox("Área responsable", AREAS)
    with col_b:
        estado = st.selectbox("Estado inicial", ESTADOS, index=0)

    pdf_file = st.file_uploader("Factura en PDF", type=["pdf"])
    xml_file = st.file_uploader("Factura en XML", type=["xml"])

    st.markdown("### Documentos opcionales del expediente")
    req_file = st.file_uploader("Requisición", type=["pdf", "jpg", "jpeg", "png"])
    cot_file = st.file_uploader("Cotización", type=["pdf", "jpg", "jpeg", "png"])
    evid_file = st.file_uploader("Evidencia / recibido", type=["pdf", "jpg", "jpeg", "png"])

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

        if st.button("💾 Guardar expediente digital"):
            if not pdf_file:
                st.error("Falta subir el PDF.")
            elif not datos["uuid"]:
                st.error("El XML no tiene UUID. Revisa que sea CFDI válido.")
            else:
                nombre_base = datos["uuid"]
                pdf_path = guardar_archivo(pdf_file, PDF_DIR, f"{nombre_base}.pdf")
                xml_path = guardar_archivo(xml_file, XML_DIR, f"{nombre_base}.xml")
                req_path = guardar_archivo(req_file, REQ_DIR, f"{nombre_base}_requisicion_{req_file.name}" if req_file else "")
                cot_path = guardar_archivo(cot_file, COT_DIR, f"{nombre_base}_cotizacion_{cot_file.name}" if cot_file else "")
                evid_path = guardar_archivo(evid_file, EVID_DIR, f"{nombre_base}_evidencia_{evid_file.name}" if evid_file else "")

                expediente = insertar_factura(datos, area, estado, pdf_path, xml_path, req_path, cot_path, evid_path, observaciones)
                st.success(f"Factura guardada correctamente en expediente {expediente}.")
                st.rerun()
    else:
        st.info("Primero sube el XML para leer los datos automáticamente.")

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# BUSCAR FACTURA
# ============================================================
elif menu == "🔎 Buscar factura":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Buscar factura")

    col1, col2, col3 = st.columns(3)
    with col1:
        texto = st.text_input("Buscar por proveedor, RFC, folio, UUID, concepto o expediente")
    with col2:
        area = st.selectbox("Área", ["Todas"] + AREAS)
    with col3:
        estado = st.selectbox("Estado", ["Todos"] + ESTADOS)

    resultado = filtrar_facturas(df, texto=texto, area=area, estado=estado)
    st.write(f"Resultados encontrados: **{len(resultado)}**")

    if resultado.empty:
        st.warning("No se encontraron facturas.")
    else:
        st.dataframe(resultado[["id", "expediente", "area", "estado", "proveedor", "rfc_proveedor", "folio", "uuid", "fecha_factura", "subtotal", "iva", "total"]], use_container_width=True)

        id_sel = st.selectbox("Selecciona una factura", resultado["id"].tolist())
        factura = resultado[resultado["id"] == id_sel].iloc[0]

        st.markdown("### Detalle")
        c1, c2, c3 = st.columns(3)
        c1.write(f"**Expediente:** {factura.get('expediente','')}")
        c2.write(f"**Proveedor:** {factura['proveedor']}")
        c3.write(f"**Total:** ${factura['total']:,.2f}")
        st.write(f"**UUID:** {factura['uuid']}")
        st.text_area("Conceptos", value=str(factura["conceptos"]), height=150, disabled=True)

        st.markdown("### Cambiar estado")
        nuevo_estado = st.selectbox("Nuevo estado", ESTADOS, index=ESTADOS.index(factura["estado"]) if factura["estado"] in ESTADOS else 0)
        if st.button("Actualizar estado"):
            actualizar_estado_factura(id_sel, nuevo_estado)
            st.success("Estado actualizado.")
            st.rerun()

        st.markdown("### Descargar documentos")
        col1, col2, col3, col4, col5 = st.columns(5)
        documentos = [
            ("📄 PDF", "pdf_path", "application/pdf"),
            ("🧾 XML", "xml_path", "text/xml"),
            ("📋 Requisición", "requisicion_path", "application/octet-stream"),
            ("💰 Cotización", "cotizacion_path", "application/octet-stream"),
            ("📷 Evidencia", "evidencia_path", "application/octet-stream"),
        ]
        cols = [col1, col2, col3, col4, col5]
        for col, (label, campo, mime) in zip(cols, documentos):
            with col:
                data = descargar_archivo(factura.get(campo, ""))
                if data:
                    st.download_button(label, data=data, file_name=os.path.basename(factura.get(campo, "")), mime=mime)
                else:
                    st.caption(f"Sin {label}")

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# EXPEDIENTE DIGITAL
# ============================================================
elif menu == "📁 Expediente digital":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Expediente digital por factura")

    if df.empty:
        st.warning("Todavía no hay expedientes.")
    else:
        opciones = (df["expediente"].fillna("") + " | " + df["proveedor"].fillna("") + " | $" + df["total"].fillna(0).astype(float).map("{:,.2f}".format)).tolist()
        seleccionado = st.selectbox("Selecciona expediente", opciones)
        idx = opciones.index(seleccionado)
        factura = df.iloc[idx]

        st.markdown(f"### {factura.get('expediente','')}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Área", factura.get("area", ""))
        c2.metric("Estado", factura.get("estado", ""))
        c3.metric("Proveedor", str(factura.get("proveedor", ""))[:20])
        c4.metric("Total", f"${float(factura.get('total', 0) or 0):,.2f}")

        st.write(f"**UUID:** {factura.get('uuid','')}")
        st.write(f"**Fecha factura:** {factura.get('fecha_factura','')}")
        st.text_area("Conceptos", value=str(factura.get("conceptos", "")), height=160, disabled=True)

        st.markdown("### Documentos del expediente")
        docs = {
            "Factura PDF": factura.get("pdf_path", ""),
            "XML": factura.get("xml_path", ""),
            "Requisición": factura.get("requisicion_path", ""),
            "Cotización": factura.get("cotizacion_path", ""),
            "Evidencia": factura.get("evidencia_path", ""),
        }
        for nombre_doc, ruta in docs.items():
            if ruta and os.path.exists(ruta):
                st.success(f"✅ {nombre_doc}: {os.path.basename(ruta)}")
            else:
                st.warning(f"⚠️ Falta {nombre_doc}")

        st.download_button(
            "📦 Descargar expediente completo ZIP",
            data=crear_zip_facturas(pd.DataFrame([factura])),
            file_name=f"{factura.get('expediente','expediente')}.zip",
            mime="application/zip"
        )

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# DASHBOARD
# ============================================================
elif menu == "📊 Dashboard":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Dashboard ejecutivo")

    if df.empty:
        st.warning("Todavía no hay facturas registradas.")
    else:
        df_temp = df.copy()
        df_temp["fecha_dt"] = pd.to_datetime(df_temp["fecha_factura"], errors="coerce")
        hoy = datetime.now()
        df_mes = df_temp[(df_temp["fecha_dt"].dt.month == hoy.month) & (df_temp["fecha_dt"].dt.year == hoy.year)]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total general", f"${df_temp['total'].sum():,.2f}")
        c2.metric("Total del mes", f"${df_mes['total'].sum():,.2f}")
        c3.metric("Facturas", len(df_temp))
        c4.metric("Proveedores", df_temp["proveedor"].nunique())

        st.markdown("### Gasto por área")
        area_res = df_temp.groupby("area", as_index=False)["total"].sum()
        st.dataframe(area_res, use_container_width=True)
        st.bar_chart(area_res.set_index("area"))

        st.markdown("### Top 10 proveedores")
        top = df_temp.groupby("proveedor", as_index=False)["total"].sum().sort_values("total", ascending=False).head(10)
        st.dataframe(top, use_container_width=True)
        st.bar_chart(top.set_index("proveedor"))

        st.markdown("### Facturas por estado")
        est = df_temp["estado"].value_counts().reset_index()
        est.columns = ["Estado", "Total"]
        st.dataframe(est, use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# PROVEEDORES
# ============================================================
elif menu == "🏢 Proveedores":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Catálogo de proveedores")

    if proveedores_df.empty:
        st.warning("Todavía no hay proveedores registrados. Se agregarán automáticamente al subir facturas.")
    else:
        compras = df.groupby("proveedor", as_index=False)["total"].sum() if not df.empty else pd.DataFrame(columns=["proveedor", "total"])
        prov = proveedores_df.merge(compras, left_on="nombre", right_on="proveedor", how="left")
        prov["total"] = prov["total"].fillna(0)

        st.dataframe(prov[["id", "nombre", "rfc", "telefono", "correo", "contacto", "giro", "total"]], use_container_width=True)

        id_prov = st.selectbox("Selecciona proveedor para completar datos", prov["id"].tolist())
        p = prov[prov["id"] == id_prov].iloc[0]

        with st.form("form_proveedor"):
            telefono = st.text_input("Teléfono", value=str(p.get("telefono", "") or ""))
            correo = st.text_input("Correo", value=str(p.get("correo", "") or ""))
            direccion = st.text_area("Dirección", value=str(p.get("direccion", "") or ""))
            contacto = st.text_input("Contacto", value=str(p.get("contacto", "") or ""))
            giro = st.text_input("Giro", value=str(p.get("giro", "") or ""))
            guardar = st.form_submit_button("💾 Guardar proveedor")

        if guardar:
            actualizar_proveedor(id_prov, telefono, correo, direccion, contacto, giro)
            st.success("Proveedor actualizado.")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# REPORTES PDF
# ============================================================
elif menu == "📋 Reportes PDF":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Reportes institucionales")

    if df.empty:
        st.warning("Todavía no hay facturas.")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            area = st.selectbox("Área", ["Todas"] + AREAS)
        with col2:
            estado = st.selectbox("Estado", ["Todos"] + ESTADOS)
        with col3:
            proveedor = st.selectbox("Proveedor", ["Todos"] + sorted(df["proveedor"].dropna().unique().tolist()))

        rep = df.copy()
        if area != "Todas":
            rep = rep[rep["area"] == area]
        if estado != "Todos":
            rep = rep[rep["estado"] == estado]
        if proveedor != "Todos":
            rep = rep[rep["proveedor"] == proveedor]

        st.metric("Total filtrado", f"${rep['total'].sum():,.2f}")
        st.metric("Facturas filtradas", len(rep))
        st.dataframe(rep[["expediente", "area", "estado", "proveedor", "fecha_factura", "total"]], use_container_width=True)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.download_button("📄 Descargar PDF", data=crear_pdf_reporte(rep), file_name="reporte_facturas_dif.pdf", mime="application/pdf")
        with c2:
            st.download_button("📥 Descargar Excel", data=crear_excel(rep), file_name="reporte_facturas_dif.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with c3:
            st.download_button("📦 Descargar expedientes ZIP", data=crear_zip_facturas(rep), file_name="expedientes_facturas.zip", mime="application/zip")

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# AREAS
# ============================================================
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
        st.dataframe(area_df[["id", "expediente", "estado", "proveedor", "folio", "uuid", "fecha_factura", "total"]], use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# ADMINISTRACION
# ============================================================
elif menu == "⚙️ Administración":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Administración de facturas")

    if st.session_state.rol not in ["Administrador"]:
        st.warning("Solo el administrador puede eliminar facturas.")
    elif df.empty:
        st.warning("No hay facturas registradas.")
    else:
        st.dataframe(df, use_container_width=True)

        id_sel = st.selectbox("Selecciona ID para eliminar", df["id"].tolist())
        if st.button("🗑️ Eliminar factura seleccionada"):
            con = conectar()
            cur = con.cursor()
            factura = df[df["id"] == id_sel].iloc[0]

            for campo in ["pdf_path", "xml_path", "requisicion_path", "cotizacion_path", "evidencia_path"]:
                ruta = factura.get(campo, "")
                if ruta and os.path.exists(ruta):
                    os.remove(ruta)

            cur.execute("DELETE FROM facturas WHERE id = ?", (int(id_sel),))
            con.commit()
            con.close()
            st.success("Factura eliminada.")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
