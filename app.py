from flask import Flask, render_template, request, redirect, url_for, session, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO
import pandas as pd
import pdfkit
import re
import os

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
    rol = db.Column(db.String(50), nullable=False)  # admin o gerencia

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
    folio = db.Column(db.String(30), unique=True)
    numero = db.Column(db.String(50))
    fecha = db.Column(db.String(20))
    hora = db.Column(db.String(20))
    numero_expediente = db.Column(db.String(100))
    quien_emite = db.Column(db.String(200))
    con_copia_para = db.Column(db.String(200))
    anexos = db.Column(db.String(200))
    gerencia_turnada = db.Column(db.String(200))
    asunto = db.Column(db.Text)
    prioridad = db.Column(db.String(50))
    termino = db.Column(db.Integer)
    fecha_limite = db.Column(db.String(20))
    responsable1 = db.Column(db.String(200))
    responsable2 = db.Column(db.String(200))
    nis = db.Column(db.String(100))

    # Campos de respuesta de gerencias
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

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]

        user = Usuario.query.filter_by(usuario=usuario).first()

        if user and user.check_password(password) and user.activo:
            session["gerencia"] = user.usuario
            session["rol"] = user.rol
            return redirect(url_for("lista"))

        return "Usuario o contraseña incorrectos, o usuario bloqueado."

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("gerencia", None)
    session.pop("rol", None)
    return redirect(url_for("login"))
# --------------------------
#  GENERAR OFICIO
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
    if "rol" not in session or session["rol"] != "admin":
        return "Solo el admin puede registrar oficios"

    if request.method == "POST":
        numero = request.form["numero"]
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
            numero=numero,
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
            nis=nis
        )

        db.session.add(nuevo)
        db.session.commit()

        return redirect(url_for("lista"))

    return render_template("nuevo.html")

# --------------------------
#   LISTA DE OFICIOS
# --------------------------

@app.route("/lista")
def lista():
    gerencia = session["gerencia"]

    if session.get("rol") == "admin":
        oficios = Oficio.query.all()
    else:
        oficios = Oficio.query.filter_by(gerencia_turnada=gerencia).all()

    return render_template("lista.html", oficios=oficios)

# --------------------------
#   RESPUESTA DE GERENCIAS
# --------------------------

@app.route('/responder/<int:id>', methods=['GET', 'POST'])
def responder(id):
    oficio = Oficio.query.get_or_404(id)

    if request.method == 'POST':

        # ⭐ ESTA LÍNEA ES LA QUE TE FALTABA
        oficio.estatus = request.form.get('estatus')

        oficio.observaciones = request.form.get('observaciones')
        oficio.fecha_atencion = request.form.get('fecha_atencion')
        oficio.oficio_respuesta = request.form.get('oficio_respuesta')
        oficio.fecha_acuse = request.form.get('fecha_acuse')

        db.session.commit()
        return redirect(url_for('lista'))

    return render_template('responder.html', oficio=oficio)

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
            "Folio": o.folio,
            "Fecha": o.fecha,
            "Hora": o.hora,
            "Numero": o.numero,
            "Numero expediente": o.numero_expediente,
            "Quien emite": o.quien_emite,
            "Gerencia": o.gerencia_turnada,
            "Asunto": o.asunto,
            "Prioridad": o.prioridad,
            "Fecha límite": o.fecha_limite,
            "Responsable1": o.responsable1,
            "Responsable2": o.responsable2,
            "NIS": o.nis,
            "Estatus": o.estatus,
            "Fecha atención": o.fecha_atencion,
            "Días atención": o.dias_atencion,
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
#   IMPORTAR EXCEL
# --------------------------

import pandas as pd
import uuid
import os

@app.route("/importar_excel", methods=["GET", "POST"])
def importar_excel():
    if session.get("rol") != "admin":
        return "Acceso restringido"

    if request.method == "POST":
        archivo = request.files.get("archivo")

        if not archivo:
            return "No se subió archivo"

        try:
            df = pd.read_excel(archivo, header=1)
        except Exception as e:
            return f"Error al leer el archivo: {e}"

        # Normalizar columnas
        df.columns = df.columns.str.strip().str.upper()

        # Reemplazar NaN/NaT
        df = df.fillna("").replace("NaT", "")

        # Guardar archivo temporal
        temp_id = str(uuid.uuid4())
        temp_path = f"temp_{temp_id}.pkl"
        df.to_pickle(temp_path)

        session["excel_temp_file"] = temp_path

        # Vista previa
        preview = df.head(20).to_dict(orient="records")

        return render_template(
            "importar_excel_preview.html",
            preview=preview,
            columnas=df.columns
        )

    return render_template("importar_excel.html")


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

@app.route("/confirmar_importacion", methods=["POST"])
def confirmar_importacion():
    if session.get("rol") != "admin":
        return "Acceso restringido"

    temp_path = session.get("excel_temp_file")

    if not temp_path or not os.path.exists(temp_path):
        return "No se encontró el archivo temporal"

    df = pd.read_pickle(temp_path)
    df.columns = df.columns.str.strip().str.upper()

    # Importar solo hasta la fila 2698
    df = df.iloc[:2698]

    # Borrar información anterior
    Oficio.query.delete()
    db.session.commit()

    for _, fila in df.iterrows():

        # Ignorar filas vacías
        if fila.isnull().all():
            continue

        # --------------------------
        #   FECHAS
        # --------------------------
        fecha = fila.get("FECHA INGRESO", "")
        fecha_limite = fila.get("FECHA LÍMITE DE ATENCIÓN", "")

        if isinstance(fecha, pd.Timestamp):
            fecha = fecha.strftime("%Y-%m-%d")
        else:
            fecha = ""

        if isinstance(fecha_limite, pd.Timestamp):
            fecha_limite = fecha_limite.strftime("%Y-%m-%d")
        else:
            fecha_limite = ""

        # --------------------------
        #   FOLIO (AQUÍ SÍ EXISTE fila)
        # --------------------------
        folio = fila.get("FOLIO", "")

        if pd.isna(folio):
            folio = ""

        folio = str(folio).strip()

        if folio == "" or folio.lower() == "none":
            folio = generar_folio()

        # --------------------------
        #   CREAR REGISTRO
        # --------------------------
        nuevo = Oficio(
            numero=folio,
            fecha=fecha,
            hora=fila.get("HORA", ""),
            numero_expediente=fila.get("NO. EXP.", ""),
            quien_emite=fila.get("QUIEN LO EMITE", ""),
            con_copia_para=fila.get("CON COPIA PARA", ""),
            anexos=fila.get("ANEXOS", ""),
            gerencia_turnada=fila.get("GERENCIA", ""),
            asunto=fila.get("ASUNTO", ""),
            prioridad=fila.get("PRIORIDAD", ""),
            termino=0,
            fecha_limite=fecha_limite,
            responsable1=fila.get("RESPONSABLE 1", ""),
            responsable2=fila.get("RESPONSABLE 2", ""),
            nis=fila.get("NIS", "")
        )

        db.session.add(nuevo)

    db.session.commit()

    os.remove(temp_path)
    session.pop("excel_temp_file", None)

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

