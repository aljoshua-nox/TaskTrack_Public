# TaskTrack Public

TaskTrack is a Django web app for managing groups and tasks.

## Clone the Repository

```bash
git clone https://github.com/aljoshua-nox/TaskTrack_Public.git
cd TaskTrack_Public
```

## Run Locally

### 1) Create and activate a virtual environment

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2) Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Run migrations

```bash
python manage.py migrate
```

### 4) (Optional) Create an admin user

```bash
python manage.py createsuperuser
```

### 5) Start the development server

```bash
python manage.py runserver
```

Open: `http://127.0.0.1:8000/`

## Notes

- The app uses SQLite by default (`db.sqlite3`) unless environment variables override database settings.
- Static source files are in `static/`; collected static files are placed in `staticfiles/`.
