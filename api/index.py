from flask import Flask, render_template, request
from flask_cors import CORS

app = Flask(__name__, template_folder="../templates", static_folder="../static")
CORS(app)

@app.route("/")
def home():
    return render_template("index.html")