"""MarkBook API: store each student's marks (out of 20) in five subjects and rank them by CGPA."""
import os
import sqlite3

from flask import Flask, g, jsonify, request, send_from_directory

MAX_SCORE = 20

# Subjects in display order: (key, label, scale name).
SUBJECTS = (
    ("qp", "QP", "strict"),
    ("cp", "CP", "strict"),
    ("maths", "Maths", "strict"),
    ("ee", "EE", "standard"),
    ("ece", "ECE", "standard"),
)
KEYS = tuple(k for k, _, _ in SUBJECTS)
SCALE_OF = {k: scale for k, _, scale in SUBJECTS}

# Minimum marks (out of 20) for each grade point.
# These are the out-of-100 cutoffs divided by 5. Anything below the last row is a 0.
SCALES = {
    "strict": ((19, 10), (17, 9), (15, 8), (13, 7), (11, 6), (9, 5)),     # 95/85/75/65/55/45 of 100
    "standard": ((18, 10), (16, 9), (14, 8), (12, 7), (10, 6), (8, 5)),   # 90/80/70/60/50/40 of 100
}


def grade_point(subject, score):
    for cutoff, gp in SCALES[SCALE_OF[subject]]:
        if score >= cutoff:
            return gp
    return 0


def compute_cgpa(marks):
    """CGPA = average of the grade points of all subjects."""
    points = [grade_point(k, marks[k]) for k in KEYS]
    return round(sum(points) / len(points), 2)


def create_app(db_path=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["DATABASE"] = db_path or os.environ.get("DATABASE_PATH", "markbook.db")
    allowed_origin = os.environ.get("CORS_ORIGINS", "*")

    @app.after_request
    def cors(resp):
        if request.path.startswith("/api/"):
            resp.headers["Access-Control-Allow-Origin"] = allowed_origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_e):
        d = g.pop("db", None)
        if d is not None:
            d.close()

    with app.app_context():
        mark_cols = ",\n                ".join(
            f"{k} REAL NOT NULL CHECK ({k} >= 0 AND {k} <= {MAX_SCORE})" for k in KEYS)
        db().execute(
            f"""CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                roll_no TEXT NOT NULL UNIQUE COLLATE NOCASE,
                {mark_cols}
            )"""
        )
        db().commit()

    def err(msg, code):
        return jsonify({"error": msg}), code

    # ---------- data ----------
    def to_dict(row):
        marks = {k: row[k] for k in KEYS}
        return {"id": row["id"], "name": row["name"], "roll_no": row["roll_no"],
                "marks": marks,
                "grade_points": {k: grade_point(k, marks[k]) for k in KEYS},
                "cgpa": compute_cgpa(marks)}

    def ranked_students():
        """All students, highest CGPA first. Ties are broken by total marks, then name."""
        students = [to_dict(r) for r in db().execute("SELECT * FROM results")]
        students.sort(key=lambda s: (-s["cgpa"], -sum(s["marks"].values()), s["name"].lower()))
        rank, prev = 0, None
        for i, s in enumerate(students, 1):  # equal CGPA shares a rank
            if s["cgpa"] != prev:
                rank, prev = i, s["cgpa"]
            s["rank"] = rank
        return students

    def one_student(sid):
        return next((s for s in ranked_students() if s["id"] == sid), None)

    def exists(sid):
        return db().execute("SELECT 1 FROM results WHERE id = ?", (sid,)).fetchone() is not None

    # ---------- validation ----------
    def clean_payload(data, partial):
        """Return (fields, error). Fields are name, roll_no and subject keys, all safe column names."""
        if not isinstance(data, dict):
            return None, "Request body must be a JSON object."
        out = {}
        for field, limit in (("name", 80), ("roll_no", 30)):
            if field in data or not partial:
                v = data.get(field)
                if not isinstance(v, str) or not v.strip():
                    return None, f"'{field}' is required and must be a non-empty string."
                if len(v.strip()) > limit:
                    return None, f"'{field}' must be {limit} characters or fewer."
                out[field] = v.strip()
        marks = data.get("marks")
        if marks is None and partial:
            marks = {}
        if not isinstance(marks, dict):
            return None, "'marks' must be an object with a score for each subject."
        unknown = sorted(set(marks) - set(KEYS))
        if unknown:
            return None, f"Unknown subject(s) {unknown}. Use {list(KEYS)}."
        if not partial:
            missing = [k for k in KEYS if k not in marks]
            if missing:
                return None, f"Missing marks for {missing}."
        for k, v in marks.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= MAX_SCORE:
                return None, f"Marks for '{k}' must be a number between 0 and {MAX_SCORE}."
            out[k] = float(v)
        return out, None

    # ---------- frontend ----------
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # ---------- API ----------
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/subjects")
    def subjects():
        return jsonify({
            "max_score": MAX_SCORE,
            "subjects": [
                {"key": k, "label": label,
                 "scale": [{"min_marks": m, "grade_point": gp} for m, gp in SCALES[scale]]}
                for k, label, scale in SUBJECTS
            ],
        })

    @app.get("/api/students")
    def list_students():
        return jsonify(ranked_students())

    @app.get("/api/students/<int:sid>")
    def get_student(sid):
        s = one_student(sid)
        return jsonify(s) if s else err(f"Student {sid} not found.", 404)

    @app.post("/api/students")
    def create_student():
        clean, e = clean_payload(request.get_json(silent=True), partial=False)
        if e:
            return err(e, 400)
        try:
            cur = db().execute(
                f"INSERT INTO results ({', '.join(clean)}) VALUES ({', '.join('?' for _ in clean)})",
                tuple(clean.values()))
            db().commit()
        except sqlite3.IntegrityError:
            return err(f"Roll number '{clean['roll_no']}' already exists.", 409)
        resp = jsonify(one_student(cur.lastrowid))
        resp.status_code = 201
        resp.headers["Location"] = f"/api/students/{cur.lastrowid}"
        return resp

    def update_student(sid, partial):
        if not exists(sid):
            return err(f"Student {sid} not found.", 404)
        clean, e = clean_payload(request.get_json(silent=True), partial)
        if e:
            return err(e, 400)
        if not clean:
            return err("No updatable fields supplied.", 400)
        sets = ", ".join(f"{k} = ?" for k in clean)
        try:
            db().execute(f"UPDATE results SET {sets} WHERE id = ?", (*clean.values(), sid))
            db().commit()
        except sqlite3.IntegrityError:
            return err("That roll number already exists.", 409)
        return jsonify(one_student(sid))

    @app.put("/api/students/<int:sid>")
    def put_student(sid):
        return update_student(sid, partial=False)

    @app.patch("/api/students/<int:sid>")
    def patch_student(sid):
        return update_student(sid, partial=True)

    @app.delete("/api/students/<int:sid>")
    def delete_student(sid):
        if not exists(sid):
            return err(f"Student {sid} not found.", 404)
        db().execute("DELETE FROM results WHERE id = ?", (sid,))
        db().commit()
        return "", 204

    # ---------- JSON error handlers ----------
    @app.errorhandler(404)
    def nf(_e):
        return err("Resource not found.", 404)

    @app.errorhandler(405)
    def mna(_e):
        return err("Method not allowed for this route.", 405)

    @app.errorhandler(500)
    def ise(_e):
        return err("Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))