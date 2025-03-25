from flask import Flask, request, jsonify, session
from flask_cors import CORS
import os
from datetime import datetime, timezone
from mcp.server.fastmcp import FastMCP
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_community.chat_models.gigachat import GigaChat
from dataclasses import dataclass
from typing import List, Optional
from jira_ap import create_jira_issue
from atlassian import Confluence
from jira import JIRA

# Initialize Flask app
app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = os.urandom(24)
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True

# Initialize models and services
model = GigaChat(
    credentials='NDk1MzkxZDYtYjQyYy00NjRiLTlkOWItZGY4MGY3MWY1MTg2Ojc5ZTllNWNlLWFmY2QtNDgwOC1iZjIxLWMwYmUyZjk0YWFmZA==',
    scope="GIGACHAT_API_PERS",
    model="GigaChat",
    verify_ssl_certs=False,
)

# Configure LangGraph
workflow = StateGraph(state_schema=MessagesState)


def call_model(state: MessagesState):
    response = model.invoke(state["messages"])
    return {"messages": response}


workflow.add_edge(START, "model")
workflow.add_node("model", call_model)
memory = MemorySaver()
graph_app = workflow.compile(checkpointer=memory)
conversation_history = {}

# Initialize Jira and Confluence clients
confluence = Confluence(
    url="https://queerxdisasster.atlassian.net/wiki",
    username="7germania7@gmail.com",
    password="ATATT3xFfGF08nF1MUT2FYJTxEbAuBl8aajQ1FYyntXIo1xFGppoXriNoBJSZxz1FbQQ678LgQfArqI7vc8-spHSn-5NWZzCzdqEjo5utIDlK269XkkLIouQaAGA84v4rfYzoxpzOFuikU6XWnoeRnpZQwJnPeUR8hQRSQkXLkg2hYDCsDgloCI=A414B3DA"
)

jira_options = {'server': "https://queerxdisasster.atlassian.net"}
jira_client = JIRA(options=jira_options, basic_auth=("7germania7@gmail.com",
                                                     "ATATT3xFfGF08nF1MUT2FYJTxEbAuBl8aajQ1FYyntXIo1xFGppoXriNoBJSZxz1FbQQ678LgQfArqI7vc8-spHSn-5NWZzCzdqEjo5utIDlK269XkkLIouQaAGA84v4rfYzoxpzOFuikU6XWnoeRnpZQwJnPeUR8hQRSQkXLkg2hYDCsDgloCI=A414B3DA"))


# Helper classes and functions
@dataclass
class ChatResponse:
    message: str
    timestamp: float = datetime.now(timezone.utc).timestamp()


def generate_response(task: str, session_id: str) -> str:
    """Generate response using the model"""
    try:
        if session_id not in conversation_history:
            conversation_history[session_id] = []
            prompt_for_decompose = '''
            Ты эксперт по декомпозиции сложных задач в методологии Agile. Твоя задача - разбивать комплексные требования в виде {task} на атомарные пользовательские истории (user stories), оценивать их сложность в story points и предлагать оптимальные сроки выполнения.
            В первую очередь проанализируй запрос от пользователя, если он не указал планируемую дату завершения задачи ОБЯЗАТЕЛЬНО задай вопрос про это.
            Во-вторых, ты должен знать количество сотрудников, которые будут работать над этой задачей и их роли в команде, если пользователь не указал их, то ОБЯЗАТЕЛЬНО уточни этот момент
            не используя инструменты Marcdown, разбей минимум на 5 задач, по каждой задаче на отдельной строке жду описание, тип и название задачи'''

            conversation_history[session_id].append(SystemMessage(content=prompt_for_decompose))

        conversation_history[session_id].append(HumanMessage(content=task))
        output = graph_app.invoke(
            {"messages": conversation_history[session_id]},
            {"configurable": {"thread_id": session_id}}
        )
        ai_response = output["messages"][-1].content
        conversation_history[session_id] = output["messages"]

        # Process Jira tasks creation
        list_of_lines = ai_response.split('\n')
        tsk_names = [wrd.lstrip("- **Название задачи**: ") for wrd in list_of_lines if 'Название' in wrd]
        tsk_types = [wrd.lstrip("- **Тип задачи**: ") for wrd in list_of_lines if 'Тип' in wrd]
        tsk_desc = [wrd.lstrip("- **Описание задачи**: ") for wrd in list_of_lines if 'Описание' in wrd]

        for i in range(len(tsk_names) - 1):
            tsl = 'Task' if 'Task' in tsk_types[i] else 'Epic'
            jira_dict = {
                'project': {'key': 'KAN'},
                'summary': tsk_names[i],
                'description': tsk_desc[i],
                'issuetype': {'name': tsl},
            }
            create_jira_issue(jira_client, jira_dict)

        return ai_response
    except Exception as e:
        return f"Error generating response: {str(e)}"


# API Endpoints
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    if username and username.strip():
        session['username'] = username
        return jsonify({
            'success': True,
            'message': f'Welcome, {username}!'
        })
    return jsonify({'success': False, 'error': 'Invalid username'}), 400


@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return jsonify({'success': True})


@app.route('/api/send', methods=['POST'])
def send_message():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.json
    message = data.get('message')
    if not message or not message.strip():
        return jsonify({'error': 'Message cannot be empty'}), 400

    username = session['username']
    response_text = generate_response(message, username)

    return jsonify({
        'userMessage': {
            'username': username,
            'content': message,
            'timestamp': datetime.now().isoformat()
        },
        'botMessage': {
            'username': 'ChatBot',
            'content': response_text,
            'timestamp': datetime.now().isoformat()
        }
    })


@app.route('/api/session', methods=['GET'])
def check_session():
    if 'username' in session:
        return jsonify({
            'authenticated': True,
            'username': session['username']
        })
    return jsonify({'authenticated': False})


if __name__ == '__main__':
    app.run(debug=True, port=5000)