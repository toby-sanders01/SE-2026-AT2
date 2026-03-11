from flask import request

# Modals are constructed using OpenAI Codex

# Builds the state of the modal for items
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
                'type': 'success',
                'message': f'Stock decreased by {stock_amount}.',
            }
        else:
            stock_feedback = {
                'type': 'success',
                'message': 'Stock decreased.',
            }
    elif stock_status == 'invalid_amount':
        stock_feedback = {
            'type': 'error',
            'message': 'Enter a whole number greater than 0.',
        }
    elif stock_status == 'item_not_found':
        stock_feedback = {
            'type': 'error',
            'message': 'The selected item could not be found.',
        }
    elif stock_status == 'zero':
        if modal_item:
            stock_feedback = {
                'type': 'error',
                'message': 'No items remaining.',
            }
    elif stock_status == 'insufficient':
        if modal_item:
            stock_feedback = {
                'type': 'error',
                'message': f"Only {modal_item['stock_remaining']} items remaining.",
            }
        else:
            stock_feedback = {
                'type': 'error',
                'message': 'Decrease amount cannot be more than items remaining.',
            }
    elif stock_status == 'added':
        stock_amount_raw = request.args.get('stock_amount', '').strip()
        try:
            stock_amount = int(stock_amount_raw)
        except ValueError:
            stock_amount = 0
        if stock_amount > 0:
            stock_feedback = {
                'type': 'success',
                'message': f'Stock increased by {stock_amount}.',
            }
        else:
            stock_feedback = {
                'type': 'success',
                'message': 'Stock increased.',
            }
    elif stock_status == 'edited':
        stock_feedback = {
            'type': 'success',
            'message': 'Item updated successfully.',
        }
    elif stock_status == 'deleted':
        stock_feedback = {
            'type': 'success',
            'message': 'Item deleted successfully.',
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
                        'item_id': confirm_item_id,
                        'amount': confirm_amount,
                        'item_title': item['title'],
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
                        'action': 'add',
                        'item_id': pending_item_id,
                        'amount': pending_amount,
                    }
            elif pending_action == 'edit':
                action_confirmation = {
                    'action': 'edit',
                    'item_id': pending_item_id,
                    'title': request.args.get('pending_title', '').strip(),
                    'tag': request.args.get('pending_tag', '').strip(),
                    'description': request.args.get('pending_description', '').strip(),
                }
            elif pending_action == 'delete':
                action_confirmation = {
                    'action': 'delete',
                    'item_id': pending_item_id,
                }

    show_modal_on_load = bool(
        stock_confirmation
        or action_confirmation
        or (stock_feedback is not None and modal_item is not None)
    )
    return {
        'stock_feedback': stock_feedback,
        'stock_confirmation': stock_confirmation,
        'action_confirmation': action_confirmation,
        'modal_item': modal_item,
        'show_modal_on_load': show_modal_on_load,
    }

# Builds the state of the user management moda
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
            'type': 'success',
            'message': 'User permissions updated successfully.',
        }
    elif user_status == 'user_not_found':
        user_feedback = {
            'type': 'error',
            'message': 'The selected user could not be found.',
        }
    elif user_status == 'invalid_permission':
        user_feedback = {
            'type': 'error',
            'message': 'Invalid permission value.',
        }
    elif user_status == 'cannot_demote_self':
        user_feedback = {
            'type': 'error',
            'message': 'You cannot remove your own admin permission.',
        }
    elif user_status == 'last_admin':
        user_feedback = {
            'type': 'error',
            'message': 'At least one admin must remain.',
        }
    elif user_status == 'cannot_delete_self':
        user_feedback = {
            'type': 'error',
            'message': 'You cannot delete your own account.',
        }
    elif user_status == 'user_deleted':
        user_feedback = {
            'type': 'success',
            'message': 'User removed successfully.',
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
                    'action': 'permission',
                    'user_id': pending_user_id,
                    'target_is_admin': pending_user_is_admin,
                }
        elif user_modal and pending_user_action == 'delete':
            user_confirmation = {
                'action': 'delete',
                'user_id': pending_user_id,
            }

    show_user_modal_on_load = bool(
        user_confirmation or (user_feedback is not None and user_modal is not None)
    )
    return {
        'user_feedback': user_feedback,
        'user_modal': user_modal,
        'user_confirmation': user_confirmation,
        'show_user_modal_on_load': show_user_modal_on_load,
    }
