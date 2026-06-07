# ☁️ MiniDrive - 파일 공유 드라이브

> 미니 Google Drive 클론 - 파일 업로드/다운로드, 폴더 관리, 공유 링크 생성

## 📌 주요 기능

- **📁 파일 관리**: 업로드, 다운로드, 삭제, 이름 변경
- **📂 폴더 관리**: 생성, 이동, 중첩 폴더 지원
- **🔗 공유 링크**: 만료 기간 설정 가능한 공유 링크
- **👀 미리보기**: 이미지/PDF 파일 미리보기
- **📊 용량 관리**: 사용자별 저장 용량 제한 (100MB)
- **🔐 사용자 인증**: 회원가입/로그인 (JWT)
- **🖱️ 드래그앤드롭**: 파일 드래그앤드롭 업로드

---

## 🛠️ 기술 스택

| 구분 | 기술 |
|------|------|
| 프론트엔드 | React + Tailwind CSS |
| 백엔드 | Flask (Python) |
| 데이터베이스 | MySQL |
| 인증 | JWT (JSON Web Token) |
| 파일 저장 | 로컬 (→ AWS S3 확장 가능) |

---

## 🚀 설치 및 실행

### 1. 백엔드

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt

# MySQL에서 DB 생성
# mysql -u root -p -e "CREATE DATABASE minidrive;"

# 환경변수 설정 (.env 파일)
cp .env.example .env
# .env 파일에서 DB 정보 수정

# 테이블 생성 및 서버 실행
python app.py
```

### 2. 프론트엔드

```bash
cd frontend
npm install
npm start
# http://localhost:3000 접속
```

---

## 📁 프로젝트 구조

```
mini-drive/
├── backend/
│   ├── app.py              # Flask 메인 앱
│   ├── config.py           # 설정
│   ├── models.py           # DB 모델
│   ├── auth.py             # 인증 (JWT)
│   ├── routes/
│   │   ├── file_routes.py  # 파일 API
│   │   ├── folder_routes.py # 폴더 API
│   │   └── share_routes.py # 공유 API
│   ├── uploads/            # 파일 저장소
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/     # React 컴포넌트
│   │   ├── pages/          # 페이지
│   │   ├── utils/          # 유틸 함수
│   │   └── App.jsx
│   └── package.json
└── README.md
```
