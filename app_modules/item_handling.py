from .database_int import ITEM_IMAGES_DIR, get_items_db_connection, get_users_db_connection
from .core import get_upload_extension, make_result, write_item_audit_log

# Sets the user who is performing an action
def _get_actor_user(user_id):
    users_conn = get_users_db_connection()
    user = users_conn.execute(
        'SELECT id, is_admin FROM users WHERE id = ?',
        (user_id,),
    ).fetchone()
    users_conn.close()
    return user

# decreases the stock by the set amount, and handles errors
def decrease_stock(actor_user_id, item_id_raw, decrease_amount_raw, confirm_large):
    db_user = _get_actor_user(actor_user_id)
    if not db_user:
        return make_result(False, 'auth_missing')

    try:
        item_id = int(item_id_raw)
        if item_id < 1:
            raise ValueError
    except ValueError:
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_decrease',
            status='failure',
            error_message='Invalid item id.',
        )
        return make_result(False, 'invalid_amount', redirect_params={'stock_status': 'invalid_amount'})

    try:
        decrease_amount = int(decrease_amount_raw) #ensures decrease amount is an int
        if decrease_amount < 1:
            raise ValueError
    except ValueError: 
        write_item_audit_log( # writes audit log
            admin_user_id=db_user['id'],
            action='stock_decrease',
            status='failure',
            item_id=item_id,
            error_message='Invalid decrease amount.',
        )
        return make_result(
            False,
            'invalid_amount',
            redirect_params={'stock_status': 'invalid_amount', 'modal_item_id': item_id},
        )

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id, title, tag, description, image, stock_remaining
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id']),
    ).fetchone()

    if not item:
        items_conn.close()
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_decrease',
            status='failure',
            item_id=item_id,
            error_message='Item not found.',
        )
        return make_result(False, 'item_not_found', redirect_params={'stock_status': 'item_not_found'})

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
            error_message='No items remaining.',
        )
        return make_result(False, 'zero', redirect_params={'stock_status': 'zero', 'modal_item_id': item_id})

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
            error_message='Decrease amount exceeds remaining stock.',
        )
        return make_result(
            False,
            'insufficient',
            redirect_params={'stock_status': 'insufficient', 'modal_item_id': item_id},
        )

    if decrease_amount > 5 and not confirm_large:
        items_conn.close()
        return make_result(
            False,
            'confirm_required',
            redirect_params={'confirm_item_id': item_id, 'confirm_amount': decrease_amount},
        )

    items_conn.execute(
        'UPDATE items SET stock_remaining = stock_remaining - ? WHERE id = ?',
        (decrease_amount, item_id),
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
        new_image=item['image'],
    )
    return make_result(
        True,
        'decreased',
        redirect_params={'stock_status': 'decreased', 'stock_amount': decrease_amount, 'modal_item_id': item_id},
    )

# admin only, increases the stock by the set amount, and handles errors
def add_stock(actor_user_id, item_id_raw, add_amount_raw, confirm_action):
    db_user = _get_actor_user(actor_user_id)
    if not db_user:
        return make_result(False, 'auth_missing')
    if not db_user['is_admin']:
        return make_result(False, 'forbidden')

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
            error_message='Invalid item id or add amount.',
        )
        return make_result(
            False,
            'invalid_amount',
            redirect_params={'stock_status': 'invalid_amount', 'modal_item_id': item_id_raw},
        )

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id, title, tag, description, image, stock_remaining
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id']),
    ).fetchone()

    if not item:
        items_conn.close()
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='stock_add',
            status='failure',
            item_id=item_id,
            error_message='Item not found.',
        )
        return make_result(False, 'item_not_found', redirect_params={'stock_status': 'item_not_found'})

    if not confirm_action:
        items_conn.close()
        return make_result(
            False,
            'confirm_required',
            redirect_params={'pending_action': 'add', 'pending_item_id': item_id, 'pending_amount': add_amount},
        )

    items_conn.execute(
        'UPDATE items SET stock_remaining = stock_remaining + ? WHERE id = ?',
        (add_amount, item_id),
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
        new_image=item['image'],
    )
    return make_result(
        True,
        'added',
        redirect_params={'stock_status': 'added', 'stock_amount': add_amount, 'modal_item_id': item_id},
    )

#admin only, edits the item details, and handles errors
def edit_item(actor_user_id, item_id_raw, title, tag, description, confirm_action):
    db_user = _get_actor_user(actor_user_id)
    if not db_user:
        return make_result(False, 'auth_missing')
    if not db_user['is_admin']:
        return make_result(False, 'forbidden')

    try:
        item_id = int(item_id_raw)
        if item_id < 1:
            raise ValueError
    except ValueError:
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='edit',
            status='failure',
            error_message='Invalid item id.',
        )
        return make_result(False, 'item_not_found', redirect_params={'stock_status': 'item_not_found'})

    if not title or not tag:
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='edit',
            status='failure',
            item_id=item_id,
            new_title=title or None,
            new_tag=tag or None,
            new_description=description or None,
            error_message='Title and tag are required.',
        )
        return make_result(
            False,
            'invalid_amount',
            redirect_params={'stock_status': 'invalid_amount', 'modal_item_id': item_id},
        )

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id, title, tag, description, image, stock_remaining
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id']),
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
            error_message='Item not found.',
        )
        return make_result(False, 'item_not_found', redirect_params={'stock_status': 'item_not_found'})

    if not confirm_action:
        items_conn.close()
        return make_result(
            False,
            'confirm_required',
            redirect_params={
                'pending_action': 'edit',
                'pending_item_id': item_id,
                'pending_title': title,
                'pending_tag': tag,
                'pending_description': description,
            },
        )

    items_conn.execute(
        '''
        UPDATE items
        SET title = ?, tag = ?, description = ?
        WHERE id = ?
        ''',
        (title, tag, description, item_id),
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
        new_image=item['image'],
    )
    return make_result(True, 'edited', redirect_params={'stock_status': 'edited', 'modal_item_id': item_id})

# admin only, deletes the item, and handles errors
def delete_item(actor_user_id, item_id_raw, confirm_action):
    db_user = _get_actor_user(actor_user_id)
    if not db_user:
        return make_result(False, 'auth_missing')
    if not db_user['is_admin']:
        return make_result(False, 'forbidden')

    try:
        item_id = int(item_id_raw)
        if item_id < 1:
            raise ValueError
    except ValueError:
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='delete',
            status='failure',
            error_message='Invalid item id.',
        )
        return make_result(False, 'item_not_found', redirect_params={'stock_status': 'item_not_found'})

    items_conn = get_items_db_connection()
    item = items_conn.execute(
        '''
        SELECT id, title, tag, description, image, stock_remaining
        FROM items
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)
        ''',
        (item_id, db_user['id']),
    ).fetchone()

    if not item:
        items_conn.close()
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='delete',
            status='failure',
            item_id=item_id,
            error_message='Item not found.',
        )
        return make_result(False, 'item_not_found', redirect_params={'stock_status': 'item_not_found'})

    if not confirm_action:
        items_conn.close()
        return make_result(False, 'confirm_required', redirect_params={'pending_action': 'delete', 'pending_item_id': item_id})

    items_conn.execute('DELETE FROM items WHERE id = ?', (item_id,))
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
        old_image=item['image'],
    )
    return make_result(True, 'deleted', redirect_params={'stock_status': 'deleted'})

# admin only, creates a new item with the given details, and handles errors
def create_item(actor_user_id, title, tag, image, description, stock_remaining_raw, image_file):
    db_user = _get_actor_user(actor_user_id)
    if not db_user:
        return make_result(False, 'auth_missing')
    if not db_user['is_admin']:
        return make_result(False, 'forbidden')

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
            error_message=error,
        )
        return make_result(False, 'validation_error', error=error)

    if not tag:
        error = 'Item tag is required.'
        write_item_audit_log(
            admin_user_id=db_user['id'],
            action='create',
            status='failure',
            new_title=title or None,
            new_tag=tag or None,
            new_description=description or None,
            error_message=error,
        )
        return make_result(False, 'validation_error', error=error)

    upload_extension = None
    if uploaded_filename:
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
                error_message=error,
            )
            return make_result(False, 'validation_error', error=error)

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
            error_message=error,
        )
        return make_result(False, 'validation_error', error=error)

    image_value = image or 'small-logo.png'
    items_conn = get_items_db_connection()
    try:
        insert_cursor = items_conn.execute(
            '''
            INSERT INTO items (user_id, image, stock_remaining, title, tag, description)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (None, image_value, stock_remaining, title, tag, description),
        )

        if uploaded_filename and image_file and upload_extension:
            unique_filename = f'{insert_cursor.lastrowid}{upload_extension}'
            save_path = ITEM_IMAGES_DIR / unique_filename
            image_file.save(save_path)
            image_value = f'/item_images/{unique_filename}'
            items_conn.execute(
                'UPDATE items SET image = ? WHERE id = ?',
                (image_value, insert_cursor.lastrowid),
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
            new_image=image_value,
        )
        return make_result(True, 'created', payload={'success': 'Item created successfully.'})
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
            new_stock=stock_remaining,
            error_message=error,
        )
        return make_result(False, 'file_error', error=error)
    finally:
        items_conn.close()
