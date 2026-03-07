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


def get_visible_items_for_user(user_id):
    items_conn = get_items_db_connection()
    items = items_conn.execute(
        '''
        SELECT id, image, stock_remaining, title, tag, description
        FROM items
        WHERE user_id = ? OR user_id IS NULL
        ORDER BY id
        ''',
        (user_id,)
    ).fetchall()
    items_conn.close()
    return items


def normalize_stock_filter(value):
    stock_filter = (value or 'all').strip().lower()
    allowed_stock_filters = {'all', 'in-stock', 'low-stock', 'out-of-stock'}
    if stock_filter not in allowed_stock_filters:
        return 'all'
    return stock_filter


def filter_items(items, search_query, stock_filter):
    filtered_items = items

    if search_query:
        search_lower = search_query.lower()
        filtered_items = [
            item for item in filtered_items
            if search_lower in (item['title'] or '').lower()
            or search_lower in (item['tag'] or '').lower()
            or search_lower in (item['description'] or '').lower()
        ]

    if stock_filter != 'all':
        stock_filtered = []
        for item in filtered_items:
            stock_remaining = item['stock_remaining']
            status = 'out-of-stock'
            if stock_remaining > 10:
                status = 'in-stock'
            elif stock_remaining > 0:
                status = 'low-stock'

            if status == stock_filter:
                stock_filtered.append(item)
        filtered_items = stock_filtered

    return filtered_items


def build_item_modal_state(items):
    stock_feedback = None
    modal_item = None
    action_confirmation = None
    stock_status = request.args.get('stock_status', '').strip()
    modal_item_id_raw = request.args.get('modal_item_id', '').strip()
    modal_item_id = None

    if modal_item_id_raw:
        try:
            parsed_modal_item_id = int(modal_item_id_raw)
            if parsed_modal_item_id > 0:
                modal_item_id = parsed_modal_item_id
        except ValueError:
            modal_item_id = None

    if modal_item_id is not None:
        for item in items:
            if item['id'] == modal_item_id:
                modal_item = item
                break

    if stock_status == 'decreased':
        stock_amount_raw = request.args.get('stock_amount', '').strip()
        try:
            stock_amount = int(stock_amount_raw)
        except ValueError:
            stock_amount = 0

        if stock_amount > 0:
            stock_feedback = {
                "type": "success",
                "message": f"Stock decreased by {stock_amount}."
            }
        else:
            stock_feedback = {
                "type": "success",
                "message": "Stock decreased."
            }
    elif stock_status == 'invalid_amount':
        stock_feedback = {
            "type": "error",
            "message": "Enter a whole number greater than 0."
        }
    elif stock_status == 'item_not_found':
        stock_feedback = {
            "type": "error",
            "message": "The selected item could not be found."
        }
    elif stock_status == 'zero':
        if modal_item:
            stock_feedback = {
                "type": "error",
                "message": "No items remaining."
            }
    elif stock_status == 'insufficient':
        if modal_item:
            stock_feedback = {
                "type": "error",
                "message": f"Only {modal_item['stock_remaining']} items remaining."
            }
        else:
            stock_feedback = {
                "type": "error",
                "message": "Decrease amount cannot be more than items remaining."
            }
    elif stock_status == 'added':
        stock_amount_raw = request.args.get('stock_amount', '').strip()
        try:
            stock_amount = int(stock_amount_raw)
        except ValueError:
            stock_amount = 0
        if stock_amount > 0:
            stock_feedback = {
                "type": "success",
                "message": f"Stock increased by {stock_amount}."
            }
        else:
            stock_feedback = {
                "type": "success",
                "message": "Stock increased."
            }
    elif stock_status == 'edited':
        stock_feedback = {
            "type": "success",
            "message": "Item updated successfully."
        }
    elif stock_status == 'deleted':
        stock_feedback = {
            "type": "success",
            "message": "Item deleted successfully."
        }

    stock_confirmation = None
    confirm_item_id_raw = request.args.get('confirm_item_id', '').strip()
    confirm_amount_raw = request.args.get('confirm_amount', '').strip()

    if confirm_item_id_raw and confirm_amount_raw:
        try:
            confirm_item_id = int(confirm_item_id_raw)
            confirm_amount = int(confirm_amount_raw)
        except ValueError:
            confirm_item_id = None
            confirm_amount = None

        if (
            isinstance(confirm_item_id, int)
            and isinstance(confirm_amount, int)
            and confirm_item_id > 0
            and confirm_amount > 5
        ):
            for item in items:
                if item['id'] == confirm_item_id:
                    modal_item = item
                    stock_confirmation = {
                        "item_id": confirm_item_id,
                        "amount": confirm_amount,
                        "item_title": item['title']
                    }
                    break

    pending_action = request.args.get('pending_action', '').strip()
    pending_item_id_raw = request.args.get('pending_item_id', '').strip()
    if pending_action and pending_item_id_raw:
        try:
            pending_item_id = int(pending_item_id_raw)
        except ValueError:
            pending_item_id = None

        if isinstance(pending_item_id, int) and pending_item_id > 0:
            for item in items:
                if item['id'] == pending_item_id:
                    modal_item = item
                    break

        if modal_item:
            if pending_action == 'add':
                pending_amount_raw = request.args.get('pending_amount', '').strip()
                try:
                    pending_amount = int(pending_amount_raw)
                except ValueError:
                    pending_amount = None
                if isinstance(pending_amount, int) and pending_amount > 0:
                    action_confirmation = {
                        "action": "add",
                        "item_id": pending_item_id,
                        "amount": pending_amount
                    }
            elif pending_action == 'edit':
                action_confirmation = {
                    "action": "edit",
                    "item_id": pending_item_id,
                    "title": request.args.get('pending_title', '').strip(),
                    "tag": request.args.get('pending_tag', '').strip(),
                    "description": request.args.get('pending_description', '').strip()
                }
            elif pending_action == 'delete':
                action_confirmation = {
                    "action": "delete",
                    "item_id": pending_item_id
                }

    show_modal_on_load = bool(
        stock_confirmation
        or action_confirmation
        or (stock_feedback is not None and modal_item is not None)
    )
    return {
        "stock_feedback": stock_feedback,
        "stock_confirmation": stock_confirmation,
        "action_confirmation": action_confirmation,
        "modal_item": modal_item,
        "show_modal_on_load": show_modal_on_load
    }


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

    search_query = request.args.get('q', '').strip()
    stock_filter = normalize_stock_filter(request.args.get('stock', 'all'))

    visible_items = get_visible_items_for_user(db_user['id'])
    items = filter_items(visible_items, search_query, stock_filter)
    item_modal_state = build_item_modal_state(items)

    users_conn.close()

    session['user_email'] = db_user['email']
    session['user_name'] = user_name
    session['is_admin'] = bool(db_user['is_admin'])
    return render_template(
        "user.html",
        show_footer=True,
        user_email=db_user['email'],
        user_name=user_name.capitalize(),
        items=items,
        search_query=search_query,
        selected_stock_filter=stock_filter,
        stock_feedback=item_modal_state['stock_feedback'],
        stock_confirmation=item_modal_state['stock_confirmation'],
        action_confirmation=item_modal_state['action_confirmation'],
        modal_item=item_modal_state['modal_item'],
        show_modal_on_load=item_modal_state['show_modal_on_load']
    )


@app.route('/decrease-stock', methods=['POST'])
def decrease_stock():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (session.get('user_id'),)
    ).fetchone()
    users_conn.close()

    if not db_user:
        session.clear()
        return redirect(url_for('login'))

    item_id_raw = request.form.get('item_id', '').strip()
    decrease_amount_raw = request.form.get('decrease_amount', '').strip()
    confirm_large = request.form.get('confirm_large', '').strip() == '1'
    return_endpoint = request.form.get('return_endpoint', 'user').strip()
    if return_endpoint not in {'user', 'admin'}:
        return_endpoint = 'user'

    def redirect_back(**params):
        return redirect(url_for(return_endpoint, **params))

    try:
        item_id = int(item_id_raw)
        if item_id < 1:
            raise ValueError
    except ValueError:
        return redirect_back(stock_status='invalid_amount')

    try:
        decrease_amount = int(decrease_amount_raw)
        if decrease_amount < 1:
            raise ValueError
    except ValueError:
        return redirect_back(stock_status='invalid_amount', modal_item_id=item_id)

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id, stock_remaining
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id'])
    ).fetchone()

    if not item:
        items_conn.close()
        return redirect_back(stock_status='item_not_found')
    
    if item['stock_remaining'] == 0:
        items_conn.close()
        return redirect_back(stock_status='zero', modal_item_id=item_id)

    if decrease_amount > item['stock_remaining']:
        items_conn.close()
        return redirect_back(stock_status='insufficient', modal_item_id=item_id)


    if decrease_amount > 5 and not confirm_large:
        items_conn.close()
        return redirect_back(confirm_item_id=item_id, confirm_amount=decrease_amount)

    items_conn.execute(
        'UPDATE items SET stock_remaining = stock_remaining - ? WHERE id = ?',
        (decrease_amount, item_id)
    )
    items_conn.commit()
    items_conn.close()

    return redirect_back(stock_status='decreased', stock_amount=decrease_amount, modal_item_id=item_id)


@app.route('/add-stock', methods=['POST'])
def add_stock():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (session.get('user_id'),)
    ).fetchone()
    users_conn.close()

    if not db_user:
        session.clear()
        return redirect(url_for('login'))
    if not db_user['is_admin']:
        return redirect(url_for('user'))

    item_id_raw = request.form.get('item_id', '').strip()
    add_amount_raw = request.form.get('add_amount', '').strip()
    confirm_action = request.form.get('confirm_action', '').strip() == '1'
    return_endpoint = request.form.get('return_endpoint', 'admin').strip()
    if return_endpoint not in {'user', 'admin'}:
        return_endpoint = 'admin'

    def redirect_back(**params):
        return redirect(url_for(return_endpoint, **params))

    try:
        item_id = int(item_id_raw)
        add_amount = int(add_amount_raw)
        if item_id < 1 or add_amount < 1:
            raise ValueError
    except ValueError:
        return redirect_back(stock_status='invalid_amount', modal_item_id=item_id_raw)

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id'])
    ).fetchone()

    if not item:
        items_conn.close()
        return redirect_back(stock_status='item_not_found')

    if not confirm_action:
        items_conn.close()
        return redirect_back(
            pending_action='add',
            pending_item_id=item_id,
            pending_amount=add_amount
        )

    items_conn.execute(
        'UPDATE items SET stock_remaining = stock_remaining + ? WHERE id = ?',
        (add_amount, item_id)
    )
    items_conn.commit()
    items_conn.close()
    return redirect_back(stock_status='added', stock_amount=add_amount, modal_item_id=item_id)


@app.route('/edit-item', methods=['POST'])
def edit_item():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (session.get('user_id'),)
    ).fetchone()
    users_conn.close()

    if not db_user:
        session.clear()
        return redirect(url_for('login'))
    if not db_user['is_admin']:
        return redirect(url_for('user'))

    item_id_raw = request.form.get('item_id', '').strip()
    title = request.form.get('title', '').strip()
    tag = request.form.get('tag', '').strip()
    description = request.form.get('description', '').strip()
    confirm_action = request.form.get('confirm_action', '').strip() == '1'
    return_endpoint = request.form.get('return_endpoint', 'admin').strip()
    if return_endpoint not in {'user', 'admin'}:
        return_endpoint = 'admin'

    def redirect_back(**params):
        return redirect(url_for(return_endpoint, **params))

    try:
        item_id = int(item_id_raw)
        if item_id < 1:
            raise ValueError
    except ValueError:
        return redirect_back(stock_status='item_not_found')

    if not title or not tag:
        return redirect_back(stock_status='invalid_amount', modal_item_id=item_id)

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id'])
    ).fetchone()

    if not item:
        items_conn.close()
        return redirect_back(stock_status='item_not_found')

    if not confirm_action:
        items_conn.close()
        return redirect_back(
            pending_action='edit',
            pending_item_id=item_id,
            pending_title=title,
            pending_tag=tag,
            pending_description=description
        )

    items_conn.execute(
        '''
        UPDATE items
        SET title = ?, tag = ?, description = ?
        WHERE id = ?
        ''',
        (title, tag, description, item_id)
    )
    items_conn.commit()
    items_conn.close()
    return redirect_back(stock_status='edited', modal_item_id=item_id)


@app.route('/delete-item', methods=['POST'])
def delete_item():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (session.get('user_id'),)
    ).fetchone()
    users_conn.close()

    if not db_user:
        session.clear()
        return redirect(url_for('login'))
    if not db_user['is_admin']:
        return redirect(url_for('user'))

    item_id_raw = request.form.get('item_id', '').strip()
    confirm_action = request.form.get('confirm_action', '').strip() == '1'
    return_endpoint = request.form.get('return_endpoint', 'admin').strip()
    if return_endpoint not in {'user', 'admin'}:
        return_endpoint = 'admin'

    def redirect_back(**params):
        return redirect(url_for(return_endpoint, **params))

    try:
        item_id = int(item_id_raw)
        if item_id < 1:
            raise ValueError
    except ValueError:
        return redirect_back(stock_status='item_not_found')

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id'])
    ).fetchone()

    if not item:
        items_conn.close()
        return redirect_back(stock_status='item_not_found')

    if not confirm_action:
        items_conn.close()
        return redirect_back(
            pending_action='delete',
            pending_item_id=item_id
        )

    items_conn.execute(
        'DELETE FROM items WHERE id = ?',
        (item_id,)
    )
    items_conn.commit()
    items_conn.close()
    return redirect_back(stock_status='deleted')


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

    search_query = request.args.get('q', '').strip()
    stock_filter = normalize_stock_filter(request.args.get('stock', 'all'))
    visible_items = get_visible_items_for_user(db_user['id'])
    items = filter_items(visible_items, search_query, stock_filter)
    item_modal_state = build_item_modal_state(items)

    users_conn.close()
    session['user_email'] = db_user['email']
    session['user_name'] = user_name
    session['is_admin'] = bool(db_user['is_admin'])
    return render_template(
        "admin.html",
        show_footer=True,
        error=error,
        success=success,
        items=items,
        search_query=search_query,
        selected_stock_filter=stock_filter,
        stock_feedback=item_modal_state['stock_feedback'],
        stock_confirmation=item_modal_state['stock_confirmation'],
        action_confirmation=item_modal_state['action_confirmation'],
        modal_item=item_modal_state['modal_item'],
        show_modal_on_load=item_modal_state['show_modal_on_load']
    )


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
                is_admin = bool(user['is_admin'])
                session['is_admin'] = is_admin
                if is_admin:
                    return redirect(url_for('admin'))
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
