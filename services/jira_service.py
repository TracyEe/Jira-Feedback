import logging
from typing import Dict, Optional, List
from atlassian import Jira
from models.schemas import ExtractedIssueData, IssueType, Priority, IssueStatus
from config.settings import settings

logger = logging.getLogger(__name__)

class JiraService:
    """Service for interacting with Jira API"""
    
    def __init__(self):
        if not all([settings.JIRA_URL, settings.JIRA_EMAIL, settings.JIRA_API_TOKEN]):
            logger.warning("Jira credentials not configured - running in mock mode")
            self.jira = None
            print("JiraService: MOCK mode (no issues will be created)")
        else:
            self.jira = Jira(
                url=settings.JIRA_URL,
                username=settings.JIRA_EMAIL,
                password=settings.JIRA_API_TOKEN
            )
            print("JiraService: REAL mode (will create issues on your cloud site)")
            
    def _enum_value(self, x, default=None):
        """Return Enum.value if x is an Enum, else x (with optional default)."""
        if x is None:
            x = default
        return getattr(x, "value", x)
    
    def create_issue(self, issue_data: ExtractedIssueData, project_key: str = None) -> Dict:
        """Create a new Jira issue"""
        
        import json
        try:
            if not self.jira:
                print("[MOCK] create_issue called")
                return self._mock_create_issue(issue_data, project_key)

            project_key = project_key or issue_data.project_key or settings.JIRA_PROJECT_KEY

            # Convert enums -> plain strings Jira expects
            issuetype_name = self._enum_value(issue_data.issue_type, IssueType.TASK)
            priority_name = self._enum_value(issue_data.priority)
            status_name = self._enum_value(issue_data.status)

            # Map issue type names to specific IDs (use the lower IDs as primary)
            issue_type_mapping = {
                "Task": "10003",
                "Story": "10004", 
                "Epic": "10000"
            }
            
            issue_type_id = issue_type_mapping.get(issuetype_name)
            if not issue_type_id:
                issue_type_id = "10003"  # Default to Task
                print(f"[WARN] Unknown issue type '{issuetype_name}', defaulting to Task")

            fields = {
                "project": {"key": project_key},
                "summary": issue_data.summary or "Issue created via AI Agent",
                "issuetype": {"id": issue_type_id},  # Use ID instead of name
            }
            
            if issue_data.description:
                fields["description"] = issue_data.description
            if priority_name and issuetype_name == "Task":
                # Only set priority for Task type, skip for Story/Epic
                fields["priority"] = {"name": priority_name}
                print(f"[DEBUG] Setting priority for Task: {priority_name}")
            else:
                print(f"[DEBUG] Skipping priority for issue type: {issuetype_name}")
            if issue_data.labels:
                fields["labels"] = [lbl.strip().lower().replace(" ", "-") for lbl in issue_data.labels if lbl]

            # Jira built-in due date
            if issue_data.due_date:
                fields["duedate"] = issue_data.due_date
            if settings.JIRA_START_DATE_FIELD_ID and issue_data.start_date:
                fields[settings.JIRA_START_DATE_FIELD_ID] = issue_data.start_date

            # Parent (only valid for Sub-task issue type)
            if getattr(issue_data, "parent_key", None) and issuetype_name.lower() in ("sub-task", "subtask"):
                fields["parent"] = {"key": issue_data.parent_key}

            # Assignee (resolve to accountId; continue if not found)
            if issue_data.assignee:
                assignee = self._find_user(issue_data.assignee)
                if assignee:
                    fields["assignee"] = {"accountId": assignee["accountId"]}
                else:
                    print(f"[WARN] Assignee not found: {issue_data.assignee} (continuing without assignee)")

            print(f"[DEBUG] Issue type being sent: '{issuetype_name}' -> ID: {issue_type_id}")
            print(f"[DEBUG] Full fields being sent: {json.dumps(fields, indent=2)}")
            
            print("[DBG] Creating Jira issue with fields:", fields)
            new_issue = self.jira.issue_create(fields=fields)

            # Extract key
            if isinstance(new_issue, dict):
                issue_key = new_issue.get("key")
            elif hasattr(new_issue, "key"):
                issue_key = new_issue.key
            else:
                issue_key = str(new_issue)

            print(f"Created issue {issue_key}")

            # Optional: transition right after create
            if status_name:
                ok = self._transition_issue(issue_key, status_name)
                if not ok:
                    print(f"[WARN] Could not transition {issue_key} to {status_name}")

            return {
                "success": True,
                "issue_key": issue_key,
                "issue_url": f"{settings.JIRA_URL.rstrip('/')}/browse/{issue_key}",
                "message": f"Successfully created {issuetype_name or 'issue'} {issue_key}",
            }

        except Exception as e:
            import traceback
            print("Jira create failed:", repr(e))
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to create issue: {e}",
            }

        
    def get_issue(self, issue_key: str) -> Dict:
        """Get information about a Jira issue"""
        try:
            if not self.jira:
                return self._mock_get_issue(issue_key)
            
            # Use correct method for atlassian-python-api
            issue = self.jira.issue(issue_key)
            
            return {
                'success': True,
                'issue': {
                    'key': issue['key'],
                    'summary': issue['fields']['summary'],
                    'status': issue['fields']['status']['name'],
                    'priority': issue['fields']['priority']['name'] if issue['fields'].get('priority') else 'None',
                    'assignee': issue['fields']['assignee']['displayName'] if issue['fields'].get('assignee') else 'Unassigned',
                    'issue_type': issue['fields']['issuetype']['name'],
                    'created': issue['fields']['created'],
                    'updated': issue['fields']['updated'],
                    'description': issue['fields'].get('description') or 'No description',
                    'url': f"{settings.JIRA_URL}/browse/{issue['key']}"
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting Jira issue {issue_key}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'message': f"Could not find issue {issue_key}"
            }
    
    def update_issue(self, issue_key: str, update_data: ExtractedIssueData) -> Dict:
        """Update an existing Jira issue"""
        try:
            if not self.jira:
                return self._mock_update_issue(issue_key, update_data)

            # Convert enums -> plain strings Jira expects
            issuetype_name = self._enum_value(getattr(update_data, "issue_type", None))   # optional
            priority_name  = self._enum_value(getattr(update_data, "priority", None))
            status_name    = self._enum_value(getattr(update_data, "status", None))

            # Build ONE fields dict (merge everything here)
            fields = {}

            if update_data.summary:
                fields["summary"] = update_data.summary

            if update_data.description:
                fields["description"] = update_data.description

            if priority_name:
                fields["priority"] = {"name": priority_name}

            # Optional: allow changing issue type
            if issuetype_name:
                fields["issuetype"] = {"name": issuetype_name}

            # Dates
            if update_data.due_date:
                fields["duedate"] = update_data.due_date  # YYYY-MM-DD

            if getattr(settings, "JIRA_START_DATE_FIELD_ID", None) and update_data.start_date:
                fields[settings.JIRA_START_DATE_FIELD_ID] = update_data.start_date

            # Labels
            if update_data.labels:
                fields["labels"] = [lbl.strip().lower().replace(" ", "-") for lbl in update_data.labels if lbl]

            # Parent: only valid for Sub-task
            if getattr(update_data, "parent_key", None) and (issuetype_name or "").lower() in ("sub-task", "subtask"):
                fields["parent"] = {"key": update_data.parent_key}

            # Assignee (resolve to accountId; continue if not found)
            if update_data.assignee:
                assignee = self._find_user(update_data.assignee)
                if assignee:
                    fields["assignee"] = {"accountId": assignee["accountId"]}
                else:
                    print(f"[WARN] Assignee not found: {update_data.assignee} (continuing without changing assignee)")

            # --- Apply field updates
            if fields:
                print("[DBG] Updating Jira issue with fields:", fields)
                self.jira.issue_update(issue_key, fields)
            else:
                print("[DBG] No field changes to apply")

            # --- Handle status transition after field updates
            if status_name:
                try:
                    transitions = self.jira.get_issue_transitions(issue_key)
                    target = status_name.lower()
                    for t in transitions.get("transitions", []):
                        if t["to"]["name"].lower() == target:
                            self.jira.issue_transition(issue_key, t["id"])
                            print(f"✅ Transitioned {issue_key} to {status_name}")
                            break
                    else:
                        print(f"[WARN] No transition found that leads to status '{status_name}'. "
                            f"Available: {[tr['to']['name'] for tr in transitions.get('transitions', [])]}")
                except Exception as e:
                    print(f"[WARN] Could not transition issue {issue_key} to {status_name}: {e}")

            return {
                "success": True,
                "issue_key": issue_key,
                "message": f"Successfully updated issue {issue_key}"
            }

        except Exception as e:
            import traceback
            print(f"❌ Error updating Jira issue {issue_key}:", repr(e))
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to update issue {issue_key}: {e}"
            }

    
    def search_issues(self, jql: str, max_results: int = 10) -> Dict:
        """Search for Jira issues using JQL"""
        try:
            if not self.jira:
                return self._mock_search_issues(jql, max_results)
            
            # Use correct method for atlassian-python-api
            results = self.jira.jql(jql, limit=max_results)
            
            issues = []
            for issue in results.get('issues', []):
                issues.append({
                    'key': issue['key'],
                    'summary': issue['fields']['summary'],
                    'status': issue['fields']['status']['name'],
                    'priority': issue['fields']['priority']['name'] if issue['fields'].get('priority') else 'None',
                    'assignee': issue['fields']['assignee']['displayName'] if issue['fields'].get('assignee') else 'Unassigned',
                    'url': f"{settings.JIRA_URL}/browse/{issue['key']}"
                })
            
            return {
                'success': True,
                'total': results.get('total', 0),
                'issues': issues,
                'message': f"Found {len(issues)} issues"
            }
            
        except Exception as e:
            logger.error(f"Error searching Jira issues: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'message': f"Search failed: {str(e)}"
            }
    
    def get_user_issues(self, user_email: str, status: str = None) -> Dict:
        """Get issues assigned to a specific user"""
        
        jql = f'assignee = "{user_email}"'
        if status:
            jql += f' AND status = "{status}"'
        jql += ' ORDER BY updated DESC'
        
        return self.search_issues(jql)
    
    def _find_user(self, user_identifier: str) -> Optional[Dict]:
        """Find a Jira user by email or display name"""
        try:
            if not self.jira:
                return None
            
            # For TJ project, try different user search methods
            # Method 1: Search by email
            if '@' in user_identifier:
                try:
                    # Try direct user search
                    users = self.jira.search_users(user_identifier)
                    if users:
                        return users[0]
                except:
                    pass
            
            # Method 2: Get assignable users for the project
            try:
                assignable_users = self.jira.search_assignable_users_for_projects(
                    user_identifier, 
                    project_keys=[settings.JIRA_PROJECT_KEY]
                )
                if assignable_users:
                    for user in assignable_users:
                        if (user_identifier.lower() in user.get('emailAddress', '').lower() or 
                            user_identifier.lower() in user.get('displayName', '').lower()):
                            return user
            except:
                pass
            
            # Method 3: If user not found, log it but don't fail
            logger.warning(f"Could not find user '{user_identifier}' in Jira")
            return None
            
        except Exception as e:
            logger.error(f"Error finding user {user_identifier}: {str(e)}")
            return None
    
    def _transition_issue(self, issue_key: str, target_status: str) -> bool:
        """Transition issue to the target status using direct API calls."""
        target = (target_status or "").strip().lower()

        try:
            # Get transitions directly
            raw = self.jira.get_issue_transitions(issue_key)
            
            # Normalize to a list of transition dicts
            if isinstance(raw, dict):
                items = raw.get("transitions") or raw.get("values") or []
            elif isinstance(raw, list):
                items = raw
            else:
                items = []

            # Find the correct transition ID
            transition_id = None
            for t in items:
                # Handle both string and dict formats for 'to' field
                to_field = t.get("to")
                if isinstance(to_field, dict):
                    to_name = (to_field.get("name") or "").strip().lower()
                elif isinstance(to_field, str):
                    to_name = to_field.strip().lower()
                else:
                    to_name = ""
                    
                if to_name == target:
                    transition_id = t.get("id")
                    break

            if transition_id is None:
                print(f"[WARN] No transition found that leads to '{target_status}'.")
                return False

            # Use direct POST API call instead of the buggy library method
            url = f"rest/api/2/issue/{issue_key}/transitions"
            data = {
                "transition": {
                    "id": str(transition_id)  # Ensure it's a string
                }
            }
            
            response = self.jira.post(url, data=data)
            print(f"Transitioned {issue_key} to {target_status}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to transition {issue_key} to {target_status}: {e}")
            return False

    def add_attachment(self, issue_key: str, file_obj) -> Dict:
        """Add an attachment to a Jira issue"""
        try:
            print(f"[DEBUG] add_attachment called for {issue_key}, file: {getattr(file_obj, 'filename', 'unknown')}")
            
            if not self.jira:
                print("[DEBUG] Running in mock mode")
                return {
                    'success': True, 
                    'message': f"Mock: Added attachment to {issue_key}",
                    'filename': getattr(file_obj, 'filename', 'mock_file.txt')
                }
            
            print("[DEBUG] Calling Jira API to upload attachment using POST method")
            
            # Use direct POST method if add_attachment doesn't exist
            files = {'file': (file_obj.filename, file_obj.read(), file_obj.content_type)}
            result = self.jira.post(f"rest/api/2/issue/{issue_key}/attachments", files=files, headers={'X-Atlassian-Token': 'no-check'})
            print(f"[DEBUG] Jira API response: {result}")
            
            return {
                'success': True, 
                'message': f"Attachment uploaded to {issue_key}",
                'filename': getattr(file_obj, 'filename', 'uploaded_file'),
                'result': result
            }
            
        except Exception as e:
            print(f"[ERROR] add_attachment failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False, 
                'error': str(e), 
                'message': f"Failed to upload attachment: {str(e)}",
                'filename': getattr(file_obj, 'filename', 'unknown')
            }
        
    def add_comment(self, issue_key: str, comment_text: str) -> Dict:
        """Add a comment to a Jira issue"""
        try:
            if not self.jira:
                return {'success': True, 'message': f"Mock: Added comment to {issue_key}"}

            # Build ADF document from plain text
            payload = {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": comment_text}]
                        }
                    ]
                }
            }

            result = self.jira.post(f"rest/api/3/issue/{issue_key}/comment", data=payload)
            return {"success": True, "message": f"Added comment to {issue_key}"}

        except Exception as e:
            return {"success": False, "error": str(e), "message": f"Failed to add comment: {str(e)}"}
    
    # Mock methods for testing without Jira connection
    def _mock_create_issue(self, issue_data: ExtractedIssueData, project_key: str) -> Dict:
        """Mock issue creation for testing"""
        mock_key = f"{project_key or 'TJ'}-{hash(issue_data.summary or 'mock') % 1000}"
        return {
            'success': True,
            'issue_key': mock_key,
            'issue_url': f"https://mock-jira.com/browse/{mock_key}",
            'message': f"Mock: Created {issue_data.issue_type or 'issue'} {mock_key}"
        }
    
    def _mock_update_issue(self, issue_key: str, update_data: ExtractedIssueData) -> Dict:
        """Mock issue update for testing"""
        return {
            'success': True,
            'issue_key': issue_key,
            'message': f"Mock: Updated issue {issue_key}"
        }
    
    def _mock_get_issue(self, issue_key: str) -> Dict:
        """Mock issue retrieval for testing"""
        return {
            'success': True,
            'issue': {
                'key': issue_key,
                'summary': 'Mock Issue Summary',
                'status': 'To Do',
                'priority': 'Medium',
                'assignee': 'Mock User',
                'issue_type': 'Task',  # Changed from Bug to Task
                'created': '2024-01-01T00:00:00.000+0000',
                'updated': '2024-01-01T00:00:00.000+0000',
                'description': 'This is a mock issue for testing',
                'url': f"https://mock-jira.com/browse/{issue_key}"
            }
        }
    
    def _mock_search_issues(self, jql: str, max_results: int) -> Dict:
        """Mock issue search for testing"""
        return {
            'success': True,
            'total': 2,
            'issues': [
                {
                    'key': 'TJ-123',
                    'summary': 'Mock Task 1',
                    'status': 'In Progress',
                    'priority': 'High',
                    'assignee': 'Mock User',
                    'url': 'https://mock-jira.com/browse/TJ-123'
                },
                {
                    'key': 'TJ-124',
                    'summary': 'Mock Story 2',
                    'status': 'To Do',
                    'priority': 'Medium',
                    'assignee': 'Unassigned',
                    'url': 'https://mock-jira.com/browse/TJ-124'
                }
            ],
            'message': "Found 2 mock issues"
        }