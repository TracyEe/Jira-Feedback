import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Settings:
    """Application configuration"""
    
    # Google Gemini Configuration - Using your specific variable names
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY_2") 
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    
    # LangSmith Configuration - Using your specific variable names
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY_2")  
    LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "whatsapp-jira-agent")
    LANGSMITH_TRACING = (os.getenv("LANGSMITH_TRACING", "false").lower() == "true") and bool(os.getenv("LANGSMITH_API_KEY_2"))
    
    # Jira Configuration (keep these the same)
    JIRA_URL = os.getenv("JIRA_URL")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL")
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
    JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "TEST")
    JIRA_START_DATE_FIELD_ID = os.getenv("JIRA_START_DATE_FIELD_ID")
    
    # Flask Configuration
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
    
    @classmethod
    def validate_required_settings(cls):
        """Validate that required settings are present"""
        required_settings = [
            "GOOGLE_API_KEY",  # Will check GOOGLE_API_KEY_1
        ]
        
        missing = []
        for setting in required_settings:
            if not getattr(cls, setting):
                missing.append(setting)
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    @classmethod
    def print_config_status(cls):
        """Print configuration status for debugging"""
        print(" Configuration Status:")
        print(f"   Google API Key: {'Set' if cls.GOOGLE_API_KEY else 'Missing'}")
        print(f"   LangSmith API Key: {'Set' if cls.LANGSMITH_API_KEY else 'Missing'}")
        print(f"   LangSmith Tracing: {'Enabled' if cls.LANGSMITH_TRACING else 'Disabled'}")
        print(f"   Jira URL: {'Set' if cls.JIRA_URL else 'Missing'}")
        print(f"   Jira API Token: {'Set' if cls.JIRA_API_TOKEN else 'Missing'}")

# Create settings instance
settings = Settings()

{
  "python.defaultInterpreterPath": ".venv\\Scripts\\python.exe"
}
