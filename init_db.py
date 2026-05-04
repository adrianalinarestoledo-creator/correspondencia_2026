import sqlite3

# Conexión a la base de datos (si no existe, se crea)
conn = sqlite3.connect("correspondencia.db")
cursor = conn.cursor()

# Crear tabla de oficios
cursor.execute("""
CREATE TABLE IF NOT EXISTS oficios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_ingreso TEXT,
    mes TEXT,
    hora TEXT,
    numero_oficio TEXT,
    fecha_emision TEXT,
    quien_emite TEXT,
    numero_expediente TEXT,
    con_copia_para TEXT,
    asunto TEXT,
    anexos TEXT,
    gerencia TEXT,
    prioridad TEXT,
    responsable1 TEXT,
    responsable2 TEXT,
    nis TEXT,
    estatus TEXT,
    semaforo TEXT,
    observaciones TEXT,
    termino TEXT,
    fecha_limite TEXT,
    fecha_atencion TEXT,
    oficio_respuesta TEXT,
    fecha_acuse TEXT,
    dias_atencion INTEGER
);
""")

conn.commit()
conn.close()

print("Base de datos y tabla 'oficios' creadas correctamente.")
