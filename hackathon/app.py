from flask import Flask, render_template, request, session, redirect, url_for, flash, send_file
from flask_socketio import join_room, leave_room, send, SocketIO
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, ValidationError
import bcrypt
from werkzeug.utils import secure_filename
from flask_mysqldb import MySQL
from io import BytesIO
import uuid
import base64
from compiler import run_code

app = Flask(__name__)
app.config["SECRET_KEY"] = "your_secret_key_here"
socketio = SocketIO(app)

# MySQL Configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'mydatabase'
mysql = MySQL(app)

rooms = {}
meeting_rooms = set()

class RegisterForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Register")

    def validate_email(self, field):
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM users WHERE email=%s", (field.data,))
        user = cursor.fetchone()
        cursor.close()
        if user:
            raise ValidationError('Email Already Taken')

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        name = form.name.data
        email = form.email.data
        password = form.password.data
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        cursor = mysql.connection.cursor()
        cursor.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)", (name, email, hashed_password))
        mysql.connection.commit()
        cursor.close()

        return redirect(url_for('login'))

    return render_template('register.html', form=form)

@app.route('/aboutus')
def aboutus():
    return render_template('aboutus.html')

@app.route('/sem1upload', methods=['GET', 'POST'])
def sem1upload():
    if request.method == 'POST':
        # Check if the 'file' part is present in the request
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        
        file = request.files['file']
        
        # Check if a file was selected
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        
        # Check if the file has a .pdf extension
        if file and file.filename.lower().endswith('.pdf'):
            filename = secure_filename(file.filename)
            file_data = file.read()
            
            conn = mysql.connection
            cursor = conn.cursor()
            
            try:
                cursor.execute(
                    "INSERT INTO sem1_pdf_files (filename, file) VALUES (%s, %s)", 
                    (filename, file_data)
                )
                conn.commit()
                flash('File successfully uploaded')
            except Exception as e:
                conn.rollback()
                flash(f'An error occurred: {e}')
            finally:
                cursor.close()
            
            return redirect(url_for('dashboard'))
        else:
            flash('Only PDF files are allowed')
    
    return render_template('upload.html')

@app.route('/select_semister')
def select_semister():
    return render_template('select_semister.html')

@app.route('/upload_download')
def upload_download():
    return render_template('upload_download.html')

@app.route('/download/<int:file_id>')
def download_file(file_id):
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT filename, file FROM sem1_pdf_files WHERE id = %s", (file_id,))
    file = cursor.fetchone()
    cursor.close()
    if file:
        filename, file_data = file
        return send_file(BytesIO(file_data), as_attachment=True, download_name=filename)
    return "File not found", 404

@app.route('/files')
def list_files():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT id, filename FROM sem1_pdf_files")
    files = cursor.fetchall()
    cursor.close()
    return render_template('download.html', files=files)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
        cursor.close()

        if user and bcrypt.checkpw(password.encode('utf-8'), user[3].encode('utf-8')):
            session['user_id'] = user[0]
            return redirect(url_for('dashboard'))
        else:
            flash("Login failed. Please check your email and password")
            return redirect(url_for('login'))

    return render_template('login.html', form=form)

@app.route('/dashboard')
def dashboard():
    if 'user_id' in session:
        user_id = session['user_id']

        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        user = cursor.fetchone()
        cursor.close()

        if user:
            return render_template('dashboard.html', user=user)

    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("You have been logged out successfully.")
    return redirect(url_for('login'))

@app.route("/chat", methods=["POST", "GET"])
def chat_home():
    session.clear()
    if request.method == "POST":
        name = request.form.get("name")
        div = request.form.get("div")
        join = request.form.get("join")
        create = request.form.get("create")

        if not name:
            return render_template("home.html", error="Please enter a name.", div=div, name=name)

        if join!=False and not div:
            return render_template("home.html", error="Please enter a room code.", div=div, name=name)

        if create!=False:
            room = div
            rooms[room] = {"members": 0, "messages": []}
        elif div not in rooms:
            return render_template("home.html", error="Room does not exist.", div=div, name=name)

        session["room"] = div
        session["name"] = name
        return redirect(url_for("room"))

    return render_template("home.html")

@app.route("/room")
def room():
    room = session.get("room")
    if room is None or session.get("name") is None or room not in rooms:
        return redirect(url_for("chat_home"))

    return render_template("room.html", div=room, messages=rooms[room]["messages"])

@socketio.on("message")
def handle_message(data):
    room = session.get("room")
    if room not in rooms:
        return

    content = {
        "name": session.get("name"),
        "message": data["data"]
    }
    send(content, to=room)
    rooms[room]["messages"].append(content)
    print(f"{session.get('name')} said: {data['data']}")

@socketio.on("connect")
def handle_connect(auth):
    room = session.get("room")
    name = session.get("name")
    if not room or not name:
        return
    if room not in rooms:
        leave_room(room)
        return

    join_room(room)
    send({"name": name, "message": "has entered the room"}, to=room)
    rooms[room]["members"] += 1
    print(f"{name} joined room {room}")

@socketio.on("disconnect")
def handle_disconnect():
    room = session.get("room")
    name = session.get("name")
    leave_room(room)

    if room in rooms:
        rooms[room]["members"] -= 1
        if rooms[room]["members"] <= 0:
            del rooms[room]

    send({"name": name, "message": "has left the room"}, to=room)
    print(f"{name} has left the room {room}")

@app.route('/quiz')
def quiz_index():
    return render_template('quiz.html')

@app.route('/quiz_create_room', methods=['POST'])
def create_room():
    room_code = request.form.get('room_code')
    cur = mysql.connection.cursor()
    cur.execute('INSERT INTO rooms (room_code) VALUES (%s)', (room_code,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('quiz_index'))

@app.route('/add_question', methods=['POST'])
def add_question():
    room_id = int(request.form.get('room_id'))
    question_text = request.form.get('question_text')
    options = request.form.getlist('options')
    correct_option = int(request.form.get('correct_option'))

    cur = mysql.connection.cursor()

    # Check if the room exists
    cur.execute('SELECT id FROM rooms WHERE id = %s', (room_id,))
    room_exists = cur.fetchone()

    if not room_exists:
        cur.close()
        return "Room ID does not exist", 400

    # Insert the question
    cur.execute('INSERT INTO questions (room_id, question_text) VALUES (%s, %s)', (room_id, question_text))
    question_id = cur.lastrowid

    # Insert the options
    for index, option_text in enumerate(options):
        is_correct = (index == correct_option)
        cur.execute('INSERT INTO options (question_id, option_text, is_correct) VALUES (%s, %s, %s)', (question_id, option_text, is_correct))

    mysql.connection.commit()
    cur.close()

    return redirect(url_for('quiz_index'))

@app.route('/play_quiz', methods=['GET', 'POST'])
def play_quiz():
    if request.method == 'POST':
        room_id = int(request.form.get('room_id'))
        user_id = request.form.get('user_id')
        return redirect(url_for('show_quiz', room_id=room_id, user_id=user_id))

    return render_template('play_quiz.html')

@app.route('/show_quiz/<int:room_id>/<user_id>', methods=['GET', 'POST'])
def show_quiz(room_id, user_id):
    cur = mysql.connection.cursor()
    
    # Fetch questions
    cur.execute('SELECT * FROM questions WHERE room_id = %s', (room_id,))
    questions = cur.fetchall()
    
    if not questions:
        cur.close()
        return "No questions found for this room", 404

    # Fetch options
    cur.execute('SELECT * FROM options WHERE question_id IN (SELECT id FROM questions WHERE room_id = %s)', (room_id,))
    options = cur.fetchall()

    if not options:
        cur.close()
        return "No options found for these questions", 404

    # Group options by question_id
    options_by_question = {}
    for option in options:
        question_id = option[1]  # Assuming option[1] is the question_id
        if question_id not in options_by_question:
            options_by_question[question_id] = []
        options_by_question[question_id].append(option)

    if request.method == 'POST':
        score = 0
        for question_id in request.form:
            selected_option = request.form.get(question_id)
            cur.execute('SELECT is_correct FROM options WHERE id = %s', (selected_option,))
            is_correct = cur.fetchone()
            if is_correct and is_correct[0]:
                score += 1
        
        # Check if room_id and user_id are valid before inserting or updating user_scores
        cur.execute('SELECT id FROM questions WHERE id = %s', (room_id,))
        valid_room = cur.fetchone()
        
        if not valid_room:
            cur.close()
            return "Invalid room ID", 400

        cur.execute('SELECT id FROM user_scores WHERE room_id = %s AND user_id = %s', (room_id, user_id))
        existing_score = cur.fetchone()

        if existing_score:
            cur.execute('UPDATE user_scores SET score = %s WHERE id = %s', (score, existing_score[0]))
        else:
            cur.execute('INSERT INTO user_scores (room_id, user_id, score) VALUES (%s, %s, %s)', (room_id, user_id, score))

        mysql.connection.commit()
        cur.close()

        return f"Quiz completed. Your score: {score}"

    cur.close()
    return render_template('show_quiz.html', room_id=room_id, user_id=user_id, questions=questions, options_by_question=options_by_question)

def fetch_one_as_dict(cursor, query, args=()):
    cursor.execute(query, args)
    row = cursor.fetchone()
    if row:
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))
    return None

def fetch_all_as_dict(cursor, query, args=()):
    cursor.execute(query, args)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]

@app.route("/posts/new")
def new_post():
    return render_template("new.html")

@app.route("/posts", methods=["POST"])
def create_post():
    file = request.files.get("image")
    username = request.form.get("username")
    content = request.form.get("content")
    post_id = str(uuid.uuid4())

    image_data = None
    if file and file.filename != '':
        image_data = file.read()

    conn = mysql.connection
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO posts (id, username, content, image) VALUES (%s, %s, %s, %s)",
        (post_id, username, content, image_data)
    )
    conn.commit()
    cursor.close()

    return redirect(url_for('show_posts'))

@app.route("/posts/<string:id>/edit")
def edit_post(id):
    conn = mysql.connection
    cursor = conn.cursor()
    post = fetch_one_as_dict(cursor, "SELECT * FROM posts WHERE id = %s", (id,))
    cursor.close()

    if post:
        return render_template("edit.html", post=post)
    else:
        return render_template("error.html")

@app.route("/posts/<string:id>", methods=["POST"])
def update_post(id):
    new_content = request.form.get("content")
    file = request.files.get("image")

    image_data = None
    if file and file.filename != '':
        image_data = file.read()

    conn = mysql.connection
    cursor = conn.cursor()
    if image_data:
        cursor.execute("UPDATE posts SET content = %s, image = %s WHERE id = %s", (new_content, image_data, id))
    else:
        cursor.execute("UPDATE posts SET content = %s WHERE id = %s", (new_content, id))
    conn.commit()
    cursor.close()

    return redirect(url_for('show_posts'))

@app.route("/posts/<string:id>", methods=["DELETE"])
def delete_post(id):
    conn = mysql.connection
    cursor = conn.cursor()
    cursor.execute("DELETE FROM posts WHERE id = %s", (id,))
    conn.commit()
    cursor.close()

    return redirect(url_for('show_posts'))

@app.route("/posts/<string:id>")
def show_post(id):
    conn = mysql.connection
    cursor = conn.cursor()
    post = fetch_one_as_dict(cursor, "SELECT * FROM posts WHERE id = %s", (id,))
    cursor.close()

    if post:
        if post['image']:
            post['image'] = base64.b64encode(post['image']).decode('utf-8')  # Encode image to base64
        return render_template("specific.html", post=post)
    else:
        return render_template("error.html")

@app.route("/posts")
def show_posts():
    conn = mysql.connection
    cursor = conn.cursor()
    posts = fetch_all_as_dict(cursor, "SELECT * FROM posts")
    cursor.close()

    for post in posts:
        if post['image']:
            post['image'] = base64.b64encode(post['image']).decode('utf-8')  # Encode image to base64

    return render_template("profile_index.html", posts=posts)

meeting_rooms = set()

@app.route("/videomeet")
def home_videomeet():
    return redirect(url_for("dashboard_videomeet"))
@app.route("/dashboard_videomeet")
# @login_required
def dashboard_videomeet():
    if 'user_id' in session:
        user_id = session['user_id']

        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        user = cursor.fetchone()
        cursor.close()

        if user:
            return render_template('dashboard_videomeet.html', user=user)

    return redirect(url_for('login'))

@app.route("/meeting_videomeet")

def meeting_videomeet():
    return render_template("meeting_videomeet.html", username='karthik')


@app.route("/join_videomeet", methods=["GET", "POST"])

def join_videomeet():
    if request.method == "POST":
        room_id = request.form.get("roomID")
        return redirect(f"/meeting_videomeet?roomID={room_id}")

    return render_template("join_videomeet.html")

@app.route('/compiling')
def compiler_index():
    return render_template('compiler_index.html')

@app.route('/domain')
def domain_selector():
    return render_template('Domain.html')

@app.route('/guidance_videos')
def guidance_videos():
    return render_template('guidance_videos.html')

@app.route('/compile', methods=['POST'])
def compile():
    code = request.form.get('code')
    language = request.form.get('language')
    
    if not code:
        return "No code provided", 400
    if not language:
        return "No language selected", 400

    compiled_output = run_code(language, code)
    return render_template('compiler_result.html', compiled_output=compiled_output)

if __name__ == "__main__":
    socketio.run(app, debug=True)
