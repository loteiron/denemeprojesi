import os
import re
from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash, abort
from flask_mysqldb import MySQL
from functools import wraps
from datetime import datetime, timedelta
import logging
from config import Config

logging.basicConfig(filename='app.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

app = Flask(__name__)
app.config.from_object(Config)
mysql = MySQL(app)

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500

def db_init():
    import MySQLdb
    conn = MySQLdb.connect(host=Config.MYSQL_HOST, user=Config.MYSQL_USER, passwd=Config.MYSQL_PASSWORD)
    c = conn.cursor()
    c.execute(f"CREATE DATABASE IF NOT EXISTS {Config.MYSQL_DB} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    conn.commit()
    c.close()
    conn = MySQLdb.connect(host=Config.MYSQL_HOST, user=Config.MYSQL_USER, passwd=Config.MYSQL_PASSWORD, db=Config.MYSQL_DB, charset="utf8mb4")
    c = conn.cursor()
    c.execute("SHOW TABLES LIKE 'users'")
    if c.fetchone():
        c.execute("SHOW COLUMNS FROM users LIKE 'is_admin'")
        if not c.fetchone():
            c.execute("ALTER TABLE users ADD is_admin BOOLEAN DEFAULT 0")
            conn.commit()
    c.execute("SHOW TABLES LIKE 'reservations'")
    if c.fetchone():
        c.execute("SHOW COLUMNS FROM reservations LIKE 'course_id'")
        if not c.fetchone():
            c.execute("ALTER TABLE reservations ADD COLUMN course_id INT NOT NULL AFTER slot_id")
            conn.commit()
    c.execute("""
    CREATE TABLE IF NOT EXISTS faculties (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL UNIQUE
    ) ENGINE=InnoDB;
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(100) NOT NULL UNIQUE,
        student_number VARCHAR(30) NOT NULL,
        password VARCHAR(200) NOT NULL,
        faculty_id INT NOT NULL,
        is_admin BOOLEAN DEFAULT 0,
        FOREIGN KEY (faculty_id) REFERENCES faculties(id) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS courses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        faculty_id INT NOT NULL,
        FOREIGN KEY (faculty_id) REFERENCES faculties(id) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS slots (
        id INT AUTO_INCREMENT PRIMARY KEY,
        date DATE NOT NULL,
        time TIME NOT NULL,
        faculty_id INT NOT NULL,
        UNIQUE KEY uniq_slot (date, time, faculty_id),
        FOREIGN KEY (faculty_id) REFERENCES faculties(id) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS reservations (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        slot_id INT NOT NULL UNIQUE,
        course_id INT NOT NULL,
        title VARCHAR(120) NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (slot_id) REFERENCES slots(id) ON DELETE CASCADE,
        FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(150) NOT NULL,
        message TEXT NOT NULL,
        show_until DATE DEFAULT NULL
    ) ENGINE=InnoDB;
    """)
    faculties = ["Mühendislik", "İktisat", "Fen-Edebiyat", "Tıp"]
    courses = {
        "Mühendislik": ["Matematik I", "Fizik I", "Programlama", "Devreler"],
        "İktisat": ["Mikroekonomi", "Makroekonomi", "İstatistik", "Muhasebe"],
        "Fen-Edebiyat": ["Biyoloji", "Kimya", "Psikoloji", "Tarih"],
        "Tıp": ["Anatomi", "Fizyoloji", "Farmakoloji", "Cerrahi"]
    }
    for fac in faculties:
        c.execute("INSERT IGNORE INTO faculties (name) VALUES (%s)", (fac,))
    c.execute("SELECT * FROM faculties")
    fac_map = {f[1]: f[0] for f in c.fetchall()}
    for fac, dersler in courses.items():
        for ders in dersler:
            c.execute("INSERT IGNORE INTO courses (name, faculty_id) VALUES (%s, %s)", (ders, fac_map[fac]))
    c.execute("SELECT * FROM users WHERE email='admin@admin.com'")
    if not c.fetchone():
        c.execute("INSERT INTO users (name, email, student_number, password, faculty_id, is_admin) VALUES ('Admin', 'admin@admin.com', '000000', %s, %s, 1)", ("admin", fac_map["Mühendislik"]))
    conn.commit()
    c.close()
    conn.close()
db_init()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Giriş yapmalısınız!", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Yönetici girişi gerekli!", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

@app.context_processor
def inject_now():
    return {'now': datetime.now()}

def get_upcoming_reservations(user_id, limit=3):
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT s.date, s.time, f.name as faculty, r.title, c.name as course
        FROM reservations r
        JOIN slots s ON r.slot_id = s.id
        JOIN faculties f ON s.faculty_id = f.id
        JOIN courses c ON r.course_id = c.id
        WHERE r.user_id=%s AND s.date >= CURDATE()
        ORDER BY s.date ASC, s.time ASC
        LIMIT %s
    """, (user_id, limit))
    return cursor.fetchall()

def get_active_notifications():
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT title, message FROM notifications
        WHERE show_until IS NULL OR show_until >= CURDATE()
        ORDER BY id DESC LIMIT 5
    """)
    return cursor.fetchall()

@app.route("/")
def home():
    if "user_id" in session:
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/dashboard")
@login_required
def dashboard():
    upcoming = get_upcoming_reservations(session["user_id"])
    notifications = get_active_notifications()
    return render_template("dashboard.html", upcoming=upcoming, notifications=notifications)

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s AND password = %s", (email, password))
        user = cursor.fetchone()
        if user:
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["faculty_id"] = user["faculty_id"]
            session["is_admin"] = bool(user["is_admin"])
            flash("Giriş başarılı!","success")
            if session["is_admin"]:
                return redirect(url_for("admin_dashboard"))
            else:
                return redirect(url_for("dashboard"))
        else:
            flash("Hatalı e-posta veya şifre!", "danger")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM faculties")
    faculties = cursor.fetchall()
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        student_number = request.form["student_number"]
        password = request.form["password"]
        faculty_id = request.form["faculty_id"]
        if not (name and email and student_number and password and faculty_id):
            flash("Tüm alanlar doldurulmalı!", "danger")
        elif not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash("Geçerli bir e-posta giriniz!", "danger")
        elif len(password) < 5:
            flash("Şifre en az 5 karakter olmalı!", "danger")
        else:
            try:
                cursor.execute(
                    "INSERT INTO users (name, email, student_number, password, faculty_id) VALUES (%s, %s, %s, %s, %s)",
                    (name, email, student_number, password, faculty_id)
                )
                mysql.connection.commit()
                flash("Kayıt başarılı! Giriş yapabilirsiniz.", "success")
                return redirect(url_for("login"))
            except Exception as e:
                logging.error(f"Kayıt hatası: {e}")
                flash("Bu e-posta ile daha önce kayıt olunmuş!", "danger")
    return render_template("register.html", faculties=faculties)

@app.route("/logout")
def logout():
    session.clear()
    flash("Çıkış yapıldı!","info")
    return redirect(url_for("login"))

@app.route("/calendar")
@login_required
def calendar():
    base_date = datetime.today()
    days = [(base_date + timedelta(days=i)).date() for i in range(5)]
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM faculties ORDER BY id ASC")
    faculties = cursor.fetchall()
    times = []
    start = datetime.strptime("09:30", "%H:%M")
    end = datetime.strptime("16:30", "%H:%M")
    while start <= end:
        times.append(start.strftime("%H:%M"))
        start += timedelta(minutes=1)
    slot_map = {}
    placeholder = ','.join(['%s'] * len(days))
    cursor.execute(f"SELECT s.*, r.user_id FROM slots s LEFT JOIN reservations r ON s.id = r.slot_id WHERE s.date IN ({placeholder})", tuple(days))
    for row in cursor.fetchall():
        slot_map[(str(row["date"]), row["time"], row["faculty_id"])] = row
    return render_template("calendar.html", days=days, times=times, faculties=faculties, slot_map=slot_map, session=session, now=datetime.now())

@app.route("/get_courses")
@login_required
def get_courses():
    faculty_id = request.args.get("faculty_id")
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM courses WHERE faculty_id=%s", (faculty_id,))
    dersler = cursor.fetchall()
    return jsonify([{"id": d["id"], "name": d["name"]} for d in dersler])

@app.route("/make_reservation", methods=["POST"])
@login_required
def make_reservation():
    date = request.form.get("date")
    time = request.form.get("time")
    faculty_id = request.form.get("faculty_id")
    course_id = request.form.get("course")
    title = request.form.get("title")
    description = request.form.get("description")
    if not (date and time and faculty_id and course_id and title):
        return jsonify({"success": False, "message": "Eksik bilgi!"})
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM slots WHERE date=%s AND time=%s AND faculty_id=%s", (date, time, faculty_id))
    slot = cursor.fetchone()
    if not slot:
        cursor.execute("INSERT INTO slots (date, time, faculty_id) VALUES (%s,%s,%s)", (date, time, faculty_id))
        mysql.connection.commit()
        cursor.execute("SELECT * FROM slots WHERE date=%s AND time=%s AND faculty_id=%s", (date, time, faculty_id))
        slot = cursor.fetchone()
    cursor.execute("SELECT * FROM reservations WHERE slot_id=%s", (slot['id'],))
    rezervasyon = cursor.fetchone()
    if rezervasyon:
        return jsonify({"success": False, "message": "Bu slot zaten rezerve edilmiş!"})
    cursor.execute("""
        SELECT r.* FROM reservations r
        JOIN slots s ON r.slot_id = s.id
        WHERE r.user_id=%s AND s.date=%s AND s.faculty_id=%s
    """, (session["user_id"], date, faculty_id))
    user_slots = cursor.fetchone()
    if user_slots:
        return jsonify({"success": False, "message": "Aynı fakültede aynı gün bir rezervasyonunuz olabilir!"})
    cursor.execute("""
        INSERT INTO reservations (user_id, slot_id, course_id, title, description)
        VALUES (%s, %s, %s, %s, %s)
    """, (session["user_id"], slot['id'], course_id, title, description))
    mysql.connection.commit()
    logging.info(f"Kullanıcı {session['user_id']} {date} {time} {faculty_id} slotu rezerve etti.")
    return jsonify({"success": True, "message": "Rezervasyon yapıldı!"})

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    cursor = mysql.connection.cursor()
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        student_number = request.form["student_number"]
        cursor.execute("UPDATE users SET name=%s, email=%s, student_number=%s WHERE id=%s",
                       (name, email, student_number, session["user_id"]))
        mysql.connection.commit()
        flash("Bilgiler güncellendi!", "success")
    cursor.execute("""
        SELECT u.*, f.name as faculty_name
        FROM users u
        JOIN faculties f ON u.faculty_id = f.id
        WHERE u.id=%s
    """, (session["user_id"],))
    user = cursor.fetchone()
    return render_template("profile.html", user=user)

@app.route("/password_update", methods=["GET", "POST"])
@login_required
def password_update():
    if request.method == "POST":
        old = request.form["old_password"]
        new = request.form["new_password"]
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT password FROM users WHERE id=%s", (session["user_id"],))
        real = cursor.fetchone()
        if real and real["password"] == old:
            cursor.execute("UPDATE users SET password=%s WHERE id=%s", (new, session["user_id"]))
            mysql.connection.commit()
            flash("Şifre güncellendi!", "success")
        else:
            flash("Eski şifre hatalı!", "danger")
    return render_template("password_update.html")

@app.route("/notification_settings", methods=["GET", "POST"])
@login_required
def notification_settings():
    if request.method == "POST":
        flash("Bildirim tercihleri kaydedildi!", "success")
    return render_template("notification_settings.html")

@app.route("/admin")
@admin_required
def admin_dashboard():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT COUNT(*) as c FROM users WHERE is_admin=0")
    user_count = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) as c FROM reservations")
    reservation_count = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) as c FROM notifications")
    notification_count = cursor.fetchone()["c"]
    return render_template("admin_dashboard.html", user_count=user_count, reservation_count=reservation_count, notification_count=notification_count)

@app.route("/admin/users")
@admin_required
def admin_users():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT u.id, u.name, u.email, u.student_number, f.name as faculty, u.is_admin FROM users u JOIN faculties f ON u.faculty_id=f.id")
    users = cursor.fetchall()
    return render_template("admin_users.html", users=users)

@app.route("/admin/reservations")
@admin_required
def admin_reservations():
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT r.id, u.name as user, f.name as faculty, s.date, s.time, c.name as course, r.title, r.created_at
        FROM reservations r
        JOIN users u ON r.user_id=u.id
        JOIN slots s ON r.slot_id=s.id
        JOIN faculties f ON s.faculty_id=f.id
        JOIN courses c ON r.course_id=c.id
        ORDER BY s.date DESC, s.time DESC
    """)
    reservations = cursor.fetchall()
    return render_template("admin_reservations.html", reservations=reservations)

@app.route("/admin/notifications", methods=["GET", "POST"])
@admin_required
def admin_notifications():
    cursor = mysql.connection.cursor()
    if request.method == "POST":
        title = request.form["title"]
        message = request.form["message"]
        show_until = request.form.get("show_until")
        cursor.execute("INSERT INTO notifications (title, message, show_until) VALUES (%s, %s, %s)", (title, message, show_until or None))
        mysql.connection.commit()
        flash("Bildirim eklendi!", "success")
    cursor.execute("SELECT * FROM notifications ORDER BY id DESC")
    notifications = cursor.fetchall()
    return render_template("admin_notifications.html", notifications=notifications)

if __name__ == "__main__":
    app.run(debug=True)