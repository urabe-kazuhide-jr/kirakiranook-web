import os
import sqlite3
from flask import (
    Flask, g, render_template, request,
    redirect, url_for, abort, session, flash,
    send_from_directory
)
from werkzeug.utils import secure_filename


app = Flask(__name__)

# Secret key for sessions (change in production)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# Simple admin password (set env var in production)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "kirakiranook")

# Point to kira.db in the same folder as app.py
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "kira.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # Create folder if it doesn't exist


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    """Open a new database connection if there is none yet for the current request."""
    if "db" not in g:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row  # so you can do row["name"]
        g.db = conn
    return g.db

def init_db():
    """Initialize the database using schema.sql."""
    with app.app_context():
        db = get_db()
        schema_path = os.path.join(BASE_DIR, "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            db.executescript(f.read())
            
@app.route("/test-db")
def test_db():
    db = get_db()
    # Try to read one customer
    row = db.execute("SELECT id, name, email FROM customers LIMIT 1").fetchone()

    if row is None:
        return "DB is connected ✅ but there are no customers yet 🐣"

    # If there IS a customer, show basic info
    return f"DB OK ✅ First customer: {row['id']} – {row['name']} ({row['email']})"


@app.teardown_appcontext
def close_db(exception):
    """Close the database connection at the end of the request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/how")
def how():
    return render_template("how.html")

@app.route("/products")
def products():
    return render_template("products.html")

@app.route("/upload")
def upload():
    return render_template("upload.html")

@app.route("/thank-you")
def thank_you():
    request_id = request.args.get("request_id", type=int)

    if request_id is None:
        # fallback generic page
        return render_template("thank_you.html", info=None)

    db = get_db()
    row = db.execute(
        """
        SELECT
            r.id,
            r.method,
            r.notes,
            r.created,
            c.name AS customer_name,
            c.email AS customer_email,
            c.phone AS customer_phone
        FROM requests r
        JOIN customers c ON r.customer_id = c.id
        WHERE r.id = ?
        """,
        (request_id,),
    ).fetchone()

    if row is None:
        return render_template("thank_you.html", info=None)

    return render_template("thank_you.html", info=row)



@app.route("/order")
def order():
    return render_template("order.html")


@app.route("/order/send", methods=["POST"])
def order_send():
    # Get form data from order.html
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    count = request.form.get("count", "").strip()
    product = request.form.get("product", "").strip()
    notes = request.form.get("notes", "").strip()

    if not name or not email:
        return "Name and email are required.", 400

    db = get_db()
    cur = db.cursor()

    # 1) Customer
    cur.execute(
        "INSERT INTO customers (name, email, phone) VALUES (?, ?, ?)",
        (name, email, phone),
    )
    customer_id = cur.lastrowid

    # 2) Build notes text
    details = []
    if product:
        details.append(f"Product: {product}")
    if count:
        details.append(f"Artwork count: {count}")
    if notes:
        details.append(f"Notes: {notes}")

    full_notes = " | ".join(details) if details else None

    # 3) Request (method = send)
    cur.execute(
        """
        INSERT INTO requests (customer_id, method, notes)
        VALUES (?, ?, ?)
        """,
        (customer_id, "send", full_notes),
    )
    request_id = cur.lastrowid

    db.commit()

    # (Optional) send email here later

    return redirect(url_for("thank_you", request_id=request_id))



@app.route("/order/upload", methods=["POST"])
def order_upload():
    # Get form data from order.html (upload form)
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    product = request.form.get("product", "").strip()
    notes = request.form.get("notes", "").strip()

    # Files (multiple)
    files = request.files.getlist("files")

    # Basic validation
    if not name or not email:
        return "Name and email are required.", 400

    if not files or all(f.filename == "" for f in files):
        return "Please select at least one image.", 400

    # Filter valid files
    valid_files = [f for f in files if f and f.filename and allowed_file(f.filename)]
    if not valid_files:
        return "No valid image files were uploaded.", 400

    db = get_db()
    cur = db.cursor()

    # 1) Insert into customers
    cur.execute(
        "INSERT INTO customers (name, email, phone) VALUES (?, ?, ?)",
        (name, email, None),  # no phone field in upload form
    )
    customer_id = cur.lastrowid

    # 2) Build notes text for the request
    details = []
    if product:
        details.append(f"Product: {product}")
    details.append(f"Uploaded files: {len(valid_files)}")
    if notes:
        details.append(f"Notes: {notes}")

    full_notes = " | ".join(details)

    # 3) Insert into requests (method = 'upload')
    cur.execute(
        """
        INSERT INTO requests (customer_id, method, notes)
        VALUES (?, ?, ?)
        """,
        (customer_id, "upload", full_notes),
    )
    request_id = cur.lastrowid

    # 4) Save each file to disk + record in artworks table
    for idx, file in enumerate(valid_files, start=1):
        original_filename = file.filename
        safe_name = secure_filename(original_filename)

        # Build a unique stored filename like: 12_1_originalname.png
        stored_filename = f"{request_id}_{idx}_{safe_name}"

        save_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_filename)
        file.save(save_path)

        ext = original_filename.rsplit(".", 1)[1].lower()

        cur.execute(
            """
            INSERT INTO artworks (request_id, original_filename, stored_filename, file_type)
            VALUES (?, ?, ?, ?)
            """,
            (request_id, original_filename, stored_filename, ext),
        )

    db.commit()
    
    # redirect with this specific request_id
    return redirect(url_for("thank_you", request_id=request_id))

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            next_url = request.args.get("next") or url_for("admin")
            return redirect(next_url)
        else:
            flash("Wrong password.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
def admin():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login", next=request.path))

    db = get_db()
    filter_status = request.args.get("status", "all")

    base_query = """
        SELECT
            r.id,
            r.method,
            r.notes,
            r.status,
            r.created,
            c.name AS customer_name,
            c.email AS customer_email,
            c.phone AS customer_phone,
            COUNT(a.id) AS artwork_count
        FROM requests r
        JOIN customers c ON r.customer_id = c.id
        LEFT JOIN artworks a ON a.request_id = r.id
    """

    params = []

    # Apply filter if a specific status is selected
    if filter_status in ("new", "in_progress", "completed"):
        base_query += " WHERE COALESCE(r.status, 'new') = ?"
        params.append(filter_status)

    base_query += """
        GROUP BY r.id
        ORDER BY r.created DESC
    """

    rows = db.execute(base_query, params).fetchall()

    return render_template("admin.html", requests=rows, filter_status=filter_status)


# Allowed statuses for requests
ALLOWED_STATUSES = ("new", "in_progress", "completed")


@app.route("/admin/update-status/<int:request_id>", methods=["POST"])
def admin_update_status(request_id):
    if not session.get("is_admin"):
        abort(403)

    new_status = request.form.get("status", "").strip()

    if new_status not in ALLOWED_STATUSES:
        abort(400)

    db = get_db()
    db.execute(
        "UPDATE requests SET status = ? WHERE id = ?",
        (new_status, request_id),
    )
    db.commit()

    return redirect(url_for("admin"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/admin/request/<int:request_id>")
def admin_request_detail(request_id):
    db = get_db()

    req = db.execute(
        """
        SELECT
            r.id,
            r.method,
            r.notes,
            r.status,
            r.created,
            c.name AS customer_name,
            c.email AS customer_email,
            c.phone AS customer_phone
        FROM requests r
        JOIN customers c ON r.customer_id = c.id
        WHERE r.id = ?
        """,
        (request_id,),
    ).fetchone()

    if req is None:
        abort(404)

    artworks = db.execute(
        """
        SELECT
            id,
            original_filename,
            stored_filename,
            file_type,
            uploaded_at
        FROM artworks
        WHERE request_id = ?
        ORDER BY id
        """,
        (request_id,),
    ).fetchall()

    return render_template("admin_request.html", req=req, artworks=artworks)


if __name__ == "__main__":
    app.run(debug=True)