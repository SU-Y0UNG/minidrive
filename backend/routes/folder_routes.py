"""
폴더 관련 API
"""
from flask import Blueprint, request, jsonify
from auth import login_required
from models import get_db

folder_bp = Blueprint('folders', __name__)


@folder_bp.route('/api/folders', methods=['GET'])
@login_required
def get_folders():
    """현재 위치의 폴더 목록"""
    parent_id = request.args.get('parent_id')
    get_all = request.args.get('all')
    conn = get_db()
    cursor = conn.cursor()

    if get_all:
        cursor.execute(
            "SELECT * FROM folders WHERE user_id=%s AND is_trashed=FALSE ORDER BY name",
            (request.user_id,)
        )
    elif parent_id:
        cursor.execute(
            "SELECT * FROM folders WHERE user_id=%s AND parent_id=%s AND is_trashed=FALSE ORDER BY name",
            (request.user_id, parent_id)
        )
    else:
        cursor.execute(
            "SELECT * FROM folders WHERE user_id=%s AND parent_id IS NULL AND is_trashed=FALSE ORDER BY name",
            (request.user_id,)
        )

    folders = cursor.fetchall()
    conn.close()

    for f in folders:
        f['created_at'] = f['created_at'].isoformat() if f['created_at'] else None

    return jsonify({'folders': folders})


@folder_bp.route('/api/folders', methods=['POST'])
@login_required
def create_folder():
    """폴더 생성"""
    data = request.get_json()
    name = data.get('name', '').strip()
    parent_id = data.get('parent_id') or None

    if not name:
        return jsonify({'error': '폴더 이름을 입력해주세요'}), 400

    conn = get_db()
    cursor = conn.cursor()

    # 같은 위치에 같은 이름 폴더 체크
    if parent_id:
        cursor.execute(
            "SELECT id FROM folders WHERE user_id=%s AND parent_id=%s AND name=%s AND is_trashed=FALSE",
            (request.user_id, parent_id, name)
        )
    else:
        cursor.execute(
            "SELECT id FROM folders WHERE user_id=%s AND parent_id IS NULL AND name=%s AND is_trashed=FALSE",
            (request.user_id, name)
        )

    if cursor.fetchone():
        conn.close()
        return jsonify({'error': '같은 이름의 폴더가 이미 있습니다'}), 400

    cursor.execute(
        "INSERT INTO folders (name, parent_id, user_id) VALUES (%s, %s, %s)",
        (name, parent_id, request.user_id)
    )

    conn.commit()
    folder_id = cursor.lastrowid
    conn.close()

    return jsonify({
        'message': '폴더 생성 완료',
        'folder': {'id': folder_id, 'name': name}
    }), 201


@folder_bp.route('/api/folders/<int:folder_id>', methods=['DELETE'])
@login_required
def delete_folder(folder_id):
    """폴더를 휴지통으로 이동"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM folders WHERE id=%s AND user_id=%s AND is_trashed=FALSE",
        (folder_id, request.user_id)
    )
    folder = cursor.fetchone()

    if not folder:
        conn.close()
        return jsonify({'error': '폴더를 찾을 수 없습니다'}), 404

    # 폴더와 하위 파일들을 휴지통으로
    cursor.execute(
        "UPDATE folders SET is_trashed=TRUE, trashed_at=NOW() WHERE id=%s",
        (folder_id,)
    )

    # 하위 파일도 휴지통으로
    _trash_folder_contents(cursor, folder_id, request.user_id)

    conn.commit()
    conn.close()

    return jsonify({'message': '휴지통으로 이동됨'})


@folder_bp.route('/api/folders/<int:folder_id>/permanent', methods=['DELETE'])
@login_required
def permanent_delete_folder(folder_id):
    """폴더 영구 삭제"""
    import os
    from config import Config

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM folders WHERE id=%s AND user_id=%s",
        (folder_id, request.user_id)
    )
    folder = cursor.fetchone()

    if not folder:
        conn.close()
        return jsonify({'error': '폴더를 찾을 수 없습니다'}), 404

    total_size = _get_folder_size(cursor, folder_id, request.user_id)

    # 실제 파일 삭제
    _delete_folder_files(cursor, folder_id, request.user_id)

    cursor.execute("DELETE FROM folders WHERE id=%s", (folder_id,))
    cursor.execute(
        "UPDATE users SET storage_used = GREATEST(0, storage_used - %s) WHERE id=%s",
        (total_size, request.user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '영구 삭제 완료'})


@folder_bp.route('/api/folders/<int:folder_id>/restore', methods=['PATCH'])
@login_required
def restore_folder(folder_id):
    """폴더를 휴지통에서 복원"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM folders WHERE id=%s AND user_id=%s AND is_trashed=TRUE",
        (folder_id, request.user_id)
    )
    folder = cursor.fetchone()

    if not folder:
        conn.close()
        return jsonify({'error': '폴더를 찾을 수 없습니다'}), 404

    # 부모 폴더가 휴지통이면 루트로 복원
    if folder['parent_id']:
        cursor.execute("SELECT is_trashed FROM folders WHERE id=%s", (folder['parent_id'],))
        parent = cursor.fetchone()
        if parent and parent['is_trashed']:
            cursor.execute(
                "UPDATE folders SET is_trashed=FALSE, trashed_at=NULL, parent_id=NULL WHERE id=%s",
                (folder_id,)
            )
        else:
            cursor.execute(
                "UPDATE folders SET is_trashed=FALSE, trashed_at=NULL WHERE id=%s",
                (folder_id,)
            )
    else:
        cursor.execute(
            "UPDATE folders SET is_trashed=FALSE, trashed_at=NULL WHERE id=%s",
            (folder_id,)
        )

    # 하위 파일도 복원
    cursor.execute(
        "UPDATE files SET is_trashed=FALSE, trashed_at=NULL WHERE folder_id=%s AND user_id=%s",
        (folder_id, request.user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '복원 완료'})


@folder_bp.route('/api/folders/<int:folder_id>/rename', methods=['PATCH'])
@login_required
def rename_folder(folder_id):
    """폴더 이름 변경"""
    data = request.get_json()
    new_name = data.get('name', '').strip()

    if not new_name:
        return jsonify({'error': '폴더 이름을 입력해주세요'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE folders SET name=%s WHERE id=%s AND user_id=%s",
        (new_name, folder_id, request.user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '이름 변경 완료'})


@folder_bp.route('/api/folders/<int:folder_id>/path')
@login_required
def get_folder_path(folder_id):
    """폴더 경로 (빵 부스러기 네비게이션용)"""
    conn = get_db()
    cursor = conn.cursor()

    path = []
    current_id = folder_id

    while current_id:
        cursor.execute(
            "SELECT id, name, parent_id FROM folders WHERE id=%s AND user_id=%s",
            (current_id, request.user_id)
        )
        folder = cursor.fetchone()

        if not folder:
            break

        path.insert(0, {'id': folder['id'], 'name': folder['name']})
        current_id = folder['parent_id']

    conn.close()
    return jsonify({'path': path})


def _trash_folder_contents(cursor, folder_id, user_id):
    """폴더 내 파일/서브폴더를 재귀적으로 휴지통 이동"""
    cursor.execute(
        "UPDATE files SET is_trashed=TRUE, trashed_at=NOW(), original_folder_id=folder_id WHERE folder_id=%s AND user_id=%s",
        (folder_id, user_id)
    )
    cursor.execute(
        "SELECT id FROM folders WHERE parent_id=%s AND user_id=%s",
        (folder_id, user_id)
    )
    subfolders = cursor.fetchall()
    for sub in subfolders:
        cursor.execute(
            "UPDATE folders SET is_trashed=TRUE, trashed_at=NOW() WHERE id=%s",
            (sub['id'],)
        )
        _trash_folder_contents(cursor, sub['id'], user_id)


def _delete_folder_files(cursor, folder_id, user_id):
    """폴더 내 실제 파일 삭제 (재귀)"""
    import os
    from config import Config

    cursor.execute(
        "SELECT stored_name FROM files WHERE folder_id=%s AND user_id=%s",
        (folder_id, user_id)
    )
    for f in cursor.fetchall():
        filepath = os.path.join(Config.UPLOAD_FOLDER, f['stored_name'])
        if os.path.exists(filepath):
            os.remove(filepath)
        thumb_path = os.path.join(Config.UPLOAD_FOLDER, 'thumbs', f['stored_name'])
        if os.path.exists(thumb_path):
            os.remove(thumb_path)

    cursor.execute(
        "SELECT id FROM folders WHERE parent_id=%s AND user_id=%s",
        (folder_id, user_id)
    )
    for sub in cursor.fetchall():
        _delete_folder_files(cursor, sub['id'], user_id)


def _get_folder_size(cursor, folder_id, user_id):
    """폴더 내 전체 파일 크기 (재귀)"""
    total = 0

    cursor.execute(
        "SELECT COALESCE(SUM(file_size), 0) as total FROM files WHERE folder_id=%s AND user_id=%s",
        (folder_id, user_id)
    )
    total += cursor.fetchone()['total']

    cursor.execute(
        "SELECT id FROM folders WHERE parent_id=%s AND user_id=%s",
        (folder_id, user_id)
    )
    subfolders = cursor.fetchall()

    for sub in subfolders:
        total += _get_folder_size(cursor, sub['id'], user_id)

    return total