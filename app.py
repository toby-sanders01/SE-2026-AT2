import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from time import time
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, make_response
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"
USERS_DB_PATH = 'users.db'
ITEMS_DB_PATH = 'items.db'
ITEM_IMAGES_DIR = Path('item_images')
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}
RATE_LIMIT_CONFIG = {
    "login": (5, 60),
    "signup": (3, 300),
    "item_changes": (30, 60),
    "admin_user_changes": (20, 60)
}
RATE_LIMIT_EVENTS = defaultdict(deque)

# Rate Limiting programmed by Codex
def get_rate_limit_identity():
    user_id = session.get('user_id')
    if user_id:
        return f"user:{user_id}"

    forwarded_for = request.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        client_ip = forwarded_for.split(',', 1)[0].strip()
    else:
        client_ip = request.remote_addr or 'unknown'
    return f"ip:{client_ip}"


def consume_rate_limit(bucket_name):
    limit, window_seconds = RATE_LIMIT_CONFIG[bucket_name]
    now = time()
    bucket_key = f"{bucket_name}:{get_rate_limit_identity()}"
    events = RATE_LIMIT_EVENTS[bucket_key]
    cutoff = now - window_seconds

    while events and events[0] <= cutoff:
        events.popleft()

    if len(events) >= limit:
        retry_after = max(1, int(window_seconds - (now - events[0])))
        response = make_response(
            render_template(
                "429.html",
                #show_footer=True,
                show_login=True,
                retry_after=retry_after
            ),
            429
        )
        response.headers["Retry-After"] = str(retry_after)
        return response

    events.append(now)
    return None


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

    # admin_count = c.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]
    # if admin_count == 0:
    #     first_user = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    #     if first_user:
    #         c.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (first_user[0],))

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

    c.execute('''
        CREATE TABLE IF NOT EXISTS item_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            admin_user_id INTEGER,
            action TEXT NOT NULL,
            item_id INTEGER,
            status TEXT NOT NULL,
            old_title TEXT,
            new_title TEXT,
            old_tag TEXT,
            new_tag TEXT,
            old_description TEXT,
            new_description TEXT,
            old_stock INTEGER,
            stock_change INTEGER,
            new_stock INTEGER,
            old_image TEXT,
            new_image TEXT,
            error_message TEXT NOT NULL DEFAULT ''
        )
    ''')
    c.execute(
        'CREATE INDEX IF NOT EXISTS idx_item_audit_logs_created_at ON item_audit_logs(created_at DESC)'
    )
    c.execute(
        'CREATE INDEX IF NOT EXISTS idx_item_audit_logs_item_id ON item_audit_logs(item_id)'
    )
    c.execute(
        'CREATE INDEX IF NOT EXISTS idx_item_audit_logs_admin_user_id ON item_audit_logs(admin_user_id)'
    )
    c.execute(
        'CREATE INDEX IF NOT EXISTS idx_item_audit_logs_action ON item_audit_logs(action)'
    )

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


def write_item_audit_log(
    admin_user_id,
    action,
    status,
    item_id=None,
    old_title=None,
    new_title=None,
    old_tag=None,
    new_tag=None,
    old_description=None,
    new_description=None,
    old_stock=None,
    stock_change=None,
    new_stock=None,
    old_image=None,
    new_image=None,
    error_message=''
):
    items_conn = get_items_db_connection()
    items_conn.execute(
        '''
        INSERT INTO item_audit_logs (
            created_at,
            admin_user_id,
            action,
            item_id,
            status,
            old_title,
            new_title,
            old_tag,
            new_tag,
            old_description,
            new_description,
            old_stock,
            stock_change,
            new_stock,
            old_image,
            new_image,
            error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            datetime.now(timezone.utc).isoformat(),
            admin_user_id,
            action,
            item_id,
            status,
            old_title,
            new_title,
            old_tag,
            new_tag,
            old_description,
            new_description,
            old_stock,
            stock_change,
            new_stock,
            old_image,
            new_image,
            error_message
        )
    )
    items_conn.commit()
    items_conn.close()


def format_audit_timestamp(timestamp_value):
    if not timestamp_value:
        return '-'
    try:
        parsed = datetime.fromisoformat(timestamp_value)
    except ValueError:
        return timestamp_value
    return parsed.strftime('%d %b %Y, %I:%M:%S %p UTC')


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


def normalize_user_role_filter(value):
    role_filter = (value or 'all').strip().lower()
    allowed_role_filters = {'all', 'admin', 'user'}
    if role_filter not in allowed_role_filters:
        return 'all'
    return role_filter


def filter_users(users, search_query, role_filter):
    filtered_users = users

    if search_query:
        search_lower = search_query.lower()
        filtered_users = [
            user for user in filtered_users
            if search_lower in (user['name'] or '').lower()
            or search_lower in (user['email'] or '').lower()
        ]

    if role_filter != 'all':
        target_admin_value = 1 if role_filter == 'admin' else 0
        filtered_users = [
            user for user in filtered_users
            if int(user['is_admin']) == target_admin_value
        ]

    return filtered_users

# Codex - Used to build modal cards
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

def build_user_modal_state(all_users):
    user_feedback = None
    user_modal = None
    user_confirmation = None

    user_status = request.args.get('user_status', '').strip()
    user_modal_id_raw = request.args.get('user_modal_id', '').strip()
    user_modal_id = None

    if user_modal_id_raw:
        try:
            parsed_user_modal_id = int(user_modal_id_raw)
            if parsed_user_modal_id > 0:
                user_modal_id = parsed_user_modal_id
        except ValueError:
            user_modal_id = None

    if user_modal_id is not None:
        for user in all_users:
            if user['id'] == user_modal_id:
                user_modal = user
                break

    if user_status == 'permission_updated':
        user_feedback = {
            "type": "success",
            "message": "User permissions updated successfully."
        }
    elif user_status == 'user_not_found':
        user_feedback = {
            "type": "error",
            "message": "The selected user could not be found."
        }
    elif user_status == 'invalid_permission':
        user_feedback = {
            "type": "error",
            "message": "Invalid permission value."
        }
    elif user_status == 'cannot_demote_self':
        user_feedback = {
            "type": "error",
            "message": "You cannot remove your own admin permission."
        }
    elif user_status == 'last_admin':
        user_feedback = {
            "type": "error",
            "message": "At least one admin must remain."
        }
    elif user_status == 'cannot_delete_self':
        user_feedback = {
            "type": "error",
            "message": "You cannot delete your own account."
        }
    elif user_status == 'user_deleted':
        user_feedback = {
            "type": "success",
            "message": "User removed successfully."
        }

    pending_user_action = request.args.get('pending_user_action', '').strip()
    pending_user_id_raw = request.args.get('pending_user_id', '').strip()
    pending_user_is_admin_raw = request.args.get('pending_user_is_admin', '').strip()
    if pending_user_action and pending_user_id_raw:
        try:
            pending_user_id = int(pending_user_id_raw)
        except ValueError:
            pending_user_id = None

        if isinstance(pending_user_id, int) and pending_user_id > 0:
            for user in all_users:
                if user['id'] == pending_user_id:
                    user_modal = user
                    break

        if user_modal and pending_user_action == 'permission' and pending_user_is_admin_raw:
            try:
                pending_user_is_admin = int(pending_user_is_admin_raw)
            except ValueError:
                pending_user_is_admin = None
            if pending_user_is_admin in {0, 1}:
                user_confirmation = {
                    "action": "permission",
                    "user_id": pending_user_id,
                    "target_is_admin": pending_user_is_admin
                }
        elif user_modal and pending_user_action == 'delete':
            user_confirmation = {
                "action": "delete",
                "user_id": pending_user_id
            }

    show_user_modal_on_load = bool(
        user_confirmation
        or (user_feedback is not None and user_modal is not None)
    )
    return {
        "user_feedback": user_feedback,
        "user_modal": user_modal,
        "user_confirmation": user_confirmation,
        "show_user_modal_on_load": show_user_modal_on_load
    }


# Ensure both tables exist on startup.
init_users_db()
init_items_db()


@app.context_processor
# This injects authentication state into all templates, so we can show/hide elements based on login status and user role.
def inject_auth_state(): 
    user_name = (session.get('user_name') or '').strip().capitalize()
    if not user_name and session.get('user_email'):
        user_name = session['user_email'].split('@', 1)[0]
    if not user_name:
        user_name = "User"

    return {
        "logged_in": 'user_id' in session,
        "current_user_name": user_name,
        "current_user_is_admin": bool(session.get('is_admin'))
    }


@app.errorhandler(404)
def page_not_found(error):
    if session.get('is_admin'):
        primary_endpoint = 'admin'
        primary_label = 'Go to Admin Dashboard'
    elif 'user_id' in session:
        primary_endpoint = 'user'
        primary_label = 'Go to Dashboard'
    else:
        primary_endpoint = 'index'
        primary_label = 'Go to Home'

    return (
        render_template(
            "404.html",
            show_footer=True,
            show_login=True,
            primary_endpoint=primary_endpoint,
            primary_label=primary_label
        ),
        404
    )


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
    
    if session.get('is_admin'):
        return redirect(url_for('admin'))

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

    rate_limit_response = consume_rate_limit("item_changes")
    if rate_limit_response:
        return rate_limit_response

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
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_decrease',
            status='failure',
            error_message='Invalid item id.'
        )
        return redirect_back(stock_status='invalid_amount')

    try:
        decrease_amount = int(decrease_amount_raw)
        if decrease_amount < 1:
            raise ValueError
    except ValueError:
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_decrease',
            status='failure',
            item_id=item_id,
            error_message='Invalid decrease amount.'
        )
        return redirect_back(stock_status='invalid_amount', modal_item_id=item_id)

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id, title, tag, description, image, stock_remaining
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id'])
    ).fetchone()

    if not item:
        items_conn.close()
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_decrease',
            status='failure',
            item_id=item_id,
            error_message='Item not found.'
        )
        return redirect_back(stock_status='item_not_found')
    
    if item['stock_remaining'] == 0:
        items_conn.close()
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_decrease',
            status='failure',
            item_id=item_id,
            old_title=item['title'],
            old_tag=item['tag'],
            old_description=item['description'],
            old_stock=item['stock_remaining'],
            old_image=item['image'],
            error_message='No items remaining.'
        )
        return redirect_back(stock_status='zero', modal_item_id=item_id)

    if decrease_amount > item['stock_remaining']:
        items_conn.close()
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_decrease',
            status='failure',
            item_id=item_id,
            old_title=item['title'],
            old_tag=item['tag'],
            old_description=item['description'],
            old_stock=item['stock_remaining'],
            old_image=item['image'],
            stock_change=-decrease_amount,
            error_message='Decrease amount exceeds remaining stock.'
        )
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

    write_item_audit_log(
        admin_user_id=db_user['id'],
        action='stock_decrease',
        status='success',
        item_id=item_id,
        old_title=item['title'],
        new_title=item['title'],
        old_tag=item['tag'],
        new_tag=item['tag'],
        old_description=item['description'],
        new_description=item['description'],
        old_stock=item['stock_remaining'],
        stock_change=-decrease_amount,
        new_stock=item['stock_remaining'] - decrease_amount,
        old_image=item['image'],
        new_image=item['image']
    )

    return redirect_back(stock_status='decreased', stock_amount=decrease_amount, modal_item_id=item_id)


@app.route('/add-stock', methods=['POST'])
def add_stock():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    rate_limit_response = consume_rate_limit("item_changes")
    if rate_limit_response:
        return rate_limit_response

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
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_add',
            status='failure',
            error_message='Invalid item id or add amount.'
        )
        return redirect_back(stock_status='invalid_amount', modal_item_id=item_id_raw)

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id, title, tag, description, image, stock_remaining
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id'])
    ).fetchone()

    if not item:
        items_conn.close()
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_add',
            status='failure',
            item_id=item_id,
            error_message='Item not found.'
        )
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

    write_item_audit_log(
        admin_user_id=db_user['id'],
        action='stock_add',
        status='success',
        item_id=item_id,
        old_title=item['title'],
        new_title=item['title'],
        old_tag=item['tag'],
        new_tag=item['tag'],
        old_description=item['description'],
        new_description=item['description'],
        old_stock=item['stock_remaining'],
        stock_change=add_amount,
        new_stock=item['stock_remaining'] + add_amount,
        old_image=item['image'],
        new_image=item['image']
    )
    return redirect_back(stock_status='added', stock_amount=add_amount, modal_item_id=item_id)


@app.route('/edit-item', methods=['POST'])
def edit_item():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    rate_limit_response = consume_rate_limit("item_changes")
    if rate_limit_response:
        return rate_limit_response

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
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='edit',
            status='failure',
            error_message='Invalid item id.'
        )
        return redirect_back(stock_status='item_not_found')

    if not title or not tag:
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='edit',
            status='failure',
            item_id=item_id,
            new_title=title or None,
            new_tag=tag or None,
            new_description=description or None,
            error_message='Title and tag are required.'
        )
        return redirect_back(stock_status='invalid_amount', modal_item_id=item_id)

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id, title, tag, description, image, stock_remaining
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id'])
    ).fetchone()

    if not item:
        items_conn.close()
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='edit',
            status='failure',
            item_id=item_id,
            new_title=title,
            new_tag=tag,
            new_description=description,
            error_message='Item not found.'
        )
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

    write_item_audit_log(
        admin_user_id=db_user['id'],
        action='edit',
        status='success',
        item_id=item_id,
        old_title=item['title'],
        new_title=title,
        old_tag=item['tag'],
        new_tag=tag,
        old_description=item['description'],
        new_description=description,
        old_stock=item['stock_remaining'],
        new_stock=item['stock_remaining'],
        old_image=item['image'],
        new_image=item['image']
    )
    return redirect_back(stock_status='edited', modal_item_id=item_id)


@app.route('/delete-item', methods=['POST'])
def delete_item():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    rate_limit_response = consume_rate_limit("item_changes")
    if rate_limit_response:
        return rate_limit_response

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
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='delete',
            status='failure',
            error_message='Invalid item id.'
        )
        return redirect_back(stock_status='item_not_found')

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id, title, tag, description, image, stock_remaining
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id'])
    ).fetchone()

    if not item:
        items_conn.close()
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='delete',
            status='failure',
            item_id=item_id,
            error_message='Item not found.'
        )
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

    write_item_audit_log(
        admin_user_id=db_user['id'],
        action='delete',
        status='success',
        item_id=item_id,
        old_title=item['title'],
        old_tag=item['tag'],
        old_description=item['description'],
        old_stock=item['stock_remaining'],
        old_image=item['image']
    )
    return redirect_back(stock_status='deleted')


@app.route('/update-user-permission', methods=['POST'])
def update_user_permission():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    rate_limit_response = consume_rate_limit("admin_user_changes")
    if rate_limit_response:
        return rate_limit_response

    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (session.get('user_id'),)
    ).fetchone()

    if not db_user:
        users_conn.close()
        session.clear()
        return redirect(url_for('login'))
    if not db_user['is_admin']:
        users_conn.close()
        return redirect(url_for('user'))

    target_user_id_raw = request.form.get('target_user_id', '').strip()
    target_is_admin_raw = request.form.get('target_is_admin', '').strip()
    confirm_action = request.form.get('confirm_action', '').strip() == '1'
    return_endpoint = request.form.get('return_endpoint', 'admin').strip()
    if return_endpoint not in {'admin'}:
        return_endpoint = 'admin'

    def redirect_back(**params):
        return redirect(url_for(return_endpoint, **params))

    try:
        target_user_id = int(target_user_id_raw)
        target_is_admin = int(target_is_admin_raw)
        if target_user_id < 1 or target_is_admin not in {0, 1}:
            raise ValueError
    except ValueError:
        users_conn.close()
        return redirect_back(user_status='invalid_permission')

    target_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (target_user_id,)
    ).fetchone()
    if not target_user:
        users_conn.close()
        return redirect_back(user_status='user_not_found')

    if not confirm_action:
        users_conn.close()
        return redirect_back(
            pending_user_action='permission',
            pending_user_id=target_user_id,
            pending_user_is_admin=target_is_admin
        )

    if target_user_id == db_user['id'] and target_is_admin == 0:
        users_conn.close()
        return redirect_back(user_status='cannot_demote_self', user_modal_id=target_user_id)

    if int(target_user['is_admin']) == 1 and target_is_admin == 0:
        admin_count = users_conn.execute(
            'SELECT COUNT(*) FROM users WHERE is_admin = 1'
        ).fetchone()[0]
        if admin_count <= 1:
            users_conn.close()
            return redirect_back(user_status='last_admin', user_modal_id=target_user_id)

    users_conn.execute(
        'UPDATE users SET is_admin = ? WHERE id = ?',
        (target_is_admin, target_user_id)
    )
    users_conn.commit()
    users_conn.close()
    return redirect_back(user_status='permission_updated', user_modal_id=target_user_id)


@app.route('/delete-user', methods=['POST'])
def delete_user():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    rate_limit_response = consume_rate_limit("admin_user_changes")
    if rate_limit_response:
        return rate_limit_response

    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (session.get('user_id'),)
    ).fetchone()

    if not db_user:
        users_conn.close()
        session.clear()
        return redirect(url_for('login'))
    if not db_user['is_admin']:
        users_conn.close()
        return redirect(url_for('user'))

    target_user_id_raw = request.form.get('target_user_id', '').strip()
    confirm_action = request.form.get('confirm_action', '').strip() == '1'
    return_endpoint = request.form.get('return_endpoint', 'admin').strip()
    if return_endpoint != 'admin':
        return_endpoint = 'admin'

    def redirect_back(**params):
        return redirect(url_for(return_endpoint, **params))

    try:
        target_user_id = int(target_user_id_raw)
        if target_user_id < 1:
            raise ValueError
    except ValueError:
        users_conn.close()
        return redirect_back(user_status='user_not_found')

    target_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (target_user_id,)
    ).fetchone()
    if not target_user:
        users_conn.close()
        return redirect_back(user_status='user_not_found')

    if not confirm_action:
        users_conn.close()
        return redirect_back(
            pending_user_action='delete',
            pending_user_id=target_user_id
        )

    if target_user_id == db_user['id']:
        users_conn.close()
        return redirect_back(user_status='cannot_delete_self', user_modal_id=target_user_id)

    if int(target_user['is_admin']) == 1:
        admin_count = users_conn.execute(
            'SELECT COUNT(*) FROM users WHERE is_admin = 1'
        ).fetchone()[0]
        if admin_count <= 1:
            users_conn.close()
            return redirect_back(user_status='last_admin', user_modal_id=target_user_id)

    items_conn = get_items_db_connection()
    items_conn.execute(
        'UPDATE items SET user_id = NULL WHERE user_id = ?',
        (target_user_id,)
    )
    items_conn.commit()
    items_conn.close()

    users_conn.execute(
        'DELETE FROM users WHERE id = ?',
        (target_user_id,)
    )
    users_conn.commit()
    users_conn.close()
    return redirect_back(user_status='user_deleted')


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
        rate_limit_response = consume_rate_limit("item_changes")
        if rate_limit_response:
            users_conn.close()
            return rate_limit_response

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
            write_item_audit_log(
                admin_user_id=db_user['id'],
                action='create',
                status='failure',
                new_title=title or None,
                new_tag=tag or None,
                new_description=description or None,
                error_message=error
            )
        elif not tag:
            error = 'Item tag is required.'
            write_item_audit_log(
                admin_user_id=db_user['id'],
                action='create',
                status='failure',
                new_title=title or None,
                new_tag=tag or None,
                new_description=description or None,
                error_message=error
            )
        elif uploaded_filename:
            upload_extension = get_upload_extension(uploaded_filename)
            if not upload_extension:
                error = 'Upload a valid image file: png, jpg, jpeg, gif, webp, or svg.'
                write_item_audit_log(
                    admin_user_id=db_user['id'],
                    action='create',
                    status='failure',
                    new_title=title or None,
                    new_tag=tag or None,
                    new_description=description or None,
                    error_message=error
                )

        if error is None:
            try:
                stock_remaining = int(stock_remaining_raw)
                if stock_remaining < 0:
                    raise ValueError
            except ValueError:
                error = 'Stock remaining must be a non-negative whole number.'
                write_item_audit_log(
                    admin_user_id=db_user['id'],
                    action='create',
                    status='failure',
                    new_title=title or None,
                    new_tag=tag or None,
                    new_description=description or None,
                    error_message=error
                )

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
                write_item_audit_log(
                    admin_user_id=db_user['id'],
                    action='create',
                    status='success',
                    item_id=insert_cursor.lastrowid,
                    new_title=title,
                    new_tag=tag,
                    new_description=description,
                    new_stock=stock_remaining,
                    new_image=image_value
                )
                success = 'Item created successfully.'
            except OSError:
                items_conn.rollback()
                error = 'Could not save uploaded image file.'
                write_item_audit_log(
                    admin_user_id=db_user['id'],
                    action='create',
                    status='failure',
                    new_title=title or None,
                    new_tag=tag or None,
                    new_description=description or None,
                    new_stock=stock_remaining if 'stock_remaining' in locals() else None,
                    error_message=error
                )
            items_conn.close()

    search_query = request.args.get('q', '').strip()
    stock_filter = normalize_stock_filter(request.args.get('stock', 'all'))
    visible_items = get_visible_items_for_user(db_user['id'])
    items = filter_items(visible_items, search_query, stock_filter)
    item_modal_state = build_item_modal_state(items)

    user_search_query = request.args.get('user_q', '').strip()
    user_role_filter = normalize_user_role_filter(request.args.get('user_role', 'all'))
    all_users = users_conn.execute(
        '''
        SELECT id, name, email, is_admin
        FROM users
        ORDER BY id
        '''
    ).fetchall()
    filtered_users = filter_users(all_users, user_search_query, user_role_filter)
    user_modal_state = build_user_modal_state(all_users)
    user_identity_by_id = {}
    for user in all_users:
        display_name = (user['name'] or '').strip() or user['email']
        user_identity_by_id[user['id']] = f"{display_name} ({user['email']})"

    items_conn = get_items_db_connection()
    item_audit_logs = items_conn.execute(
        '''
        SELECT
            id,
            created_at,
            admin_user_id,
            action,
            item_id,
            status,
            old_title,
            new_title,
            old_tag,
            new_tag,
            old_stock,
            stock_change,
            new_stock,
            error_message
        FROM item_audit_logs
        WHERE action IN ('stock_add', 'stock_decrease')
        ORDER BY id DESC
        LIMIT 100
        '''
    ).fetchall()
    items_conn.close()
    item_audit_logs = [
        {
            **dict(log),
            "created_at_display": format_audit_timestamp(log['created_at']),
            "actor_display": user_identity_by_id.get(log['admin_user_id'], f"User #{log['admin_user_id']}" if log['admin_user_id'] else '-')
        }
        for log in item_audit_logs
    ]

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
        admin_users=filtered_users,
        user_search_query=user_search_query,
        selected_user_role_filter=user_role_filter,
        stock_feedback=item_modal_state['stock_feedback'],
        stock_confirmation=item_modal_state['stock_confirmation'],
        action_confirmation=item_modal_state['action_confirmation'],
        modal_item=item_modal_state['modal_item'],
        show_modal_on_load=item_modal_state['show_modal_on_load'],
        user_feedback=user_modal_state['user_feedback'],
        user_confirmation=user_modal_state['user_confirmation'],
        user_modal=user_modal_state['user_modal'],
        show_user_modal_on_load=user_modal_state['show_user_modal_on_load'],
        item_audit_logs=item_audit_logs
    )


@app.route('/login', methods=['GET', 'POST'])
def login():

    if 'user_id' in session:
        if session.get('is_admin'):
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('user'))

    error = None
    success = "Account created. You can log in now." if request.args.get('created') == '1' else None

    if request.method == 'POST':
        rate_limit_response = consume_rate_limit("login")
        if rate_limit_response:
            return rate_limit_response

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

    if 'user_id' in session:
        if session.get('is_admin'):
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('user'))

    error = None

    if request.method == 'POST':
        rate_limit_response = consume_rate_limit("signup")
        if rate_limit_response:
            return rate_limit_response

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
        elif not email or '@' not in email:
            error = 'Proper email is required.'
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
    return redirect(url_for('index'))


# if __name__ == '__main__':
#     app.run(port= 5001, debug=True)
