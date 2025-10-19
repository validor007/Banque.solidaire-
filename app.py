from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_session import Session
import sqlite3
import secrets
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', secrets.token_hex(16))
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

DATABASE = 'database.db'

# -------------------------
# DATABASE HELPERS
# -------------------------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                balance REAL DEFAULT 0.0,
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users (id),
                FOREIGN KEY (receiver_id) REFERENCES users (id)
            )
        ''')
        
        cursor = conn.execute('SELECT COUNT(*) as count FROM users WHERE is_admin = 1')
        admin_count = cursor.fetchone()['count']
        
        if admin_count == 0:
            hashed_password = generate_password_hash('admin123')
            conn.execute(
                'INSERT INTO users (username, email, password, balance, is_admin) VALUES (?, ?, ?, ?, ?)',
                ('admin', 'admin@bank.com', hashed_password, 1000000.0, 1)
            )
        
        conn.commit()

# -------------------------
# EMAIL HELPER (Zoho)
# -------------------------
ZOHO_EMAIL = os.environ.get('ZOHO_EMAIL')
ZOHO_PASSWORD = os.environ.get('ZOHO_PASSWORD')

def send_email(to_email: str, subject: str, body: str):
    if not ZOHO_EMAIL or not ZOHO_PASSWORD:
        app.logger.warning("ZOHO_EMAIL or ZOHO_PASSWORD not defined. Email not sent.")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = ZOHO_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP_SSL('smtp.zoho.com', 465)
        server.login(ZOHO_EMAIL, ZOHO_PASSWORD)
        server.sendmail(ZOHO_EMAIL, to_email, msg.as_string())
        server.quit()
        app.logger.info(f"Email sent to {to_email}")
        return True
    except Exception as e:
        app.logger.error(f"Error sending email to {to_email}: {e}")
        return False

# -------------------------
# DECORATORS
# -------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('login'))
        with get_db() as conn:
            user = conn.execute('SELECT is_admin FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            if not user or user['is_admin'] != 1:
                flash('Access denied. Admin privileges required.', 'error')
                return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# -------------------------
# ROUTES
# -------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not username or not email or not password:
            flash('All fields are required.', 'error')
            return redirect(url_for('register'))
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        
        try:
            with get_db() as conn:
                conn.execute(
                    'INSERT INTO users (username, email, password, balance) VALUES (?, ?, ?, ?)',
                    (username, email, hashed_password, 100.0)
                )
                conn.commit()
            # Send welcome email
            send_email(email, "Welcome to Banque Solidaire", 
                       f"Hello {username},\n\nWelcome! Your account has been created with a $100 bonus.")
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists.', 'error')
            return redirect(url_for('register'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Email and password are required.', 'error')
            return redirect(url_for('login'))
        
        with get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                flash('Login successful!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid email or password.', 'error')
                return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    with get_db() as conn:
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        sent_transactions = conn.execute('''
            SELECT t.*, u.username as receiver_name 
            FROM transactions t 
            JOIN users u ON t.receiver_id = u.id 
            WHERE t.sender_id = ? 
            ORDER BY t.created_at DESC
        ''', (session['user_id'],)).fetchall()
        received_transactions = conn.execute('''
            SELECT t.*, u.username as sender_name 
            FROM transactions t 
            JOIN users u ON t.sender_id = u.id 
            WHERE t.receiver_id = ? AND t.status = 'approved'
            ORDER BY t.created_at DESC
        ''', (session['user_id'],)).fetchall()
    return render_template('dashboard.html', user=user, sent_transactions=sent_transactions, received_transactions=received_transactions)

@app.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    if request.method == 'POST':
        receiver_username = request.form.get('receiver_username')
        amount_str = request.form.get('amount')
        
        if not amount_str:
            flash('Amount is required.', 'error')
            return redirect(url_for('transfer'))
        
        try:
            amount = float(amount_str)
            if amount <= 0:
                flash('Amount must be greater than zero.', 'error')
                return redirect(url_for('transfer'))
        except ValueError:
            flash('Invalid amount.', 'error')
            return redirect(url_for('transfer'))
        
        with get_db() as conn:
            sender = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            receiver = conn.execute('SELECT * FROM users WHERE username = ?', (receiver_username,)).fetchone()
            
            if not receiver:
                flash('Receiver not found.', 'error')
                return redirect(url_for('transfer'))
            
            if receiver['id'] == sender['id']:
                flash('You cannot transfer to yourself.', 'error')
                return redirect(url_for('transfer'))
            
            if sender['balance'] < amount:
                flash('Insufficient balance.', 'error')
                return redirect(url_for('transfer'))
            
            conn.execute(
                'UPDATE users SET balance = balance - ? WHERE id = ?',
                (amount, sender['id'])
            )
            
            conn.execute(
                'INSERT INTO transactions (sender_id, receiver_id, amount, status) VALUES (?, ?, ?, ?)',
                (sender['id'], receiver['id'], amount, 'pending')
            )
            
            conn.commit()
            
            # Notify receiver via email
            send_email(receiver['email'], "New Transfer Pending",
                       f"Hello {receiver['username']},\n\nYou have received a transfer of ${amount:.2f} from {sender['username']}. It is pending admin approval.")
            
            flash(f'Transfer of ${amount:.2f} to {receiver_username} initiated. Awaiting admin approval.', 'success')
            return redirect(url_for('dashboard'))
    
    return render_template('transfer.html')

@app
