# models/schemas.py - UPDATED for your MFLP project
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from enum import Enum

class Intent(str, Enum):
    CREATE_ISSUE = "create_issue"
    UPDATE_ISSUE = "update_issue"
    QUERY_ISSUE = "query_issue"
    SEARCH_ISSUES = "search_issues"
    HELP = "help"
    UNKNOWN = "unknown"

# UPDATED: Only include issue types available in your MFLP project
class IssueType(str, Enum):
    TASK = "Task"       
    STORY = "Story"     
    EPIC = "Epic"      

class Priority(str, Enum):
    LOWEST = "Lowest"
    LOW = "Low"
    MEDIUM = "Medium" 
    HIGH = "High"
    HIGHEST = "Highest"

class IssueStatus(str, Enum):
    TO_DO = "To Do"
    IN_PROGRESS = "In Progress"
    IN_REVIEW = "In Review"
    DONE = "Done"

class ExtractedIssueData(BaseModel):
    """Structured data extracted from user message"""
    issue_type: Optional[IssueType] = None
    priority: Optional[Priority] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    assignee: Optional[str] = None
    project_key: Optional[str] = None
    labels: List[str] = []
    issue_key: Optional[str] = None  # For updates/queries
    status: Optional[IssueStatus] = None
    due_date: Optional[str] = None      # YYYY-MM-DD
    start_date: Optional[str] = None    # YYYY-MM-DD
    parent_key: Optional[str] = None    # e.g., MFLP-3 for subtasks

class AgentResponse(BaseModel):
    """Standard response format from the agent"""
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    extracted_data: ExtractedIssueData
    missing_fields: List[str] = Field(default_factory=list)
    next_question: Optional[str] = None
    ready_for_jira: bool = False
    response_message: str
    error: Optional[str] = None

class ConversationState(BaseModel):
    """Track conversation state across turns"""
    user_phone: str
    current_intent: Optional[Intent] = None
    partial_issue_data: ExtractedIssueData = Field(default_factory=ExtractedIssueData)
    conversation_history: List[str] = Field(default_factory=list)
    awaiting_field: Optional[str] = None
    last_activity: Optional[str] = None