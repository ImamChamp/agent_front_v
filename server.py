from flask import Flask, request, jsonify
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Optional

from flask_cors import CORS

# 1) Импорт Jira и Confluence, если нужно создавать задачи:
from jira_ap import create_jira_issue, fetch_confluence_context
from atlassian import Confluence
from jira import JIRA

# 2) Импорт GigaChat и LangChain:
from langchain_community.chat_models.gigachat import GigaChat
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from mcp.server.fastmcp import FastMCP

# -----------------------------------------------------------------------------
# Заполните свои учётные данные:
CONFLUENCE_URL = "https://queerxdisasster.atlassian.net/wiki"
CONFLUENCE_USERNAME = "7germania7@gmail.com"
CONFLUENCE_API_TOKEN = "ATATT3xFfGF0OlN3ffQp5CJFvw1pniUbJZg24xG-AxSiumNeMCE-W-CT_cKBiBPMTbgKrpyW0-kUoSnl3AOsaqWphA8p8sAnDs2ZdJpAykwVfmufcln2HcwhZDiMNK1rM0s02BJM9W__KaAqtRooyI6-HVdfN6qh-A959zxsCKYSMmLkPVQuAzQ=EC95BE24"

JIRA_SERVER = "https://queerxdisasster.atlassian.net"
JIRA_EMAIL = "7germania7@gmail.com"
JIRA_API_TOKEN = "ATATT3xFfGF0OlN3ffQp5CJFvw1pniUbJZg24xG-AxSiumNeMCE-W-CT_cKBiBPMTbgKrpyW0-kUoSnl3AOsaqWphA8p8sAnDs2ZdJpAykwVfmufcln2HcwhZDiMNK1rM0s02BJM9W__KaAqtRooyI6-HVdfN6qh-A959zxsCKYSMmLkPVQuAzQ=EC95BE24"

# Инициализация клиентов Confluence и Jira (если требуется):
confluence = Confluence(
    url=CONFLUENCE_URL,
    username=CONFLUENCE_USERNAME,
    password=CONFLUENCE_API_TOKEN
)
jira_options = {"server": JIRA_SERVER}
jira_client = JIRA(options=jira_options, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))

# -----------------------------------------------------------------------------
# Инициализация GigaChat-модели:
model = GigaChat(
    credentials="NDk1MzkxZDYtYjQyYy00NjRiLTlkOWItZGY4MGY3MWY1MTg2Ojc5ZTllNWNlLWFmY2QtNDgwOC1iZjIxLWMwYmUyZjk0YWFmZA==",
    scope="GIGACHAT_API_PERS",
    model="GigaChat",
    verify_ssl_certs=False,
)

# Создаём FastMCP (для совместимости с LangGraph):
mcp = FastMCP(
    "gigachat",
    dependencies=[
        "langchain-community",
        "langchain-core",
        "langgraph",
        "jira"
    ],
)

parser = StrOutputParser()

# -----------------------------------------------------------------------------
# Создаём граф (LangGraph)
workflow = StateGraph(state_schema=MessagesState)

def call_model(state: MessagesState):
    response = model.invoke(state["messages"])
    return {"messages": response}

workflow.add_edge(START, "model")
workflow.add_node("model", call_model)

memory = MemorySaver()
graph_app = workflow.compile(checkpointer=memory)
config = {"configurable": {"thread_id": "abc123"}}

# -----------------------------------------------------------------------------
# Храним историю сообщений для каждой сессии
conversation_history = {}

# Системный промпт (чтобы модель знала, что делать при декомпозиции):
prompt_for_decompose = """
Ты эксперт по декомпозиции сложных задач в методологии Agile. Твоя задача - разбивать комплексные требования в виде {task} на атомарные пользовательские истории (user stories), оценивать их сложность в story points и предлагать оптимальные сроки выполнения.
В первую очередь проанализируй запрос от пользователя, если он не указал планируемую дату завершения задачи ОБЯЗАТЕЛЬНО задай вопрос про это.
Во-вторых, ты должен знать количество сотрудников, которые будут работать над этой задачей и их роли в команде, если пользователь не указал их, то ОБЯЗАТЕЛЬНО уточни этот момент
не используя инструменты Marcdown, разбей минимум на 5 задач, по каждой задаче на отдельной строке жду описание, тип и название задачи
"""

@dataclass
class ChatResponse:
    message: str
    timestamp: float = datetime.now(timezone.utc).timestamp()

# -----------------------------------------------------------------------------
# Вспомогательная функция: если в тексте есть ссылки на Confluence, тянем контент
def get_confluence_context_if_needed(text: str) -> str:
    words = text.split()
    confluence_content = ""
    for w in words:
        if w.startswith("http"):
            try:
                extra = fetch_confluence_context(confluence, w)
                confluence_content += str(extra) + "\n"
            except Exception as e:
                confluence_content += f"Ошибка чтения Confluence: {e}\n"
    return confluence_content

# -----------------------------------------------------------------------------
# Основная функция для декомпозиции
def decompose_task(task: str, session_id: str = "default") -> str:
    # Проверяем, есть ли ссылки, подгружаем
    conf_context = get_confluence_context_if_needed(task)

    if session_id not in conversation_history:
        conversation_history[session_id] = []
        if prompt_for_decompose:
            conversation_history[session_id].append(
                SystemMessage(content=prompt_for_decompose)
            )

    # Добавляем сообщение пользователя
    conversation_history[session_id].append(HumanMessage(content=task + "\n" + conf_context))

    # Запускаем модель:
    try:
        input_messages = conversation_history[session_id]
        config = {"configurable": {"thread_id": session_id}}
        output = graph_app.invoke({"messages": input_messages}, config)
        ai_response = output["messages"][-1].content
        conversation_history[session_id] = output["messages"]
    except Exception as e:
        return f"Ошибка при обработке запроса: {str(e)}"

    # Пытаемся автоматически создать задачи в Jira
    try:
        lines = ai_response.split('\n')
        tsk_names = [ln.lstrip("- **Название задачи**: ").strip() for ln in lines if 'Название' in ln]
        tsk_types = [ln.lstrip("- **Тип задачи**: ").strip() for ln in lines if 'Тип' in ln]
        tsk_desc = [ln.lstrip("- **Описание задачи**: ").strip() for ln in lines if 'Описание' in ln]

        user_stories = []
        for i in range(len(tsk_names)):
            # Определяем тип задачи (Task/Epic)
            if i < len(tsk_types) and "Task" in tsk_types[i]:
                new_issue_type = "Task"
            else:
                new_issue_type = "Epic"

            # Описание подхватываем, если есть
            if i < len(tsk_desc):
                tdesc = tsk_desc[i]
            else:
                tdesc = "Описание не найдено"

            jira_dict = {
                "project": {"key": "KAN"},  # ваш ключ проекта
                "summary": tsk_names[i],
                "description": tdesc,
                "issuetype": {"name": new_issue_type},
            }
            user_stories.append(jira_dict)

        for us in user_stories:
            issue_key = create_jira_issue(jira_client, us)
            print(f"Создана задача в Jira: {issue_key}")

    except Exception as je:
        print(f"Ошибка при создании задач в Jira: {je}")

    return ai_response

# -----------------------------------------------------------------------------
# Flask-приложение (без фронта, только API):
app = Flask(__name__)
CORS(app)
app.secret_key = os.urandom(24)

@app.route("/api/decompose", methods=["POST"])
def api_decompose():
    # Пример: body = {"task": "...", "session_id": "..."}
    data = request.get_json()
    if not data or "task" not in data:
        return jsonify({"error": "Параметр 'task' обязателен"}), 400

    task = data["task"]
    session_id = data.get("session_id", "default")
    result = decompose_task(task, session_id)
    return jsonify({"response": result}), 200

@app.route("/api/clear_history", methods=["POST"])
def api_clear_history():
    data = request.get_json()
    session_id = data.get("session_id", "default")
    conversation_history[session_id] = []
    return jsonify({"result": f"История сессии '{session_id}' очищена"}), 200

@app.route("/api/get_history", methods=["POST"])
def api_get_history():
    data = request.get_json()
    session_id = data.get("session_id", "default")
    max_messages = int(data.get("max_messages", 10))

    if session_id not in conversation_history:
        return jsonify({"history": []}), 200

    all_msgs = conversation_history[session_id]
    last_msgs = all_msgs[-max_messages:]
    formatted = []
    for m in last_msgs:
        if isinstance(m, HumanMessage):
            formatted.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            formatted.append({"role": "assistant", "content": m.content})
        elif isinstance(m, SystemMessage):
            formatted.append({"role": "system", "content": m.content})

    return jsonify({"history": formatted}), 200

if __name__ == "__main__":
    # Запускаем Flask. Если хотите другой порт, сделайте app.run(port=3001)
    app.run(debug=True)
