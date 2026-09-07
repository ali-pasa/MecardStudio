# Installation & Setup

Follow the steps below to set up MecardStudio locally.

## Prerequisites

Make sure the following are installed on your system:

- Python 3.x
- pip
- Node.js
- npm
- MySQL
- Git

1. Clone the Repository

Clone the repository from GitHub:
git clone <YOUR_REPOSITORY_URL>

2. Go to Backend folder
cd backend

3. Navigate to Backend
python -m venv venv

Windows
venv\Scripts\activate

Linux / macOS
source venv/bin/activate

4. Install Python Dependencies
pip install -r requirements.txt

5. Configure Database
CREATE DATABASE mecardstudio;

6. Run Database Migrations
python manage.py makemigrations

8. Start Backend Server
python manage.py runserver