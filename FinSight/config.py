import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "finsight-super-secret-key-1324!#$")
    # Store database in the instance folder or root
    SQLALCHEMY_DATABASE_URI = "sqlite:///database.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload Folder Settings
    UPLOAD_FOLDER = os.path.join("static", "uploads")
    RECEIPT_FOLDER = os.path.join(UPLOAD_FOLDER, "receipts")
    PROFILE_FOLDER = os.path.join(UPLOAD_FOLDER, "profiles")
    BACKUP_FOLDER = os.path.join("instance", "backups")
    
    # 5 MB maximum size
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}
