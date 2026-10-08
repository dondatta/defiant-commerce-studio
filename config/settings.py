from pathlib import Path
import os
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv('DEBUG', '1') == '1'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'local-development-only-change-before-deployment')
if not DEBUG and SECRET_KEY == 'local-development-only-change-before-deployment':
    raise RuntimeError('Set DJANGO_SECRET_KEY for production')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','studio']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
if os.getenv('POSTGRES_DB'):
    DATABASES = {'default':{'ENGINE':'django.db.backends.postgresql','NAME':os.environ['POSTGRES_DB'],'USER':os.getenv('POSTGRES_USER','postgres'),'PASSWORD':os.getenv('POSTGRES_PASSWORD',''),'HOST':os.getenv('POSTGRES_HOST','localhost'),'PORT':os.getenv('POSTGRES_PORT','5432')}}
else:
    DATABASES = {'default':{'ENGINE':'django.db.backends.sqlite3','NAME':BASE_DIR / 'db.sqlite3','OPTIONS':{'timeout':30}}}
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / '.static'
PRIVATE_STORAGE_ROOT = Path(os.getenv('PRIVATE_STORAGE_ROOT', str(BASE_DIR / '.private')))
STORAGE_BACKEND = os.getenv('STORAGE_BACKEND','local')
S3_BUCKET = os.getenv('S3_BUCKET','')
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL')
S3_REGION = os.getenv('S3_REGION','us-east-1')
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/brands/'
LOGOUT_REDIRECT_URL = '/login/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
