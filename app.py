import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"
USERS_DB_PATH = 'users.db'
ITEMS_DB_PATH = 'items.db'


def init_users_db():
    conn = sqlite3.connect(USERS_DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


def init_items_db():
    conn = sqlite3.connect(ITEMS_DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            image TEXT NOT NULL DEFAULT '',
            stock_remaining INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL DEFAULT '',
            tag TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT ''
        )
    ''')
    
    conn.commit()
    conn.close()


def get_users_db_connection():
    conn = sqlite3.connect(USERS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_items_db_connection():
    conn = sqlite3.connect(ITEMS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Ensure both tables exist on startup.
init_users_db()
init_items_db()


@app.context_processor
def inject_auth_state():
    user_name = (session.get('user_name') or '').strip().capitalize()
    if not user_name and session.get('user_email'):
        user_name = session['user_email'].split('@', 1)[0]
    if not user_name:
        user_name = "there"

    return {
        "logged_in": 'user_id' in session,
        "current_user_name": user_name
    }


@app.route('/')
def index():
    return render_template("index.html", show_footer=True, show_login=True)


@app.route('/user')
def user():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, name, email FROM users WHERE id = ?',
        (session.get('user_id'),)
    ).fetchone()

    if not db_user:
        users_conn.close()
        session.clear()
        return redirect(url_for('login'))

    user_name = (db_user['name'] or '').strip()
    if not user_name:
        user_name = db_user['email'].split('@', 1)[0]

    items_conn = get_items_db_connection()
    items = items_conn.execute(
        '''
        SELECT id, image, stock_remaining, title, tag, description
        FROM items
        WHERE user_id = ? OR user_id IS NULL
        ORDER BY id
        ''',
        (db_user['id'],)
    ).fetchall()

    items_conn.close()
    users_conn.close()

    session['user_email'] = db_user['email']
    session['user_name'] = user_name
    return render_template(
        "user.html",
        show_footer=True,
        user_email=db_user['email'],
        user_name=user_name.capitalize(),
        items=items
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    success = "Account created. You can log in now." if request.args.get('created') == '1' else None

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        conn = get_users_db_connection()
        user = conn.execute('SELECT id, name, email, password FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if not user:
            error = 'No account found with that email.'
        else:
            stored_password = user['password']
            valid_password = check_password_hash(stored_password, password) or stored_password == password

            if valid_password:
                display_name = (user['name'] or '').strip()
                if not display_name:
                    display_name = user['email'].split('@', 1)[0]
                session['user_id'] = user['id']
                session['user_email'] = user['email']
                session['user_name'] = display_name
                return redirect(url_for('user'))

            error = 'Incorrect password.'

    return render_template("login.html", show_footer=False, error=error, success=success)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if password != confirm_password:
            error = 'Passwords do not match.'
        elif not name:
            error = 'Name is required.'
        elif len(password) < 8:
            error = 'Password must be at least 8 characters.'
        elif not email:
            error = 'Email is required.'
        else:
            conn = get_users_db_connection()
            try:
                conn.execute(
                    'INSERT INTO users (name, email, password) VALUES (?, ?, ?)',
                    (name, email, generate_password_hash(password))
                )
                conn.commit()
                conn.close()
                return redirect(url_for('login', created='1'))
            except sqlite3.IntegrityError:
                conn.close()
                error = 'An account with that email already exists.'

    return render_template("signup.html", show_footer=False, error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(port= 5001, debug=True)
