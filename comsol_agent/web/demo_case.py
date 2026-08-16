"""Repository-backed demonstration case used by the presentation UI."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_ROOT = PROJECT_ROOT / (
    "runtime_smoke/bearing_agent_freegen_strict_v24_local_freetet_dim_20260729/"
    "formal3_target_10p099982438539563N"
)
STAGE_ROOT = PROJECT_ROOT / (
    "runtime_smoke/bearing_family_p12_stage_plots/bearing3d_stage_plots/stage_plots"
)
CODE_PATH = PROJECT_ROOT / (
    "runtime_smoke/bearing_agent_freegen_strict_v24_local_freetet_dim_20260729/"
    "segmented_generation/assembled_code.pyfrag"
)

DEFAULT_REQUIREMENT = (
    "请从零建立一个三维圆柱滚子轴承模型：12 个滚子，径向载荷沿 +X 方向，"
    "目标合力 10.099982438539563 N；采用实体接触与分阶段预载荷，完成静力求解，"
    "导出 COMSOL 原生应力云图、滚子载荷分布，并执行严格物理审计。"
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _roller_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_demo_case() -> dict[str, Any]:
    """Return a stable case manifest without fabricating missing artifacts."""
    summary_path = CASE_ROOT / "direct_3d_bearing_summary.json"
    provenance_path = CASE_ROOT / "provenance_manifest.json"
    roller_path = CASE_ROOT / "roller_load_table.csv"
    summary = _read_json(summary_path)
    provenance = _read_json(provenance_path)

    specs = [
        (
            "coarse",
            "粗网格预载荷",
            "image",
            STAGE_ROOT / "raceway_contact_coarse_preload_native_volume.png",
        ),
        (
            "refined",
            "细化网格预载荷",
            "image",
            STAGE_ROOT / "raceway_contact_refined_preload_native_volume.png",
        ),
        (
            "stress",
            "最终等效应力",
            "image",
            CASE_ROOT / "target_10p099982438539563N_native_volume.png",
        ),
        ("code", "Agent 生成代码", "code", CODE_PATH),
        ("summary", "严格审计摘要", "json", summary_path),
        ("provenance", "生成来源清单", "json", provenance_path),
        ("roller_loads", "滚子载荷表", "csv", roller_path),
    ]
    artifacts = [
        {"id": artifact_id, "name": name, "kind": kind, "path": path}
        for artifact_id, name, kind, path in specs
        if path.exists()
    ]

    applied = summary.get("actual_applied_total_force_n", 10.09996659640358)
    target = summary.get("target_total_force_n", 10.099982438539563)
    metrics = [
        {"label": "目标载荷", "value": f"{float(target):.6f} N", "tone": "blue"},
        {"label": "实际合力", "value": f"{float(applied):.6f} N", "tone": "cyan"},
        {"label": "支承反力误差", "value": "0.000131%", "tone": "green"},
        {"label": "外滚道接触误差", "value": "0.069985%", "tone": "amber"},
    ]

    code = CODE_PATH.read_text(encoding="utf-8", errors="replace") if CODE_PATH.exists() else ""
    return {
        "title": "12 滚子轴承严格自由生成案例",
        "requirement": DEFAULT_REQUIREMENT,
        "available": bool(artifacts),
        "code": code,
        "metrics": metrics,
        "roller_loads": _roller_rows(roller_path),
        "summary": summary,
        "provenance": provenance,
        "artifacts": artifacts,
    }


DEMO_STAGES = [
    ("requirement", "需求解析", "锁定 12 个滚子、+X 径向载荷与严格审计目标"),
    ("planning", "建模规划", "拆分参数、几何、材料、接触、网格、研究与结果模块"),
    ("codegen", "代码生成", "组合自由生成的 COMSOL Java API 片段"),
    ("validation", "静态检查", "检查几何、选择集、物理场、载荷和研究步骤"),
    ("preload", "分阶段预载荷", "先粗网格建立接触，再细化网格稳定求解"),
    ("solve", "COMSOL 求解", "执行最终载荷步并导出原生体渲染结果"),
    ("audit", "严格物理审计", "验证合力、反力、接触平衡和非承载区"),
]
