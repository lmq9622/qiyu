# Phase B：深度轮（12人设 x focused 18场景 x iters=100）
$env:QIYU_TEST_BASE = "http://127.0.0.1:8766"
$env:QIYU_TEST_WORKERS = "4"
$env:QIYU_TEST_TIMEOUT = "300"
# 注意：首次运行建议加 --clear 清空旧结果；断点续跑时去掉 --clear 并加 --resume 即可跳过已完成项
python test_harness\run_personas.py --label runB --scenarios focused --personas all --iters 100 --workers 4 --resume
Write-Host "Phase B done. Report: test_harness/report/report_personas_runB.md"
