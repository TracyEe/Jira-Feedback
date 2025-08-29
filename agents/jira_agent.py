import json
import logging
import re
from datetime import datetime, date
from typing import Dict, Optional, List
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage, SystemMessage
from models.schemas import (
    AgentResponse, ConversationState, ExtractedIssueData, 
    Intent, IssueType, Priority, IssueStatus
)
from agents.prompts import SYSTEM_PROMPT, CONVERSATION_CONTEXT_PROMPT

logger = logging.getLogger(__name__)

# Enhanced menu choices with all Jira fields
CHOICE_MAPS = {
    "issue_type": ["Task", "Story", "Epic"],
    "priority": ["Highest", "High", "Medium", "Low", "Lowest"],
    "status": ["To Do", "In Progress", "In Review"],
}

# Field collection order for complete issue creation
FIELD_ORDER = [
    "issue_type",    # Work Type
    "priority",      # Priority  
    "status",        # Status
    "summary",       # Title/Summary
    "description",   # Description
    "assignee",      # Assignee (optional)
    "start_date",    # Start Date (optional)
    "due_date",      # Due Date (optional)
    "parent_key",    # Parent Issue (optional)
    "labels"         # Labels (auto-generated + manual)
]

def interpret_choice(field: str, text: str) -> str | None:
    """Interpret user choice for menu fields"""
    t = (text or "").strip().lower()
    
    # Handle numeric reply
    if t.isdigit():
        i = int(t) - 1
        opts = CHOICE_MAPS.get(field, [])
        if 0 <= i < len(opts):
            return opts[i]
    
    # Handle text reply
    for opt in CHOICE_MAPS.get(field, []):
        normalized = opt.lower().replace(" ", "").replace("-", "")
        if t in (opt.lower(), normalized):
            return opt
    
    return None

def validate_date(date_str: str) -> bool:
    """Validate date format YYYY-MM-DD"""
    if not date_str.strip():
        return True  # Empty is OK (optional field)
    
    try:
        datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return False

def validate_email(email: str) -> bool:
    """Basic email validation"""
    if not email.strip():
        return True  # Empty is OK (optional field)
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))

def generate_labels_from_description(description: str) -> List[str]:
    """Auto-generate labels from description text"""
    if not description:
        return []
    
    # Common tech keywords that make good labels
    tech_keywords = {
        # Programming/Tech
        'api', 'database', 'frontend', 'backend', 'mobile', 'web', 'server',
        'authentication', 'oauth', 'login', 'payment', 'gateway', 'security',
        'performance', 'bug', 'error', 'timeout', 'crash', 'fix',
        
        # Priority/Urgency
        'critical', 'urgent', 'important', 'high', 'medium', 'low',
        
        # Components
        'ui', 'ux', 'design', 'infrastructure', 'devops', 'testing',
        'deployment', 'monitoring', 'logging', 'backup', 'migration',
        
        # Business
        'user', 'customer', 'admin', 'report', 'analytics', 'dashboard',
        'checkout', 'cart', 'wishlist', 'profile', 'settings', 'notification'
    }
    
    # Extract keywords from description
    words = re.findall(r'\b\w+\b', description.lower())
    found_labels = []
    
    for word in words:
        if word in tech_keywords and word not in found_labels:
            found_labels.append(word)
    
    # Convert multi-word concepts
    desc_lower = description.lower()
    compound_keywords = {
        'two-factor': ['two', 'factor', 'authentication', '2fa'],
        'single-sign-on': ['single', 'sign', 'sso'],
        'real-time': ['real', 'time', 'realtime'],
        'third-party': ['third', 'party', 'external'],
        'end-to-end': ['end', 'to', 'end', 'e2e'],
    }
    
    for label, keywords in compound_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            if label not in found_labels:
                found_labels.append(label)
    
    return found_labels[:5]  # Limit to 5 labels

def to_enum(field: str, value: str):
    """Convert string value to appropriate enum"""
    if field == "status": 
        return IssueStatus(value)
    if field == "issue_type": 
        return IssueType(value)
    if field == "priority": 
        return Priority(value)
    return value

class JiraAgent:
    """Enhanced interactive Jira agent with complete field collection"""
    
    def __init__(self, google_api_key: str, model: str = "gemini-1.5-flash"):
        self.llm = ChatGoogleGenerativeAI(
            google_api_key=google_api_key,
            model=model,
            temperature=0.1,
        )
        self.conversation_states: Dict[str, ConversationState] = {}
        
    def process_direct_issue_creation(self, issue_data: ExtractedIssueData) -> AgentResponse:
        """Process issue creation directly without interactive collection"""
        try:
            # Validate required fields
            missing_fields = []
            if not issue_data.issue_type:
                missing_fields.append("issue_type")
            if not issue_data.priority:
                missing_fields.append("priority")
            if not issue_data.summary:
                missing_fields.append("summary")
            if not issue_data.description:
                missing_fields.append("description")
            
            if missing_fields:
                return AgentResponse(
                    intent=Intent.CREATE_ISSUE,
                    confidence=1.0,
                    extracted_data=issue_data,
                    missing_fields=missing_fields,
                    ready_for_jira=False,
                    response_message=f"Missing required fields: {', '.join(missing_fields)}",
                    error=f"Required fields missing: {', '.join(missing_fields)}"
                )
            
            # Auto-generate labels from description if not provided
            if not issue_data.labels and issue_data.description:
                issue_data.labels = generate_labels_from_description(issue_data.description)
            
            # Set default project key if not provided
            if not issue_data.project_key:
                issue_data.project_key = "TJ"
            
            return AgentResponse(
                intent=Intent.CREATE_ISSUE,
                confidence=1.0,
                extracted_data=issue_data,
                missing_fields=[],
                ready_for_jira=True,
                response_message="Issue data validated and ready for creation"
            )
            
        except Exception as e:
            logger.error(f"Error in direct issue creation processing: {str(e)}")
            return AgentResponse(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                extracted_data=ExtractedIssueData(),
                response_message="Error processing issue creation request",
                error=str(e)
            )
    
    def process_message(self, user_phone: str, message: str) -> AgentResponse:
        """Process user message with enhanced interactive field collection"""
        try:
            state = self.get_conversation_state(user_phone)
            partial = state.partial_issue_data
            
            # Handle interactive field collection
            awaiting = state.awaiting_field
            if awaiting:
                response = self._handle_field_input(state, message, awaiting)
                if response:
                    state.conversation_history.append(f"User: {message}")
                    state.conversation_history.append(f"Agent: {response.response_message}")
                    return response
            
            # Add message to history
            state.conversation_history.append(f"User: {message}")
            
            # Process with LLM for intent detection
            response = self._extract_intent_and_data(message, state)
            
            # Start interactive collection for create_issue
            if response.intent == Intent.CREATE_ISSUE and not response.ready_for_jira:
                response = self._start_interactive_collection(state)
            
            # Update conversation state
            self._update_conversation_state(state, response)
            
            # Add agent response to history
            state.conversation_history.append(f"Agent: {response.response_message}")
            return response
            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            return AgentResponse(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                extracted_data=ExtractedIssueData(),
                response_message="Sorry, I encountered an error. Please try again.",
                error=str(e)
            )
    # Add this method to your JiraAgent class in jira_agent.py

    def process_direct_issue_creation(self, issue_data: ExtractedIssueData) -> AgentResponse:
        """Process issue creation directly without interactive collection"""
        try:
            # Validate required fields
            missing_fields = []
            if not issue_data.issue_type:
                missing_fields.append("issue_type")
            if not issue_data.priority:
                missing_fields.append("priority")
            if not issue_data.summary:
                missing_fields.append("summary")
            if not issue_data.description:
                missing_fields.append("description")
            
            if missing_fields:
                return AgentResponse(
                    intent=Intent.CREATE_ISSUE,
                    confidence=1.0,
                    extracted_data=issue_data,
                    missing_fields=missing_fields,
                    ready_for_jira=False,
                    response_message=f"Missing required fields: {', '.join(missing_fields)}",
                    error=f"Required fields missing: {', '.join(missing_fields)}"
                )
            
            # Auto-generate labels from description if not provided
            if not issue_data.labels and issue_data.description:
                issue_data.labels = generate_labels_from_description(issue_data.description)
            
            # Set default project key if not provided
            if not issue_data.project_key:
                issue_data.project_key = "MFLP"
            
            return AgentResponse(
                intent=Intent.CREATE_ISSUE,
                confidence=1.0,
                extracted_data=issue_data,
                missing_fields=[],
                ready_for_jira=True,
                response_message="Issue data validated and ready for creation"
            )
            
        except Exception as e:
            logger.error(f"Error in direct issue creation processing: {str(e)}")
            return AgentResponse(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                extracted_data=ExtractedIssueData(),
                response_message="Error processing issue creation request",
                error=str(e)
            )
        
    def _handle_field_input(self, state: ConversationState, message: str, field: str) -> Optional[AgentResponse]:
        """Handle user input for a specific field"""
        partial = state.partial_issue_data
        user_input = message.strip()
        
        # Handle menu fields (issue_type, priority, status)
        if field in CHOICE_MAPS:
            choice = interpret_choice(field, user_input)
            if choice:
                setattr(partial, field, to_enum(field, choice))
                return self._get_next_field_prompt(state)
            else:
                return self._get_field_prompt(state, field, error="Invalid choice. Please try again.")
        
        # Handle text fields
        elif field == "summary":
            if user_input:
                if len(user_input) > 255:
                    return self._get_field_prompt(state, field, error=f"Summary too long ({len(user_input)} characters). Please keep it under 255 characters and provide a brief title.")
                partial.summary = user_input
                return self._get_next_field_prompt(state)
            else:
                return self._get_field_prompt(state, field, error="Summary cannot be empty. Please enter a title.")
        
        elif field == "description":
            if user_input.lower() in ["skip", "none", ""]:
                partial.description = None
            else:
                partial.description = user_input
                # Auto-generate labels from description
                auto_labels = generate_labels_from_description(user_input)
                if auto_labels:
                    partial.labels = auto_labels
            return self._get_next_field_prompt(state)
        
        elif field == "assignee":
            if user_input.lower() in ["skip", "none", ""]:
                partial.assignee = None
            elif validate_email(user_input):
                partial.assignee = user_input
            else:
                return self._get_field_prompt(state, field, error="Invalid email format. Please enter a valid email or 'skip'.")
            return self._get_next_field_prompt(state)
        
        elif field in ["start_date", "due_date"]:
            if user_input.lower() in ["skip", "none", ""]:
                setattr(partial, field, None)
            elif validate_date(user_input):
                setattr(partial, field, user_input)
            else:
                return self._get_field_prompt(state, field, error="Invalid date format. Please use YYYY-MM-DD or 'skip'.")
            return self._get_next_field_prompt(state)
        
        elif field == "parent_key":
            if user_input.lower() in ["skip", "none", ""]:
                partial.parent_key = None
            else:
                # Basic validation for issue key format
                if re.match(r'^[A-Z]+-\d+$', user_input.upper()):
                    partial.parent_key = user_input.upper()
                else:
                    return self._get_field_prompt(state, field, error="Invalid issue key format. Use format like TJ-123 or 'skip'.")
            return self._get_next_field_prompt(state)
        
        elif field == "labels":
            if user_input.lower() in ["skip", "none", ""]:
                # Keep auto-generated labels
                pass
            elif user_input.lower() == "clear":
                partial.labels = []
            else:
                # Add manual labels to auto-generated ones
                manual_labels = [l.strip().lower().replace(" ", "-") for l in user_input.split(",") if l.strip()]
                existing_labels = partial.labels or []
                partial.labels = list(set(existing_labels + manual_labels))
            return self._get_next_field_prompt(state)
        
        return None
    
    def _start_interactive_collection(self, state: ConversationState) -> AgentResponse:
        """Start interactive field collection process"""
        state.awaiting_field = FIELD_ORDER[0]  # Start with issue_type
        return self._get_field_prompt(state, state.awaiting_field)
    
    def _get_next_field_prompt(self, state: ConversationState) -> AgentResponse:
        """Get prompt for the next field in the collection process"""
        current_field = state.awaiting_field
        
        if current_field in FIELD_ORDER:
            current_index = FIELD_ORDER.index(current_field)
            if current_index + 1 < len(FIELD_ORDER):
                next_field = FIELD_ORDER[current_index + 1]
                state.awaiting_field = next_field
                return self._get_field_prompt(state, next_field)
        
        # All fields collected - ready to create issue
        state.awaiting_field = None
        return AgentResponse(
            intent=Intent.CREATE_ISSUE,
            confidence=1.0,
            extracted_data=state.partial_issue_data,
            ready_for_jira=True,
            response_message=f"Perfect! I have all the information needed. Creating your {state.partial_issue_data.issue_type} issue now..."
        )
    
    def _get_field_prompt(self, state: ConversationState, field: str, error: str = None) -> AgentResponse:
        """Get prompt for a specific field"""
        partial = state.partial_issue_data
        
        if error:
            error_msg = f"❌ {error}\n\n"
        else:
            error_msg = ""
        
        if field == "issue_type":
            options = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(CHOICE_MAPS[field])])
            message = f"{error_msg}🏷️ **Select Work Type:**\n{options}\n\nEnter number or name:"
        
        elif field == "priority":
            options = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(CHOICE_MAPS[field])])  
            message = f"{error_msg}⚡ **Select Priority:**\n{options}\n\nEnter number or name:"
        
        elif field == "status":
            options = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(CHOICE_MAPS[field])])
            message = f"{error_msg}🔄 **Select Status:**\n{options}\n\nEnter number or name:"
        
        elif field == "summary":
            message = f"{error_msg}📝 **Enter Issue Title/Summary:**\nProvide a brief, clear title for this issue:"
        
        elif field == "description":
            message = f"{error_msg}📋 **Enter Description:**\nProvide detailed information about this issue (or type 'skip'):"
        
        elif field == "assignee":
            message = f"{error_msg}👤 **Enter Assignee:**\nEnter email address to assign this issue (or type 'skip'):"
        
        elif field == "start_date":
            message = f"{error_msg}📅 **Enter Start Date:**\nFormat: YYYY-MM-DD (e.g., {date.today().strftime('%Y-%m-%d')}) or type 'skip':"
        
        elif field == "due_date":
            message = f"{error_msg}⏰ **Enter Due Date:**\nFormat: YYYY-MM-DD (e.g., {date.today().strftime('%Y-%m-%d')}) or type 'skip':"
        
        elif field == "parent_key":
            message = f"{error_msg}🔗 **Enter Parent Issue:**\nLink to parent issue (e.g., TJ-123) or type 'skip':"
        
        elif field == "labels":
            auto_labels = partial.labels or []
            if auto_labels:
                labels_str = ", ".join(auto_labels)
                message = f"{error_msg}🏷️ **Review Labels:**\nAuto-generated labels: **{labels_str}**\n\nAdd more labels (comma-separated), type 'clear' to remove all, or 'skip' to keep current:"
            else:
                message = f"{error_msg}🏷️ **Enter Labels:**\nAdd labels (comma-separated) or type 'skip':"
        
        else:
            message = f"{error_msg}Please provide information for {field}:"
        
        return AgentResponse(
            intent=Intent.CREATE_ISSUE,
            confidence=1.0,
            extracted_data=partial,
            missing_fields=[field],
            next_question=message,
            ready_for_jira=False,
            response_message=message
        )
    
    def get_conversation_state(self, user_phone: str) -> ConversationState:
        """Get or create conversation state for a user"""
        if user_phone not in self.conversation_states:
            self.conversation_states[user_phone] = ConversationState(
                user_phone=user_phone
            )
        return self.conversation_states[user_phone]
    
    def _extract_intent_and_data(self, message: str, state: ConversationState) -> AgentResponse:
        """Extract intent and structured data from user message using LLM"""
        system_prompt = SYSTEM_PROMPT
        
        if state.conversation_history:
            context_prompt = CONVERSATION_CONTEXT_PROMPT.format(
                conversation_history="\n".join(state.conversation_history[-5:]),
                partial_issue_data=state.partial_issue_data.model_dump_json(indent=2) if state.partial_issue_data else "{}",
                awaiting_field=state.awaiting_field or "nothing specific"
            )
            system_prompt += "\n\n" + context_prompt
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"User message: {message}")
        ]
        
        try:
            llm_response = self.llm.invoke(messages)
            response_text = llm_response.content.strip()
            
            # Extract JSON from response
            try:
                if "```json" in response_text:
                    start = response_text.find("```json") + 7
                    end = response_text.find("```", start)
                    if end != -1:
                        response_text = response_text[start:end].strip()
                elif "```" in response_text:
                    start = response_text.find("```") + 3
                    end = response_text.rfind("```")
                    if end != -1:
                        response_text = response_text[start:end].strip()
                
                response_data = json.loads(response_text)
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {response_text}")
                response_data = {
                    "intent": "unknown",
                    "confidence": 0.0,
                    "extracted_data": {},
                    "missing_fields": [],
                    "next_question": None,
                    "ready_for_jira": False,
                    "response_message": "I understand you want to work with Jira, but I need a clearer request. Try saying 'create an issue' or 'what's the status of TJ-123?'",
                    "error": f"JSON parsing error: {str(e)}"
                }
            
            agent_response = AgentResponse(**response_data)
            
            # Merge with existing partial data
            if state.current_intent and agent_response.intent == state.current_intent:
                agent_response.extracted_data = self._merge_issue_data(
                    state.partial_issue_data, 
                    agent_response.extracted_data
                )
            
            return agent_response
            
        except Exception as e:
            logger.error(f"LLM invocation error: {str(e)}")
            return AgentResponse(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                extracted_data=ExtractedIssueData(),
                response_message="I'm having trouble understanding that request. Try 'create an issue' or 'what's the status of TJ-123?'",
                error=f"LLM error: {str(e)}"
            )
    
    def _merge_issue_data(self, existing: ExtractedIssueData, new: ExtractedIssueData) -> ExtractedIssueData:
        """Merge new issue data with existing partial data"""
        merged_data = existing.model_copy()
        
        for field_name, new_value in new.model_dump().items():
            if new_value is not None:
                if field_name == "labels" and isinstance(new_value, list):
                    existing_labels = getattr(merged_data, field_name) or []
                    merged_data.labels = list(set(existing_labels + new_value))
                else:
                    setattr(merged_data, field_name, new_value)
        
        return merged_data
    
    def _update_conversation_state(self, state: ConversationState, response: AgentResponse):
        """Update conversation state based on agent response"""
        if response.intent != Intent.UNKNOWN:
            state.current_intent = response.intent
            state.partial_issue_data = response.extracted_data
        
        if response.missing_fields:
            state.awaiting_field = response.missing_fields[0]
        elif not response.ready_for_jira:
            # Keep current awaiting_field if still collecting
            pass
        else:
            state.awaiting_field = None
    # Add this method to your JiraAgent class in jira_agent.py

    
    def clear_conversation_state(self, user_phone: str):
        """Clear conversation state for a user"""
        if user_phone in self.conversation_states:
            del self.conversation_states[user_phone]