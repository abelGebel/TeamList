import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_por_defecto_desarrollo')

# Configuración de la base de datos
database_url = os.environ.get('DATABASE_URL', 'sqlite:///jugadores.db')

# Corrección para compatibilidad de SQLAlchemy con URLs de Render (postgres:// -> postgresql://)
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

if database_url.startswith("sqlite") and os.environ.get('RENDER'):
    # Advertencia: SQLite en Render no es persistente sin discos montados
    print("ADVERTENCIA: Usando SQLite en un entorno efímero. Los datos se perderán al reiniciar.")

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Configuración para evitar desconexiones prematuras en Render/Postgres
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}
db = SQLAlchemy(app)

# Modelos de la base de datos
class Seleccion(db.Model):
    __tablename__ = 'tl_seleccion'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    jugadores = db.relationship('Jugador', backref='seleccion', lazy=True, cascade="all, delete-orphan")

class Club(db.Model):
    __tablename__ = 'tl_club'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    jugadores = db.relationship('Jugador', backref='club', lazy=True)

class Jugador(db.Model):
    __tablename__ = 'tl_jugador'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    posicion = db.Column(db.String(50), nullable=False)
    seleccion_id = db.Column(db.Integer, db.ForeignKey('tl_seleccion.id'), nullable=False)
    orden = db.Column(db.Integer, default=0)
    club_id = db.Column(db.Integer, db.ForeignKey('tl_club.id'), nullable=False)

    def __repr__(self):
        return f'<Jugador {self.nombre}>'

with app.app_context():
    db.create_all()
    # Imprimir en logs de Render para verificar qué DB se está usando realmente
    db_type = "PostgreSQL" if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI'] else "SQLite"
    print(f"INFO: Conectado a base de datos tipo: {db_type}")

@app.route('/')
def index():
    selecciones = Seleccion.query.all()
    return render_template('index.html', selecciones=selecciones)

@app.route('/crear_seleccion', methods=['POST'])
def crear_seleccion():
    nombre = request.form.get('nombre')
    if nombre:
        nueva = Seleccion(nombre=nombre)
        db.session.add(nueva)
        db.session.commit()
        flash(f'Selección "{nombre}" creada.', 'success')
    return redirect(url_for('index'))

@app.route('/seleccion/<int:id>')
def ver_seleccion(id):
    seleccion = Seleccion.query.get_or_404(id)
    clubes = Club.query.all()
    
    # Agrupamos jugadores por posición para facilitar el renderizado por secciones
    posiciones = ['Portero', 'Defensa', 'Mediocampista', 'Delantero']
    jugadores_agrupados = {}
    
    for pos in posiciones:
        # Filtramos y ordenamos por el campo 'orden'
        jugadores_agrupados[pos] = sorted([j for j in seleccion.jugadores if j.posicion == pos], 
                                        key=lambda x: x.orden)
    
    return render_template('equipo.html', seleccion=seleccion, jugadores_agrupados=jugadores_agrupados, clubes=clubes)

@app.route('/registrar_jugador/<int:seleccion_id>', methods=['POST'])
def registrar_jugador(seleccion_id):
    seleccion = Seleccion.query.get_or_404(seleccion_id)
    
    if len(seleccion.jugadores) >= 23:
        flash('Error: Esta selección ya alcanzó el límite máximo de 23 jugadores.', 'danger')
        return redirect(url_for('ver_seleccion', id=seleccion_id))

    nombre = request.form.get('nombre')
    posicion = request.form.get('posicion')
    nombre_club = request.form.get('nombre_club')

    if nombre and posicion and nombre_club:
        # Buscar si el club ya existe o crearlo
        club = Club.query.filter_by(nombre=nombre_club).first()
        if not club:
            club = Club(nombre=nombre_club)
            db.session.add(club)
            db.session.flush() # Usar flush en lugar de commit intermedio
        
        # Calcular el siguiente número de orden para esa posición
        ordenes = [j.orden for j in seleccion.jugadores if j.posicion == posicion]
        max_orden = max(ordenes) if ordenes else -1
        
        nuevo_jugador = Jugador(
            nombre=nombre, 
            posicion=posicion, 
            seleccion_id=seleccion_id, 
            club_id=club.id,
            orden=max_orden + 1
        )
        db.session.add(nuevo_jugador)
        db.session.commit()
    else:
        flash('Todos los campos son obligatorios.', 'danger')
    
    return redirect(url_for('ver_seleccion', id=seleccion_id))

@app.route('/eliminar_seleccion/<int:id>', methods=['POST'])
def eliminar_seleccion(id):
    seleccion = Seleccion.query.get_or_404(id)
    nombre = seleccion.nombre
    db.session.delete(seleccion)
    db.session.commit()
    flash(f'Selección {nombre} eliminada correctamente.', 'warning')
    return redirect(url_for('index'))

@app.route('/eliminar_jugador/<int:id>', methods=['POST'])
def eliminar_jugador(id):
    jugador = Jugador.query.get_or_404(id)
    seleccion_id = jugador.seleccion_id
    nombre = jugador.nombre
    db.session.delete(jugador)
    db.session.commit()
    flash(f'Jugador {nombre} eliminado.', 'info')
    return redirect(url_for('ver_seleccion', id=seleccion_id))

@app.route('/reordenar_jugadores', methods=['POST'])
def reordenar_jugadores():
    data = request.get_json()
    if not data:
        return {'status': 'error', 'message': 'No data provided'}, 400
        
    # Recibimos una lista de IDs en el nuevo orden
    orden_ids = data.get('orden', [])
    for index, jugador_id in enumerate(orden_ids):
        # Usamos session.get() que es el reemplazo moderno de query.get()
        jugador = db.session.get(Jugador, jugador_id)
        if jugador:
            jugador.orden = index
    db.session.commit()
    return {'status': 'success'}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
