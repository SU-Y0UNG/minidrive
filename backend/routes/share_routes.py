"""
공유 링크 관련 API
"""
import os
import secrets
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from auth import login_required
from models import get_db
from config import Config

share_bp = Blueprint('shares', __name__)


@share_bp.route('/api/shares', methods=['POST'])
@login_required
def create_share():
    """공유 링크 생성"""
    data = request.get_json()
    file_id = data.get('file_id')
    expires_hours = data.get('expires_hours')  # None이면 무기한

    if not file_id:
        return jsonify({'error': '파일을 선택해주세요'}), 400

    conn = get_db()
    cursor = conn.cursor()

    # 파일 소유 확인
    cursor.execute(
        "SELECT * FROM files WHERE id=%s AND user_id=%s",
        (file_id, request.user_id)
    )
    if not cursor.fetchone():
        conn.close()
        return jsonify({'error': '파일을 찾을 수 없습니다'}), 404

    # 토큰 생성
    token = secrets.token_urlsafe(32)

    # 만료 시간
    expires_at = None
    if expires_hours:
        from datetime import timedelta
        expires_at = datetime.now() + timedelta(hours=int(expires_hours))

    cursor.execute(
        """INSERT INTO shares (token, file_id, user_id, expires_at)
           VALUES (%s, %s, %s, %s)""",
        (token, file_id, request.user_id, expires_at)
    )

    conn.commit()
    conn.close()

    return jsonify({
        'message': '공유 링크 생성 완료',
        'share': {
            'token': token,
            'url': f'/share/{token}',
            'expires_at': expires_at.isoformat() if expires_at else None
        }
    }), 201


@share_bp.route('/api/shares', methods=['GET'])
@login_required
def get_shares():
    """내 공유 링크 목록"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.*, f.original_name, f.file_size, f.mime_type
        FROM shares s
        JOIN files f ON s.file_id = f.id
        WHERE s.user_id = %s
        ORDER BY s.created_at DESC
    """, (request.user_id,))

    shares = cursor.fetchall()
    conn.close()

    for s in shares:
        s['created_at'] = s['created_at'].isoformat() if s['created_at'] else None
        s['expires_at'] = s['expires_at'].isoformat() if s['expires_at'] else None
        s['is_expired'] = s['expires_at'] and datetime.fromisoformat(s['expires_at']) < datetime.now()

    return jsonify({'shares': shares})


@share_bp.route('/api/shares/<token>', methods=['DELETE'])
@login_required
def delete_share(token):
    """공유 링크 삭제"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM shares WHERE token=%s AND user_id=%s",
        (token, request.user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': '공유 링크 삭제 완료'})


@share_bp.route('/share/<token>')
def shared_file_info(token):
    """공유 파일 정보 (비로그인)"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.*, f.original_name, f.file_size, f.mime_type
        FROM shares s
        JOIN files f ON s.file_id = f.id
        WHERE s.token = %s
    """, (token,))

    share = cursor.fetchone()
    conn.close()

    if not share:
        return jsonify({'error': '공유 링크를 찾을 수 없습니다'}), 404

    # 만료 체크
    if share['expires_at'] and share['expires_at'] < datetime.now():
        return jsonify({'error': '만료된 링크입니다'}), 410

    return jsonify({
        'file_name': share['original_name'],
        'file_size': share['file_size'],
        'mime_type': share['mime_type'],
        'download_count': share['download_count']
    })


@share_bp.route('/share/<token>/download')
def download_shared_file(token):
    """공유 파일 다운로드 (비로그인)"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.*, f.original_name, f.stored_name, f.mime_type
        FROM shares s
        JOIN files f ON s.file_id = f.id
        WHERE s.token = %s
    """, (token,))

    share = cursor.fetchone()

    if not share:
        conn.close()
        return jsonify({'error': '공유 링크를 찾을 수 없습니다'}), 404

    if share['expires_at'] and share['expires_at'] < datetime.now():
        conn.close()
        return jsonify({'error': '만료된 링크입니다'}), 410

    # 다운로드 카운트 증가
    cursor.execute(
        "UPDATE shares SET download_count = download_count + 1 WHERE token=%s",
        (token,)
    )
    conn.commit()
    conn.close()

    filepath = os.path.join(Config.UPLOAD_FOLDER, share['stored_name'])
    return send_file(filepath, download_name=share['original_name'], as_attachment=True)
