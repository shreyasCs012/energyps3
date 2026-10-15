import json

from eval.campaign import run_policy_campaign


def test_phase9_campaign_smoke_writes_paired_results(tmp_path):
    output = tmp_path / "phase9"
    report = run_policy_campaign(
        output_dir=output,
        seeds=3,
        scenarios=("S1",),
        campaign_seed=29,
        optimizer_seeds=1,
    )
    assert report["synthetic"] is True
    assert len(report["policy_rows"]) == 3 * 4
    assert set(row["policy"] for row in report["policy_rows"]) == {
        "P0_baseline",
        "P1_threshold_alert",
        "P2_idle_shutdown",
        "P3_optimizer",
    }
    assert (output / "policy_evaluation.json").is_file()
    assert (output / "policy_trials.csv").is_file()
    assert (output / "analytics" / "S1" / "analytics_report.json").is_file()
    assert (output / "reports" / "results.md").is_file()
    saved = json.loads((output / "policy_evaluation.json").read_text(encoding="utf-8"))
    assert saved["cv_evaluation"]["sample_count"] > 0
    assert set(saved["cv_evaluation"]["planner_input_ablations"]["S1"]) == {
        "no_cv",
        "cv_100",
        "cv_92",
        "cv_80",
    }
