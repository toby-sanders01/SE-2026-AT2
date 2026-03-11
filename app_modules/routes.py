from flask import redirect, render_template, request, send_from_directory, session, url_for

#misc. codex assistance throughout the file

#imports from other modules in the app
from .database_int import ITEM_IMAGES_DIR
from .core import (
    delete_user as delete_user_service,
    filter_items,
    filter_users,
    format_audit_timestamp,
    get_all_users,
    get_display_name,
    get_stock_audit_logs,
    get_user_by_id,
    get_visible_items_for_user,
    hydrate_session,
    normalize_stock_filter,
    normalize_user_role_filter,
    process_login,
    process_signup,
    refresh_session_identity,
    update_user_permission as update_user_permission_service,
)
from .item_handling import (
    add_stock as add_stock_service,
    create_item,
    decrease_stock as decrease_stock_service,
    delete_item as delete_item_service,
    edit_item as edit_item_service,
)
from .modal import build_item_modal_state, build_user_modal_state
from .rate_limiting import consume_rate_limit


def register_routes(app):
    @app.context_processor
    # injects auth state into all pages
    def inject_auth_state():
        user_name = (session.get('user_name') or '').strip().capitalize()
        if not user_name and session.get('user_email'):
            user_name = session['user_email'].split('@', 1)[0]
        if not user_name:
            user_name = 'User'

        return {
            'logged_in': 'user_id' in session,
            'current_user_name': user_name,
            'current_user_is_admin': bool(session.get('is_admin')),
        }

    # 404 page handler that shows different options based on auth state
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
                '404.html',
                show_footer=True,
                show_login=True,
                primary_endpoint=primary_endpoint,
                primary_label=primary_label,
            ),
            404,
        )

    # home page route, hero screen
    @app.route('/')
    def index():
        return render_template('index.html', show_footer=True, show_login=True)

    # route to serve item images
    @app.route('/item_images/<path:filename>')
    def item_image(filename):
        return send_from_directory(ITEM_IMAGES_DIR, filename)

    # user dashboard route, shows items and allows stock decrease
    @app.route('/user')
    def user():
        if 'user_id' not in session:
            return redirect(url_for('login'))

        if session.get('is_admin'):
            return redirect(url_for('admin'))

        db_user = get_user_by_id(session.get('user_id'))
        if not db_user:
            session.clear()
            return redirect(url_for('login'))

        user_name = get_display_name(db_user)
        search_query = request.args.get('q', '').strip()
        stock_filter = normalize_stock_filter(request.args.get('stock', 'all'))

        visible_items = get_visible_items_for_user(db_user['id'])
        items = filter_items(visible_items, search_query, stock_filter)
        item_modal_state = build_item_modal_state(items)

        refresh_session_identity(session, db_user)
        return render_template(
            'user.html',
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
            show_modal_on_load=item_modal_state['show_modal_on_load'],
        )

    # post route to decrease stock of an item, with confirmation for large decreases
    @app.route('/decrease-stock', methods=['POST'])
    def decrease_stock():
        if 'user_id' not in session:
            return redirect(url_for('login'))

        rate_limit_response = consume_rate_limit('item_changes')
        if rate_limit_response:
            return rate_limit_response

        return_endpoint = request.form.get('return_endpoint', 'user').strip()
        if return_endpoint not in {'user', 'admin'}:
            return_endpoint = 'user'

        #sends for info to module
        result = decrease_stock_service(
            actor_user_id=session.get('user_id'),
            item_id_raw=request.form.get('item_id', '').strip(),
            decrease_amount_raw=request.form.get('decrease_amount', '').strip(),
            confirm_large=request.form.get('confirm_large', '').strip() == '1',
        )

        if result['status'] == 'auth_missing':
            session.clear()
            return redirect(url_for('login'))

        return redirect(url_for(return_endpoint, **result['redirect_params']))

    # post route to add stock of an item, with confirmation for large increases
    @app.route('/add-stock', methods=['POST'])
    def add_stock():
        if 'user_id' not in session:
            return redirect(url_for('login'))

        rate_limit_response = consume_rate_limit('item_changes')
        if rate_limit_response:
            return rate_limit_response

        return_endpoint = request.form.get('return_endpoint', 'admin').strip()
        if return_endpoint not in {'user', 'admin'}:
            return_endpoint = 'admin'

        #sends for info to module
        result = add_stock_service(
            actor_user_id=session.get('user_id'),
            item_id_raw=request.form.get('item_id', '').strip(),
            add_amount_raw=request.form.get('add_amount', '').strip(),
            confirm_action=request.form.get('confirm_action', '').strip() == '1',
        )

        if result['status'] == 'auth_missing':
            session.clear()
            return redirect(url_for('login'))
        if result['status'] == 'forbidden':
            return redirect(url_for('user'))

        return redirect(url_for(return_endpoint, **result['redirect_params']))

    # post route to edit item details, with confirmation for changes
    @app.route('/edit-item', methods=['POST'])
    def edit_item():
        if 'user_id' not in session:
            return redirect(url_for('login'))

        rate_limit_response = consume_rate_limit('item_changes')
        if rate_limit_response:
            return rate_limit_response

        return_endpoint = request.form.get('return_endpoint', 'admin').strip()
        if return_endpoint not in {'user', 'admin'}:
            return_endpoint = 'admin'

        #sends for info to module
        result = edit_item_service(
            actor_user_id=session.get('user_id'),
            item_id_raw=request.form.get('item_id', '').strip(),
            title=request.form.get('title', '').strip(),
            tag=request.form.get('tag', '').strip(),
            description=request.form.get('description', '').strip(),
            confirm_action=request.form.get('confirm_action', '').strip() == '1',
        )

        if result['status'] == 'auth_missing':
            session.clear()
            return redirect(url_for('login'))
        if result['status'] == 'forbidden':
            return redirect(url_for('user'))

        return redirect(url_for(return_endpoint, **result['redirect_params']))

    # post route to delete an item, with confirmation for deletion
    @app.route('/delete-item', methods=['POST'])
    def delete_item():
        if 'user_id' not in session:
            return redirect(url_for('login'))

        rate_limit_response = consume_rate_limit('item_changes')
        if rate_limit_response:
            return rate_limit_response

        return_endpoint = request.form.get('return_endpoint', 'admin').strip()
        if return_endpoint not in {'user', 'admin'}:
            return_endpoint = 'admin'

        #sends for info to module
        result = delete_item_service(
            actor_user_id=session.get('user_id'),
            item_id_raw=request.form.get('item_id', '').strip(),
            confirm_action=request.form.get('confirm_action', '').strip() == '1',
        )

        if result['status'] == 'auth_missing':
            session.clear()
            return redirect(url_for('login'))
        if result['status'] == 'forbidden':
            return redirect(url_for('user'))

        return redirect(url_for(return_endpoint, **result['redirect_params']))

    # post route to update a user's admin permissions, with confirmation for changes
    @app.route('/update-user-permission', methods=['POST'])
    def update_user_permission():
        if 'user_id' not in session:
            return redirect(url_for('login'))

        rate_limit_response = consume_rate_limit('admin_user_changes')
        if rate_limit_response:
            return rate_limit_response

        return_endpoint = request.form.get('return_endpoint', 'admin').strip()
        if return_endpoint not in {'admin'}:
            return_endpoint = 'admin'

        result = update_user_permission_service(
            actor_user_id=session.get('user_id'),
            target_user_id_raw=request.form.get('target_user_id', '').strip(),
            target_is_admin_raw=request.form.get('target_is_admin', '').strip(),
            confirm_action=request.form.get('confirm_action', '').strip() == '1',
        )

        if result['status'] == 'auth_missing':
            session.clear()
            return redirect(url_for('login'))
        if result['status'] == 'forbidden':
            return redirect(url_for('user'))

        return redirect(url_for(return_endpoint, **result['redirect_params']))

    # post route to delete a user, with confirmation for deletion
    @app.route('/delete-user', methods=['POST'])
    def delete_user():
        if 'user_id' not in session:
            return redirect(url_for('login'))

        rate_limit_response = consume_rate_limit('admin_user_changes')
        if rate_limit_response:
            return rate_limit_response

        return_endpoint = request.form.get('return_endpoint', 'admin').strip()
        if return_endpoint != 'admin':
            return_endpoint = 'admin'

        result = delete_user_service(
            actor_user_id=session.get('user_id'),
            target_user_id_raw=request.form.get('target_user_id', '').strip(),
            confirm_action=request.form.get('confirm_action', '').strip() == '1',
        )

        if result['status'] == 'auth_missing':
            session.clear()
            return redirect(url_for('login'))
        if result['status'] == 'forbidden':
            return redirect(url_for('user'))

        return redirect(url_for(return_endpoint, **result['redirect_params']))

    # admin dashboard
    @app.route('/admin', methods=['GET', 'POST'])
    def admin():
        if 'user_id' not in session:
            return redirect(url_for('login'))

        db_user = get_user_by_id(session.get('user_id'))
        if not db_user:
            session.clear()
            return redirect(url_for('login'))

        if not db_user['is_admin']:
            return redirect(url_for('user'))

        error = None
        success = None

        if request.method == 'POST':
            rate_limit_response = consume_rate_limit('item_changes')
            if rate_limit_response:
                return rate_limit_response

            result = create_item(
                actor_user_id=db_user['id'],
                title=request.form.get('title', '').strip(),
                tag=request.form.get('tag', '').strip(),
                image=request.form.get('image', '').strip(),
                description=request.form.get('description', '').strip(),
                stock_remaining_raw=request.form.get('stock_remaining', '').strip(),
                image_file=request.files.get('image_file'),
            )
            if result['ok']:
                success = result['payload'].get('success')
            else:
                error = result['error']

        search_query = request.args.get('q', '').strip()
        stock_filter = normalize_stock_filter(request.args.get('stock', 'all'))
        visible_items = get_visible_items_for_user(db_user['id'])
        items = filter_items(visible_items, search_query, stock_filter)
        item_modal_state = build_item_modal_state(items)

        user_search_query = request.args.get('user_q', '').strip()
        user_role_filter = normalize_user_role_filter(request.args.get('user_role', 'all'))
        all_users = get_all_users()
        filtered_users = filter_users(all_users, user_search_query, user_role_filter)
        user_modal_state = build_user_modal_state(all_users)
        user_identity_by_id = {}
        for user_record in all_users:
            display_name = (user_record['name'] or '').strip() or user_record['email']
            user_identity_by_id[user_record['id']] = f"{display_name} ({user_record['email']})"

        item_audit_logs = get_stock_audit_logs(limit=100)
        item_audit_logs = [
            {
                **dict(log),
                'created_at_display': format_audit_timestamp(log['created_at']),
                'actor_display': user_identity_by_id.get(
                    log['admin_user_id'],
                    f"User #{log['admin_user_id']}" if log['admin_user_id'] else '-',
                ),
            }
            for log in item_audit_logs
        ]

        refresh_session_identity(session, db_user)
        return render_template(
            'admin.html',
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
            item_audit_logs=item_audit_logs,
        )

    #login form
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if 'user_id' in session:
            if session.get('is_admin'):
                return redirect(url_for('admin'))
            return redirect(url_for('user'))

        error = None
        success = 'Account created. You can log in now.' if request.args.get('created') == '1' else None

        if request.method == 'POST':
            rate_limit_response = consume_rate_limit('login')
            if rate_limit_response:
                return rate_limit_response

            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            result = process_login(email, password)

            if not result['ok']:
                error = result['error']
            else:
                hydrate_session(session, result['payload']['user'])
                if session.get('is_admin'):
                    return redirect(url_for('admin'))
                return redirect(url_for('user'))

        return render_template('login.html', show_footer=False, error=error, success=success)

    #signup form
    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        if 'user_id' in session:
            if session.get('is_admin'):
                return redirect(url_for('admin'))
            return redirect(url_for('user'))

        error = None

        if request.method == 'POST':
            rate_limit_response = consume_rate_limit('signup')
            if rate_limit_response:
                return rate_limit_response

            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            result = process_signup(name, email, password, confirm_password)

            if not result['ok']:
                error = result['error']
            else:
                return redirect(url_for('login', **result['redirect_params']))

        return render_template('signup.html', show_footer=False, error=error)

    # logout route
    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))
