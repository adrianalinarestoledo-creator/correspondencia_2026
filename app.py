from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text   # ⭐ NECESARIO PARA TRUNCATE
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO
import pandas as pd
import pdfkit
import re
import os
from openpyxl import load_workbook   # ⭐ NECESARIO PARA IMPORTACIÓN STREAMING

app = Flask(__name__)

# 🔐 Clave segura para sesiones (local + Render)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CLAVE_LOCAL_SUPER_SEGURA_2026_!_SOAPAP_987654321"
)

# 🔗 Base de datos (Render usa DATABASE_URL)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")

db = SQLAlchemy(app)

# --------------------------
#   FUNCIONES DE CÁLCULO
# --------------------------

FERIADOS = []  # si luego quieres agregar días festivos, aquí van

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
    rol = db.Column(db.String(50), nullable=False)  # admin, admin_limited, gerencia

    # ⭐ Campo que existía en PostgreSQL pero faltaba en tu modelo
    gerencia = db.Column(db.String(50))

    # Controles empresariales
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

    # Datos del oficio
    numero = db.Column(db.String(50))            # Folio SOAPAP-00001
    numero_oficio = db.Column(db.String(100))
    fecha = db.Column(db.String(20))             # YYYY-MM-DD
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

    # Respuesta de gerencias
    estatus = db.Column(db.String(50))
    observaciones = db.Column(db.Text)
    fecha_atencion = db.Column(db.String(20))
    oficio_respuesta = db.Column(db.String(200))
    fecha_acuse = db.Column(db.String(20))

    # Campo calculado
    dias_atencion = db.Column(db.Integer)

# --------------------------
#   VALIDACIÓN DE PASSWORD
# --------------------------

def password_segura(pwd):
    reglas = [
        r".{8,}",          # mínimo 8 caracteres
        r"[A-Z]",          # al menos una mayúscula
        r"[a-z]",          # al menos una minúscula
        r"[0-9]",          # al menos un número
        r"[^A-Za-z0-9]"    # al menos un símbolo
    ]
    return all(re.search(r, pwd) for r in reglas)

# --------------------------
#   INICIALIZAR BD Y USUARIOS
# --------------------------

with app.app_context():
    db.create_all()

    usuarios_iniciales = [
        ("admin", "Admin_2026!Segura", "admin"),
        ("GAL", "Gal_2026#Firme", "gerencia"),
        ("GAL-Despacho", "Despacho_2026$Clave", "gerencia"),
        ("GAF", "Gaf_2026*Control", "gerencia"),
        ("GSMA", "Gsma_2026@Gestion", "gerencia"),
        ("GPSOI", "Gpsoi_2026%Operacion", "gerencia"),
        ("GSTS", "Gsts_2026&Servicio", "gerencia"),
        ("DG", "Dg_2026+Direccion", "gerencia"),
    ]

    for u, pwd, rol in usuarios_iniciales:
        existente = Usuario.query.filter_by(usuario=u).first()
        if not existente:
            nuevo_u = Usuario(
                usuario=u,
                rol=rol,
                creado_por="sistema",
                creado_en=datetime.utcnow(),
                activo=True
            )
            nuevo_u.set_password(pwd, quien="sistema")
            db.session.add(nuevo_u)
    db.session.commit()

# --------------------------
#   LOGIN / LOGOUT
# --------------------------
from datetime import datetime

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]

        user = Usuario.query.filter_by(usuario=usuario).first()

        if user and user.check_password(password) and user.activo:

            session.clear()

            session["usuario"] = user.usuario
            session["rol"] = user.rol
            session["gerencia"] = user.gerencia

            # ⭐ Año automático
            session["anio"] = datetime.now().year

            return redirect(url_for("lista"))

        flash("Usuario o contraseña incorrectos o usuario inactivo", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# --------------------------
#  GENERAR OFICIO
# --------------------------
def generar_folio():
    prefijo = "SOAPAP-"

    # Buscar el último oficio registrado
    ultimo = Oficio.query.order_by(Oficio.id.desc()).first()

    # Si no hay oficios o el campo está vacío → iniciar en 00001
    if not ultimo or not ultimo.numero:
        return f"{prefijo}00001"

    try:
        # Extraer la parte numérica del folio
        consecutivo = int(ultimo.numero.replace(prefijo, ""))
    except:
        # Si el formato está mal → reiniciar
        return f"{prefijo}00001"

    # Incrementar
    nuevo = consecutivo + 1
    return f"{prefijo}{nuevo:05d}"

# --------------------------
#   PROTEGER RUTAS
# --------------------------

@app.before_request
def proteger():
    rutas_publicas = ["login", "static"]
    if request.endpoint not in rutas_publicas and "gerencia" not in session:
        return redirect(url_for("login"))

# --------------------------
#   MÓDULO DE USUARIOS
# --------------------------

@app.route("/usuarios")
def usuarios():
    if session.get("rol") != "admin":
        return "Acceso restringido"
    lista = Usuario.query.all()
    return render_template("usuarios.html", usuarios=lista)

@app.route("/usuarios/nuevo", methods=["GET", "POST"])
def usuarios_nuevo():
    if session.get("rol") != "admin":
        return "Acceso restringido"

    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]
        rol = request.form["rol"]

        if not password_segura(password):
            return "La contraseña no cumple los requisitos de seguridad."

        u = Usuario(
            usuario=usuario,
            rol=rol,
            creado_por=session.get("gerencia"),
            creado_en=datetime.utcnow(),
            activo=True
        )
        u.set_password(password, quien=session.get("gerencia"))
        db.session.add(u)
        db.session.commit()
        return redirect(url_for("usuarios"))

    return render_template("usuarios_nuevo.html")

@app.route("/usuarios/editar/<int:id>", methods=["GET", "POST"])
def usuarios_editar(id):
    if session.get("rol") != "admin":
        return "Acceso restringido"

    u = Usuario.query.get(id)

    if request.method == "POST":
        nuevo_password = request.form["password"]
        rol = request.form["rol"]
        activo = True if request.form.get("activo") == "on" else False

        u.rol = rol
        u.activo = activo
        u.modificado_por = session.get("gerencia")
        u.modificado_en = datetime.utcnow()

        if nuevo_password.strip():
            if not password_segura(nuevo_password):
                return "La contraseña no cumple los requisitos de seguridad."
            u.set_password(nuevo_password, quien=session.get("gerencia"))

        db.session.commit()
        return redirect(url_for("usuarios"))

    return render_template("usuarios_editar.html", usuario=u)

@app.route("/usuarios/bloquear/<int:id>")
def usuarios_bloquear(id):
    if session.get("rol") != "admin":
        return "Acceso restringido"
    u = Usuario.query.get(id)
    u.activo = not u.activo
    u.modificado_por = session.get("gerencia")
    u.modificado_en = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("usuarios"))
# --------------------------
#   REGISTRO DE OFICIOS (ADMIN)
# --------------------------
@app.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if session.get("rol") not in ["admin", "superadmin"]:
        return "Acceso no autorizado", 403

    if request.method == "POST":
        anio = session.get("anio")

        folio = generar_folio(anio)

        oficio = Oficio(
            numero=folio,
            numero_oficio=request.form.get("numero_oficio"),
            fecha=request.form.get("fecha"),
            hora=request.form.get("hora"),
            numero_expediente=request.form.get("numero_expediente"),
            quien_emite=request.form.get("quien_emite"),
            con_copia_para=request.form.get("con_copia_para"),
            anexos=request.form.get("anexos"),
            gerencia_turnada=request.form.get("gerencia_turnada"),
            asunto=request.form.get("asunto"),
            prioridad=request.form.get("prioridad"),
            termino=int(request.form.get("termino") or 0),
            fecha_limite=request.form.get("fecha_limite"),
            responsable1=request.form.get("responsable1"),
            responsable2=request.form.get("responsable2"),
            nis=request.form.get("nis"),
            estatus="Pendiente",
        )

        db.session.add(oficio)
        db.session.commit()

        flash(f"Oficio registrado con folio {folio}", "success")
        return redirect(url_for("lista"))

    return render_template("nuevo.html")

# --------------------------
#   LISTA DE OFICIOS
# --------------------------
from sqlalchemy import or_

@app.route("/lista")
def lista():
    # ⭐ Cambio de año desde menú
    anio_param = request.args.get("anio", type=int)
    if anio_param:
        session["anio"] = anio_param

    anio = session.get("anio")
    rol = session.get("rol")
    gerencia = session.get("gerencia")

    consulta = Oficio.query

    # ⭐ Filtrar por año automáticamente
    consulta = consulta.filter(Oficio.fecha.like(f"{anio}-%"))

    # ⭐ BUSCADOR GENERAL (folio, NIS, número de oficio)
    q = request.args.get("q")
    if q:
        consulta = consulta.filter(
            or_(
                Oficio.numero.ilike(f"%{q}%"),          # Folio SOAPAP-00001
                Oficio.nis.ilike(f"%{q}%"),             # NIS
                Oficio.numero_oficio.ilike(f"%{q}%")    # Número de oficio externo
            )
        )

    # ⭐ Filtros opcionales
    gerencia_f = request.args.get("gerencia")
    estatus_f = request.args.get("estatus")
    fecha_f = request.args.get("fecha")

    if gerencia_f:
        consulta = consulta.filter_by(gerencia_turnada=gerencia_f)

    if estatus_f:
        consulta = consulta.filter_by(estatus=estatus_f)

    if fecha_f:
        consulta = consulta.filter_by(fecha=fecha_f)

    # ⭐ Permisos por rol
    if rol not in ["admin", "superadmin", "admin_limited"]:

        if gerencia == "GAL":
            consulta = consulta.filter(
                or_(
                    Oficio.gerencia_turnada == "GAL",
                    Oficio.gerencia_turnada == "GAL-Despacho"
                )
            )

        elif gerencia == "GAL-Despacho":
            consulta = consulta.filter_by(gerencia_turnada="GAL-Despacho")

        else:
            consulta = consulta.filter_by(gerencia_turnada=gerencia)

    # ⭐ Orden final
    oficios = consulta.order_by(Oficio.id.desc()).all()

    return render_template("lista.html", oficios=oficios)

from flask import flash

# --------------------------
#   RESPONDER OFICIO
# --------------------------
@app.route("/responder/<int:id>", methods=["GET", "POST"])
def responder(id):
    oficio = Oficio.query.get_or_404(id)

    rol = session.get("rol")
    gerencia = session.get("gerencia")

    # ⭐ 1. Validación de permisos
    # ADMINISTRADOR: puede editar cualquier oficio, incluso solucionado
    if rol in ["admin", "superadmin"]:
        tiene_permiso = True

    # GERENCIAS: solo pueden responder sus turnados
    else:
        # Caso especial GAL
        if gerencia == "GAL":
            tiene_permiso = oficio.gerencia_turnada in ["GAL", "GAL-Despacho"]
        else:
            tiene_permiso = (oficio.gerencia_turnada == gerencia)

        # ⭐ Las gerencias NO pueden modificar un oficio solucionado
        if oficio.estatus == "Solucionado":
            return "Este oficio ya está finalizado y no puede modificarse por la gerencia.", 403

    if not tiene_permiso:
        return "Acceso no autorizado", 403

    # ⭐ 2. Procesar respuesta
    if request.method == "POST":

        nuevo_estatus = request.form.get("estatus")

        # ⭐ 2.1 Si es gerencia, NO puede cambiar un solucionado
        if rol not in ["admin", "superadmin"] and oficio.estatus == "Solucionado":
            return "Este oficio ya está finalizado y no puede modificarse por la gerencia.", 403

        # ⭐ 2.2 Guardar estatus
        oficio.estatus = nuevo_estatus

        # ⭐ 2.3 Guardar campos adicionales solo si aplica
        if nuevo_estatus in ["En proceso", "En acuerdo"]:
            oficio.observaciones = request.form.get("observaciones")
            oficio.fecha_atencion = request.form.get("fecha_atencion")
            oficio.oficio_respuesta = request.form.get("oficio_respuesta")
            oficio.fecha_acuse = request.form.get("fecha_acuse")
        else:
            # Pendiente o Solucionado → guardar lo que venga
            oficio.observaciones = request.form.get("observaciones")
            oficio.fecha_atencion = request.form.get("fecha_atencion")
            oficio.oficio_respuesta = request.form.get("oficio_respuesta")
            oficio.fecha_acuse = request.form.get("fecha_acuse")

        # ⭐ 2.4 Calcular días de atención
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
#   EXPORTAR A EXCEL
# --------------------------

@app.route("/exportar_excel")
def exportar_excel():
    if "gerencia" not in session:
        return redirect(url_for("login"))

    if session.get("rol") == "admin":
        oficios = Oficio.query.all()
    else:
        oficios = Oficio.query.filter_by(gerencia_turnada=session["gerencia"]).all()

    data = []
    for o in oficios:
        data.append({
            "Folio SOAPAP": o.numero,                     # ⭐ Folio institucional
            "Número de oficio externo": o.numero_oficio,  # ⭐ Nuevo campo
            "Fecha": o.fecha,
            "Hora": o.hora,
            "Número expediente": o.numero_expediente,
            "Quien emite": o.quien_emite,
            "Con copia para": o.con_copia_para,
            "Anexos": o.anexos,
            "Gerencia turnada": o.gerencia_turnada,
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

    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Oficios")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="oficios.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# --------------------------
#   EXPORTAR A PDF
# --------------------------

@app.route("/exportar_pdf")
def exportar_pdf():
    if "gerencia" not in session:
        return redirect(url_for("login"))

    if session.get("rol") == "admin":
        oficios = Oficio.query.all()
    else:
        oficios = Oficio.query.filter_by(gerencia_turnada=session["gerencia"]).all()

    html = render_template("oficios_pdf.html", oficios=oficios)
    pdf = pdfkit.from_string(html, False)

    return send_file(
        BytesIO(pdf),
        as_attachment=True,
        download_name="oficios.pdf",
        mimetype="application/pdf"
    )
    
# --------------------------
#   CONFIRMAR IMPORTACIÓN
# --------------------------
from openpyxl import load_workbook

@app.route("/confirmar_importacion", methods=["POST"])
def confirmar_importacion():

    file_path = session.get("excel_temp_file")
    if not file_path:
        flash("No se encontró archivo para importar", "danger")
        return redirect(url_for("importar_excel"))

    # ⭐ BORRAR TABLA COMPLETA (solo en desarrollo)
    db.session.execute(text("TRUNCATE oficio RESTART IDENTITY CASCADE;"))
    db.session.commit()

    # ⭐ CARGAR EXCEL SIN PANDAS (STREAMING)
    wb = load_workbook(filename=file_path, read_only=True, data_only=True)
    ws = wb.active

    # ⭐ ENCABEZADOS ESTÁN EN LA FILA 2 (porque importar_excel usa header=1)
    headers = [cell.value for cell in next(ws.iter_rows(min_row=2, max_row=2))]

    # Convertir encabezados a índice
    idx = {h: i for i, h in enumerate(headers)}

    # ⭐ Procesar fila por fila SIN cargar todo en memoria
    # Los datos empiezan en la fila 3
    for row in ws.iter_rows(min_row=3):

        folio = row[idx["FOLIO"]].value
        if not folio:
            continue

        oficio = Oficio(
            numero = folio,
            fecha = row[idx["FECHA INGRESO"]].value,
            hora = row[idx["HORA"]].value,
            asunto = row[idx["ASUNTO"]].value,
            quien_emite = row[idx["QUIEN LO EMITE"]].value,
            gerencia_turnada = row[idx["GERENCIA"]].value,
            prioridad = row[idx["PRIORIDAD"]].value,
            numero_oficio = row[idx["NUMERO DE OFICIO"]].value
        )

        # ⭐ OBSERVACIONES
        obs = row[idx["OBSERVACIONES"]].value
        if obs:
            oficio.observaciones = str(obs).strip()

        # ⭐ FECHA DE ATENCIÓN
        f_at = row[idx["FECHA DE ATENCIÓN"]].value
        if f_at:
            try:
                oficio.fecha_atencion = f_at.strftime("%Y-%m-%d")
            except:
                oficio.fecha_atencion = None

        # ⭐ OFICIO DE RESPUESTA
        of_resp = row[idx["OFICIO DE RESPUESTA"]].value
        if of_resp:
            oficio.oficio_respuesta = str(of_resp).strip()

        # ⭐ FECHA ACUSE DE RESPUESTA
        f_acuse = row[idx["FECHA ACUSE DE RESPUESTA"]].value
        if f_acuse:
            try:
                oficio.fecha_acuse = f_acuse.strftime("%Y-%m-%d")
            except:
                oficio.fecha_acuse = None

        # ⭐ ESTATUS
        estatus_excel = str(row[idx["ESTATUS"]].value or "").strip().lower()

        if estatus_excel == "finalizado":
            oficio.estatus = "Solucionado"
        elif estatus_excel in ["pendiente", "en proceso", "en acuerdo", "solucionado"]:
            oficio.estatus = estatus_excel.capitalize()
        else:
            oficio.estatus = "Pendiente"

        # ⭐ CÁLCULO DE DÍAS DE ATENCIÓN
        if oficio.fecha and oficio.fecha_atencion:
            try:
                f1 = datetime.strptime(str(oficio.fecha), "%Y-%m-%d")
                f2 = datetime.strptime(oficio.fecha_atencion, "%Y-%m-%d")
                oficio.dias_atencion = (f2 - f1).days
            except:
                oficio.dias_atencion = None

        db.session.add(oficio)

    db.session.commit()

    flash("Importación completada correctamente", "success")
    return redirect(url_for("lista"))

# --------------------------
#   FUNCIÓN PARA GENERAR FOLIO
# --------------------------

def generar_folio():
    ultimo = Oficio.query.order_by(Oficio.id.desc()).first()

    if not ultimo or not ultimo.numero:
        return "SOAPAP-2026-0001"

    try:
        consecutivo = int(ultimo.numero.split("-")[2])
    except:
        consecutivo = 0

    nuevo = consecutivo + 1
    return f"SOAPAP-2026-{nuevo:04d}"
    
# --------------------------
#   CONFIRMAR IMPORTACIÓN
# --------------------------
from openpyxl import load_workbook

@app.route("/confirmar_importacion", methods=["POST"])
def confirmar_importacion():

    file_path = session.get("excel_temp_file")
    if not file_path:
        flash("No se encontró archivo para importar", "danger")
        return redirect(url_for("importar_excel"))

    # ⭐ BORRAR TABLA COMPLETA (solo en desarrollo)
    db.session.execute(text("TRUNCATE oficio RESTART IDENTITY CASCADE;"))
    db.session.commit()

    # ⭐ CARGAR EXCEL SIN PANDAS (STREAMING)
    wb = load_workbook(filename=file_path, read_only=True, data_only=True)
    ws = wb.active

    # Obtener encabezados
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]

    # Convertir encabezados a índice
    idx = {h: i for i, h in enumerate(headers)}

    # Procesar fila por fila SIN cargar todo en memoria
    for row in ws.iter_rows(min_row=2):

        folio = row[idx["FOLIO"]].value
        if not folio:
            continue

        oficio = Oficio(
            numero = folio,
            fecha = row[idx["FECHA INGRESO"]].value,
            hora = row[idx["HORA"]].value,
            asunto = row[idx["ASUNTO"]].value,
            quien_emite = row[idx["QUIEN LO EMITE"]].value,
            gerencia_turnada = row[idx["GERENCIA"]].value,
            prioridad = row[idx["PRIORIDAD"]].value,
            numero_oficio = row[idx["NUMERO DE OFICIO"]].value
        )

        # ⭐ OBSERVACIONES
        obs = row[idx["OBSERVACIONES"]].value
        if obs:
            oficio.observaciones = str(obs).strip()

        # ⭐ FECHA DE ATENCIÓN
        f_at = row[idx["FECHA DE ATENCIÓN"]].value
        if f_at:
            try:
                oficio.fecha_atencion = f_at.strftime("%Y-%m-%d")
            except:
                oficio.fecha_atencion = None

        # ⭐ OFICIO DE RESPUESTA
        of_resp = row[idx["OFICIO DE RESPUESTA"]].value
        if of_resp:
            oficio.oficio_respuesta = str(of_resp).strip()

        # ⭐ FECHA ACUSE DE RESPUESTA
        f_acuse = row[idx["FECHA ACUSE DE RESPUESTA"]].value
        if f_acuse:
            try:
                oficio.fecha_acuse = f_acuse.strftime("%Y-%m-%d")
            except:
                oficio.fecha_acuse = None

        # ⭐ ESTATUS
        estatus_excel = str(row[idx["ESTATUS"]].value or "").strip().lower()

        if estatus_excel == "finalizado":
            oficio.estatus = "Solucionado"
        elif estatus_excel in ["pendiente", "en proceso", "en acuerdo", "solucionado"]:
            oficio.estatus = estatus_excel.capitalize()
        else:
            oficio.estatus = "Pendiente"

        # ⭐ CÁLCULO DE DÍAS DE ATENCIÓN
        if oficio.fecha and oficio.fecha_atencion:
            try:
                f1 = datetime.strptime(str(oficio.fecha), "%Y-%m-%d")
                f2 = datetime.strptime(oficio.fecha_atencion, "%Y-%m-%d")
                oficio.dias_atencion = (f2 - f1).days
            except:
                oficio.dias_atencion = None

        db.session.add(oficio)

    db.session.commit()

    flash("Importación completada correctamente", "success")
    return redirect(url_for("lista"))

# --------------------------
#   INICIO
# --------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

@app.route('/dashboard')
def dashboard():

    # ============================
    # 1. Obtener todos los oficios
    # ============================
    oficios = Oficio.query.all()

    # ============================
    # 2. KPIs generales
    # ============================
    total_recibidos = len(oficios)
    total_atendidos = sum(1 for o in oficios if o.estatus == "Solucionado")
    total_pendientes = total_recibidos - total_atendidos

    porcentaje_cumplimiento = 0
    if total_recibidos > 0:
        porcentaje_cumplimiento = round((total_atendidos / total_recibidos) * 100, 1)

    # ============================
    # 3. Tabla por gerencia
    # ============================
    gerencias = {}
    for o in oficios:
        g = o.gerencia_turnada or "SIN GERENCIA"

        if g not in gerencias:
            gerencias[g] = {
                "recibidos": 0,
                "atendidos": 0,
                "pendientes": 0,
                "dias": []
            }

        gerencias[g]["recibidos"] += 1

        if o.estatus == "Solucionado":
            gerencias[g]["atendidos"] += 1
            if o.dias_atencion:
                gerencias[g]["dias"].append(o.dias_atencion)
        else:
            gerencias[g]["pendientes"] += 1

    # Convertir a lista para la tabla
    tabla_gerencias = []
    for g, datos in gerencias.items():
        promedio = round(sum(datos["dias"]) / len(datos["dias"]), 1) if datos["dias"] else 0
        cumplimiento = round((datos["atendidos"] / datos["recibidos"]) * 100, 1) if datos["recibidos"] else 0

        tabla_gerencias.append({
            "gerencia": g,
            "recibidos": datos["recibidos"],
            "atendidos": datos["atendidos"],
            "pendientes": datos["pendientes"],
            "cumplimiento": cumplimiento,
            "promedio_dias": promedio
        })

    # ============================
    # 4. Datos para gráficas mensuales
    # ============================
    meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
             "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    recibidos_mes = [0] * 12
    atendidos_mes = [0] * 12
    dias_promedio = [0] * 12

    dias_por_mes = {i: [] for i in range(12)}

    for o in oficios:
        if o.fecha:
            try:
                mes = int(o.fecha.split("-")[1]) - 1
            except:
                continue

            recibidos_mes[mes] += 1

            if o.estatus == "Solucionado":
                atendidos_mes[mes] += 1
                if o.dias_atencion:
                    dias_por_mes[mes].append(o.dias_atencion)

    for i in range(12):
        if dias_por_mes[i]:
            dias_promedio[i] = round(sum(dias_por_mes[i]) / len(dias_por_mes[i]), 1)

    # ============================
    # 5. Enviar datos al dashboard
    # ============================
    return render_template(
        "dashboard.html",
        total_recibidos=total_recibidos,
        total_atendidos=total_atendidos,
        total_pendientes=total_pendientes,
        porcentaje_cumplimiento=porcentaje_cumplimiento,
        tabla_gerencias=tabla_gerencias,
        meses=meses,
        recibidos_mes=recibidos_mes,
        atendidos_mes=atendidos_mes,
        dias_promedio=dias_promedio
    )

