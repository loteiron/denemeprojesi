import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "cokgizlisifre")
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_DB = os.environ.get("MYSQL_DB", "sinav_rezervasyon")
    MYSQL_CURSORCLASS = "DictCursor"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False # Sunucuya alındığında True yapılmalı
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = 60*60*24  # 1 gün