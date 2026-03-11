from flask import Flask

from app_modules.database_int import init_items_db, init_users_db
from app_modules.routes import register_routes

app = Flask(__name__)
app.secret_key = 'dev-secret-change-me'

# Ensure both databases and image directory exist on startup.
init_users_db()
init_items_db()

register_routes(app)

# if __name__ == '__main__':
#     app.run(port=5001, debug=True)
