"""
☁️ MiniDrive - 파일 공유 드라이브
Flask 메인 애플리케이션
"""
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from config import Config
from models import init_db, get_db
from auth import hash_password, create_token, login_required
from routes.file_routes import file_bp
from routes.folder_routes import folder_bp
from routes.share_routes import share_bp

app = Flask(__name__)
CORS(app)

# Blueprint 등록
app.register_blueprint(file_bp)
app.register_blueprint(folder_bp)
app.register_blueprint(share_bp)


# ========== 인증 API ==========

@app.route('/api/auth/register', methods=['POST'])
def register():
    """회원가입"""
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    username = data.get('username', '').strip()

    if not all([email, password, username]):
        return jsonify({'error': '모든 항목을 입력해주세요'}), 400

    if len(password) < 6:
        return jsonify({'error': '비밀번호는 6자 이상이어야 합니다'}), 400

    conn = get_db()
    cursor = conn.cursor()

    # 이메일 중복 체크
    cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'error': '이미 가입된 이메일입니다'}), 400

    # 사용자 생성
    cursor.execute(
        "INSERT INTO users (email, password, username) VALUES (%s, %s, %s)",
        (email, hash_password(password), username)
    )

    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    token = create_token(user_id)

    return jsonify({
        'message': '가입 완료',
        'token': token,
        'user': {'id': user_id, 'email': email, 'username': username}
    }), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
    """로그인"""
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not all([email, password]):
        return jsonify({'error': '이메일과 비밀번호를 입력해주세요'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE email=%s AND password=%s",
        (email, hash_password(password))
    )
    user = cursor.fetchone()
    conn.close()

    if not user:
        return jsonify({'error': '이메일 또는 비밀번호가 일치하지 않습니다'}), 401

    token = create_token(user['id'])

    return jsonify({
        'token': token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'username': user['username']
        }
    })


@app.route('/api/auth/me')
@login_required
def get_me():
    """내 정보 조회"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, email, username, storage_used, created_at FROM users WHERE id=%s",
        (request.user_id,)
    )
    user = cursor.fetchone()
    conn.close()

    if user:
        user['created_at'] = user['created_at'].isoformat() if user['created_at'] else None
        user['storage_used_mb'] = round(user['storage_used'] / (1024 * 1024), 2)
        user['storage_total_mb'] = round(Config.MAX_STORAGE_BYTES / (1024 * 1024), 2)

    return jsonify({'user': user})


if __name__ == '__main__':
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    init_db()
    print("☁️ MiniDrive 서버 시작!")
    app.run(debug=True, host='0.0.0.0', port=5000)
