from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)



from livereload import Server

app.config["TEMPLATES_AUTO_RELOAD"] = True

if __name__ == "__main__":
    server = Server(app.wsgi_app)
    server.watch("templates/")
    server.watch("static/")
    server.serve(port=5000, debug=True)