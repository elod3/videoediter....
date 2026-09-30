import json
import shutil

from test_pipeline import fake_transcript

from vedit.evals import main


def make_case(root, name, prompt, expect, talking_video):
    d = root / name
    d.mkdir(parents=True)
    shutil.copy(talking_video, d / "vlog.mp4")
    (d / "t.json").write_text(fake_transcript().model_dump_json())
    (d / "case.json").write_text(json.dumps({"prompt": prompt, "assets": ["vlog.mp4"],
                                             "transcripts": {"a0": "t.json"}, "expect": expect}))


def test_eval_runs_cases_and_reports(vhome, tmp_path, talking_video):
    cases = tmp_path / "cases"
    make_case(cases, "tiktok-ok", "Pentru TikTok: fără pauze, 9:16, subtitrări",
              {"format": "9:16", "duration_min": 4, "duration_max": 7, "captions": True, "qa_ok": True,
               "max_midword_cuts": 0, "must_call": ["cut_silences"], "must_not_call": ["broll_generate"]},
              talking_video)
    make_case(cases, "asteptare-gresita", "taie pauzele", {"format": "9:16", "duration_max": 3}, talking_video)
    out = tmp_path / "rep"
    code = main([str(cases), "--runner", "scripted", "--out", str(out)])
    assert code == 1                                  # un caz trebuie să pice
    res = {r["case"]: r for r in json.loads((out / "results.json").read_text())}
    assert all(c["ok"] for c in res["tiktok-ok"]["checks"]), res["tiktok-ok"]["checks"]
    bad = {c["name"]: c for c in res["asteptare-gresita"]["checks"]}
    assert not bad["format 9:16"]["ok"] and not bad["durată 0-3s"]["ok"]
    md = (out / "report.md").read_text()
    assert "1/2 cazuri trecute" in md and "❌" in md and "cut_silences" in md
