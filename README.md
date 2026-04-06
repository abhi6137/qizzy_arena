# Quizy+

Quizy+ is a production-oriented online quiz and examination platform built with Django (MVT), vanilla JavaScript, and responsive HTML/CSS.

## Highlights

- Multi-role architecture: Admin and Student
- Secure authentication with custom user model
- Full quiz CRUD with MCQ, True/False, and short-answer questions
- Adaptive quiz engine (difficulty shifts with performance)
- Anti-cheat telemetry (tab-switch and fullscreen exit tracking)
- Timer-driven quiz attempts with auto-submit
- Real-time live quiz mode with join code and polling leaderboard
- Gamification: points, streaks, badges, leaderboard, daily challenges
- Smart analytics for admins and students
- Detailed per-question result breakdown with optional PDF export
- Rule-based question generator from source text

## Tech Stack

- Backend: Django
- Frontend: Django templates + vanilla JavaScript + modern CSS
- Database: SQLite by default, MySQL-ready via environment variables

## Project Structure

- core/: landing and role-aware dashboard
- users/: custom user model, auth, profile
- quiz/: quiz domain, adaptive services, analytics, live sessions, APIs
- templates/: HTML templates
- static/: CSS and JavaScript assets
- fixtures/: sample data

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment:

```bash
copy .env.example .env
```

4. Run migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

5. (Optional) Load sample data:

```bash
python manage.py loaddata fixtures/sample_data.json
```

Demo credentials from fixture:

- Admin: `admin_demo` / `admin12345`
- Student: `student_demo` / `student12345`

6. Create a superuser (recommended for admin access):

```bash
python manage.py createsuperuser
```

7. Run server:

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000`.

## User Flows

### Admin

- Manage quizzes, questions, and generation from source text
- Configure difficulty, timer, negative marking, and anti-cheat settings
- Launch live sessions and monitor real-time leaderboard
- Review analytics dashboard and weak-topic insights

### Student

- Register/login and attempt quizzes
- Navigate with question navigator + autosave
- Receive instant result breakdown and export PDF
- Track trends, weak topics, badges, streaks, and leaderboard position

## Adaptive Engine Logic

Adaptive mode uses a lightweight heuristic:

- Correct answer -> target next harder difficulty level
- Wrong answer -> target next easier difficulty level
- If exact difficulty unavailable, nearest level is selected

## Security and Access Control

- CSRF protection enabled on all POST APIs
- Role-based route protection for admin/student views
- Ownership checks for attempt/result APIs
- Input validation for JSON endpoints and form submissions

## Real-Time Mode

Live quiz sessions support:

- Host-created session codes
- Student join by code
- Polling-based leaderboard updates for broad compatibility

## Testing

Run test suite:

```bash
python manage.py test
```

Covered cases include:

- negative marking and score computation
- partial submissions / unattempted handling
- timer expiry flow
- invalid API payload handling

## MySQL Upgrade

Set these `.env` variables:

- `DB_ENGINE=mysql`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`

Then install a MySQL driver compatible with Django and run migrations.

## Deployment Notes

For production:

- set `DJANGO_DEBUG=False`
- configure a strong `DJANGO_SECRET_KEY`
- set `DJANGO_ALLOWED_HOSTS`
- enable secure cookies (`SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`)
- configure static/media serving strategy
