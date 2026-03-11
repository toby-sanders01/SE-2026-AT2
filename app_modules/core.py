import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from .database_int import get_items_db_connection, get_users_db_connection

ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}

#misc. codex assistance throughout the file

# format to return results from service functions - made by Codex as part of restrcuturing
def make_result(ok, status, payload=None, redirect_params=None, error=None):
    return {
        'ok': ok,
        'status': status,
        'payload': payload or {},
        'redirect_params': redirect_params or {},
        'error': error,
    }

# formats name to display the users as
def get_display_name(user_row):
    display_name = (user_row['name'] or '').strip()
    if not display_name:
        display_name = user_row['email'].split('@', 1)[0]
    return display_name

# user db functions
def get_user_by_id(user_id):
    conn = get_users_db_connection()
    user = conn.execute(
        'SELECT id, name, email, is_admin FROM users WHERE id = ?',
        (user_id,),
    ).fetchone()
    conn.close()
    return user

# user db functions for login, signup, and session management
def get_user_for_login(email):
    conn = get_users_db_connection()
    user = conn.execute(
        'SELECT id, name, email, password, is_admin FROM users WHERE email = ?',
        (email,),
    ).fetchone()
    conn.close()
    return user

# gets all users to display in the admin dashboard
def get_all_users():
    users_conn = get_users_db_connection()
    users = users_conn.execute(
        '''
        SELECT id, name, email, is_admin
        FROM users
        ORDER BY id
        '''
    ).fetchall()
    users_conn.close()
    return users

# codex generated
def hydrate_session(session_obj, user_row):
    display_name = get_display_name(user_row)
    session_obj['user_id'] = user_row['id']
    session_obj['user_email'] = user_row['email']
    session_obj['user_name'] = display_name
    session_obj['is_admin'] = bool(user_row['is_admin'])

# codex generated
def refresh_session_identity(session_obj, user_row):
    session_obj['user_email'] = user_row['email']
    session_obj['user_name'] = get_display_name(user_row)
    session_obj['is_admin'] = bool(user_row['is_admin'])

#logic for processing what shows on the login form
def process_login(email, password):
    user = get_user_for_login(email)
    if not user:
        return make_result(False, 'no_account', error='No account found with that email.')

    stored_password = user['password']
    valid_password = check_password_hash(stored_password, password) or stored_password == password
    if not valid_password:
        return make_result(False, 'invalid_password', error='Incorrect password.')

    return make_result(True, 'authenticated', payload={'user': user})

# logic for processing the signup form, with validation and error handling
def process_signup(name, email, password, confirm_password):
    if password != confirm_password:
        return make_result(False, 'password_mismatch', error='Passwords do not match.')
    if not name:
        return make_result(False, 'name_required', error='Name is required.')
    if len(password) < 8:
        return make_result(False, 'password_too_short', error='Password must be at least 8 characters.')
    if not email or '@' not in email:
        return make_result(False, 'invalid_email', error='Proper email is required.')

    conn = get_users_db_connection()
    try:
        conn.execute(
            'INSERT INTO users (name, email, password) VALUES (?, ?, ?)',
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return make_result(False, 'duplicate_email', error='An account with that email already exists.')

    conn.close()
    return make_result(True, 'created', redirect_params={'created': '1'})

# validates image filename
def get_upload_extension(filename):
    safe_name = secure_filename(filename or '')
    extension = Path(safe_name).suffix.lower()
    if extension in ALLOWED_IMAGE_EXTENSIONS:
        return extension
    return None

# writes an audit log for changes
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
    error_message='',
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
            error_message,
        ),
    )
    items_conn.commit()
    items_conn.close()

# gets items
def get_visible_items_for_user(user_id):
    items_conn = get_items_db_connection()
    items = items_conn.execute(
        '''
        SELECT id, image, stock_remaining, title, tag, description
        FROM items
        WHERE user_id = ? OR user_id IS NULL
        ORDER BY id
        ''',
        (user_id,),
    ).fetchall()
    items_conn.close()
    return items

# displays audit log on admin dashboard
def get_stock_audit_logs(limit=100):
    items_conn = get_items_db_connection()
    logs = items_conn.execute(
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
        LIMIT ?
        ''',
        (limit,),
    ).fetchall()
    items_conn.close()
    return logs

# displays time in a readable format on the audit log
def format_audit_timestamp(timestamp_value):
    if not timestamp_value:
        return '-'
    try:
        parsed = datetime.fromisoformat(timestamp_value)
    except ValueError:
        return timestamp_value
    return parsed.strftime('%d %b %Y, %I:%M:%S %p UTC')

# creates the stock filter for the search bar
def normalize_stock_filter(value):
    stock_filter = (value or 'all').strip().lower()
    allowed_stock_filters = {'all', 'in-stock', 'low-stock', 'out-of-stock'}
    if stock_filter not in allowed_stock_filters:
        return 'all'
    return stock_filter

# filters items based on search query and stock status
def filter_items(items, search_query, stock_filter):
    filtered_items = items

    if search_query:
        search_lower = search_query.lower()
        filtered_items = [
            item
            for item in filtered_items
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

# normalizes the user role filter
def normalize_user_role_filter(value):
    role_filter = (value or 'all').strip().lower()
    allowed_role_filters = {'all', 'admin', 'user'}
    if role_filter not in allowed_role_filters:
        return 'all'
    return role_filter

# filters users based on search query and role
def filter_users(users, search_query, role_filter):
    filtered_users = users

    if search_query:
        search_lower = search_query.lower()
        filtered_users = [
            user
            for user in filtered_users
            if search_lower in (user['name'] or '').lower()
            or search_lower in (user['email'] or '').lower()
        ]

    if role_filter != 'all':
        target_admin_value = 1 if role_filter == 'admin' else 0
        filtered_users = [
            user for user in filtered_users if int(user['is_admin']) == target_admin_value
        ]

    return filtered_users

# updates the user permissions
def update_user_permission(actor_user_id, target_user_id_raw, target_is_admin_raw, confirm_action):
    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (actor_user_id,),
    ).fetchone()

    if not db_user:
        users_conn.close()
        return make_result(False, 'auth_missing')
    if not db_user['is_admin']:
        users_conn.close()
        return make_result(False, 'forbidden')

    try:
        target_user_id = int(target_user_id_raw)
        target_is_admin = int(target_is_admin_raw)
        if target_user_id < 1 or target_is_admin not in {0, 1}:
            raise ValueError
    except ValueError:
        users_conn.close()
        return make_result(False, 'invalid_permission', redirect_params={'user_status': 'invalid_permission'})

    target_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (target_user_id,),
    ).fetchone()
    if not target_user:
        users_conn.close()
        return make_result(False, 'user_not_found', redirect_params={'user_status': 'user_not_found'})

    if not confirm_action:
        users_conn.close()
        return make_result(
            False,
            'confirm_required',
            redirect_params={
                'pending_user_action': 'permission',
                'pending_user_id': target_user_id,
                'pending_user_is_admin': target_is_admin,
            },
        )

    if target_user_id == db_user['id'] and target_is_admin == 0:
        users_conn.close()
        return make_result(
            False,
            'cannot_demote_self',
            redirect_params={'user_status': 'cannot_demote_self', 'user_modal_id': target_user_id},
        )

    if int(target_user['is_admin']) == 1 and target_is_admin == 0:
        admin_count = users_conn.execute('SELECT COUNT(*) FROM users WHERE is_admin = 1').fetchone()[0]
        if admin_count <= 1:
            users_conn.close()
            return make_result(
                False,
                'last_admin',
                redirect_params={'user_status': 'last_admin', 'user_modal_id': target_user_id},
            )

    users_conn.execute('UPDATE users SET is_admin = ? WHERE id = ?', (target_is_admin, target_user_id))
    users_conn.commit()
    users_conn.close()
    return make_result(
        True,
        'permission_updated',
        redirect_params={'user_status': 'permission_updated', 'user_modal_id': target_user_id},
    )

# deletes a user
def delete_user(actor_user_id, target_user_id_raw, confirm_action):
    users_conn = get_users_db_connection()
    db_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (actor_user_id,),
    ).fetchone()

    if not db_user:
        users_conn.close()
        return make_result(False, 'auth_missing')
    if not db_user['is_admin']:
        users_conn.close()
        return make_result(False, 'forbidden')

    try:
        target_user_id = int(target_user_id_raw)
        if target_user_id < 1:
            raise ValueError
    except ValueError:
        users_conn.close()
        return make_result(False, 'user_not_found', redirect_params={'user_status': 'user_not_found'})

    target_user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (target_user_id,),
    ).fetchone()
    if not target_user:
        users_conn.close()
        return make_result(False, 'user_not_found', redirect_params={'user_status': 'user_not_found'})

    if not confirm_action:
        users_conn.close()
        return make_result(
            False,
            'confirm_required',
            redirect_params={'pending_user_action': 'delete', 'pending_user_id': target_user_id},
        )

    if target_user_id == db_user['id']:
        users_conn.close()
        return make_result(
            False,
            'cannot_delete_self',
            redirect_params={'user_status': 'cannot_delete_self', 'user_modal_id': target_user_id},
        )

    if int(target_user['is_admin']) == 1:
        admin_count = users_conn.execute('SELECT COUNT(*) FROM users WHERE is_admin = 1').fetchone()[0]
        if admin_count <= 1:
            users_conn.close()
            return make_result(
                False,
                'last_admin',
                redirect_params={'user_status': 'last_admin', 'user_modal_id': target_user_id},
            )

    items_conn = get_items_db_connection()
    items_conn.execute('UPDATE items SET user_id = NULL WHERE user_id = ?', (target_user_id,))
    items_conn.commit()
    items_conn.close()

    users_conn.execute('DELETE FROM users WHERE id = ?', (target_user_id,))
    users_conn.commit()
    users_conn.close()
    return make_result(True, 'user_deleted', redirect_params={'user_status': 'user_deleted'})
