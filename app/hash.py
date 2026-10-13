"""Хэши расписания по целям (группа / преподаватель) в разрезе (корпус, день).

Формат ключа: `g:{groupId}` / `t:{teacherId}`. Hash — детерминированная строка;
совпадает с форматом из прежней node-версии.
"""
from __future__ import annotations

TargetKey = str  # "g:38" | "t:33"
TargetsSnapshot = dict[TargetKey, str]


def build_snapshots(week: dict) -> list[dict]:
    snapshots: list[dict] = []

    for day in week['days']:
        for building in day['buildings']:
            targets: TargetsSnapshot = {}

            for schedule in building.get('group_schedules', []):
                targets[f'g:{schedule["id"]}'] = _hash_pairs(schedule['pairs'])

            for teacher in building.get('teachers', []):
                targets[f't:{teacher["id"]}'] = _hash_assignments(teacher['assignments'])

            snapshots.append({
                'buildingSlug': building['building']['slug'],
                'date': day['date'],
                'targets': targets,
            })

    return snapshots


def _hash_pairs(pairs: list[dict]) -> str:
    parts = []
    for pair in sorted(
        (p for p in pairs if p['has_content']),
        key=lambda p: p['number'],
    ):
        lessons = sorted(
            f"{l['subgroup'] or '-'}|{l['subject']}|{l['teacher']}|{l['room']}"
            for l in pair['lessons']
        )
        marker = 's' if pair.get('is_split') else ''
        parts.append(f"{pair['number']}{marker} [{';;'.join(lessons)}]")
    return '|'.join(parts) or 'empty'


def _hash_assignments(assignments: list[dict]) -> str:
    parts = sorted(
        f"{a['pair_number']}|{a['group_id']}|{a['subgroup'] or '-'}|{a['subject']}|{a['room']}"
        for a in assignments
    )
    return '|'.join(parts) or 'empty'
