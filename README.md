# MecardStudio

A full-stack web application for creating and managing business cards. Built with a
**Django REST Framework** backend and a **React + Vite** frontend, organized as a
monorepo.

## Tech Stack

| Layer    | Technology                                             |
| -------- | ------------------------------------------------------ |
| Backend  | Python 3.12+, Django 5.2 LTS, Django REST Framework    |
| Database | MySQL / MariaDB 10.6+                                  |
| Frontend | React 19, Vite 8, JavaScript (ES modules)              |
| Tooling  | python-dotenv for configuration, django-cors-headers   |

> **Note:** Django is pinned to the 5.2 LTS release (supported until April 2028).
> Django 6.x requires MariaDB 10.11+ — see
> [Troubleshooting](#troubleshooting) if you consider upgrading.

## Project Structure

```
MecardStudio/
├── README.md                  # This file
├── .gitignore                 # Root ignore rules (Python, Node, env, OS)
│
├── backend/                   # Django backend
│   ├── manage.py              # Django CLI entry point
│   ├── requirements.txt       # Pinned Python dependencies
│   ├── .env.example           # Template for environment variables
│   ├── .env                   # Your local config (gitignored, never commit)
│   ├── MecardStudio/          # Project configuration package
│   │   ├── settings.py        # Settings (reads config from .env)
│   │   ├── urls.py            # Root URL routing
│   │   ├── wsgi.py            # WSGI entry point (production)
│   │   └── asgi.py            # ASGI entry point
│   └── api/                   # Main API application
│       ├── views.py           # View functions / API views
│       ├── urls.py            # API URL routing
│       ├── models.py          # Database models
│       ├── admin.py           # Django admin registration
│       └── migrations/        # Database migrations
│
└── frontend/                  # React frontend (Vite)
    ├── package.json           # npm dependencies and scripts
    ├── vite.config.js         # Vite config (proxies /api to Django)
    ├── index.html             # HTML entry point
    └── src/                   # React source code
        ├── main.jsx           # App entry point
        ├── App.jsx            # Root component
        └── assets/            # Static assets
```

## Prerequisites

| Tool              | Minimum Version          | Check with      |
| ----------------- | ------------------------ | --------------- |
| Python            | 3.12+                    | `python --version` |
| Node.js           | 20.19+ (22 LTS recommended) | `node --version` |
| npm               | 10+                      | `npm --version` |
| MySQL / MariaDB   | MariaDB 10.6+ / MySQL 8+ | `mysql --version` |
| Git               | —                        | `git --version` |

## Getting Started

### 1. Clone the repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd MecardStudio
```

### 2. Backend setup

```bash
cd backend

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows (PowerShell: venv\Scripts\Activate.ps1)

# Install dependencies
pip install -r requirements.txt
```

**Configure environment variables:**

```bash
cp .env.example .env
```

Edit `.env` and set your database credentials and a secret key:

| Variable               | Description                                  | Default                     |
| ---------------------- | -------------------------------------------- | --------------------------- |
| `DJANGO_SECRET_KEY`    | Django secret key (generate one for prod)    | insecure dev-only key       |
| `DJANGO_DEBUG`         | `True` / `False` — never `True` in production | `True`                     |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated list of allowed hosts        | `localhost,127.0.0.1`       |
| `DB_NAME`              | Database name                                | `mecard_studio`             |
| `DB_USER`              | Database user                                | `root`                      |
| `DB_PASSWORD`          | Database password                            | *(empty)*                   |
| `DB_HOST`              | Database host                                | `127.0.0.1`                 |
| `DB_PORT`              | Database port                                | `3306`                      |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origins allowed to call the API | Vite dev server origins |

> To generate a proper secret key:
> `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`

**Create the database** (if it doesn't exist yet):

```sql
CREATE DATABASE mecard_studio CHARACTER SET utf8mb4;
```

**Generate Static file:**

Django's built-in admin static files are handled automatically by
```bash
python manage.py collectstatic --noinput
```
**Genrate Django Secret Key
python3 -c "import secrets; print(secrets.token_urlsafe(50))"

**Run migrations and start the server:**

```bash
python manage.py migrate
python manage.py runserver
```

**Rund the seeder file
python manage.py seed_card_categories

The backend is now running at **http://127.0.0.1:8000**.
Verify it with: http://127.0.0.1:8000/api/health/

**Optional — create an admin user** (for Django admin at `/admin/`):

```bash
python manage.py createsuperuser
```

### 3. Frontend setup

Open a **second terminal**:

```bash
cd frontend
npm install
npm run dev
```

The frontend is now running at **http://localhost:5173**.
Vite proxies `/api/*` requests to the Django backend automatically, so you can
call the API directly from React:

```js
const res = await fetch('/api/health/')
```

## API Endpoints

| Method | Endpoint        | Description              |
| ------ | --------------- | ------------------------ |
| GET    | `/api/health/`  | Health check for the API |
| —      | `/admin/`       | Django admin panel       |

Add new endpoints by creating views in `backend/api/views.py` and routes in
`backend/api/urls.py` — they are automatically served under `/api/`.

## Useful Commands

| Command                             | Where      | Purpose                    |
| ----------------------------------- | ---------- | -------------------------- |
| `python manage.py runserver`        | `backend/` | Start the dev server       |
| `python manage.py makemigrations`   | `backend/` | Create migrations          |
| `python manage.py migrate`          | `backend/` | Apply migrations           |
| `python manage.py check`            | `backend/` | Validate project config    |
| `python manage.py test`             | `backend/` | Run backend tests          |
| `npm run dev`                       | `frontend/`| Start the Vite dev server  |
| `npm run build`                     | `frontend/`| Production build           |
| `npm run lint`                      | `frontend/`| Lint the frontend code     |

## Troubleshooting

**`mysqlclient` fails to install (Linux)**
Install the MySQL development headers first:
```bash
sudo apt install pkg-config default-libmysqlclient-dev build-essential
```

**`Unknown database 'mecard_studio'`**
The database hasn't been created. Run the `CREATE DATABASE` statement above and
retry `python manage.py migrate`.

**`MariaDB 10.11 or later is required`**
You're running Django 6.x against an older MariaDB. This project pins Django 5.2
LTS, which works with MariaDB 10.6+. Either keep 5.2 or upgrade your database
server to MariaDB 10.11+.

**Port already in use**
- Backend: run on another port with `python manage.py runserver 8001`
- Frontend: change the port in `frontend/vite.config.js` (and update
  `CORS_ALLOWED_ORIGINS` in `.env` accordingly).

**Frontend can't reach the API / CORS error**
- Make sure the backend server is running.
- Make sure your frontend origin is listed in `CORS_ALLOWED_ORIGINS` in `.env`,
  then restart the backend.

## Contributing

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Commit small, focused changes with clear messages.
3. Run `python manage.py check` and `npm run lint` before pushing.
4. Never commit `.env`, database files, or `venv/` — they are gitignored.

---

Built with Django 5.2 LTS and React 19.
