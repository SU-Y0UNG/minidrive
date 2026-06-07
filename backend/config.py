"""
설정 파일
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # MySQL
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'minidrive')

    # JWT
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'dev-secret-key')
    JWT_ACCESS_TOKEN_EXPIRES = 86400  # 24시간 (초)

    # 파일 업로드
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
    MAX_STORAGE_BYTES = int(os.getenv('MAX_STORAGE_MB', 100)) * 1024 * 1024
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 단일 파일 50MB 제한

    ALLOWED_PREVIEW = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'svg'}
