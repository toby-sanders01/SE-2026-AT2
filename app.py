import sqlite3
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"
USERS_DB_PATH = 'users.db'
ITEMS_DB_PATH = 'items.db'
ITEM_IMAGES_DIR = Path('item_images')
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}


def init_users_db():
    conn = sqlite3.connect(USERS_DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        )
    ''')

    user_columns = [column[1] for column in c.execute("PRAGMA table_info(users)").fetchall()]
    if 'is_admin' not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    admin_count = c.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]
    if admin_count == 0:
        first_user = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if first_user:
            c.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (first_user[0],))

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

    ITEM_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    conn.commit()
    conn.close()


def get_upload_extension(filename):
    safe_name = secure_filename(filename or '')
    extension = Path(safe_name).suffix.lower()
    if extension in ALLOWED_IMAGE_EXTENSIONS:
        return extension
    return None


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
        "current_user_name": user_name,
        "current_user_is_admin": bool(session.get('is_admin'))
    }


@app.route('/')
def index():
    return render_template("index.html", show_footer=True, show_login=True)


@app.route('/item_images/<path:filename>')
def item_image(filename):
    return send_from_directory(ITEM_IMAGES_DIR, filename)


@app.route('/user')
def user():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, name, email, is_admin FROM users WHERE id = ?',
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
    session['is_admin'] = bool(db_user['is_admin'])
    return render_template(
        "user.html",
        show_footer=True,
        user_email=db_user['email'],
        user_name=user_name.capitalize(),
        items=items
    )


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, name, email, is_admin FROM users WHERE id = ?',
        (session.get('user_id'),)
    ).fetchone()

    if not db_user:
        users_conn.close()
        session.clear()
        return redirect(url_for('login'))

    if not db_user['is_admin']:
        users_conn.close()
        return redirect(url_for('user'))

    user_name = (db_user['name'] or '').strip()
    if not user_name:
        user_name = db_user['email'].split('@', 1)[0]

    error = None
    success = None

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        tag = request.form.get('tag', '').strip()
        image = request.form.get('image', '').strip()
        description = request.form.get('description', '').strip()
        stock_remaining_raw = request.form.get('stock_remaining', '').strip()
        image_file = request.files.get('image_file')
        upload_extension = None
        uploaded_filename = ''

        if image_file and image_file.filename:
            uploaded_filename = image_file.filename.strip()

        if not title:
            error = 'Item title is required.'
        elif not tag:
            error = 'Item tag is required.'
        elif uploaded_filename:
            upload_extension = get_upload_extension(uploaded_filename)
            if not upload_extension:
                error = 'Upload a valid image file: png, jpg, jpeg, gif, webp, or svg.'

        if error is None:
            try:
                stock_remaining = int(stock_remaining_raw)
                if stock_remaining < 0:
                    raise ValueError
            except ValueError:
                error = 'Stock remaining must be a non-negative whole number.'

        if error is None:
            image_value = image or 'small-logo.png'
            items_conn = get_items_db_connection()
            try:
                insert_cursor = items_conn.execute(
                    '''
                    INSERT INTO items (user_id, image, stock_remaining, title, tag, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (None, image_value, stock_remaining, title, tag, description)
                )

                if uploaded_filename and image_file and upload_extension:
                    unique_filename = f"{insert_cursor.lastrowid}{upload_extension}"
                    save_path = ITEM_IMAGES_DIR / unique_filename
                    image_file.save(save_path)
                    image_value = f"/item_images/{unique_filename}"
                    items_conn.execute(
                        "UPDATE items SET image = ? WHERE id = ?",
                        (image_value, insert_cursor.lastrowid)
                    )

                items_conn.commit()
                success = 'Item created successfully.'
            except OSError:
                items_conn.rollback()
                error = 'Could not save uploaded image file.'
            items_conn.close()

    users_conn.close()
    session['user_email'] = db_user['email']
    session['user_name'] = user_name
    session['is_admin'] = bool(db_user['is_admin'])
    return render_template("admin.html", show_footer=True, error=error, success=success)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    success = "Account created. You can log in now." if request.args.get('created') == '1' else None

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        conn = get_users_db_connection()
        user = conn.execute(
            'SELECT id, name, email, password, is_admin FROM users WHERE email = ?',
            (email,)
        ).fetchone()
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
                session['is_admin'] = bool(user['is_admin'])
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
                first_account = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                if first_account:
                    conn.execute(
                        'INSERT INTO users (name, email, password, is_admin) VALUES (?, ?, ?, 1)',
                        (name, email, generate_password_hash(password))
                    )
                else:
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
