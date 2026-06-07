"""
파일 관련 API
"""
import os
import uuid
import hashlib
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, send_file
from auth import login_required
from models import get_db
from config import Config

file_bp = Blueprint('files', __name__)


@file_bp.route('/api/files', methods=['GET'])
@login_required
def get_files():
    """현재 폴더의 파일 목록"""
    folder_id = request.args.get('folder_id')
    search = request.args.get('search', '').strip()
    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if search:
        cursor.execute(
            """SELECT * FROM files WHERE user_id=%s
               AND original_name LIKE %s
               AND is_deleted=FALSE
               AND (is_scheduled = FALSE OR visible_after <= %s)
               ORDER BY created_at DESC""",
            (request.user_id, f'%{search}%', now)
        )
    elif folder_id:
        cursor.execute(
            """SELECT * FROM files WHERE user_id=%s AND folder_id=%s
               AND is_deleted=FALSE
               AND (is_scheduled = FALSE OR visible_after <= %s)
               ORDER BY created_at DESC""",
            (request.user_id, folder_id, now)
        )
    else:
        cursor.execute(
            """SELECT * FROM files WHERE user_id=%s AND folder_id IS NULL
               AND is_deleted=FALSE
               AND (is_scheduled = FALSE OR visible_after <= %s)
               ORDER BY created_at DESC""",
            (request.user_id, now)
        )

    files = cursor.fetchall()
    conn.close()

    for f in files:
        f['created_at'] = f['created_at'].isoformat() if f['created_at'] else None
        f['visible_after'] = f['visible_after'].isoformat() if f.get('visible_after') else None

    return jsonify({'files': files})


@file_bp.route('/api/files/upload', methods=['POST'])
@login_required
def upload_file():
    """파일 업로드 (중복탐지 + 자동분류 + 예약)"""
    if 'file' not in request.files:
        return jsonify({'error': '파일을 선택해주세요'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일을 선택해주세요'}), 400

    folder_id = request.form.get('folder_id') or None
    schedule_minutes = request.form.get('schedule_minutes')  # 예약 업로드 (분)
    duplicate_action = request.form.get('duplicate_action', 'ask')  # ask, replace, keep

    # 파일 크기 체크
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > Config.MAX_FILE_SIZE:
        return jsonify({'error': '파일이 너무 큽니다 (최대 50MB)'}), 400

    # 해시 계산
    file_data = file.read()
    file_hash = hashlib.sha256(file_data).hexdigest()
    file.seek(0)

    conn = get_db()
    cursor = conn.cursor()

    # 사용자 용량 체크
    cursor.execute("SELECT storage_used FROM users WHERE id=%s", (request.user_id,))
    user = cursor.fetchone()

    if user['storage_used'] + file_size > Config.MAX_STORAGE_BYTES:
        conn.close()
        return jsonify({'error': '저장 용량이 부족합니다'}), 400

    # 중복 파일 체크
    cursor.execute(
        "SELECT id, original_name, folder_id FROM files WHERE user_id=%s AND file_hash=%s",
        (request.user_id, file_hash)
    )
    duplicate = cursor.fetchone()

    if duplicate and duplicate_action == 'ask':
        conn.close()
        return jsonify({
            'duplicate': True,
            'existing_file': {
                'id': duplicate['id'],
                'name': duplicate['original_name'],
                'folder_id': duplicate['folder_id']
            },
            'message': f"'{duplicate['original_name']}' 파일과 동일한 파일이 이미 존재합니다."
        }), 409

    if duplicate and duplicate_action == 'replace':
        # 기존 파일 삭제
        cursor.execute("SELECT stored_name, file_size FROM files WHERE id=%s", (duplicate['id'],))
        old = cursor.fetchone()
        old_path = os.path.join(Config.UPLOAD_FOLDER, old['stored_name'])
        if os.path.exists(old_path):
            os.remove(old_path)
        cursor.execute("DELETE FROM files WHERE id=%s", (duplicate['id'],))
        cursor.execute(
            "UPDATE users SET storage_used = storage_used - %s WHERE id=%s",
            (old['file_size'], request.user_id)
        )

    # 자동 분류 규칙 적용 (폴더 미지정 시)
    if not folder_id:
        folder_id = _apply_auto_rules(cursor, request.user_id, file.filename)

    # 파일 저장
    ext = os.path.splitext(file.filename)[1]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(Config.UPLOAD_FOLDER, stored_name)
    with open(filepath, 'wb') as f:
        f.write(file_data)

    # 예약 처리
    is_scheduled = False
    visible_after = None
    if schedule_minutes:
        is_scheduled = True
        visible_after = datetime.now() + timedelta(minutes=int(schedule_minutes))

    # DB 저장
    cursor.execute(
        """INSERT INTO files (original_name, stored_name, file_size, mime_type, file_hash, folder_id, user_id, is_scheduled, visible_after)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (file.filename, stored_name, file_size, file.content_type, file_hash,
         folder_id, request.user_id, is_scheduled, visible_after)
    )

    # 용량 업데이트
    cursor.execute(
        "UPDATE users SET storage_used = storage_used + %s WHERE id=%s",
        (file_size, request.user_id)
    )

    conn.commit()
    file_id = cursor.lastrowid
    conn.close()

    result = {
        'message': '업로드 완료',
        'file': {
            'id': file_id,
            'original_name': file.filename,
            'file_size': file_size,
            'auto_folder_id': folder_id,
        }
    }

    if is_scheduled:
        result['message'] = f'예약 업로드 완료 ({schedule_minutes}분 후 공개)'
        result['file']['visible_after'] = visible_after.isoformat()

    return jsonify(result), 201


def _apply_auto_rules(cursor, user_id, filename):
    """자동 분류 규칙 매칭"""
    cursor.execute(
        "SELECT * FROM auto_rules WHERE user_id=%s ORDER BY priority DESC, id ASC",
        (user_id,)
    )
    rules = cursor.fetchall()

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    name_lower = filename.lower()

    for rule in rules:
        if rule['rule_type'] == 'extension' and ext == rule['pattern'].lower().strip('.'):
            return rule['folder_id']
        elif rule['rule_type'] == 'filename' and rule['pattern'].lower() in name_lower:
            return rule['folder_id']

    return None


@file_bp.route('/api/files/<int:file_id>', methods=['DELETE'])
@login_required
def delete_file(file_id):
    """파일 삭제 → 휴지통으로 이동 (soft delete)"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM files WHERE id=%s AND user_id=%s",
        (file_id, request.user_id)
    )
    file = cursor.fetchone()

    if not file:
        conn.close()
        return jsonify({'error': '파일을 찾을 수 없습니다'}), 404

    cursor.execute(
        "UPDATE files SET is_deleted=TRUE, deleted_at=NOW() WHERE id=%s",
        (file_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '휴지통으로 이동 완료'})


@file_bp.route('/api/trash', methods=['GET'])
@login_required
def get_trash():
    """휴지통 파일 목록"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM files WHERE user_id=%s AND is_deleted=TRUE ORDER BY deleted_at DESC",
        (request.user_id,)
    )
    files = cursor.fetchall()
    conn.close()

    for f in files:
        f['created_at'] = f['created_at'].isoformat() if f['created_at'] else None
        f['deleted_at'] = f['deleted_at'].isoformat() if f['deleted_at'] else None

    return jsonify({'files': files})


@file_bp.route('/api/trash/<int:file_id>/restore', methods=['POST'])
@login_required
def restore_file(file_id):
    """휴지통에서 복원"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE files SET is_deleted=FALSE, deleted_at=NULL WHERE id=%s AND user_id=%s",
        (file_id, request.user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '복원 완료'})


@file_bp.route('/api/trash/<int:file_id>', methods=['DELETE'])
@login_required
def permanent_delete(file_id):
    """영구 삭제"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM files WHERE id=%s AND user_id=%s AND is_deleted=TRUE",
        (file_id, request.user_id)
    )
    file = cursor.fetchone()

    if not file:
        conn.close()
        return jsonify({'error': '파일을 찾을 수 없습니다'}), 404

    filepath = os.path.join(Config.UPLOAD_FOLDER, file['stored_name'])
    if os.path.exists(filepath):
        os.remove(filepath)

    cursor.execute("DELETE FROM files WHERE id=%s", (file_id,))
    cursor.execute(
        "UPDATE users SET storage_used = storage_used - %s WHERE id=%s",
        (file['file_size'], request.user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '영구 삭제 완료'})


@file_bp.route('/api/trash/empty', methods=['DELETE'])
@login_required
def empty_trash():
    """휴지통 비우기"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT stored_name, file_size FROM files WHERE user_id=%s AND is_deleted=TRUE",
        (request.user_id,)
    )
    files = cursor.fetchall()

    total_freed = 0
    for f in files:
        filepath = os.path.join(Config.UPLOAD_FOLDER, f['stored_name'])
        if os.path.exists(filepath):
            os.remove(filepath)
        total_freed += f['file_size']

    cursor.execute("DELETE FROM files WHERE user_id=%s AND is_deleted=TRUE", (request.user_id,))
    cursor.execute(
        "UPDATE users SET storage_used = storage_used - %s WHERE id=%s",
        (total_freed, request.user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '휴지통 비우기 완료', 'freed_bytes': total_freed})


@file_bp.route('/api/files/<int:file_id>/download')
@login_required
def download_file(file_id):
    """파일 다운로드"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM files WHERE id=%s AND user_id=%s",
        (file_id, request.user_id)
    )
    file = cursor.fetchone()
    conn.close()

    if not file:
        return jsonify({'error': '파일을 찾을 수 없습니다'}), 404

    filepath = os.path.join(Config.UPLOAD_FOLDER, file['stored_name'])
    return send_file(filepath, download_name=file['original_name'], as_attachment=True)


@file_bp.route('/api/files/<int:file_id>/preview')
@login_required
def preview_file(file_id):
    """파일 미리보기"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM files WHERE id=%s AND user_id=%s",
        (file_id, request.user_id)
    )
    file = cursor.fetchone()
    conn.close()

    if not file:
        return jsonify({'error': '파일을 찾을 수 없습니다'}), 404

    ext = file['original_name'].rsplit('.', 1)[-1].lower()
    if ext not in Config.ALLOWED_PREVIEW:
        return jsonify({'error': '미리보기를 지원하지 않는 파일입니다'}), 400

    filepath = os.path.join(Config.UPLOAD_FOLDER, file['stored_name'])
    return send_file(filepath, mimetype=file['mime_type'])


@file_bp.route('/api/files/<int:file_id>/rename', methods=['PATCH'])
@login_required
def rename_file(file_id):
    """파일 이름 변경"""
    data = request.get_json()
    new_name = data.get('name', '').strip()

    if not new_name:
        return jsonify({'error': '파일 이름을 입력해주세요'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE files SET original_name=%s WHERE id=%s AND user_id=%s",
        (new_name, file_id, request.user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '이름 변경 완료'})


@file_bp.route('/api/files/<int:file_id>/move', methods=['PATCH'])
@login_required
def move_file(file_id):
    """파일 이동"""
    data = request.get_json()
    folder_id = data.get('folder_id')  # None이면 루트로 이동

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE files SET folder_id=%s WHERE id=%s AND user_id=%s",
        (folder_id, file_id, request.user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '이동 완료'})


@file_bp.route('/api/storage')
@login_required
def get_storage():
    """사용자 저장 용량 조회"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT storage_used FROM users WHERE id=%s", (request.user_id,))
    user = cursor.fetchone()
    conn.close()

    return jsonify({
        'used': user['storage_used'],
        'total': Config.MAX_STORAGE_BYTES,
        'used_mb': round(user['storage_used'] / (1024 * 1024), 2),
        'total_mb': round(Config.MAX_STORAGE_BYTES / (1024 * 1024), 2)
    })


# ========== 중복 파일 스캔 ==========

@file_bp.route('/api/files/duplicates')
@login_required
def scan_duplicates():
    """전체 드라이브 중복 파일 스캔"""
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT file_hash, COUNT(*) as cnt
            FROM files
            WHERE user_id=%s AND file_hash IS NOT NULL AND is_deleted=FALSE
            GROUP BY file_hash
            HAVING cnt > 1
        """, (request.user_id,))
        dup_hashes = cursor.fetchall()

        groups = []
        for dh in dup_hashes:
            cursor.execute(
                "SELECT id, original_name, file_size, folder_id, created_at FROM files WHERE user_id=%s AND file_hash=%s AND is_deleted=FALSE ORDER BY created_at ASC",
                (request.user_id, dh['file_hash'])
            )
            files = cursor.fetchall()
            for f in files:
                f['created_at'] = f['created_at'].isoformat() if f['created_at'] else None
            groups.append({'hash': dh['file_hash'], 'count': dh['cnt'], 'files': files})

        conn.close()
        return jsonify({'duplicate_groups': groups, 'total_groups': len(groups)})
    except Exception as e:
        conn.close()
        return jsonify({'duplicate_groups': [], 'total_groups': 0, 'error': str(e)})


# ========== 자동 분류 규칙 ==========

@file_bp.route('/api/rules', methods=['GET'])
@login_required
def get_rules():
    """자동 분류 규칙 목록"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT r.*, f.name as folder_name
        FROM auto_rules r
        LEFT JOIN folders f ON r.folder_id = f.id
        WHERE r.user_id=%s
        ORDER BY r.priority DESC, r.id ASC
    """, (request.user_id,))
    rules = cursor.fetchall()
    conn.close()

    for r in rules:
        r['created_at'] = r['created_at'].isoformat() if r['created_at'] else None

    return jsonify({'rules': rules})


@file_bp.route('/api/rules', methods=['POST'])
@login_required
def create_rule():
    """자동 분류 규칙 추가"""
    data = request.get_json()
    rule_type = data.get('rule_type')  # extension 또는 filename
    pattern = data.get('pattern', '').strip()
    folder_id = data.get('folder_id')
    priority = data.get('priority', 0)

    if not all([rule_type, pattern, folder_id]):
        return jsonify({'error': '모든 항목을 입력해주세요'}), 400

    if rule_type not in ('extension', 'filename'):
        return jsonify({'error': '규칙 유형은 extension 또는 filename이어야 합니다'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO auto_rules (user_id, rule_type, pattern, folder_id, priority) VALUES (%s, %s, %s, %s, %s)",
        (request.user_id, rule_type, pattern, folder_id, priority)
    )

    conn.commit()
    rule_id = cursor.lastrowid
    conn.close()

    return jsonify({'message': '규칙 추가 완료', 'rule_id': rule_id}), 201


@file_bp.route('/api/rules/<int:rule_id>', methods=['DELETE'])
@login_required
def delete_rule(rule_id):
    """자동 분류 규칙 삭제"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM auto_rules WHERE id=%s AND user_id=%s", (rule_id, request.user_id))
    conn.commit()
    conn.close()

    return jsonify({'message': '규칙 삭제 완료'})


# ========== 예약 파일 ==========

@file_bp.route('/api/files/scheduled')
@login_required
def get_scheduled():
    """예약된 파일 목록"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """SELECT * FROM files
           WHERE user_id=%s AND is_scheduled=TRUE AND visible_after > NOW()
           ORDER BY visible_after ASC""",
        (request.user_id,)
    )
    files = cursor.fetchall()
    conn.close()

    for f in files:
        f['created_at'] = f['created_at'].isoformat() if f['created_at'] else None
        f['visible_after'] = f['visible_after'].isoformat() if f['visible_after'] else None

    return jsonify({'scheduled_files': files})