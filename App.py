# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change_this_in_production")

DB_PATH = "banque.db"

# -------------------------
# Helpers DB
# -------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(DB_PATH):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                balance REAL DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE donations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        c.execute("""
            CREATE TABLE transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                receiver_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(sender_id) REFERENCES users(id),
                FOREIGN KEY(receiver_id) REFERENCES users(id)
            )
        """)
        c.execute("""
            CREATE TABLE credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                user_id INTEGER,
                amount REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.commit()
        conn.close()

init_db()

# -------------------------
# Email (Zoho) helper
# -------------------------
ZOHO_EMAIL = os.environ.get("ZOHO_EMAIL")        # ex: banquesolidairee@zohomail.com
ZOHO_PASSWORD = os.environ.get("ZOHO_PASSWORD")  # mot de passe d'application Zoho

def send_email(to_email: str, subject: str, body: str):
    """Envoie un email via SMTP Zoho. Si les variables d'environnement ne sont pas définies,
    on log et on ne plante pas l'application (mode démonstration)."""
    if not ZOHO_EMAIL or not ZOHO_PASSWORD:
        app.logger.warning("ZOHO_EMAIL ou ZOHO_PASSWORD non définis — email non envoyé.")
        app.logger.info(f"[Email skip] to={to_email} subject={subject} body={body}")
        return False

    msg = MIMEMultipart()
    msg["From"] = ZOHO_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP_SSL("smtp.zoho.com", 465, timeout=10)
        server.login(ZOHO_EMAIL, ZOHO_PASSWORD)
        server.sendmail(ZOHO_EMAIL, to_email, msg.as_string())
        server.quit()
        app.logger.info(f"Email envoyé à {to_email} (subject: {subject})")
        return True
    except Exception as e:
        app.logger.error(f"Erreur envoi email à {to_email}: {e}")
        return False

# -------------------------
# Utilitaires
# -------------------------
def get_current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return user

def is_admin():
    u = get_current_user()
    return u and u["email"] == os.environ.get("ADMIN_EMAIL", "admin@banque.com")

# -------------------------
# Routes publiques
# -------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if not (name and email and password):
            flash("Tous les champs sont requis.")
            return redirect(url_for("register"))
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)", (name, email, password))
            conn.commit()
            # send welcome email
            subject = "Bienvenue à Banque Solidaire"
            body = f"Bonjour {name},\n\nMerci d'avoir créé un compte sur Banque Solidaire (prototype éducatif).\n\nCordialement,\nBanque Solidaire"
            send_email(email, subject, body)
            flash("Compte créé avec succès. Un e-mail de confirmation a été envoyé (si configuré).")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Cet email est déjà utilisé.")
        finally:
            conn.close()
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password)).fetchone()
        conn.close()
        if user:
            session["user_id"] = user["id"]
            flash("Connexion réussie.")
            return redirect(url_for("dashboard"))
        else:
            flash("Email ou mot de passe incorrect.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Déconnecté.")
    return redirect(url_for("index"))

# -------------------------
# Dashboard, dons, transferts
# -------------------------
@app.route("/dashboard")
def dashboard():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    conn = get_db_connection()
    donations = conn.execute("SELECT * FROM donations WHERE user_id=? ORDER BY timestamp DESC", (user["id"],)).fetchall()
    conn.close()
    return render_template("dashboard.html", user=user, donations=donations)

@app.route("/donate", methods=["POST"])
def donate():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    try:
        amount = float(request.form.get("amount","0"))
    except:
        flash("Montant invalide.")
        return redirect(url_for("dashboard"))
    if amount <= 0:
        flash("Montant invalide.")
        return redirect(url_for("dashboard"))
    conn = get_db_connection()
    # simple check balance
    u = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if u["balance"] < amount:
        flash("Solde insuffisant.")
        conn.close()
        return redirect(url_for("dashboard"))
    conn.execute("UPDATE users SET balance = balance - ? WHERE id=?", (amount, user["id"]))
    conn.execute("INSERT INTO donations (user_id, amount) VALUES (?, ?)", (user["id"], amount))
    conn.commit()
    conn.close()
    flash(f"Merci ! Vous avez donné {amount} €.")
    return redirect(url_for("dashboard"))

@app.route("/transfer", methods=["GET","POST"])
def transfer():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    conn = get_db_connection()
    users = conn.execute("SELECT * FROM users WHERE id != ?", (user["id"],)).fetchall()
    if request.method == "POST":
        try:
            receiver_id = int(request.form.get("receiver"))
            amount = float(request.form.get("amount","0"))
        except:
            flash("Données invalides.")
            conn.close()
            return redirect(url_for("transfer"))
        if amount <= 0:
            flash("Montant invalide.")
            conn.close()
            return redirect(url_for("transfer"))
        sender = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        if sender["balance"] < amount:
            flash("Solde insuffisant.")
            conn.close()
            return redirect(url_for("transfer"))
        # create transfer pending for admin approval
        conn.execute("INSERT INTO transfers (sender_id, receiver_id, amount, status) VALUES (?, ?, ?, 'pending')",
                     (user["id"], receiver_id, amount))
        conn.commit()
        # notify receiver by email immediately that a transfer has been initiated (educatif)
        receiver = conn.execute("SELECT * FROM users WHERE id=?", (receiver_id,)).fetchone()
        if receiver:
            subj = "Un transfert vous a été envoyé (en attente)"
            body = (f"Bonjour {receiver['name']},\n\n"
                    f"Un transfert de {amount} € a été initié en votre faveur par {sender['name']}. "
                    "Le paiement est en attente de validation administrative (prototype éducatif).\n\n"
                    "Cordialement,\nBanque Solidaire")
            send_email(receiver["email"], subj, body)
        flash("Transfert soumis à validation administrative. Le destinataire a été notifié (si email configuré).")
    conn.close()
    return render_template("transfer.html", users=users, user=user)

# -------------------------
# Admin routes
# -------------------------
@app.route("/admin/transfers", methods=["GET","POST"])
def admin_transfers():
    if not is_admin():
        flash("Accès admin requis.")
        return redirect(url_for("login"))
    conn = get_db_connection()
    transfers = conn.execute("""
        SELECT t.*, s.name as sender_name, r.name as receiver_name
        FROM transfers t
        JOIN users s ON t.sender_id = s.id
        JOIN users r ON t.receiver_id = r.id
        WHERE t.status='pending'
        ORDER BY t.timestamp ASC
    """).fetchall()
    if request.method == "POST":
        try:
            transfer_id = int(request.form.get("transfer_id"))
        except:
            flash("ID transfert invalide.")
            conn.close()
            return redirect(url_for("admin_transfers"))
        action = request.form.get("action")
        tr = conn.execute("SELECT * FROM transfers WHERE id=?", (transfer_id,)).fetchone()
        if not tr:
            flash("Transfert introuvable.")
            conn.close()
            return redirect(url_for("admin_transfers"))
        if action == "approve":
            # debit sender, credit receiver
            conn.execute("UPDATE users SET balance = balance - ? WHERE id=?", (tr["amount"], tr["sender_id"]))
            conn.execute("UPDATE users SET balance = balance + ? WHERE id=?", (tr["amount"], tr["receiver_id"]))
            conn.execute("UPDATE transfers SET status='approved' WHERE id=?", (transfer_id,))
            conn.commit()
            # notify receiver
            receiver = conn.execute("SELECT * FROM users WHERE id=?", (tr["receiver_id"],)).fetchone()
            sender = conn.execute("SELECT * FROM users WHERE id=?", (tr["sender_id"],)).fetchone()
            if receiver:
                subj = "Transfert reçu"
                body = (f"Bonjour {receiver['name']},\n\n"
                        f"Votre compte a été crédité de {tr['amount']:.2f} € de la part de {sender['name']}.\n\nCordialement,\nBanque Solidaire")
                send_email(receiver["email"], subj, body)
            flash("Transfert approuvé et destinataire notifié (si email configuré).")
        else:
            conn.execute("UPDATE transfers SET status='rejected' WHERE id=?", (transfer_id,))
            conn.commit()
            flash("Transfert rejeté.")
    conn.close()
    return render_template("admin_transfers.html", transfers=transfers)

@app.route("/admin/credits", methods=["GET","POST"])
def admin_credits():
    if not is_admin():
        flash("Accès admin requis.")
        return redirect(url_for("login"))
    conn = get_db_connection()
    users = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
    if request.method == "POST":
        try:
            user_id = int(request.form.get("user_id"))
            amount = float(request.form.get("amount","0"))
        except:
            flash("Données invalides.")
            conn.close()
            return redirect(url_for("admin_credits"))
        if amount <= 0:
            flash("Montant invalide.")
            conn.close()
            return redirect(url_for("admin_credits"))
        conn.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id))
        conn.execute("INSERT INTO credits (admin_id, user_id, amount) VALUES (?, ?, ?)",
                     (session.get("user_id"), user_id, amount))
        conn.commit()
        # notify user
        u = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if u:
            subj = "Votre compte a été crédité"
            body = (f"Bonjour {u['name']},\n\nVotre compte a été crédité de {amount:.2f} € par l'administrateur.\n\nCordialement,\nBanque Solidaire")
            send_email(u["email"], subj, body)
        flash("Compte crédité et utilisateur notifié (si email configuré).")
    credits = conn.execute("""
        SELECT c.*, u.name as user_name
        FROM credits c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.timestamp DESC
    """).fetchall()
    conn.close()
    return render_template("admin_credits.html", users=users, credits=credits)

# -------------------------
# Contact
# -------------------------
@app.route("/contact", methods=["GET","POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name","")
        email = request.form.get("email","")
        message = request.form.get("message","")
        app.logger.info(f"[CONTACT] {name} <{email}>: {message}")
        flash("Message reçu. Merci !")
        return redirect(url_for("contact"))
    return render_template("contact.html")

# -------------------------
# Run (local)
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
