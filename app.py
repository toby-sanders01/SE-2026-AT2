from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

@app.route('/')
def index():
    return(render_template("index.html", show_footer=True))

@app.route('/login')
def login():
    return(render_template("login.html", show_footer=False))

@app.route('/signup')
def signup():
    return(render_template("signup.html", show_footer=False))

if __name__ == '__main__':
    app.run(debug=True)