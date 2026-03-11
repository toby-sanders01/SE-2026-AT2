from collections import defaultdict, deque
from time import time

from flask import make_response, render_template, request, session

# Codex implemented rate limiting system.

RATE_LIMIT_CONFIG = {
    'login': (5, 60),
    'signup': (3, 300),
    'item_changes': (30, 60),
    'admin_user_changes': (20, 60),
}
RATE_LIMIT_EVENTS = defaultdict(deque)

# generates a unique identity for the user, based on their ip or user
def get_rate_limit_identity():
    user_id = session.get('user_id')
    if user_id:
        return f'user:{user_id}'

    forwarded_for = request.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        client_ip = forwarded_for.split(',', 1)[0].strip()
    else:
        client_ip = request.remote_addr or 'unknown'
    return f'ip:{client_ip}'

# checks if a user has exceeded the rate limit for a given bucket, and if so returns a 429 response, otherwise records the event and allows the request to proceed
def consume_rate_limit(bucket_name):
    limit, window_seconds = RATE_LIMIT_CONFIG[bucket_name]
    now = time()
    bucket_key = f'{bucket_name}:{get_rate_limit_identity()}'
    events = RATE_LIMIT_EVENTS[bucket_key]
    cutoff = now - window_seconds

    while events and events[0] <= cutoff:
        events.popleft()

    if len(events) >= limit:
        retry_after = max(1, int(window_seconds - (now - events[0])))
        response = make_response(
            render_template(
                '429.html',
                show_login=True,
                retry_after=retry_after,
            ),
            429,
        )
        response.headers['Retry-After'] = str(retry_after)
        return response

    events.append(now)
    return None
