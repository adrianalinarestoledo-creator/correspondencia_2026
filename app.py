from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, or_
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO
import pandas as pd
import pdfkit
import re
import os
import uuid
from openpyxl import load_workbook  # si ya no lo usas, también lo puedes borrar

app = Flask(__name__)

# 🔐 Clave segura para sesiones
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CLAVE_LOCAL_SUPER_SEGURA_2026_!_SOAPAP_987654321"
)

# 🔗 Base de datos
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
db = SQLAlchemy(app)

# --------------------------
#   FUNCIONES DE CÁLCULO
# --------------------------

FERIADOS = []

def sumar_dias_habiles(fecha, dias):
    contador = 0
    resultado = fecha
    while contador < dias:
        resultado += timedelta(days=1)
        if resultado.weekday() < 5 and resultado not in FERIADOS:
            contador += 1
    return resultado

def dias_habiles(fecha_inicio, fecha_fin):
    dias = 0
    actual = fecha_inicio
    while actual <= fecha_fin:
        if actual.weekday() < 5 and actual not in FERIADOS:
            dias += 1
        actual += timedelta(days=1)
    return dias

# --------------------------
#   MODELOS
# --------------------------

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    rol = db.Column(db.String(50), nullable=False)
    gerencia = db.Column(db.String(50))
    activo = db.Column(db.Boolean, default=True)
    debe_cambiar_password = db.Column(db.Boolean, default=False)
    ultimo_cambio_password = db.Column(db.DateTime)
    creado_por = db.Column(db.String(50))
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    modificado_por = db.Column(db.String(50))
    modificado_en = db.Column(db.DateTime)

    def set_password(self, password, quien=None):
        self.password_hash = generate_password_hash(password)
        self.ultimo_cambio_password = datetime.utcnow()
        self.debe_cambiar_password = False
        self.modificado_por = quien
        self.modificado_en = datetime.utcnow()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Oficio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(50))
    numero_oficio = db.Column(db.String(100))
    fecha = db.Column(db.String(20))
    hora = db.Column(db.String(20))
    numero_expediente = db.Column(db.String(100))
    quien_emite = db.Column(db.String(200))
    con_copia_para = db.Column(db.String(200))
    anexos = db.Column(db.String(200))
    gerencia_turnada = db.Column(db.String(50))
    asunto = db.Column(db.String(500))
    prioridad = db.Column(db.String(20))
    termino = db.Column(db.Integer)
    fecha_limite = db.Column(db.String(20))
    responsable1 = db.Column(db.String(200))
    responsable2 = db.Column(db.String(200))
    nis = db.Column(db.String(50))
    estatus = db.Column(db.String(50))
    observaciones = db.Column(db.Text)
    fecha_atencion = db.Column(db.String(20))
    oficio_respuesta = db.Column(db.String(200))
    fecha_acuse = db.Column(db.String(20))
    dias_atencion = db.Column(db.Integer)

# --------------------------
#   INICIALIZAR BD
# --------------------------

with app.app_context():
    db.create_all()

# --------------------------
#   LOGIN
# --------------------------

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]

        user = Usuario.query.filter_by(usuario=usuario).first()

        if user and user.password_hash and check_password_hash(user.password_hash, password):

            # Datos base de sesión
            session["usuario"] = user.usuario
            session["rol"] = user.rol

            # Asignar gerencia solo a usuarios de gerencia
            if user.rol not in ["admin", "superadmin"]:
                session["gerencia"] = user.gerencia
            else:
                session["gerencia"] = None

            # Año actual para el menú
            session["anio"] = datetime.now().year

            return redirect(url_for("lista"))

        return render_template("login.html", error="Usuario o contraseña incorrectos")

    return render_template("login.html")

# --------------------------
#   LOGOUT
# --------------------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/usuarios")
def usuarios():
    if session.get("rol") not in ["admin", "superadmin"]:
        return render_template("bloqueado.html", oficio=None)

    lista_usuarios = Usuario.query.all()
    return render_template("usuarios.html", usuarios=lista_usuarios)
    
# --------------------------
#   REGISTRO DE OFICIOS (ADMIN)
# --------------------------

@app.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if "rol" not in session or session["rol"] != "admin":
        return "Solo el admin puede registrar oficios"

    # --------------------------
    #   GET → Solo muestra el formulario
    # --------------------------
    if request.method == "GET":
        return render_template("nuevo.html")

    # --------------------------
    #   POST → Genera folio real y guarda
    # --------------------------
    if request.method == "POST":

        # Generar folio real en el momento del guardado
        ultimo = Oficio.query.filter(
            Oficio.numero.like("SOAPAP-%")
        ).order_by(Oficio.id.desc()).first()

        if ultimo:
            try:
                num = int(ultimo.numero.split("-")[-1])
            except:
                num = 0
            nuevo_num = num + 1
            folio = f"SOAPAP-{nuevo_num:05d}"
        else:
            folio = "SOAPAP-00001"

        numero_oficio = request.form["numero_oficio"]
        fecha = datetime.strptime(request.form["fecha"], "%Y-%m-%d")
        hora = request.form["hora"]
        numero_expediente = request.form["numero_expediente"]
        quien_emite = request.form["quien_emite"]
        con_copia_para = request.form["con_copia_para"]
        anexos = request.form["anexos"]
        gerencia_turnada = request.form["gerencia_turnada"]
        asunto = request.form["asunto"]
        prioridad = request.form["prioridad"]
        responsable1 = request.form["responsable1"]
        responsable2 = request.form["responsable2"]
        nis = request.form["nis"]

        # Cálculo de fecha límite
        if prioridad == "Urgente":
            fecha_limite = sumar_dias_habiles(fecha, 1)
        elif prioridad == "Alta":
            fecha_limite = sumar_dias_habiles(fecha, 3)
        elif prioridad == "Media":
            fecha_limite = sumar_dias_habiles(fecha, 15)
        elif prioridad == "Baja":
            fecha_limite = sumar_dias_habiles(fecha, 30)
        else:
            fecha_limite = None

        fecha_limite_str = fecha_limite.strftime("%Y-%m-%d") if fecha_limite else ""

        nuevo = Oficio(
            numero=folio,
            numero_oficio=numero_oficio,
            fecha=fecha.strftime("%Y-%m-%d"),
            hora=hora,
            numero_expediente=numero_expediente,
            quien_emite=quien_emite,
            con_copia_para=con_copia_para,
            anexos=anexos,
            gerencia_turnada=gerencia_turnada,
            asunto=asunto,
            prioridad=prioridad,
            termino=0,
            fecha_limite=fecha_limite_str,
            responsable1=responsable1,
            responsable2=responsable2,
            nis=nis,
            estatus="Pendiente"
        )

        db.session.add(nuevo)
        db.session.commit()

        return redirect(url_for("lista"))
# --------------------------
#   EDITAR OFICIO (SOLO ADMIN)
# --------------------------

@app.route("/editar/<int:id>", methods=["GET", "POST"])
def editar(id):
    if "rol" not in session or session["rol"] != "admin":
        return "No tienes permiso para modificar este oficio"

    oficio = Oficio.query.get_or_404(id)

    # GET → mostrar formulario
    if request.method == "GET":
        return render_template("editar.html", oficio=oficio)

    # POST → guardar cambios
    if request.method == "POST":
        oficio.estatus = request.form["estatus"]
        oficio.gerencia_turnada = request.form["gerencia_turnada"]
        oficio.responsable1 = request.form["responsable1"]
        oficio.responsable2 = request.form["responsable2"]
        oficio.asunto = request.form["asunto"]
        oficio.nis = request.form["nis"]

        db.session.commit()
        return redirect(url_for("lista"))

# --------------------------
#   LISTA DE OFICIOS (FINAL)
# --------------------------

@app.route("/lista")
def lista():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    q = request.args.get("q", "").strip()
    gerencia_filtro = request.args.get("gerencia", "")
    estatus_filtro = request.args.get("estatus", "")
    fecha_ini = request.args.get("fecha_ini", "")
    fecha_fin = request.args.get("fecha_fin", "")

    consulta = Oficio.query

    # ⭐ Si NO es admin ni superadmin → solo ve su gerencia
    if session.get("rol") not in ["admin", "superadmin"]:
        consulta = consulta.filter_by(gerencia_turnada=session["gerencia"])

    # ⭐ Filtro de búsqueda general
    if q:
        consulta = consulta.filter(
            (Oficio.asunto.ilike(f"%{q}%")) |
            (Oficio.numero.ilike(f"%{q}%")) |
            (Oficio.numero_oficio.ilike(f"%{q}%"))
        )

    # ⭐ Filtro por gerencia (solo admin/superadmin)
    if gerencia_filtro and session.get("rol") in ["admin", "superadmin"]:
        consulta = consulta.filter_by(gerencia_turnada=gerencia_filtro)

    # ⭐ Filtro por estatus
    if estatus_filtro:
        consulta = consulta.filter_by(estatus=estatus_filtro)

    # ⭐ Filtro por fecha inicial
    if fecha_ini:
        consulta = consulta.filter(Oficio.fecha >= fecha_ini)

    # ⭐ Filtro por fecha final
    if fecha_fin:
        consulta = consulta.filter(Oficio.fecha <= fecha_fin)

    # ⭐ Ordenar por ID DESC
    consulta = consulta.order_by(Oficio.id.desc())

    # ⭐ PAGINACIÓN REAL
    paginacion = consulta.paginate(page=page, per_page=per_page)

    return render_template(
        "lista.html",
        oficios=paginacion.items,
        paginacion=paginacion,
        page=page,
        per_page=per_page,
        q=q,
        gerencia_filtro=gerencia_filtro,
        estatus_filtro=estatus_filtro,
        fecha_ini=fecha_ini,
        fecha_fin=fecha_fin
    )

# --------------------------
#   EXPORTAR A EXCEL (CON FILTROS)
# --------------------------
from sqlalchemy import cast, Date
import pandas as pd

@app.route("/exportar_excel")
def exportar_excel():
    if "gerencia" not in session:
        return redirect(url_for("login"))

    q = request.args.get("q", "").strip()
    gerencia_filtro = request.args.get("gerencia", "")
    estatus_filtro = request.args.get("estatus", "")
    fecha_ini = request.args.get("fecha_ini", "")
    fecha_fin = request.args.get("fecha_fin", "")

    consulta = Oficio.query

    # ⭐ Gerencias solo ven lo suyo
    if session.get("rol") not in ["admin", "superadmin"]:
        consulta = consulta.filter_by(gerencia_turnada=session["gerencia"])

    # ⭐ Filtro búsqueda
    if q:
        consulta = consulta.filter(
            (Oficio.asunto.ilike(f"%{q}%")) |
            (Oficio.numero.ilike(f"%{q}%")) |
            (Oficio.numero_oficio.ilike(f"%{q}%"))
        )

    # ⭐ Filtro gerencia
    if gerencia_filtro and session.get("rol") in ["admin", "superadmin"]:
        consulta = consulta.filter_by(gerencia_turnada=gerencia_filtro)

    # ⭐ Filtro estatus
    if estatus_filtro:
        consulta = consulta.filter_by(estatus=estatus_filtro)

    # ⭐ Filtro fecha
    if fecha_ini:
        consulta = consulta.filter(cast(Oficio.fecha, Date) >= fecha_ini)

    if fecha_fin:
        consulta = consulta.filter(cast(Oficio.fecha, Date) <= fecha_fin)

    consulta = consulta.order_by(Oficio.id.desc())
    oficios = consulta.all()

    # ⭐ Convertir a DataFrame
    data = [{
        "Folio SOAPAP": o.numero,
        "Número de oficio externo": o.numero_oficio,
        "Fecha": o.fecha,
        "Hora": o.hora,
        "Número expediente": o.numero_expediente,
        "Quien emite": o.quien_emite,
        "Gerencia": o.gerencia_turnada,
        "Asunto": o.asunto,
        "Prioridad": o.prioridad,
        "Fecha límite": o.fecha_limite,
        "Responsable Director": o.responsable1,
        "Responsable Gerente": o.responsable2,
        "NIS": o.nis,
        "Estatus": o.estatus,
        "Fecha atención": o.fecha_atencion,
        "Días atención": o.dias_atencion,
        "Oficio respuesta": o.oficio_respuesta,
        "Fecha acuse": o.fecha_acuse,
        "Observaciones": o.observaciones
    } for o in oficios]

    df = pd.DataFrame(data)

    # ⭐ Crear archivo Excel en memoria
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Oficios")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="oficios_filtrados.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# --------------------------
#   EXPORTAR A PDF (CON FILTROS)
# --------------------------
from sqlalchemy import cast, Date

@app.route("/exportar_pdf")
def exportar_pdf():
    if "gerencia" not in session:
        return redirect(url_for("login"))

    q = request.args.get("q", "").strip()
    gerencia_filtro = request.args.get("gerencia", "")
    estatus_filtro = request.args.get("estatus", "")
    fecha_ini = request.args.get("fecha_ini", "")
    fecha_fin = request.args.get("fecha_fin", "")

    consulta = Oficio.query

    # ⭐ Gerencias solo ven lo suyo
    if session.get("rol") not in ["admin", "superadmin"]:
        consulta = consulta.filter_by(gerencia_turnada=session["gerencia"])

    # ⭐ Filtro búsqueda
    if q:
        consulta = consulta.filter(
            (Oficio.asunto.ilike(f"%{q}%")) |
            (Oficio.numero.ilike(f"%{q}%")) |
            (Oficio.numero_oficio.ilike(f"%{q}%"))
        )

    # ⭐ Filtro gerencia
    if gerencia_filtro and session.get("rol") in ["admin", "superadmin"]:
        consulta = consulta.filter_by(gerencia_turnada=gerencia_filtro)

    # ⭐ Filtro estatus
    if estatus_filtro:
        consulta = consulta.filter_by(estatus=estatus_filtro)

    # ⭐ Filtro fecha (CORRECTO)
    if fecha_ini:
        consulta = consulta.filter(cast(Oficio.fecha, Date) >= fecha_ini)

    if fecha_fin:
        consulta = consulta.filter(cast(Oficio.fecha, Date) <= fecha_fin)

    # ⭐ Ordenar y obtener resultados
    consulta = consulta.order_by(Oficio.id.desc())
    oficios = consulta.all()

    # ⭐ Preparar datos para la plantilla PDF
    data = []
    for o in oficios:
        data.append({
            "Folio SOAPAP": o.numero,
            "Número de oficio externo": o.numero_oficio,
            "Fecha": o.fecha,
            "Hora": o.hora,
            "Número expediente": o.numero_expediente,
            "Quien emite": o.quien_emite,
            "Gerencia": o.gerencia_turnada,
            "Asunto": o.asunto,
            "Prioridad": o.prioridad,
            "Fecha límite": o.fecha_limite,
            "Responsable Director": o.responsable1,
            "Responsable Gerente": o.responsable2,
            "NIS": o.nis,
            "Estatus": o.estatus,
            "Fecha atención": o.fecha_atencion,
            "Días atención": o.dias_atencion,
            "Oficio respuesta": o.oficio_respuesta,
            "Fecha acuse": o.fecha_acuse,
            "Observaciones": o.observaciones
        })

    # ⭐ Renderizar HTML
    rendered = render_template("oficios_pdf.html", oficios=data)

    # ⭐ Opciones PDF
    options = {
        "page-size": "Letter",
        "orientation": "Portrait",
        "encoding": "UTF-8",
        "margin-top": "0.5in",
        "margin-bottom": "0.5in",
        "margin-left": "0.3in",
        "margin-right": "0.3in",
        "enable-local-file-access": None
    }

    pdf = pdfkit.from_string(rendered, False, options=options)

    return send_file(
        BytesIO(pdf),
        as_attachment=True,
        download_name="oficios_filtrados.pdf",
        mimetype="application/pdf"
    )

# --------------------------
#   VER OFICIO
# --------------------------

@app.route("/ver/<int:id>")
def ver(id):
    oficio = Oficio.query.get_or_404(id)
    return render_template("ver.html", oficio=oficio)

# --------------------------
#   ATENDER OFICIO
# --------------------------

@app.route("/atender/<int:id>", methods=["POST"])
def atender(id):
    oficio = Oficio.query.get_or_404(id)

    oficio.estatus = "Atendido"
    oficio.fecha_atencion = datetime.now().strftime("%Y-%m-%d")

    fecha_ingreso = datetime.strptime(oficio.fecha, "%Y-%m-%d")
    fecha_atencion = datetime.now()
    oficio.dias_atencion = (fecha_atencion - fecha_ingreso).days

    db.session.commit()

    return redirect(url_for("lista"))

# --------------------------
#   RESPONDER OFICIO (FINAL)
# --------------------------
@app.route("/responder/<int:id>", methods=["GET", "POST"])
def responder(id):
    oficio = Oficio.query.get_or_404(id)

    rol = session.get("rol")
    gerencia = session.get("gerencia")

    # ============================
    # VALIDACIÓN DE PERMISOS
    # ============================

    # 1. Si NO es admin → validar que la gerencia coincida
    if rol not in ["admin", "superadmin", "admin_limited"]:

        # Caso especial GAL
        if gerencia == "GAL":
            if oficio.gerencia_turnada not in ["GAL", "GAL-Despacho"]:
                return "Acceso no autorizado", 403

        # Caso general
        elif oficio.gerencia_turnada != gerencia:
            return "Acceso no autorizado", 403

        # 2. Si el oficio ya está solucionado → NO permitir editar
        if oficio.estatus == "Solucionado":
            return render_template("bloqueado.html", oficio=oficio)

    # ============================
    # PROCESAR RESPUESTA
    # ============================
    if request.method == "POST":

        oficio.estatus = request.form.get("estatus")
        oficio.observaciones = request.form.get("observaciones")
        oficio.fecha_atencion = request.form.get("fecha_atencion")
        oficio.oficio_respuesta = request.form.get("oficio_respuesta")
        oficio.fecha_acuse = request.form.get("fecha_acuse")

        # ⭐ NUEVO: GUARDAR NIS
        oficio.nis = request.form.get("nis")

        # ============================
        # CÁLCULO DE DÍAS DE ATENCIÓN
        # ============================
        if oficio.fecha and oficio.fecha_atencion:
            try:
                f1 = datetime.strptime(oficio.fecha, "%Y-%m-%d")
                f2 = datetime.strptime(oficio.fecha_atencion, "%Y-%m-%d")
                oficio.dias_atencion = (f2 - f1).days
            except:
                oficio.dias_atencion = None

        db.session.commit()
        flash("Respuesta guardada correctamente", "success")
        return redirect(url_for("lista"))

    return render_template("responder.html", oficio=oficio)

# --------------------------
#   IMPORTAR EXCEL (SUBIR Y VISTA PREVIA)
# --------------------------

@app.route("/importar_excel", methods=["GET", "POST"])
def importar_excel():
    if request.method == "POST":
        archivo = request.files["archivo"]

        # Encabezados reales están en la primera fila
        df = pd.read_excel(archivo, header=0)

        # Limpiar encabezados
        df.columns = df.columns.str.strip()

        # Eliminar filas totalmente vacías
        df = df.dropna(how="all")

        # Convertir todo a string
        df = df.astype(str)

        # Eliminar filas sin FOLIO
        if "FOLIO" in df.columns:
            df = df[df["FOLIO"].str.strip().notna()]
            df = df[df["FOLIO"].str.strip() != ""]
            df = df[df["FOLIO"].str.lower() != "nan"]

        preview = df.to_dict(orient="records")
        columnas = df.columns.tolist()

        return render_template(
            "importar_excel_preview.html",
            preview=preview,
            columnas=columnas
        )

    return render_template("importar_excel.html")

  
# --------------------------
#   FUNCIÓN PARA LIMPIAR FECHAS
# --------------------------

def limpiar_fecha(valor):
    if not valor or valor in ["nan", "None", ""]:
        return None
    valor = str(valor).strip()
    if " " in valor:
        valor = valor.split(" ")[0]
    return valor[:20]
# --------------------------
#   IMPORTAR EXCEL GUARDAR (CORRECTA)
# --------------------------

@app.route("/importar_excel_guardar", methods=["POST"])
def importar_excel_guardar():
    datos = request.json

    if not datos:
        return jsonify({"error": "No se recibieron datos"}), 400

    # Borrar tabla antes de importar
    db.session.query(Oficio).delete()
    db.session.commit()

    for fila in datos:

        # Convertir números
        termino_val = fila.get("TÉRMINO")
        dias_val = fila.get("DÍAS DE ATENCIÓN")

        try:
            termino_val = int(float(termino_val)) if termino_val not in ["", "None", "nan"] else None
        except:
            termino_val = None

        try:
            dias_val = int(float(dias_val)) if dias_val not in ["", "None", "nan"] else None
        except:
            dias_val = None

        # Limpiar fechas
        fecha_ingreso = limpiar_fecha(fila.get("FECHA INGRESO"))
        fecha_emision = limpiar_fecha(fila.get("FECHA DE EMISIÓN"))
        fecha_limite = limpiar_fecha(fila.get("FECHA LÍMITE DE ATENCIÓN"))
        fecha_atencion = limpiar_fecha(fila.get("FECHA ATENCIÓN"))
        fecha_acuse = limpiar_fecha(fila.get("FECHA ACUSE DE RESPUESTA"))

        # Semáforo → Estatus
        semaforo = fila.get("SEMAFORO")
        if semaforo and str(semaforo).strip().lower() == "finalizado":
            estatus_val = "Solucionado"
        else:
            estatus_val = fila.get("ESTATUS")

        # Crear registro
        nuevo = Oficio(
            numero=fila.get("FOLIO"),
            numero_oficio=fila.get("NUMERO DE OFICIO"),
            fecha=fecha_ingreso,
            hora=fila.get("HORA"),
            numero_expediente=fila.get("No. EXP."),
            quien_emite=fila.get("QUIEN LO EMITE"),
            con_copia_para=fila.get("CON COPIA PARA"),
            anexos=fila.get("ANEXOS"),
            gerencia_turnada=fila.get("GERENCIA"),
            asunto=fila.get("ASUNTO"),
            prioridad=fila.get("PRIORIDAD"),
            termino=termino_val,
            fecha_limite=fecha_limite,
            responsable1=fila.get("RESPONSABLE 1"),
            responsable2=fila.get("RESPONSABLE"),
            nis=fila.get("NIS"),
            estatus=estatus_val,
            observaciones=fila.get("OBSERVACIONES"),
            fecha_atencion=fecha_atencion,
            oficio_respuesta=fila.get("OFICIO DE RESPUESTA"),
            fecha_acuse=fecha_acuse,
            dias_atencion=dias_val
        )

        db.session.add(nuevo)
        db.session.commit()

    return jsonify({"mensaje": "Importación completada"})
    
# --------------------------
#   DASHBOARD INSTITUCIONAL (CON FILTRO MENSUAL + MULTI GERENCIA)
# --------------------------
from sqlalchemy import func

@app.route("/dashboard")
def dashboard():

    # ============================
    # FILTROS
    # ============================
    anio = request.args.get("anio", session.get("anio"))
    mes = request.args.get("mes", "")
    gerencias_filtro = request.args.getlist("gerencia")  # ⭐ MULTI-GERENCIA
    estatus_filtro = request.args.get("estatus", "")
    prioridad_filtro = request.args.get("prioridad", "")

    consulta = Oficio.query

    # ============================
# FILTRO POR ROL
# ============================
rol = session.get("rol")
gerencia_usuario = session.get("gerencia")

# GERENCIAS → solo lo suyo
if rol not in ["admin", "superadmin"]:
    if not gerencia_usuario:
        return redirect(url_for("login"))  # Sesión inválida o incompleta
    consulta = consulta.filter_by(gerencia_turnada=gerencia_usuario)


    # ============================
    # FILTRO POR AÑO
    # ============================
    if anio:
        consulta = consulta.filter(func.substr(Oficio.fecha, 1, 4) == str(anio))

    # ============================
    # FILTRO POR MES
    # ============================
    if mes and mes != "00":
        consulta = consulta.filter(func.substr(Oficio.fecha, 6, 2) == mes)

    # ============================
    # FILTRO POR GERENCIAS (MÚLTIPLES)
    # ============================
    if gerencias_filtro:
        consulta = consulta.filter(Oficio.gerencia_turnada.in_(gerencias_filtro))

    # ============================
    # FILTRO POR ESTATUS
    # ============================
    if estatus_filtro:
        consulta = consulta.filter_by(estatus=estatus_filtro)

    # ============================
    # FILTRO POR PRIORIDAD
    # ============================
    if prioridad_filtro:
        consulta = consulta.filter_by(prioridad=prioridad_filtro)

    # ============================
    # OBTENER OFICIOS FILTRADOS
    # ============================
    oficios = consulta.all()

    # ============================
    # KPIs GENERALES
    # ============================
    total_recibidos = len(oficios)
    total_pendientes = sum(1 for o in oficios if o.estatus == "Pendiente")
    total_proceso = sum(1 for o in oficios if o.estatus == "En proceso")
    total_acuerdo = sum(1 for o in oficios if o.estatus == "En acuerdo")
    total_atendidos = sum(1 for o in oficios if o.estatus == "Solucionado")

    porcentaje_cumplimiento = (
        round((total_atendidos / total_recibidos) * 100, 2)
        if total_recibidos > 0 else 0
    )

    dias = [o.dias_atencion for o in oficios if o.dias_atencion]
    promedio_dias = round(sum(dias) / len(dias), 2) if dias else 0

    # ============================
    # TABLA POR GERENCIA
    # ============================
    gerencias = ["DG", "GAL", "GAL-Despacho", "GPSOI", "GSMA", "GSTS"]
    tabla_gerencias = []

    for g in gerencias:
        recibidos = len([o for o in oficios if o.gerencia_turnada == g])
        atendidos = len([o for o in oficios if o.gerencia_turnada == g and o.estatus == "Solucionado"])
        pendientes = len([o for o in oficios if o.gerencia_turnada == g and o.estatus == "Pendiente"])
        proceso = len([o for o in oficios if o.gerencia_turnada == g and o.estatus == "En proceso"])
        acuerdo = len([o for o in oficios if o.gerencia_turnada == g and o.estatus == "En acuerdo"])

        cumplimiento = round((atendidos / recibidos) * 100, 2) if recibidos > 0 else 0

        dias_g = [o.dias_atencion for o in oficios if o.gerencia_turnada == g and o.dias_atencion]
        promedio_dias_g = round(sum(dias_g) / len(dias_g), 2) if dias_g else 0

        tabla_gerencias.append({
            "gerencia": g,
            "recibidos": recibidos,
            "pendientes": pendientes,
            "proceso": proceso,
            "acuerdo": acuerdo,
            "atendidos": atendidos,
            "cumplimiento": cumplimiento,
            "promedio_dias": promedio_dias_g
        })

    # ============================
    # GRÁFICAS MENSUALES (SOLO SI ES ANUAL)
    # ============================
    meses_lista = ["01","02","03","04","05","06","07","08","09","10","11","12"]

    recibidos_mes = []
    atendidos_mes = []
    dias_promedio = []

    if not mes:  # Solo mostrar gráficas anuales si NO se selecciona mes
        for m in meses_lista:
            oficios_mes = [o for o in oficios if o.fecha and o.fecha[5:7] == m]

            recibidos_mes.append(len(oficios_mes))
            atendidos_mes.append(len([o for o in oficios_mes if o.estatus == "Solucionado"]))

            dias_m = [o.dias_atencion for o in oficios_mes if o.estatus == "Solucionado" and o.dias_atencion]
            dias_promedio.append(round(sum(dias_m) / len(dias_m), 2) if dias_m else 0)

    return render_template(
        "dashboard.html",
        total_recibidos=total_recibidos,
        total_pendientes=total_pendientes,
        total_proceso=total_proceso,
        total_acuerdo=total_acuerdo,
        total_atendidos=total_atendidos,
        porcentaje_cumplimiento=porcentaje_cumplimiento,
        promedio_dias=promedio_dias,
        tabla_gerencias=tabla_gerencias,
        meses=meses_lista,
        recibidos_mes=recibidos_mes,
        atendidos_mes=atendidos_mes,
        dias_promedio=dias_promedio,
        anio=anio,
        mes=mes,
        gerencias_filtro=gerencias_filtro,
        estatus_filtro=estatus_filtro,
        prioridad_filtro=prioridad_filtro
    )

# --------------------------
#   INICIO DEL SERVIDOR
# --------------------------

if __name__ == "__main__":
    app.run(debug=True)

