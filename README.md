# Rate My Uni Life

## Project Description
Rate My Uni Life is an anonymous university review platform designed for students in Uzbekistan. Students can create anonymous posts about courses, professors, campus life, and general university experiences, then interact through comments, votes, and reports. The platform also includes admin moderation tools to help keep discussions useful and respectful.

Recent platform additions include:
- University community feeds with dedicated pages, scoped leaderboards, and joinable communities
- University media galleries for anonymous photo and video sharing
- A "Find My Uni" matching quiz that recommends universities based on learning preferences

## Tech Stack
- Flask
- SQLAlchemy
- Flask-Login
- Bootstrap 5
- Jinja2
- SQLite or MySQL
- JavaScript and jQuery
- University community and matching modules built on existing Flask blueprints

## Local Setup Instructions
1. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file from `.env.example` and update values as needed.

4. Run the application:
```bash
python3 app.py
```

5. Open the app in your browser at `http://127.0.0.1:5000`.

## How to Switch to MySQL
1. Make sure your local MySQL server is running.
2. Create a database, for example:
```sql
CREATE DATABASE rate_my_uni_life CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```
3. Update `.env`:
```env
USE_MYSQL=true
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DB=rate_my_uni_life
```
4. Start the app. The tables will be created automatically.

To use SQLite instead, set `USE_MYSQL=false` and the app will use `app.db`.

## How to Contribute
1. Fork or clone the repository.
2. Create a feature branch.
3. Make your changes and test them locally.
4. Open a pull request with a short explanation of what changed.

## Major Features
- Global anonymous review feed with filtering, voting, comments, and reports
- University community pages with member counts, top tags, and leaderboard posts
- University gallery pages for media sharing
- Interactive university matching quiz with top 3 recommendations

## Screenshots
- Homepage screenshot placeholder
- Post detail screenshot placeholder
- Admin dashboard screenshot placeholder
- University community screenshot placeholder
- Gallery screenshot placeholder
- Matching quiz screenshot placeholder
