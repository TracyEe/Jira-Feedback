import os
import json
from dotenv import load_dotenv
from agents.jira_agent import JiraAgent
from services.jira_service import JiraService
from config.settings import settings # for FLASK_PORT / FLASK_DEBUG
from flask import Flask, request, jsonify  
from models.schemas import ExtractedIssueData

# Load environment - only need Gemini and Jira
load_dotenv()

class StandaloneJiraAgent:
    """Jira agent that works without WhatsApp"""
    
    def __init__(self):
        # Initialize both agent and Jira service
        print("🔧Initializing services...")
        self.agent = JiraAgent(google_api_key=settings.GOOGLE_API_KEY)
        self.jira_service = JiraService()
        
        settings.print_config_status()
        
        print("Jira Agent initialized (WhatsApp not required)")
    
    def process_text_command(self, message: str, user_phone: str = "console_user"):
        """Process any text command and perform Jira actions"""
        print(f"\nInput: {message}")
        print("Processing with AI...")

        # Keep the same user id across turns so conversation state works
        resp = self.agent.process_message(user_phone, message)

        # Pretty intent + confidence
        intent_str = getattr(resp.intent, "value", str(resp.intent))
        try:
            conf_str = f"{float(resp.confidence):.2f}"
        except Exception:
            conf_str = str(resp.confidence)

        print(f"Intent: {intent_str}")
        print(f"Confidence: {conf_str}")
        print(f"Response: {resp.response_message}")

        # Helpful during development
        try:
            print("[DBG] extracted_data:", resp.extracted_data.model_dump(exclude_none=True))
        except Exception:
            pass

        if resp.ready_for_jira:
            print("Executing Jira operation...")
            self.execute_jira_action(resp)
        else:
            # Show exactly what's missing + the numbered menu prompt (if any)
            if resp.missing_fields:
                print(f"Missing: {resp.missing_fields}")
            if resp.next_question:
                print(resp.next_question)  # e.g., "Choose a status: 1) To Do 2) In Progress 3) In Review 4) Done"
            else:
                print("Waiting for more information before creating Jira issue")

        return resp

    
    def execute_jira_action(self, response):
        """Execute the actual Jira operation with clear debug + safe intent parsing."""
        # Parse enum safely
        intent = getattr(response.intent, "value", str(response.intent)).lower()
        print(f"[DBG] intent={intent} ready={response.ready_for_jira}")

        # If the agent still needs info, stop early
        if not response.ready_for_jira:
            try:
                print(f"[DBG] missing_fields={response.missing_fields}")
            except Exception:
                pass
            print("[INFO] Waiting for more information before creating Jira issue")
            return

        # If user said "assign it to ..." during a create flow and no issue_key is present,
        # treat it as continuing the CREATE (not UPDATE).
        if intent == "update_issue" and not getattr(response.extracted_data, "issue_key", None):
            print("[INFO] No issue key provided; treating this as continuation of create flow")
            intent = "create_issue"

        # Show the structured fields we’re about to send
        try:
            print("[DBG] extracted_data=", response.extracted_data.model_dump(exclude_none=True))
        except Exception as e:
            print("[DBG] could not dump extracted_data:", e)

        try:
            if intent == "create_issue":
                print("[INFO] Creating Jira issue…")
                result = self.jira_service.create_issue(response.extracted_data)
                print("[RESULT]", result)

                if result.get("success"):
                    print(f"Created: {result['issue_key']}")
                    print(f"URL: {result['issue_url']}")
                else:
                    print(f"Failed: {result.get('message')}")

            elif intent == "update_issue":
                issue_key = response.extracted_data.issue_key
                print(f"[INFO] Updating issue {issue_key}…")
                result = self.jira_service.update_issue(issue_key, response.extracted_data)
                print("[RESULT]", result)

                if result.get("success"):
                    print(f"Updated: {issue_key}")
                else:
                    print(f"Failed: {result.get('message')}")

            elif intent == "query_issue":
                issue_key = response.extracted_data.issue_key
                print(f"[INFO] Querying issue {issue_key}…")
                result = self.jira_service.get_issue(issue_key)
                print("[RESULT]", result)

                if result.get("success"):
                    issue = result["issue"]
                    print(f"{issue['key']}: {issue['summary']}")
                    print(f"Status: {issue['status']}")
                    print(f"Assignee: {issue['assignee']}")
                    print(f"Priority: {issue['priority']}")
                    print(f"URL: {issue['url']}")
                else:
                    print(f"Failed: {result.get('message')}")

            elif intent == "search_issues":
                print("[INFO] Searching issues…")
                # Build simple JQL
                jql_parts = []
                if response.extracted_data.priority:
                    jql_parts.append(f'priority = "{response.extracted_data.priority}"')
                if response.extracted_data.issue_type:
                    jql_parts.append(f'issuetype = "{response.extracted_data.issue_type}"')
                if response.extracted_data.assignee and '@' in response.extracted_data.assignee:
                    jql_parts.append(f'assignee = "{response.extracted_data.assignee}"')
                if not jql_parts:
                    jql_parts.append('updated >= -7d')
                jql = ' AND '.join(jql_parts) + ' ORDER BY updated DESC'
                print("[DBG] JQL:", jql)

                result = self.jira_service.search_issues(jql, max_results=5)
                print("[RESULT]", result)

                if result.get("success"):
                    print(f"Found {len(result['issues'])} issues:")
                    for issue in result["issues"]:
                        print(f"  • {issue['key']}: {issue['summary'][:80]}...")
                else:
                    print(f"Search failed: {result.get('message')}")

            else:
                print(f"[WARN] Unhandled intent: {intent}")

        except Exception as e:
            import traceback
            print("[ERROR] Jira operation raised:", e)
            traceback.print_exc()


def interactive_mode():
    """Interactive console mode"""
    
    print("Jira AI Agent - Interactive Mode")
    print("=" * 50)
    print("Commands you can try:")
    print("• Create a critical bug for login issues in TJ assigned to tracy.ctee@gmail.com")
    print("• What's the status of TJ-123?")
    print("• Update TJ-456 to done")
    print("• Show me recent issues")
    print("• help")
    print("• quit")
    print("-" * 50)
    
    try:
        agent = StandaloneJiraAgent()
    except Exception as e:
        print(f"Failed to initialize agent: {str(e)}")
        return
    
    while True:
        try:
            user_input = input("\n Enter command: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            # Process the command
            agent.process_text_command(user_input)
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {str(e)}")

def batch_mode():
    """Process multiple commands at once"""
    
    print("Jira AI Agent - Batch Mode")
    print("=" * 50)
    
    # Sample commands to demonstrate
    commands = [
        "Create a high priority bug for database connection timeout in TJ assigned to tracy.ctee@gmail.com",
        "Make a task for updating API documentation in TJ assigned to tracy.ctee@gmail.com", 
        "What's the status of TJ-3?",
        "Create an epic for mobile app redesign in TJ assigned to tracy.ctee@gmail.com",
        "Show me critical priority issues"
    ]
    
    try:
        agent = StandaloneJiraAgent()
    except Exception as e:
        print(f"Failed to initialize agent: {str(e)}")
        return
    
    for i, command in enumerate(commands, 1):
        print(f"\nCommand {i}/{len(commands)}")
        agent.process_text_command(command)
        print("-" * 60)

def api_mode():
    """Simple REST API mode using Flask"""
    from flask import Flask, request, jsonify, send_from_directory
    from config.settings import settings
    from models.schemas import ExtractedIssueData

    app = Flask(__name__, static_folder="static")
    @app.route("/")
    def home():
        return send_from_directory(app.static_folder, "index.html")

    try:
        agent = StandaloneJiraAgent()
    except Exception as e:
        print(f"Failed to initialize agent: {str(e)}")
        return

    @app.route("/process", methods=["POST"])
    def process_command():
        """API endpoint to process Jira commands"""
        try:
            data = request.get_json(silent=True) or {}
            message = (data.get("message") or "").strip()
            user_phone = data.get("user_id", "api_user")  # keep stable per chat/session

            if not message:
                return jsonify({"error": "Message is required"}), 400

            # Process the command (returns AgentResponse)
            resp = agent.process_text_command(message, user_phone=user_phone)

            # Safely serialize extracted_data (pydantic model)
            try:
                extracted = resp.extracted_data.model_dump(exclude_none=True)
            except Exception:
                extracted = {}

            return jsonify({
                "intent": getattr(resp.intent, "value", str(resp.intent)),
                "confidence": resp.confidence,
                "response_message": resp.response_message,
                "ready_for_jira": resp.ready_for_jira,
                "missing_fields": resp.missing_fields,
                "next_question": resp.next_question,
                "extracted_data": extracted,
            }), 200

        except Exception as e:
            return jsonify({"error": str(e)}), 500
    # Add these routes to your standalone_jira_agent.py file in the api_mode() function

    @app.route("/create_issue", methods=["POST"])
    def create_issue_direct():
        """Direct endpoint to create Jira issues from form data"""
        try:
            data = request.get_json(silent=True) or {}
            
            # Import the label generation function
            from agents.jira_agent import generate_labels_from_description
            
            # Get description for auto-label generation
            description = data.get("description", "")
            manual_labels = data.get("labels", [])
            
            # Auto-generate labels from description
            auto_labels = generate_labels_from_description(description) if description else []
            
            # Combine manual and auto-generated labels, remove duplicates
            combined_labels = list(set(manual_labels + auto_labels))
            
            # Create ExtractedIssueData directly from form data
            extracted_data = ExtractedIssueData(
                issue_type=data.get("issue_type"),
                priority=data.get("priority"),
                summary=data.get("summary"),
                description=description,
                assignee=data.get("assignee"),
                status=data.get("status"),
                start_date=data.get("start_date"),
                due_date=data.get("due_date"),
                labels=combined_labels,  # Use combined labels instead
                parent_key=data.get("parent_key"),
                project_key=data.get("project_key", "TJ")
            )
            
            # Validate required fields
            if not extracted_data.issue_type:
                return jsonify({"success": False, "message": "Issue type is required"}), 400
            if not extracted_data.priority:
                return jsonify({"success": False, "message": "Priority is required"}), 400
            if not extracted_data.summary:
                return jsonify({"success": False, "message": "Summary is required"}), 400
            if not extracted_data.description:
                return jsonify({"success": False, "message": "Description is required"}), 400
            
            # Create the issue directly
            result = agent.jira_service.create_issue(extracted_data)
            
            # Add debug info about labels
            if combined_labels:
                print(f"[DEBUG] Auto-generated labels: {auto_labels}")
                print(f"[DEBUG] Manual labels: {manual_labels}")
                print(f"[DEBUG] Combined labels: {combined_labels}")
            
            return jsonify(result), 200 if result.get("success") else 400
            
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        
    @app.route("/debug/issue_types", methods=["GET"])
    def get_issue_types():
        """Debug endpoint to see available issue types"""
        try:
            if not agent.jira_service.jira:
                return jsonify({"error": "Running in mock mode"}), 400
            
            # Use a different method to get issue types
            try:
                # Method 1: Get create meta for the project
                create_meta = agent.jira_service.jira.get_create_meta(
                    project_keys=['TJ'], 
                    expand='projects.issuetypes'
                )
                
                issue_types = []
                if create_meta and 'projects' in create_meta:
                    for project in create_meta['projects']:
                        if project['key'] == 'TJ':
                            issue_types = [
                                {"name": it["name"], "id": it["id"]} 
                                for it in project.get('issuetypes', [])
                            ]
                            break
                
                return jsonify({
                    "method": "create_meta",
                    "available_issue_types": issue_types
                })
                
            except Exception as e1:
                # Method 2: Try getting all issue types
                try:
                    all_issue_types = agent.jira_service.jira.get_issue_types()
                    return jsonify({
                        "method": "all_issue_types", 
                        "available_issue_types": [
                            {"name": it["name"], "id": it["id"]} 
                            for it in all_issue_types
                        ]
                    })
                except Exception as e2:
                    return jsonify({
                        "error": f"Method 1 failed: {e1}, Method 2 failed: {e2}"
                    }), 500
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        
    @app.route("/add_comment/<issue_key>", methods=["POST"])
    def add_comment_direct(issue_key):
        try:
            data = request.get_json(silent=True) or {}
            comment_body = data.get("comment_body", "")
            
            if not comment_body:
                return jsonify({"success": False, "message": "Comment cannot be empty"}), 400
            
            # Call the service method correctly - it only takes 2 parameters
            result = agent.jira_service.add_comment(issue_key, comment_body)
            return jsonify(result), 200 if result.get("success") else 400
            
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/upload_attachment/<issue_key>", methods=["POST"])
    def upload_attachment(issue_key):
        try:
            print(f"[DEBUG] Upload route called for issue: {issue_key}")
            files = request.files.getlist("files")
            print(f"[DEBUG] Received {len(files)} files")
            
            if not files:
                print("[DEBUG] No files provided")
                return jsonify({"success": False, "error": "No files provided"}), 400
                
            results = []
            for i, file_obj in enumerate(files):
                print(f"[DEBUG] Processing file {i+1}: {file_obj.filename}")
                if file_obj.filename:  # Only process files with names
                    result = agent.jira_service.add_attachment(issue_key, file_obj)
                    print(f"[DEBUG] Attachment result: {result}")
                    results.append(result)
            
            final_response = {
                "success": True, 
                "results": results,
                "message": f"Processed {len(results)} files"
            }
            print(f"[DEBUG] Final response: {final_response}")
            return jsonify(final_response), 200
            
        except Exception as e:
            print(f"[ERROR] Upload failed: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/get_issue/<issue_key>", methods=["GET"])
    def get_issue_direct(issue_key):
        """Direct endpoint to get issue details"""
        try:
            result = agent.jira_service.get_issue(issue_key)
            return jsonify(result), 200 if result.get("success") else 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/update_issue/<issue_key>", methods=["PUT"])
    def update_issue_direct(issue_key):
        """Direct endpoint to update issue"""
        try:
            data = request.get_json(silent=True) or {}
            
            # Create ExtractedIssueData for update
            extracted_data = ExtractedIssueData(
                status=data.get("status"),
                assignee=data.get("assignee"),
                priority=data.get("priority"),
                summary=data.get("summary"),
                description=data.get("description"),
                issue_key=issue_key
            )
            
            result = agent.jira_service.update_issue(issue_key, extracted_data)
            return jsonify(result), 200 if result.get("success") else 400
            
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/search_issues", methods=["POST"])
    def search_issues_direct():
        """Direct endpoint to search issues"""
        try:
            data = request.get_json(silent=True) or {}
            jql = data.get("jql", "updated >= -7d ORDER BY updated DESC")
            max_results = data.get("max_results", 10)
            
            result = agent.jira_service.search_issues(jql, max_results)
            return jsonify(result), 200 if result.get("success") else 400
            
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        
    @app.route("/debug/project_issue_types", methods=["GET"])
    def get_project_issue_types():
        """Get issue types specifically for TJ project"""
        try:
            if not agent.jira_service.jira:
                return jsonify({"error": "Running in mock mode"}), 400
            
            # Method 1: Try project-specific create meta
            try:
                create_meta = agent.jira_service.jira.get_create_meta(
                    project_keys=['TJ'], 
                    expand='projects.issuetypes.fields'
                )
                
                if create_meta and 'projects' in create_meta:
                    for project in create_meta['projects']:
                        if project['key'] == 'TJ':
                            issue_types = [
                                {"name": it["name"], "id": it["id"]} 
                                for it in project.get('issuetypes', [])
                            ]
                            return jsonify({
                                "method": "project_create_meta",
                                "project": "TJ",
                                "available_issue_types": issue_types
                            })
            
            except Exception as e1:
                print(f"Create meta failed: {e1}")
                
            # Method 2: Try getting project info directly
            try:
                project = agent.jira_service.jira.project("TJ")
                return jsonify({
                    "method": "project_info",
                    "project": project,
                    "note": "Check project.issueTypes if available"
                })
            except Exception as e2:
                return jsonify({"error": f"All methods failed: {e1}, {e2}"}), 500
                
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Add CORS support for frontend
    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        return response

    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "healthy", "whatsapp_required": False}), 200

    print(f"Starting Jira Agent API (no WhatsApp required) on :{settings.FLASK_PORT}")
    print('Endpoint: POST /process  payload: {"message":"Create a task ..."}')

    app.run(host="0.0.0.0", port=settings.FLASK_PORT, debug=False, use_reloader=False)
    
    
if __name__ == "__main__":
    print("Choose mode:")
    print("1. Interactive mode (type commands)")
    print("2. Batch mode (run sample commands)")  
    print("3. API mode (REST endpoint)")
    
    choice = input("Enter choice (1, 2, or 3): ").strip()
    
    if choice == "1":
        interactive_mode()
    elif choice == "2":
        batch_mode()
    elif choice == "3":
        api_mode()
    else:
        print("Invalid choice, starting interactive mode...")
        interactive_mode()