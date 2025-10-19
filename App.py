from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os

app = Flask(__name__)
app.secret_key = "banque_solidaire_secret"

# --- INITIALISATION DE LA BASE DE DONNÉES ---
def init_db():
    if not os.path.exists("banque.db"):
        conn = sqlite3.connect("banque.db")
        c = conn.cursor()
        c.execute("""CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT,
                        email TEXT UNIQUE,
                        password TEXT,
                        balance REAL DEFAULT 0
                    )""")
        conn.commit()
        conn.close()

init_db()

# --- PAGE D’ACCUEIL ---
@app.route('/')
def index():
    return render_template('index.html')

# --- INSCRIPTION ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        conn = sqlite3.connect("banque.db")
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)", (name, email, password))
            conn.commit()
            flash("Compte créé avec succès ! Connectez-vous.")
            return redirect(url_for('login'))
        except:
            flash("Cet email est déjà utilisé.")
        conn.close()
    return render_template('register.html')

# --- CONNEXION ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = sqlite3.connect("banque.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
        user = c.fetchone()
        conn.close()

        if user:
            session['user_id'] = user[0]
            session['email'] = user[2]
            session['name'] = user[1]
            if user[2] == "admin@banque.com":
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        else:
            flash("Email ou mot de passe incorrect.")
    return render_template('login.html')

# --- TABLEAU DE BORD CLIENT ---
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = sqlite3.connect("banque.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE id=?", (session['user_id'],))
    balance = c.fetchone()[0]
    conn.close()
    return render_template('dashboard.html', name=session['name'], balance=balance)

# --- TRANSFERT ENTRE COMPTES ---
@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        recipient = request.form['email']
        amount = float(request.form['amount'])
        conn = sqlite3.connect("banque.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=?", (recipient,))
        rec = c.fetchone()
        if not rec:
            flash("Le destinataire n’existe pas.")
            conn.close()
            return redirect(url_for('transfer'))
        c.execute("SELECT balance FROM users WHERE id=?", (session['user_id'],))
        sender_balance = c.fetchone()[0]
        if sender_balance < amount:
            flash("Solde insuffisant.")
        else:
            c.execute("UPDATE users SET balance = balance - ? WHERE id=?", (amount, session['user_id']))
            c.execute("UPDATE users SET balance = balance + ? WHERE email=?", (amount, recipient))
            conn.commit()
            flash(f"Transfert de {amount} € effectué avec succès vers {recipient}.")
        conn.close()
    return render_template('transfer.html')

# --- ADMIN : CRÉDITER LES COMPTES ---
@app.route('/admin')
def admin_dashboard():
    if 'email' not in session or session['email'] != 'admin@banque.com':
        return redirect(url_for('login'))
    conn = sqlite3.connect("banque.db")
    c = conn.cursor()
    c.execute("SELECT name, email, balance FROM users")
    users = c.fetchall()
    conn.close()
    return render_template('admin_credits.html', users=users)

@app.route('/admin/credit', methods=['POST'])
def admin_credit():
    if 'email' not in session or session['email'] != 'admin@banque.com':
        return redirect(url_for('login'))
    email = request.form['email']
    amount = float(request.form['amount'])
    conn = sqlite3.connect("banque.db")
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE email=?", (amount, email))
    conn.commit()
    conn.close()
    flash(f"Le compte {email} a été crédité de {amount} €.")
    return redirect(url_for('admin_dashboard'))

# --- DÉCONNEXION ---
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)

