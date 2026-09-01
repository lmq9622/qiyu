# Phase A：诊断轮（12人设 x focused 18场景 x iters=5）
$env:QIYU_TEST_BASE = "http://127.0.0.1:8766"
$env:QIYU_TEST_WORKERS = "4"
$env:QIYU_TEST_TIMEOUT = "300"
python test_harness\run_personas.py --label runA --scenarios focused --personas all --iters 5 --workers 4 --clear
Write-Host "Phase A done. Report: test_harness/report/report_personas_runA.md"
