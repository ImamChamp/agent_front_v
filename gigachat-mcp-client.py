from flask import Flask, render_template, request, redirect, url_for, session
import os
from datetime import datetime
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route
from mcp.server.fastmcp import FastMCP
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_community.chat_models.gigachat import GigaChat
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timezone
from jira_ap import create_jira_issue, get_page_content, extract_page_id, fetch_confluence_context
from atlassian import Confluence
from jira import JIRA

model = GigaChat(
    credentials='NDk1MzkxZDYtYjQyYy00NjRiLTlkOWItZGY4MGY3MWY1MTg2Ojc5ZTllNWNlLWFmY2QtNDgwOC1iZjIxLWMwYmUyZjk0YWFmZA==',
    scope="GIGACHAT_API_PERS",
    model="GigaChat",
    verify_ssl_certs=False,
)

mcp = FastMCP(
    "gigachat",
    dependencies=[
        "langchain-community",
        "langchain-core",
        "langgraph",
        'jira'
    ],
)

# Configure LangChain
parser = StrOutputParser()

# Configure LangGraph
workflow = StateGraph(state_schema=MessagesState)
app = Flask(__name__)
app.secret_key = os.urandom(24)


def call_model(state: MessagesState):
    response = model.invoke(state["messages"])
    return {"messages": response}


# Хранилище сообщений
messages = []
workflow.add_edge(START, "model")
workflow.add_node("model", call_model)

# Add memory
memory = MemorySaver()
graph_app = workflow.compile(checkpointer=memory)
config = {"configurable": {"thread_id": "abc123"}}
conversation_history = {}

prompt_for_decompose = '''
Ты эксперт по декомпозиции сложных задач в методологии Agile. Твоя задача - разбивать комплексные требования в виде {task} на атомарные пользовательские истории (user stories), оценивать их сложность в story points и предлагать оптимальные сроки выполнения.
В первую очередь проанализируй запрос от пользователя, если он не указал планируемую дату завершения задачи ОБЯЗАТЕЛЬНО задай вопрос про это.
Во-вторых, ты должен знать количество сотрудников, которые будут работать над этой задачей и их роли в команде, если пользователь не указал их, то ОБЯЗАТЕЛЬНО уточни этот момент
не используя инструменты Marcdown, разбей минимум на 5 задач, по каждой задаче на отдельной строке жду описание, тип и название задачи'''

CONFLUENCE_URL = "https://queerxdisasster.atlassian.net/wiki"
CONFLUENCE_USERNAME = "7germania7@gmail.com"
CONFLUENCE_API_TOKEN = "ATATT3xFfGF08nF1MUT2FYJTxEbAuBl8aajQ1FYyntXIo1xFGppoXriNoBJSZxz1FbQQ678LgQfArqI7vc8-spHSn-5NWZzCzdqEjo5utIDlK269XkkLIouQaAGA84v4rfYzoxpzOFuikU6XWnoeRnpZQwJnPeUR8hQRSQkXLkg2hYDCsDgloCI=A414B3DA"

JIRA_SERVER = "https://queerxdisasster.atlassian.net"
JIRA_EMAIL = "7germania7@gmail.com"
JIRA_API_TOKEN = "ATATT3xFfGF08nF1MUT2FYJTxEbAuBl8aajQ1FYyntXIo1xFGppoXriNoBJSZxz1FbQQ678LgQfArqI7vc8-spHSn-5NWZzCzdqEjo5utIDlK269XkkLIouQaAGA84v4rfYzoxpzOFuikU6XWnoeRnpZQwJnPeUR8hQRSQkXLkg2hYDCsDgloCI=A414B3DA"

# Инициализация клиента Confluence
confluence = Confluence(
    url=CONFLUENCE_URL,
    username=CONFLUENCE_USERNAME,
    password=CONFLUENCE_API_TOKEN
)

# Инициализация клиента Jira
jira_options = {'server': JIRA_SERVER}
jira_client = JIRA(options=jira_options, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))


@dataclass
class ChatResponse:
    message: str
    timestamp: float = datetime.now(timezone.utc).timestamp()


def generate_response(task: str, session_id: str = "default") -> str:
    """Генерирует ответ на сообщение пользователя с помощью модели"""
    try:
        if session_id not in conversation_history:
            conversation_history[session_id] = []
            if prompt_for_decompose:
                conversation_history[session_id].append(
                    SystemMessage(content=prompt_for_decompose)
                )

        # Add user message to history
        conversation_history[session_id].append(HumanMessage(content=task))

        # Use LangGraph for processing
        input_messages = conversation_history[session_id]
        config = {"configurable": {"thread_id": session_id}}
        output = graph_app.invoke({"messages": input_messages}, config)
        ai_response = output["messages"][-1].content
        conversation_history[session_id] = output["messages"]
        response = ChatResponse(message=ai_response)
        list_of_lines = response.message.split('\n')
        tsk_names = [wrd.lstrip("- **Название задачи**: ") for wrd in list_of_lines if 'Название' in wrd]
        tsk_types = [wrd.lstrip("- **Тип задачи**: ") for wrd in list_of_lines if 'Тип' in wrd]
        tsk_desc = [wrd.lstrip("- **Описание задачи**: ") for wrd in list_of_lines if 'Описание' in wrd]
        user_stories = []
        for i in range(len(tsk_names) - 1):
            if 'Task' in tsk_types[i]:
                tsl = 'Task'
            else:
                tsl = 'Epic'
            print(tsl)
            jira_dict = {
                'project': {'key': 'KAN'},  # ключ проекта в Jira
                'summary': tsk_names[i],
                'description': tsk_desc[i],
                'issuetype': {'name': tsl},
            }
            user_stories.append(jira_dict)
        for us in user_stories:
            issue_key = create_jira_issue(jira_client, us)
            print(f"Создана задача: {issue_key}")

        return ai_response
    except Exception as e:
        return f"Произошла ошибка при генерации ответа: {str(e)}"


@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('chat.html', messages=messages)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        if username.strip():
            session['username'] = username
            timestamp = datetime.now().strftime('%H:%M:%S')
            messages.append({
                'username': 'Чат-бот',
                'content': f'Добро пожаловать в чат, {username}! Я помогу вам с декомпозицией задач.',
                'timestamp': timestamp
            })
            return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))


@app.route('/send', methods=['POST'])
def send():
    if 'username' in session:
        message = request.form['message']
        if message.strip():
            timestamp = datetime.now().strftime('%H:%M:%S')
            username = session['username']

            # Добавляем сообщение пользователя
            messages.append({
                'username': username,
                'content': message,
                'timestamp': timestamp
            })

            # Генерируем и добавляем ответ бота сразу
            response_text = generate_response(message, session['username'])
            timestamp = datetime.now().strftime('%H:%M:%S')
            messages.append({
                'username': 'Чат-бот',
                'content': response_text,
                'timestamp': timestamp
            })

    return redirect(url_for('index'))


# Создаем папку templates, если она не существует
if not os.path.exists('templates'):
    os.makedirs('templates')

# Создаем HTML-шаблоны (они остаются такими же, как у вас)
with open('templates/login.html', 'w', encoding='utf-8') as f:
    f.write('''
<!DOCTYPE html>
<html>
<head>
    <title>Вход в чат</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background-color: #f5f5f5;
        }
        .login-form {
            background-color: white;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
            width: 300px;
        }
        h1 {
            text-align: center;
            color: #333;
        }
        input[type="text"] {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 3px;
            box-sizing: border-box;
        }
        button {
            width: 100%;
            padding: 10px;
            background-color: #4CAF50;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
        }
        button:hover {
            background-color: #45a049;
        }
    </style>
</head>
<body>
    <div class="login-form">
        <h1>Вход в чат</h1>
        <form method="post">
            <input type="text" name="username" placeholder="Введите ваше имя" required>
            <button type="submit">Войти</button>
        </form>
    </div>
</body>
</html>
''')

with open('templates/chat.html', 'w', encoding='utf-8') as f:
    f.write('''
<!DOCTYPE html>
<html>
<head>
    <title>Чат</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }
        .chat-header {
            background-color: #4CAF50;
            color: white;
            padding: 10px 20px;
            border-radius: 5px 5px 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .logout-btn {
            background-color: transparent;
            color: white;
            border: 1px solid white;
            padding: 5px 10px;
            border-radius: 3px;
            cursor: pointer;
            text-decoration: none;
        }
        .chat-messages {
            background-color: white;
            padding: 20px;
            height: 400px;
            overflow-y: auto;
            border-left: 1px solid #ddd;
            border-right: 1px solid #ddd;
        }
        .message {
            margin-bottom: 15px;
            padding: 10px;
            border-radius: 5px;
        }
        .message .header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 5px;
            font-size: 0.8em;
        }
        .message .username {
            font-weight: bold;
            color: #4CAF50;
        }
        .message.bot .username {
            color: #2196F3;
        }
        .message .timestamp {
            color: #999;
        }
        .message .content {
            background-color: #f9f9f9;
            padding: 10px;
            border-radius: 3px;
        }
        .chat-form {
            display: flex;
            padding: 10px;
            background-color: #eee;
            border-radius: 0 0 5px 5px;
        }
        .chat-form input[type="text"] {
            flex-grow: 1;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 3px;
            margin-right: 10px;
        }
        .chat-form button {
            padding: 10px 20px;
            background-color: #4CAF50;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
        }
        .chat-form button:hover {
            background-color: #45a049;
        }
        /* Автоматическое обновление страницы */
        <meta http-equiv="refresh" content="5">
    </style>
</head>
<body>
    <div class="container">
        <div class="chat-header">
            <h1>Чат: {{ session['username'] }}</h1>
            <a href="{{ url_for('logout') }}" class="logout-btn">Выйти</a>
        </div>
        <div class="chat-messages">
            {% if not messages %}
                <p>Пока нет сообщений. Будьте первым!</p>
            {% endif %}
            {% for message in messages %}
                <div class="message {% if message['username'] == 'Чат-бот' %}bot{% endif %}">
                    <div class="header">
                        <span class="username">{{ message['username'] }}</span>
                        <span class="timestamp">{{ message['timestamp'] }}</span>
                    </div>
                    <div class="content">{{ message['content'] }}</div>
                </div>
            {% endfor %}
        </div>
        <form class="chat-form" method="post" action="{{ url_for('send') }}">
            <input type="text" name="message" placeholder="Введите сообщение..." required autofocus>
            <button type="submit">Отправить</button>
        </form>
    </div>
    <script>
        // Прокрутка вниз при загрузке страницы
        window.onload = function() {
            var chatMessages = document.querySelector('.chat-messages');
            chatMessages.scrollTop = chatMessages.scrollHeight;
        };
    </script>
</body>
</html>
''')

if __name__ == '__main__':
    app.run(debug=True)