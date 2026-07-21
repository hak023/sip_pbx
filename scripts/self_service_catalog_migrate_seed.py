"""
셀프서비스 카탈로그/Screen Graph 하드코딩 값 → 동적 구성 DB 1회성 마이그레이션 (Epic 2 Story 2.1 Task 4).

`settings_catalog.py::export_static_snapshot()`/`screen_graph.py::export_static_snapshot()`
(Story 2.4에서 export API와 공용으로 추출됨)가 만든 JSON을 그대로 읽어
`self_service_catalog_config` 테이블에 version 1(활성)로 시드한다.

이 시점에는 아직 `settings_catalog.py`/`screen_graph.py`가 DB를 읽어오도록 리팩터링되지
않았으므로(Story 2.2/2.3에서 진행), 이 스크립트를 실행해도 런타임 동작에는 영향이 없다 —
순수하게 "현재 하드코딩된 값과 동일한 내용을 DB에도 채워 두는" 준비 단계다.

사용법:
    python scripts/self_service_catalog_migrate_seed.py
    python scripts/self_service_catalog_migrate_seed.py --force   # 이미 시드되어 있어도 재실행
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai_voicebot.self_service import settings_catalog, screen_graph  # noqa: E402
from src.booking.database import init_db  # noqa: E402
from src.common import self_service_catalog_config_db as config_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="이미 활성 버전이 있어도 재시드")
    args = parser.parse_args()

    init_db()  # self_service_catalog_config 테이블이 없으면 생성(멱등)

    for kind, builder in (
        (config_db.CATALOG_KIND, settings_catalog.export_static_snapshot),
        (config_db.SCREEN_GRAPH_KIND, screen_graph.export_static_snapshot),
    ):
        existing = config_db.get_active_config(kind)
        if existing is not None and not args.force:
            print(f"[skip] '{kind}' 이미 활성 버전(v{existing['version_no']}) 존재 — --force로 재실행")
            continue

        config = builder()
        version_no = config_db.save_new_version(
            kind, config, uploaded_by="migration_script", note="Epic 2 Story 2.1 초기 시드",
        )
        if version_no is None:
            print(f"[error] '{kind}' 저장 실패")
            return 1
        ok = config_db.activate_version(kind, version_no)
        print(f"[{'ok' if ok else 'error'}] '{kind}' v{version_no} 시드 및 활성화 {'완료' if ok else '실패'}")
        if not ok:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
