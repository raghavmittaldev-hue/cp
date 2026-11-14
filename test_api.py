import os
import tempfile
import unittest

from app import create_app, grade_point


def marks(qp=10, cp=10, maths=10, ee=10, ece=10):
    return {"qp": qp, "cp": cp, "maths": maths, "ee": ee, "ece": ece}


class MarkBookTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.c = create_app(self.path).test_client()

    def tearDown(self):
        os.remove(self.path)

    def add(self, name="Asha", roll="1", **m):
        return self.c.post("/api/students", json={"name": name, "roll_no": roll, "marks": marks(**m)})

    # ----- grading scheme (out-of-100 cutoffs divided by 5) -----
    def test_grade_points_qp_cp_maths(self):
        for subject in ("qp", "cp", "maths"):
            for score, gp in [(20, 10), (19, 10), (18.9, 9), (17, 9), (16.9, 8), (15, 8),
                              (14.9, 7), (13, 7), (11, 6), (9, 5), (8.9, 0), (0, 0)]:
                self.assertEqual(grade_point(subject, score), gp, (subject, score))

    def test_grade_points_ee_ece(self):
        for subject in ("ee", "ece"):
            for score, gp in [(20, 10), (18, 10), (17.9, 9), (16, 9), (14, 8), (12, 7),
                              (10, 6), (8, 5), (7.9, 0), (0, 0)]:
                self.assertEqual(grade_point(subject, score), gp, (subject, score))

    def test_same_marks_different_subject_different_grade(self):
        self.assertEqual(grade_point("maths", 18), 9)
        self.assertEqual(grade_point("ee", 18), 10)

    # ----- CGPA and ordering -----
    def test_cgpa_is_average_of_grade_points(self):
        r = self.add(qp=17, cp=15, maths=19, ee=16, ece=14)   # 9, 8, 10, 9, 8
        s = r.get_json()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(s["grade_points"], {"qp": 9, "cp": 8, "maths": 10, "ee": 9, "ece": 8})
        self.assertEqual(s["cgpa"], 8.8)

    def test_students_sorted_highest_to_lowest_cgpa(self):
        self.add("Low", "1", qp=5, cp=5, maths=5, ee=5, ece=5)
        self.add("High", "2", qp=19, cp=19, maths=19, ee=19, ece=19)
        self.add("Mid", "3", qp=15, cp=15, maths=15, ee=14, ece=14)
        out = self.c.get("/api/students").get_json()
        self.assertEqual([s["name"] for s in out], ["High", "Mid", "Low"])
        self.assertEqual([s["rank"] for s in out], [1, 2, 3])
        self.assertEqual(out[0]["cgpa"], 10.0)

    def test_equal_cgpa_shares_rank_and_ties_break_by_total_marks(self):
        self.add("A", "1", qp=15, cp=15, maths=15, ee=14, ece=14)
        self.add("B", "2", qp=16, cp=16, maths=16, ee=15, ece=15)   # same grade points, more marks
        out = self.c.get("/api/students").get_json()
        self.assertEqual([s["name"] for s in out], ["B", "A"])
        self.assertEqual([s["rank"] for s in out], [1, 1])

    # ----- validation -----
    def test_all_five_subjects_required(self):
        r = self.c.post("/api/students", json={"name": "X", "roll_no": "9", "marks": {"qp": 10}})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.post("/api/students", json={"name": "X", "roll_no": "9"}).status_code, 400)

    def test_marks_must_be_between_0_and_20(self):
        self.assertEqual(self.add(qp=21).status_code, 400)
        self.assertEqual(self.add(qp=-1).status_code, 400)
        self.assertEqual(self.add(qp="x").status_code, 400)
        self.assertEqual(self.add(qp=True).status_code, 400)
        self.assertEqual(self.add(qp=20, cp=0).status_code, 201)

    def test_unknown_subject_and_bad_body(self):
        bad = {"name": "X", "roll_no": "9", "marks": {**marks(), "physics": 10}}
        self.assertEqual(self.c.post("/api/students", json=bad).status_code, 400)
        self.assertEqual(self.c.post("/api/students", data="nope").status_code, 400)
        self.assertEqual(self.c.post("/api/students", json={"name": "", "roll_no": "1", "marks": marks()}).status_code, 400)

    def test_duplicate_roll_number(self):
        self.assertEqual(self.add(roll="CS1").status_code, 201)
        self.assertEqual(self.add("Other", "cs1").status_code, 409)

    # ----- CRUD -----
    def test_get_one_and_404(self):
        self.add()
        self.assertEqual(self.c.get("/api/students/1").status_code, 200)
        self.assertEqual(self.c.get("/api/students/99").status_code, 404)

    def test_put_replaces_everything(self):
        self.add()
        ok = self.c.put("/api/students/1", json={"name": "New", "roll_no": "7", "marks": marks(qp=19)})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.get_json()["marks"]["qp"], 19)
        self.assertEqual(self.c.put("/api/students/1", json={"name": "New", "roll_no": "7"}).status_code, 400)
        self.assertEqual(self.c.put("/api/students/99", json={}).status_code, 404)

    def test_patch_changes_only_what_is_sent(self):
        self.add(qp=12, cp=13)
        r = self.c.patch("/api/students/1", json={"marks": {"qp": 19}}).get_json()
        self.assertEqual(r["marks"]["qp"], 19)
        self.assertEqual(r["marks"]["cp"], 13)
        self.assertEqual(r["name"], "Asha")
        self.assertEqual(self.c.patch("/api/students/1", json={}).status_code, 400)

    def test_delete(self):
        self.add()
        self.assertEqual(self.c.delete("/api/students/1").status_code, 204)
        self.assertEqual(self.c.delete("/api/students/1").status_code, 404)
        self.assertEqual(self.c.get("/api/students").get_json(), [])

    # ----- misc -----
    def test_subjects_endpoint(self):
        d = self.c.get("/api/subjects").get_json()
        self.assertEqual(d["max_score"], 20)
        self.assertEqual([s["label"] for s in d["subjects"]], ["QP", "CP", "Maths", "EE", "ECE"])
        self.assertEqual(d["subjects"][0]["scale"][0], {"min_marks": 19, "grade_point": 10})
        self.assertEqual(d["subjects"][3]["scale"][0], {"min_marks": 18, "grade_point": 10})

    def test_health_cors_and_json_errors(self):
        self.assertEqual(self.c.get("/api/health").get_json(), {"status": "ok"})
        self.assertIn("POST", self.c.options("/api/students").headers["Access-Control-Allow-Methods"])
        self.assertEqual(self.c.post("/api/health").status_code, 405)
        self.assertIn("error", self.c.get("/api/nope").get_json())


if __name__ == "__main__":
    unittest.main()